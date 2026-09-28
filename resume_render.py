#!/usr/bin/env python3
"""Render a dossier into a downloadable resume.

The dossier is the record of what is known. This turns it into a document a
person can send, and it inherits the dossier's rules rather than inventing
anything of its own:

  - Nothing appears that is not in the dossier. A field the dossier could not
    establish is omitted, not guessed at.
  - Years of experience is printed with the figure the dossier published, and
    when the dossier records a different stated figure the document says which
    one it used. A resume that quietly disagreed with itself is worse than one
    that is simply dated.
  - Everything is laid out as plain paragraphs. Applicant tracking systems parse
    text far more reliably than they parse tables, columns or text boxes, and
    LinkedIn's PDF reader chokes on most of them.

DOCX is the primary format because it is what most ATS upload paths and
LinkedIn both accept, and because the candidate can correct a word without
re-downloading. HTML is offered as a print-to-PDF fallback for the same reason.
"""

from __future__ import annotations

import html as html_mod
from datetime import datetime
from typing import Any

# python-docx is imported lazily so the portal still starts if it is missing.
# A missing renderer should degrade to "no download" rather than take the whole
# resume service down with it.
try:  # pragma: no cover - import guard
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    DOCX_AVAILABLE = True
except ImportError:  # pragma: no cover - import guard
    DOCX_AVAILABLE = False


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _contact_line(dossier: dict[str, Any]) -> list[str]:
    """Contact details in the order a reader expects them."""
    parts: list[str] = []
    for key in ("email", "phone", "location"):
        value = _text(dossier.get(key))
        if value:
            parts.append(value)
    links = dossier.get("links")
    if isinstance(links, dict):
        for key in ("linkedin", "github", "portfolio", "website"):
            value = _text(links.get(key))
            if value and value not in parts:
                parts.append(value)
        for value in links.get("other") or []:
            value = _text(value)
            if value and value not in parts:
                parts.append(value)
    return parts


def format_date_range(job: dict[str, Any]) -> str:
    """A start and end as a reader expects, or the present tense.

    Overlapping roles are normal - a business run alongside a day job, a contract
    inside a founding period - so nothing is clipped or reordered here. The
    document is a record of what happened, not a claim that the hours add up.
    """
    start = _text(job.get("start")) or "Date not stated"
    if job.get("current"):
        return f"{start} - Present"
    end = _text(job.get("end"))
    if not end:
        return f"{start} - End not stated"
    return f"{start} - {end}"


def experience_summary(dossier: dict[str, Any]) -> str | None:
    """One line about total experience, with its provenance kept intact.

    The dossier publishes a figure measured from the employment dates and keeps
    the resume's own stated figure in a separate field. Printing only the
    published one would hide that the document once claimed something different,
    so when both exist the line names the source.
    """
    years = dossier.get("experience_years")
    if not isinstance(years, (int, float)) or isinstance(years, bool):
        return None
    rounded = int(round(float(years)))
    if rounded <= 0:
        return None
    span = dossier.get("experience_years_from_dates")
    line = f"{rounded} years of professional experience"
    if isinstance(span, dict) and span.get("from") and span.get("to"):
        line += f" ({span['from']} to {span['to']}, measured from employment dates)"
    return line


def _ordered_roles(dossier: dict[str, Any]) -> list[dict[str, Any]]:
    """Current roles first, then most recent first.

    Sorted on the year found in the date text, with anything undated last
    rather than guessed into a position. An undated role is still printed, at
    the end, because hiding it would be worse than showing it out of order.
    """
    jobs = [j for j in (dossier.get("employment") or []) if isinstance(j, dict)]

    def sort_key(job: dict[str, Any]):
        raw = _text(job.get("start"))
        year = None
        for token in raw.replace("/", " ").split():
            if token.isdigit() and len(token) == 4:
                year = int(token)
                break
        # Undated sorts last; current roles outrank ended ones of the same year.
        return (year is None, -(year or 0), not bool(job.get("current")))

    return sorted(jobs, key=sort_key)


def _role_bullets(job: dict[str, Any]) -> list[str]:
    bullets: list[str] = []
    for highlight in job.get("highlights") or []:
        value = _text(highlight)
        if value:
            bullets.append(value)
    description = _text(job.get("description"))
    if description:
        bullets.append(description)
    return bullets


# ── DOCX ────────────────────────────────────────────────────────────────────


