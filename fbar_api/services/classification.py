"""Classification service: orchestrates FBAR filing risk classification.

This module provides:
- summarize_filing: extract only classification-relevant fields from a filing
- build_deterministic_signals: compute objective compliance flags in code
- ClassificationService.classify: full workflow (added in a later task)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fbar_api.models.classification import Flag
from fbar_api.services.classification_constants import (
    CLUSTERING_BAND_USD,
    CLUSTERING_MIN_ACCOUNTS,
    FBAR_DUE_DAY,
    FBAR_DUE_MONTH,
    HIGH_AGGREGATE_VALUE_USD,
    HIGH_RISK_JURISDICTIONS,
    REPORTING_THRESHOLD_USD,
)


def _account_country(account: dict) -> str | None:
    """Extract the ISO country code for an account's financial institution."""
    fi = account.get("financialInstitution") or {}
    addr = fi.get("address") or {}
    return addr.get("country")


def summarize_filing(filing: dict) -> dict:
    """Extract only the fields relevant to classification.

    Avoids sending unnecessary PII (full address, DOB, names) to the model.

    Args:
        filing: The full filing record as stored in DynamoDB.

    Returns:
        A compact structured summary dict.
    """
    accounts_in = filing.get("financialAccounts") or []
    accounts_out: list[dict] = []
    aggregate = 0.0

    for acct in accounts_in:
        raw_value = acct.get("maxAccountValueUSD")
        try:
            value = float(raw_value) if raw_value is not None else None
        except (TypeError, ValueError):
            value = None
        if value is not None:
            aggregate += value
        accounts_out.append(
            {
                "country": _account_country(acct),
                "currency": acct.get("currency"),
                "accountType": acct.get("accountType"),
                "maxAccountValueUSD": value,
                "accountClosedDuringYear": acct.get("accountClosedDuringYear"),
            }
        )

    signature = filing.get("signature") or {}
    filer = filing.get("filer") or {}

    return {
        "bsaId": filing.get("bsaId"),
        "taxYear": filing.get("taxYear"),
        "submissionType": filing.get("submissionType"),
        "dateFiled": filing.get("dateFiled"),
        "priorReportBsaId": filing.get("priorReportBsaId"),
        "signature": {
            "signed": signature.get("signed"),
            "preparerUsed": signature.get("preparerUsed"),
        },
        "filerType": filer.get("filerType"),
        "accounts": accounts_out,
        "aggregateMaxValueUSD": round(aggregate, 2),
        "accountCount": len(accounts_out),
    }


