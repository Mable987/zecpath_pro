"""
core/signals.py

Auto-creates an Employer or Candidate profile whenever a User is created,
based on their role. This keeps profile creation automatic and consistent
instead of relying on registration code to remember to do it.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, Role, Employer, Candidate


@receiver(post_save, sender=User)
def create_role_profile(sender, instance, created, **kwargs):
    if not created:
        return  # only run on first creation, not every save

    if instance.role == Role.EMPLOYER:
        Employer.objects.get_or_create(
            user=instance,
            defaults={"company_name": instance.email.split("@")[0]},
        )
    elif instance.role == Role.CANDIDATE:
        Candidate.objects.get_or_create(
            user=instance,
            defaults={"full_name": instance.email.split("@")[0]},
        )
    # Admin role: no separate profile needed


@receiver(post_save, sender=User)
def sync_profile_on_update(sender, instance, created, **kwargs):
    """
    If a user's role changes after creation, make sure the matching
    profile exists (keeps profile in sync with role).
    """
    if created:
        return

    if instance.role == Role.EMPLOYER and not hasattr(instance, "employer"):
        Employer.objects.get_or_create(
            user=instance,
            defaults={"company_name": instance.email.split("@")[0]},
        )
    elif instance.role == Role.CANDIDATE and not hasattr(instance, "candidate"):
        Candidate.objects.get_or_create(
            user=instance,
            defaults={"full_name": instance.email.split("@")[0]},
        )