"""Error handling middleware and custom exception hierarchy."""

import logging
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom Exception Hierarchy
# ---------------------------------------------------------------------------


class FbarApiError(Exception):
    """Base exception for application-level errors.

    Subclasses define a specific HTTP status code and error code that the
    middleware uses to build an ErrorEnvelope response.
    """

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str = "An unexpected error occurred"):
        self.message = message
        super().__init__(message)


class NotFoundError(FbarApiError):
    """Raised when a requested resource (e.g., bsaId) does not exist."""

    status_code: int = 404
    error_code: str = "not_found"

    def __init__(self, message: str = "The requested resource was not found"):
        super().__init__(message)


class PdfNotFoundError(FbarApiError):
    """Raised when a filing exists but has no associated PDF."""

    status_code: int = 404
    error_code: str = "pdf_not_found"

    def __init__(self, message: str = "The requested PDF was not found"):
        super().__init__(message)


class ConflictError(FbarApiError):
    """Raised on conflicting operations (e.g., case-link to different caseId)."""

    status_code: int = 409
    error_code: str = "conflict"

    def __init__(self, message: str = "The request conflicts with the current state of the resource"):
        super().__init__(message)


class UnprocessableError(FbarApiError):
    """Raised when a request is semantically invalid (e.g., taxYear out of range)."""

    status_code: int = 422
    error_code: str = "unprocessable_entity"

    def __init__(self, message: str = "The request could not be processed"):
        super().__init__(message)


# ---------------------------------------------------------------------------
# HTTP status → error code mapping for HTTPException without structured detail
# ---------------------------------------------------------------------------

_STATUS_TO_ERROR_CODE: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "unprocessable_entity",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


# ---------------------------------------------------------------------------
# ErrorEnvelopeMiddleware
# ---------------------------------------------------------------------------


class ErrorEnvelopeMiddleware(BaseHTTPMiddleware):
    """Catches exceptions and returns standardised ErrorEnvelope JSON responses.

    Handles:
    - FbarApiError subclasses → mapped directly via their status_code/error_code
    - HTTPException → detail may be a pre-formatted dict or a plain string
    - Pydantic ValidationError → "bad_request" with validation details
    - Unhandled exceptions → "internal_error" with sanitized generic message
    """

    async def dispatch(self, request: Request, call_next):
        """Process the request, catching any unhandled errors.

        Args:
            request: The incoming HTTP request.
            call_next: Callable to pass the request to the next middleware/handler.

        Returns:
            The downstream response or an ErrorEnvelope JSONResponse.
        """
        try:
            response = await call_next(request)
            return response
        except HTTPException as exc:
            return self._handle_http_exception(exc)
        except ValidationError as exc:
            return self._handle_validation_error(exc)
        except FbarApiError as exc:
            return self._handle_fbar_api_error(exc)
        except Exception as exc:
            return self._handle_unhandled_exception(exc)

    # ------------------------------------------------------------------
    # Private helper methods
    # ------------------------------------------------------------------

    def _handle_http_exception(self, exc: HTTPException) -> JSONResponse:
        """Map an HTTPException to an ErrorEnvelope response.

        If detail is already a dict with error/message/traceId keys, it is
        returned as-is. Otherwise, a new envelope is constructed from the
        status code.
        """
        detail = exc.detail

        # Already-formatted dict from route handlers
        if isinstance(detail, dict) and "error" in detail and "message" in detail and "traceId" in detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=detail,
            )

        # Build envelope from status code and string detail
        error_code = _STATUS_TO_ERROR_CODE.get(exc.status_code, "internal_error")
        message = detail if isinstance(detail, str) else "An error occurred"
        message = self._truncate_message(message)

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": error_code,
                "message": message,
                "traceId": str(uuid4()),
            },
        )

    def _handle_validation_error(self, exc: ValidationError) -> JSONResponse:
        """Map a Pydantic ValidationError to a 400 bad_request envelope."""
        errors = exc.errors()
        if errors:
            first_error = errors[0]
            loc = " -> ".join(str(part) for part in first_error.get("loc", []))
            reason = first_error.get("msg", "invalid value")
            message = f"Invalid parameter '{loc}': {reason}"
        else:
            message = "Request validation failed"

        message = self._truncate_message(message)

        return JSONResponse(
            status_code=400,
            content={
                "error": "bad_request",
                "message": message,
                "traceId": str(uuid4()),
            },
        )

    def _handle_fbar_api_error(self, exc: FbarApiError) -> JSONResponse:
        """Map an FbarApiError subclass to its corresponding envelope."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": self._truncate_message(exc.message),
                "traceId": str(uuid4()),
            },
        )

    def _handle_unhandled_exception(self, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions with a sanitized generic message.

        Logs the real exception for debugging but never exposes stack traces,
        internal file paths, database identifiers, or upstream service details
        to the caller.
        """
        logger.exception("Unhandled exception during request processing")

        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred",
                "traceId": str(uuid4()),
            },
        )

    @staticmethod
    def _truncate_message(message: str) -> str:
        """Ensure message does not exceed 256 characters."""
        if len(message) > 256:
            return message[:253] + "..."
        return message
