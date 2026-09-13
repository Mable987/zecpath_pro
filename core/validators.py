"""
core/validators.py

Reusable validators for resume uploads: type, size, and a basic
malware-prevention sanity check.
"""

import os
from django.core.exceptions import ValidationError

ALLOWED_RESUME_EXTENSIONS = [".pdf", ".doc", ".docx"]
ALLOWED_RESUME_CONTENT_TYPES = [
    "application/pdf",
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
]
MAX_RESUME_SIZE_MB = 5
MAX_RESUME_SIZE_BYTES = MAX_RESUME_SIZE_MB * 1024 * 1024

# Extensions that should NEVER be accepted, even if somehow disguised
# with a matching content-type header (defense in depth — basic
# malware-prevention: never trust the client's declared type alone).
DANGEROUS_EXTENSIONS = [
    ".exe", ".bat", ".sh", ".js", ".php", ".py", ".jar", ".msi", ".scr",
]


def validate_resume_file(file):
    """Run all resume validation checks. Raises ValidationError on failure."""
    ext = os.path.splitext(file.name)[1].lower()

    if ext in DANGEROUS_EXTENSIONS:
        raise ValidationError("This file type is not allowed for security reasons.")

    if ext not in ALLOWED_RESUME_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{ext}'. Allowed types: "
            f"{', '.join(ALLOWED_RESUME_EXTENSIONS)}."
        )

    # Content-type check is a second, independent signal — a renamed
    # .exe with a .pdf extension would still fail here in most cases,
    # since browsers/clients set content_type based on file content
    # sniffing, not just the filename.
    content_type = getattr(file, "content_type", None)
    if content_type and content_type not in ALLOWED_RESUME_CONTENT_TYPES:
        raise ValidationError(
            f"File content type '{content_type}' does not match an allowed resume format."
        )

    if file.size > MAX_RESUME_SIZE_BYTES:
        raise ValidationError(
            f"File too large ({file.size / (1024*1024):.1f} MB). "
            f"Maximum allowed size is {MAX_RESUME_SIZE_MB} MB."
        )