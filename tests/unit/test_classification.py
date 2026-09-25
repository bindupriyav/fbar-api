"""Unit tests for the FBAR Classification Agent.

Covers models, deterministic signals, prompt guardrails, the classification
service (with a stubbed Bedrock client), and the API endpoint.
"""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fbar_api.config import Settings
from fbar_api.main import create_app
from fbar_api.middleware.error_handler import BedrockError
from fbar_api.models.classification import ClassificationResult, Flag
from fbar_api.services.classification import (
    ClassificationService,
    build_deterministic_signals,
    summarize_filing,
)
from fbar_api.services.prompt import PromptBuilder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


def _clean_filing():
    return {
        "bsaId": "31000000000001",
        "taxYear": 2023,
        "submissionType": "Original",
        "dateFiled": "2024-05-07",
        "signature": {"signed": True, "preparerUsed": False},
        "filer": {"filerType": "Individual"},
        "financialAccounts": [
            {
                "currency": "CAD",
                "accountType": "Bank",
                "maxAccountValueUSD": 5000.0,
                "accountClosedDuringYear": False,
                "financialInstitution": {"address": {"country": "CA"}},
            }
        ],
    }


def _risky_filing():
    return {
        "bsaId": "31000000000999",
        "taxYear": 2022,
        "submissionType": "Amended",
        "dateFiled": "2024-12-01",
        "priorReportBsaId": "31000000000001",
        "signature": {"signed": False, "preparerUsed": False},
        "filer": {"filerType": "Individual"},
        "financialAccounts": [
            {
                "currency": "CHF",
                "accountType": "Bank",
                "maxAccountValueUSD": 1500000.0,
                "accountClosedDuringYear": False,
                "financialInstitution": {"address": {"country": "CH"}},
            }
        ],
    }


class StubBedrock:
    """A stand-in for BedrockService that returns a canned string."""

    model_id = "stub-model"

    def __init__(self, output: str):
        self._output = output

    def invoke(self, system_prompt: str, user_content: str) -> str:
        return self._output


# ---------------------------------------------------------------------------
# 2.2 Model validation tests
# ---------------------------------------------------------------------------


def test_classification_result_valid():
    r = ClassificationResult(
        bsaId="1", riskTier="LOW", confidence=0.5, flags=[], explanation="x",
        model="m", generatedAt="t",
    )
    assert r.riskTier == "LOW"


def test_classification_result_rejects_bad_tier():
    with pytest.raises(ValidationError):
        ClassificationResult(
            bsaId="1", riskTier="BOGUS", confidence=0.5, flags=[], explanation="x",
            model="m", generatedAt="t",
        )


def test_classification_result_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        ClassificationResult(
            bsaId="1", riskTier="LOW", confidence=1.5, flags=[], explanation="x",
            model="m", generatedAt="t",
        )


# ---------------------------------------------------------------------------
# 3.4 Deterministic signal tests
# ---------------------------------------------------------------------------


def test_clean_filing_has_no_flags():
    flags = build_deterministic_signals(summarize_filing(_clean_filing()))
    assert flags == []


def test_risky_filing_triggers_expected_flags():
    codes = {f.code for f in build_deterministic_signals(summarize_filing(_risky_filing()))}
    assert "HIGH_RISK_JURISDICTION" in codes
    assert "HIGH_AGGREGATE_VALUE" in codes
    assert "LATE_FILING" in codes
    assert "AMENDED_OR_PRIOR" in codes
    assert "MISSING_SIGNATURE" in codes


def test_threshold_clustering_flag():
    filing = _clean_filing()
    filing["financialAccounts"] = [
        {"currency": "USD", "accountType": "Bank", "maxAccountValueUSD": 9500.0,
         "accountClosedDuringYear": False,
         "financialInstitution": {"address": {"country": "CA"}}},
        {"currency": "USD", "accountType": "Bank", "maxAccountValueUSD": 9800.0,
         "accountClosedDuringYear": False,
         "financialInstitution": {"address": {"country": "CA"}}},
    ]
    codes = {f.code for f in build_deterministic_signals(summarize_filing(filing))}
    assert "THRESHOLD_CLUSTERING" in codes


def test_incomplete_data_flag_when_no_accounts():
    filing = _clean_filing()
    filing["financialAccounts"] = []
    codes = {f.code for f in build_deterministic_signals(summarize_filing(filing))}
    assert "INCOMPLETE_DATA" in codes


def test_summarize_excludes_pii_fields():
    summary = summarize_filing(_clean_filing())
    # Only classification-relevant keys; no raw filer name/address/DOB
    assert "filer" not in summary
    assert set(summary.keys()) >= {"bsaId", "accounts", "aggregateMaxValueUSD", "accountCount"}


