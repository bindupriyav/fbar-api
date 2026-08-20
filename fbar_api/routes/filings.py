"""Filing route handlers for the FBAR API service."""

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from fbar_api.auth.bearer import CallerContext
from fbar_api.auth.row_level import check_row_access, filter_accessible_filings
from fbar_api.auth.scopes import require_scope
from fbar_api.utils.pagination import paginate
from fbar_api.utils.validation import (
    validate_bsa_id,
    validate_filing_status,
    validate_page_params,
    validate_tax_year,
    validate_tin,
)

router = APIRouter(prefix="/api/v1/fbar")


@router.get("/filings")
async def list_filings(
    request: Request,
    caller: CallerContext = Depends(require_scope("fbar:read")),
    page: int = Query(default=1),
    pageSize: int = Query(default=25),
    taxYear: Optional[str] = Query(default=None),
    tin: Optional[str] = Query(default=None),
    filingStatus: Optional[str] = Query(default=None),
):
    """List FBAR filings with optional filters, pagination, and row-level access control.

    Accepts optional query parameters to filter filings by taxYear, tin, and/or filingStatus.
    Results are filtered by row-level access, sorted by bsaId ascending, and paginated.

    Args:
        request: The incoming FastAPI request (for accessing app state).
        caller: Authenticated caller context with fbar:read scope.
        page: Page number (default 1, must be >= 1).
        pageSize: Number of items per page (default 25, must be 1-100).
        taxYear: Optional 4-digit tax year filter.
        tin: Optional TIN filter (SSN or EIN format).
        filingStatus: Optional filing status filter (Accepted, Rejected, Pending).

    Returns:
        PaginationEnvelope containing the filtered, sorted, and paginated filing records.

    Raises:
        HTTPException: 400 if any query parameters are invalid.
        HTTPException: 422 if taxYear is out of supported range.
    """
    # 1. Validate pagination parameters
    validate_page_params(page, pageSize)

    # 2. Validate optional filter parameters
    validated_tax_year: Optional[int] = None
    if taxYear is not None:
        validated_tax_year = validate_tax_year(taxYear)

    if tin is not None:
        validate_tin(tin)

    if filingStatus is not None:
        validate_filing_status(filingStatus)

    # 3. Query DynamoDB based on filter combination
    dynamodb_service = request.app.state.dynamodb_service

    if validated_tax_year is not None and filingStatus is not None:
        # Query GSI with taxYear + filingStatus
        filings = dynamodb_service.query_by_tax_year_and_status(
            validated_tax_year, filingStatus
        )
    elif validated_tax_year is not None:
        # Query GSI with taxYear alone
        filings = dynamodb_service.query_by_tax_year(validated_tax_year)
    elif tin is not None:
        # Scan by TIN
        filings = dynamodb_service.scan_by_tin(tin)
    elif filingStatus is not None:
        # Scan by status
        filings = dynamodb_service.scan_by_status(filingStatus)
    else:
        # No filters — list all filings
        filings = dynamodb_service.list_filings()

    # 4. Apply row-level filtering
    filings = filter_accessible_filings(filings, caller)

    # 5. Sort by bsaId ascending
    filings.sort(key=lambda f: f.get("bsaId", ""))

    # 6. Paginate and return
    return paginate(filings, page, pageSize)


@router.get("/filings/{bsaId}")
async def get_single_filing(
    bsaId: str,
    request: Request,
    caller: CallerContext = Depends(require_scope("fbar:read")),
):
    """Retrieve a single FBAR filing by its BSA ID.

    Validates the bsaId format, fetches the filing from DynamoDB,
    checks row-level access, and returns the filing record.

    Args:
        bsaId: The 14-digit BSA identifier path parameter.
        request: The incoming FastAPI request (for accessing app state).
        caller: Authenticated caller context with fbar:read scope.

    Returns:
        The complete filing record as JSON with HTTP 200.

    Raises:
        HTTPException: 400 if bsaId is invalid format.
        HTTPException: 404 if filing not found.
        HTTPException: 403 if row-level access denied.
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

    # 4. Return filing dict as JSON with 200
    return filing
