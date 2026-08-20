"""Accounts endpoint for retrieving financial accounts associated with a filing."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from fbar_api.auth.bearer import CallerContext
from fbar_api.auth.row_level import check_row_access
from fbar_api.auth.scopes import require_scope
from fbar_api.utils.validation import validate_bsa_id

router = APIRouter(prefix="/api/v1/fbar")


@router.get("/filings/{bsaId}/accounts")
async def get_accounts(
    bsaId: str,
    request: Request,
    caller: CallerContext = Depends(require_scope("fbar:read")),
) -> list:
    """Retrieve financial accounts for a specific filing.

    Validates the BSA ID, fetches the filing from DynamoDB, checks
    row-level access, and returns the financialAccounts array.

    Args:
        bsaId: The 14-digit BSA identifier path parameter.
        request: The incoming FastAPI request (used to access app services).
        caller: The authenticated caller context (requires fbar:read scope).

    Returns:
        A JSON array of financial account objects, or an empty array
        if the filing has no associated accounts.

    Raises:
        HTTPException: 400 if bsaId is invalid format.
        HTTPException: 404 if filing not found.
        HTTPException: 403 if row-level access is denied.
    """
    # 1. Validate bsaId format (raises 400 if invalid)
    validate_bsa_id(bsaId)

    # 2. Fetch filing from DynamoDB
    dynamodb_service = request.app.state.dynamodb_service
    filing = dynamodb_service.get_filing(bsaId)

    if filing is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": f"Filing not found for bsaId '{bsaId}'",
                "traceId": str(uuid4()),
            },
        )

    # 3. Check row-level access (raises 403 if denied)
    check_row_access(filing, caller)

    # 4. Return financialAccounts array (or empty [])
    return filing.get("financialAccounts", [])
