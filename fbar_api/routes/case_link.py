"""Case-link route handler for the FBAR API service."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from fbar_api.auth.bearer import CallerContext
from fbar_api.auth.row_level import check_row_access
from fbar_api.auth.scopes import require_scope
from fbar_api.models.requests import CaseLinkRequest
from fbar_api.utils.validation import validate_bsa_id

router = APIRouter(prefix="/api/v1/fbar")


@router.post("/filings/{bsaId}/case-link")
async def link_filing_to_case(
    bsaId: str,
    body: CaseLinkRequest,
    request: Request,
    caller: CallerContext = Depends(require_scope("fbar:write")),
):
    """Link an FBAR filing to an investigation case.

    Associates the specified filing with a caseId. Handles idempotence
    (same caseId returns 200 without update) and conflict detection
    (different existing caseId returns 409).

    Args:
        bsaId: The 14-digit BSA identifier path parameter.
        body: Request body containing the caseId to link.
        request: The incoming FastAPI request (for accessing app state).
        caller: Authenticated caller context with fbar:write scope.

    Returns:
        The updated (or existing) filing record as JSON with HTTP 200.

    Raises:
        HTTPException: 400 if bsaId is invalid format or body validation fails.
        HTTPException: 404 if filing not found.
        HTTPException: 403 if row-level access denied.
        HTTPException: 409 if filing is already linked to a different case.
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

    # 4. Check existing caseId
    existing_case_id = filing.get("caseId")

    if existing_case_id is not None:
        if existing_case_id == body.caseId:
            # Idempotent: same caseId already linked, return existing filing without update
            return filing
        else:
            # Conflict: filing is linked to a different case
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "conflict",
                    "message": "Filing is already linked to a different case",
                    "traceId": str(uuid4()),
                },
            )

    # 5. No existing caseId — update filing with new case link
    updated_filing = dynamodb_service.update_case_link(bsaId, body.caseId)

    # 6. Return updated filing
    return updated_filing
