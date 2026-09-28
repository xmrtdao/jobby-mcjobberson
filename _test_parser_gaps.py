"""Regression tests for the four gaps found by parsing a real resume end to end.

Every case here was a live failure against Joseph Andrew Lee's actual
"Joseph Andrew Lee Resume - Sales ELVTR.docx" on jobby.mobilemonero.com. The
dossier reported 21 named skills as zero, dropped a phone number the resume
stated in plain sight, and tagged a sales and media professional into the
Architecture industry because his job title contained the word "Architect".

The theme is the same in all three: the parser only recognised one layout, and
anything else was dropped in silence rather than reported. A gap that is
reported can be researched; a gap that is silent looks like a fact.
"""
import sys

sys.path.insert(0, ".")
from resume_ingest import (  # noqa: E402
    _extract_job_fields,
    _extract_phones,
    _extract_skills,
    _extract_stated_experience_years,
)

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail}"))
    if not cond:
        fails.append(label)


CONTACT = (
    "Joseph Andrew Lee\n"
    "Contact: joeyleepcs@gmail.com | +1-202-798-0610 | linkedin.com/in/joecodes\n"
)
COMPETENCIES = (
    "CORE COMPETENCIES\n"
    "Consultative Selling & Closing: High-ticket program conversions, value alignment.\n"
    "Relationship & Trust Building: Executive-level communication, objection handling.\n"
)

print("--- CORE COMPETENCIES (was: no skills at all) ---")
r = _extract_skills(COMPETENCIES)
check("named a skills section", len(r) > 0, r)
check("kept the category label", "Consultative Selling & Closing" in r, r)
check("did not glue label to first value",
      not any(s.startswith("Consultative Selling & Closing:") for s in r), r)
check("kept the individual values", "value alignment" in r, r)
check("kept second category", "Relationship & Trust Building" in r, r)

for heading in ("CORE COMPETENCIES", "COMPETENCIES", "CORE SKILLS",
                "AREAS OF EXPERTISE", "KEY STRENGTHS", "SKILLS"):
    r = _extract_skills(heading + "\nPython, Go, Kubernetes")
    check("heading %r recognised" % heading, r == ["Python", "Go", "Kubernetes"], r)

print("\n--- prose must not become a skill ---")
r = _extract_skills("CORE COMPETENCIES\nNote: unavailable until March, ideally")
check("sentence prose not read as a competency",
      not any(s.lower().startswith("note:") for s in r), r)

print("\n--- phone extraction (there was no pattern at all) ---")
r = _extract_phones(CONTACT)
check("found the stated phone", len(r) == 1, r)
check("kept every digit",
      r and "".join(ch for ch in r[0] if ch.isdigit()) == "12027980610", r)

for probe, want in [
    ("Call 202-798-0610 today", True),
    ("(202) 555-0147", True),
    ("+44 20 7946 0958", True),
]:
    check("real format %r" % probe, bool(_extract_phones(probe)) is want, _extract_phones(probe))

print("\n--- date ranges must not be read as phones ---")
for probe in ("2004 - 2014", "2015 - 2021", "2004 – 2014", "2015 – 2021",
              "Experience 2004 - 2014 at Foo", "2011 - 2013, 2015 - present"):
    r = _extract_phones(probe)
    check("year range %r rejected" % probe, r == [], r)

r = _extract_phones("2004 - 2014\nCall 202-798-0610")
check("real phone still found beside a year range",
      len(r) == 1 and "2027980610" in "".join(ch for ch in r[0] if ch.isdigit()), r)

r = _extract_phones("2015")
check("a bare year is not a phone", r == [], r)

print("\n--- a job title is not an industry ---")
title_resume = (
    CONTACT
    + "PROFESSIONAL EXPERIENCE\n"
    + "CUTTLEFISH LABS / XMRT DAO | Remote\n"
    + "Multi-Agent Systems Architect & Founder | 2024 - Present\n"
)
r = _extract_job_fields(title_resume)
check("Systems Architect title does not mean Architecture",
      "Architecture" not in r, r)

verb_resume = (
    CONTACT
    + "PROFESSIONAL SUMMARY\n"
    + "Founder of Party Favor Photo and architect of complex technical projects.\n"
)
r = _extract_job_fields(verb_resume)
check("'architect of projects' verb is not the Architecture industry",
      "Architecture" not in r, r)

genuine = "PROFESSIONAL SUMMARY\nLicensed architectural practice, NCARB certified.\n"
r = _extract_job_fields(genuine)
check("genuine architectural practice still detected",
      "Architecture" in r, r)

genuine_title = "PROFESSIONAL EXPERIENCE\nPrincipal | Architecture Studio | 2019 - 2024\n"
r = _extract_job_fields(genuine_title)
check("architecture in the company name still detected",
      "Architecture" in r, r)

print("\n--- a real software resume still resolves its field ---")
sw = "SKILLS: Python, Kubernetes, AWS\nEXPERIENCE\nEngineer | Acme | 2020 - 2024\n"
r = _extract_job_fields(sw)
check("cloud terms detected", "Cloud Engineering" in r, r)

print("\n--- years of experience is stated or it is nothing ---")
# The dossier answered 15.0 on one run and 21.0 on the next for the same file.
# 15 is what the resume says; 21 is 2004-to-present arithmetic the model did
# itself, and publishing it as a fact is the failure this guards against.
check("stated figure read from the summary",
      _extract_stated_experience_years("15+ years of proven leadership") == 15.0)
check("plain '10 years of experience'",
      _extract_stated_experience_years("10 years of experience in sales") == 10.0)
check("a date range is not a years figure",
      _extract_stated_experience_years("2004 - 2014") is None)
check("nothing stated means None, not a calculation",
      _extract_stated_experience_years("No duration information here.") is None)
check("unqualified figures take the largest, not the first",
      _extract_stated_experience_years("3 years at Acme, 8 years at Beta") == 8.0)
check("a qualifier wins over a larger unqualified number",
      _extract_stated_experience_years(
          "12 years total. 15 years of professional leadership") == 15.0)
check("absurd values rejected",
      _extract_stated_experience_years("120 years of experience") is None)

print("\n" + (f"{len(fails)} FAILED" if fails else "all parser regression checks passed"))
sys.exit(1 if fails else 0)
