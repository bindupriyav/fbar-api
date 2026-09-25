"""Prompt construction for the FBAR classification agent.

Encodes the guardrails: strict JSON-only output, BSA ID citation, and
non-accusatory regulatory language.
"""

import json
from decimal import Decimal

from fbar_api.models.classification import Flag

SYSTEM_PROMPT = """You are an FBAR (FinCEN Form 114) compliance triage assistant.

Your job is to assign a compliance-review risk tier to a single FBAR filing based
on the structured filing summary and the pre-computed deterministic signals provided.

Rules you MUST follow:
- Respond with a single JSON object ONLY. Do not include any prose, markdown, or text
  outside the JSON object.
- The JSON object MUST have exactly these keys:
  {
    "riskTier": one of "LOW", "REVIEW", or "HIGH_RISK",
    "confidence": a number between 0 and 1,
    "flags": a list of objects each with "code" and "description",
    "explanation": a short string
  }
- Cite the filing's BSA ID in the explanation.
- Use non-accusatory, regulatory-appropriate language. Describe items as
  "warranting review" rather than asserting criminal wrongdoing. Do not accuse any
  person or entity of a crime.
- Base the tier on the provided signals: no elevated-risk signals suggests LOW;
  one or more moderate signals suggests REVIEW; multiple or severe signals
  (e.g., high-risk jurisdiction combined with high aggregate value or missing
  signature) suggests HIGH_RISK.
- If you assign REVIEW or HIGH_RISK, include at least one flag explaining why."""


def _json_default(obj):
    """JSON encoder fallback: render Decimal as float (DynamoDB returns Decimals)."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


class PromptBuilder:
    """Builds the system prompt and user content for the classification model."""

    @staticmethod
    def system_prompt() -> str:
        """Return the guardrailed system prompt."""
        return SYSTEM_PROMPT

    @staticmethod
    def user_content(summary: dict, signals: list[Flag]) -> str:
        """Build the user message containing the filing summary and signals.

        Args:
            summary: Output of summarize_filing.
            signals: Deterministic flags computed in code.

        Returns:
            A string payload for the model.
        """
        signals_payload = [{"code": f.code, "description": f.description} for f in signals]
        payload = {
            "bsaId": summary.get("bsaId"),
            "filingSummary": summary,
            "deterministicSignals": signals_payload,
        }
        return (
            "Classify the following FBAR filing. Consider the deterministic signals "
            "as authoritative evidence of the conditions they describe.\n\n"
            + json.dumps(payload, indent=2, default=_json_default)
        )
