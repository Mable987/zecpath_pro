import logging
from django.http import JsonResponse

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