"""
core/filters.py

django-filter FilterSets — these define the *structured* filter fields
(exact matches, date ranges) that appear as query params, separate
from free-text SearchFilter (which searches across multiple fields
with partial matches).
"""

import django_filters
from .models import Job, Application, User


class JobFilter(django_filters.FilterSet):
    # ?posted_after=2026-01-01&posted_before=2026-12-31
    posted_after = django_filters.DateFilter(field_name="posted_at", lookup_expr="gte")
    posted_before = django_filters.DateFilter(field_name="posted_at", lookup_expr="lte")
    employer = django_filters.NumberFilter(field_name="employer__id")

    class Meta:
        model = Job
        fields = ["employer", "posted_after", "posted_before"]


class ApplicationFilter(django_filters.FilterSet):
    # ?status=pending
    status = django_filters.ChoiceFilter(choices=Application.STATUS_CHOICES)
    applied_after = django_filters.DateFilter(field_name="applied_at", lookup_expr="gte")
    applied_before = django_filters.DateFilter(field_name="applied_at", lookup_expr="lte")

    class Meta:
        model = Application
        fields = ["status", "applied_after", "applied_before"]


class UserFilter(django_filters.FilterSet):
    # ?role=employer
    role = django_filters.ChoiceFilter(choices=User._meta.get_field("role").choices)
    is_active = django_filters.BooleanFilter()

    class Meta:
        model = User
        fields = ["role", "is_active"]