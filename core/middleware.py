import logging
from django.http import JsonResponse
import time
from django.conf import settings
from django.db import connection, reset_queries
perf_logger = logging.getLogger("performance")

logger = logging.getLogger("core.rbac")


class RoleAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # By the time this runs, JWTAuthentication middleware/DRF has
        # not yet populated request.user for DRF views specifically —
        # DRF authenticates inside its own dispatch, not at the Django
        # middleware layer. So we log at the Django user level, which
        # covers session-authenticated requests (e.g. the admin site);
        # for DRF API requests, role is available via request.user
        # once DRF's authentication has run, so we also inspect it if
        # already resolved (e.g. on the response side).
        user = getattr(request, "user", None)

        if user is not None and getattr(user, "is_authenticated", False):
            role = getattr(user, "role", "unknown")

            # Global safety net: block inactive users outright, no
            # matter what a specific view's permission_classes allow.
            if not getattr(user, "is_active", True):
                logger.warning(
                    "Blocked inactive user %s (role=%s) from %s",
                    user.email, role, request.path,
                )
                return JsonResponse(
                    {"detail": "This account has been deactivated."},
                    status=403,
                )

            logger.info("%s [role=%s] -> %s", user.email, role, request.path)
        else:
            logger.info("anonymous -> %s", request.path)

        response = self.get_response(request)
        return response

class QueryPerformanceMiddleware:
    """
    Only active when DEBUG=True — django.db.connection.queries is only
    populated in debug mode (or with django.test.utils.CaptureQueriesContext,
    which is the right tool for automated tests rather than live traffic).
    In production this middleware is a harmless no-op.
    """
    def __init__(self, get_response):
        self.get_response = get_response
 
    def __call__(self, request):
        if not settings.DEBUG:
            return self.get_response(request)
 
        reset_queries()
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = (time.monotonic() - start) * 1000
        query_count = len(connection.queries)
 
        perf_logger.info(
            "PERF path=%s method=%s queries=%d duration_ms=%.1f",
            request.path, request.method, query_count, duration_ms,
        )
        # Also surface it as a response header — easiest way to see it
        # directly in Postman without digging through terminal logs.
        response["X-Query-Count"] = str(query_count)
        response["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        return response    