from rest_framework import serializers
from .models import *
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.password_validation import validate_password

class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = [
            "id", "employer", "title", "description", "skills", "experience",
            "salary_min", "salary_max", "location", "job_type", "status",
            "posted_at", "updated_at",
        ]
        read_only_fields = ["id", "employer", "posted_at", "updated_at"]
 
    def validate(self, data):
        salary_min = data.get("salary_min", getattr(self.instance, "salary_min", None))
        salary_max = data.get("salary_max", getattr(self.instance, "salary_max", None))
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            raise serializers.ValidationError(
                {"salary_min": "salary_min cannot be greater than salary_max."}
            )
        return data
 
    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Job title cannot be blank.")
        return value
    
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'   
        extra_kwargs = {
            'password': {'write_only': True}
        }   
          
 
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
    employer_name = serializers.CharField(source="job.employer.company_name", read_only=True)
 
    class Meta:
        model = Application
        fields = [
            "id", "job", "job_title", "employer_name", "candidate", "candidate_name",
            "resume_snapshot", "applied_at", "status",
        ]
        read_only_fields = ["id", "applied_at", "resume_snapshot"] 
        
class ApplicationStatusLogSerializer(serializers.ModelSerializer):
    changed_by_email = serializers.CharField(source="changed_by.email", read_only=True)
 
    class Meta:
        model = ApplicationStatusLog
        fields = ["id", "from_status", "to_status", "changed_by", "changed_by_email", "changed_at"]
        read_only_fields = fields     
       
class SavedJobSerializer(serializers.ModelSerializer):
    job_detail = JobSerializer(source="job", read_only=True)
 
    class Meta:
        model = SavedJob
        fields = ["id", "job", "job_detail", "saved_at"]
        read_only_fields = ["id", "saved_at"]
 
 
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "application", "message", "is_read", "created_at"]
        read_only_fields = ["id", "application", "message", "created_at"]           