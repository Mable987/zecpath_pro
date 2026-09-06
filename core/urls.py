from django.urls import path
from core.views import *

urlpatterns = [
    path("api/home/", home_api, name="home_api"),
    path("api/jobs/", JobListAPIView.as_view(), name="job_list_api"),
    path("api/jobs/create/", JobCreateAPIView.as_view(), name="job_create_api"),
    path("api/test/", UserTestAPIView.as_view(), name="user_test_api"),
]