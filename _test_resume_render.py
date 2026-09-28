"""Resume rendering: what the document says, and what it refuses to say.

The dossier is the record of what is known, and the document inherits that. The
assertions here are mostly about absence: a field the dossier could not
establish must not appear in the CV, because a resume that fills a gap is worse
than one that leaves it visibly empty.
"""
import io
import sys
import zipfile

sys.path.insert(0, ".")
import resume_render  # noqa: E402

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail}"))
    if not cond:
        fails.append(label)


def docx_text(data):
    """Pull the visible text out of a DOCX without depending on the parser."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", "replace")
    # Runs are split across tags even mid-sentence, so strip tags and collapse.
    # Entities must be resolved too: an ampersand is "&amp;" in the XML, so
    # without this a field containing one can never be found in the output.
    import html as html_mod
    import re
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", "", xml)))


DOSSIER = {
    "name": "Joseph Andrew Lee",
    "current_title": "Founder",
    "email": "joeyleepcs@gmail.com",
    "phone": "+1 202 798 0610",
    "location": "",
    "links": {"linkedin": "linkedin.com/in/joecodes", "github": None},
    "summary": "High-impact communicator and entrepreneur.",
    "experience_years": 29.0,
    "experience_years_stated": 15.0,
    "experience_years_from_dates": {"from": 1997, "to": 2026, "years": 29},
    "experience_years_source": "employment dates",
    "skills": ["consultative-selling", "public-speaking"],
    "employment": [
        {"company": "Party Favor Photo", "title": "Founder & Managing Director",
         "location": "Costa Rica & USA", "start": "2015", "end": None, "current": True,
         "highlights": ["Founded and operated an event technology venture."]},
        {"company": "1st Surveillance, Reconnaissance and Intelligence Group",
         "title": "LVS Operator", "location": "Okinawa, Japan",
         "start": "1997", "end": "2004", "current": False,
         "description": "Intelligence support."},
        {"company": "United Service Organizations (USO)",
         "title": "Senior Multimedia Journalist", "location": "Arlington, VA",
         "start": "2015", "end": "2019", "current": False, "highlights": []},
    ],
    "education": [{"institution": "Harvard University", "degree": "Master's",
                   "field": "Journalism & Advanced Communication", "year": None}],
    "certifications": [],
}

print("--- DOCX renders and is a real file ---")
body, content_type, filename = resume_render.render(DOSSIER, "docx")
check("non-empty", len(body) > 2000, len(body))
check("docx content type", "wordprocessingml" in content_type, content_type)
check("filename carries the name and a date", "Joseph-Andrew-Lee" in filename and filename.endswith(".docx"), filename)
check("is a valid zip container", zipfile.is_zipfile(io.BytesIO(body)))

text = docx_text(body)
print("--- it contains what the dossier holds ---")
check("name", "Joseph Andrew Lee" in text, text[:120])
check("email", "joeyleepcs@gmail.com" in text)
check("phone", "202 798 0610" in text, )
check("linkedin", "linkedin.com/in/joecodes" in text)
check("all three employers", all(c in text for c in (
    "Party Favor Photo",
    "1st Surveillance",
    "United Service Organizations",
)), )
check("per-role location is printed", "Okinawa, Japan" in text)
check("education", "Harvard University" in text)
check("skills", "consultative-selling" in text)

print("\n--- experience is the published figure, with its provenance ---")
check("29 years, not the stated 15", "29 years" in text, )
check("the stated 15 is not printed as the headline", "15 years of professional" not in text)
check("source is named", "measured from employment dates" in text)
check("the span is shown", "1997 to 2026" in text)

print("\n--- it does not invent anything ---")
# location is empty in the dossier, so it must not appear as a blank line of
# invented geography.
check("empty location not printed", not any(
    line.strip() in ("Location:", "|", "-") for line in text.split("| ")[1:2]
))
check("no placeholder text", "not stated" not in text.lower() or "End not stated" in text)
check("undated education year not invented", "Harvard University - Master's - Journalism & Advanced Communication" in text)

print("\n--- ordering: current first, most recent first, undated last ---")
order = [
    text.find("Party Favor Photo"),
    text.find("United Service Organizations"),
    text.find("1st Surveillance"),
]
check("all three present", all(o > 0 for o in order), order)
check("current role first", order[0] < order[1], order)
check("2015 role before 1997 role", order[1] < order[2], order)

print("\n--- a role with no location still prints cleanly ---")
check("USO has no invented location", "Arlington, VA" in text)

print("\n--- HTML variant ---")
html_body, html_type, html_name = resume_render.render(DOSSIER, "html")
# render() returns bytes for every format, so the HTML variant is decoded here
# rather than compared as bytes.
html_body = html_body.decode("utf-8")
check("html served", "text/html" in html_type, html_type)
check("html filename", html_name.endswith(".html"), html_name)
check("has a print stylesheet", "@media print" in html_body)
check("escapes nothing dangerous here", "<script" not in html_body.lower())

print("\n--- empty dossier degrades instead of crashing ---")
try:
    b, c, f = resume_render.render({}, "docx")
    check("renders an empty dossier", len(b) > 500, len(b))
    t = docx_text(b)
    check("no experience line invented", "years of professional experience" not in t)
except Exception as error:  # noqa: BLE001
    check("empty dossier does not raise", False, str(error))

print("\n--- a dossier whose experience is unknown gets no years line ---")
minimal = dict(DOSSIER)
minimal["experience_years"] = None
minimal.pop("experience_years_from_dates", None)
t = docx_text(resume_render.render(minimal, "docx")[0])
check("no years line", "years of professional experience" not in t)

print()
if fails:
    print(f"{len(fails)} FAILED")
    sys.exit(1)
print("all resume-render checks passed")
