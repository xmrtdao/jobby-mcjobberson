#!/usr/bin/env python3
"""Check the experience-years policy and the self-contradiction flag.

The policy was reversed on the user's instruction. These assertions used to
require the figure the resume states, because publishing a number the candidate
never wrote was the failure being guarded against: the dossier answered 15.0 on
one run and 21.0 on the next for the same file, 21 being date arithmetic the
model did itself.

It turned out the stated 15 was not a career length at all. It was how long the
candidate had owned his company. He began work in 1997 at seventeen, so the
honest figure was twenty-nine and fifteen would have been read as a mid-career
applicant. So the span is published now, and these tests assert that the stated
number is preserved beside it rather than discarded, which is the part that
matters for honesty: a derived figure must never be mistakable for a written
one.
"""
import sys

sys.path.insert(0, ".")
from resume_server import _pin_experience_years  # noqa: E402

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail}"))
    if not cond:
        fails.append(label)


def dossier(jobs):
    return {"employment": jobs, "verification_flags": [], "not_stated": []}


# The real case: states 15+ years, dates run 2004 to present.
real = dossier([
    {"company": "Party Favor Photo", "start": "2025", "end": None, "current": True},
    {"company": "USO", "start": "2015", "end": "2021", "current": False},
    {"company": "Marine Corps", "start": "2004", "end": "2014", "current": False},
])
_pin_experience_years(real, {"stated_experience_years": 15.0})

print("--- the stated figure is not what gets published ---")
check("publishes the date span, not 15",
      real["experience_years"] == 22.0, real["experience_years"])
check("keeps the stated figure on record",
      real["experience_years_stated"] == 15.0, real.get("experience_years_stated"))
check("records the span it used",
      real["experience_years_from_dates"] == {"from": 2004, "to": 2026, "years": 22},
      real.get("experience_years_from_dates"))
check("says where the number came from",
      real["experience_years_source"] == "employment dates", real.get("experience_years_source"))
check("the candidate is told the number changed",
      len(real["verification_flags"]) == 1, real["verification_flags"])
if real["verification_flags"]:
    print("      " + real["verification_flags"][0])

print("\n--- a 29-year career is published as 29, not 15 ---")
# 1997 to present, which is the real figure for this candidate.
long_career = dossier([
    {"company": "LVS Operator, 1st SRI Group", "start": "1997", "end": "2004"},
    {"company": "Marine Corps", "start": "2004", "end": "2014"},
    {"company": "Party Favor Photo", "start": "2025", "end": None, "current": True},
])
_pin_experience_years(long_career, {"stated_experience_years": 15.0})
check("29 years", long_career["experience_years"] == 29.0, long_career["experience_years"])
check("stated 15 still on record", long_career["experience_years_stated"] == 15.0)
check("flag raised", len(long_career["verification_flags"]) == 1)

print("\n--- stated figure agrees with the dates: no flag ---")
agree = dossier([
    {"company": "A", "start": "2006", "end": None, "current": True},
    {"company": "B", "start": "2004", "end": "2006", "current": False},
])
_pin_experience_years(agree, {"stated_experience_years": 21.0})
check("no flag when consistent", agree["verification_flags"] == [], agree["verification_flags"])
check("still publishes the span", agree["experience_years"] == 22.0, agree["experience_years"])

print("\n--- a gap of exactly the tolerance is still raised ---")
edge = dossier([
    {"company": "A", "start": "2006", "end": None, "current": True},
    {"company": "B", "start": "2004", "end": "2006", "current": False},
])
_pin_experience_years(edge, {"stated_experience_years": 20.0})
check("two-year gap flagged", len(edge["verification_flags"]) == 1, edge["verification_flags"])

print("\n--- no dates: fall back to the stated figure, clearly labelled ---")
nodates = dossier([{"company": "A", "start": None, "end": None}])
_pin_experience_years(nodates, {"stated_experience_years": 12.0})
check("uses the stated figure", nodates["experience_years"] == 12.0, nodates["experience_years"])
check("labelled as stated", nodates["experience_years_source"] == "stated on the resume",
      nodates.get("experience_years_source"))
check("no span invented", "experience_years_from_dates" not in nodates)
check("no flag without dates to compare", nodates["verification_flags"] == [],
      nodates["verification_flags"])

print("\n--- neither dates nor a stated figure: null plus a recorded gap ---")
neither = dossier([{"company": "A", "start": None, "end": None}])
_pin_experience_years(neither, {})
check("years is null", neither["experience_years"] is None, neither["experience_years"])
check("gap recorded", len(neither["not_stated"]) == 1, neither["not_stated"])
check("no calculation published", "experience_years_from_dates" not in neither)

print("\n--- an overstatement is caught too, not just an understatement ---")
over = dossier([{"company": "A", "start": "1998", "end": None, "current": True}])
_pin_experience_years(over, {"stated_experience_years": 3.0})
check("overstatement flagged", len(over["verification_flags"]) == 1, over["verification_flags"])
check("the dates win", over["experience_years"] == 28.0, over["experience_years"])

print("\n" + (f"{len(fails)} FAILED" if fails else "all experience-years checks passed"))
sys.exit(1 if fails else 0)
