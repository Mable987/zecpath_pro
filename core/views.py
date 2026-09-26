from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from rest_framework.response import Response
from core.serializers import *
from rest_framework.views import APIView
from core.pagination import JobFeedCursorPagination
from core.services.auth_service import register_user
from .models import *
from rest_framework import status, permissions, generics
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.permissions import IsAuthenticated
from .permissions import IsAdmin, IsEmployer, IsCandidate, IsOwnerEmployer
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.exceptions import ValidationError as DjangoValidationError
from .validators import validate_resume_file
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .filters import JobFilter, ApplicationFilter, UserFilter
import shutil
from django.core.files.base import ContentFile
from django.db import transaction
from rest_framework.exceptions import NotFound
from .workflow import validate_transition, ACTION_TO_STATUS, STATUS_SHORTLISTED, STATUS_INTERVIEW_SCHEDULED, STATUS_SELECTED
from django.db.models import Q, Count    
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import TruncDate
from .resume_parser import extract_text, clean_text


# Create your views here.
def home_api(request): 
    return JsonResponse({"message": "Hello Zecpath Backend"})

class JobListAPIView(generics.ListAPIView):
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = JobFilter
    search_fields = ["title", "description"]
    ordering_fields = ["posted_at", "title"]
    ordering = ["-posted_at"]  # default: newest first
 
    def get_queryset(self):
        return Job.objects.select_related("employer").all()
    
class ApplicationListAPIView(generics.ListAPIView):
    """
    GET /api/applications/?status=pending&ordering=-applied_at
 
    - Candidates see only their OWN applications (never anyone else's —
      enforced in get_queryset, not just by a permission check).
    - Admins see ALL applications, filterable by status/date.
    - N+1 prevention: select_related("job", "candidate") — without
      this, serializing each application's job title and candidate name
      would fire two extra queries PER ROW (2 x page_size queries just
      for a single page of results).
    """
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ApplicationFilter
    ordering_fields = ["applied_at"]
    ordering = ["-applied_at"]
 
    def get_queryset(self):
        base = Application.objects.select_related("job", "job__employer", "candidate")
        user = self.request.user
 
        if user.role == "admin":
            return base.all()
        elif user.role == "candidate":
            return base.filter(candidate__user=user)
        else:
            # Employers see applications to THEIR jobs only
            return base.filter(job__employer__user=user)

class ApplicationDetailAPIView(generics.RetrieveAPIView):
    """
    GET /api/applications/<pk>/
 
    Single-application lookup with the SAME ownership scoping as
    ApplicationListAPIView.get_queryset — a candidate, employer, or
    admin can only ever retrieve an application their role is allowed
    to see. Requesting an application outside that scope returns 404
    (via get_object_or_404 on an already-filtered queryset), not 403 —
    this avoids confirming to an unauthorized user that a given
    application id even exists.
    """
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]
 
    def get_queryset(self):
        base = Application.objects.select_related("job", "job__employer", "candidate")
        user = self.request.user
 
        if user.role == "admin":
            return base.all()
        elif user.role == "candidate":
            return base.filter(candidate__user=user)
        else:
            return base.filter(job__employer__user=user)
        
    
class JobCreateAPIView(generics.CreateAPIView):
    """Only Employers can create jobs. employer is always taken from
    the authenticated user's own profile, never from client input."""
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmployer]
 
    def perform_create(self, serializer):
        employer = Employer.objects.get(user=self.request.user, is_deleted=False)
        serializer.save(employer=employer)
 
 
