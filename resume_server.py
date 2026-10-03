#!/usr/bin/env python3
"""Serve the static hero, parse resumes, and bridge Jobby to the relay.

Three jobs live in this file, and they were separated on purpose:

  1. Static delivery. Assets are served with a content-derived `?v=` stamp.
     GitHub Pages lets Cloudflare rewrite the origin's `no-cache` on .js/.css to
     `max-age=14400`, so without a versioned URL a redeploy leaves a browser
     running an old script against new markup for up to four hours. The entry
     point is always revalidated; the versioned assets are cacheable.

  2. Resume parsing and dossier building. Text extraction and every field the
     deterministic extractor can prove live in resume_ingest. The LLM is used
     only to interpret, never to invent, and the deterministic values are
     applied afterwards as a floor under it. The dossier build runs the model
     several times and takes tens of seconds, which is far too long to hold an
     upload open for, so /api/resume/parse returns immediately with a
     request_id and the browser polls /api/resume/dossier for the result.

  3. The Jobby bridge. The browser talks only to this origin. The relay holds
     the model cascade, the tools and the database, so every /api/jobby/* call
     is proxied there with the browser's session cookie forwarded. That keeps
     the relay API key out of the browser entirely.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from resume_ingest import (
    MAX_RESUME_BYTES,
    _SUPPORTED_FORMATS,
    ingest_resume,
)
import resume_render


_FORMATS_BY_CONTENT_TYPE = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}
_STATIC_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    # The image, manifest and sitemap types were missing, so all three fell through
    # to application/octet-stream. Every file was on disk and every request returned
    # 200 with the correct bytes, which is why this hid for so long: nothing errored.
    #
    # It matters because of the nosniff header below. Sniffing is exactly what a
    # browser would do to recover the real type, and nosniff forbids it, so an
    # octet-stream response is taken at face value:
    #   - og:image as octet-stream is rejected by every major scraper, so the social
    #     card renders with no picture. Worse than no tag, because the platform then
    #     falls back to a screenshot of a blank page.
    #   - the manifest is only parsed when it is application/manifest+json, so the
    #     install prompt, theme colour and standalone display all silently drop.
    #   - the sitemap is still read, but not as the XML it is.
    #
    # The rest of the image and font types are here so the next image added does not
    # reproduce this. Adding a file is two edits in this repository: the name goes in
    # _STATIC_ASSETS, and if it is a new extension, the type goes here.
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".xml": "application/xml; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}
# The two new pages and their scripts/stylesheets.
#
# The allowlist is explicit rather than a directory listing, and it has to be
# extended by hand: dashboard.html and employers.html both 404'd on first serve
# because this set still named only the candidate page's five files. That is the
# allowlist doing its job — nothing is served because it happened to be on disk —
# but it means a new page is invisible until it is named here, which is worth
# knowing rather than rediscovering.
_DASHBOARD_ASSETS = {
    "dashboard.html", "dashboard.js", "dashboard.css",
    "employers.html", "employer.js", "employer.css",
    # The chat usability layer, ported from the Suite SPA's UnifiedChat. Named
    # here for the same reason the others are: the allowlist is explicit, so a new
    # file is invisible until it is listed, and a page that loads a script the
    # server will not serve fails with a 404 that reads as a broken build.
    "chat-experience.js",
    # The floating conversation panel, and the stylesheet for its shell.
    #
    # Both are loaded by index.html *and* dashboard.html, which is the whole point
    # of the change: the chat stopped being a section on one page. jobby.js is now
    # shared for the same reason — it went from front-page-only to loaded on both —
    # so it is listed once below rather than per page.
    "jobby-chat-widget.js", "chat-widget.css",
    # The jobs list on the front page, and its stylesheet. Listed explicitly for
    # the same reason as everything else here: a script the allowlist does not name
    # 404s, and a 404 reads as a broken build rather than as a missing entry.
    "jobs.js", "jobs.css",
}
_STATIC_ASSETS = _DASHBOARD_ASSETS | {
    "index.html", "styles.css", "app.js", "jobby.js", "hero-scene.js", "i18n.js",
    # Social and SEO assets for jobbymcjobberson.com.
    #
    # These have to be listed here because this set is an ALLOWLIST, not a
    # directory listing. An asset that is on disk but absent below is simply not
    # served - so an og:image that 404s produces a social card with no picture,
    # and a missing favicon produces a blank tab icon. Both fail silently, which
    # is why they are named explicitly rather than added by prefix.
    "robots.txt",
    "sitemap.xml",
    "site.webmanifest",
    "jobby-og.png",
    "jobby-favicon-16.png",
    "jobby-favicon-32.png",
    "jobby-favicon-512.png",
}
# The assets that get a version stamp in the entry point's markup. Both new pages
# are entry points, so their own assets need stamping too — without it a cached
# dashboard.html can be paired with a stale dashboard.js, which is the exact
# pairing the stamp exists to prevent.
#
# The widget is stamped for a second reason that matters more here: it builds the
# chat's DOM at runtime, so a page holding a cached jobby-chat-widget.js against a
# fresh jobby.js — or the reverse — produces a chat that renders and then sends
# nothing, because the ids stopped lining up. A stale mix is silent; a stamped one
# is a 404 that says so.
_VERSIONED_ASSETS = (
    "app.js", "styles.css", "jobby.js", "hero-scene.js", "i18n.js",
    "dashboard.js", "dashboard.css", "employer.js", "employer.css",
    "chat-experience.js", "jobby-chat-widget.js", "chat-widget.css",
    "jobs.js", "jobs.css",
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; object-src 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_MAX_MULTIPART_OVERHEAD = 1024 * 1024

# Dossier generation runs the model several times and takes 10-90s, far too long
# to hold an upload request open for. Parse results return immediately and the
# dossier is fetched from GET /api/resume/dossier?request_id=... once ready.
_DOSSIER_JOBS: dict[str, dict[str, Any]] = {}
_DOSSIER_JOBS_LOCK = threading.Lock()
_DOSSIER_JOB_TTL_SECONDS = 900
_DOSSIER_JOBS_MAX = 40

# Jobby relay bridge. The portal serves the browser; the relay holds the model
# cascade, the tools and the database. The portal proxies to the relay and
# forwards the browser's session cookie, so the browser never receives a relay
# API key.
_JOBBY_RELAY_URL = os.environ.get("JOBBY_RELAY_URL", "http://127.0.0.1:8080")

# ── Logging ──────────────────────────────────────────────────────────────────
#
# This service had none. Every failure became a bare status code: a parse error
# answered 500 "resume parsing failed", an unreachable relay answered 502, and
# both left nothing on disk. That is not merely inconvenient — it is why a
# download that worked minutes earlier could not be diagnosed at all, because the
# one thing that would have said why was the thing that was missing.
#
# Everything below exists so that a failure names itself:
#
#   - every response is logged with its status and how long it took, so a slow or
#     failing endpoint is visible without waiting for it to be reported
#   - every exception is logged WITH its traceback, while the browser still only
#     ever receives the short message. The traceback is the diagnostic; the
#     response is the contract.
#   - the document route logs which format was resolved and which was refused,
#     because "you asked for a PDF and got a DOCX" is exactly the kind of failure
#     that otherwise looks like success
#   - relay reachability is logged separately from relay errors, because "the
#     relay said no" and "the relay never answered" have opposite causes
#
# Rotating at 8 MB with 5 files. The log lives beside the server so it is found
# next to the thing it describes.
_LOG_DIR = Path(__file__).resolve().parent
_LOG_PATH = Path(os.environ.get("RESUME_SERVER_LOG", str(_LOG_DIR / "resume_server.log")))


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("resume_server")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            _LOG_PATH, maxBytes=8 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S"
        ))
        logger.addHandler(handler)
    except OSError as error:
        # A log that cannot be written must not stop the portal from serving.
        # Say so once, on stderr, and carry on without a file handler.
        print(f"[resume_server] cannot write {_LOG_PATH}: {error}", flush=True)
        logger.addHandler(logging.NullHandler())
    return logger


LOG = _build_logger()


def _safe_error_body(error: Exception, limit: int = 300) -> str:
    """The body of a failed HTTP response, for the log.

    A relay that answers 500 with an empty body and a relay that answers 500
    with a reason are different bugs, and the reason is usually only in the body.
    Truncated, because an upstream error page can be enormous and the useful part
    is at the front.
    """
    try:
        body = error.read()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - the whole point is that this cannot fail
        return "<no body readable>"
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return "<undecodable body>"
    text = " ".join(str(body).split())
    return text[:limit] if text else "<empty>"
_JOBBY_SESSION_COOKIE = "jobby_sid"
_JOBBY_PROXY_PREFIX = "/api/jobby/"
_JOBBY_PROXY_TIMEOUT = 200

# The employer side. A separate prefix and a separate cookie, for the same reason
# the relay holds two cookies: one browser must never carry one identity across
# both products. An HR person who opens the candidate page in a second tab would
# otherwise find a job-seeker dossier they never created, and a candidate who
# followed an employer link would find their applications attached to postings.
_EMPLOYER_RELAY_URL = os.environ.get("JOBBY_RELAY_URL", "http://127.0.0.1:8080")
_EMPLOYER_SESSION_COOKIE = "jobby_employer_sid"
_EMPLOYER_PROXY_PREFIX = "/api/employer/"
_EMPLOYER_PROXY_TIMEOUT = 200

# A job description is a document strangers will read and act on, so the ceiling
# is enforced before the file is opened rather than after it has been read.
_MAX_JD_BYTES = 5 * 1024 * 1024
_JD_TEXT_LIMIT = 200_000

# The employer side. A separate prefix and a separate cookie, for the same reason
# the relay has two cookies: one browser must never carry one identity across both
# products. An HR person who opens the candidate page in a second tab would
# otherwise find a job-seeker dossier they never created.
_EMPLOYER_RELAY_URL = os.environ.get("JOBBY_RELAY_URL", "http://127.0.0.1:8080")
_EMPLOYER_SESSION_COOKIE = "jobby_employer_sid"
_EMPLOYER_PROXY_PREFIX = "/api/employer/"
_EMPLOYER_PROXY_TIMEOUT = 200

# A job description is a document a stranger will read and act on, so the size
# ceiling is enforced before the file is opened rather than after.
_MAX_JD_BYTES = 5 * 1024 * 1024
_JD_TEXT_LIMIT = 200_000

# How far the resume's own employment dates may exceed its stated years of
# experience before the difference is worth raising. A year of slack absorbs
# rounding and the odd overlapping role.
_EXPERIENCE_GAP_TOLERANCE_YEARS = 2.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx instead of following it.

    The Google OAuth callback answers with a 302 back to the portal. With the
    default opener, urlopen follows that redirect internally, so the portal
    never sees a 302 and the browser is handed whatever Google redirected to -
    which is how a consent round trip silently became a plain page load.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_no_redirect_opener = urllib.request.build_opener(_NoRedirect)


# -- upload parsing ----------------------------------------------------------


# --- output language ---------------------------------------------------------
#
# The site has a language toggle and the product has to honour it. A toggle that
# only rewrites the page copy translates the marketing, not the product: what a
# candidate actually reads is the dossier, the rendered resume and what the agent
# says back, and all three are written by the model.
#
# Only prose the model authors is translated. Field names stay English, because
# they are stored in the database and read by the relay, the renderer and the
# page agent; renaming them would mean a migration, an audit of every consumer,
# and it would orphan every dossier already on file. The client renders those
# names through the same dictionary.

_LANG_RULES = {
    "en": (
        "Write every value in English, including the professional summary, the "
        "highlights and the achievements. Leave the field names exactly as the "
        "schema spells them."
    ),
    "es": (
        "IMPORTANT: write every value in Spanish. The candidate's resume may be "
        "in English, and that does not change what you output: the professional "
        "summary, every highlight, every achievement and every rationale must be "
        "written in Spanish, in natural professional Spanish, rather than a "
        "word-for-word translation. Keep proper nouns, employer names, job titles "
        "as the document states them, certifications, acronyms, technology names "
        "and URLs exactly as they appear. Translate only descriptive prose. Leave "
        "the field names exactly as the schema spells them, in English - they are "
        "keys, not text."
    ),
}


def _normalise_lang(value: Any) -> str:
    """The languages offered, and nothing else.

    An unrecognised value falls back to English rather than passing through into
    the prompt: a stray "fr" would otherwise become an instruction the model tries
    to satisfy, with no French copy anywhere on the site to show for it.
    """
    if isinstance(value, str):
        head = value.strip().casefold()[:2]
        if head in ("es", "en"):
            return head
    return "en"


def _language_rule(lang: str) -> str:
    return _LANG_RULES.get(_normalise_lang(lang), _LANG_RULES["en"])


def _query_value(query: str, name: str) -> str | None:
    """One parameter out of a raw query string, or None.

    Used where a bad value must fall through to a default rather than raise: the
    language in particular, because an unrecognised one should mean English
    rather than a 400 on the candidate's download.
    """
    for part in (query or "").split("&"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        if unquote(key.strip()) == name:
            return unquote(value.strip())
    return None


def _safe_filename(value: str | None) -> str:
    filename = unquote(value or "").strip()
    if (
        not filename
        or "\x00" in filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
        or Path(filename).name != filename
    ):
        raise ValueError("invalid resume filename")
    return filename


def _format_for_request(
    filename: str,
    content_type: str,
    hint: str | None,
) -> str:
    """Resolve format only when every supplied signal agrees."""
    hint_value = (hint or "").strip().lower().lstrip(".")
    media_type = content_type.split(";", 1)[0].strip().lower()
    media_value = _FORMATS_BY_CONTENT_TYPE.get(media_type)
    suffix_value = Path(filename).suffix.lower().lstrip(".")
    if not media_value:
        raise ValueError("unsupported resume format")
    if hint_value and hint_value not in _SUPPORTED_FORMATS:
        raise ValueError("unsupported resume format")
    if suffix_value and suffix_value not in _SUPPORTED_FORMATS:
        raise ValueError("unsupported resume format")
    signals = [media_value]
    if suffix_value:
        signals.append(suffix_value)
    if hint_value:
        signals.append(hint_value)
    if len(set(signals)) != 1:
        raise ValueError("conflicting resume format signals")
    return next(iter(signals))


def _multipart_upload(
    body: bytes,
    content_type: str,
) -> tuple[str, bytes, str, dict[str, str]]:
    """Extract exactly one resume part without using the removed cgi module."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("multipart resume upload required")
    if "boundary=" not in content_type.lower():
        raise ValueError("multipart boundary missing")

    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + content_type.encode("latin-1", errors="replace")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    if not message.is_multipart():
        raise ValueError("invalid multipart resume upload")

    file_parts: list[tuple[str, bytes, str]] = []
    fields: dict[str, str] = {}
    for part in message.iter_parts():
        filename = part.get_filename()
        if filename is not None:
            name = part.get_param("name", header="content-disposition")
            if name != "resume":
                raise ValueError("resume field name missing")
            if part.get("Content-Type") is None:
                raise ValueError("resume file content type missing")
            file_parts.append(
                (
                    filename,
                    part.get_payload(decode=True) or b"",
                    part.get_content_type(),
                )
            )
            continue

        name = part.get_param("name", header="content-disposition")
        if name:
            payload = part.get_payload(decode=True)
            if payload is None:
                raw_payload = part.get_payload()
                payload = (
                    raw_payload.encode("utf-8")
                    if isinstance(raw_payload, str)
                    else b""
                )
            fields[name] = payload.decode("utf-8", errors="replace")

    if len(file_parts) != 1:
        raise ValueError("exactly one resume file is required")
    filename, payload, part_content_type = file_parts[0]
    return _safe_filename(filename), payload, part_content_type, fields


