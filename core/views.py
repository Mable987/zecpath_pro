from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.response import Response
from core.serializers import JobSerializer, UserSerializer
from rest_framework.views import APIView
from .models import *
from rest_framework import status

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