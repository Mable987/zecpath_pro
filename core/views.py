from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.response import Response
from core.serializers import *
from rest_framework.views import APIView
from .models import *
from rest_framework import status, permissions, generics
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.permissions import IsAuthenticated
from .permissions import IsAdmin, IsEmployer, IsCandidate, IsOwnerEmployer

# Create your views here.
def home_api(request): 
    return JsonResponse({"message": "Hello Zecpath Backend"})

class JobListAPIView(APIView):
    def get(self, request):
        jobs = Job.objects.all()
        serializer = JobSerializer(jobs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class JobCreateAPIView(generics.CreateAPIView):
    """Only Employers can post jobs. (Overrides the open Day 5 version.)"""
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [IsAuthenticated, IsEmployer]
 
    def perform_create(self, serializer):
        # auto-attach the job to the logged-in employer's profile —
        # an employer can never post a job "as" someone else
        employer = Employer.objects.get(user=self.request.user)
        serializer.save(employer=employer)
 
 
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
    Admin-only: full visibility into all users on the platform.
    Demonstrates 'Admin can control system'.
    """
    permission_classes = [IsAuthenticated, IsAdmin]
 
    def get(self, request):
        from .models import User
        users = User.objects.all().values("id", "email", "role", "is_active", "is_verified")
        return Response(list(users))
 
 
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
    permission_classes = [permissions.AllowAny]  # signup must be open to everyone
 
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
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