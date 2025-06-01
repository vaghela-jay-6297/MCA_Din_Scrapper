from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from .models import DINRequest, EmailStatus
from .utils import validate_din_range, validate_din_csv, xml_to_json, PARAMETERS, find_key_value
import csv
import os
import time
import random
import aiohttp
import asyncio
import json
from din_project.celery import app
from celery import group, chord
from celery.exceptions import Ignore
import glob
from datetime import datetime, timedelta

async def get_din_data_async(din, session, max_retries=3, retry_delay=2):
    """
    Fetch DIN data from MCA API asynchronously with retries.
    Returns a list with DIN, status, and data (or empty fields if failed).
    """
    url = "http://www.mca.gov.in/FOServicesWeb/NCAPrefillService"
    headers = {
        "Accept": "*/*",
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "",
        "User-Agent": "Mozilla/3.0 (compatible; Spider 1.0; Windows)",
        "Host": "www.mca.gov.in",
        "Connection": "Keep-Alive",
        "Cache-Control": "no-cache"
    }
    xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
    <soap:Envelope
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/"
        xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
        <soap:Body>
            <tns:getNCAPrefillDetails
                xmlns:tns="http://ncaprifill.org/wsdl">
                <NCAPrefillProcessorDTO>
                    <callID>DIN</callID>
                    <din>{din}</din>
                    <formID>ZI03</formID>
                    <sid>NCA</sid>
                </NCAPrefillProcessorDTO>
            </tns:getNCAPrefillDetails>
        </soap:Body>
    </soap:Envelope>"""
    
    for attempt in range(max_retries + 1):
        try:
            async with session.post(url, headers=headers, data=xml_payload, timeout=120) as response:
                if response.status == 200:
                    text = await response.text()
                    json_response = xml_to_json(text)
                    response_data = json.loads(json_response)
                    row_data = [find_key_value(response_data, param) for param in PARAMETERS]
                    return [din, "success"] + row_data
                else:
                    if response.status >= 500 and attempt < max_retries:
                        sleep_time = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                        await asyncio.sleep(sleep_time)
                    else:
                        status = f"failed: server error {response.status}" if response.status >= 500 else \
                                 "failed: DIN not found (404)" if response.status == 404 else \
                                 f"failed: status {response.status}"
                        return [din, status] + [""] * len(PARAMETERS)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < max_retries:
                sleep_time = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(sleep_time)
            else:
                return [din, f"failed: request exception {str(e)}"] + [""] * len(PARAMETERS)
    return [din, "failed: max retries exceeded"] + [""] * len(PARAMETERS)

@app.task(bind=True)
def process_din_batch(self, din_batch, din_request_id):
    din_request = DINRequest.objects.get(id=din_request_id)
    
    if din_request.is_cancelled:
        self.request.callbacks = None
        raise Ignore("Task cancelled")
    
    async def fetch_all_dins():
        async with aiohttp.ClientSession() as session:
            tasks = [get_din_data_async(din, session) for din in din_batch]
            return await asyncio.gather(*tasks, return_exceptions=True)
    
    # Run async DIN fetches
    loop = asyncio.get_event_loop()
    data = loop.run_until_complete(fetch_all_dins())
    
    # Update progress
    din_request.refresh_from_db()
    if din_request.is_cancelled:
        self.request.callbacks = None
        raise Ignore("Task cancelled")
    
    batch_size = len(din_batch)
    total_dins = (din_request.end_range - din_request.start_range + 1) if din_request.start_range else len(din_batch)
    progress_increment = (batch_size / total_dins) * 100
    din_request.progress = min(din_request.progress + progress_increment, 100)
    din_request.save(update_fields=['progress'])
    
    time.sleep(0.5)  # Respect API rate limits between batches
    
    return data

@app.task(bind=True)
def finalize_din_task(self, batch_results, din_request_id):
    try:
        din_request = DINRequest.objects.get(id=din_request_id)
        
        if din_request.is_cancelled:
            self.request.callbacks = None
            din_request.status = 'cancelled'
            din_request.save()
            email_status = din_request.email_status
            email_status.status = 'cancelled'
            email_status.save()
            raise Ignore("Task cancelled")
        
        output_dir = os.path.join(settings.MEDIA_ROOT, 'outputs')
        os.makedirs(output_dir, exist_ok=True)
        output_csv_path = os.path.join(output_dir, f'din_{din_request.id}.csv')

        # Write all batch results to CSV
        with open(output_csv_path, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            for batch_result in batch_results:
                for row in batch_result:
                    writer.writerow(row)

        din_request.output_csv = os.path.join('outputs', f'din_{din_request.id}.csv')
        din_request.status = 'completed'
        din_request.completed_at = timezone.now()
        din_request.progress = 100
        din_request.save()

        try:
            email = EmailMessage(
                subject=f'DIN Processing Complete - Request {din_request.id}',
                body=f'Your DIN request has been processed. See attached CSV.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[din_request.user.email],
            )
            email.attach_file(output_csv_path)
            email.send()
            email_status = din_request.email_status
            email_status.status = 'sent'
            email_status.sent_at = timezone.now()
            email_status.save()
        except Exception as e:
            email_status = din_request.email_status
            email_status.status = 'failed'
            email_status.error_message = str(e)
            email_status.save()

        return "Processing completed"

    except Ignore:
        raise
    except Exception as e:
        din_request = DINRequest.objects.get(id=din_request_id)
        din_request.status = 'failed'
        din_request.save()
        email_status = din_request.email_status
        email_status.status = 'failed'
        email_status.error_message = str(e)
        email_status.save()
        raise e

@app.task(bind=True)
def process_din_task(self, din_request_id):
    try:
        din_request = DINRequest.objects.get(id=din_request_id)
        din_request.status = 'processing'
        din_request.save()

        if din_request.is_cancelled:
            self.request.callbacks = None
            din_request.status = 'cancelled'
            din_request.save()
            email_status = din_request.email_status
            email_status.status = 'cancelled'
            email_status.save()
            raise Ignore("Task cancelled")

        # Get DIN list from din_request
        if din_request.din_list:
            din_list = json.loads(din_request.din_list)
            is_valid, error_msg = True, ""
        elif din_request.input_csv:
            file_path = os.path.join(settings.MEDIA_ROOT, din_request.input_csv.name)
            is_valid, error_msg, din_list = validate_din_csv(file_path)
        else:
            start_range = din_request.start_range
            end_range = din_request.end_range
            is_valid, error_msg = validate_din_range(start_range, end_range)
            if is_valid:
                din_list = [f"{din:08d}" for din in range(start_range, end_range + 1)]
            else:
                din_list = []

        if not is_valid:
            din_request.status = 'failed'
            din_request.save()
            email_status = din_request.email_status
            email_status.status = 'failed'
            email_status.error_message = error_msg
            email_status.save()
            return

        batch_size = 10
        batches = [din_list[i:i + batch_size] for i in range(0, len(din_list), batch_size)]

        output_dir = os.path.join(settings.MEDIA_ROOT, 'outputs')
        os.makedirs(output_dir, exist_ok=True)
        output_csv_path = os.path.join(output_dir, f'din_{din_request.id}.csv')

        # Initialize CSV with headers
        with open(output_csv_path, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["DIN", "Status"] + PARAMETERS)

        # Create group of batch tasks and link to finalize task
        task_signatures = [
            process_din_batch.s(batch, din_request_id).set(task_id=f"din_batch_{din_request_id}_{i}")
            for i, batch in enumerate(batches)
        ]
        
        # Use chord to run batches in parallel and trigger finalize_din_task
        chord(group(task_signatures))(finalize_din_task.s(din_request_id=din_request_id).set(task_id=f"finalize_din_task_{din_request_id}"))

    except Ignore:
        raise
    except Exception as e:
        din_request = DINRequest.objects.get(id=din_request_id)
        din_request.status = 'failed'
        din_request.save()
        email_status = din_request.email_status
        email_status.status = 'failed'
        email_status.error_message = str(e)
        email_status.save()
        raise e

@app.task
def cleanup_old_logs():
    """
    Delete log files older than 7 days from the logs directory.
    """
    log_dir = os.path.join(settings.BASE_DIR, 'logs')
    if not os.path.exists(log_dir):
        return
    
    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)
    
    for log_file in glob.glob(os.path.join(log_dir, '*.log')):
        file_mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
        if file_mtime < seven_days_ago:
            try:
                os.remove(log_file)
            except OSError:
                pass