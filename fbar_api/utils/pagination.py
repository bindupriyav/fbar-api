"""Pagination math utilities."""

import math

from fbar_api.models.responses import PaginationEnvelope


def paginate(items: list, page: int, page_size: int) -> PaginationEnvelope:
    """Apply in-memory pagination to a list of items.

    Args:
        items: The full list of items to paginate.
        page: The 1-based page number to return.
        page_size: The number of items per page.

    Returns:
        PaginationEnvelope with correct totalRecords, totalPages, page,
        pageSize, and the appropriate data slice.
    """
    total_records = len(items)

    # Special case: 0 items → totalPages = 0
    if total_records == 0:
        total_pages = 0
    else:
        total_pages = math.ceil(total_records / page_size)

    # If page exceeds total pages, return empty data
    if page > total_pages:
        data = []
    else:
        start = (page - 1) * page_size
        end = page * page_size
        data = items[start:end]

    return PaginationEnvelope(
        data=data,
        page=page,
        pageSize=page_size,
        totalRecords=total_records,
        totalPages=total_pages,
    )
