"""Pydantic models for API request bodies."""

from pydantic import BaseModel, Field


class CaseLinkRequest(BaseModel):
    """Request body for linking a filing to an investigation case."""

    caseId: str = Field(..., min_length=1, max_length=64)
