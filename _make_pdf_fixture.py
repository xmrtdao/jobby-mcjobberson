#!/usr/bin/env python3
"""Build a DOCX and a PDF from test_resume.txt, for the PDF parity test.

Both are generated from the same source text so the A/B is meaningful: whatever
the PDF path loses relative to the DOCX path is a PDF problem, not a difference in
the document. python-docx writes the DOCX; the PDF is written directly with a
Helvetica text layer, because no PDF library is installed and Word COM hung on
opening a .txt.

The PDF is deliberately not trivial - Flate-compressed content stream, explicit
font resource, per-line text positioning, multiple pages - so it exercises the
parts of pypdf's extraction path that a naive single-blob PDF would skip.
"""
import io
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "test_resume.txt")
DOCX = os.path.join(HERE, "test_resume.docx")
PDF = os.path.join(HERE, "test_resume.pdf")

lines = [l.rstrip() for l in io.open(SRC, encoding="utf-8").read().splitlines()]
while lines and not lines[-1].strip():
    lines.pop()

# --- DOCX --------------------------------------------------------------------
import docx  # noqa: E402

document = docx.Document()
for line in lines:
    document.add_paragraph(line)
document.save(DOCX)
print("  docx %6d bytes" % os.path.getsize(DOCX))


# --- PDF ---------------------------------------------------------------------
# Escape for a PDF literal string, and stay on WinAnsi so a byte-for-byte
# comparison against the DOCX text is meaningful.
def pdf_escape(text):
    out = []
    for ch in text:
        if ch in "()\\":
            out.append("\\" + ch)
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append("?")  # the fixture is ASCII; anything else is dropped
    return "".join(out)


def layout(all_lines, per_page=46):
    """Split into pages and assign a font size per line."""
    pages = [all_lines[i:i + per_page] for i in range(0, len(all_lines), per_page)]
    return pages or [[]]


def content_stream(page_lines):
    parts = ["BT", "/F1 10 Tf", "12 TL", "1 0 0 1 54 738 Tm"]
    for line in page_lines:
        size = 13 if line and line == line.upper() and len(line) < 40 else 10
        parts.append("/F1 %d Tf" % size)
        parts.append("(%s) Tj" % pdf_escape(line))
        parts.append("T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1", "replace")


pages = layout(lines)
objects = []          # 1-indexed object bodies; objects[n] becomes object n+1
page_count = len(pages)

# 1 catalog, 2 pages tree, 3 font
objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
objects.append(("<< /Type /Pages /Kids [%s] /Count %d >>"
                % (" ".join("%d 0 R" % (5 + 2 * i) for i in range(page_count)),
                   page_count)).encode("latin-1"))
objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
               b"/Encoding /WinAnsiEncoding >>")

# Then a content stream followed by its page, per page.
#
# Object numbers are assigned by position: after appending the content stream it
# sits at index 3, so it is object 4, and the page that follows is object 5. The
# first attempt computed the page reference as len(objects) + 1, which pointed
# the page at itself, and pypdf then extracted zero characters from a
# structurally valid but contentless PDF - a fixture that silently tested
# nothing.
page_object_numbers = []
for page_lines in pages:
    stream = zlib.compress(content_stream(page_lines))
    objects.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
                   + stream + b"\nendstream")
    content_object = len(objects)          # 1-based: index + 1 == len(objects)
    page_object_numbers.append(content_object + 1)
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                   b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
                   % content_object)

out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
offsets = []
for index, body in enumerate(objects, start=1):
    offsets.append(len(out))
    out += b"%d 0 obj\n" % index + body + b"\nendobj\n"

xref_at = len(out)
out += b"xref\n0 %d\n" % (len(objects) + 1)
out += b"0000000000 65535 f \n"
for offset in offsets:
    out += b"%010d 00000 n \n" % offset
out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref_at))

io.open(PDF, "wb").write(bytes(out))
print("  pdf  %6d bytes, %d page(s)" % (os.path.getsize(PDF), page_count))
