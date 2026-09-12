from rest_framework.permissions import BasePermission
from .models import Role


class IsAdmin(BasePermission):
    message = "Only Admin users can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == Role.ADMIN
        )


class IsEmployer(BasePermission):
    message = "Only Employer users can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == Role.EMPLOYER
        )


class IsCandidate(BasePermission):
    message = "Only Candidate users can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == Role.CANDIDATE
        )


class IsOwnerEmployer(BasePermission):
    """
    Object-level check: an Employer can only modify/delete THEIR OWN job
    postings, not someone else's. Used alongside IsEmployer.
    """
    message = "You can only manage your own job postings."

    def has_object_permission(self, request, view, obj):
        return obj.employer.user_id == request.user.id