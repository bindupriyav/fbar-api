"""PDF document retrieval endpoint for FBAR filings."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from fbar_api.auth.bearer import CallerContext
from fbar_api.auth.row_level import check_row_access
from fbar_api.auth.scopes import require_scope
from fbar_api.utils.validation import validate_bsa_id

router = APIRouter(prefix="/api/v1/fbar")


@router.get("/filings/{bsaId}/pdf")
async def get_filing_pdf(
    bsaId: str,
    request: Request,
    caller: CallerContext = Depends(require_scope("fbar:read")),
) -> RedirectResponse:
    """Retrieve the PDF document for a specific FBAR filing.

    Validates the BSA ID, fetches the filing, checks row-level access,
    verifies a PDF document exists, confirms the S3 object is present,
    and returns a 302 redirect to a presigned URL with a 10-minute TTL.

    Args:
        bsaId: The 14-digit BSA identifier path parameter.
        request: The incoming FastAPI request.
        caller: The authenticated caller context (requires fbar:read scope).

    Returns:
        302 redirect to a presigned S3 URL for the PDF document.

    Raises:
        HTTPException: 400 if bsaId is invalid format.
        HTTPException: 403 if caller lacks access to the filing.
        HTTPException: 404 if filing not found, no PDF associated, or S3 object missing.
    """
    # Step 1: Validate bsaId format (raises 400 if invalid)
    validate_bsa_id(bsaId)

    # Step 2: Fetch the filing from DynamoDB
    dynamodb_service = request.app.state.dynamodb_service
    filing = dynamodb_service.get_filing(bsaId)

    if filing is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": "The requested filing was not found",
                "traceId": str(uuid4()),
            },
        )

    # Step 3: Check row-level access (raises 403 if denied)
    check_row_access(filing, caller)

    # Step 4: Check if pdfDocument exists on the filing
    pdf_document = filing.get("pdfDocument")
    if pdf_document is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "pdf_not_found",
                "message": "No PDF document associated with this filing",
                "traceId": str(uuid4()),
            },
        )

    # Step 5: Extract S3 bucket and key from pdfDocument
    s3_bucket = pdf_document.get("s3Bucket")
    s3_key = pdf_document.get("s3Key")

    # Step 6: Verify the S3 object exists
    s3_service = request.app.state.s3_service
    if not s3_service.object_exists(s3_bucket, s3_key):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "pdf_not_found",
                "message": "PDF object not found in storage",
                "traceId": str(uuid4()),
            },
        )

    # Step 7: Generate presigned URL with 10-minute TTL
    url = s3_service.generate_presigned_url(s3_bucket, s3_key, ttl_seconds=600)

    # Step 8: Return 302 redirect with required headers
    return RedirectResponse(
        url=url,
        status_code=302,
        headers={
            "Content-Type": "application/pdf",
            "Cache-Control": "no-store",
        },
    )