def _extract_resume_upload(
    body: bytes,
    content_type: str,
    header_filename: str | None,
    hint: str | None,
) -> tuple[str, bytes, str, str | None]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type.startswith("multipart/form-data"):
        filename, payload, part_content_type, fields = _multipart_upload(
            body, content_type
        )
        return (
            filename,
            payload,
            part_content_type,
            fields.get("format") or fields.get("hint") or hint,
            # The non-file parts travel with the payload rather than being read
            # again by the caller. The language the reader asked for arrives as
            # one of them, and re-parsing the multipart body at the call site to
            # reach a single field would mean walking it twice for no reason.
            fields,
        )

    filename = _safe_filename(header_filename)
    return filename, body, content_type, hint, fields


# -- model access ------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RELAY_ENV_PATH = _REPO_ROOT / "relay" / ".env"
_relay_env_cache: dict[str, str] | None = None


def _relay_env() -> dict[str, str]:
    """Read relay/.env once.

    The portal and the relay share one model account, so the credentials live in
    one place rather than being duplicated into a second file that can drift.
    Values already present in the process environment win, so a deployment can
    override without editing the file.
    """
    global _relay_env_cache
    if _relay_env_cache is not None:
        return _relay_env_cache
    values: dict[str, str] = {}
    try:
        for line in _RELAY_ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    _relay_env_cache = values
    return values


def _model_settings() -> tuple[str, str, str]:
    env = _relay_env()

    def pick(name: str, default: str = "") -> str:
        return os.environ.get(name) or env.get(name) or default

    base = pick("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/")
    key = pick("OPENCODE_API_KEY")
    model = pick("OPENCODE_MODELS", "space-bunny-free").split(",")[0].strip()
    return base, key, model


class ModelUnavailable(RuntimeError):
    """The model could not be reached or refused the request."""


_MODEL_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _llm_json(
    system: str, user: str, *, temperature: float = 0.2, allow_text: bool = False
) -> dict[str, Any] | str:
    """One model call, expected to answer with a single JSON object.

    Every value here is an interpretation of a document the deterministic
    extractor has already read, so the prompt forbids inventing anything. A
    model that answers with prose instead of JSON gets one repair attempt,
    because it does that intermittently and the alternative is losing the pass.

    allow_text is for the caller that can use a prose answer. The interpret pass
    sometimes replies with capitalised headings and bullets rather than JSON;
    that is still an answer, and _parse_labelled_sections can read it, so it is
    handed back instead of raising. Without this the pass is simply lost for
    being formatted differently from what was asked.
    """
    base, key, model = _model_settings()
    if not key:
        raise ModelUnavailable("no model credential configured")

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error = ""

    for attempt in range(2):
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if attempt:
            # The repair turn says plainly what is wrong rather than repeating
            # the instruction, which is what the model actually responds to.
            messages = messages + [
                {"role": "assistant", "content": user[:400]},
                {
                    "role": "user",
                    "content": (
                        "That was not valid JSON. Reply with one JSON object and "
                        "nothing else - no prose, no markdown fence, no code "
                        "block. Start with { and end with }."
                    ),
                },
            ]
            payload["messages"] = messages

        request = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                # Cloudflare answers a User-Agent-less request with
                # "error code: 1010", which is a browser-signature block rather
                # than anything to do with the key or the model. Python's urllib
                # sends no User-Agent at all, so every call was refused with a
                # 403 that looked like a credentials problem.
                "User-Agent": _MODEL_USER_AGENT,
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001 - diagnostics only
                pass
            last_error = f"HTTP {error.code}: {detail}"
            # A 4xx will not improve on a retry; only transport does.
            if 400 <= error.code < 500:
                break
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = str(error)
            continue

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            last_error = "unexpected response shape"
            continue

        parsed = _extract_json_object(content)
        if isinstance(parsed, dict):
            return parsed
        if allow_text and isinstance(content, str) and content.strip():
            return content
        last_error = "no JSON object in the reply"

    raise ModelUnavailable(last_error or "the model did not answer with JSON")


def _extract_json_object(content: Any) -> dict[str, Any] | None:
    """Pull one JSON object out of a model reply.

    The model is asked for JSON but does not always comply, so this accepts the
    shapes that actually show up: a bare object, or one wrapped in a markdown
    fence, or one with a sentence in front of it.
    """
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except ValueError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


