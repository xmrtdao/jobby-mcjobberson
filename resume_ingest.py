#!/usr/bin/env python3
"""Parse resume files into an auditable, source-derived profile payload."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from newsletter_ingest import _EMAIL_RE, _URL_RE
try:
    from pypdf import PdfReader, apply_configuration
    from pypdf.errors import LimitReachedError, PyPdfError
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        IndirectObject,
        NameObject,
        StreamObject,
    )
    _PDF_SUPPORT = True
except Exception:
    _PDF_SUPPORT = False


MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_DOCX_DOCUMENT_XML_BYTES = 4 * 1024 * 1024
MAX_PDF_CONTENT_BYTES = 4 * 1024 * 1024
MAX_RESUME_TEXT_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 200
_SUPPORTED_FORMATS = {"pdf", "docx", "txt"}
_WORDPROCESSING_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_URL_CLEANUP = ".,;:!?)]}>'\""
_EMAIL_CLEANUP = _URL_CLEANUP
# Matches a skills label on its own, with an optional inline list. The
# separator is optional but the rest of the line must be empty when it is
# absent, so prose like "Skilled in Python" is not mistaken for a label.
#
# "CORE COMPETENCIES" is included because it is one of the most common resume
# headings there is and its absence meant a whole section of named skills was
# silently dropped. That label also uses a "Category: a, b, c" line shape, which
# _extract_skills handles separately.
_SKILL_LABEL_RE = re.compile(
    r"^[ \t]*(?:technical\s+|core\s+|key\s+|main\s+|primary\s+)?"
    r"(?:areas?\s+of\s+)?"
    r"(?:skills?|tools?|technologies|tech\s+stack|expertise|competenc(?:y|ies)|strengths)"
    r"(?:\s+(?:&|and)\s+[\w\s]+?)?"
    r"\s*(?:[:\-]\s*(.*))?$",
    re.IGNORECASE,
)
# A skills block continues onto following lines. It ends at a blank line or
# at the next section heading, recognised by being a short all-caps line or a
# title ending in a colon ("EXPERIENCE", "Certifications:").
_SECTION_HEADING_RE = re.compile(
    r"^(?:[A-Z][A-Z0-9 &/'\-\.]{2,}[ \t]*:?|[A-Z][A-Za-z][A-Za-z ]{2,40}:)$"
)
_SKILL_DELIMITERS = (",", ";", "|", "\u2022", "\u00b7", "*")
_MAX_SKILL_CONTINUATION_LINES = 8
# A years-of-experience figure the document states outright, such as
# "15+ years of proven leadership" or "10 years in sales". The qualifier words
# keep a per-role duration ("3 years at Acme") from being read as a lifetime
# total when a summary is present. Years is a small, bounded claim: capping at
# 60 keeps a phone number or a ZIP+4 from being read as decades.
_STATED_YEARS_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*\+?\s*\+?\s*years?\b"
    r"(?![\d])",
    re.IGNORECASE,
)
_YEARS_QUALIFIER_RE = re.compile(
    r"(experience|professional|industry|career|leadership|proven|track record"
    r"|background|working|work)",
    re.IGNORECASE,
)
_MAX_CAREER_YEARS = 60


def _extract_stated_experience_years(text: str) -> float | None:
    """Return a years-of-experience figure the document actually states.

    A qualifier like "of proven leadership" or "of experience" belongs to the
    number it follows, so each candidate is judged only on the clause between it
    and the next years-figure. A fixed character window is wrong here: in
    "12 years total. 15 years of professional leadership" a wide window lets
    the later qualifier reach back and validate the 12, and the 12 wins.

    Where no figure is qualified, the largest is used. A career total is never
    shorter than one role inside it, so the maximum cannot understate the way
    taking the first match would. Returns None when the document states no
    figure, so the caller records a gap instead of computing one.
    """
    fallback: float | None = None
    for line in text.splitlines():
        matches = list(_STATED_YEARS_RE.finditer(line))
        for index, match in enumerate(matches):
            try:
                years = float(match.group(1))
            except ValueError:
                continue
            if years <= 0 or years > _MAX_CAREER_YEARS:
                continue
            # The clause this number governs: from the end of the previous
            # figure to the start of the next one.
            clause_start = matches[index - 1].end() if index else 0
            clause_end = (
                matches[index + 1].start() if index + 1 < len(matches) else len(line)
            )
            clause = line[clause_start:clause_end]
            if _YEARS_QUALIFIER_RE.search(clause):
                return years
            fallback = years if fallback is None else max(fallback, years)
    return fallback


# A phone number as written on a resume. Requires seven or more digits so that
# bare years, date ranges and postal codes are not read as numbers to call. The
# separator run is bounded so a phone cannot swallow a following date or ID.
_PHONE_RE = re.compile(
    r"(?<![\w.])\+?\d[\d\s().\u2010-\u2015-]{6,22}\d(?![\w-])"
)
_MIN_PHONE_DIGITS = 7


def _extract_phones(text: str) -> list[str]:
    """Return phone-shaped strings the document actually states.

    Formatting is normalised to a readable form but the digits are preserved
    exactly; nothing is guessed from a name or an email local part.
    """
    phones: list[str] = []
    seen: set[str] = set()
    for match in _PHONE_RE.finditer(text):
        raw = match.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) < _MIN_PHONE_DIGITS or len(digits) > 15:
            continue
        # A match whose every digit group is exactly four digits is a year
        # range ("2004 - 2014"), not a number to dial. Such a string also
        # satisfies the 7-to-15 digit length rule, because the dash between
        # the years is inside the character class. The length rule alone
        # therefore cannot separate a phone from employment dates.
        groups = re.findall(r"\d+", raw)
        if groups and all(len(g) == 4 for g in groups):
            continue
        pretty = re.sub(r"[\s().-]+", " ", raw).strip()
        key = digits
        if key not in seen:
            seen.add(key)
            phones.append(pretty)
    return phones


_JOB_FIELD_RULES = (
    # "architectural"/"architecture" rather than bare "architect": the bare
    # form is overwhelmingly a job title ("Systems Architect") or a verb
    # ("architect of complex projects"), and matching it put a sales and
    # media professional into the Architecture industry. Someone who
    # actually works in architecture writes the noun or adjective somewhere.
    (re.compile(r"\barchitectural\b|\barchitecture\b", re.IGNORECASE), "Architecture"),
    (
        re.compile(r"\b(?:cloud|aws|azure|gcp|kubernetes|terraform|devops|infrastructure)\b", re.IGNORECASE),
        "Cloud Engineering",
    ),
    (re.compile(r"\bsoftware\s+(?:engineer|developer|programmer)\b", re.IGNORECASE), "Software Engineering"),
    (re.compile(r"\bdata\s+(?:scientist|analyst|engineer)\b|\bmachine learning\b", re.IGNORECASE), "Data Science"),
    (re.compile(r"\bproduct\s+manager\b", re.IGNORECASE), "Product Management"),
    (re.compile(r"\bproject\s+manager\b", re.IGNORECASE), "Project Management"),
    (re.compile(r"\b(?:ux|ui)\s+designer\b|\bdesigner\b", re.IGNORECASE), "Design"),
)


class _PDFContentLimitError(ValueError):
    pass


class _PDFTextLimitError(ValueError):
    pass


def _pdf_object_key(value: Any) -> tuple[Any, ...]:
    if isinstance(value, IndirectObject):
        return ("indirect", value.idnum, value.generation)
    return ("direct", id(value))


def _resolve_pdf_object(value: Any) -> Any:
    while isinstance(value, IndirectObject):
        value = value.get_object()
    return value


def _iter_pdf_streams(
    value: Any,
    seen_streams: set[tuple[Any, ...]],
    seen_forms: set[tuple[Any, ...]],
    *,
    xobject_collection: bool = False,
):
    """Yield decoded content streams without following image streams."""
    value = _resolve_pdf_object(value)

    if isinstance(value, ArrayObject):
        for item in value:
            yield from _iter_pdf_streams(
                item,
                seen_streams,
                seen_forms,
                xobject_collection=xobject_collection,
            )
        return

    if isinstance(value, DictionaryObject) and value.get("/Subtype") == NameObject("/Form"):
        key = _pdf_object_key(value)
        if key in seen_forms:
            return
        seen_forms.add(key)
        yield from _iter_pdf_streams(
            value.get("/Contents"), seen_streams, seen_forms
        )
        resources = _resolve_pdf_object(value.get("/Resources"))
        if isinstance(resources, DictionaryObject):
            xobjects = _resolve_pdf_object(resources.get("/XObject"))
            if xobjects is not None:
                yield from _iter_pdf_streams(
                    xobjects,
                    seen_streams,
                    seen_forms,
                    xobject_collection=True,
                )
        return

    if isinstance(value, StreamObject):
        if value.get("/Subtype") == NameObject("/Image"):
            return
        key = _pdf_object_key(value)
        if key in seen_streams:
            return
        seen_streams.add(key)
        yield value
        return

    if xobject_collection and isinstance(value, DictionaryObject):
        for child in value.values():
            yield from _iter_pdf_streams(
                child,
                seen_streams,
                seen_forms,
                xobject_collection=True,
            )


def _decoded_pdf_content_bytes(page: Any) -> int:
    seen_streams: set[tuple[Any, ...]] = set()
    seen_forms: set[tuple[Any, ...]] = set()
    total = 0
    for stream in _iter_pdf_streams(page.get("/Contents"), seen_streams, seen_forms):
        total += len(stream.get_data())
        if total > MAX_PDF_CONTENT_BYTES:
            raise _PDFContentLimitError(
                "PDF decoded content exceeds the size limit"
            )
    resources = page.get("/Resources")
    if isinstance(resources, DictionaryObject):
        xobjects = resources.get("/XObject")
        if xobjects is not None:
            for stream in _iter_pdf_streams(
                xobjects,
                seen_streams,
                seen_forms,
                xobject_collection=True,
            ):
                total += len(stream.get_data())
                if total > MAX_PDF_CONTENT_BYTES:
                    raise _PDFContentLimitError(
                        "PDF decoded content exceeds the size limit"
                    )
    return total


def _format_for(path: Path, hint: str | None) -> str:
    if hint:
        candidate = hint.strip().lower().lstrip(".")
    else:
        candidate = path.suffix.lower().lstrip(".")
    if candidate not in _SUPPORTED_FORMATS:
        supported = ", ".join(sorted(_SUPPORTED_FORMATS))
        raise ValueError(f"unsupported resume format {candidate!r}; expected {supported}")
    return candidate


def _extract_docx_text(path: Path) -> str:
    """Extract paragraph text from a bounded, valid DOCX package."""
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                document_info = archive.getinfo("word/document.xml")
            except KeyError as error:
                raise ValueError("DOCX is missing word/document.xml") from error
            if document_info.file_size > MAX_DOCX_DOCUMENT_XML_BYTES:
                raise ValueError("DOCX document.xml exceeds the size limit")
            with archive.open(document_info) as source:
                document = source.read(MAX_DOCX_DOCUMENT_XML_BYTES + 1)
            if len(document) > MAX_DOCX_DOCUMENT_XML_BYTES:
                raise ValueError("DOCX document.xml exceeds the size limit")
        root = ElementTree.fromstring(document)
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, ValueError) as error:
        raise ValueError("invalid DOCX resume") from error
    paragraph_tag = f"{{{_WORDPROCESSING_NS}}}p"
    text_tag = f"{{{_WORDPROCESSING_NS}}}t"
    paragraphs: list[str] = []
    text_bytes = 0
    for paragraph in root.iter(paragraph_tag):
        text = "".join(
            node.text or "" for node in paragraph.iter(text_tag)
        ).strip()
        if not text:
            continue
        text_bytes += len(text.encode("utf-8"))
        if text_bytes > MAX_RESUME_TEXT_BYTES:
            raise ValueError("extracted DOCX text exceeds the size limit")
        paragraphs.append(text)
    return "\n".join(paragraphs)


def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF with bounded stream expansion."""
    try:
        # pypdf decodes compressed content streams lazily. Apply a per-parse
        # expansion limit around reader initialization and extraction so a
        # small compressed stream cannot allocate an arbitrarily large buffer.
        with apply_configuration(
            maximum_declared_stream_length=MAX_PDF_CONTENT_BYTES,
            array_based_stream_maximum_output_length=MAX_PDF_CONTENT_BYTES,
            jbig2_maximum_output_length=MAX_PDF_CONTENT_BYTES,
            lzw_maximum_output_length=MAX_PDF_CONTENT_BYTES,
            run_length_maximum_output_length=MAX_PDF_CONTENT_BYTES,
            zlib_maximum_output_length=MAX_PDF_CONTENT_BYTES,
            zlib_maximum_recovery_input_length=MAX_PDF_CONTENT_BYTES,
        ):
            with path.open("rb") as source:
                if source.read(5) != b"%PDF-":
                    raise ValueError("invalid PDF header")
            reader = PdfReader(path)
            try:
                if len(reader.pages) > MAX_PDF_PAGES:
                    raise ValueError(f"PDF exceeds the {MAX_PDF_PAGES}-page resume limit")
                decoded_content_bytes = 0
                text_parts: list[str] = []
                text_bytes = 0
                for page in reader.pages:
                    decoded_content_bytes += _decoded_pdf_content_bytes(page)
                    if decoded_content_bytes > MAX_PDF_CONTENT_BYTES:
                        raise _PDFContentLimitError(
                            "PDF decoded content exceeds the size limit"
                        )
                    page_text = page.extract_text() or ""
                    text_bytes += len(page_text.encode("utf-8"))
                    if text_bytes > MAX_RESUME_TEXT_BYTES:
                        raise _PDFTextLimitError(
                            "extracted PDF text exceeds the size limit"
                        )
                    if page_text:
                        text_parts.append(page_text)
                return "\n".join(text_parts).strip()
            finally:
                reader.close()
    except (OSError, ValueError, TypeError, LimitReachedError, PyPdfError) as error:
        if isinstance(error, (_PDFContentLimitError, _PDFTextLimitError)):
            raise
        if isinstance(error, ValueError) and str(error).startswith(
            ("invalid PDF header", "PDF exceeds")
        ):
            raise
        if isinstance(error, LimitReachedError):
            raise _PDFContentLimitError(
                "PDF content stream exceeds the size limit"
            ) from error
        raise ValueError("invalid or unreadable PDF resume") from error


