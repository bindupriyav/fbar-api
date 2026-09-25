"""Pydantic models for FBAR classification results."""

from typing import Literal

from pydantic import BaseModel, Field

RiskTier = Literal["LOW", "REVIEW", "HIGH_RISK"]


class Flag(BaseModel):
    """A single detected compliance signal."""

    code: str
    description: str


class ClassificationResult(BaseModel):
    """Structured result of classifying an FBAR filing."""

    bsaId: str
    riskTier: RiskTier
    confidence: float = Field(ge=0.0, le=1.0)
    flags: list[Flag] = []
    explanation: str
    model: str
    generatedAt: str
