"""Unit tests for bearer token authentication dependency."""

import json
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi import Depends

from fbar_api.auth.bearer import CallerContext, verify_bearer_token
from fbar_api.config import Settings


def _create_app_with_token_store(token_store_path: str) -> FastAPI:
    """Helper to create a test app with the auth dependency."""
    settings = Settings(AUTH_TOKEN_STORE=token_store_path)
    app = FastAPI()
    app.state.settings = settings

    @app.get("/protected")
    async def protected_route(caller: CallerContext = Depends(verify_bearer_token)):
        return {
            "subject": caller.subject,
            "scopes": list(caller.scopes),
            "case_ids": caller.case_ids,
        }

    return app


def _write_token_store(tokens: dict) -> str:
    """Write a token store to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(tokens, tmp)
    tmp.close()
    return tmp.name


class TestCallerContext:
    """Tests for CallerContext dataclass."""

    def test_default_values(self):
        ctx = CallerContext(subject="user-1")
        assert ctx.subject == "user-1"
        assert ctx.scopes == set()
        assert ctx.case_ids == []

    def test_full_initialization(self):
        ctx = CallerContext(
            subject="analyst-jane",
            scopes={"fbar:read", "fbar:write"},
            case_ids=["CASE-001", "CASE-002"],
        )
        assert ctx.subject == "analyst-jane"
        assert ctx.scopes == {"fbar:read", "fbar:write"}
        assert ctx.case_ids == ["CASE-001", "CASE-002"]


class TestVerifyBearerToken:
    """Tests for verify_bearer_token dependency."""

    def setup_method(self):
        """Set up test token store for each test."""
        future_expiry = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        past_expiry = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        self.tokens = {
            "valid-token": {
                "subject": "test-user",
                "scopes": ["fbar:read"],
                "case_ids": ["CASE-001"],
                "expires_at": future_expiry,
            },
            "expired-token": {
                "subject": "expired-user",
                "scopes": ["fbar:read"],
                "case_ids": [],
                "expires_at": past_expiry,
            },
            "no-expiry-token": {
                "subject": "no-expiry-user",
                "scopes": ["fbar:read", "fbar:write"],
                "case_ids": ["CASE-002"],
            },
        }
        self.token_store_path = _write_token_store(self.tokens)
        self.app = _create_app_with_token_store(self.token_store_path)
        self.client = TestClient(self.app)

    def test_valid_token_returns_caller_context(self):
        response = self.client.get(
            "/protected", headers={"Authorization": "Bearer valid-token"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["subject"] == "test-user"
        assert body["scopes"] == ["fbar:read"]
        assert body["case_ids"] == ["CASE-001"]

    def test_missing_authorization_header_returns_401(self):
        response = self.client.get("/protected")
        assert response.status_code == 401
        body = response.json()["detail"]
        assert body["error"] == "unauthorized"
        assert "missing" in body["message"].lower()
        assert "traceId" in body

    def test_non_bearer_prefix_returns_401(self):
        response = self.client.get(
            "/protected", headers={"Authorization": "Basic abc123"}
        )
        assert response.status_code == 401
        body = response.json()["detail"]
        assert body["error"] == "unauthorized"
        assert "Bearer" in body["message"]

    def test_empty_bearer_token_returns_401(self):
        response = self.client.get(
            "/protected", headers={"Authorization": "Bearer "}
        )
        assert response.status_code == 401
        body = response.json()["detail"]
        assert body["error"] == "unauthorized"
        assert "empty" in body["message"].lower()

    def test_unrecognized_token_returns_401(self):
        response = self.client.get(
            "/protected", headers={"Authorization": "Bearer unknown-token-xyz"}
        )
        assert response.status_code == 401
        body = response.json()["detail"]
        assert body["error"] == "unauthorized"
        assert "not recognized" in body["message"].lower()

    def test_expired_token_returns_401(self):
        response = self.client.get(
            "/protected", headers={"Authorization": "Bearer expired-token"}
        )
        assert response.status_code == 401
        body = response.json()["detail"]
        assert body["error"] == "unauthorized"
        assert "expired" in body["message"].lower()

    def test_token_without_expiry_is_valid(self):
        response = self.client.get(
            "/protected", headers={"Authorization": "Bearer no-expiry-token"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["subject"] == "no-expiry-user"
        assert set(body["scopes"]) == {"fbar:read", "fbar:write"}

    def test_trace_id_is_unique_across_errors(self):
        r1 = self.client.get("/protected")
        r2 = self.client.get("/protected")
        trace1 = r1.json()["detail"]["traceId"]
        trace2 = r2.json()["detail"]["traceId"]
        assert trace1 != trace2

    def test_error_response_format(self):
        response = self.client.get("/protected")
        body = response.json()["detail"]
        # Must have exactly these three fields
        assert set(body.keys()) == {"error", "message", "traceId"}
        assert body["error"] == "unauthorized"
        assert isinstance(body["message"], str)
        assert len(body["traceId"]) == 36  # UUID format