def _read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if len(text.encode("utf-8")) > MAX_RESUME_TEXT_BYTES:
        raise ValueError("extracted resume text exceeds the size limit")
    return text


def _unique_matches(pattern: re.Pattern[str], text: str, cleanup: str) -> list[str]:
    seen: set[str] = set()
    matches: list[str] = []
    for raw_value in pattern.findall(text):
        value = raw_value.strip().rstrip(cleanup)
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            matches.append(value)
    return matches


def _iter_skill_blocks(text: str) -> list[str]:
    """Return the payload text of every skills block in the document.

    Handles both layouts seen in the wild: the list on the same line as the
    label ("Skills: Python, Go") and the label alone on its own line with the
    list underneath, which the original single-line pattern silently missed.
    """
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        match = _SKILL_LABEL_RE.match(lines[index])
        if not match:
            index += 1
            continue

        inline = (match.group(1) or "").strip()
        if inline:
            blocks.append(inline)
            index += 1
            continue

        # Bare label: consume the following lines until the block ends.
        index += 1
        taken = 0
        while index < len(lines) and taken < _MAX_SKILL_CONTINUATION_LINES:
            candidate = lines[index].strip()
            if not candidate or _SECTION_HEADING_RE.match(candidate):
                break
            # Continue only when the line actually reads as a list, or it is
            # the first line and the block is followed immediately by the end
            # of the section. A leading bullet marker counts as a list too.
            body = candidate.lstrip("-+\u2013\u2014\u2022\u00b7*").strip()
            looks_like_list = body != candidate or any(
                d in candidate for d in _SKILL_DELIMITERS
            )
            nxt = lines[index + 1].strip() if index + 1 < len(lines) else ""
            block_ends = not nxt or bool(_SECTION_HEADING_RE.match(nxt))
            if not looks_like_list and not (taken == 0 and block_ends):
                break
            blocks.append(candidate)
            index += 1
            taken += 1
    return blocks


