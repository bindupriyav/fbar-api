"""Unit tests for the GET /api/v1/fbar/filings endpoint."""

import json
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fbar_api.config import Settings
from fbar_api.routes.filings import router


def _create_test_app(filings: list[dict], token_store_path: str) -> tuple:
    """Create a lightweight test app with mocked DynamoDB service (no real AWS calls)."""
    settings = Settings(AUTH_TOKEN_STORE=token_store_path)

    app = FastAPI()
    app.state.settings = settings

    # Mock the DynamoDB service
    mock_db = MagicMock()
    mock_db.list_filings.return_value = filings
    mock_db.query_by_tax_year.return_value = []
    mock_db.query_by_tax_year_and_status.return_value = []
    mock_db.scan_by_tin.return_value = []
    mock_db.scan_by_status.return_value = []
    app.state.dynamodb_service = mock_db

    app.include_router(router)

    return TestClient(app), mock_db


def _make_token_store() -> str:
    """Create a temp token store file and return its path."""
    future_expiry = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    tokens = {
        "test-read-token": {
            "subject": "test-analyst",
            "scopes": ["fbar:read"],
            "case_ids": ["CASE-001", "CASE-002"],
            "expires_at": future_expiry,
        },
        "test-no-cases-token": {
            "subject": "test-no-cases",
            "scopes": ["fbar:read"],
            "case_ids": [],
            "expires_at": future_expiry,
        },
    }
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(tokens, tmp)
    tmp.close()
    return tmp.name


SAMPLE_FILINGS = [
    {"bsaId": "31000000000003", "taxYear": 2023, "filingStatus": "Accepted", "filer": {"tin": {"value": "900-12-3456"}}},
    {"bsaId": "31000000000001", "taxYear": 2022, "filingStatus": "Rejected", "filer": {"tin": {"value": "900-99-8888"}}},
    {"bsaId": "31000000000002", "taxYear": 2023, "filingStatus": "Pending", "filer": {"tin": {"value": "98-1234567"}}},
    {"bsaId": "31000000000005", "taxYear": 2021, "filingStatus": "Accepted", "filer": {"tin": {"value": "900-12-3456"}}, "caseId": "CASE-001"},
    {"bsaId": "31000000000004", "taxYear": 2022, "filingStatus": "Pending", "filer": {"tin": {"value": "900-55-4321"}}, "caseId": "CASE-999"},
]

AUTH_HEADER = {"Authorization": "Bearer test-read-token"}