def render_docx(dossier: dict[str, Any]) -> bytes:
    """A DOCX resume built from the dossier."""
    if not DOCX_AVAILABLE:
        raise RuntimeError("python-docx is not installed")

    document = Document()

    # ATS parsers read plain text most reliably, so the body font is a common
    # one and the sizes stay conventional.
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)

    name = _text(dossier.get("name"))
    if name:
        heading = document.add_paragraph()
        run = heading.add_run(name)
        run.bold = True
        run.font.size = Pt(18)
        heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
        heading.paragraph_format.space_after = Pt(2)

    title_bits = [b for b in (_text(dossier.get("current_title")),) if b]
    if title_bits:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(" - ".join(title_bits))
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(0x44, 0x44, 0x44)
        paragraph.paragraph_format.space_after = Pt(2)

    for part in _contact_line(dossier):
        paragraph = document.add_paragraph()
        run = paragraph.add_run(part)
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        paragraph.paragraph_format.space_after = Pt(0)

    summary_line = experience_summary(dossier)
    if summary_line:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(summary_line)
        run.italic = True
        run.font.size = Pt(10)
        paragraph.paragraph_format.space_before = Pt(6)
        paragraph.paragraph_format.space_after = Pt(2)

    if _text(dossier.get("summary")):
        document.add_paragraph(_text(dossier["summary"]))

    roles = _ordered_roles(dossier)
    if roles:
        document.add_paragraph()
        heading = document.add_paragraph()
        run = heading.add_run("PROFESSIONAL EXPERIENCE")
        run.bold = True
        run.font.size = Pt(11)
        heading.paragraph_format.space_before = Pt(8)
        heading.paragraph_format.space_after = Pt(2)

        for job in roles:
            company = _text(job.get("company")) or "Employer not stated"
            role_title = _text(job.get("title"))
            location = _text(job.get("location"))

            paragraph = document.add_paragraph()
            run = paragraph.add_run(company)
            run.bold = True
            run.font.size = Pt(10.5)
            paragraph.paragraph_format.space_before = Pt(6)
            paragraph.paragraph_format.space_after = Pt(0)

            if role_title:
                paragraph = document.add_paragraph()
                run = paragraph.add_run(role_title)
                run.font.size = Pt(10.5)
                paragraph.paragraph_format.space_after = Pt(0)

            meta = format_date_range(job)
            if location:
                meta = f"{meta} | {location}"
            paragraph = document.add_paragraph()
            run = paragraph.add_run(meta)
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            paragraph.paragraph_format.space_after = Pt(1)

            for bullet in _role_bullets(job):
                paragraph = document.add_paragraph(bullet, style="List Bullet")
                paragraph.paragraph_format.space_after = Pt(0)
                for run in paragraph.runs:
                    run.font.size = Pt(10)

    education = [e for e in (dossier.get("education") or []) if isinstance(e, dict)]
    if education:
        document.add_paragraph()
        heading = document.add_paragraph()
        run = heading.add_run("EDUCATION")
        run.bold = True
        run.font.size = Pt(11)
        heading.paragraph_format.space_before = Pt(8)
        heading.paragraph_format.space_after = Pt(2)
        for entry in education:
            parts = [
                _text(entry.get("institution")),
                _text(entry.get("degree")),
                _text(entry.get("field")),
                _text(entry.get("year")),
            ]
            line = " - ".join(p for p in parts if p)
            if line:
                paragraph = document.add_paragraph(line)
                paragraph.paragraph_format.space_after = Pt(0)

    skills = [s for s in (dossier.get("skills") or []) if _text(s)]
    if skills:
        document.add_paragraph()
        heading = document.add_paragraph()
        run = heading.add_run("SKILLS")
        run.bold = True
        run.font.size = Pt(11)
        heading.paragraph_format.space_before = Pt(8)
        heading.paragraph_format.space_after = Pt(2)
        paragraph = document.add_paragraph(", ".join(_text(s) for s in skills))
        paragraph.paragraph_format.space_after = Pt(0)

    certifications = [c for c in (dossier.get("certifications") or []) if _text(c)]
    if certifications:
        document.add_paragraph()
        heading = document.add_paragraph()
        run = heading.add_run("CERTIFICATIONS")
        run.bold = True
        run.font.size = Pt(11)
        heading.paragraph_format.space_before = Pt(8)
        heading.paragraph_format.space_after = Pt(2)
        for entry in certifications:
            paragraph = document.add_paragraph(_text(entry))
            paragraph.paragraph_format.space_after = Pt(0)

    import io

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ── HTML ────────────────────────────────────────────────────────────────────


