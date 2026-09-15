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

class EmployerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employer
        fields = [
            "id", "company_name", "company_website", "domain", "size",
            "is_verified", "created_at", "updated_at",
        ]
        # is_verified is admin-controlled, not self-editable — see views.py
        read_only_fields = ["id", "is_verified", "created_at", "updated_at"]
 
    def validate_company_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Company name cannot be blank.")
        return value
 
 
class CandidateProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = [
            "id", "full_name", "resume", "skills", "education",
            "experience_years", "expected_salary", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
 
    def validate_full_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Full name cannot be blank.")
        return value
 
    def validate_experience_years(self, value):
        if value < 0 or value > 60:
            raise serializers.ValidationError("Experience years must be between 0 and 60.")
        return value
 
    def validate_expected_salary(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Expected salary cannot be negative.")
        return value        
class ApplicationSerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source="job.title", read_only=True)
    candidate_name = serializers.CharField(source="candidate.full_name", read_only=True)
 
    class Meta:
        model = Application
        fields = ["id", "job", "job_title", "candidate", "candidate_name",
                  "applied_at", "status"]
        read_only_fields = ["id", "applied_at"]    