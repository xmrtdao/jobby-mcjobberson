"""Lead normalization helpers."""

from typing import Any, Dict


def normalize_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalized lead without fabricated contact addresses."""
    normalized = dict(lead)
    email = str(normalized.get("email") or "").strip()
    if not email or email.lower().endswith("@placeholder.com"):
        normalized["email"] = None
    else:
        normalized["email"] = email
    return normalized
