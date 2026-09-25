"""Tunable constants for FBAR classification deterministic signals.

These values are intentionally centralized so they can be adjusted without
changing the signal-detection logic. In production these could be sourced
from configuration or a policy service.
"""

# ISO country codes considered higher-risk for FBAR compliance review.
# This is an illustrative list for the synthetic dataset, not legal guidance.
HIGH_RISK_JURISDICTIONS: set[str] = {
    "KY",  # Cayman Islands
    "CH",  # Switzerland
    "PA",  # Panama
    "BS",  # Bahamas
    "VG",  # British Virgin Islands
    "LI",  # Liechtenstein
    "AE",  # United Arab Emirates
    "LB",  # Lebanon
}

# Aggregate maximum account value (USD) at/above which a filing is flagged
# as high aggregate value.
HIGH_AGGREGATE_VALUE_USD: float = 1_000_000.0

# Common FBAR reporting threshold (USD). Accounts whose max value falls within
# CLUSTERING_BAND_USD just below this threshold contribute to a structuring
# (threshold-clustering) signal when multiple accounts cluster there.
REPORTING_THRESHOLD_USD: float = 10_000.0
CLUSTERING_BAND_USD: float = 1_000.0
CLUSTERING_MIN_ACCOUNTS: int = 2

# FBAR filing deadline month/day (with automatic extension) used to detect
# late filing relative to the tax year. FBARs for a given tax year are due the
# following calendar year; treated as late if filed after Oct 15 of year+1.
FBAR_DUE_MONTH: int = 10
FBAR_DUE_DAY: int = 15
