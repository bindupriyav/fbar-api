"""Unit tests for the GET /health endpoint."""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from fbar_api.config import Settings
from fbar_api.main import create_app


@pytest.fixture(autouse=True)
def set_aws_region(monkeypatch):
    """Set a default AWS region to prevent NoRegionError during tests."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


@pytest.fixture
def settings() -> Settings:
    """Create test settings pointing to a fake endpoint."""
    return Settings(
        DYNAMODB_TABLE_NAME="test-table",
        S3_BUCKET_NAME="test-bucket",
        AWS_ENDPOINT_URL="http://localhost:4566",
    )


@pytest.fixture
def app(settings: Settings):
    """Create a FastAPI app with mocked services on app.state."""
    application = create_app(settings)

    # Replace real services with mocks to avoid AWS calls
    mock_dynamodb = MagicMock()
    mock_s3 = MagicMock()
    application.state.dynamodb_service = mock_dynamodb
    application.state.s3_service = mock_s3

    return application


@pytest.fixture
def client(app) -> TestClient:
    """Create a synchronous test client."""
    return TestClient(app)


def test_health_returns_200_when_dependencies_healthy(app, client):
    """GET /health returns 200 with healthy status when both dependencies are up."""
    app.state.dynamodb_service.health_check.return_value = True
    app.state.s3_service.health_check.return_value = True

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "healthy", "service": "fbar-api"}


def test_health_returns_200_degraded_when_dynamodb_unhealthy(app, client):
    """GET /health returns 200 degraded when DynamoDB is unreachable."""
    app.state.dynamodb_service.health_check.return_value = False
    app.state.s3_service.health_check.return_value = True

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["service"] == "fbar-api"
    assert body["dependencies"]["dynamodb"] == "unhealthy"
    assert body["dependencies"]["s3"] == "healthy"


def test_health_returns_200_degraded_when_s3_unhealthy(app, client):
    """GET /health returns 200 degraded when S3 is unreachable."""
    app.state.dynamodb_service.health_check.return_value = True
    app.state.s3_service.health_check.return_value = False

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["dynamodb"] == "healthy"
    assert body["dependencies"]["s3"] == "unhealthy"


def test_health_returns_200_degraded_when_both_unhealthy(app, client):
    """GET /health returns 200 degraded when both dependencies are unreachable."""
    app.state.dynamodb_service.health_check.return_value = False
    app.state.s3_service.health_check.return_value = False

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["dynamodb"] == "unhealthy"
    assert body["dependencies"]["s3"] == "unhealthy"


def test_health_accepts_request_with_authorization_header(app, client):
    """GET /health works even when an Authorization header is present."""
    app.state.dynamodb_service.health_check.return_value = True
    app.state.s3_service.health_check.return_value = True

    response = client.get(
        "/health",
        headers={"Authorization": "Bearer some-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "healthy", "service": "fbar-api"}


def test_health_degraded_response_reports_dependency_status(app, client):
    """GET /health degraded response reports per-dependency status."""
    app.state.dynamodb_service.health_check.return_value = False
    app.state.s3_service.health_check.return_value = True

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert set(body["dependencies"].keys()) == {"dynamodb", "s3"}
