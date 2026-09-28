"""Employment header extraction across resume layouts.

These are copied verbatim from the document, so they are what the AI timeline
gets corrected against.
"""
import json
import sys

sys.path.insert(0, ".")
from resume_ingest import _extract_employment_headers  # noqa: E402

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail!r}"))
    if not cond:
        fails.append(label)


print("--- dash + parentheses (the layout in test_resume.txt) ---")
h = _extract_employment_headers(
    "EXPERIENCE\n"
    "Lead Platform Engineer - Acme Systems (March 2021 - present)\n"
    "Platform Engineer - Beta Labs (June 2017 - February 2021)\n"
    "Backend Engineer - Gamma Systems (Aug 2015 - May 2017)"
)
check("three jobs found", len(h) == 3, h)
check("title/company split", h[0]["title"] == "Lead Platform Engineer" and h[0]["company"] == "Acme Systems", h[0])
check("verbatim start kept", h[0]["start"] == "March 2021", h[0])
check("present -> current", h[0]["current"] is True and h[0]["end"] is None, h[0])
check("closed job dates", (h[1]["start"], h[1]["end"]) == ("June 2017", "February 2021"), h[1])
check("closed job not current", h[1]["current"] is False, h[1])
check("abbreviated month kept", h[2]["start"] == "Aug 2015", h[2])

print("\n--- comma form ---")
h = _extract_employment_headers("Senior Engineer, Initech, January 2020 - December 2023")
check("comma form found", len(h) == 1, h)
check("comma form fields", h and h[0]["title"] == "Senior Engineer" and h[0]["company"] == "Initech", h)
check("comma form dates", h and (h[0]["start"], h[0]["end"]) == ("January 2020", "December 2023"), h)

print("\n--- at / year-only / en-dash forms ---")
h = _extract_employment_headers("Data Scientist at Globex (2019 - 2022)")
check("at form", len(h) == 1 and h[0]["company"] == "Globex", h)
check("year-only dates", h and (h[0]["start"], h[0]["end"]) == ("2019", "2022"), h)

h = _extract_employment_headers("Consultant — Soylent (Jan 2022 – now)")
check("em-dash + now", len(h) == 1 and h[0]["current"] is True, h)

print("\n--- must not match non-headers ---")
check("bullet with no dates", _extract_employment_headers("- Led migration of 40 microservices to Kubernetes") == [])
check("prose line", _extract_employment_headers("I have worked at Acme Systems for many years") == [])
check("reversed range rejected", _extract_employment_headers("Engineer, Acme, 2023 - 2020") == [])
check("empty", _extract_employment_headers("") == [])

print("\n--- dedupe ---")
h = _extract_employment_headers(
    "Engineer - Acme (2020 - 2022)\nEngineer - Acme (2020 - 2022)"
)
check("duplicate header collapsed", len(h) == 1, h)

print("\n--- ordering and full text ---")
resume = (open("test_resume.txt", encoding="utf-8").read())
h = _extract_employment_headers(resume)
print("  " + json.dumps(h, indent=2))
check("test resume: 3 jobs in order",
      [x["company"] for x in h] == ["Acme Systems", "Beta Labs", "Gamma Systems"],
      [x["company"] for x in h])
check("test resume: Acme start is March 2021",
      h and h[0]["start"] == "March 2021", h[:1])

print("\n--- bullets under a header become highlights ---")
h = _extract_employment_headers(
    "Lead Platform Engineer - Acme Systems (March 2021 - present)\n"
    "- Reduced p99 latency 42%\n"
    "- Led migration of 40 microservices\n"
    "\n"
    "Platform Engineer - Beta Labs (June 2017 - February 2021)\n"
    "- Built event pipeline\n"
    "\n"
    "EDUCATION\n"
    "B.S. Computer Science"
)
check("first job highlights", h[0]["highlights"] == [
    "Reduced p99 latency 42%", "Led migration of 40 microservices"], h[0])
check("bullets stop at blank line", len(h[0]["highlights"]) == 2, h[0])
check("second job highlights", h[1]["highlights"] == ["Built event pipeline"], h[1])
check("highlights do not bleed into the next section", len(h) == 2, h)

h = _extract_employment_headers("Engineer - Acme (2020 - 2022)\n\u2022 first\n\u2022 second\nEDUCATION\nX")
check("bullet char accepted", h[0]["highlights"] == ["first", "second"], h)

h = _extract_employment_headers("Engineer - Acme (2020 - 2022)\nNot a bullet line")
check("non-bullet not taken", h[0]["highlights"] == [], h)

h = _extract_employment_headers(
    "Engineer - Acme (2020 - 2022)\n" + "".join(f"- bullet {i}\n" for i in range(20))
)
check("highlight cap enforced", len(h[0]["highlights"]) == 10, len(h[0]["highlights"]))

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("all employment-header tests passed")
