from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
import uuid, os
from .validators import validate_resume_file


class Role(models.TextChoices):
    """Role constants — single source of truth for valid roles."""
    ADMIN = "admin", "Admin"
    EMPLOYER = "employer", "Employer"
    CANDIDATE = "candidate", "Candidate"


class UserManager(BaseUserManager):
    """Custom manager since we use email instead of username to log in."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        extra_fields.setdefault("role", Role.CANDIDATE)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_verified", True)
        extra_fields.setdefault("role", Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CANDIDATE)

    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)  # required for admin access

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"      # login with email, not username
    REQUIRED_FIELDS = []          # no extra fields required for createsuperuser

    def __str__(self):
        return f"{self.email} ({self.role})"


class Employer(models.Model):
    SIZE_CHOICES = [
        ("1-10", "1-10 employees"),
        ("11-50", "11-50 employees"),
        ("51-200", "51-200 employees"),
        ("201-500", "201-500 employees"),
        ("500+", "500+ employees"),
    ]
 
    user = models.OneToOneField("User", on_delete=models.CASCADE)
    company_name = models.CharField(max_length=150)
    company_website = models.URLField(blank=True, null=True)
    domain = models.CharField(max_length=100, blank=True)               # e.g. "Fintech", "Healthcare"
    size = models.CharField(max_length=20, choices=SIZE_CHOICES, blank=True)
    is_verified = models.BooleanField(default=False)                    # company verification status
 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)                     # soft delete flag
    deleted_at = models.DateTimeField(null=True, blank=True)
 
    def __str__(self):
        return self.company_name
 
    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])
 
 
class Candidate(models.Model):
    def resume_upload_path(instance, filename):
        ext = os.path.splitext(filename)[1].lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        return f"resumes/{instance.user_id}/{unique_name}"
    EDUCATION_CHOICES = [
        ("high_school", "High School"),
        ("bachelors", "Bachelor's Degree"),
        ("masters", "Master's Degree"),
        ("phd", "PhD"),
        ("other", "Other"),
    ]
 
    user = models.OneToOneField("User", on_delete=models.CASCADE)
    full_name = models.CharField(max_length=150)
    resume = models.FileField(upload_to=resume_upload_path, blank=True, null=True, validators=[validate_resume_file])
    skills = models.TextField(blank=True)                                # comma-separated or free text
    education = models.CharField(max_length=20, choices=EDUCATION_CHOICES, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    expected_salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)                      # soft delete flag
    deleted_at = models.DateTimeField(null=True, blank=True)
 
    def __str__(self):
        return self.full_name
 
    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])


class Job(models.Model):
    employer = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name="jobs")
    title = models.CharField(max_length=100)
    description = models.TextField()
    posted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Application(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("reviewed", "Reviewed"),
        ("rejected", "Rejected"),
    ]
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="applications")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="applications")
    applied_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    def __str__(self):
        return f"{self.candidate.full_name} applied for {self.job.title}"
    