def _clean_skill(value: str) -> str:
    skill = value.strip().strip("-+\u2013\u2014").strip().strip(".\u2022")
    return re.sub(r"\s+", " ", skill)


# A "Category: a, b, c" line inside a skills block. The category is itself a
# competency worth keeping, and the values after the colon are the individual
# skills. Capped short and barred from sentence punctuation, so prose such as
# "Note: unavailable until March, ideally" is not read as a competency.
_CATEGORY_LINE_RE = re.compile(r"^(?P<label>[^:]{2,60}):\s*(?P<values>.+)$")


def _extract_skills(text: str) -> list[str]:
    """Return explicitly listed skills without inventing implied expertise."""
    skills: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        skill = _clean_skill(value)
        if not skill or len(skill) > 80:
            return
        key = skill.casefold()
        if key not in seen:
            seen.add(key)
            skills.append(skill)

    for block in _iter_skill_blocks(text):
        # A competencies section groups skills under a heading:
        #   "Consultative Selling & Closing: value alignment, active listening"
        # Splitting on commas alone glued the heading onto the first value,
        # inventing a bogus skill and losing the real one.
        category = _CATEGORY_LINE_RE.match(block.strip())
        if category:
            label = category.group("label")
            if not re.search(r"[.!?]", label):
                add(label)
            block = category.group("values")
        for raw_skill in _split_skill_list(block):
            add(raw_skill)
    return skills