class JobUpdateAPIView(generics.UpdateAPIView):
    """
    PATCH/PUT a job's fields. Ownership is enforced at the object level
    (IsOwnerEmployer) — an Employer can only edit THEIR OWN job, not
    just any job because they happen to hold the Employer role.
    """
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmployer, IsOwnerEmployer]
 
 
class JobStatusToggleAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsEmployer, IsOwnerEmployer]
 
    def _get_job_and_check_ownership(self, request, pk):
        job = get_object_or_404(Job, pk=pk)
        self.check_object_permissions(request, job)  # applies IsOwnerEmployer manually
        return job
 
    def post(self, request, pk, action):
        job = self._get_job_and_check_ownership(request, pk)
 
        if action == "activate":
            job.status = "active"
        elif action == "deactivate":
            job.status = "inactive"
        elif action == "close":
            job.status = "closed"    
        else:
            return Response({"detail": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)
 
        job.save(update_fields=["status", "updated_at"])
        return Response({"id": job.id, "title": job.title, "status": job.status})
 
 
class JobDeleteAPIView(generics.DestroyAPIView):
    """
    Only the Employer who OWNS a job can delete it — demonstrates
    object-level permission, not just role-level.
    """
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [IsAuthenticated, IsEmployer, IsOwnerEmployer]


class ApplyToJobAPIView(APIView):
    """
    POST /api/jobs/<job_id>/apply/
 
    Only Candidates can apply (role check). Ownership is implicit —
    the application is always created FOR the logged-in candidate,
    never a candidate id supplied by the client.
    """
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def post(self, request, job_id):
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)
 
        # Job status check: can't apply to a job that isn't active
        # (e.g. the employer deactivated or closed it) — checked before
        # duplicate check so the error message is the most relevant one.
        if job.status != "active":
            return Response(
                {"detail": f"This job is currently '{job.status}' and is not accepting applications."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        candidate = Candidate.objects.get(user=request.user, is_deleted=False)
 
        # Duplicate prevention: checked in application logic (fast,
        # friendly error message) AND enforced by the model's
        # unique_together as a hard backstop against race conditions.
        if Application.objects.filter(candidate=candidate, job=job).exists():
            return Response(
                {"detail": "You have already applied to this job."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        if not candidate.resume:
            return Response(
                {"detail": "Upload a resume to your profile before applying."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        application = Application.objects.create(candidate=candidate, job=job)
 
        # Resume binding: copy the candidate's CURRENT resume file into
        # a snapshot tied to this specific application, so it's frozen
        # at the moment of applying (see model docstring for why).
        candidate.resume.open("rb")
        snapshot_name = os.path.basename(candidate.resume.name)
        application.resume_snapshot.save(
            snapshot_name, ContentFile(candidate.resume.read()), save=True
        )
        candidate.resume.close()
 
        return Response(
            {
                "id": application.id,
                "job": job.title,
                "status": application.status,
                "resume_snapshot": application.resume_snapshot.url,
                "applied_at": application.applied_at,
            },
            status=status.HTTP_201_CREATED,
        )
 
 
class AdminUserListAPIView(generics.ListAPIView):
    """
    GET /api/admin/users/?role=candidate&is_active=true&search=nico
 
    - Filtering by role/is_active via UserFilter.
    - search_fields lets an Admin find a user by partial email match.
    - No select_related needed here since UserSerializer doesn't touch
      any foreign-key relations.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = UserFilter
    search_fields = ["email"]
    ordering_fields = ["created_at", "email"]
    ordering = ["-created_at"]
    queryset = User.objects.all()
 
 
class AdminDeactivateUserAPIView(APIView):
    """Admin-only: deactivate any user account."""
    permission_classes = [IsAuthenticated, IsAdmin]
 
    def post(self, request, user_id):
        from .models import User
        try:
            target = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
 
        target.is_active = False
        target.save(update_fields=["is_active"])
        log_admin_action(request.user, "deactivate_user", "User", target.id, target.email)
        return Response({"detail": f"{target.email} has been deactivated."})
    
class UserTestAPIView(APIView):
    def get(self, request):
        users = User.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)       

class SignupView(APIView):
    permission_classes = [permissions.AllowAny]
 
    def post(self, request):
        data = request.data
        user = register_user(
            email=data.get("email", ""),
            password=data.get("password", ""),
            phone=data.get("phone", ""),
            role=data.get("role", "candidate"),
        )
        return Response(
            {"id": user.id, "email": user.email, "role": user.role},
            status=status.HTTP_201_CREATED,
        )
 
 
class LoginView(TokenObtainPairView):
    """
    POST {"email": ..., "password": ...} -> {"access": ..., "refresh": ...}
    SimpleJWT handles password checking internally via authenticate().
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer
 
 
class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()  # requires token_blacklist app — invalidates the refresh token
            return Response(status=status.HTTP_205_RESET_CONTENT)
        except (KeyError, TokenError):
            return Response(
                {"detail": "A valid refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
 
class RefreshTokenView(TokenRefreshView):
    """Plain pass-through to SimpleJWT's refresh view — kept here for a clear URL name."""
    permission_classes = [permissions.AllowAny]
 
 
class ProtectedPingView(APIView):
    """Sample protected endpoint — only reachable with a valid access token."""
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request):
        return Response({
            "message": f"Hello {request.user.email}, you are authenticated!",
            "role": request.user.role,
        })   

class EmployerProfileView(APIView):
    """GET / PUT / PATCH / DELETE the logged-in Employer's own profile."""
    permission_classes = [permissions.IsAuthenticated, IsEmployer]
 
    def get_object(self, request):
        return get_object_or_404(Employer, user=request.user, is_deleted=False)
 
    def get(self, request):
        profile = self.get_object(request)
        return Response(EmployerProfileSerializer(profile).data)
 
    def put(self, request):
        profile = self.get_object(request)
        serializer = EmployerProfileSerializer(profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
 
    def patch(self, request):
        profile = self.get_object(request)
        serializer = EmployerProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
 
    def delete(self, request):
        profile = self.get_object(request)
        profile.soft_delete()
        return Response({"detail": "Employer profile deactivated."}, status=status.HTTP_204_NO_CONTENT)
 
 
# ---------- Candidate: self profile ----------
 
class CandidateProfileView(APIView):
    """GET / PUT / PATCH / DELETE the logged-in Candidate's own profile."""
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def get_object(self, request):
        return get_object_or_404(Candidate, user=request.user, is_deleted=False)
 
    def get(self, request):
        profile = self.get_object(request)
        return Response(CandidateProfileSerializer(profile).data)
 
    def put(self, request):
        profile = self.get_object(request)
        serializer = CandidateProfileSerializer(profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
 
    def patch(self, request):
        profile = self.get_object(request)
        serializer = CandidateProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
 
    def delete(self, request):
        profile = self.get_object(request)
        profile.soft_delete()
        return Response({"detail": "Candidate profile deactivated."}, status=status.HTTP_204_NO_CONTENT)
 
 
# ---------- Admin override: any profile by id ----------
 
class AdminEmployerDetailView(APIView):
    """Admin-only: view/update/soft-delete ANY Employer profile by id."""
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    def get(self, request, pk):
        profile = get_object_or_404(Employer, pk=pk)
        return Response(EmployerProfileSerializer(profile).data)
 
    def patch(self, request, pk):
        profile = get_object_or_404(Employer, pk=pk)
        serializer = EmployerProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_admin_action(request.user, "update_employer", "Employer", profile.id, str(request.data))
        return Response(serializer.data)
 
    def delete(self, request, pk):
        profile = get_object_or_404(Employer, pk=pk)
        profile.soft_delete()
        log_admin_action(request.user, "delete_employer", "Employer", profile.id, profile.company_name)
        return Response({"detail": "Employer profile deactivated by admin."}, status=status.HTTP_204_NO_CONTENT)
 
 
class AdminVerifyEmployerView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    def post(self, request, pk):
        profile = get_object_or_404(Employer, pk=pk)
        profile.is_verified = True
        profile.save(update_fields=["is_verified"])
        log_admin_action(request.user, "verify_employer", "Employer", profile.id, profile.company_name)
        return Response({"detail": f"{profile.company_name} is now verified."})
 
 
class AdminCandidateDetailView(APIView):
    """Admin-only: view/update/soft-delete ANY Candidate profile by id."""
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    def get(self, request, pk):
        profile = get_object_or_404(Candidate, pk=pk)
        return Response(CandidateProfileSerializer(profile).data)
 
    def patch(self, request, pk):
        profile = get_object_or_404(Candidate, pk=pk)
        serializer = CandidateProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_admin_action(request.user, "update_candidate", "Candidate", profile.id, str(request.data))
        return Response(serializer.data)
 
    def delete(self, request, pk):
        profile = get_object_or_404(Candidate, pk=pk)
        profile.soft_delete()
        log_admin_action(request.user, "delete_candidate", "Candidate", profile.id, profile.full_name)
        return Response({"detail": "Candidate profile deactivated by admin."}, status=status.HTTP_204_NO_CONTENT) 
    
class ResumeUploadView(APIView):
    """
    POST a multipart/form-data request with a 'resume' file field to
    upload or REPLACE the logged-in Candidate's resume.
 
    Replacement behavior: if a resume already exists, the old file is
    deleted from disk before the new one is saved — otherwise old
    resume files would silently accumulate on disk forever, one per
    upload, even though only the latest is ever referenced.
    """
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
    parser_classes = [MultiPartParser, FormParser]
 
    def post(self, request):
        candidate = Candidate.objects.get(user=request.user, is_deleted=False)
        uploaded_file = request.FILES.get("resume")
 
        if not uploaded_file:
            return Response(
                {"detail": "No file provided. Attach a file under the 'resume' field."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        try:
            validate_resume_file(uploaded_file)
        except DjangoValidationError as e:
            return Response({"detail": e.messages}, status=status.HTTP_400_BAD_REQUEST)
 
        # Replacement: remove the old file from disk before attaching the new one
        if candidate.resume:
            candidate.resume.delete(save=False)
 
        candidate.resume = uploaded_file
        candidate.save(update_fields=["resume", "updated_at"])
 
        return Response(
            {
                "detail": "Resume uploaded successfully.",
                "resume_url": candidate.resume.url,
                "file_name": candidate.resume.name,
            },
            status=status.HTTP_200_OK,
        )
 
    def delete(self, request):
        """Remove the resume entirely (no replacement)."""
        candidate = Candidate.objects.get(user=request.user, is_deleted=False)
 
        if not candidate.resume:
            return Response({"detail": "No resume on file."}, status=status.HTTP_404_NOT_FOUND)
 
        candidate.resume.delete(save=False)
        candidate.resume = None
        candidate.save(update_fields=["resume", "updated_at"])
        return Response({"detail": "Resume removed."}, status=status.HTTP_204_NO_CONTENT)     
    
class PublicJobListAPIView(generics.ListAPIView):
    """
    GET /api/public/jobs/?skills=python&location=remote&job_type=full_time
        &min_salary=40000&max_salary=90000&search=django&ordering=-posted_at
 
    All active jobs, publicly browsable (no login required) — this is
    the core marketplace discovery endpoint. Cursor-paginated for
    infinite-scroll on a candidate-facing feed.
    """
    serializer_class = JobSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = JobFeedCursorPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = JobFilter
    search_fields = ["title", "description", "skills"]
    ordering_fields = ["posted_at", "salary_min", "salary_max"]
    ordering = ["-posted_at"]
 
    def get_queryset(self):
        # select_related("employer") — same N+1 prevention as Day 14,
        # since JobSerializer includes the employer id/relation.
        return Job.objects.select_related("employer").filter(status="active")
 
 
class FeaturedJobListAPIView(generics.ListAPIView):
    """
    GET /api/public/jobs/featured/
 
    A smaller, curated list — active AND featured jobs. Uses regular
    page-number pagination (Day 14's default) rather than cursor,
    since a "featured" section is typically a short, static-ish list
    rather than an infinite feed.
    """
    serializer_class = JobSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = JobFilter
    search_fields = ["title", "description", "skills"]
 
    def get_queryset(self):
        return Job.objects.select_related("employer").filter(
            status="active", featured=True
        )
 
 
class LatestJobListAPIView(generics.ListAPIView):
    serializer_class = JobSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None 
 
    def get_queryset(self):
        return Job.objects.select_related("employer").filter(
            status="active"
        ).order_by("-posted_at")[:10]          

class EmployerApplicationStatusAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request, pk, action):
        application = get_object_or_404(
            Application.objects.select_related("job", "job__employer", "candidate"),
            pk=pk,
        )
 
        user = request.user
        is_owner_employer = (
            user.role == "employer" and application.job.employer.user_id == user.id
        )
        is_admin = user.role == "admin"
        if not (is_owner_employer or is_admin):
            raise NotFound()
 
        target_status = ACTION_TO_STATUS.get(action)
        if target_status is None:
            return Response(
                {"detail": f"Invalid action '{action}'. Allowed: {list(ACTION_TO_STATUS)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        try:
            validate_transition(application.status, target_status)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 
        with transaction.atomic():
            ApplicationStatusLog.objects.create(
                application=application,
                from_status=application.status,
                to_status=target_status,
                changed_by=user,
            )
            Notification.objects.create(
                recipient=application.candidate.user,
                application=application,
                message=(
                    f"Your application for '{application.job.title}' is now "
                    f"'{target_status}'."
                ),
            )
            application.status = target_status
            application.save(update_fields=["status"])
 
        return Response(
            {
                "id": application.id,
                "job": application.job.title,
                "candidate": application.candidate.full_name,
                "status": application.status,
            },
            status=status.HTTP_200_OK,
        )
 
 
class ApplicationStatusHistoryAPIView(generics.ListAPIView):
    """
    GET /api/applications/<id>/history/
 
    Full audit trail for one application, newest first. Same three-way
    ownership rule as ApplicationDetailAPIView: the candidate who owns
    it, the employer who owns the job, or Admin.
    """
    serializer_class = ApplicationStatusLogSerializer
    permission_classes = [permissions.IsAuthenticated]
 
    def get_queryset(self):
        application = get_object_or_404(
            Application.objects.select_related("job__employer", "candidate"),
            pk=self.kwargs["pk"],
        )
        user = self.request.user
 
        is_owner_candidate = application.candidate.user_id == user.id
        is_owner_employer = application.job.employer.user_id == user.id
        is_admin = user.role == "admin"
 
        if not (is_owner_candidate or is_owner_employer or is_admin):
            raise NotFound()
 
        return application.status_logs.select_related("changed_by")   

class EmployerJobListAPIView(generics.ListAPIView):
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmployer]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = JobFilter
    search_fields = ["title", "description", "skills"]
    ordering_fields = ["posted_at", "title"]
    ordering = ["-posted_at"]
 
    def get_queryset(self):
        return Job.objects.select_related("employer").filter(
            employer__user=self.request.user
        )          

class JobApplicantsAPIView(generics.ListAPIView):
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmployer, IsOwnerEmployer]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ApplicationFilter
    search_fields = ["candidate__full_name", "candidate__skills"]
    ordering_fields = ["applied_at"]
    ordering = ["-applied_at"]
 
    def get_job(self):
        job = get_object_or_404(Job, pk=self.kwargs["job_id"])
        self.check_object_permissions(self.request, job)
        return job
 
    def get_queryset(self):
        job = self.get_job()
        return Application.objects.select_related("candidate", "job").filter(job=job)
    
def _status_breakdown(applications):
    """Current-status counts, e.g. {"applied": 3, "shortlisted": 2, ...}."""
    return {
        value: applications.filter(status=value).count()
        for value, _ in Application.STATUS_CHOICES
    }
 
 
def _shortlist_ratio(applications, total):
    """
    'ever_shortlisted' counts an application if it EVER reached
    Shortlisted/Interview Scheduled/Selected at any point in its
    audit log — not just its current status. This matters: an
    applicant who was shortlisted and later rejected should still
    count toward "did we shortlist them", since that's a screening-
    quality metric, not a snapshot of where they are right now.
    """
    ever_shortlisted = applications.filter(
        status_logs__to_status__in=[
            STATUS_SHORTLISTED, STATUS_INTERVIEW_SCHEDULED, STATUS_SELECTED
        ]
    ).distinct().count()
    ratio = round(ever_shortlisted / total, 2) if total else 0.0
    return ever_shortlisted, ratio
 
 
class JobAnalyticsAPIView(APIView):
    """
    GET /api/jobs/<job_id>/analytics/
 
    Application counts and shortlist ratio for ONE job. Ownership
    enforced the same manual way as JobApplicantsAPIView.
    """
    permission_classes = [permissions.IsAuthenticated, IsEmployer, IsOwnerEmployer]
 
    def get(self, request, job_id):
        job = get_object_or_404(Job, pk=job_id)
        self.check_object_permissions(request, job)
 
        applications = job.applications.all()
        total_applications = applications.count()
        ever_shortlisted, shortlist_ratio = _shortlist_ratio(applications, total_applications)
 
        return Response({
            "job_id": job.id,
            "title": job.title,
            "total_applications": total_applications,
            "status_breakdown": _status_breakdown(applications),
            "ever_shortlisted": ever_shortlisted,
            "shortlist_ratio": shortlist_ratio,
        })
 
 
class EmployerDashboardAnalyticsAPIView(APIView):
    """
    GET /api/employer/dashboard/
 
    Aggregate analytics across ALL of the requesting employer's own
    jobs — total job counts, total applications, an overall shortlist
    ratio, and a per-job breakdown for the dashboard's summary panel.
    """
    permission_classes = [permissions.IsAuthenticated, IsEmployer]
 
    def get(self, request):
        employer = Employer.objects.get(user=request.user, is_deleted=False)
        jobs = Job.objects.filter(employer=employer)
        applications = Application.objects.filter(job__employer=employer)
 
        total_applications = applications.count()
        ever_shortlisted, shortlist_ratio = _shortlist_ratio(applications, total_applications)
 
        per_job = [
            {
                "job_id": job.id,
                "title": job.title,
                "status": job.status,
                "application_count": job.applications.count(),
            }
            for job in jobs
        ]
 
        return Response({
            "total_jobs": jobs.count(),
            "active_jobs": jobs.filter(status="active").count(),
            "total_applications": total_applications,
            "status_breakdown": _status_breakdown(applications),
            "ever_shortlisted": ever_shortlisted,
            "shortlist_ratio": shortlist_ratio,
            "jobs": per_job,
        })   
class SaveJobAPIView(APIView):
    """
    POST   /api/jobs/<job_id>/save/   -> bookmark a job
    DELETE /api/jobs/<job_id>/save/   -> remove the bookmark
 
    Candidate-only. Saving is unrelated to applying — no job-status
    check here, since bookmarking an inactive/closed job to revisit
    later is a legitimate use case even though applying to one isn't.
    """
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def post(self, request, job_id):
        job = get_object_or_404(Job, pk=job_id)
        candidate = Candidate.objects.get(user=request.user, is_deleted=False)
 
        saved, created = SavedJob.objects.get_or_create(candidate=candidate, job=job)
        if not created:
            return Response({"detail": "Job already saved."}, status=status.HTTP_400_BAD_REQUEST)
 
        return Response(SavedJobSerializer(saved).data, status=status.HTTP_201_CREATED)
 
    def delete(self, request, job_id):
        candidate = Candidate.objects.get(user=request.user, is_deleted=False)
        deleted_count, _ = SavedJob.objects.filter(candidate=candidate, job_id=job_id).delete()
        if not deleted_count:
            return Response({"detail": "This job was not saved."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": "Job removed from saved list."}, status=status.HTTP_204_NO_CONTENT)
 
 
class SavedJobListAPIView(generics.ListAPIView):
    """GET /api/candidate/saved-jobs/ — the candidate's own bookmarked jobs."""
    serializer_class = SavedJobSerializer
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def get_queryset(self):
        candidate = Candidate.objects.get(user=self.request.user, is_deleted=False)
        return SavedJob.objects.select_related("job", "job__employer").filter(candidate=candidate)
 
 
class CandidateInterviewsAPIView(generics.ListAPIView):
    """
    GET /api/candidate/interviews/
 
    Convenience view for the dashboard's "Interview status" panel: the
    candidate's own applications currently at the interview_scheduled
    stage. 
    """
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def get_queryset(self):
        candidate = Candidate.objects.get(user=self.request.user, is_deleted=False)
        return Application.objects.select_related("job", "job__employer").filter(
            candidate=candidate, status=STATUS_INTERVIEW_SCHEDULED
        )
       
class RecommendedJobsAPIView(generics.ListAPIView):
    """
    GET /api/candidate/recommended-jobs/
 
    Basic skill-based matching: splits the candidate's comma-separated
    `skills` text into keywords, keeps active jobs whose `skills` field
    contains at least one keyword, and ranks results by how many
    keywords match. Jobs already applied to are excluded.
 
    Deliberately simple — substring matching in Python, no ML/embedding
    similarity — matching the Day 21 scope of "Recommendation logic
    (basic)". A candidate with no skills on file gets the newest active
    jobs instead of an empty list.
    """
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def get_queryset(self):
        candidate = Candidate.objects.get(user=self.request.user, is_deleted=False)
        keywords = [k.strip().lower() for k in candidate.skills.split(",") if k.strip()]
 
        applied_job_ids = Application.objects.filter(candidate=candidate).values_list("job_id", flat=True)
        base = Job.objects.select_related("employer").filter(status="active").exclude(id__in=applied_job_ids)
 
        if not keywords:
            return base.order_by("-posted_at")
 
        keyword_filter = Q()
        for kw in keywords:
            keyword_filter |= Q(skills__icontains=kw)
        matched = list(base.filter(keyword_filter))
 
        def match_count(job):
            job_skills = job.skills.lower()
            return sum(1 for kw in keywords if kw in job_skills)
 
        matched.sort(key=match_count, reverse=True)
        return matched       
   
class CandidateNotificationListAPIView(generics.ListAPIView):
    """GET /api/candidate/notifications/ — newest first, own notifications only."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)
 
 
class MarkNotificationReadAPIView(APIView):
    """
    POST /api/candidate/notifications/<id>/read/
 
    Ownership enforced by filtering on recipient in the same query
    that fetches the object — a notification belonging to someone else
    returns 404, it never confirms whose it actually is.
    """
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return Response({"id": notification.id, "is_read": True})   
    
class CandidateDashboardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def get(self, request):
        candidate = Candidate.objects.get(user=request.user, is_deleted=False)
        applications = Application.objects.filter(candidate=candidate)
 
        return Response({
            "applied_jobs": applications.count(),
            "saved_jobs": SavedJob.objects.filter(candidate=candidate).count(),
            "interviews_scheduled": applications.filter(status=STATUS_INTERVIEW_SCHEDULED).count(),
            "unread_notifications": Notification.objects.filter(
                recipient=request.user, is_read=False
            ).count(),
        })     
        
def log_admin_action(admin_user, action, target_type, target_id, details=""):
    """Every admin governance/moderation action gets one row here — the
    Day 22 audit trail. Called from every admin-mutating view below,
    and should also be added to the EXISTING AdminDeactivateUserAPIView
    and AdminVerifyEmployerView (see notes at the bottom of this file)."""
    AdminActionLog.objects.create(
        admin=admin_user, action=action, target_type=target_type,
        target_id=target_id, details=details,
    )
 
 
class AdminJobListAPIView(generics.ListAPIView):
    """
    GET /api/admin/jobs/?status=active&search=backend
 
    ALL jobs on the platform, any status, any employer — the "Manage
    job posts" panel. Reuses JobFilter/SearchFilter, same as the
    public and employer-scoped job lists.
    """
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = JobFilter
    search_fields = ["title", "description", "skills"]
    ordering_fields = ["posted_at", "title"]
    ordering = ["-posted_at"]
    queryset = Job.objects.select_related("employer")
 
 
class AdminJobActionAPIView(APIView):
    """
    POST /api/admin/jobs/<id>/activate/
    POST /api/admin/jobs/<id>/deactivate/
    POST /api/admin/jobs/<id>/close/
    POST /api/admin/jobs/<id>/remove/
 
    Admin-only job management. Unlike the Employer-facing
    JobStatusToggleAPIView, there's no ownership check here — an Admin
    acts on ANY job, e.g. to remove a spam posting regardless of who
    created it ("remove" is the Content Moderation "Remove spam jobs"
    action — a hard delete, not a status change). Every action is
    logged to AdminActionLog.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    STATUS_ACTIONS = {"activate": "active", "deactivate": "inactive", "close": "closed"}
 
    def post(self, request, pk, action):
        job = get_object_or_404(Job, pk=pk)
 
        if action == "remove":
            job_title = job.title
            job.delete()
            log_admin_action(request.user, "remove_job", "Job", pk, job_title)
            return Response({"detail": f"Job '{job_title}' removed."}, status=status.HTTP_204_NO_CONTENT)
 
        if action not in self.STATUS_ACTIONS:
            return Response({"detail": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)
 
        job.status = self.STATUS_ACTIONS[action]
        job.save(update_fields=["status", "updated_at"])
        log_admin_action(request.user, f"job_{action}", "Job", job.id, job.title)
        return Response({"id": job.id, "title": job.title, "status": job.status})
 
 
class AdminFlagUserAPIView(APIView):
    """
    POST /api/admin/users/<user_id>/flag/    body: {"reason": "..."}
    POST /api/admin/users/<user_id>/unflag/
 
    Flagging is deliberately separate from deactivating: a flagged
    account can still log in and use the platform normally — it's
    marked for admin review (e.g. a suspected fake employer or an
    abusive candidate), not locked out. Blocking access is what
    AdminDeactivateUserAPIView already does.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    def post(self, request, user_id, action):
        target = get_object_or_404(User, pk=user_id)
 
        if action == "flag":
            reason = request.data.get("reason", "")
            target.is_flagged = True
            target.flag_reason = reason
            target.save(update_fields=["is_flagged", "flag_reason"])
            log_admin_action(request.user, "flag_user", "User", target.id, reason)
        elif action == "unflag":
            target.is_flagged = False
            target.flag_reason = ""
            target.save(update_fields=["is_flagged", "flag_reason"])
            log_admin_action(request.user, "unflag_user", "User", target.id)
        else:
            return Response({"detail": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)
 
        return Response({
            "id": target.id, "email": target.email,
            "is_flagged": target.is_flagged, "flag_reason": target.flag_reason,
        })        
   
class PlatformStatsAPIView(APIView):
    """
    GET /api/admin/stats/overview/
 
    High-level platform snapshot: user counts by role, job counts by
    status, total applications, and how many accounts are currently
    flagged or deactivated.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    def get(self, request):
        users_by_role = {
            value: User.objects.filter(role=value).count() for value, _ in Role.choices
        }
        jobs_by_status = {
            value: Job.objects.filter(status=value).count() for value, _ in Job.STATUS_CHOICES
        }
        return Response({
            "total_users": User.objects.count(),
            "users_by_role": users_by_role,
            "flagged_users": User.objects.filter(is_flagged=True).count(),
            "deactivated_users": User.objects.filter(is_active=False).count(),
            "total_jobs": Job.objects.count(),
            "jobs_by_status": jobs_by_status,
            "total_applications": Application.objects.count(),
        })
 
 
class UserGrowthStatsAPIView(APIView):
    """
    GET /api/admin/stats/user-growth/?days=30
 
    Daily signup counts for the last N days (default 30) — the series
    a "user growth" chart would plot.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    def get(self, request):
        days = int(request.query_params.get("days", 30))
        since = timezone.now() - timedelta(days=days)
 
        rows = (
            User.objects.filter(created_at__gte=since)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        return Response({
            "days": days,
            "growth": [{"date": row["day"], "signups": row["count"]} for row in rows],
        })
 
 
class JobActivityStatsAPIView(APIView):
    """
    GET /api/admin/stats/job-activity/?days=30
 
    Daily job-posting counts and daily application counts for the last
    N days — two series a "job activity" chart would plot side by side.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    def get(self, request):
        days = int(request.query_params.get("days", 30))
        since = timezone.now() - timedelta(days=days)
 
        jobs_posted = (
            Job.objects.filter(posted_at__gte=since)
            .annotate(day=TruncDate("posted_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        applications_received = (
            Application.objects.filter(applied_at__gte=since)
            .annotate(day=TruncDate("applied_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        return Response({
            "days": days,
            "jobs_posted": [{"date": r["day"], "count": r["count"]} for r in jobs_posted],
            "applications_received": [{"date": r["day"], "count": r["count"]} for r in applications_received],
        })
class AdminActionLogListAPIView(generics.ListAPIView):
    """
    GET /api/admin/audit-logs/?action=flag_user&admin=3
 
    Full admin action history, newest first — every governance and
    moderation action taken on the platform. filterset_fields (rather
    than a dedicated FilterSet class) is enough here since these are
    plain exact-match filters, not the range/overlap logic JobFilter
    needs.
    """
    serializer_class = AdminActionLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["action", "target_type", "admin"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    queryset = AdminActionLog.objects.select_related("admin")                         
   
class ResumeParseUploadAPIView(APIView):
    """
    POST /api/resume/parse/   (multipart, field name "resume")
 
    The "upload -> parse" pipeline deliverable: accepts a fresh file
    upload independent of the candidate's saved profile resume,
    extracts raw text, cleans it, and returns both. Nothing is saved
    to the database — this is a stateless preprocessing utility.
    """
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
    parser_classes = [MultiPartParser, FormParser]
 
    def post(self, request):
        uploaded_file = request.FILES.get("resume")
        if not uploaded_file:
            return Response(
                {"detail": "No file provided. Attach a file under the 'resume' field."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        try:
            validate_resume_file(uploaded_file)
        except DjangoValidationError as e:
            return Response({"detail": e.messages}, status=status.HTTP_400_BAD_REQUEST)
 
        try:
            raw_text = extract_text(uploaded_file, uploaded_file.name)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 
        cleaned = clean_text(raw_text)
 
        return Response({
            "file_name": uploaded_file.name,
            "raw_length": len(raw_text),
            "cleaned_length": len(cleaned),
            "cleaned_text": cleaned,
        })
 
 
class CandidateResumeParsedTextAPIView(APIView):
    """
    GET /api/candidate/resume/parsed-text/
 
    Parses the candidate's ALREADY-uploaded profile resume (from the
    Day 12 ResumeUploadView) rather than requiring a fresh upload —
    the natural entry point once a candidate already has a resume on
    file, feeding straight into later AI-preprocessing steps.
    """
    permission_classes = [permissions.IsAuthenticated, IsCandidate]
 
    def get(self, request):
        candidate = Candidate.objects.get(user=request.user, is_deleted=False)
        if not candidate.resume:
            return Response({"detail": "No resume on file."}, status=status.HTTP_404_NOT_FOUND)
 
        try:
            candidate.resume.open("rb")
            raw_text = extract_text(candidate.resume, candidate.resume.name)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            candidate.resume.close()
 
        cleaned = clean_text(raw_text)
 
        return Response({
            "file_name": candidate.resume.name,
            "raw_length": len(raw_text),
            "cleaned_length": len(cleaned),
            "cleaned_text": cleaned,
        })    