"""Pure standard-library ingestion for newsletter text.

The adapter extracts only explicit links and addresses already present in the
input. It never opens a URL, calls a network service, guesses a contact, or
invents an opportunity.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from lead_utils import prepare_recipients


_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)", re.IGNORECASE)
_MAILTO_RE = re.compile(r"mailto:([^\s?#<>\"']+)", re.IGNORECASE)

# Labels that make a link an explicit opportunity rather than a generic article.
_LABEL_TERMS = {
    "apply",
    "architect",
    "career",
    "careers",
    "consult",
    "consultant",
    "consulting",
    "contract",
    "developer",
    "employment",
    "engineer",
    "freelance",
    "gig",
    "hiring",
    "intern",
    "internship",
    "opening",
    "openings",
    "opportunity",
    "position",
    "positions",
    "role",
    "roles",
    "staffing",
    "vacancy",
}

# Generic "job" is intentionally excluded: /blog/job-market is not a posting.
_PATH_TERMS = _LABEL_TERMS - {"job", "jobs"}
_PATH_TERMS |= {"contractor", "contractors", "engineers", "developers"}


class _AnchorParser(HTMLParser):
    """Collect anchor labels and hrefs without following or fetching them."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current: dict[str, Any] | None = None
        self._anchors: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._current = {"href": href, "text": []}

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current is not None:
            self._anchors.append(self._current)
            self._current = None

    @property
    def anchors(self) -> list[dict[str, Any]]:
        return self._anchors


def _clean_url(value: str) -> str:
    value = html.unescape(value).strip()
    return value.rstrip(".,;:!?)]}>\"'")


def _clean_email(value: str) -> str:
    return value.strip().rstrip(".,;:!?)]}>\"'")


def _url_path_segments(url: str) -> list[str]:
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        return []
    return [segment for segment in re.findall(r"[a-z0-9]+", path)]


def _is_explicit_job_link(url: str, label: str = "") -> bool:
    """Return true only for an explicit opportunity link or job label."""
    path_segments = _url_path_segments(url)
    if path_segments and path_segments[0] in {"job", "jobs"}:
        return True
    if any(segment in _PATH_TERMS for segment in path_segments):
        return True

    label_words = set(re.findall(r"[a-z0-9]+", label.lower()))
    return bool(label_words & _LABEL_TERMS)


def _unique_urls(candidates: list[tuple[str, str]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_url, label in candidates:
        url = _clean_url(raw_url)
        if not url.lower().startswith(("http://", "https://")):
            continue
        key = url.lower().rstrip("/")
        if key not in seen and _is_explicit_job_link(url, label):
            seen.add(key)
            result.append(url)
    return result


def _unique_emails(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        email = _clean_email(value)
        key = email.lower()
        if key and key not in seen:
            seen.add(key)
            result.append(email)
    return result


def extract_newsletter_contacts(text: str) -> dict[str, list[str]]:
    """Extract explicit job URLs and email addresses from newsletter text."""
    if not isinstance(text, str):
        raise TypeError("newsletter text must be a string")

    markdown_candidates: list[tuple[str, str]] = [
        (_clean_url(url), label.strip())
        for label, url in _MARKDOWN_LINK_RE.findall(text)
    ]

    parser = _AnchorParser()
    try:
        parser.feed(text)
    except Exception:
        # Malformed HTML should not prevent extraction of plain-text links.
        pass
    html_candidates = [
        (_clean_url(anchor["href"]), " ".join(anchor["text"]).strip())
        for anchor in parser.anchors
    ]
    plain_candidates = [(_clean_url(url), "") for url in _URL_RE.findall(text)]
    job_urls = _unique_urls(markdown_candidates + html_candidates + plain_candidates)

    mailto_values = [match.group(1) for match in _MAILTO_RE.finditer(text)]
    plain_values = [match.group(0) for match in _EMAIL_RE.finditer(text)]
    emails = _unique_emails(plain_values + mailto_values)
    return {"job_urls": job_urls, "emails": emails}


def ingest_newsletter(text: str) -> dict[str, Any]:
    """Normalize, deduplicate, and suppress newsletter contacts.

    Newsletter addresses are marked ``unverified`` because their presence in a
    message is not an email-verification result. Job links are kept as URL-only
    records. Placeholder addresses are discarded rather than passed downstream.
    """
    contacts = extract_newsletter_contacts(text)
    records: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []

    for url in contacts["job_urls"]:
        records.append(
            {
                "source": "newsletter",
                "url": url,
                "track": "track_1",
                "email_status": "missing",
            }
        )

    for email in contacts["emails"]:
        if email.lower().endswith("@placeholder.com"):
            discarded.append(
                {
                    "raw_record": {
                        "source": "newsletter",
                        "email": email,
                        "email_status": "unverified",
                        "track": "track_1",
                    },
                    "discarded_status": "malformed",
                }
            )
            continue
        records.append(
            {
                "source": "newsletter",
                "url": "mailto:" + email.lower(),
                "email": email,
                "email_status": "unverified",
                "track": "track_1",
            }
        )

    prepared = prepare_recipients(records)
    return {
        "contacts": contacts,
        "eligible": prepared["eligible"],
        "suppressed": prepared["suppressed"],
        "discarded": discarded + prepared["discarded"],
    }