# A separator only separates when it is not inside a qualifier.
_SKILL_SEPARATORS = re.compile(r"[,;|\u2022\u00b7*]")
_OPENERS = "([{"
_CLOSERS = ")]}"


def _split_skill_list(block):
    """Split a skills line on its separators, ignoring any inside brackets.

    A comma inside parentheses is nearly always part of the skill rather than a
    boundary, and splitting on it destroys the entry — see the note above. Real
    skill lines use all three bracket kinds ("Python (Django, Flask)", "Scheduling
    [ Outlook, Google ]", "Configuration {XML, YAML}"), so depth is tracked for
    each.

    An unbalanced closer is treated as an ordinary character rather than allowed to
    drive the depth negative. Negative depth is the dangerous case: every subsequent
    separator in the document stops separating, and one stray ")" turns the rest of
    a resume into a single enormous skill. An unclosed opener is likewise left
    alone — the line still has a usable first entry, and inventing a boundary to
    balance it would be worse than a slightly long one.
    """
    parts = []
    buf = []
    depth = 0
    for ch in block:
        if ch in _OPENERS:
            depth += 1
            buf.append(ch)
            continue
        if ch in _CLOSERS:
            if depth > 0:
                depth -= 1
            buf.append(ch)
            continue
        if depth == 0 and _SKILL_SEPARATORS.match(ch):
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


