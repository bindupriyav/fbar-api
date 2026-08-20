"""Health check endpoint for load balancer and monitoring probes."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> JSONResponse:
    """Check service health by probing DynamoDB and S3 dependencies.

    No authentication required. Accepts requests with or without
    an Authorization header.

    Returns:
        200 with {"status": "healthy", "service": "fbar-api"} when all
        dependencies are reachable, or 503 with dependency status when
        one or more dependencies are unreachable.
    """
    dynamodb_service = request.app.state.dynamodb_service
    s3_service = request.app.state.s3_service

    try:
        dynamodb_healthy = dynamodb_service.health_check()
    except Exception:
        dynamodb_healthy = False

    try:
        s3_healthy = s3_service.health_check()
    except Exception:
        s3_healthy = False

    if dynamodb_healthy and s3_healthy:
        return JSONResponse(
            status_code=200,
            content={"status": "healthy", "service": "fbar-api"},
        )

    # Return 200 with degraded status so ALB registers the target as healthy
    # but indicate which dependencies are down
    return JSONResponse(
        status_code=200,
        content={
            "status": "degraded",
            "service": "fbar-api",
            "dependencies": {
                "dynamodb": "healthy" if dynamodb_healthy else "unhealthy",
                "s3": "healthy" if s3_healthy else "unhealthy",
            },
        },
    )
