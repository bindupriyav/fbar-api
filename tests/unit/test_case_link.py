"""Unit tests for the POST /api/v1/fbar/filings/{bsaId}/case-link endpoint.

Validates Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
"""

import json
import tempfile
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
def token_store_file(tmp_path):
    """Create a temporary token store JSON file."""
    tokens = {
        "write-token": {
            "subject": "supervisor-bob",
            "scopes": ["fbar:read", "fbar:write"],
            "case_ids": ["CASE-001", "CASE-002"],
            "expires_at": "2026-12-31T23:59:59Z",
        },
        "read-only-token": {
            "subject": "analyst-jane",
            "scopes": ["fbar:read"],
            "case_ids": ["CASE-001"],
            "expires_at": "2026-12-31T23:59:59Z",
        },
    }
    token_file = tmp_path / "tokens.json"
    token_file.write_text(json.dumps(tokens))
    return str(token_file)


@pytest.fixture
def settings(token_store_file) -> Settings:
    """Create test settings."""
    return Settings(
        DYNAMODB_TABLE_NAME="test-table",
        S3_BUCKET_NAME="test-bucket",
        AWS_ENDPOINT_URL="http://localhost:4566",
        AUTH_TOKEN_STORE=token_store_file,
    )


@pytest.fixture
def mock_dynamodb():
    """Create a mock DynamoDB service."""
    return MagicMock()


@pytest.fixture
def app(settings, mock_dynamodb):
    """Create a FastAPI app with mocked services."""
    application = create_app(settings)
    application.state.dynamodb_service = mock_dynamodb
    application.state.s3_service = MagicMock()
    return application


@pytest.fixture
def client(app) -> TestClient:
    """Create a synchronous test client."""
    return TestClient(app)


WRITE_AUTH = {"Authorization": "Bearer write-token"}
READ_AUTH = {"Authorization": "Bearer read-only-token"}
VALID_BSA_ID = "31000000000001"


class TestCaseLinkSuccess:
    """Tests for successful case-link creation (Req 8.1, 8.2, 8.6)."""

    def test_new_link_returns_200_with_updated_filing(self, mock_dynamodb, client):
        """POST case-link with valid caseId on unlinked filing returns 200."""
        # Filing exists without a caseId
        filing = {"bsaId": VALID_BSA_ID, "recordType": "FILING", "filingStatus": "Accepted"}
        mock_dynamodb.get_filing.return_value = filing

        # DynamoDB returns updated filing with caseId and updatedAt
        updated_filing = {
            **filing,
            "caseId": "CASE-NEW-001",
            "updatedAt": "2024-01-15T10:30:00Z",
        }
        mock_dynamodb.update_case_link.return_value = updated_filing

        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": "CASE-NEW-001"},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["caseId"] == "CASE-NEW-001"
        assert "updatedAt" in body
        mock_dynamodb.update_case_link.assert_called_once_with(VALID_BSA_ID, "CASE-NEW-001")

    def test_updated_at_is_utc_iso8601(self, mock_dynamodb, client):
        """Req 8.6: updatedAt is set to UTC ISO-8601 format on new link."""
        filing = {"bsaId": VALID_BSA_ID, "recordType": "FILING"}
        mock_dynamodb.get_filing.return_value = filing

        updated_filing = {
            **filing,
            "caseId": "CASE-001",
            "updatedAt": "2024-06-15T14:30:00Z",
        }
        mock_dynamodb.update_case_link.return_value = updated_filing

        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": "CASE-001"},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 200
        body = response.json()
        # Verify ISO-8601 UTC format (ends with Z)
        assert body["updatedAt"].endswith("Z")


class TestCaseLinkNotFound:
    """Tests for filing not found (Req 8.3)."""

    def test_nonexistent_bsa_id_returns_404(self, mock_dynamodb, client):
        """POST case-link on non-existent bsaId returns 404 not_found."""
        mock_dynamodb.get_filing.return_value = None

        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": "CASE-001"},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["error"] == "not_found"
        assert "traceId" in body["detail"]


class TestCaseLinkConflict:
    """Tests for conflict detection (Req 8.4)."""

    def test_different_case_id_returns_409(self, mock_dynamodb, client):
        """POST case-link with different caseId on already-linked filing returns 409."""
        # Filing already linked to CASE-001 (which is in caller's case_ids)
        filing = {
            "bsaId": VALID_BSA_ID,
            "recordType": "FILING",
            "caseId": "CASE-001",
        }
        mock_dynamodb.get_filing.return_value = filing

        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": "CASE-002"},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 409
        body = response.json()
        assert body["detail"]["error"] == "conflict"
        assert "traceId" in body["detail"]
        # Should NOT call update
        mock_dynamodb.update_case_link.assert_not_called()


class TestCaseLinkIdempotence:
    """Tests for idempotent behavior (Req 8.5)."""

    def test_same_case_id_returns_200_without_update(self, mock_dynamodb, client):
        """POST case-link with same caseId returns 200 and does not update DynamoDB."""
        filing = {
            "bsaId": VALID_BSA_ID,
            "recordType": "FILING",
            "caseId": "CASE-001",
            "updatedAt": "2024-01-10T08:00:00Z",
        }
        mock_dynamodb.get_filing.return_value = filing

        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": "CASE-001"},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 200
        body = response.json()
        # Returns existing filing unchanged
        assert body["caseId"] == "CASE-001"
        assert body["updatedAt"] == "2024-01-10T08:00:00Z"
        # No update call
        mock_dynamodb.update_case_link.assert_not_called()


class TestCaseLinkValidation:
    """Tests for request body validation (Req 8.7)."""

    def test_missing_case_id_returns_422(self, mock_dynamodb, client):
        """POST case-link with missing caseId returns 422."""
        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 422

    def test_null_case_id_returns_422(self, mock_dynamodb, client):
        """POST case-link with null caseId returns 422."""
        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": None},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 422

    def test_empty_case_id_returns_422(self, mock_dynamodb, client):
        """POST case-link with empty caseId returns 422."""
        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": ""},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 422

    def test_case_id_over_64_chars_returns_422(self, mock_dynamodb, client):
        """POST case-link with caseId exceeding 64 chars returns 422."""
        long_case_id = "A" * 65

        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": long_case_id},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 422

    def test_invalid_bsa_id_format_returns_400(self, mock_dynamodb, client):
        """POST case-link with invalid bsaId format returns 400."""
        response = client.post(
            "/api/v1/fbar/filings/INVALID/case-link",
            json={"caseId": "CASE-001"},
            headers=WRITE_AUTH,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"


class TestCaseLinkAuth:
    """Tests for authorization (fbar:write scope required)."""

    def test_read_only_token_returns_403(self, mock_dynamodb, client):
        """POST case-link with read-only scope returns 403."""
        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": "CASE-001"},
            headers=READ_AUTH,
        )

        assert response.status_code == 403

    def test_no_auth_returns_401(self, mock_dynamodb, client):
        """POST case-link without Authorization header returns 401."""
        response = client.post(
            f"/api/v1/fbar/filings/{VALID_BSA_ID}/case-link",
            json={"caseId": "CASE-001"},
        )

        assert response.status_code == 401
