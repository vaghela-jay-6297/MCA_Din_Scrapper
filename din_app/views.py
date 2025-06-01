from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from .models import DINRequest, EmailStatus
from .utils import validate_din_range, validate_din_csv
from .tasks import process_din_task
import os
from celery import Celery
import csv
import json

app = Celery('din_project')
app.config_from_object('django.conf:settings', namespace='CELERY')

def staff_check(user):
    return user.is_active and user.is_staff and not user.is_superuser

def index(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('admin:index')
        elif staff_check(request.user):
            return redirect('din_form')
    return redirect('login')

def user_login(request):
    if request.user.is_authenticated:
        return redirect('index')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if staff_check(user):
                login(request, user)
                return redirect('din_form')
            elif user.is_superuser:
                messages.error(request, 'Superusers should login through the admin panel.')
            else:
                messages.error(request, 'You do not have permission to access this system.')
        else:
            messages.error(request, 'Invalid username or password.')
            
    return render(request, 'login.html')

@login_required
def user_logout(request):
    logout(request)
    return redirect('login')

@login_required
@user_passes_test(staff_check)
def din_form(request):
    return render(request, 'din_form.html')

@login_required
@user_passes_test(staff_check)
def din_status(request, request_id):
    try:
        din_request = DINRequest.objects.get(id=request_id, user=request.user)
        return render(request, 'din_status.html', {'din_request': din_request})
    except DINRequest.DoesNotExist:
        messages.error(request, 'Request not found or you do not have permission to view it.')
        return redirect('din_form')

@login_required
@user_passes_test(staff_check)
def process_din(request):
    if request.method == 'POST':
        try:
            input_type = request.POST.get('input_type')
            sub_requests = []
            
            if input_type == 'csv':
                if 'input_csv' not in request.FILES:
                    messages.error(request, 'Please upload a CSV file.')
                    return redirect('din_form')
                
                csv_file = request.FILES['input_csv']
                if not csv_file.name.endswith('.csv'):
                    messages.error(request, 'Please upload a valid CSV file.')
                    return redirect('din_form')
                
                # Save CSV file
                din_request = DINRequest.objects.create(
                    user=request.user,
                    status='pending',
                    input_csv=csv_file
                )
                file_path = os.path.join(settings.MEDIA_ROOT, din_request.input_csv.name)
                
                # Validate CSV and get DINs
                is_valid, error_msg, din_numbers = validate_din_csv(file_path)
                if not is_valid:
                    din_request.delete()
                    messages.error(request, error_msg)
                    return redirect('din_form')
                
                # Store DINs in din_request
                din_request.din_list = json.dumps(din_numbers)
                din_request.save()
                
                # Split DINs into chunks of 5000
                chunk_size = 5000
                din_chunks = [din_numbers[i:i + chunk_size] for i in range(0, len(din_numbers), chunk_size)]
                
                for chunk in din_chunks:
                    sub_request = DINRequest.objects.create(
                        user=request.user,
                        status='pending',
                        din_list=json.dumps(chunk)  # Store chunk directly
                    )
                    EmailStatus.objects.create(
                        din_request=sub_request,
                        status='pending'
                    )
                    sub_requests.append(sub_request)
                
                # Delete the original request after splitting
                din_request.delete()
            
            elif input_type == 'range':
                start_range = request.POST.get('start_range')
                end_range = request.POST.get('end_range')
                
                if not (start_range.isdigit() and end_range.isdigit()):
                    messages.error(request, 'Both start and end ranges must be valid positive integers.')
                    return redirect('din_form')
                
                start_range = int(start_range)
                end_range = int(end_range)
                
                is_valid, error_msg = validate_din_range(start_range, end_range)
                if not is_valid:
                    messages.error(request, error_msg)
                    return redirect('din_form')
                
                # Split range into chunks of 5000
                chunk_size = 5000
                ranges = []
                current = start_range
                while current <= end_range:
                    chunk_end = min(current + chunk_size - 1, end_range)
                    ranges.append((current, chunk_end))
                    current = chunk_end + 1
                
                for chunk_start, chunk_end in ranges:
                    din_request = DINRequest.objects.create(
                        user=request.user,
                        status='pending',
                        start_range=chunk_start,
                        end_range=chunk_end
                    )
                    EmailStatus.objects.create(
                        din_request=din_request,
                        status='pending'
                    )
                    sub_requests.append(din_request)
            
            else:
                messages.error(request, 'Invalid input type selected.')
                return redirect('din_form')
            
            # Queue all sub-requests
            for din_request in sub_requests:
                process_din_task.delay(din_request.id)
            
            messages.success(request, f'DIN processing initiated for {len(sub_requests)} sub-requests. You will receive emails when each is complete.')
            return redirect('din_form')
        
        except ValueError:
            for din_request in sub_requests:
                din_request.delete()
            messages.error(request, 'Please enter valid numbers for DIN range.')
            return redirect('din_form')
        except Exception as e:
            for din_request in sub_requests:
                din_request.delete()
            messages.error(request, f'Error processing request: {str(e)}')
            return redirect('din_form')
    
    return redirect('din_form')

@login_required
@user_passes_test(staff_check)
def cancel_din_request(request, request_id):
    try:
        din_request = DINRequest.objects.get(id=request_id, user=request.user)
        if din_request.status == 'processing' and not din_request.is_cancelled:
            din_request.is_cancelled = True
            din_request.status = 'cancelled'
            din_request.save()
            
            email_status = din_request.email_status
            email_status.status = 'cancelled'
            email_status.save()
            
            # Revoke main task
            app.control.revoke(f"process_din_task_{request_id}", terminate=True, 
                             destination=['worker1@localhost', 'worker2@localhost', 
                                        'worker3@localhost', 'worker4@localhost', 
                                        'worker5@localhost'])
            # Revoke finalize task
            app.control.revoke(f"finalize_din_task_{request_id}", terminate=True, 
                             destination=['worker1@localhost', 'worker2@localhost', 
                                        'worker3@localhost', 'worker4@localhost', 
                                        'worker5@localhost'])
            
            # Revoke batch tasks
            max_batches = 10000
            if din_request.input_csv:
                file_path = os.path.join(settings.MEDIA_ROOT, din_request.input_csv.name)
                _, _, din_numbers = validate_din_csv(file_path)
                max_batches = (len(din_numbers) // 10) + 1 if din_numbers else max_batches
            elif din_request.end_range and din_request.start_range:
                max_batches = ((din_request.end_range - din_request.start_range + 1) // 10) + 1
            
            for i in range(max_batches):
                app.control.revoke(f"din_batch_{request_id}_{i}", terminate=True, 
                                 destination=['worker1@localhost', 'worker2@localhost', 
                                            'worker3@localhost', 'worker4@localhost', 
                                            'worker5@localhost'])
                
            messages.success(request, 'DIN request has been cancelled.')
        else:
            messages.error(request, 'Cannot cancel request: It is not in processing state.')
    except DINRequest.DoesNotExist:
        messages.error(request, 'Request not found or you do not have permission to cancel it.')
    return redirect('din_form')

@login_required
@user_passes_test(staff_check)
def get_recent_requests(request):
    recent_requests = DINRequest.objects.filter(user=request.user).order_by('-created_at')[:100]
    data = []
    for req in recent_requests:
        email_status = req.email_status.status if req.email_status else 'Not Initiated'
        data.append({
            'id': req.id,
            'start_range': req.start_range,
            'end_range': req.end_range,
            'input_csv': req.input_csv.url if req.input_csv else None,
            'status': req.status,
            'progress': req.progress,
            'email_status': email_status,
            'output_csv': req.output_csv.url if req.output_csv else None,
            'is_cancelled': req.is_cancelled
        })
    return JsonResponse(data, safe=False)