class TestListFilingsEndpoint:
    """Tests for GET /api/v1/fbar/filings."""

    def setup_method(self):
        self.token_store_path = _make_token_store()

    def test_returns_paginated_filings_with_defaults(self):
        """Validates Req 1.1, 1.2: Default pagination (page=1, pageSize=25) and sorted by bsaId."""
        client, mock_db = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get("/api/v1/fbar/filings", headers=AUTH_HEADER)

        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 1
        assert body["pageSize"] == 25
        # Row-level filtering: CASE-999 is not in caller's case_ids
        # So filing with bsaId 31000000000004 should be excluded
        assert body["totalRecords"] == 4
        # Verify ascending bsaId order
        bsa_ids = [item["bsaId"] for item in body["data"]]
        assert bsa_ids == sorted(bsa_ids)

    def test_custom_pagination_params(self):
        """Validates Req 1.3: Custom page and pageSize are respected."""
        client, mock_db = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings?page=1&pageSize=2", headers=AUTH_HEADER
        )

        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 1
        assert body["pageSize"] == 2
        assert len(body["data"]) == 2
        assert body["totalRecords"] == 4
        assert body["totalPages"] == 2

    def test_page_beyond_total_returns_empty_data(self):
        """Validates Req 1.5: Page exceeding total returns empty data array."""
        client, mock_db = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings?page=100&pageSize=25", headers=AUTH_HEADER
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["totalRecords"] == 4
        assert body["totalPages"] == 1

    def test_invalid_page_returns_400(self):
        """Validates Req 1.6: Invalid page parameter returns 400."""
        client, _ = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings?page=0", headers=AUTH_HEADER
        )
        assert response.status_code == 400

    def test_invalid_page_size_returns_400(self):
        """Validates Req 1.6: Invalid pageSize parameter returns 400."""
        client, _ = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings?pageSize=200", headers=AUTH_HEADER
        )
        assert response.status_code == 400

    def test_filter_by_tax_year(self):
        """Validates Req 3.1: Filtering by taxYear queries GSI and returns matching filings."""
        filings_2023 = [f for f in SAMPLE_FILINGS if f["taxYear"] == 2023]
        client, mock_db = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        mock_db.query_by_tax_year.return_value = filings_2023

        response = client.get(
            "/api/v1/fbar/filings?taxYear=2023", headers=AUTH_HEADER
        )

        assert response.status_code == 200
        body = response.json()
        mock_db.query_by_tax_year.assert_called_once_with(2023)
        assert body["totalRecords"] == 2

    def test_filter_by_tax_year_and_status(self):
        """Validates Req 5.4: Filtering by taxYear + filingStatus uses combined GSI query."""
        matched = [f for f in SAMPLE_FILINGS if f["taxYear"] == 2023 and f["filingStatus"] == "Accepted"]
        client, mock_db = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        mock_db.query_by_tax_year_and_status.return_value = matched

        response = client.get(
            "/api/v1/fbar/filings?taxYear=2023&filingStatus=Accepted", headers=AUTH_HEADER
        )

        assert response.status_code == 200
        body = response.json()
        mock_db.query_by_tax_year_and_status.assert_called_once_with(2023, "Accepted")
        assert body["totalRecords"] == 1

    def test_filter_by_tin(self):
        """Validates Req 4.1: Filtering by TIN performs scan."""
        matched = [f for f in SAMPLE_FILINGS if f["filer"]["tin"]["value"] == "900-12-3456"]
        client, mock_db = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        mock_db.scan_by_tin.return_value = matched

        response = client.get(
            "/api/v1/fbar/filings?tin=900-12-3456", headers=AUTH_HEADER
        )

        assert response.status_code == 200
        body = response.json()
        mock_db.scan_by_tin.assert_called_once_with("900-12-3456")

    def test_filter_by_status_only(self):
        """Validates Req 5.5: Filtering by filingStatus alone performs scan."""
        matched = [f for f in SAMPLE_FILINGS if f["filingStatus"] == "Pending"]
        client, mock_db = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        mock_db.scan_by_status.return_value = matched

        response = client.get(
            "/api/v1/fbar/filings?filingStatus=Pending", headers=AUTH_HEADER
        )

        assert response.status_code == 200
        body = response.json()
        mock_db.scan_by_status.assert_called_once_with("Pending")

    def test_invalid_tax_year_format_returns_400(self):
        """Validates Req 3.2: Non-4-digit taxYear returns 400."""
        client, _ = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings?taxYear=abc", headers=AUTH_HEADER
        )
        assert response.status_code == 400

    def test_invalid_tax_year_range_returns_422(self):
        """Validates Req 3.3: Out-of-range taxYear returns 422."""
        client, _ = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings?taxYear=1990", headers=AUTH_HEADER
        )
        assert response.status_code == 422

    def test_invalid_tin_format_returns_400(self):
        """Validates Req 4.2: Invalid TIN format returns 400."""
        client, _ = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings?tin=123-45-6789", headers=AUTH_HEADER
        )
        assert response.status_code == 400

    def test_invalid_filing_status_returns_400(self):
        """Validates Req 5.2: Invalid filingStatus returns 400."""
        client, _ = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings?filingStatus=InvalidStatus", headers=AUTH_HEADER
        )
        assert response.status_code == 400

    def test_row_level_filtering_excludes_unauthorized_filings(self):
        """Validates Req 11.4: Filings with caseId not in caller's context are excluded."""
        client, mock_db = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get("/api/v1/fbar/filings", headers=AUTH_HEADER)

        assert response.status_code == 200
        body = response.json()
        # Filing with caseId CASE-999 should be excluded (not in caller's case_ids)
        for filing in body["data"]:
            if filing.get("caseId"):
                assert filing["caseId"] in ["CASE-001", "CASE-002"]

    def test_caller_with_no_cases_only_sees_unlinked_filings(self):
        """Validates Req 11.5: Empty case list allows access only to filings without caseId."""
        client, _ = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get(
            "/api/v1/fbar/filings",
            headers={"Authorization": "Bearer test-no-cases-token"},
        )

        assert response.status_code == 200
        body = response.json()
        # Only filings without caseId should be visible
        for filing in body["data"]:
            assert filing.get("caseId") is None

    def test_no_auth_returns_401(self):
        """Validates Req 9.1: Missing Authorization header returns 401."""
        client, _ = _create_test_app(SAMPLE_FILINGS, self.token_store_path)
        response = client.get("/api/v1/fbar/filings")
        assert response.status_code == 401

    def test_empty_results_return_correct_envelope(self):
        """Validates Req 4.3, 5.3: Empty results return valid pagination envelope."""
        client, mock_db = _create_test_app([], self.token_store_path)
        response = client.get("/api/v1/fbar/filings", headers=AUTH_HEADER)

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["totalRecords"] == 0
        assert body["totalPages"] == 0
        assert body["page"] == 1
        assert body["pageSize"] == 25
