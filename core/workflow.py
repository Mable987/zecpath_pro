STATUS_APPLIED = "applied"
STATUS_SHORTLISTED = "shortlisted"
STATUS_INTERVIEW_SCHEDULED = "interview_scheduled"
STATUS_REJECTED = "rejected"
STATUS_SELECTED = "selected"

APPLICATION_STATUS_CHOICES = [
    (STATUS_APPLIED, "Applied"),
    (STATUS_SHORTLISTED, "Shortlisted"),
    (STATUS_INTERVIEW_SCHEDULED, "Interview Scheduled"),
    (STATUS_REJECTED, "Rejected"),
    (STATUS_SELECTED, "Selected"),
]

# Forward-only pipeline. "Rejected" is reachable from any active stage
# (an employer can reject at any point), but nothing is reachable from
# Rejected or Selected — those are terminal/locked.
ALLOWED_TRANSITIONS = {
    STATUS_APPLIED: {STATUS_SHORTLISTED, STATUS_REJECTED},
    STATUS_SHORTLISTED: {STATUS_INTERVIEW_SCHEDULED, STATUS_REJECTED},
    STATUS_INTERVIEW_SCHEDULED: {STATUS_SELECTED, STATUS_REJECTED},
    STATUS_REJECTED: set(),
    STATUS_SELECTED: set(),
}

LOCKED_STATUSES = {STATUS_REJECTED, STATUS_SELECTED}

# Maps the employer-facing action name (used in the URL) to the status
# it moves an application to — keeps the API surface readable
# (/shortlist/, /reject/) instead of a raw ?status=shortlisted PATCH.
ACTION_TO_STATUS = {
    "shortlist": STATUS_SHORTLISTED,
    "schedule-interview": STATUS_INTERVIEW_SCHEDULED,
    "select": STATUS_SELECTED,
    "reject": STATUS_REJECTED,
}


def validate_transition(current_status: str, target_status: str) -> None:
    """Raises ValueError with a human-readable message if the transition
    isn't allowed. The view turns this into a 400 response."""
    if current_status in LOCKED_STATUSES:
        raise ValueError(
            f"This application is '{current_status}', a locked stage — "
            "no further status changes are allowed."
        )
    allowed_next = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_next:
        raise ValueError(
            f"Cannot move from '{current_status}' to '{target_status}'. "
            f"Allowed next stage(s): {sorted(allowed_next) or 'none'}."
        )