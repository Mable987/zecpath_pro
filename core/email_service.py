from datetime import timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone


# ---------------------------------------------------------------------------
# 1. Email Infrastructure: template system
# ---------------------------------------------------------------------------

TEMPLATES = {
    "application_submitted": {
        "subject": "Application received: {job_title}",
        "template": "emails/application_submitted.txt",
    },
    "shortlisted": {
        "subject": "You've been shortlisted for {job_title}!",
        "template": "emails/shortlisted.txt",
    },
    "rejected": {
        "subject": "Update on your application for {job_title}",
        "template": "emails/rejected.txt",
    },
}


# ---------------------------------------------------------------------------
# 2. Trigger Events — called from the apply view and apply_status_change()
# ---------------------------------------------------------------------------

def queue_email(event_type: str, application):
    """Renders the right template for the event and writes a PENDING
    EmailLog row. Does NOT send anything — see send_one()/
    send_pending_emails() for the actual delivery step."""
    from .models import EmailLog

    config = TEMPLATES[event_type]
    candidate = application.candidate
    job = application.job

    context = {
        "candidate_name": candidate.full_name,
        "job_title": job.title,
        "company_name": job.employer.company_name,
        "status": application.status,
    }
    body = render_to_string(config["template"], context)
    subject = config["subject"].format(job_title=job.title)

    return EmailLog.objects.create(
        recipient_email=candidate.user.email,
        recipient_user=candidate.user,
        event_type=event_type,
        application=application,
        subject=subject,
        body=body,
        status=EmailLog.Status.PENDING,
    )


# ---------------------------------------------------------------------------
# 3. Async Jobs: sending + retry  /  4. Logging: failure handling
# ---------------------------------------------------------------------------

def _backoff_minutes(attempts: int) -> int:
    """Growing delay: 5, 15, 45 minutes for attempts 1, 2, 3."""
    return 5 * (3 ** (attempts - 1))


def send_one(email_log) -> bool:
    """
    Attempt to deliver ONE queued email. Returns True on success. On
    failure: records the error, increments attempts, and either
    schedules a retry or marks it permanently failed.
    """
    from .models import EmailLog

    email_log.attempts += 1
    try:
        send_mail(
            subject=email_log.subject,
            message=email_log.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email_log.recipient_email],
            fail_silently=False,
        )
    except Exception as exc:
        email_log.last_error = str(exc)
        if email_log.attempts >= email_log.max_attempts:
            email_log.status = EmailLog.Status.FAILED_PERMANENTLY
            email_log.next_retry_at = None
        else:
            email_log.status = EmailLog.Status.FAILED
            email_log.next_retry_at = timezone.now() + timedelta(
                minutes=_backoff_minutes(email_log.attempts)
            )
        email_log.save(update_fields=["attempts", "status", "last_error", "next_retry_at"])
        return False

    email_log.status = EmailLog.Status.SENT
    email_log.sent_at = timezone.now()
    email_log.save(update_fields=["attempts", "status", "sent_at"])
    return True


def send_pending_emails() -> dict:
    """
    The function the cron-scheduled management command calls. Picks up
    everything PENDING, plus anything FAILED whose retry delay has
    passed, and attempts delivery.
    """
    from .models import EmailLog

    due = EmailLog.objects.filter(
        Q(status=EmailLog.Status.PENDING)
        | Q(status=EmailLog.Status.FAILED, next_retry_at__lte=timezone.now())
    )
    total = due.count()

    sent = failed = 0
    for email_log in due:
        if send_one(email_log):
            sent += 1
        else:
            failed += 1

    return {"total_attempted": total, "sent": sent, "failed_or_retrying": failed}