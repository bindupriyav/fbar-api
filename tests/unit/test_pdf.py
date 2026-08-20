"""Unit tests for the GET /api/v1/fbar/filings/{bsaId}/pdf endpoint."""

import json
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
def token_file(tmp_path):
    """Create a temporary token store file."""
    tokens = {
        "valid-read-token": {
            "subject": "test-user",
            "scopes": ["fbar:read"],
            "case_ids": ["CASE-001", "CASE-002"],
            "expires_at": "2026-12-31T23:59:59Z",
        },
        "no-scope-token": {
            "subject": "no-scope-user",
            "scopes": [],
            "case_ids": [],
            "expires_at": "2026-12-31T23:59:59Z",
        },
    }
    token_path = tmp_path / "tokens.json"
    token_path.write_text(json.dumps(tokens))
    return str(token_path)


@pytest.fixture
def settings(token_file) -> Settings:
    """Create test settings."""
    return Settings(
        DYNAMODB_TABLE_NAME="test-table",
        S3_BUCKET_NAME="test-bucket",
        AWS_ENDPOINT_URL="http://localhost:4566",
        AUTH_TOKEN_STORE=token_file,
    )


@pytest.fixture
def app(settings: Settings):
    """Create a FastAPI app with mocked services."""
    application = create_app(settings)
    mock_dynamodb = MagicMock()
    mock_s3 = MagicMock()
    application.state.dynamodb_service = mock_dynamodb
    application.state.s3_service = mock_s3
    return application


@pytest.fixture
def client(app) -> TestClient:
    """Create a synchronous test client (follow_redirects=False to inspect 302)."""
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def auth_headers():
    """Return valid Authorization headers."""
    return {"Authorization": "Bearer valid-read-token"}


@pytest.fixture
def sample_filing_with_pdf():
    """A filing record with a pdfDocument."""
    return {
        "bsaId": "31000000000001",
        "recordType": "FILING",
        "filingStatus": "Accepted",
        "taxYear": 2023,
        "caseId": "CASE-001",
        "pdfDocument": {
            "fileName": "FBAR_31000000000001.pdf",
            "s3Bucket": "irs-cm-fbar-documents-dev",
            "s3Key": "fbar-pdfs/2023/FBAR_31000000000001.pdf",
            "contentType": "application/pdf",
            "sizeBytes": 125000,
            "sha256": "abc123def456",
        },
    }


@pytest.fixture
def sample_filing_without_pdf():
    """A filing record without a pdfDocument."""
    return {
        "bsaId": "31000000000002",
        "recordType": "FILING",
        "filingStatus": "Pending",
        "taxYear": 2023,
        "caseId": "CASE-001",
        "pdfDocument": None,
    }


