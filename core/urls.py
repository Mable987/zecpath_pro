from django.urls import path
from core.views import *

urlpatterns = [
    path("api/home/", home_api, name="home_api"),
    path("api/jobs/", JobListAPIView.as_view(), name="job_list_api"),
    path("api/jobs/create/", JobCreateAPIView.as_view(), name="job_create_api"),
    path("api/jobs/<int:pk>/delete/", JobDeleteAPIView.as_view(), name="job_delete_api"),
    path("api/jobs/<int:job_id>/apply/", ApplyToJobAPIView.as_view(), name="job_apply_api"),

    path("api/test/", UserTestAPIView.as_view(), name="user_test_api"),
    path("api/signup/", SignupView.as_view(), name="signup_api"),
    path("api/login/", LoginView.as_view(), name="login_api"),
    path("api/logout/", LogoutView.as_view(), name="logout_api"),
    path("api/refresh/", RefreshTokenView.as_view(), name="refresh_api"),
    path("api/protected/", ProtectedPingView.as_view(), name="protected_api"),
    path("api/admin/users/", AdminUserListAPIView.as_view(), name="admin_user_list_api"),
    path("api/admin/users/<int:user_id>/deactivate/", AdminDeactivateUserAPIView.as_view(), name="admin_deactivate_user_api"),
    path("api/profile/employer/", EmployerProfileView.as_view(), name="employer_profile"),
    path("api/profile/candidate/", CandidateProfileView.as_view(), name="candidate_profile"),
 
    path("api/admin/employers/<int:pk>/", AdminEmployerDetailView.as_view(), name="admin_employer_detail"),
    path("api/admin/employers/<int:pk>/verify/", AdminVerifyEmployerView.as_view(), name="admin_verify_employer"),
    path("api/admin/candidates/<int:pk>/", AdminCandidateDetailView.as_view(), name="admin_candidate_detail"),
]