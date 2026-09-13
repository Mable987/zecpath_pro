import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status as drf_status
 
logger = logging.getLogger("core.errors")
 
 
def custom_exception_handler(exc, context):
    # Let DRF build its normal response first (handles ValidationError,
    # NotAuthenticated, PermissionDenied, NotFound, etc. correctly)
    response = exception_handler(exc, context)
 
    if response is not None:
        # Reshape DRF's default {"detail": ...} or field-error dict into
        # our standard envelope, without losing any information.
        detail = response.data
 
        if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
            message = str(detail["detail"])
            errors = None
        else:
            message = "One or more fields failed validation."
            errors = detail
 
        response.data = {
            "success": False,
            "status_code": response.status_code,
            "message": message,
            "errors": errors,
        }
        return response
 
    # response is None means DRF didn't recognize the exception at all —
    # this is an UNHANDLED error that would otherwise become a raw 500
    # with a full stack trace leaking to the client. Log it fully on the
    # server side, but return a safe, generic message to the client.
    logger.exception("Unhandled exception: %s", exc, extra={"context": context})
 
    return Response(
        {
            "success": False,
            "status_code": drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "message": "An unexpected error occurred. Please try again later.",
            "errors": None,
        },
        status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
    )