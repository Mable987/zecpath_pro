from rest_framework import serializers
from .models import *

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.password_validation import validate_password

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
          
class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
 
    class Meta:
        model = User
        fields = ["id", "email", "phone", "role", "password"]
 
    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
 
    def validate_phone(self, value):
        if value and User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return value
 
    def create(self, validated_data):
        # use create_user so the password gets hashed (never save raw passwords)
        return User.objects.create_user(**validated_data)
 
 
class LoginSerializer(TokenObtainPairSerializer):
    """
    Extends SimpleJWT's default serializer so the returned tokens also
    carry the user's role and email as custom claims — useful on the
    frontend without a separate profile lookup.
    """
 
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["role"] = user.role
        return token        
        