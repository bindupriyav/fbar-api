"""Bearer token authentication dependency."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import Header, HTTPException, Request

from fbar_api.config import Settings


@dataclass
class CallerContext:
    """Authenticated caller's identity and authorization context."""

    subject: str
    scopes: set[str] = field(default_factory=set)
    case_ids: list[str] = field(default_factory=list)


def _load_token_store(token_store_path: str) -> dict:
    """Load the static token store from a JSON file.

    Args:
        token_store_path: File path to the tokens JSON file.

    Returns:
        Dictionary mapping token strings to their metadata.

    Raises:
        RuntimeError: If the token store file cannot be read or parsed.
    """
    path = Path(token_store_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _make_401_response(message: str) -> dict:
    """Build a 401 error envelope body."""
    return {
        "error": "unauthorized",
        "message": message,
        "traceId": str(uuid4()),
    }


async def verify_bearer_token(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> CallerContext:
    """FastAPI dependency that validates the Authorization Bearer token.

    Extracts the token from the Authorization header, validates its format,
    looks it up in the static token store, and checks expiration.

    Args:
        request: The incoming FastAPI request (used to access app settings).
        authorization: The Authorization header value.

    Returns:
        CallerContext with the authenticated caller's subject, scopes, and case_ids.

    Raises:
        HTTPException: 401 if the token is missing, malformed, unrecognized, or expired.
    """
    # Check for missing Authorization header
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail=_make_401_response("Authorization header is missing"),
        )

    # Validate "Bearer <token>" format
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail=_make_401_response(
                'Authorization header must use "Bearer <token>" format'
            ),
        )

    token = authorization[7:]  # Strip "Bearer " prefix

    # Check for empty token
    if not token or not token.strip():
        raise HTTPException(
            status_code=401,
            detail=_make_401_response("Bearer token is empty"),
        )

    # Load token store from settings
    settings: Settings = request.app.state.settings
    token_store = _load_token_store(settings.AUTH_TOKEN_STORE)

    # Look up token in the store
    token_data = token_store.get(token)
    if token_data is None:
        raise HTTPException(
            status_code=401,
            detail=_make_401_response("Bearer token is not recognized"),
        )

    # Check token expiration
    expires_at = token_data.get("expires_at")
    if expires_at:
        try:
            # Replace 'Z' suffix with '+00:00' for Python 3.10 compatibility
            iso_str = expires_at.replace("Z", "+00:00")
            expiration = datetime.fromisoformat(iso_str)
            # Ensure expiration is timezone-aware (assume UTC if naive)
            if expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expiration:
                raise HTTPException(
                    status_code=401,
                    detail=_make_401_response("Bearer token has expired"),
                )
        except ValueError:
            raise HTTPException(
                status_code=401,
                detail=_make_401_response("Bearer token has invalid expiration format"),
            )

    # Build and return caller context
    return CallerContext(
        subject=token_data["subject"],
        scopes=set(token_data.get("scopes", [])),
        case_ids=token_data.get("case_ids", []),
    )
