"""Unit tests for row-level authorization."""

import pytest
from fastapi import HTTPException

from fbar_api.auth.bearer import CallerContext
from fbar_api.auth.row_level import check_row_access, filter_accessible_filings


class TestCheckRowAccess:
    """Tests for check_row_access function."""

    def test_filing_with_no_case_id_allows_access(self):
        """Filing without caseId should be accessible to any scoped caller."""
        filing = {"bsaId": "31000000000001", "filingStatus": "Accepted"}
        caller = CallerContext(subject="user-1", scopes={"fbar:read"}, case_ids=[])
        # Should not raise
        result = check_row_access(filing, caller)
        assert result is None

    def test_filing_with_none_case_id_allows_access(self):
        """Filing with caseId=None should be accessible to any scoped caller."""
        filing = {"bsaId": "31000000000001", "caseId": None}
        caller = CallerContext(subject="user-1", scopes={"fbar:read"}, case_ids=["CASE-001"])
        result = check_row_access(filing, caller)
        assert result is None

    def test_filing_case_id_in_caller_case_ids_allows_access(self):
        """Filing with caseId in caller's case_ids should be accessible."""
        filing = {"bsaId": "31000000000001", "caseId": "CASE-001"}
        caller = CallerContext(
            subject="user-1", scopes={"fbar:read"}, case_ids=["CASE-001", "CASE-002"]
        )
        result = check_row_access(filing, caller)
        assert result is None

    def test_filing_case_id_not_in_caller_case_ids_raises_403(self):
        """Filing with caseId not in caller's case_ids should raise 403."""
        filing = {"bsaId": "31000000000001", "caseId": "CASE-999"}
        caller = CallerContext(
            subject="user-1", scopes={"fbar:read"}, case_ids=["CASE-001", "CASE-002"]
        )
        with pytest.raises(HTTPException) as exc_info:
            check_row_access(filing, caller)
        assert exc_info.value.status_code == 403
        detail = exc_info.value.detail
        assert detail["error"] == "forbidden"
        assert "Access denied" in detail["message"]
        assert "traceId" in detail

    def test_filing_case_id_with_empty_caller_case_ids_raises_403(self):
        """Filing with caseId when caller has empty case_ids should raise 403."""
        filing = {"bsaId": "31000000000001", "caseId": "CASE-001"}
        caller = CallerContext(subject="user-1", scopes={"fbar:read"}, case_ids=[])
        with pytest.raises(HTTPException) as exc_info:
            check_row_access(filing, caller)
        assert exc_info.value.status_code == 403

    def test_403_response_has_unique_trace_id(self):
        """Each 403 response should have a unique traceId."""
        filing = {"bsaId": "31000000000001", "caseId": "CASE-999"}
        caller = CallerContext(subject="user-1", scopes={"fbar:read"}, case_ids=[])

        with pytest.raises(HTTPException) as exc1:
            check_row_access(filing, caller)
        with pytest.raises(HTTPException) as exc2:
            check_row_access(filing, caller)

        assert exc1.value.detail["traceId"] != exc2.value.detail["traceId"]


class TestFilterAccessibleFilings:
    """Tests for filter_accessible_filings function."""

    def test_empty_filings_list(self):
        """Empty list returns empty list."""
        caller = CallerContext(subject="user-1", scopes={"fbar:read"}, case_ids=["CASE-001"])
        result = filter_accessible_filings([], caller)
        assert result == []

    def test_all_filings_without_case_id_are_returned(self):
        """Filings without caseId should all be accessible."""
        filings = [
            {"bsaId": "31000000000001"},
            {"bsaId": "31000000000002", "caseId": None},
        ]
        caller = CallerContext(subject="user-1", scopes={"fbar:read"}, case_ids=[])
        result = filter_accessible_filings(filings, caller)
        assert len(result) == 2

    def test_filings_with_matching_case_id_are_returned(self):
        """Filings with caseId in caller's case_ids should be included."""
        filings = [
            {"bsaId": "31000000000001", "caseId": "CASE-001"},
            {"bsaId": "31000000000002", "caseId": "CASE-002"},
        ]
        caller = CallerContext(
            subject="user-1", scopes={"fbar:read"}, case_ids=["CASE-001", "CASE-002"]
        )
        result = filter_accessible_filings(filings, caller)
        assert len(result) == 2

    def test_filings_with_non_matching_case_id_are_excluded(self):
        """Filings with caseId NOT in caller's case_ids should be excluded."""
        filings = [
            {"bsaId": "31000000000001", "caseId": "CASE-001"},
            {"bsaId": "31000000000002", "caseId": "CASE-999"},
        ]
        caller = CallerContext(
            subject="user-1", scopes={"fbar:read"}, case_ids=["CASE-001"]
        )
        result = filter_accessible_filings(filings, caller)
        assert len(result) == 1
        assert result[0]["bsaId"] == "31000000000001"

    def test_mixed_filings_filtered_correctly(self):
        """Mix of accessible and inaccessible filings should filter properly."""
        filings = [
            {"bsaId": "31000000000001", "caseId": None},         # accessible (no caseId)
            {"bsaId": "31000000000002", "caseId": "CASE-001"},   # accessible (in case_ids)
            {"bsaId": "31000000000003", "caseId": "CASE-999"},   # NOT accessible
            {"bsaId": "31000000000004"},                          # accessible (missing key)
            {"bsaId": "31000000000005", "caseId": "CASE-002"},   # accessible (in case_ids)
        ]
        caller = CallerContext(
            subject="user-1", scopes={"fbar:read"}, case_ids=["CASE-001", "CASE-002"]
        )
        result = filter_accessible_filings(filings, caller)
        assert len(result) == 4
        bsa_ids = [f["bsaId"] for f in result]
        assert "31000000000003" not in bsa_ids

    def test_empty_caller_case_ids_only_returns_no_case_id_filings(self):
        """Caller with empty case_ids only sees filings without caseId."""
        filings = [
            {"bsaId": "31000000000001", "caseId": None},
            {"bsaId": "31000000000002", "caseId": "CASE-001"},
            {"bsaId": "31000000000003"},
        ]
        caller = CallerContext(subject="user-1", scopes={"fbar:read"}, case_ids=[])
        result = filter_accessible_filings(filings, caller)
        assert len(result) == 2
        bsa_ids = [f["bsaId"] for f in result]
        assert "31000000000001" in bsa_ids
        assert "31000000000003" in bsa_ids