# A job header line, e.g. "Lead Platform Engineer - Acme Systems (March 2021 -
# present)" or "Platform Engineer, Beta Labs, June 2017 - February 2021".
# Both forms require a date range, which keeps ordinary bullet lines out.
_DATE_TOKEN = (
    r"(?:[A-Za-z]{3,9}\.?\s+\d{4}|\d{1,2}\s*[/-]\s*\d{4}|(?:19|20)\d{2})"
)
_END_TOKEN = r"(?:" + _DATE_TOKEN + r"|present|current|now|ongoing|to\s+date)"
_EMPLOYMENT_HEADER_RES = (
    # Title - Company (Start - End)
    re.compile(
        r"^[ \t]*(?P<title>[^\n()]{2,70}?)[ \t]*(?:[ \t]+at[ \t]+|@|[-–—•])[ \t]*"
        r"(?P<company>[^\n()]{2,70}?)[ \t]*\([ \t]*"
        r"(?P<start>" + _DATE_TOKEN + r")[ \t]*(?:-|–|—|to|until|through)[ \t]*"
        r"(?P<end>" + _END_TOKEN + r")[ \t]*\)[ \t]*$",
        re.IGNORECASE,
    ),
    # Title, Company, Start - End
    re.compile(
        r"^[ \t]*(?P<title>[^\n,|]{2,70}?)[ \t]*(?:,| at |@)[ \t]*"
        r"(?P<company>[^\n,|]{2,70}?)[ \t]*,[ \t]*"
        r"(?P<start>" + _DATE_TOKEN + r")[ \t]*(?:-|–|—|to|until|through)[ \t]*"
        r"(?P<end>" + _END_TOKEN + r")[ \t]*$",
        re.IGNORECASE,
    ),
)
_CURRENT_WORDS = {"present", "current", "now", "ongoing", "to date"}

