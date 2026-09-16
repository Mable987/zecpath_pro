"""
core/services/auth_service.py

Service-layer functions for authentication logic. Views should call
these instead of embedding business logic directly, which:
- removes duplication (e.g. "does this email/phone already exist"
  checks previously lived inside the serializer only; now reusable)
- gives each operation a clear, testable, single-purpose function
- keeps views thin — a view's job is to translate HTTP <-> service call,
  not to contain the actual logic
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from core.models import User, Role


def email_is_taken(email: str, exclude_user_id: int = None) -> bool:
    qs = User.objects.filter(email__iexact=email)
    if exclude_user_id:
        qs = qs.exclude(id=exclude_user_id)
    return qs.exists()


def phone_is_taken(phone: str, exclude_user_id: int = None) -> bool:
    if not phone:
        return False
    qs = User.objects.filter(phone=phone)
    if exclude_user_id:
        qs = qs.exclude(id=exclude_user_id)
    return qs.exists()


def register_user(*, email: str, password: str, phone: str = "", role: str = Role.CANDIDATE) -> User:
    """
    Single entry point for creating a new user account.
    Raises DRFValidationError with a clear message on any failure,
    so callers (the signup view) don't need to duplicate these checks.
    """
    if email_is_taken(email):
        raise DRFValidationError({"email": "A user with this email already exists."})

    if phone_is_taken(phone):
        raise DRFValidationError({"phone": "A user with this phone number already exists."})

    try:
        validate_password(password)
    except DjangoValidationError as e:
        raise DRFValidationError({"password": e.messages})

    return User.objects.create_user(email=email, password=password, phone=phone, role=role)


def deactivate_user(user: User) -> User:
    """Used by the Admin deactivate-user endpoint — single source of truth
    for what 'deactivating' a user actually means, rather than each
    caller setting is_active=False inline."""
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


def verify_employer(employer) -> None:
    """Used by the Admin verify-employer endpoint."""
    employer.is_verified = True
    employer.save(update_fields=["is_verified"])