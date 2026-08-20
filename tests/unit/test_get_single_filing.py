"""Unit tests for the GET /api/v1/fbar/filings/{bsaId} endpoint."""

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
    """Create a synchronous test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Return valid Authorization headers."""
    return {"Authorization": "Bearer valid-read-token"}


@pytest.fixture
def sample_filing():
    """A complete filing record."""
    return {
        "bsaId": "31000000000001",
        "recordType": "FILING",
        "submissionType": "Initial",
        "filingStatus": "Accepted",
        "taxYear": 2023,
        "dateFiled": "2024-04-15T10:30:00Z",
        "priorReportBsaId": None,
        "caseId": "CASE-001",
        "filer": {
            "name": {"firstName": "John", "lastName": "Doe"},
            "tin": {"type": "SSN", "value": "900-12-3456"},
            "address": {
                "street": "123 Main St",
                "city": "Anytown",
                "stateOrProvince": "CA",
                "zipOrPostal": "90210",
                "country": "US",
            },
        },
        "jointFilers": [],
        "financialAccounts": [
            {
                "accountNumber": "CH9300762011623852957",
                "accountType": "Deposit",
                "currency": "CHF",
                "financialInstitution": {
                    "name": "UBS AG",
                    "address": {
                        "street": "Bahnhofstrasse 45",
                        "city": "Zurich",
                        "stateOrProvince": None,
                        "zipOrPostal": "8001",
                        "country": "CH",
                    },
                },
                "jointOwnerCount": 0,
                "accountClosedDuringYear": False,
                "maxAccountValueUSD": 150000.00,
            },
        ],
        "signature": {
            "signerName": "John Doe",
            "dateSigned": "2024-04-15",
        },
        "pdfDocument": {
            "s3Bucket": "irs-cm-fbar-documents-dev",
            "s3Key": "fbar-pdfs/2023/FBAR_31000000000001.pdf",
        },
    }


class TestGetSingleFiling:
    """Tests for GET /api/v1/fbar/filings/{bsaId}."""

    def test_returns_200_with_complete_filing(
        self, app, client, auth_headers, sample_filing
    ):
        """Returns 200 with complete Filing record on valid bsaId (Req 2.1, 2.4)."""
        app.state.dynamodb_service.get_filing.return_value = sample_filing

        response = client.get(
            "/api/v1/fbar/filings/31000000000001",
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["bsaId"] == "31000000000001"
        assert body["submissionType"] == "Initial"
        assert body["filingStatus"] == "Accepted"
        assert body["taxYear"] == 2023
        assert body["dateFiled"] == "2024-04-15T10:30:00Z"
        assert body["filer"]["name"]["firstName"] == "John"
        assert body["filer"]["tin"]["value"] == "900-12-3456"
        assert len(body["financialAccounts"]) == 1
        assert body["signature"]["signerName"] == "John Doe"
        assert body["pdfDocument"]["s3Bucket"] == "irs-cm-fbar-documents-dev"

    def test_returns_404_when_filing_not_found(
        self, app, client, auth_headers
    ):
        """Returns 404 with not_found error when bsaId does not exist (Req 2.2)."""
        app.state.dynamodb_service.get_filing.return_value = None

        response = client.get(
            "/api/v1/fbar/filings/31000000000099",
            headers=auth_headers,
        )

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["error"] == "not_found"
        assert "31000000000099" in body["detail"]["message"]

    def test_returns_400_for_non_numeric_bsa_id(self, client, auth_headers):
        """Returns 400 with bad_request when bsaId contains non-numeric chars (Req 2.3)."""
        response = client.get(
            "/api/v1/fbar/filings/abcdefghijklmn",
            headers=auth_headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"

    def test_returns_400_for_short_bsa_id(self, client, auth_headers):
        """Returns 400 when bsaId is fewer than 14 digits (Req 2.3)."""
        response = client.get(
            "/api/v1/fbar/filings/1234567890123",
            headers=auth_headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"

    def test_returns_400_for_long_bsa_id(self, client, auth_headers):
        """Returns 400 when bsaId is more than 14 digits (Req 2.3)."""
        response = client.get(
            "/api/v1/fbar/filings/310000000000015",
            headers=auth_headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"

    def test_returns_403_when_row_access_denied(
        self, app, client, auth_headers
    ):
        """Returns 403 when filing's caseId is not in caller's case_ids (Req 11.1)."""
        filing = {
            "bsaId": "31000000000010",
            "caseId": "CASE-RESTRICTED",
            "filingStatus": "Accepted",
        }
        app.state.dynamodb_service.get_filing.return_value = filing

        response = client.get(
            "/api/v1/fbar/filings/31000000000010",
            headers=auth_headers,
        )

        assert response.status_code == 403
        body = response.json()
        assert body["detail"]["error"] == "forbidden"

    def test_returns_200_for_filing_with_no_case_id(
        self, app, client, auth_headers, sample_filing
    ):
        """Returns 200 for filing with no caseId (accessible to any scoped caller, Req 11.2)."""
        sample_filing["caseId"] = None
        app.state.dynamodb_service.get_filing.return_value = sample_filing

        response = client.get(
            "/api/v1/fbar/filings/31000000000001",
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["bsaId"] == "31000000000001"

    def test_returns_401_without_auth_header(self, client):
        """Returns 401 when Authorization header is missing (Req 9.1)."""
        response = client.get("/api/v1/fbar/filings/31000000000001")

        assert response.status_code == 401

    def test_returns_403_without_fbar_read_scope(self, client):
        """Returns 403 when caller lacks fbar:read scope (Req 10.1)."""
        response = client.get(
            "/api/v1/fbar/filings/31000000000001",
            headers={"Authorization": "Bearer no-scope-token"},
        )

        assert response.status_code == 403

    def test_response_content_type_is_json(
        self, app, client, auth_headers, sample_filing
    ):
        """Response content type is application/json (Req 2.4)."""
        app.state.dynamodb_service.get_filing.return_value = sample_filing

        response = client.get(
            "/api/v1/fbar/filings/31000000000001",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
