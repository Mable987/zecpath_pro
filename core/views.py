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
        base = Application.objects.select_related("job", "candidate")
        user = self.request.user
 
        if user.role == "admin":
            return base.all()
        elif user.role == "candidate":
            return base.filter(candidate__user=user)
        else:
            # Employers see applications to THEIR jobs only
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
    """
    POST /api/jobs/<id>/activate/    -> status = "active"
    POST /api/jobs/<id>/deactivate/  -> status = "inactive"
 
    Kept as a dedicated action (rather than a generic PATCH to status)
    so the intent is explicit and auditable, and so future logic
    (e.g. notifying applicants, logging the change) has one clear
    place to live per action.
    """
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
    """Only Candidates can apply to jobs."""
    permission_classes = [IsAuthenticated, IsCandidate]
 
    def post(self, request, job_id):
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)
 
        candidate = Candidate.objects.get(user=request.user)
 
        if Application.objects.filter(candidate=candidate, job=job).exists():
            return Response(
                {"detail": "You have already applied to this job."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        application = Application.objects.create(candidate=candidate, job=job)
        return Response(
            {"id": application.id, "job": job.title, "status": application.status},
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
        return Response(serializer.data)
 
    def delete(self, request, pk):
        profile = get_object_or_404(Employer, pk=pk)
        profile.soft_delete()
        return Response({"detail": "Employer profile deactivated by admin."}, status=status.HTTP_204_NO_CONTENT)
 
 
class AdminVerifyEmployerView(APIView):
    """
    Admin-only: toggle an Employer's verification status.
    Separated from the generic update view since is_verified is
    intentionally read-only on the self-serve EmployerProfileSerializer.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
 
    def post(self, request, pk):
        profile = get_object_or_404(Employer, pk=pk)
        profile.is_verified = True
        profile.save(update_fields=["is_verified"])
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
        return Response(serializer.data)
 
    def delete(self, request, pk):
        profile = get_object_or_404(Candidate, pk=pk)
        profile.soft_delete()
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
    """
    GET /api/public/jobs/latest/
 
    The N most recent active postings — a simple "what's new" feed,
    capped rather than paginated since it's meant to show a fixed,
    small window (e.g. for a homepage widget), not be browsed
    endlessly.
    """
    serializer_class = JobSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None 
 
    def get_queryset(self):
        return Job.objects.select_related("employer").filter(
            status="active"
        ).order_by("-posted_at")[:10]           