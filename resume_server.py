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
import os
import re
import tempfile
import threading
import time
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
}
_STATIC_ASSETS = {"index.html", "styles.css", "app.js", "jobby.js"}
# The assets that get a version stamp in the entry point's markup.
_VERSIONED_ASSETS = ("app.js", "styles.css", "jobby.js")
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
_JOBBY_SESSION_COOKIE = "jobby_sid"
_JOBBY_PROXY_PREFIX = "/api/jobby/"
_JOBBY_PROXY_TIMEOUT = 200

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
        )

    filename = _safe_filename(header_filename)
    return filename, body, content_type, hint


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


def _llm_json(system: str, user: str, *, temperature: float = 0.2) -> dict[str, Any]:
    """One model call, expected to answer with a single JSON object.

    Every value here is an interpretation of a document the deterministic
    extractor has already read, so the prompt forbids inventing anything. A
    model that answers with prose instead of JSON gets one repair attempt,
    because it does that intermittently and the alternative is losing the pass.
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
    if any(token in lowered for token in ("http://", "https://")) and "." in lowered.split("//")[-1].split("/")[0]:
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
        for key in ("start", "end"):
            value = hint.get(key)
            if isinstance(value, str) and value.strip():
                job[key] = value.strip()
                job["dates_from"] = "resume"
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


def _build_dossier(text: str, filename: str, ingested: dict[str, Any]) -> dict[str, Any]:
    """Run the model passes, then lay the deterministic floor underneath.

    Three short passes rather than one long one: a single request for a whole
    profile is where the model starts transposing dates and inventing
    employers. Split by concern it stays on task, and each pass is small enough
    to be retried when it answers with prose instead of JSON.
    """
    identity = history = interpret = {}
    failures: list[str] = []

    for label, system, schema, run in (
        ("identity", _IDENTITY_SYSTEM, _IDENTITY_SCHEMA, "identity"),
        ("history", _HISTORY_SYSTEM, _HISTORY_SCHEMA, "history"),
        ("interpret", _INTERPRET_SYSTEM, _INTERPRET_SCHEMA, "interpret"),
    ):
        prompt = (
            f"{schema}"
            "Here is the resume. Answer with the JSON object only.\n\n"
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
        try:
            result = _llm_json(system, prompt)
        except ModelUnavailable as error:
            failures.append(f"{label}: {error}")
            result = {}
        if run == "identity":
            identity = result
        elif run == "history":
            history = result
        else:
            interpret = result

    dossier = _merge_dossier(identity, history)
    for key, value in interpret.items():
        if key not in dossier or dossier.get(key) in (None, "", [], {}):
            dossier[key] = value

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


def _run_dossier_job(
    request_id: str, text: str, filename: str, ingested: dict[str, Any], cookie: str | None
) -> None:
    try:
        profile = _build_dossier(text, filename, ingested)
        _dossier_job_put(request_id, {"status": "done", "profile": profile})
        onboarding = _onboard_with_jobby(profile, filename, cookie)
        if isinstance(onboarding, dict) and onboarding:
            _dossier_job_put(request_id, {
                "status": "done",
                "profile": {**profile, "onboarding": onboarding},
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
            if path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("GET")
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
            self._serve_static(path, send_body=False)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path != "/api/resume/parse":
                if path.startswith(_JOBBY_PROXY_PREFIX):
                    self._proxy_to_relay("POST")
                    return
                self._write_json(404, {"error": "not found"})
                return
            self._parse_resume()

        def do_PATCH(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlsplit(self.path).path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("PATCH")
                return
            self._write_json(404, {"error": "not found"})

        def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlsplit(self.path).path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("PUT")
                return
            self._write_json(404, {"error": "not found"})

        def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlsplit(self.path).path.startswith(_JOBBY_PROXY_PREFIX):
                self._proxy_to_relay("DELETE")
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
                filename, payload, part_content_type, hint = _extract_resume_upload(
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
                _dossier_job_put(request_id, {"status": "processing"})
                thread = threading.Thread(
                    target=_run_dossier_job,
                    args=(request_id, result.get("text", ""), filename, result, cookie),
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
                self._write_json(500, {"error": "resume parsing failed"})

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
                self._write_json(202, {"status": "processing"})
                return
            self._write_json(200, {"status": "done", "profile": job.get("profile")})

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

        def _relay_response(self, status: int, response: Any, method: str) -> None:
            raw = response.read()
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
            for asset in _VERSIONED_ASSETS:
                markup = markup.replace(f'"{asset}"', f'"{asset}?v={self._asset_stamp(asset)}"')
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

            is_entry = path.name == "index.html"
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

        def log_message(self, format: str, *args: Any) -> None:
            return

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
