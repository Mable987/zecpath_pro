from django.urls import path
from core.views import *

urlpatterns = [
    path("api/home/", home_api, name="home_api"),
    path("api/jobs/", JobListAPIView.as_view(), name="job_list_api"),
    path("api/jobs/create/", JobCreateAPIView.as_view(), name="job_create_api"),
    path("api/test/", UserTestAPIView.as_view(), name="user_test_api"),
    path("api/signup/", SignupView.as_view(), name="signup_api"),
    path("api/login/", LoginView.as_view(), name="login_api"),
    path("api/logout/", LogoutView.as_view(), name="logout_api"),
    path("api/refresh/", RefreshTokenView.as_view(), name="refresh_api"),
    path("api/protected/", ProtectedPingView.as_view(), name="protected_api"),
]