# -- dossier construction ----------------------------------------------------

# Never invent. A field the resume does not state is null, and the gap is
# reported rather than filled. This is the whole contract with the model.
_IDENTITY_SYSTEM = (
    "You extract structured facts from a resume. Reply with ONE JSON object and "
    "nothing else. Use ONLY facts written in the document. If a field is not in "
    "the resume, set it to null. Never guess, never infer, never fill a gap from "
    "general knowledge. Copy names, titles, companies and dates exactly as the "
    "document writes them."
)

_HISTORY_SYSTEM = (
    "You extract a job history from a resume. Reply with ONE JSON object and "
    "nothing else. Use ONLY what the document states. A role with no dates gets "
    "null for start and end. Do not invent employers, titles, dates or bullets."
)

_INTERPRET_SYSTEM = (
    "You read a resume and report what it does and does not establish. Reply "
    "with ONE JSON object and nothing else. Every claim must trace to text in "
    "the document. Anything you cannot confirm goes in not_stated."
)

# -- normalisation ------------------------------------------------------------
#
# The passes are asked for a fixed schema and do not reliably keep to it. These
# map the shapes the model actually returns onto the one the rest of the code
# reads, so that an awkward reply is a normalisation problem here rather than a
# broken document three stages downstream.

_CONFIDENCE_LEVELS = {"high", "medium", "low"}

# Keys the model invents, mapped onto the ones the code reads. Observed: the
# person nested under "person", a role called "position", and the resume's own
# wording in "raw_start_date" sitting beside a transcribed "start_date".
_KEY_ALIASES = {
    "full_name": "name",
    "current_employer": "current_company",
    "title": "current_title",
    "years_of_experience": "experience_years",
    "professional_summary": "summary",
    "email_address": "email",
    "domain_tags": "job_fields",
    "extraction_confidence": "confidence",
    "quantified_achievements": "achievements",
    "experience": "employment",
    "roles": "target_roles",
}

_LINK_ALIASES = {
    "personal_site": "portfolio",
    "personal_website": "portfolio",
    "site": "portfolio",
    "blog": "website",
    "personal": "website",
    "github_url": "github",
    "linkedin_url": "linkedin",
}

# Bookkeeping rather than content. A dossier is not useful because it recorded
# that it is not confident.
_NOT_CONTENT = {
    "confidence", "not_stated", "verification_flags", "sourceFilename",
    "onboarding", "roles_in_resume", "experience_years_source",
    "experience_years_stated", "experience_years_from_dates",
}

# Fields that, on their own, mean the resume was actually read.
_CONTENT_ALONE = {
    "summary", "skills", "employment", "education", "links", "certifications",
    "achievements", "job_fields", "domain_expertise", "target_roles",
    "current_title", "current_company",
}


def _text(value: Any) -> str | None:
    """A trimmed string, or None.

    Bare numbers deliberately do not become text. Coercing them is how 42 ends
    up in a list of skills; the one place a number is wanted as a string (a
    graduation year) converts it itself.
    """
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("description", "text", "name", "title", "label", "value"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return None


def _text_list(value: Any) -> list[str]:
    """Strings out of whatever shape the model used, deduped, order kept."""
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    return None


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "current", "ongoing"}
    return False


def _location(value: Any) -> str | None:
    """A dict location flattened to the order a person would say it in."""
    if isinstance(value, dict):
        parts = [
            _text(value.get(key))
            for key in ("city", "state", "region", "country")
        ]
        joined = ", ".join(p for p in parts if p)
        return joined or None
    return _text(value)


def _merge_links(links: dict[str, Any], value: Any) -> None:
    if isinstance(value, str):
        value = {"website": value}
    if not isinstance(value, dict):
        return
    for key, val in value.items():
        canonical = _LINK_ALIASES.get(str(key).strip().casefold(), str(key).strip().casefold())
        if canonical == "other":
            # "other" is the plural bucket, so a bare string there is a list of
            # one. The named links stay single strings, which is the shape the
            # renderer and the deterministic floor both write.
            existing = _text_list(links.get("other"))
            for text in _text_list(val):
                if text not in existing:
                    existing.append(text)
            links["other"] = existing
        else:
            text = _text(val)
            if text and not links.get(canonical):
                links[canonical] = text


def _employment_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        # raw_* is the resume's own wording and outranks the transcribed date
        # beside it: transposing March 2021 into 2017-03 is the exact defect the
        # timeline reconciliation exists to undo, so the verbatim value is taken
        # first here rather than being overwritten downstream.
        #
        # Taking it here is also why the provenance is recorded here. The model
        # is the one returning both, so the date is the document's text from the
        # moment it is chosen - and by the time the timeline reconciliation runs
        # there is nothing left for it to correct, which would silently drop the
        # note on the most trustworthy dates in the dossier.
        start_key = next(
            (k for k in ("raw_start_date", "start_date", "start")
             if isinstance(item.get(k), str) and item[k].strip()),
            None,
        )
        end_key = next(
            (k for k in ("raw_end_date", "end_date", "end")
             if isinstance(item.get(k), str) and item[k].strip()),
            None,
        )
        current = item.get("is_current", item.get("current"))
        job = {
            "company": _text(
                item.get("company") or item.get("employer")
                or item.get("organisation") or item.get("organization")
            ),
            "title": _text(
                item.get("title") or item.get("position")
                or item.get("role") or item.get("job_title")
            ),
            "location": _location(item.get("location")),
            "start": _text(item.get(start_key) if start_key else None),
            "end": _text(item.get(end_key) if end_key else None),
            "current": _flag(current),
            "highlights": _text_list(
                item.get("highlights") or item.get("bullets") or item.get("achievements")
            ),
        }
        if start_key and start_key.startswith("raw_"):
            job["dates_from"] = "resume text"
        elif isinstance(item.get("dates_from"), str) and item["dates_from"].strip():
            # Carried through. The dossier is normalised more than once - each
            # pass, then the merged result - and on the later passes the raw_*
            # key is long gone, so without this the provenance recorded on the
            # first pass would be silently dropped on the way to the dossier.
            job["dates_from"] = item["dates_from"].strip()
        if job["company"] or job["title"] or job["start"]:
            out.append(job)
    return out


def _education_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        year = item.get("graduation_year", item.get("year", item.get("end_year")))
        if isinstance(year, (int, float)) and not isinstance(year, bool):
            year = str(int(year))
        entry = {
            "institution": _text(
                item.get("institution") or item.get("school") or item.get("university")
            ),
            "degree": _text(item.get("degree")),
            "field": _text(
                item.get("field") or item.get("field_of_study") or item.get("major")
            ),
            "year": _text(year),
        }
        if any(entry.values()):
            out.append(entry)
    return out


def _normalise_dossier(raw: Any) -> dict[str, Any]:
    """Coerce one model reply into the shape the dossier and renderer expect.

    Every key is always present, so a consumer can read a field without first
    checking whether the model mentioned it. Nothing is invented here: absent
    fields become None or [], never a plausible-looking default.
    """
    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, Any] = {
        "name": None,
        "current_title": None,
        "current_company": None,
        "email": None,
        "phone": None,
        "location": None,
        # Named links are present-but-None rather than absent, so a consumer can
        # read one without checking whether the model mentioned it.
        "links": {"linkedin": None, "github": None, "portfolio": None,
                  "website": None, "other": []},
        "summary": None,
        "skills": [],
        "seniority": None,
        "employment": [],
        "education": [],
        "certifications": [],
        "achievements": [],
        "job_fields": [],
        "domain_expertise": [],
        "target_roles": [],
        "experience_years": None,
        "confidence": "low",
        "not_stated": [],
        "verification_flags": [],
    }

    person = raw.get("person") if isinstance(raw.get("person"), dict) else {}
    # The nested person first, then the top level over it, so an explicit
    # top-level value is the one that wins.
    for source in (person, raw):
        for key, value in source.items():
            target = _KEY_ALIASES.get(str(key).strip().casefold(), str(key).strip().casefold())
            if target == "links":
                _merge_links(out["links"], value)
            elif target == "location":
                out["location"] = _location(value) or out["location"]
            elif target in ("name", "current_title", "current_company", "summary",
                            "seniority"):
                out[target] = _text(value) or out[target]
            elif target in ("email", "phone"):
                out[target] = _text(value) or out[target]
            elif target == "experience_years":
                number = _number(value)
                if number is not None:
                    out["experience_years"] = number
            elif target == "confidence":
                level = _text(value)
                level = level.casefold() if level else ""
                out["confidence"] = level if level in _CONFIDENCE_LEVELS else "low"
            elif target == "employment":
                out["employment"].extend(_employment_items(value))
            elif target == "education":
                out["education"].extend(_education_items(value))
            elif target in ("skills", "certifications", "achievements", "job_fields",
                            "domain_expertise", "target_roles", "not_stated",
                            "verification_flags"):
                out[target].extend(_text_list(value))

    # Sections the extractor said were missing are gaps, same as a field it
    # could not confirm, and the flags it raised are shown to the candidate.
    meta = raw.get("extraction_metadata")
    if isinstance(meta, dict):
        out["not_stated"].extend(_text_list(meta.get("sections_missing")))
        out["verification_flags"].extend(_text_list(meta.get("flags")))

    for key in ("skills", "certifications", "achievements", "job_fields",
                "domain_expertise", "target_roles", "not_stated",
                "verification_flags"):
        out[key] = _text_list(out[key])

    # Employment and education can arrive from more than one key, so the same
    # job must not be listed twice.
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for job in out["employment"]:
        marker = ((job["company"] or "").casefold(), (job["title"] or "").casefold(),
                  job["start"] or "")
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(job)
    out["employment"] = deduped
    return out