# A responsibility bullet sitting directly under a job header.
_BULLET_LINE_RE = re.compile(r"^[\u2022\u00b7\-\*\u2013\u2014+]\s*(?P<body>.+)$")
_MAX_JOB_HIGHLIGHTS = 10

# A TLD allowlist keeps ordinary prose out: "Node.js", "resume.docx" and "1.2"
# are not links, but "github.com/user" and "jellis.dev" are.
_TLD_ALTERNATION = (
    "com|org|net|edu|gov|io|dev|ai|co|me|app|tech|info|biz|site|online|xyz|us|uk|ca"
)
# The lookbehind rejects a domain that is the host part of an email address.
_BARE_DOMAIN_RE = re.compile(
    r"(?<![@.\w])"
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:" + _TLD_ALTERNATION + r")\b"
    r"(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)


def _url_key(value: str) -> str:
    """Compare URLs ignoring the scheme, so https://x.com and x.com are one."""
    return re.sub(r"^https?://", "", value, flags=re.IGNORECASE).casefold().rstrip("/")


def _extract_urls(text: str) -> list[str]:
    """Return full URLs plus bare domains such as "github.com/user".

    Resumes routinely list profiles with no scheme, and the newsletter-grade
    _URL_RE requires http(s):// — so those links were being dropped entirely.
    """
    urls = _unique_matches(_URL_RE, text, _URL_CLEANUP)
    seen = {_url_key(url) for url in urls}

    email_domains: set[str] = set()
    for address in _unique_matches(_EMAIL_RE, text, _EMAIL_CLEANUP):
        _, _, domain = address.partition("@")
        if domain:
            email_domains.add(domain.casefold())

    for match in _BARE_DOMAIN_RE.findall(text):
        candidate = match.strip(_URL_CLEANUP)
        key = _url_key(candidate)
        if not key or key in seen:
            continue
        host = key.split("/", 1)[0]
        # A domain belonging to an email address is not a profile link.
        if host in email_domains or any(
            host == d or host.endswith("." + d) for d in email_domains
        ):
            continue
        seen.add(key)
        urls.append(candidate)
    return urls


def _extract_employment_headers(text: str) -> list[dict[str, Any]]:
    """Pull role/company/date-range headers and their bullets from the document.

    Used to cross-check the AI-extracted timeline. The model was observed
    transposing month and year (emitting "2017-03" for a job the resume dates
    "March 2021"), which produced a work history overlapping the previous role.
    These values are copied verbatim from the text, so they win.

    The bullet lines directly beneath a header are its highlights. Those were
    also coming back empty from the model on some runs, and they are the most
    informative part of a resume, so they are read from the source.
    """
    headers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip().strip("*#>-").strip()
        index += 1
        if not stripped:
            continue
        matched = None
        for pattern in _EMPLOYMENT_HEADER_RES:
            match = pattern.match(stripped)
            if not match:
                continue
            title = match.group("title").strip(" ,;|-–—•")
            company = match.group("company").strip(" ,;|-–—•")
            start = match.group("start").strip()
            end = match.group("end").strip()
            if not title or not company:
                matched = False
                break
            # A reversed range is not a header.
            if re.fullmatch(r"\d{4}", start) and re.fullmatch(r"\d{4}", end):
                if int(end) < int(start):
                    matched = False
                    break
            matched = (title, company, start, end)
            break
        if matched is None or matched is False:
            continue
        title, company, start, end = matched
        key = (title.casefold(), company.casefold())
        if key in seen:
            continue
        seen.add(key)

        # Bullet lines immediately following the header belong to this job.
        highlights: list[str] = []
        while (
            index < len(lines)
            and len(highlights) < _MAX_JOB_HIGHLIGHTS
        ):
            bullet = _BULLET_LINE_RE.match(lines[index].strip())
            if not bullet:
                break
            text_body = bullet.group(1).strip()
            if text_body:
                highlights.append(re.sub(r"\s+", " ", text_body))
            index += 1

        headers.append(
            {
                "title": title,
                "company": company,
                "start": start,
                "end": None if end.casefold() in _CURRENT_WORDS else end,
                "current": end.casefold() in _CURRENT_WORDS,
                "highlights": highlights,
            }
        )
    return headers


