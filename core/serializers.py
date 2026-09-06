from rest_framework import serializers
from .models import *
from django.contrib.auth.models import User

class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = '__all__'
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'   
        extra_kwargs = {
            'password': {'write_only': True}
        }     