from django.urls import path
from .views import register_user, login_user, logout_user, upload_file, process_files

urlpatterns = [
    path('register/', register_user, name='register'),
    path('login/', login_user, name='login'),
    path('logout/', logout_user, name='logout'),
    path('upload/', upload_file, name='upload_file'),
    path('process/', process_files, name='process_files'),
]
