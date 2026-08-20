"""Unit tests for the GET /api/v1/fbar/filings/{bsaId}/accounts endpoint."""

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
def sample_filing_with_accounts():
    """A filing record with financial accounts."""
    return {
        "bsaId": "31000000000001",
        "recordType": "FILING",
        "filingStatus": "Accepted",
        "taxYear": 2023,
        "caseId": "CASE-001",
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
            {
                "accountNumber": "DE89370400440532013000",
                "accountType": "Securities",
                "currency": "EUR",
                "financialInstitution": {
                    "name": "Deutsche Bank AG",
                    "address": {
                        "street": "Taunusanlage 12",
                        "city": "Frankfurt",
                        "stateOrProvince": "Hessen",
                        "zipOrPostal": "60325",
                        "country": "DE",
                    },
                },
                "jointOwnerCount": 1,
                "accountClosedDuringYear": True,
                "maxAccountValueUSD": 250000.00,
            },
        ],
    }


@pytest.fixture
def sample_filing_no_accounts():
    """A filing record with no financial accounts."""
    return {
        "bsaId": "31000000000002",
        "recordType": "FILING",
        "filingStatus": "Pending",
        "taxYear": 2023,
        "caseId": "CASE-001",
        "financialAccounts": [],
    }


class TestGetAccounts:
    """Tests for GET /api/v1/fbar/filings/{bsaId}/accounts."""

    def test_returns_200_with_accounts(
        self, app, client, auth_headers, sample_filing_with_accounts
    ):
        """Returns 200 with the financialAccounts array when filing exists."""
        app.state.dynamodb_service.get_filing.return_value = (
            sample_filing_with_accounts
        )

        response = client.get(
            "/api/v1/fbar/filings/31000000000001/accounts",
            headers=auth_headers,
        )

        assert response.status_code == 200
        accounts = response.json()
        assert len(accounts) == 2
        assert accounts[0]["accountNumber"] == "CH9300762011623852957"
        assert accounts[0]["accountType"] == "Deposit"
        assert accounts[0]["currency"] == "CHF"
        assert accounts[0]["financialInstitution"]["name"] == "UBS AG"
        assert accounts[0]["jointOwnerCount"] == 0
        assert accounts[0]["accountClosedDuringYear"] is False
        assert accounts[0]["maxAccountValueUSD"] == 150000.00

    def test_returns_200_with_empty_accounts(
        self, app, client, auth_headers, sample_filing_no_accounts
    ):
        """Returns 200 with empty array when filing has no accounts (Req 6.4)."""
        app.state.dynamodb_service.get_filing.return_value = (
            sample_filing_no_accounts
        )

        response = client.get(
            "/api/v1/fbar/filings/31000000000002/accounts",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_returns_400_for_invalid_bsa_id(self, client, auth_headers):
        """Returns 400 with bad_request if bsaId is not 14-digit numeric (Req 6.3)."""
        response = client.get(
            "/api/v1/fbar/filings/abc123/accounts",
            headers=auth_headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"

    def test_returns_400_for_short_bsa_id(self, client, auth_headers):
        """Returns 400 for bsaId shorter than 14 digits."""
        response = client.get(
            "/api/v1/fbar/filings/1234567890123/accounts",
            headers=auth_headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"]["error"] == "bad_request"

    def test_returns_404_when_filing_not_found(
        self, app, client, auth_headers
    ):
        """Returns 404 with not_found if filing does not exist (Req 6.2)."""
        app.state.dynamodb_service.get_filing.return_value = None

        response = client.get(
            "/api/v1/fbar/filings/31000000000099/accounts",
            headers=auth_headers,
        )

        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["error"] == "not_found"

    def test_returns_403_when_row_access_denied(self, app, client, auth_headers):
        """Returns 403 when caller lacks access to filing's case (Req 11.1)."""
        filing = {
            "bsaId": "31000000000010",
            "caseId": "CASE-RESTRICTED",  # Not in caller's case_ids
            "financialAccounts": [],
        }
        app.state.dynamodb_service.get_filing.return_value = filing

        response = client.get(
            "/api/v1/fbar/filings/31000000000010/accounts",
            headers=auth_headers,
        )

        assert response.status_code == 403
        body = response.json()
        assert body["detail"]["error"] == "forbidden"

    def test_returns_200_for_filing_with_no_case_id(
        self, app, client, auth_headers
    ):
        """Returns 200 for filing with no caseId (accessible to any scoped caller, Req 11.2)."""
        filing = {
            "bsaId": "31000000000003",
            "caseId": None,
            "financialAccounts": [
                {
                    "accountNumber": "GB29NWBK60161331926819",
                    "accountType": "Deposit",
                    "currency": "GBP",
                    "financialInstitution": {
                        "name": "Barclays",
                        "address": {
                            "street": "1 Churchill Place",
                            "city": "London",
                            "zipOrPostal": "E14 5HP",
                            "country": "GB",
                        },
                    },
                    "jointOwnerCount": 0,
                    "accountClosedDuringYear": False,
                    "maxAccountValueUSD": 75000.00,
                }
            ],
        }
        app.state.dynamodb_service.get_filing.return_value = filing

        response = client.get(
            "/api/v1/fbar/filings/31000000000003/accounts",
            headers=auth_headers,
        )

        assert response.status_code == 200
        accounts = response.json()
        assert len(accounts) == 1
        assert accounts[0]["accountNumber"] == "GB29NWBK60161331926819"

    def test_returns_401_without_auth_header(self, client):
        """Returns 401 when Authorization header is missing (Req 9.1)."""
        response = client.get("/api/v1/fbar/filings/31000000000001/accounts")

        assert response.status_code == 401

    def test_returns_403_without_fbar_read_scope(self, client):
        """Returns 403 when caller lacks fbar:read scope (Req 10.1)."""
        response = client.get(
            "/api/v1/fbar/filings/31000000000001/accounts",
            headers={"Authorization": "Bearer no-scope-token"},
        )

        assert response.status_code == 403
