"""
app/rag/errors.py — Shared API error classification and retry-delay parsing.
"""

from __future__ import annotations

import re


def classify_api_error(err: Exception) -> str:
    """Classify provider errors into 'hard_quota', 'transient_rate_limit', or 'other'."""
    s = str(err).lower()
    hard_quota_signals = ("quota", "billing", "plan_limit", "exceeded your")
    if any(sig in s for sig in hard_quota_signals):
        return "hard_quota"
    if "429" in s or "resource exhausted" in s or "too many requests" in s:
        return "transient_rate_limit"
    return "other"


def parse_retry_delay(err: Exception, default: float) -> float:
    """Extract provider-suggested wait seconds from a 429 error payload."""
    s = str(err)
    proto_match = re.search(
        r"retry_delay\s*\{[^}]*seconds:\s*(\d+)", s, re.IGNORECASE | re.DOTALL
    )
    if proto_match:
        return float(proto_match.group(1)) + 2.0
    text_match = re.search(r"retry[_ ]in\s+(\d+\.?\d*)\s*s", s, re.IGNORECASE)
    if text_match:
        return float(text_match.group(1)) + 2.0
    return default
