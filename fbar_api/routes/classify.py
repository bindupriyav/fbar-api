"""FBAR filing classification endpoint (AI agent, callable via API)."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from fbar_api.auth.bearer import CallerContext
from fbar_api.auth.row_level import check_row_access
from fbar_api.auth.scopes import require_scope
from fbar_api.utils.validation import validate_bsa_id

router = APIRouter(prefix="/api/v1/fbar")


@router.get("/filings/{bsaId}/classify")
async def classify_filing(
    bsaId: str,
    request: Request,
    caller: CallerContext = Depends(require_scope("fbar:read")),
):
    """Classify the compliance risk of a single FBAR filing.

    Validates the BSA ID, fetches the filing, enforces row-level access, then
    runs the AI classification agent (AWS Bedrock) and returns the result.

    Args:
        bsaId: The 14-digit BSA identifier path parameter.
        request: The incoming FastAPI request.
        caller: Authenticated caller context (requires fbar:read scope).

    Returns:
        A ClassificationResult as JSON with HTTP 200.

    Raises:
        HTTPException: 400 if bsaId invalid, 404 if not found, 403 if access denied.
        BedrockError: 502 if the classification service fails or returns invalid output.
    """
    # 1. Validate bsaId format (400 on failure)
    validate_bsa_id(bsaId)

    # 2. Fetch the filing
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

    # 3. Enforce row-level access (403 on failure)
    check_row_access(filing, caller)

    # 4. Run the classification agent (BedrockError -> 502 via middleware)
    classification_service = request.app.state.classification_service
    result = classification_service.classify(filing)

    # 5. Return the validated result
    return result
