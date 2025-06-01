from django.db import models
from django.contrib.auth.models import User
import json

class DINRequest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    start_range = models.IntegerField(null=True, blank=True)
    end_range = models.IntegerField(null=True, blank=True)
    input_csv = models.FileField(upload_to='inputs/', null=True, blank=True)
    din_list = models.TextField(null=True, blank=True)  # Store DINs as JSON string
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default='pending')
    progress = models.FloatField(default=0)
    output_csv = models.FileField(upload_to='outputs/', null=True, blank=True)
    is_cancelled = models.BooleanField(default=False)

    def __str__(self):
        return f"DIN Request {self.id} by {self.user.username}"

class EmailStatus(models.Model):
    din_request = models.OneToOneField(DINRequest, on_delete=models.CASCADE, related_name='email_status')
    status = models.CharField(max_length=20, default='pending')
    error_message = models.TextField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Email Status for DIN Request {self.din_request.id}"