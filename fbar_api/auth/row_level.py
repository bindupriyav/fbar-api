"""Row-level authorization for FBAR filings."""

from uuid import uuid4

from fastapi import HTTPException

from fbar_api.auth.bearer import CallerContext


def check_row_access(filing: dict, caller: CallerContext) -> None:
    """Check if the caller has access to a specific filing based on caseId.

    If the filing has an assigned caseId, verifies it is in the caller's
    authorized case_ids list. If the filing has no caseId, allows access
    for any caller with the required scope.

    Args:
        filing: A filing dict with an optional "caseId" key.
        caller: The authenticated caller's context.

    Raises:
        HTTPException: 403 if the filing's caseId is not in caller.case_ids.
    """
    case_id = filing.get("caseId")

    # If filing has no caseId, allow access for any scoped caller
    if case_id is None:
        return None

    # If filing has a caseId, check if it's in the caller's authorized cases
    if case_id not in caller.case_ids:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "forbidden",
                "message": "Access denied: filing is assigned to a case not in your authorization context",
                "traceId": str(uuid4()),
            },
        )

    return None


def filter_accessible_filings(
    filings: list[dict], caller: CallerContext
) -> list[dict]:
    """Filter a list of filings to only those the caller can access.

    Returns filings where:
    - caseId is None/missing (accessible to all scoped callers)
    - caseId is in caller.case_ids

    Args:
        filings: List of filing dicts, each with an optional "caseId" key.
        caller: The authenticated caller's context.

    Returns:
        Filtered list containing only accessible filings.
    """
    return [
        filing
        for filing in filings
        if filing.get("caseId") is None or filing.get("caseId") in caller.case_ids
    ]
