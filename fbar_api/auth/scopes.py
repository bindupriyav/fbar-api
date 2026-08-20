"""Scope enforcement dependency for FastAPI routes."""

from typing import Callable
from uuid import uuid4

from fastapi import Depends, HTTPException

from fbar_api.auth.bearer import CallerContext, verify_bearer_token


def require_scope(scope: str) -> Callable:
    """Factory that returns a FastAPI dependency enforcing a required scope.

    The returned dependency validates that the authenticated caller's context
    includes the specified scope. If the scope is missing, a 403 Forbidden
    response is raised with an ErrorEnvelope-compatible detail body.

    Args:
        scope: The required scope string (e.g., "fbar:read", "fbar:write").

    Returns:
        An async FastAPI dependency function that checks CallerContext.scopes.
    """

    async def _check_scope(
        caller: CallerContext = Depends(verify_bearer_token),
    ) -> CallerContext:
        if scope not in caller.scopes:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "forbidden",
                    "message": f"Insufficient permissions. Required scope: {scope}",
                    "traceId": str(uuid4()),
                    "requiredScope": scope,
                },
            )
        return caller

    return _check_scope
