#!/usr/bin/env python3
"""Parse resume files into an auditable, source-derived profile payload."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from newsletter_ingest import _EMAIL_RE, _URL_RE
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError, PyPdfError
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    StreamObject,
)


MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_DOCX_DOCUMENT_XML_BYTES = 4 * 1024 * 1024
MAX_PDF_CONTENT_BYTES = 4 * 1024 * 1024
MAX_RESUME_TEXT_BYTES = 2 * 1024 * 1024
MAX_PDF_PAGES = 200
_SUPPORTED_FORMATS = {"pdf", "docx", "txt"}
_WORDPROCESSING_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_URL_CLEANUP = ".,;:!?)]}>'\""
_EMAIL_CLEANUP = _URL_CLEANUP
_SKILL_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:technical\s+)?skills?\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)
_JOB_FIELD_RULES = (
    (re.compile(r"\barchitect\b", re.IGNORECASE), "Architecture"),
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


def _extract_skills(text: str) -> list[str]:
    """Return explicitly listed skills without inventing implied expertise."""
    skills: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = _SKILL_LABEL_RE.search(line)
        if not match:
            continue
        for raw_skill in re.split(r"[,;|]", match.group(1)):
            skill = raw_skill.strip().strip("•*+-").strip()
            key = skill.casefold()
            if skill and key not in seen:
                seen.add(key)
                skills.append(skill)
    return skills


def _extract_job_fields(text: str) -> list[str]:
    """Map source terms to broad job fields for the review panel."""
    fields: list[str] = []
    seen: set[str] = set()
    for pattern, field in _JOB_FIELD_RULES:
        if pattern.search(text) and field.casefold() not in seen:
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
    urls = _unique_matches(_URL_RE, text, _URL_CLEANUP)
    emails = _unique_matches(_EMAIL_RE, text, _EMAIL_CLEANUP)
    skills = _extract_skills(text)
    job_fields = _extract_job_fields(text)
    return {
        "file": Path(file_path).name,
        "format": _format_for(Path(file_path), hint),
        "text": text,
        "skills": skills,
        "job_fields": job_fields,
        "urls": urls,
        "portfolio_urls": urls,
        "urls_found": len(urls),
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
