from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('din-form/', views.din_form, name='din_form'),
    path('process-din/', views.process_din, name='process_din'),
    path('din-status/<int:request_id>/', views.din_status, name='din_status'),
    path('get-recent-requests/', views.get_recent_requests, name='get_recent_requests'),
    path('cancel-din/<int:request_id>/', views.cancel_din_request, name='cancel_din'),
]