def _is_late_filing(summary: dict) -> bool:
    """Determine whether the filing was submitted after the FBAR due date.

    FBAR for tax year Y is due by FBAR_DUE_MONTH/FBAR_DUE_DAY of year Y+1.
    """
    tax_year = summary.get("taxYear")
    date_filed = summary.get("dateFiled")
    if not tax_year or not date_filed:
        return False
    try:
        filed = datetime.strptime(date_filed, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    try:
        due = datetime(int(tax_year) + 1, FBAR_DUE_MONTH, FBAR_DUE_DAY).date()
    except (TypeError, ValueError):
        return False
    return filed > due


def build_deterministic_signals(summary: dict) -> list[Flag]:
    """Compute objective compliance flags from a filing summary.

    Each flag corresponds to a condition actually present in the summary.

    Args:
        summary: Output of summarize_filing.

    Returns:
        A list of Flag objects (possibly empty).
    """
    flags: list[Flag] = []
    accounts = summary.get("accounts") or []

    # HIGH_RISK_JURISDICTION
    high_risk_countries = sorted(
        {
            a.get("country")
            for a in accounts
            if a.get("country") in HIGH_RISK_JURISDICTIONS
        }
    )
    if high_risk_countries:
        flags.append(
            Flag(
                code="HIGH_RISK_JURISDICTION",
                description=(
                    "Accounts located in higher-risk jurisdiction(s): "
                    + ", ".join(high_risk_countries)
                ),
            )
        )

    # HIGH_AGGREGATE_VALUE
    aggregate = summary.get("aggregateMaxValueUSD") or 0.0
    if aggregate >= HIGH_AGGREGATE_VALUE_USD:
        flags.append(
            Flag(
                code="HIGH_AGGREGATE_VALUE",
                description=(
                    f"Aggregate maximum account value (${aggregate:,.2f}) meets or "
                    f"exceeds the high-value threshold (${HIGH_AGGREGATE_VALUE_USD:,.2f})."
                ),
            )
        )

    # THRESHOLD_CLUSTERING
    lower = REPORTING_THRESHOLD_USD - CLUSTERING_BAND_USD
    clustered = [
        a
        for a in accounts
        if a.get("maxAccountValueUSD") is not None
        and lower <= float(a["maxAccountValueUSD"]) < REPORTING_THRESHOLD_USD
    ]
    if len(clustered) >= CLUSTERING_MIN_ACCOUNTS:
        flags.append(
            Flag(
                code="THRESHOLD_CLUSTERING",
                description=(
                    f"{len(clustered)} accounts have values clustered just below the "
                    f"${REPORTING_THRESHOLD_USD:,.0f} reporting threshold."
                ),
            )
        )

    # LATE_FILING
    if _is_late_filing(summary):
        flags.append(
            Flag(
                code="LATE_FILING",
                description="Filing appears to have been submitted after the FBAR due date.",
            )
        )

    # AMENDED_OR_PRIOR
    submission_type = (summary.get("submissionType") or "").strip().lower()
    if submission_type == "amended" or summary.get("priorReportBsaId"):
        flags.append(
            Flag(
                code="AMENDED_OR_PRIOR",
                description="Filing is amended or references a prior report.",
            )
        )

    # MISSING_SIGNATURE
    signature = summary.get("signature") or {}
    if not signature.get("signed"):
        flags.append(
            Flag(
                code="MISSING_SIGNATURE",
                description="Signature block is missing or the filing is unsigned.",
            )
        )

    # INCOMPLETE_DATA
    incomplete_reasons: list[str] = []
    if not summary.get("filerType"):
        incomplete_reasons.append("missing filer type")
    if summary.get("accountCount", 0) == 0:
        incomplete_reasons.append("no financial accounts reported")
    for a in accounts:
        if not a.get("country"):
            incomplete_reasons.append("account missing institution country")
            break
    if incomplete_reasons:
        flags.append(
            Flag(
                code="INCOMPLETE_DATA",
                description="Data completeness issues: " + "; ".join(incomplete_reasons) + ".",
            )
        )

    return flags


class ClassificationService:
    """Orchestrates the FBAR classification workflow.

    Combines deterministic signal detection with an LLM (via BedrockService),
    then parses and validates the model output into a ClassificationResult.
    """

    def __init__(self, settings, bedrock_service) -> None:
        """Initialize the classification service.

        Args:
            settings: Application settings (used for the model id label).
            bedrock_service: A BedrockService (or compatible) with .invoke and .model_id.
        """
        self._settings = settings
        self._bedrock = bedrock_service

    def classify(self, filing: dict):
        """Classify a filing and return a validated ClassificationResult.

        Args:
            filing: The full filing record from DynamoDB.

        Returns:
            ClassificationResult.

        Raises:
            BedrockError: If the model output cannot be parsed or validated.
        """
        # Local imports to avoid heavy imports at module load and to keep the
        # signal functions above dependency-free.
        import json as _json

        from pydantic import ValidationError

        from fbar_api.models.classification import ClassificationResult
        from fbar_api.middleware.error_handler import BedrockError
        from fbar_api.services.prompt import PromptBuilder

        bsa_id = filing.get("bsaId")
        summary = summarize_filing(filing)
        signals = build_deterministic_signals(summary)

        system_prompt = PromptBuilder.system_prompt()
        user_content = PromptBuilder.user_content(summary, signals)

        raw = self._bedrock.invoke(system_prompt, user_content)

        # Parse model output as JSON (tolerate leading/trailing whitespace only).
        try:
            data = _json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise BedrockError("Model output was not valid JSON") from exc

        if not isinstance(data, dict):
            raise BedrockError("Model output was not a JSON object")

        model_id = getattr(self._bedrock, "model_id", "unknown")
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Assemble the result, forcing bsaId/model/generatedAt from trusted sources
        # rather than trusting the model to echo them correctly.
        candidate = {
            "bsaId": bsa_id,
            "riskTier": data.get("riskTier"),
            "confidence": data.get("confidence"),
            "flags": data.get("flags", []),
            "explanation": data.get("explanation"),
            "model": model_id,
            "generatedAt": generated_at,
        }

        try:
            result = ClassificationResult(**candidate)
        except ValidationError as exc:
            raise BedrockError(f"Model output failed schema validation: {exc}") from exc

        # Enforce: elevated tier must include at least one flag.
        if result.riskTier in ("REVIEW", "HIGH_RISK") and not result.flags:
            raise BedrockError(
                "Model returned an elevated risk tier without any supporting flags"
            )

        return result