def render_html(dossier: dict[str, Any]) -> str:
    """A print-ready HTML resume, for the candidate who wants a PDF.

    The page carries a print stylesheet so the browser's own Save as PDF gives a
    clean A4 or Letter document. Kept deliberately plain for the same ATS
    reason as the DOCX path.
    """
    esc = html_mod.escape
    parts: list[str] = []
    parts.append(
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>" + esc(_text(dossier.get("name")) or "Resume") + "</title>"
        "<style>"
        "body{font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.45;"
        "color:#1a1a1a;max-width:7in;margin:0.6in auto;padding:0 0.2in}"
        "h1{font-size:19pt;margin:0 0 2px}"
        ".title{font-size:12pt;color:#444;margin:0 0 4px}"
        ".contact{font-size:9.5pt;color:#333;margin:0}"
        ".contact span:after{content:' | ';color:#999}"
        ".contact span:last-child:after{content:''}"
        ".years{font-style:italic;font-size:10pt;margin:8px 0 2px}"
        "h2{font-size:11.5pt;letter-spacing:.04em;border-bottom:1px solid #ccc;"
        "margin:14px 0 4px;padding-bottom:2px}"
        ".job{margin:0 0 9px}"
        ".co{font-weight:bold}"
        ".rt{font-size:11pt}"
        ".meta{font-size:9.5pt;color:#555}"
        "ul{margin:3px 0 0 18px;padding:0}"
        "li{margin:0 0 2px}"
        "@media print{body{margin:0;max-width:none}}"
        "</style></head><body>"
    )

    name = _text(dossier.get("name"))
    if name:
        parts.append("<h1>" + esc(name) + "</h1>")
    role_title = _text(dossier.get("current_title"))
    if role_title:
        parts.append('<p class="title">' + esc(role_title) + "</p>")
    contact = _contact_line(dossier)
    if contact:
        parts.append(
            '<p class="contact">'
            + "".join("<span>" + esc(part) + "</span>" for part in contact)
            + "</p>"
        )
    summary_line = experience_summary(dossier)
    if summary_line:
        parts.append('<p class="years">' + esc(summary_line) + "</p>")
    if _text(dossier.get("summary")):
        parts.append("<p>" + esc(_text(dossier["summary"])) + "</p>")

    roles = _ordered_roles(dossier)
    if roles:
        parts.append("<h2>PROFESSIONAL EXPERIENCE</h2>")
        for job in roles:
            parts.append('<div class="job">')
            parts.append('<div class="co">' + esc(_text(job.get("company")) or "Employer not stated") + "</div>")
            if _text(job.get("title")):
                parts.append('<div class="rt">' + esc(_text(job["title"])) + "</div>")
            meta = format_date_range(job)
            location = _text(job.get("location"))
            if location:
                meta = f"{meta} | {location}"
            parts.append('<div class="meta">' + esc(meta) + "</div>")
            bullets = _role_bullets(job)
            if bullets:
                parts.append("<ul>" + "".join("<li>" + esc(b) + "</li>" for b in bullets) + "</ul>")
            parts.append("</div>")

    education = [e for e in (dossier.get("education") or []) if isinstance(e, dict)]
    if education:
        parts.append("<h2>EDUCATION</h2>")
        for entry in education:
            line = " - ".join(
                p for p in (
                    _text(entry.get("institution")),
                    _text(entry.get("degree")),
                    _text(entry.get("field")),
                    _text(entry.get("year")),
                ) if p
            )
            if line:
                parts.append("<p>" + esc(line) + "</p>")

    skills = [s for s in (dossier.get("skills") or []) if _text(s)]
    if skills:
        parts.append("<h2>SKILLS</h2>")
        parts.append("<p>" + esc(", ".join(_text(s) for s in skills)) + "</p>")

    certifications = [c for c in (dossier.get("certifications") or []) if _text(c)]
    if certifications:
        parts.append("<h2>CERTIFICATIONS</h2>")
        for entry in certifications:
            parts.append("<p>" + esc(_text(entry)) + "</p>")

    parts.append("</body></html>")
    return "".join(parts)


def render(dossier: dict[str, Any], fmt: str = "docx") -> tuple[bytes, str, str]:
    """Return (bytes, content-type, filename) for the requested format."""
    safe = "".join(
        c if c.isalnum() or c in " -_" else "" for c in (_text(dossier.get("name")) or "resume")
    ).strip() or "resume"
    filename_base = "-".join(safe.split()) or "resume"
    stamp = datetime.now().strftime("%Y-%m-%d")

    if fmt == "html":
        return render_html(dossier).encode("utf-8"), "text/html; charset=utf-8", f"{filename_base}-resume-{stamp}.html"
    return (
        render_docx(dossier),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        f"{filename_base}-resume-{stamp}.docx",
    )