class TestGetFilingPdf:
    """Tests for GET /api/v1/fbar/filings/{bsaId}/pdf."""

    def test_returns_302_with_presigned_url(
        self, app, client, auth_headers, sample_filing_with_pdf
    ):
        """Returns 302 redirect to presigned URL when filing has PDF (Req 7.1)."""
        app.state.dynamodb_service.get_filing.return_value = sample_filing_with_pdf
        app.state.s3_service.object_exists.return_value = True
        app.state.s3_service.generate_presigned_url.return_value = (
            "https://s3.amazonaws.com/irs-cm-fbar-documents-dev/fbar-pdfs/2023/FBAR_31000000000001.pdf?signature=abc"
        )

        response = client.get(
            "/api/v1/fbar/filings/31000000000001/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 302
        assert "location" in response.headers
        assert "s3.amazonaws.com" in response.headers["location"]

    def test_presigned_url_generated_with_10_min_ttl(
        self, app, client, auth_headers, sample_filing_with_pdf
    ):
        """Verifies presigned URL is generated with 600 second TTL (Req 7.1)."""
        app.state.dynamodb_service.get_filing.return_value = sample_filing_with_pdf
        app.state.s3_service.object_exists.return_value = True
        app.state.s3_service.generate_presigned_url.return_value = "https://example.com/presigned"

        client.get(
            "/api/v1/fbar/filings/31000000000001/pdf",
            headers=auth_headers,
        )

        app.state.s3_service.generate_presigned_url.assert_called_once_with(
            "irs-cm-fbar-documents-dev",
            "fbar-pdfs/2023/FBAR_31000000000001.pdf",
            ttl_seconds=600,
        )

    def test_response_headers_content_type_and_cache_control(
        self, app, client, auth_headers, sample_filing_with_pdf
    ):
        """Returns Content-Type: application/pdf and Cache-Control: no-store (Req 7.2)."""
        app.state.dynamodb_service.get_filing.return_value = sample_filing_with_pdf
        app.state.s3_service.object_exists.return_value = True
        app.state.s3_service.generate_presigned_url.return_value = "https://example.com/presigned"

        response = client.get(
            "/api/v1/fbar/filings/31000000000001/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 302
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["cache-control"] == "no-store"

    def test_returns_404_not_found_when_filing_missing(
        self, app, client, auth_headers
    ):
        """Returns 404 with not_found error when filing doesn't exist (Req 7.3)."""
        app.state.dynamodb_service.get_filing.return_value = None

        response = client.get(
            "/api/v1/fbar/filings/31000000000099/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["error"] == "not_found"
        assert "traceId" in body["detail"]

    def test_returns_404_pdf_not_found_when_pdf_document_null(
        self, app, client, auth_headers, sample_filing_without_pdf
    ):
        """Returns 404 with pdf_not_found when pdfDocument is null (Req 7.4)."""
        app.state.dynamodb_service.get_filing.return_value = sample_filing_without_pdf

        response = client.get(
            "/api/v1/fbar/filings/31000000000002/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["error"] == "pdf_not_found"
        assert "No PDF document" in body["detail"]["message"]

    def test_returns_404_pdf_not_found_when_pdf_document_missing_key(
        self, app, client, auth_headers
    ):
        """Returns 404 with pdf_not_found when filing has no pdfDocument key (Req 7.4)."""
        filing = {
            "bsaId": "31000000000003",
            "recordType": "FILING",
            "filingStatus": "Accepted",
            "taxYear": 2023,
            "caseId": "CASE-001",
            # no pdfDocument key at all
        }
        app.state.dynamodb_service.get_filing.return_value = filing

        response = client.get(
            "/api/v1/fbar/filings/31000000000003/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["error"] == "pdf_not_found"

    def test_returns_404_pdf_not_found_when_s3_object_missing(
        self, app, client, auth_headers, sample_filing_with_pdf
    ):
        """Returns 404 with pdf_not_found when S3 object does not exist (Req 7.5)."""
        app.state.dynamodb_service.get_filing.return_value = sample_filing_with_pdf
        app.state.s3_service.object_exists.return_value = False

        response = client.get(
            "/api/v1/fbar/filings/31000000000001/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["error"] == "pdf_not_found"
        assert "not found in storage" in body["detail"]["message"]

    def test_returns_403_when_row_access_denied(
        self, app, client, auth_headers
    ):
        """Returns 403 when caller lacks access to filing's case (Req 7.6)."""
        filing = {
            "bsaId": "31000000000010",
            "caseId": "CASE-RESTRICTED",  # Not in caller's case_ids
            "pdfDocument": {
                "s3Bucket": "bucket",
                "s3Key": "key.pdf",
            },
        }
        app.state.dynamodb_service.get_filing.return_value = filing

        response = client.get(
            "/api/v1/fbar/filings/31000000000010/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 403
        body = response.json()
        assert body["detail"]["error"] == "forbidden"

    def test_returns_400_for_invalid_bsa_id(self, client, auth_headers):
        """Returns 400 with bad_request if bsaId is not 14-digit numeric (Req 7.7)."""
        response = client.get(
            "/api/v1/fbar/filings/abc123/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"

    def test_returns_400_for_short_bsa_id(self, client, auth_headers):
        """Returns 400 for bsaId shorter than 14 digits (Req 7.7)."""
        response = client.get(
            "/api/v1/fbar/filings/1234567890123/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"

    def test_returns_400_for_alphanumeric_bsa_id(self, client, auth_headers):
        """Returns 400 for bsaId with alphabetic characters (Req 7.7)."""
        response = client.get(
            "/api/v1/fbar/filings/3100000000000A/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"

    def test_returns_401_without_auth_header(self, client):
        """Returns 401 when Authorization header is missing (Req 9.1)."""
        response = client.get("/api/v1/fbar/filings/31000000000001/pdf")

        assert response.status_code == 401

    def test_returns_403_without_fbar_read_scope(self, client):
        """Returns 403 when caller lacks fbar:read scope (Req 10.1)."""
        response = client.get(
            "/api/v1/fbar/filings/31000000000001/pdf",
            headers={"Authorization": "Bearer no-scope-token"},
        )

        assert response.status_code == 403

    def test_allows_access_to_filing_with_no_case_id(
        self, app, client, auth_headers
    ):
        """Returns 302 for filing with no caseId (accessible to any scoped caller, Req 11.2)."""
        filing = {
            "bsaId": "31000000000005",
            "caseId": None,
            "pdfDocument": {
                "s3Bucket": "irs-cm-fbar-documents-dev",
                "s3Key": "fbar-pdfs/2023/FBAR_31000000000005.pdf",
            },
        }
        app.state.dynamodb_service.get_filing.return_value = filing
        app.state.s3_service.object_exists.return_value = True
        app.state.s3_service.generate_presigned_url.return_value = "https://example.com/presigned"

        response = client.get(
            "/api/v1/fbar/filings/31000000000005/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 302

    def test_s3_object_exists_called_with_correct_params(
        self, app, client, auth_headers, sample_filing_with_pdf
    ):
        """Verifies S3 object_exists is called with correct bucket and key."""
        app.state.dynamodb_service.get_filing.return_value = sample_filing_with_pdf
        app.state.s3_service.object_exists.return_value = True
        app.state.s3_service.generate_presigned_url.return_value = "https://example.com/presigned"

        client.get(
            "/api/v1/fbar/filings/31000000000001/pdf",
            headers=auth_headers,
        )

        app.state.s3_service.object_exists.assert_called_once_with(
            "irs-cm-fbar-documents-dev",
            "fbar-pdfs/2023/FBAR_31000000000001.pdf",
        )
