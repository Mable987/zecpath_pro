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
    # Date range (kept from Day 14)
    posted_after = django_filters.DateFilter(field_name="posted_at", lookup_expr="gte")
    posted_before = django_filters.DateFilter(field_name="posted_at", lookup_expr="lte")
    employer = django_filters.NumberFilter(field_name="employer__id")
 
    # Skill-based search: partial match against the comma-separated
    # skills text — e.g. ?skills=python matches "Python, Django, SQL"
    skills = django_filters.CharFilter(field_name="skills", lookup_expr="icontains")
 
    # Experience: exact match against the choice field (fresher, 0-1,
    # 1-3, 3-5, 5+) — a true numeric range isn't meaningful here since
    # experience is stored as a category, not a number.
    experience = django_filters.ChoiceFilter(choices=Job.EXPERIENCE_CHOICES)
 
    # Salary range: a job "matches" a candidate's desired range if the
    # job's range overlaps it at all, not just an exact bound match —
    # e.g. a candidate wanting 50k-70k should also see a job posted as
    # 60k-90k, since 60k-70k overlaps.
    min_salary = django_filters.NumberFilter(field_name="salary_max", lookup_expr="gte")
    max_salary = django_filters.NumberFilter(field_name="salary_min", lookup_expr="lte")
 
    # Location & job type
    location = django_filters.CharFilter(field_name="location", lookup_expr="icontains")
    job_type = django_filters.ChoiceFilter(choices=Job.JOB_TYPE_CHOICES)
 
    class Meta:
        model = Job
        fields = [
            "employer", "posted_after", "posted_before", "skills",
            "experience", "min_salary", "max_salary", "location", "job_type",
        ]


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