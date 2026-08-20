"""Sliding window rate limiter middleware."""

import logging
import math
import time
from collections import deque
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Hard defaults used when config is invalid or missing
_DEFAULT_MAX_REQUESTS = 100
_DEFAULT_WINDOW_SECONDS = 60


class SlidingWindowRateLimiter(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter.

    Tracks per-caller request timestamps in a deque. On each request the
    window is cleaned of expired entries, and if the count meets or exceeds
    the configured limit a 429 response with a Retry-After header is returned.

    Caller identity is determined by:
    - The CallerContext.subject on request.state (set by auth middleware) if present
    - Otherwise, the client's IP address (used for unauthenticated endpoints like /health)
    """

    def __init__(self, app, max_requests: int | None = None, window_seconds: int | None = None):
        """Initialize the rate limiter.

        Args:
            app: The ASGI application.
            max_requests: Maximum allowed requests per window. Falls back to
                          default 100 if None or non-positive.
            window_seconds: Sliding window duration in seconds. Falls back to
                           default 60 if None or non-positive.
        """
        super().__init__(app)
        self._max_requests = self._validate_config(
            max_requests, _DEFAULT_MAX_REQUESTS, "RATE_LIMIT_MAX"
        )
        self._window_seconds = self._validate_config(
            window_seconds, _DEFAULT_WINDOW_SECONDS, "RATE_LIMIT_WINDOW_SECONDS"
        )
        # Dict mapping caller key -> deque of request timestamps
        self._request_log: dict[str, deque[float]] = {}

    @staticmethod
    def _validate_config(value: int | None, default: int, name: str) -> int:
        """Validate a config value, returning default if invalid.

        Args:
            value: The configured value to validate.
            default: The fallback default value.
            name: Config parameter name for logging.

        Returns:
            Valid positive integer config value.
        """
        if value is None or not isinstance(value, int) or value <= 0:
            if value is not None:
                logger.warning(
                    "Invalid rate limit config %s=%r, falling back to default %d",
                    name,
                    value,
                    default,
                )
            return default
        return value

    def _get_caller_key(self, request: Request) -> str:
        """Determine the caller identity key for rate limiting.

        Uses the authenticated subject from request.state if available,
        otherwise falls back to the client IP address.

        Args:
            request: The incoming HTTP request.

        Returns:
            String key identifying the caller.
        """
        # Check if auth middleware has set a caller context on request state
        try:
            caller_context = request.state.caller_context
            if caller_context and hasattr(caller_context, "subject") and caller_context.subject:
                return f"subject:{caller_context.subject}"
        except AttributeError:
            pass

        # Fall back to client IP
        client = request.client
        if client and client.host:
            return f"ip:{client.host}"
        return "ip:unknown"

    def _clean_window(self, timestamps: deque[float], now: float) -> None:
        """Remove timestamps outside the current sliding window.

        Args:
            timestamps: Deque of request timestamps for a caller.
            now: Current time in seconds.
        """
        cutoff = now - self._window_seconds
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

    def _calculate_retry_after(self, timestamps: deque[float], now: float) -> int:
        """Calculate the Retry-After value in seconds.

        Returns the number of seconds until the oldest request in the window
        expires, clamped to [1, 3600].

        Args:
            timestamps: Deque of request timestamps for the caller.
            now: Current time in seconds.

        Returns:
            Integer seconds the caller should wait.
        """
        if not timestamps:
            return 1

        oldest = timestamps[0]
        seconds_until_expire = (oldest + self._window_seconds) - now
        # Clamp to [1, 3600]
        retry_after = max(1, min(3600, math.ceil(seconds_until_expire)))
        return retry_after

    async def dispatch(self, request: Request, call_next):
        """Process the request through the rate limiter.

        Args:
            request: The incoming HTTP request.
            call_next: Callable to pass the request to the next middleware/handler.

        Returns:
            The response from downstream, or a 429 JSONResponse if rate limited.
        """
        now = time.time()
        caller_key = self._get_caller_key(request)

        # Get or create the timestamp deque for this caller
        if caller_key not in self._request_log:
            self._request_log[caller_key] = deque()

        timestamps = self._request_log[caller_key]

        # Clean expired entries from the sliding window
        self._clean_window(timestamps, now)

        # Check if rate limit is exceeded
        if len(timestamps) >= self._max_requests:
            retry_after = self._calculate_retry_after(timestamps, now)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "message": "Rate limit exceeded. Please wait before making additional requests.",
                    "traceId": str(uuid4()),
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Record the current request timestamp
        timestamps.append(now)

        # Pass through to next middleware/handler
        response = await call_next(request)
        return response