def _strip_titles_for_field_matching(text: str) -> str:
    """Remove job-header lines before job-field keywords are matched.

    The rules below are industry terms, but the candidate's own job title is
    full of them. "Multi-Agent Systems Architect & Founder" was read as the
    Architecture industry, which would have had the agent targeting
    architecture roles for a sales and media professional. A title states what
    someone was called, not what industry they worked in, so any line that
    parses as an employment header is dropped before matching.
    """
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        # "Title | Employer | dates" is the header shape these documents use,
        # with the title first. Only the title is dropped: the employer is kept,
        # because a company name is real evidence of the industry while a job
        # title is only a label. Blanking the whole line lost "Architecture
        # Studio" along with "Systems Architect".
        if "|" in stripped and len(stripped) < 120:
            # _DATE_TOKEN is a pattern string, not a compiled regex.
            has_range = any(t in stripped for t in ("-", "\u2013", "\u2014"))
            has_range = has_range or bool(re.search(_DATE_TOKEN, stripped))
            if has_range:
                segments = [s.strip() for s in stripped.split("|") if s.strip()]
                kept.append(" | ".join(segments[1:]) if len(segments) > 1 else " ")
                continue
        header = None
        for rx in _EMPLOYMENT_HEADER_RES:
            header = rx.match(stripped)
            if header is not None:
                break
        if header is not None:
            employer = (header.groupdict().get("company") or "").strip()
            kept.append(employer if employer else " ")
            continue
        kept.append(line)
    return "\n".join(kept)


def _extract_job_fields(text: str) -> list[str]:
    """Map source terms to broad job fields for the review panel."""
    scannable = _strip_titles_for_field_matching(text)
    fields: list[str] = []
    seen: set[str] = set()
    for pattern, field in _JOB_FIELD_RULES:
        if pattern.search(scannable) and field.casefold() not in seen:
            seen.add(field.casefold())
            fields.append(field)
    return fields


def extract_resume_text(file_path: str | Path, hint: str | None = None) -> str:
    """Extract raw text from a supported resume without adding derived fields."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"resume file not found: {path}")
    if path.stat().st_size > MAX_RESUME_BYTES:
        raise ValueError(f"resume exceeds the {MAX_RESUME_BYTES // (1024 * 1024)} MB limit")

    resume_format = _format_for(path, hint)
    if resume_format == "docx":
        return _extract_docx_text(path)
    if resume_format == "pdf":
        return _extract_pdf_text(path)
    return _read_text(path)


def ingest_resume(file_path: str | Path, hint: str | None = None) -> dict[str, Any]:
    """Extract text, URLs, and email addresses from a supported resume file.

    The result contains only values present in the uploaded document. It never
    follows links, performs enrichment, or invents missing profile fields.
    """
    text = extract_resume_text(file_path, hint)
    urls = _extract_urls(text)
    emails = _unique_matches(_EMAIL_RE, text, _EMAIL_CLEANUP)
    skills = _extract_skills(text)
    job_fields = _extract_job_fields(text)
    return {
        "file": Path(file_path).name,
        "format": _format_for(Path(file_path), hint),
        "text": text,
        "skills": skills,
        "job_fields": job_fields,
        "employment_hints": _extract_employment_headers(text),
        "urls": urls,
        "portfolio_urls": urls,
        "urls_found": len(urls),
        "stated_experience_years": _extract_stated_experience_years(text),
        "phones": _extract_phones(text),
        "emails": emails,
        "emails_found": len(emails),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--hint")
    args = parser.parse_args()
    print(json.dumps(ingest_resume(args.file, args.hint), indent=2))
