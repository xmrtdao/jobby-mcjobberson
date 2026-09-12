"""Lead normalization helpers."""

import json
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


def normalize_recipient(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a recipient without mutating the input or inventing contact data."""
    if not isinstance(lead, dict):
        raise TypeError("recipient must be a dictionary")

    normalized = dict(lead)
    for field in ("name", "company", "source", "url", "track"):
        value = normalized.get(field)
        normalized[field] = str(value).strip() if value is not None else None

    email = str(normalized.get("email") or "").strip().lower()
    raw_status = normalized.get("email_status")
    status = str(raw_status).strip().lower() if raw_status is not None else None

    if not email or email.endswith("@placeholder.com") or status in {"missing", "unverified"}:
        normalized["email_status"] = status if status in {"missing", "unverified"} else "missing"
        if "email" in normalized:
            normalized["email"] = None
    elif status not in {None, "", "verified"}:
        normalized["email"] = None
        normalized["email_status"] = status
    else:
        normalized["email"] = email
        normalized["email_status"] = "verified"
    return normalized


def recipient_identity_key(recipient: Dict[str, Any]) -> str:
    """Return a stable key for a verified email or a missing-email record."""
    normalized = normalize_recipient(recipient)
    email = normalized.get("email")
    if normalized.get("email_status") == "verified" and email:
        return "email:" + str(email).lower()

    identity_parts = [
        normalized.get("source") or "",
        normalized.get("url") or "",
        normalized.get("name") or "",
    ]
    encoded_parts = json.dumps(identity_parts, ensure_ascii=False, separators=(",", ":"))
    return "missing:" + encoded_parts


def deduplicate_recipients(records: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Deduplicate first-wins while preserving the input record order."""
    deduplicated = []
    seen_keys = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        normalized = normalize_recipient(record)
        key = recipient_identity_key(normalized)
        if key not in seen_keys:
            seen_keys.add(key)
            deduplicated.append(normalized)
    return deduplicated


def apply_suppression(
    records: list[Dict[str, Any]],
    suppressed_identity_keys: set[str] | None = None,
    suppressed_emails: set[str] | None = None,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Split normalized records into eligible and auditable suppressed records."""
    suppressed_keys = {str(key) for key in (suppressed_identity_keys or set())}
    suppressed_email_values = {
        str(email).strip().lower() for email in (suppressed_emails or set()) if email
    }
    eligible = []
    suppressed = []

    for record in records:
        if not isinstance(record, dict):
            continue
        normalized = normalize_recipient(record)
        key = recipient_identity_key(normalized)
        consent_status = str(normalized.get("consent_status") or "").strip().lower()
        email = normalized.get("email")

        reason = None
        if consent_status in {"denied", "opt_out", "unsubscribe"}:
            reason = "consent_denied"
        elif key in suppressed_keys:
            reason = "identity_key"
        elif normalized.get("email_status") == "verified" and email in suppressed_email_values:
            reason = "verified_email"

        if reason is None:
            eligible.append(normalized)
        else:
            suppressed_record = dict(normalized)
            suppressed_record["suppression_status"] = "suppressed"
            suppressed_record["suppression_reason"] = reason
            suppressed_record["suppression_identity_key"] = key
            suppressed.append(suppressed_record)

    return eligible, suppressed


def prepare_recipients(
    records: list[Any],
    suppressed_identity_keys: set[str] | None = None,
    suppressed_emails: set[str] | None = None,
) -> Dict[str, list[Dict[str, Any]]]:
    """Normalize, discard malformed records, deduplicate, and apply suppression."""
    normalized_records = []
    discarded = []
    for record in records:
        if not isinstance(record, dict):
            discarded.append({"raw_record": record, "discarded_status": "malformed"})
            continue
        normalized = normalize_recipient(record)
        has_identity = any(
            normalized.get(field)
            for field in ("name", "company", "source", "url", "email")
        )
        if not has_identity:
            discarded.append({"raw_record": record, "discarded_status": "malformed"})
            continue
        normalized_records.append(normalized)

    deduplicated = deduplicate_recipients(normalized_records)
    eligible, suppressed = apply_suppression(
        deduplicated,
        suppressed_identity_keys=suppressed_identity_keys,
        suppressed_emails=suppressed_emails,
    )
    return {"eligible": eligible, "suppressed": suppressed, "discarded": discarded}
