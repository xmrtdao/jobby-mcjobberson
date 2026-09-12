"""Adapt canonical Resend inbox payloads for Jobby ingestion.

This module only normalizes payloads already returned by the fleet's
``resend-inbox`` and ``resend-get-email`` tools. It performs no network,
persistence, read-state, scheduling, or sending operations.
"""

from __future__ import annotations

from typing import Any, Mapping

from newsletter_ingest import ingest_newsletter


def _message_body(email: Mapping[str, Any]) -> str:
    """Return the available plain text body without modifying the payload."""
    text = email.get("text")
    if isinstance(text, str):
        return text
    html = email.get("html")
    return html if isinstance(html, str) else ""


def ingest_resend_email(
    email: Mapping[str, Any], domain: str | None = None
) -> dict[str, Any]:
    """Ingest one full ``resend-get-email`` payload.

    The email id, domain, subject, receivedAt, and read state are preserved
    verbatim when present. Missing optional metadata remains unknown rather
    than being fabricated.
    """
    if not isinstance(email, Mapping):
        raise TypeError("email must be a mapping")

    resolved_domain = domain
    if resolved_domain is None:
        resolved_domain = email.get("domain")
    if resolved_domain is not None:
        resolved_domain = str(resolved_domain)

    return {
        "id": email.get("id"),
        "domain": resolved_domain,
        "subject": email.get("subject"),
        "receivedAt": email.get("receivedAt"),
        "read": email.get("read"),
        "ingestion": ingest_newsletter(_message_body(email)),
    }


def ingest_resend_inbox(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Ingest recent messages from a canonical ``resend-inbox`` payload.

    Domains retain their response order, and recent messages retain their
    order within each domain. Each result contains the per-message ingestion
    output plus the preserved Resend metadata.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("resend-inbox payload must be a mapping")
    domains = payload.get("domains")
    if not isinstance(domains, Mapping):
        raise TypeError("resend-inbox payload must contain a domains mapping")

    results: list[dict[str, Any]] = []
    for domain, inbox in domains.items():
        if not isinstance(inbox, Mapping):
            raise TypeError("inbox entry must be a mapping")
        recent = inbox.get("recent", [])
        if not isinstance(recent, list):
            raise TypeError("inbox recent messages must be a list")
        for email in recent:
            results.append(ingest_resend_email(email, domain=str(domain)))
    return results
