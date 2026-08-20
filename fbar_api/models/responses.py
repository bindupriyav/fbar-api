"""Pydantic models for API response envelopes."""

from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationEnvelope(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    data: list[T]
    page: int
    pageSize: int
    totalRecords: int
    totalPages: int


class ErrorEnvelope(BaseModel):
    """Standard error response format."""

    error: Literal[
        "not_found",
        "unauthorized",
        "forbidden",
        "bad_request",
        "conflict",
        "rate_limited",
        "internal_error",
        "service_unavailable",
        "unprocessable_entity",
        "pdf_not_found",
    ]
    message: str = Field(..., max_length=256)
    traceId: str
    requiredScope: Optional[str] = None
