from django.utils import timezone
from django.db import transaction

from .workflow import validate_transition, STATUS_APPLIED, STATUS_SHORTLISTED, STATUS_REJECTED
from .ats_scoring import compute_ats_score


# ---------------------------------------------------------------------------
# 1. Threshold Logic
# ---------------------------------------------------------------------------

# Dynamic defaults by experience bracket, used ONLY when the employer
# hasn't set an explicit threshold on the job.
DEFAULT_SHORTLIST_THRESHOLDS = {
    "fresher": 60.0, "0-1": 60.0, "1-3": 70.0, "3-5": 75.0, "5+": 80.0,
}
DEFAULT_REJECT_THRESHOLDS = {
    "fresher": 30.0, "0-1": 30.0, "1-3": 35.0, "3-5": 40.0, "5+": 45.0,
}


def get_shortlist_threshold(job) -> float:
    """The job's own threshold if the employer set one (role-based
    override), otherwise a dynamic default from its experience bracket."""
    if job.auto_shortlist_threshold is not None:
        return job.auto_shortlist_threshold
    return DEFAULT_SHORTLIST_THRESHOLDS.get(job.experience, 70.0)


def get_reject_threshold(job) -> float:
    if job.auto_reject_threshold is not None:
        return job.auto_reject_threshold
    return DEFAULT_REJECT_THRESHOLDS.get(job.experience, 35.0)


# ---------------------------------------------------------------------------
# Shared status-change helper
#
# This is the ONE place that changes an application's status: it
# validates the transition, writes the Day 19 audit log entry, creates
# the Day 21 candidate notification, and saves — used by BOTH this
# automation engine and (optionally, see the setup notes) the manual
# Day 19 employer-action view, so there's one source of truth instead
# of the same logic duplicated in two places.
# ---------------------------------------------------------------------------

def apply_status_change(application, target_status, changed_by=None, auto=False):
    """changed_by=None means a system/automated action rather than a
    specific human admin or employer — reflected in the notification
    text and distinguishable in the audit log."""
    from .models import ApplicationStatusLog, Notification

    validate_transition(application.status, target_status)

    with transaction.atomic():
        ApplicationStatusLog.objects.create(
            application=application,
            from_status=application.status,
            to_status=target_status,
            changed_by=changed_by,
        )
        Notification.objects.create(
            recipient=application.candidate.user,
            application=application,
            message=(
                f"Your application for '{application.job.title}' is now "
                f"'{target_status}'" + (" (automated)" if auto else "") + "."
            ),
        )
        if target_status in (STATUS_SHORTLISTED, STATUS_REJECTED):
            from .email_service import queue_email
            queue_email(target_status, application)
        application.status = target_status
        update_fields = ["status"]
        if auto:
            application.auto_processed_at = timezone.now()
            update_fields.append("auto_processed_at")
        application.save(update_fields=update_fields)


# ---------------------------------------------------------------------------
# 2. Auto Actions + 4. Employer Overrides (enforced here)
# ---------------------------------------------------------------------------

def evaluate_application(application, changed_by=None) -> dict:
    """
    Runs ONE application through the automation engine. Only ever acts
    on applications currently at 'applied' — once anyone (automation or
    a human) moves it further, automation leaves it alone from then on.
    Both employer override switches are checked before anything else:
    a job with automation disabled, or an application specifically
    excluded, is skipped entirely — not even scored.
    """
    job = application.job

    if not job.auto_processing_enabled:
        return {"application_id": application.id, "action": "skipped", "reason": "job_automation_disabled"}

    if application.auto_processing_excluded:
        return {"application_id": application.id, "action": "skipped", "reason": "application_excluded"}

    if application.status != STATUS_APPLIED:
        return {"application_id": application.id, "action": "skipped", "reason": "not_in_applied_stage"}

    if application.ats_score is None:
        result = compute_ats_score(job, application.candidate)
        application.ats_score = result.get("suitability_percent")
        application.ats_score_breakdown = result.get("breakdown")
        application.ats_scored_at = timezone.now()
        application.save(update_fields=["ats_score", "ats_score_breakdown", "ats_scored_at"])

    score = application.ats_score
    if score is None:
        return {"application_id": application.id, "action": "skipped", "reason": "could_not_score"}

    shortlist_cutoff = get_shortlist_threshold(job)
    reject_cutoff = get_reject_threshold(job)

    if score >= shortlist_cutoff:
        apply_status_change(application, STATUS_SHORTLISTED, changed_by=changed_by, auto=True)
        return {"application_id": application.id, "action": "auto_shortlisted",
                "score": score, "threshold": shortlist_cutoff}

    if score < reject_cutoff:
        apply_status_change(application, STATUS_REJECTED, changed_by=changed_by, auto=True)
        return {"application_id": application.id, "action": "auto_rejected",
                "score": score, "threshold": reject_cutoff}

    return {"application_id": application.id, "action": "no_action",
            "reason": "score_in_manual_review_band", "score": score,
            "shortlist_threshold": shortlist_cutoff, "reject_threshold": reject_cutoff}


# ---------------------------------------------------------------------------
# 3. Batch Processing
# ---------------------------------------------------------------------------

def run_auto_shortlisting_for_job(job, changed_by=None) -> list:
    """Evaluate every 'applied'-stage application for ONE job."""
    applications = job.applications.filter(status=STATUS_APPLIED)
    return [evaluate_application(app, changed_by=changed_by) for app in applications]


def run_auto_shortlisting_platform_wide(changed_by=None) -> list:
    """Evaluate every 'applied'-stage application platform-wide — the
    function the cron-scheduled management command calls."""
    from .models import Application
    applications = Application.objects.filter(status=STATUS_APPLIED).select_related("job", "candidate")
    return [evaluate_application(app, changed_by=changed_by) for app in applications]