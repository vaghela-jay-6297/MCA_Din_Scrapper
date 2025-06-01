from django.contrib import admin
from .models import DINRequest, EmailStatus
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

class CustomUserAdmin(BaseUserAdmin):
    def has_add_permission(self, request):
        # Disable the ability to add new users
        return False

# Unregister the default UserAdmin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

@admin.register(DINRequest)
class DINRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'start_range', 'end_range', 'status', 'created_at', 'completed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'start_range', 'end_range')

@admin.register(EmailStatus)
class EmailStatusAdmin(admin.ModelAdmin):
    list_display = ('id', 'status')  # Fields to display in the list view
    search_fields = ('din_request',)  # Fields to search
    list_filter = ('status',)  # Fields to filter by