def _has_content(value: Any) -> bool:
    """Does this value carry anything a person would call information?

    Recurses, because the seeded links dict is a non-empty dict of Nones and
    must not pass for content. Compared against None and False by identity
    rather than truthiness, so a legitimate 0 is not mistaken for empty.
    """
    if isinstance(value, dict):
        return any(_has_content(inner) for inner in value.values())
    if isinstance(value, list):
        return any(_has_content(inner) for inner in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value is not False


def _dossier_is_useful(dossier: Any) -> bool:
    """Is there enough here to show a candidate as having been read?

    Two populated fields, or one that is substantive on its own. A lone name is
    not enough: it is the one field a model will produce from a document that
    says nothing else, and a dossier containing only a name is indistinguishable
    from a failed read.
    """
    if not isinstance(dossier, dict):
        return False
    populated = [
        key for key, value in dossier.items()
        if key not in _NOT_CONTENT and _has_content(value)
    ]
    if len(populated) >= 2:
        return True
    return bool(populated) and populated[0] in _CONTENT_ALONE


_SECTION_LABEL = re.compile(r"^([A-Z][A-Z &/]{2,40}):?\s*$")
_SECTION_ITEM = re.compile(r"^(?:[-*\u2022\u2013]\s*|\d+[.)]\s*)?")


# Section headings the interpret pass uses, mapped onto the schema keys. Matched
# case- and space-insensitively, because the model chooses its own
# capitalisation and its own singular or plural.
_SECTION_TARGETS = {
    "EXPERTISE": "domain_expertise",
    "EXPERTISE AREAS": "domain_expertise",
    "AREAS OF EXPERTISE": "domain_expertise",
    "SKILLS": "skills",
    "JOB FIELDS": "job_fields",
    "FIELDS": "job_fields",
    "ROLES": "target_roles",
    "TARGET ROLES": "target_roles",
    "ROLES THEY COULD DO": "target_roles",
    "NOT STATED": "not_stated",
}


def _sections_to_dossier(text: str) -> dict[str, Any]:
    """A prose interpret answer, read into the schema it should have returned."""
    sections = _parse_labelled_sections(text)
    out: dict[str, Any] = {}
    for label, items in sections.items():
        target = _SECTION_TARGETS.get(" ".join(label.upper().split()))
        if target:
            out.setdefault(target, [])
            out[target].extend(items)
    return out


def _parse_labelled_sections(text: str) -> dict[str, list[str]]:
    """Pull labelled lists out of a plain-text model reply.

    The interpret pass is asked for JSON, and usually complies. When it does
    not, it tends to answer with capitalised headings and bullets instead - and
    the retry loop raises once the JSON never arrives, losing a pass that in fact
    answered. This is the fallback for that case, and the reason the
    interpretation is not simply dropped.

    Lines that read as commentary rather than as list items are discarded, so a
    sentence about the candidate does not end up in their field list.
    """
    if not isinstance(text, str) or not text.strip():
        return {}
    if "{" in text and "}" in text:
        # A JSON reply is handled by _extract_json_object; there is nothing to
        # salvage here and parsing it as prose would invent sections.
        return {}
    sections: dict[str, list[str]] = {}
    label: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _SECTION_LABEL.match(line)
        if match:
            label = match.group(1).strip()
            sections.setdefault(label, [])
            continue
        if label is None:
            continue
        item = _SECTION_ITEM.sub("", line).strip().strip(",;")
        # A long sentence is commentary, not a list entry.
        if not item or len(item) > 70 or len(item.split()) > 8:
            continue
        if item not in sections[label]:
            sections[label].append(item)
    return {k: v for k, v in sections.items() if v}


_IDENTITY_SCHEMA = (
    '{"name": string or null, "current_title": string or null, '
    '"current_company": string or null, "email": string or null, '
    '"phone": string or null, "location": string or null, '
    '"links": {"linkedin": string or null, "github": string or null, '
    '"portfolio": string or null, "website": string or null}, '
    '"summary": string or null, "skills": [string], '
    '"seniority": string or null, '
    '"not_stated": [names of fields you could not confirm]}\n\n'
)

_HISTORY_SCHEMA = (
    '{"employment": [{"company": string, "title": string, "location": string or null, '
    '"start": string or null, "end": string or null, "current": boolean, '
    '"highlights": [string]}], '
    '"education": [{"institution": string, "degree": string or null, '
    '"field": string or null, "year": string or null}], '
    '"certifications": [string], "achievements": [string]}\n\n'
)

_INTERPRET_SCHEMA = (
    '{"job_fields": [string], "domain_expertise": [string], '
    '"target_roles": [string], "confidence": "low" or "medium" or "high", '
    '"not_stated": [string]}\n\n'
)


def _merge_dossier(
    identity: dict[str, Any], history: dict[str, Any]
) -> dict[str, Any]:
    """Union the two passes; the identity pass wins where both have a value.

    This previously skipped any key history supplied that identity lacked, so a
    thin identity response (observed: no email/phone/links/skills) left those
    holes even when the history pass had found them.
    """
    merged: dict[str, Any] = {}
    for source in (identity, history):
        for key, value in source.items():
            if key not in merged:
                merged[key] = value
            elif merged.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
                merged[key] = value
    return merged


def _classify_link(url: str) -> str | None:
    lowered = url.casefold()
    if "linkedin.com" in lowered:
        return "linkedin"
    if "github.com" in lowered or "gitlab.com" in lowered:
        return "github"
    if any(token in lowered for token in ("portfolio", "behance", "dribbble")):
        return "portfolio"
    # Anything left with a hostname and a real-looking TLD is the candidate's
    # own site. The scheme is not required: the parser normalises the URLs it
    # finds, so "https://jellis.dev" arrives here as "jellis.dev", and a test
    # that insisted on the scheme sent every bare domain to the other bucket
    # where it was never used for anything.
    host = lowered.split("//")[-1].split("/")[0].split("?")[0].split("#")[0]
    if "." in host and len(host.rsplit(".", 1)[-1]) >= 2 and not host.endswith("."):
        return "website"
    return None


def _apply_deterministic_floor(
    dossier: dict[str, Any], ingested: dict[str, Any]
) -> dict[str, Any]:
    """Backfill gaps with values the parser found literally in the document.

    The deterministic extractor is 100% reliable, so it should act as a floor
    under the AI rather than being discarded. If the model is thin on a given
    run, the email / URL / skills the parser actually matched are still
    known-good, and putting them back keeps the dossier honest and complete
    without inventing anything.
    """
    ingested = ingested if isinstance(ingested, dict) else {}

    # Phone first: it was the one field with no deterministic source at all, so
    # a stated number could never survive a thin model pass.
    phones = [p for p in (ingested.get("phones") or []) if isinstance(p, str)]
    if not dossier.get("phone") and phones:
        dossier["phone"] = phones[0]
    if len(phones) > 1:
        dossier.setdefault("other_phones", phones[1:])

    emails = [e for e in (ingested.get("emails") or []) if isinstance(e, str)]
    if not dossier.get("email") and emails:
        dossier["email"] = emails[0]
    if not dossier.get("email"):
        extra = [e for e in emails[1:] if e.casefold() != dossier.get("email", "").casefold()]
        if extra:
            dossier.setdefault("other_emails", extra)

    links = dossier.get("links")
    if not isinstance(links, dict):
        links = {}
        dossier["links"] = links
    urls = [u for u in (ingested.get("urls") or []) if isinstance(u, str)]

    for url in urls:
        kind = _classify_link(url)
        if kind and not links.get(kind):
            links[kind] = url
    if not links.get("other"):
        classified = {u for u in urls if _classify_link(u)}
        leftovers = [u for u in urls if u not in classified]
        if leftovers:
            links["other"] = leftovers[:5]

    # The parser's skills are the ones actually written in a skills section. The
    # model may add more from the prose, so the two are unioned rather than one
    # replacing the other.
    parser_skills = [s for s in (ingested.get("skills") or []) if isinstance(s, str)]
    if parser_skills:
        merged_skills = [s for s in (dossier.get("skills") or []) if isinstance(s, str)]
        seen = {s.casefold() for s in merged_skills}
        for skill in parser_skills:
            if skill.casefold() not in seen:
                seen.add(skill.casefold())
                merged_skills.append(skill)
        dossier["skills"] = merged_skills[:40]

    parser_fields = [f for f in (ingested.get("job_fields") or []) if isinstance(f, str)]
    if parser_fields:
        merged_fields = [f for f in (dossier.get("job_fields") or []) if isinstance(f, str)]
        seen = {f.casefold() for f in merged_fields}
        for field in parser_fields:
            if field.casefold() not in seen:
                seen.add(field.casefold())
                merged_fields.append(field)
        dossier["job_fields"] = merged_fields[:8]

    if not dossier.get("not_stated"):
        dossier["not_stated"] = []
    if emails and not dossier.get("email"):
        dossier["not_stated"].append("email")

    jobs = [j for j in (dossier.get("employment") or []) if isinstance(j, dict)]
    for job in jobs:
        if not job.get("current"):
            continue
        if not dossier.get("current_company") and job.get("company"):
            dossier["current_company"] = job["company"]
        if not dossier.get("current_title") and job.get("title"):
            dossier["current_title"] = job["title"]
        if dossier.get("current_company") and dossier.get("current_title"):
            break

    # A first job carries no current flag, and a resume whose only role is that
    # first job is describing a current position by not saying otherwise. Taking
    # the earliest entry here would be wrong, so this is the first, and only
    # when nothing was flagged current.
    if jobs and not (dossier.get("current_company") and dossier.get("current_title")):
        first = jobs[0]
        if not dossier.get("current_company") and first.get("company"):
            dossier["current_company"] = first["company"]
        if not dossier.get("current_title") and first.get("title"):
            dossier["current_title"] = first["title"]

    # Role titles the document actually names. The model rarely volunteers role
    # suggestions when asked in a JSON schema, and answering that question from
    # the document is grounded, so this is always available where the AI's
    # `target_roles` is not.
    if jobs:
        seen_roles: set[str] = set()
        roles: list[str] = []
        for source in [dossier.get("current_title")] + [j.get("title") for j in jobs]:
            if not isinstance(source, str):
                continue
            role = source.strip()
            key = role.casefold()
            if role and key not in seen_roles:
                seen_roles.add(key)
                roles.append(role)
            if len(roles) >= 6:
                break
        if roles:
            dossier["roles_in_resume"] = roles
    # Always present, including when there is no employment to read. A consumer
    # that has to distinguish "no roles found" from "never looked" ends up
    # guessing at a missing key.
    dossier.setdefault("roles_in_resume", [])
    if not isinstance(dossier.get("target_roles"), list):
        dossier["target_roles"] = []

    _pin_experience_years(dossier, ingested)
    _reconcile_timeline_with_source(dossier, ingested)

    # Achievements are normally derived from the job highlights, but that runs
    # before the timeline is corrected, so re-derive them once the highlights
    # are final.
    if not dossier.get("achievements"):
        seen_ach: set[str] = set()
        collected: list[str] = []
        for job in jobs:
            for highlight in job.get("highlights") or []:
                if isinstance(highlight, str) and highlight.strip():
                    key = highlight.casefold()
                    if key not in seen_ach:
                        seen_ach.add(key)
                        collected.append(highlight)
        if collected:
            dossier["achievements"] = collected[:15]

    return dossier


def _reconcile_timeline_with_source(
    dossier: dict[str, Any], ingested: dict[str, Any]
) -> None:
    """Correct the AI's job dates using headers copied from the document.

    The model transposed month and year on a real resume - it reported a job
    starting "2017-03" that the document dates "March 2021", which made the
    current role overlap the one before it. Where the parser matched an
    employment header, those dates are the ones to trust: they are copied
    verbatim rather than interpreted. `dates_from` records that the value came
    from the document rather than the model, so the two are never confused.
    """
    hints = ingested.get("employment_hints") if isinstance(ingested, dict) else None
    if not isinstance(hints, list) or not hints:
        return

    jobs = [j for j in (dossier.get("employment") or []) if isinstance(j, dict)]
    if not jobs:
        return

    used: set[int] = set()
    for hint in hints:
        if not isinstance(hint, dict):
            continue
        company = str(hint.get("company") or "").strip()
        title = str(hint.get("title") or "").strip()
        if not company and not title:
            continue
        best_index = None
        best_score = 0
        for index, job in enumerate(jobs):
            if index in used:
                continue
            job_company = str(job.get("company") or "").casefold()
            job_title = str(job.get("title") or "").casefold()
            score = 0
            if company and job_company:
                head = company.casefold()[:12]
                if head and (head in job_company or job_company[:12] in head):
                    score += 2
            if title and job_title:
                head = title.casefold()[:12]
                if head and (head in job_title or job_title[:12] in head):
                    score += 2
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is None or best_score < 2:
            continue
        used.add(best_index)
        job = jobs[best_index]
        # The document's date overwrites the model's, it does not merely fill a
        # gap. The model transposed month and year on a real resume - it
        # reported a role starting "2017-03" that the document dates "March
        # 2021" - so a fill-gaps-only version left the wrong date in place
        # whenever the model happened to supply one. These strings were read
        # verbatim out of the header, so they are the document's own text, and
        # dates_from records that so the two are never confused.
        #
        # Only recorded when a value actually moved. A model that already
        # matched the document has not been corrected, and marking it as though
        # it had would put a provenance note on a claim that was never in
        # question.
        corrected = False
        for key in ("start", "end"):
            value = hint.get(key)
            if isinstance(value, str) and value.strip() and job.get(key) != value.strip():
                job[key] = value.strip()
                corrected = True
        if corrected:
            job["dates_from"] = "resume text"

        # Bullets the parser read under the same header, when the model produced
        # none of its own. The model keeps its own where it wrote any: its
        # phrasing is usually better, and the document's version is a
        # transcription rather than a rewrite.
        if not job.get("highlights"):
            hint_highlights = [h for h in (hint.get("highlights") or [])
                               if isinstance(h, str) and h.strip()]
            if hint_highlights:
                job["highlights"] = hint_highlights
        if hint.get("company") and not job.get("company"):
            job["company"] = hint["company"]


def _employment_year_span(dossier: dict[str, Any]) -> tuple[int, int] | None:
    """Earliest start year and latest end year across the employment entries.

    A current role has no end date, so the present year is used. Returns None
    when no dated entry is available, or when the ends precede the starts, which
    means the dates cannot be read as a span.
    """
    earliest: int | None = None
    latest: int | None = None
    for job in dossier.get("employment") or []:
        if not isinstance(job, dict):
            continue
        found: list[int] = []
        for key in ("start", "end"):
            raw = job.get(key)
            if not isinstance(raw, str):
                continue
            match = re.search(r"(19|20)\d{2}", raw)
            if match:
                found.append(int(match.group(0)))
        if not found:
            continue
        start = found[0]
        end = found[1] if len(found) > 1 else datetime.now().year
        earliest = start if earliest is None else min(earliest, start)
        latest = end if latest is None else max(latest, end)
    if earliest is None or latest is None or latest < earliest:
        return None
    return earliest, latest


def _add_flag(dossier: dict[str, Any], flag: str) -> None:
    flags = dossier.get("verification_flags")
    if not isinstance(flags, list):
        flags = []
    if flag not in flags:
        flags.append(flag)
    dossier["verification_flags"] = flags


def _pin_experience_years(dossier: dict[str, Any], ingested: dict[str, Any]) -> None:
    """Set experience_years from the employment dates, and keep the stated figure.

    An earlier policy kept whatever the resume stated. That was wrong for a
    real candidate: their summary read "15+ years of proven leadership" while
    that figure was really how long they had owned their company. They began
    work in 1997, so the honest number was twenty-nine, and fifteen would have
    been read as a mid-career applicant.

    The span is therefore the figure. The stated number is not discarded: it
    stays in experience_years_stated, the span in experience_years_from_dates,
    and experience_years_source records which one is published. This is the same
    provenance rule applied to researched values, applied to arithmetic. A span
    derived from dates is a true statement about the dates, but nobody wrote it
    on the page, and the dossier should never blur a stated fact with a derived
    one.

    Where the dates cannot be read at all, the stated figure is used, because a
    candidate's own number beats nothing. Where neither exists, the field is
    null and the gap recorded rather than filled with a guess.
    """
    stated = ingested.get("stated_experience_years") if isinstance(ingested, dict) else None
    has_stated = isinstance(stated, (int, float)) and not isinstance(stated, bool)
    if has_stated:
        dossier["experience_years_stated"] = float(stated)
    else:
        dossier.pop("experience_years_stated", None)

    span = _employment_year_span(dossier)
    if span is not None:
        first_year, last_year = span
        span_years = last_year - first_year
        dossier["experience_years"] = float(span_years)
        dossier["experience_years_from_dates"] = {
            "from": first_year,
            "to": last_year,
            "years": span_years,
        }
        dossier["experience_years_source"] = "employment dates"
        if has_stated and abs(span_years - float(stated)) >= _EXPERIENCE_GAP_TOLERANCE_YEARS:
            _add_flag(dossier, (
                f"Years of experience is published as {span_years}, measured from "
                f"your employment dates ({first_year} to {last_year}), not the "
                f"{stated:g} your resume states. The stated figure is kept on "
                f"record. If the dates are wrong, tell me and I will correct them."
            ))
        return

    if has_stated:
        dossier["experience_years"] = float(stated)
        dossier["experience_years_source"] = "stated on the resume"
        dossier.pop("experience_years_from_dates", None)
        return

    dossier["experience_years"] = None
    dossier.pop("experience_years_from_dates", None)
    gaps = dossier.get("not_stated")
    if not isinstance(gaps, list):
        gaps = []
    note = "years of experience (no dated employment and no stated figure)"
    if note not in gaps:
        gaps.append(note)
    dossier["not_stated"] = gaps


def _build_dossier(
    text: str,
    filename: str,
    ingested: dict[str, Any],
    on_progress: Any = None,
    lang: str = "en",
) -> dict[str, Any]:
    """Run the model passes, then lay the deterministic floor underneath.

    Three short passes rather than one long one: a single request for a whole
    profile is where the model starts transposing dates and inventing
    employers. Split by concern it stays on task, and each pass is small enough
    to be retried when it answers with prose instead of JSON.

    on_progress is called with a stage label before each step so the browser can
    show what is happening rather than an indeterminate spinner. It is a
    parameter rather than a global so this stays callable from a test without a
    job in the store, and so a caller that does not care pays nothing.

    lang decides the language the model writes its prose in. The field names
    stay English whatever it is set to, because they are keys rather than text -
    see _LANG_RULES.
    """
    identity = history = interpret = {}
    failures: list[str] = []
    report = on_progress or (lambda stage, note="": None)

    for label, system, schema, run in (
        ("identity", _IDENTITY_SYSTEM, _IDENTITY_SCHEMA, "identity"),
        ("history", _HISTORY_SYSTEM, _HISTORY_SCHEMA, "history"),
        ("interpret", _INTERPRET_SYSTEM, _INTERPRET_SCHEMA, "interpret"),
    ):
        prompt = (
            f"{schema}"
            "Here is the resume. Answer with the JSON object only.\n"
            f"{_language_rule(lang)}\n\n"
            "=== RESUME ===\n"
            f"{text}\n"
            "=== END RESUME ===\n"
        )
        if run == "interpret":
            prompt = (
                f"{schema}"
                "Decide which broad job fields this person could work in, what "
                "they demonstrably know, and what roles their history supports. "
                "Base it only on the text below.\n\n"
                "=== RESUME ===\n"
                f"{text}\n"
                "=== END RESUME ===\n"
            )
        report(run)
        try:
            result = _llm_json(system, prompt, allow_text=(run == "interpret"))
        except ModelUnavailable as error:
            failures.append(f"{label}: {error}")
            result = {}
        if isinstance(result, str):
            result = _sections_to_dossier(result)
        if run == "identity":
            identity = result
        elif run == "history":
            history = result
        else:
            interpret = result

    # Each pass is normalised before it is merged. Without this the model's raw
    # object goes straight into the dossier and from there into the renderer and
    # the application filler, so "9 years" arrives where a number belongs and a
    # dict arrives inside the skills list. It is normalisation, not invention:
    # absent fields become None, never a default.
    identity = _normalise_dossier(identity)
    history = _normalise_dossier(history)
    interpret = _normalise_dossier(interpret)

    dossier = _merge_dossier(identity, history)
    for key, value in interpret.items():
        if key not in dossier or dossier.get(key) in (None, "", [], {}):
            dossier[key] = value
    # Normalise the merged result too, since merging two normalised dicts can
    # still leave list-valued fields concatenated rather than deduped.
    dossier = _normalise_dossier(dossier)

    if not isinstance(dossier.get("employment"), list):
        dossier["employment"] = []
    if not isinstance(dossier.get("education"), list):
        dossier["education"] = []
    for key in ("skills", "certifications", "achievements", "not_stated",
                "verification_flags", "job_fields", "domain_expertise",
                "target_roles", "roles_in_resume"):
        if not isinstance(dossier.get(key), list):
            dossier[key] = dossier.get(key) or []

    dossier = _apply_deterministic_floor(dossier, ingested)
    report("reconcile")
    dossier["sourceFilename"] = filename
    if failures:
        _add_flag(dossier, (
            "Part of the profile could not be read by the model, so those "
            "fields are thinner than usual: " + "; ".join(failures)
        ))
    return dossier


def _onboard_with_jobby(
    profile: dict[str, Any], filename: str, cookie: str | None
) -> dict[str, Any]:
    """Hand the finished dossier to the relay so tracks and a plan are built.

    A failure here must not lose the dossier the user just uploaded, so the
    error is returned rather than raised and the caller still stores the profile.
    """
    payload = json.dumps({"dossier": profile, "sourceFilename": filename}).encode("utf-8")
    request = urllib.request.Request(
        f"{_JOBBY_RELAY_URL}/api/jobby/onboard",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 - diagnostics only
            detail = {"error": f"relay returned HTTP {error.code}"}
        return {"success": False, "error": detail.get("error", "onboarding failed")}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return {"success": False, "error": f"relay unreachable: {error}"}


# -- async dossier jobs ------------------------------------------------------


def _dossier_job_store() -> None:
    with _DOSSIER_JOBS_LOCK:
        cutoff = time.time() - _DOSSIER_JOB_TTL_SECONDS
        for key in [k for k, v in _DOSSIER_JOBS.items() if v.get("created", 0) < cutoff]:
            _DOSSIER_JOBS.pop(key, None)
        if len(_DOSSIER_JOBS) > _DOSSIER_JOBS_MAX:
            ordered = sorted(_DOSSIER_JOBS.items(), key=lambda kv: kv[1].get("created", 0))
            for key, _ in ordered[: len(_DOSSIER_JOBS) - _DOSSIER_JOBS_MAX]:
                _DOSSIER_JOBS.pop(key, None)


def _dossier_job_put(request_id: str, job: dict[str, Any]) -> None:
    _dossier_job_store()
    with _DOSSIER_JOBS_LOCK:
        _DOSSIER_JOBS[request_id] = {**job, "created": time.time()}


def _dossier_job_get(request_id: str) -> dict[str, Any] | None:
    _dossier_job_store()
    with _DOSSIER_JOBS_LOCK:
        return _DOSSIER_JOBS.get(request_id)


# The stages a candidate is shown while the dossier is built. The order is the
# order the work actually happens in, and the wording is what the browser puts
# in front of the user, so it is defined here rather than in the client: the
# server knows what it is doing, and a progress bar that disagrees with the work
# is worse than no bar.
_DOSSIER_STAGES: tuple[tuple[str, str], ...] = (
    ("identity", "Reading your details out of the document"),
    ("history", "Pulling the job history apart"),
    ("interpret", "Working out what that history supports"),
    ("reconcile", "Cross-checking the dates against the document"),
    ("verify", "Deciding what it can and cannot claim"),
    ("onboard", "Building your tracks and your plan"),
)
_DOSSIER_STAGE_TOTAL = len(_DOSSIER_STAGES)
_STAGE_INDEX = {label: i for i, (label, _) in enumerate(_DOSSIER_STAGES, start=1)}


def _dossier_progress(request_id: str, stage: str, note: str = "") -> None:
    """Publish what the build is currently doing, for the progress bar.

    Read-modify-write under the lock rather than _dossier_job_put, because
    put() replaces the whole entry and would discard the status and profile
    already recorded. A finished job is left alone: a straggling update must not
    resurrect a completed build, which would leave the browser polling forever.
    """
    index = _STAGE_INDEX.get(stage)
    if index is None:
        return
    _dossier_job_store()
    with _DOSSIER_JOBS_LOCK:
        job = _DOSSIER_JOBS.get(request_id)
        if not job or job.get("status") in ("done", "error"):
            return
        job["progress"] = {
            "stage": stage,
            "label": _DOSSIER_STAGES[index - 1][1],
            "index": index,
            "total": _DOSSIER_STAGE_TOTAL,
            "note": note,
        }


def _run_dossier_job(
    request_id: str, text: str, filename: str, ingested: dict[str, Any], cookie: str | None,
    lang: str = "en",
) -> None:
    try:
        profile = _build_dossier(
            text, filename, ingested,
            on_progress=lambda stage, note="": _dossier_progress(request_id, stage, note),
            lang=lang,
        )
        _dossier_progress(request_id, "verify")
        if not _dossier_is_useful(profile):
            # Every model pass came back empty and the deterministic floor found
            # nothing either. Reporting "done" is the one outcome that must not
            # happen here: the panel would render a dossier of blank fields and
            # the candidate would read it as a successful read of their resume,
            # which is the exact opposite of what happened. This is the failure
            # this whole pipeline is supposed to be honest about.
            _dossier_job_put(request_id, {
                "status": "error",
                "error": (
                    "Nothing could be read from that file. If it is a scan or "
                    "a photo of a page, the text cannot be extracted from it - "
                    "try the original document, or a .docx or .txt copy."
                ),
            })
            return
        # Onboarding runs before the job is marked done. It used to be marked
        # done first and then re-written with the onboarding result, which let
        # the browser render a dossier whose tracks and plan had not arrived
        # yet - and made the "onboard" stage unshowable, because progress is
        # never recorded against a finished job. The tracks and the plan are
        # part of what the candidate is waiting for, so the bar now covers them
        # and the dossier appears once, complete.
        _dossier_progress(request_id, "onboard")
        onboarding = _onboard_with_jobby(profile, filename, cookie)
        if isinstance(onboarding, dict) and onboarding:
            profile = {**profile, "onboarding": onboarding}
        _dossier_job_put(request_id, {
            "status": "done",
            "profile": profile,
            # Carried on the record rather than read from a cookie at render
            # time: the candidate may switch language after uploading, and the
            # resume they download should come back in the language they are
            # currently reading the site in.
            "lang": _normalise_lang(lang),
        })
    except Exception as error:  # noqa: BLE001 - a job must never kill the thread
        _dossier_job_put(request_id, {
            "status": "error",
            "error": f"dossier build failed: {error}",
        })


# -- server ------------------------------------------------------------------


def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    root: Path | None = None,
):
    """Create a local static portal, parser and Jobby bridge server."""
    static_root = (root or Path(__file__).parent / "docs").resolve()

    class ResumeHTTPServer(ThreadingHTTPServer):
        daemon_threads = True

    class ResumeRequestHandler(BaseHTTPRequestHandler):
        server_version = "JobbyResumeParser/2"

        def _send_security_headers(self) -> None:
            for name, value in _SECURITY_HEADERS.items():
                self.send_header(name, value)

        # -- routing --
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path == "/api/resume/parse":
                self._write_json(405, {"error": "method not allowed"}, {"Allow": "POST"})
                return
            if path == "/api/resume/dossier":
                self._dossier_poll()
                return
            if path == "/api/resume/document":
                self._render_document()
                return
            if path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("GET")
                return
            if path.startswith(_EMPLOYER_PROXY_PREFIX):
                self._proxy_to_employer_relay("GET")
                return
            self._serve_static(path, send_body=True)

        def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path == "/api/resume/parse":
                self._write_json(405, {"error": "method not allowed"}, {"Allow": "POST"}, send_body=False)
                return
            if path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("HEAD")
                return
            if path.startswith(_EMPLOYER_PROXY_PREFIX):
                self._proxy_to_employer_relay("HEAD")
                return
            self._serve_static(path, send_body=False)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path == "/api/employer/jd/parse":
                self._parse_job_description()
                return
            if path != "/api/resume/parse":
                if path.startswith(_JOBBY_PROXY_PREFIX):
                    self._proxy_to_relay("POST")
                    return
                if path.startswith(_EMPLOYER_PROXY_PREFIX):
                    self._proxy_to_employer_relay("POST")
                    return
                self._write_json(404, {"error": "not found"})
                return
            self._parse_resume()

        def do_PATCH(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("PATCH")
                return
            if path.startswith(_EMPLOYER_PROXY_PREFIX):
                self._proxy_to_employer_relay("PATCH")
                return
            self._write_json(404, {"error": "not found"})

        def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("PUT")
                return
            if path.startswith(_EMPLOYER_PROXY_PREFIX):
                self._proxy_to_employer_relay("PUT")
                return
            self._write_json(404, {"error": "not found"})

        def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("DELETE")
                return
            if path.startswith(_EMPLOYER_PROXY_PREFIX):
                self._proxy_to_employer_relay("DELETE")
                return
            self._write_json(404, {"error": "not found"})

        def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self.send_response(204)
            self.send_header("Allow", "GET, HEAD, POST, PATCH, PUT, DELETE, OPTIONS")
            self._send_security_headers()
            self.end_headers()

        # -- resume upload --
        def _read_body(self) -> bytes:
            raw_length = self.headers.get("Content-Length", "")
            content_length = int(raw_length)
            if (
                content_length <= 0
                or content_length > MAX_RESUME_BYTES + _MAX_MULTIPART_OVERHEAD
            ):
                raise ValueError("invalid resume size")
            body = self.rfile.read(content_length)
            if len(body) != content_length:
                raise ValueError("incomplete resume upload")
            return body

        def _parse_resume(self) -> None:
            try:
                body = self._read_body()
                content_type = self.headers.get("Content-Type", "")
                filename, payload, part_content_type, hint, fields = _extract_resume_upload(
                    body,
                    content_type,
                    self.headers.get("X-File-Name"),
                    self.headers.get("X-Format-Hint"),
                )
                if len(payload) > MAX_RESUME_BYTES:
                    raise ValueError("resume exceeds the 10 MB limit")
                resume_format = _format_for_request(filename, part_content_type, hint)

                with tempfile.NamedTemporaryFile(
                    suffix=f".{resume_format}", delete=False
                ) as upload:
                    upload.write(payload)
                    upload_path = Path(upload.name)
                try:
                    result = ingest_resume(upload_path, hint=resume_format)
                finally:
                    upload_path.unlink(missing_ok=True)
                result["file"] = filename

                request_id = "dossier_" + uuid.uuid4().hex[:16]
                cookie = self.headers.get("Cookie")
                # The language the reader asked for, read from the upload itself
                # rather than from a cookie at build time: the build runs on a
                # worker thread some seconds later, and by then a cookie would
                # reflect whatever request arrived most recently rather than the
                # one that asked for this resume.
                lang = _normalise_lang(fields.get("lang"))
                _dossier_job_put(request_id, {"status": "processing", "lang": lang})
                thread = threading.Thread(
                    target=_run_dossier_job,
                    args=(request_id, result.get("text", ""), filename, result, cookie, lang),
                    daemon=True,
                )
                thread.start()
                result["dossier"] = {
                    "status": "processing",
                    "request_id": request_id,
                    "poll_url": "/api/resume/dossier?request_id=" + request_id,
                }
                self._write_json(200, result)
            except (FileNotFoundError, ValueError, OSError, TypeError) as error:
                self._write_json(400, {"error": str(error)})
            except Exception:  # noqa: BLE001 - never leak a traceback to a browser
                self._fail(500, "resume parsing failed")

        def _dossier_poll(self) -> None:
            query = urlsplit(self.path).query
            request_id = ""
            for part in query.split("&"):
                if part.startswith("request_id="):
                    request_id = unquote(part[len("request_id="):])
            if not request_id:
                self._write_json(400, {"error": "request_id is required"})
                return
            job = _dossier_job_get(request_id)
            if job is None:
                self._write_json(404, {
                    "status": "unknown",
                    "error": "that request has expired. Upload the resume again.",
                })
                return
            if job.get("status") == "error":
                self._write_json(500, {
                    "status": "error",
                    "error": job.get("error", "dossier build failed"),
                })
                return
            if job.get("status") == "processing":
                # The progress block is what the browser's bar is built from, so
                # it rides on the 202 rather than needing a second endpoint. A
                # job that has not reported a stage yet still returns a valid
                # one, because a bar that starts at 0% on the first poll and
                # then jumps reads as a stall.
                progress = job.get("progress")
                if not isinstance(progress, dict):
                    progress = {
                        "stage": "identity",
                        "label": _DOSSIER_STAGES[0][1],
                        "index": 1,
                        "total": _DOSSIER_STAGE_TOTAL,
                        "note": "",
                    }
                self._write_json(202, {"status": "processing", "progress": progress})
                return
            self._write_json(200, {"status": "done", "profile": job.get("profile")})

        # -- resume download --
        def _render_document(self) -> None:
            """Serve the dossier as a downloadable resume.

            The dossier is read through the relay rather than from a local cache,
            so the session cookie decides whose resume it is. Rendering a local
            copy would mean a document built from whatever this server last
            happened to parse, which for a multi-user portal is the wrong
            person's CV.
            """
            try:
                request = urllib.request.Request(
                    f"{_JOBBY_RELAY_URL}/api/jobby/dossier",
                    headers={"Accept": "application/json"},
                    method="GET",
                )
                cookie = self.headers.get("Cookie")
                if cookie:
                    request.add_header("Cookie", cookie)
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as error:
                # The relay answered, and the answer was no. That is a different
                # problem from the relay not answering, and the two used to look
                # identical from outside.
                LOG.warning(
                    "relay refused the dossier: HTTP %s %s body=%s",
                    error.code, error.reason, _safe_error_body(error),
                )
                self._fail(
                    error.code if 400 <= error.code < 600 else 502,
                    "no dossier to download yet",
                    relay=_JOBBY_RELAY_URL, relay_status=error.code,
                )
                return
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                # The relay never answered. Previously this was a bare 502 with
                # nothing recorded, which is why a download that had worked could
                # not be diagnosed at all.
                LOG.error(
                    "cannot reach the Jobby relay at %s: %s: %s",
                    _JOBBY_RELAY_URL, type(error).__name__, error,
                )
                self._fail(
                    502, "the Jobby relay is unreachable",
                    relay=_JOBBY_RELAY_URL, cause=type(error).__name__,
                )
                return

            dossier = payload.get("dossier") if isinstance(payload, dict) else None
            if not isinstance(dossier, dict) or not dossier:
                self._write_json(404, {
                    "error": "no dossier yet. Upload your resume first, then this builds.",
                })
                return

            query = urlsplit(self.path).query
            # This used to be: wanted = "html" if "format=html" in query else "docx"
            # A substring test with a default, which meant every other value —
            # format=pdf above all — quietly became a DOCX. A caller asking for a
            # PDF got a Word file with a .docx filename and no error, and since
            # this is the file a candidate sends to an employer, "silently wrong"
            # is the worst outcome available here.
            #
            # An explicit format that this server cannot build is now refused with
            # a 400 that says so, rather than answered with a different document.
            requested = _query_value(query, "format")
            if requested is None:
                wanted = "docx"
            else:
                wanted = requested.strip().lower()
                if wanted not in ("docx", "html"):
                    LOG.info(
                        "refusing format=%s: this server builds docx and html only",
                        wanted,
                    )
                    self._write_json(400, {
                        "error": (
                            f"this server cannot build a {wanted} resume yet. "
                            "It builds .docx, and .html to print to PDF yourself. "
                            "No PDF renderer is installed, so nothing was sent - "
                            "better to say so than to hand over a Word file."
                        ),
                        "supported": ["docx", "html"],
                    })
                    return
            # The downloadable CV follows the language the reader is currently
            # on, not the language of the upload. Someone who read the dossier in
            # Spanish and then downloads it should not be handed an English
            # document, and the reverse is equally wrong. Read from the query
            # rather than from the job record, so a switch takes effect on the
            # next click instead of after another upload.
            lang = _normalise_lang(_query_value(query, "lang"))
            try:
                body, content_type, filename = resume_render.render(dossier, wanted, lang)
            except RuntimeError as error:
                self._write_json(503, {"error": str(error)})
                return

            # as_path=1 writes the document to a temp file and answers with its
            # location instead of the bytes. The page agent drives a real
            # browser, and a file input needs a real file: it cannot attach
            # something it was handed as base64, and asking it to download the
            # resume first is a step that can fail in a dozen ways. Writing it
            # here means the renderer stays in one place and the path handed to
            # the agent is always the document this dossier actually produces.
            if "as_path=1" in query:
                directory = Path(tempfile.gettempdir()) / "jobby-resumes"
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    target = directory / filename
                    target.write_bytes(body)
                except OSError as error:
                    self._write_json(500, {"error": f"could not stage the resume: {error}"})
                    return
                self._write_json(200, {
                    "path": str(target), "filename": filename, "bytes": len(body),
                })
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(body)

        # -- employer side --
        def _parse_job_description(self) -> None:
            """Turn an uploaded job description into text, then let the relay parse it.

            The parse itself belongs to the relay, which owns relay/jobby/jd.mjs
            and the title library it reads. What happens here is only the part
            that needs a document reader: take the bytes, get the text out, and
            hand it over.

            The text is read by the same ingest path the resume uses, rather than a
            new one. A second extractor would be a second set of PDF quirks, and
            the quirks are where a parser quietly returns a page of nothing.
            """
            try:
                body = self._read_body()
                content_type = self.headers.get("Content-Type", "")
                filename, payload, part_content_type, hint, fields = _extract_resume_upload(
                    body, content_type,
                    self.headers.get("X-File-Name"),
                    self.headers.get("X-Format-Hint"),
                )
                if len(payload) > _MAX_JD_BYTES:
                    raise ValueError("that file is larger than 5 MB")
                jd_format = _format_for_request(filename, part_content_type, hint)

                with tempfile.NamedTemporaryFile(suffix=f".{jd_format}", delete=False) as upload:
                    upload.write(payload)
                    upload_path = Path(upload.name)
                try:
                    result = ingest_resume(upload_path, hint=jd_format)
                finally:
                    upload_path.unlink(missing_ok=True)

                text = (result.get("text") or "").strip()
                if not text:
                    # Named precisely. "Upload failed" sends an employer back to
                    # the file picker; "this looks like a scanned image" tells
                    # them to paste the text instead, which they can do.
                    self._write_json(422, {
                        "error": "No text could be read from that file. If it is a "
                                 "scanned image or a screenshot, paste the text into "
                                 "the box instead — that works.",
                    })
                    return
                if len(text) > _JD_TEXT_LIMIT:
                    self._write_json(413, {
                        "error": f"That description is {len(text):,} characters. "
                                 f"Trim it to the actual posting, under {_JD_TEXT_LIMIT:,}.",
                    })
                    return

                self._forward_employer_json(
                    "/api/employer/parse",
                    {
                        "text": text,
                        "title": fields.get("title"),
                        "company": fields.get("company"),
                        "apply_url": fields.get("apply_url"),
                        "contact_email": fields.get("contact_email"),
                    },
                )
            except (FileNotFoundError, ValueError, OSError, TypeError) as error:
                self._write_json(400, {"error": str(error)})
            except Exception:  # noqa: BLE001 - never leak a traceback to a browser
                self._fail(500, "could not read that job description")

        def _forward_employer_json(self, path: str, payload: dict[str, Any]) -> None:
            """POST a JSON body to the relay's employer surface."""
            request = urllib.request.Request(
                f"{_EMPLOYER_RELAY_URL}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            cookie = self.headers.get("Cookie")
            if cookie:
                request.add_header("Cookie", cookie)
            try:
                with urllib.request.urlopen(request, timeout=_EMPLOYER_PROXY_TIMEOUT) as response:
                    raw = response.read()
                    self._relay_response(response.status, response, "POST",
                                         override_body=raw)
            except urllib.error.HTTPError as error:
                self._relay_response(error.code, error, "POST")
            except (urllib.error.URLError, TimeoutError, OSError):
                self._write_json(502, {"error": "the Jobby relay is unreachable"})

        def _proxy_to_employer_relay(self, method: str) -> None:
            """Forward an /api/employer/* call to the relay, cookie and all.

            A copy of the candidate bridge rather than a shared one, because the
            two differ in the only part that matters: which cookie identifies
            them. Merging them would mean a single prefix that resolves whichever
            identity arrived first, which is precisely the mistake the two
            cookies exist to prevent.
            """
            path = self.path
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length > 0 else None

            headers = {"Accept": self.headers.get("Accept", "application/json")}
            if body is not None:
                headers["Content-Type"] = self.headers.get(
                    "Content-Type", "application/json"
                )
            cookie = self.headers.get("Cookie")
            if cookie:
                headers["Cookie"] = cookie

            request = urllib.request.Request(
                f"{_EMPLOYER_RELAY_URL}{path}",
                data=body,
                headers=headers,
                method=method,
            )
            try:
                with _no_redirect_opener.open(request, timeout=_EMPLOYER_PROXY_TIMEOUT) as response:
                    self._relay_response(response.status, response, method)
            except urllib.error.HTTPError as error:
                self._relay_response(error.code, error, method)
            except (urllib.error.URLError, TimeoutError, OSError):
                self._write_json(502, {"error": "the Jobby relay is unreachable"})

        # -- Jobby bridge --
        def _proxy_to_relay(self, method: str) -> None:
            """Forward a /api/jobby/* call to the relay, cookie and all.

            The relay's status codes and bodies are passed through unchanged so
            its own validation is what the browser sees: a 400 for a bad
            autonomy value comes from the relay, not from a second copy of the
            rules here. A 302 is forwarded rather than followed, because the
            Google callback answers with a redirect the browser has to receive.
            """
            path = self.path
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length > 0 else None

            headers = {"Accept": self.headers.get("Accept", "application/json")}
            if body is not None:
                headers["Content-Type"] = self.headers.get(
                    "Content-Type", "application/json"
                )
            cookie = self.headers.get("Cookie")
            if cookie:
                headers["Cookie"] = cookie

            request = urllib.request.Request(
                f"{_JOBBY_RELAY_URL}{path}",
                data=body,
                headers=headers,
                method=method,
            )
            try:
                with _no_redirect_opener.open(request, timeout=_JOBBY_PROXY_TIMEOUT) as response:
                    self._relay_response(response.status, response, method)
            except urllib.error.HTTPError as error:
                # 4xx and 5xx are real answers from the relay, not proxy failures.
                self._relay_response(error.code, error, method)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                self._write_json(502, {
                    "error": "the Jobby relay is unreachable",
                    "detail": str(error)[:200],
                })

        def _relay_response(
            self,
            status: int,
            response: Any,
            method: str,
            override_body: bytes | None = None,
        ) -> None:
            # `override_body` lets a caller hand over a body it has already read.
            # The employer JD route needs it because the relay's own Set-Cookie
            # has to be forwarded from that same response, and re-reading a
            # consumed stream to get it is not possible. Without this parameter
            # the new route would have to duplicate the whole header block, and a
            # copy of the security headers is a copy that eventually misses one.
            raw = override_body if override_body is not None else response.read()
            content_type = response.headers.get("Content-Type", "application/json")
            location = response.headers.get("Location", "")
            set_cookie = response.headers.get("Set-Cookie", "")
            payload = b"" if method == "HEAD" else raw

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if location:
                self.send_header("Location", location)
            if set_cookie:
                # The relay mints the session; the browser must receive it, and
                # the portal has to rewrite nothing because it is same-origin.
                self.send_header("Set-Cookie", set_cookie)
            self._send_security_headers()
            self.end_headers()
            if payload:
                self.wfile.write(payload)

        # -- static --
        def _static_path(self, request_path: str) -> Path | None:
            relative_path = unquote(request_path).lstrip("/") or "index.html"
            if "/" in relative_path:
                return None
            candidate = (static_root / relative_path).resolve()
            try:
                candidate.relative_to(static_root)
            except ValueError:
                return None
            if candidate.parent != static_root or candidate.name not in _STATIC_ASSETS:
                return None
            if not candidate.is_file():
                return None
            return candidate

        def _asset_stamp(self, name: str) -> str:
            """A version derived from the file's own mtime.

            Content hashing would be marginally better, but mtime changes on
            every checkout even when the bytes do not, which needlessly
            invalidates caches. What matters is only that the stamp changes when
            the content does.
            """
            try:
                return str(int((static_root / name).stat().st_mtime))
            except OSError:
                return "0"

        def _stamp_asset_references(self, markup: str) -> str:
            """Append a content stamp to every versioned asset reference.

            Matches with or without a leading slash. It used to look only for a
            bare quoted name, so an asset referenced as "/i18n.js" was never
            stamped - and a browser kept serving the old module indefinitely
            while the page showed the new markup around it. That is the same
            failure as the scrambled deploy this stamping exists to prevent, one
            slash away.

            _test_static.py asserts that every versioned asset really does come
            back stamped, which is the check whose absence let this ship.
            """
            for asset in _VERSIONED_ASSETS:
                stamp = f"?v={self._asset_stamp(asset)}"
                for quoted in (f'"{asset}"', f'"/{asset}"'):
                    markup = markup.replace(quoted, f'{quoted[:-1]}{stamp}"')
            return markup

        def _serve_static(self, request_path: str, send_body: bool) -> None:
            path = self._static_path(request_path)
            if path is None:
                self._write_json(404, {"error": "not found"})
                return
            try:
                payload = path.read_bytes()
            except OSError:
                self._write_json(404, {"error": "not found"})
                return
            content_type = _STATIC_CONTENT_TYPES.get(
                path.suffix.lower(), "application/octet-stream"
            )

            # Every HTML page is an entry point, not just the first one. Hardcoded to
            # "index.html" when there was only one page; with three, the other two
            # would have had their asset references served unstamped and their cache
            # policy set from a version query they never emit. The rule is now "is it
            # markup", which is what the branch is actually for.
            is_entry = path.suffix.lower() == ".html"
            # The version lives in the query string, and request_path has
            # already been split off the path, so it is read from self.path.
            requested_version = urlsplit(self.path).query
            is_current_version = f"v={self._asset_stamp(path.name)}" in requested_version

            if is_entry:
                # The entry point must always be revalidated, and its asset
                # references are rewritten on the way out so a redeploy cannot
                # pair new markup with a cached old script.
                try:
                    payload = self._stamp_asset_references(payload.decode("utf-8")).encode("utf-8")
                except UnicodeDecodeError:
                    pass
                cache_control = "no-cache"
            elif is_current_version:
                # The version the page asked for is the version on disk, so the
                # browser may hold on to it until the next stamp changes.
                cache_control = "public, max-age=3600"
            else:
                # A bare hit from a bookmark or a stale page: revalidate, so a
                # direct visit never shows a superseded file.
                cache_control = "no-cache"

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_security_headers()
            self.end_headers()
            if send_body:
                self.wfile.write(payload)

        def _write_json(
            self,
            status: int,
            payload: dict[str, Any],
            extra_headers: dict[str, str] | None = None,
            send_body: bool = True,
        ) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_security_headers()
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if send_body:
                self.wfile.write(body)
            self._log_response(status, len(body))

        def _log_response(self, status: int, size: int) -> None:
            """One line per response: who asked for what, what they got, how long.

            A 5xx is logged at ERROR and everything quieter at INFO, so the file
            can be read either way — tail it to watch it, or grep ERROR to find
            what broke.
            """
            started = getattr(self, "_request_started", None)
            took = f"{(time.monotonic() - started) * 1000:.0f}ms" if started else "-"
            peer = self.client_address[0] if self.client_address else "?"
            detail = ""
            if status >= 400:
                detail = f" :: {getattr(self, '_error_detail', '') or '-'}"
            line = (
                f"{self.command} {self.path} -> {status} {took} {size}b "
                f"from={peer}{detail}"
            )
            LOG.log(logging.ERROR if status >= 500 else logging.INFO, line)

        def _fail(self, status: int, message: str, **context: Any) -> None:
            """Log a failure with its cause, then answer the caller briefly.

            The browser gets `message`. The log gets the reason and a traceback
            where there is one. Those are different audiences: leaking a
            traceback to a candidate tells them about our internals and still
            does not tell us anything.
            """
            where = " ".join(f"{k}={v}" for k, v in context.items())
            self._error_detail = f"{message} {where}".strip()
            LOG.error(
                "%s %s -> %d :: %s%s", self.command, self.path, status, message,
                f" ({where})" if where else "",
                exc_info=True,
            )
            self._write_json(status, {"error": message})

        def log_message(self, format: str, *args: Any) -> None:
            # BaseHTTPRequestHandler's access log was overridden to `return`, so
            # every line it would have written was discarded. Route it to ours.
            LOG.debug("base: " + (format % args))

    return ResumeHTTPServer((host, port), ResumeRequestHandler)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent / "docs")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.root)
    print(f"Jobby portal listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
