from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.response import Response
from core.serializers import *
from rest_framework.views import APIView
from .models import *
from rest_framework import status, permissions
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

# Create your views here.
def home_api(request): 
    return JsonResponse({"message": "Hello Zecpath Backend"})

class JobListAPIView(APIView):
    def get(self, request):
        jobs = Job.objects.all()
        serializer = JobSerializer(jobs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class JobCreateAPIView(APIView):
    def post(self,request):
        serializer = JobSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST) 
    
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