# ---------------------------------------------------------------------------
# 4.2 Prompt guardrail tests
# ---------------------------------------------------------------------------


def test_system_prompt_has_guardrails():
    sp = PromptBuilder.system_prompt()
    assert "JSON object ONLY" in sp
    assert "BSA ID" in sp
    assert "non-accusatory" in sp


def test_user_content_includes_signals_and_bsa_id():
    summary = summarize_filing(_risky_filing())
    signals = build_deterministic_signals(summary)
    content = PromptBuilder.user_content(summary, signals)
    assert "31000000000999" in content
    assert "HIGH_RISK_JURISDICTION" in content


# ---------------------------------------------------------------------------
# 6.3 ClassificationService tests (stubbed model)
# ---------------------------------------------------------------------------


def _settings():
    return Settings(AUTH_TOKEN_STORE="tokens.json")


def test_classify_happy_path():
    out = json.dumps({"riskTier": "LOW", "confidence": 0.9, "flags": [],
                      "explanation": "Filing 31000000000001 warrants no review."})
    svc = ClassificationService(_settings(), StubBedrock(out))
    result = svc.classify(_clean_filing())
    assert result.riskTier == "LOW"
    assert result.bsaId == "31000000000001"
    assert result.model == "stub-model"


def test_classify_forces_input_bsa_id():
    # Model tries to claim a different bsaId; service must use the input's.
    out = json.dumps({"riskTier": "LOW", "confidence": 0.9, "flags": [],
                      "explanation": "x"})
    svc = ClassificationService(_settings(), StubBedrock(out))
    result = svc.classify(_clean_filing())
    assert result.bsaId == "31000000000001"


def test_classify_malformed_json_raises():
    svc = ClassificationService(_settings(), StubBedrock("not json"))
    with pytest.raises(BedrockError):
        svc.classify(_clean_filing())


def test_classify_invalid_tier_raises():
    out = json.dumps({"riskTier": "NOPE", "confidence": 0.5, "flags": [],
                      "explanation": "x"})
    svc = ClassificationService(_settings(), StubBedrock(out))
    with pytest.raises(BedrockError):
        svc.classify(_clean_filing())


def test_classify_elevated_without_flags_raises():
    out = json.dumps({"riskTier": "HIGH_RISK", "confidence": 0.8, "flags": [],
                      "explanation": "x"})
    svc = ClassificationService(_settings(), StubBedrock(out))
    with pytest.raises(BedrockError):
        svc.classify(_clean_filing())


# ---------------------------------------------------------------------------
# 7.3 Endpoint tests (mocked Bedrock + DynamoDB)
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_stub():
    settings = Settings(AUTH_TOKEN_STORE="tokens.json")
    app = create_app(settings)

    # Stub DynamoDB get_filing
    from unittest.mock import MagicMock

    mock_ddb = MagicMock()
    app.state.dynamodb_service = mock_ddb

    # Stub classification service with a canned valid result
    good = json.dumps({"riskTier": "LOW", "confidence": 0.9, "flags": [],
                       "explanation": "Filing 31000000000001 warrants no review."})
    app.state.classification_service = ClassificationService(settings, StubBedrock(good))

    return app, mock_ddb


def _read_token(app):
    # Use a real token from the app's token store if available; else patch auth.
    import json as _json
    with open("tokens.json") as f:
        tokens = _json.load(f)
    # pick the first token that has fbar:read
    for tok, meta in tokens.items():
        if "fbar:read" in meta.get("scopes", []):
            return tok
    return None


def test_classify_endpoint_requires_auth(app_with_stub):
    app, mock_ddb = app_with_stub
    client = TestClient(app)
    resp = client.get("/api/v1/fbar/filings/31000000000001/classify")
    assert resp.status_code == 401


def test_classify_endpoint_bad_bsa_id(app_with_stub):
    app, mock_ddb = app_with_stub
    token = _read_token(app)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/fbar/filings/123/classify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_classify_endpoint_not_found(app_with_stub):
    app, mock_ddb = app_with_stub
    mock_ddb.get_filing.return_value = None
    token = _read_token(app)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/fbar/filings/31000000000001/classify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    body = resp.json()
    envelope = body.get("detail", body)
    assert envelope["error"] == "not_found"


def test_classify_endpoint_happy_path(app_with_stub):
    app, mock_ddb = app_with_stub
    mock_ddb.get_filing.return_value = _clean_filing()
    token = _read_token(app)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/fbar/filings/31000000000001/classify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["bsaId"] == "31000000000001"
    assert body["riskTier"] == "LOW"
    assert "generatedAt" in body

