"""FastAPI application factory."""

from fastapi import FastAPI

from fbar_api.config import Settings, get_settings
from fbar_api.middleware import ErrorEnvelopeMiddleware, SlidingWindowRateLimiter
from fbar_api.routes.accounts import router as accounts_router
from fbar_api.routes.case_link import router as case_link_router
from fbar_api.routes.filings import router as filings_router
from fbar_api.routes.health import router as health_router
from fbar_api.routes.pdf import router as pdf_router
from fbar_api.services.dynamodb import DynamoDBService
from fbar_api.services.s3 import S3Service


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Args:
        settings: Optional Settings instance. If not provided, settings are
                  loaded from environment variables.

    Returns:
        Configured FastAPI application.
    """
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="FBAR API Service",
        description="REST API for Foreign Bank Account Report (FinCEN Form 114) filing data",
        version="1.0.0",
    )

    # Store settings in app state for dependency injection
    app.state.settings = settings

    # Initialize service instances and store on app state
    app.state.dynamodb_service = DynamoDBService(settings)
    app.state.s3_service = S3Service(settings)

    # Mount health router at root level (no auth required)
    app.include_router(health_router)

    # Mount filings router (requires fbar:read scope)
    app.include_router(filings_router)

    # Mount accounts router (requires fbar:read scope)
    app.include_router(accounts_router)

    # Mount case-link router (requires fbar:write scope)
    app.include_router(case_link_router)

    # Mount PDF router (requires fbar:read scope)
    app.include_router(pdf_router)

    # Register middleware (Starlette applies in LIFO order, so register
    # inner middleware first, outer middleware last):
    # 1. ErrorEnvelopeMiddleware (inner) - catches errors from auth/scope/routes
    app.add_middleware(ErrorEnvelopeMiddleware)
    # 2. SlidingWindowRateLimiter (outer) - processes requests first
    app.add_middleware(
        SlidingWindowRateLimiter,
        max_requests=settings.RATE_LIMIT_MAX,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )

    return app
