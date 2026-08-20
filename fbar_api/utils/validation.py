"""Input validation helpers for the FBAR API service.

Each validator raises fastapi.HTTPException with appropriate status code
(400 for malformed input, 422 for semantically invalid values).
"""

import re
from datetime import datetime

from fastapi import HTTPException


def validate_bsa_id(bsa_id: str) -> str:
    """Validate that bsa_id is exactly 14 decimal digit characters.

    Args:
        bsa_id: The BSA ID string to validate.

    Returns:
        The validated bsa_id string.

    Raises:
        HTTPException: 400 if bsa_id is not exactly 14 digits.
    """
    if not re.fullmatch(r"\d{14}", bsa_id):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": f"Invalid bsaId '{bsa_id}': must be exactly 14 numeric digits",
            },
        )
    return bsa_id


def validate_tax_year(year: str) -> int:
    """Validate that year is a 4-digit numeric string in [2010, current year].

    Args:
        year: The tax year string to validate.

    Returns:
        The validated tax year as an integer.

    Raises:
        HTTPException: 400 if year is not a 4-digit numeric string.
        HTTPException: 422 if year is outside the supported range.
    """
    if not re.fullmatch(r"\d{4}", year):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": f"Invalid taxYear '{year}': must be a 4-digit numeric year",
            },
        )

    year_int = int(year)
    current_year = datetime.now().year

    if year_int < 2010 or year_int > current_year:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unprocessable_entity",
                "message": (
                    f"Invalid taxYear '{year}': must be between 2010 and {current_year}"
                ),
            },
        )

    return year_int


def validate_tin(tin: str) -> str:
    """Validate that tin matches SSN pattern (900-xx-xxxx) or EIN pattern (98-xxxxxxx).

    SSN format: 900-XX-XXXX (where X is a digit)
    EIN format: 98-XXXXXXX (where X is a digit)

    Args:
        tin: The TIN string to validate.

    Returns:
        The validated TIN string.

    Raises:
        HTTPException: 400 if tin does not match SSN or EIN format.
    """
    ssn_pattern = r"900-\d{2}-\d{4}"
    ein_pattern = r"98-\d{7}"

    if not (re.fullmatch(ssn_pattern, tin) or re.fullmatch(ein_pattern, tin)):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": (
                    f"Invalid tin '{tin}': must match SSN format (900-XX-XXXX) "
                    f"or EIN format (98-XXXXXXX)"
                ),
            },
        )
    return tin


def validate_filing_status(status: str) -> str:
    """Validate that status is one of the allowed filing status values.

    Args:
        status: The filing status string to validate.

    Returns:
        The validated filing status string.

    Raises:
        HTTPException: 400 if status is not Accepted, Rejected, or Pending.
    """
    valid_statuses = {"Accepted", "Rejected", "Pending"}

    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": (
                    f"Invalid filingStatus '{status}': "
                    f"must be one of Accepted, Rejected, Pending"
                ),
            },
        )
    return status


def validate_page_params(page: int, page_size: int) -> tuple[int, int]:
    """Validate pagination parameters.

    Args:
        page: Page number (must be >= 1).
        page_size: Page size (must be between 1 and 100 inclusive).

    Returns:
        Tuple of (page, page_size) as validated integers.

    Raises:
        HTTPException: 400 if page < 1 or page_size not in [1, 100].
    """
    if not isinstance(page, int) or page < 1:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": (
                    f"Invalid page '{page}': must be a positive integer (>= 1)"
                ),
            },
        )

    if not isinstance(page_size, int) or page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": (
                    f"Invalid pageSize '{page_size}': must be an integer between 1 and 100"
                ),
            },
        )

    return page, page_size
