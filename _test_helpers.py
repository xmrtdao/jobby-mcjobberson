"""Unit tests for the dossier JSON extraction / normalisation helpers."""
import json
import sys

sys.path.insert(0, ".")
from resume_server import (  # noqa: E402
    _dossier_is_useful,
    _extract_json_object,
    _normalise_dossier,
)

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail!r}"))
    if not cond:
        fails.append(label)


print("--- _extract_json_object ---")
check("plain json", _extract_json_object('{"a": 1}') == {"a": 1})

fenced = '```json\n{"name": "A", "skills": ["x"]}\n```'
check("fenced json", (_extract_json_object(fenced) or {}).get("name") == "A")

prose = 'Here is the JSON you asked for:\n{"name": "B"}\nHope that helps!'
check("prose-wrapped", (_extract_json_object(prose) or {}).get("name") == "B")

nested = '{"outer": {"inner": {"deep": "}"}}, "top": 1}'
check("braces inside strings", (_extract_json_object(nested) or {}).get("top") == 1)

escaped = r'{"quote": "he said \"hi\" }", "name": "C"}'
check("escaped quotes", (_extract_json_object(escaped) or {}).get("name") == "C")

check("no json at all", _extract_json_object("just prose, no object") is None)
check("empty", _extract_json_object("") is None)

array_then_obj = '[1,2,3] then {"name":"D"}'
check("array before object", (_extract_json_object(array_then_obj) or {}).get("name") == "D")

print("\n--- _normalise_dossier ---")
d = _normalise_dossier(
    {
        "name": "  Jordan Ellis  ",
        "experience_years": "9 years",
        "seniority": "Senior",
        "links": {"github": "github.com/j", "linkedin": None, "other": "x"},
        "skills": ["Go", "go", "  Python  ", 42, {"description": "Kafka"}],
        "employment": [
            {"company": "Acme", "title": "Lead", "current": 1, "highlights": ["a", "a", "b"]},
            "not-a-dict",
        ],
        "education": "not-a-list",
        "confidence": "SUPER HIGH",
        "not_stated": ["phone", "location"],
    }
)
check("name trimmed", d["name"] == "Jordan Ellis")
check("numeric coerced", d["experience_years"] == 9.0)
check("bad confidence -> low", d["confidence"] == "low")
check("skills deduped+typed", d["skills"] == ["Go", "Python", "Kafka"])
check("bad list item dropped", len(d["employment"]) == 1)
check("employment highlights deduped", d["employment"][0]["highlights"] == ["a", "b"])
check("education non-list -> []", d["education"] == [])
check("links other str->list", d["links"]["other"] == ["x"])
check("links null stays null", d["links"]["linkedin"] is None)
check("not_stated preserved", d["not_stated"] == ["phone", "location"])
check("all keys present", set(d) >= {"name", "summary", "employment", "confidence", "not_stated"})

print("\n--- _dossier_is_useful ---")
check("empty rejected", _dossier_is_useful({}) is False)
check("None rejected", _dossier_is_useful(None) is False)
check("name+summary accepted", _dossier_is_useful({"name": "A", "summary": "B"}))
check("skills-only accepted", _dossier_is_useful({"skills": ["Go"]}))
check("one field rejected", _dossier_is_useful({"name": "A"}) is False)

print("\n--- empty-input resilience (no resume text) ---")
e = _normalise_dossier(_extract_json_object("I cannot help with that.") or {})
check("garbage in -> valid shape", isinstance(e, dict) and e["name"] is None)
check("garbage rejected as useless", _dossier_is_useful(e) is False)

print("\n--- schema drift tolerance (model invents its own keys) ---")
drift = _normalise_dossier({
    "document_type": "resume",
    "person": {
        "full_name": "Jordan Ellis",
        "title": "Senior Platform Engineer",
        "years_of_experience": 9,
        "location": {"city": "Richmond", "state": "VA", "country": "USA"},
        "links": {"github": "gh", "linkedin": "li", "personal_site": "site"},
        "professional_summary": "Nine years of platform work.",
    },
    "current_employer": "Acme Systems",
    "experience": [{
        "company": "Acme", "position": "Lead",
        "start_date": "2017-03", "raw_start_date": "March 2021",
        "end_date": None, "raw_end_date": "present", "is_current": True,
        "highlights": [{"description": "cut latency 42%", "category": "perf",
                        "metrics": {"x": 1}}],
    }],
    "education": [{"institution": "State U", "degree": "B.S.",
                   "field_of_study": "CS", "graduation_year": 2017}],
    "certifications": [{"name": "AWS SA Pro", "issuer": "AWS"}],
    "domain_tags": ["kubernetes", "terraform"],
    "quantified_achievements": ["cut latency 42%"],
    "extraction_confidence": "medium",
    "extraction_metadata": {
        "sections_missing": ["projects", "publications"],
        "flags": ["email local-part does not match name"],
    },
})
check("nested person.full_name -> name", drift["name"] == "Jordan Ellis")
check("person.title -> current_title", drift["current_title"] == "Senior Platform Engineer")
check("years_of_experience -> experience_years", drift["experience_years"] == 9.0)
check("dict location flattened", drift["location"] == "Richmond, VA, USA")
check("personal_site -> portfolio", drift["links"]["portfolio"] == "site")
check("top-level current_employer", drift["current_company"] == "Acme Systems")
check("experience -> employment", len(drift["employment"]) == 1)
check("position -> title", drift["employment"][0]["title"] == "Lead")
check("raw_start_date beats wrong ISO", drift["employment"][0]["start"] == "March 2021")
check("is_current -> current", drift["employment"][0]["current"] is True)
check("object highlight -> description", drift["employment"][0]["highlights"] == ["cut latency 42%"])
check("field_of_study -> field", drift["education"][0]["field"] == "CS")
check("graduation_year -> year", drift["education"][0]["year"] == "2017")
check("object cert -> name", drift["certifications"] == ["AWS SA Pro"])
check("domain_tags -> job_fields", drift["job_fields"] == ["kubernetes", "terraform"])
check("extraction_confidence -> confidence", drift["confidence"] == "medium")
check("extraction flags surfaced", any("does not match" in f for f in drift["verification_flags"]))
check("sections_missing -> not_stated", any("projects" in s for s in drift["not_stated"]))

print("\n--- deterministic floor ---")
from resume_server import _apply_deterministic_floor  # noqa: E402

ingested = {
    "emails": ["john@example.com", "jellis@acme.com"],
    "urls": ["github.com/jellis", "linkedin.com/in/jordanellis", "jellis.dev"],
    "skills": ["Python", "Go"],
    "job_fields": ["Cloud Engineering"],
}
base = _normalise_dossier({"name": "Jordan Ellis"})
floored = _apply_deterministic_floor(base, ingested)
check("email from ingest", floored["email"] == "john@example.com", floored["email"])
check("github url -> links", floored["links"]["github"] == "github.com/jellis", floored["links"])
check("linkedin url -> links", floored["links"]["linkedin"] == "linkedin.com/in/jordanellis")
check("bare url -> website", floored["links"]["website"] == "jellis.dev", floored["links"])
check("skills backfilled", floored["skills"] == ["Python", "Go"], floored["skills"])
check("job_fields backfilled", floored["job_fields"] == ["Cloud Engineering"])

# AI value must win over the deterministic floor.
kept = _apply_deterministic_floor(
    _normalise_dossier({"email": "primary@example.com", "skills": ["Rust"]}), ingested
)
check("AI email not overwritten", kept["email"] == "primary@example.com", kept["email"])
check("AI skills preserved + merged", kept["skills"] == ["Rust", "Python", "Go"], kept["skills"])

# current role read off the current job
role = _apply_deterministic_floor(
    _normalise_dossier({"employment": [
        {"company": "Acme", "title": "Lead", "current": True},
        {"company": "Beta", "title": "Engineer", "current": False},
    ]}),
    {},
)
check("current_company from current job", role["current_company"] == "Acme", role["current_company"])
check("current_title from current job", role["current_title"] == "Lead", role["current_title"])

# a first job with no explicit current flag is still the latest one
first_only = _apply_deterministic_floor(
    _normalise_dossier({"employment": [{"company": "Acme", "title": "Lead"}]}), {}
)
check("fallback to first job", first_only["current_company"] == "Acme")

# experience_years is measured from the employment dates, not taken from the
# resume's own stated figure - a stated "15 years" can be the length of one
# business the candidate owned rather than the length of their career. The
# stated figure is kept beside it, and the span carries its provenance, so the
# published number is never unattributable.
# (This replaced an assertion that experience_years must never be derived from
# dates, which encoded the opposite policy.)
no_years = _apply_deterministic_floor(
    _normalise_dossier({"employment": [
        {"company": "A", "title": "T", "current": True, "start": "August 2015"},
    ]}),
    {},
)
check("years measured from dates", no_years["experience_years"] == 11.0,
      no_years["experience_years"])
check("span carries provenance",
      no_years.get("experience_years_source") == "employment dates"
      and no_years.get("experience_years_from_dates", {}).get("years") == 11,
      (no_years.get("experience_years_source"), no_years.get("experience_years_from_dates")))
check("stated figure kept separate", no_years.get("experience_years_stated") is None,
      no_years.get("experience_years_stated"))

# empty ingest must not break anything
empty = _apply_deterministic_floor(_normalise_dossier({"name": "X"}), {})
check("empty ingest safe", empty["name"] == "X" and empty["email"] is None)
check("no ingest key safe", _apply_deterministic_floor(_normalise_dossier({"name": "X"}), None)["name"] == "X")

print("\n--- timeline reconciliation against the document ---")
# Reproduces the observed defect: the model transposed March 2021 -> 2017-03.
bad_dates = _apply_deterministic_floor(
    _normalise_dossier({"employment": [
        {"company": "Acme Systems", "title": "Lead Platform Engineer",
         "start": "2017-03", "current": True},
        {"company": "Beta Labs", "title": "Platform Engineer",
         "start": "2017-06", "end": "2021-02", "current": False},
    ]}),
    {"employment_hints": [
        {"title": "Lead Platform Engineer", "company": "Acme Systems",
         "start": "March 2021", "end": None, "current": True},
        {"title": "Platform Engineer", "company": "Beta Labs",
         "start": "June 2017", "end": "February 2021", "current": False},
    ]},
)
jobs = bad_dates["employment"]
check("transposed date corrected", jobs[0]["start"] == "March 2021", jobs[0])
check("correction is attributed", jobs[0].get("dates_from") == "resume text", jobs[0])
# The whole timeline is restated in the resume's own wording, so equivalent
# ISO dates are normalised too rather than left mixed with "March 2021".
check("iso date normalised to resume wording",
      jobs[1]["start"] == "June 2017" and jobs[1]["end"] == "February 2021", jobs[1])

# A date the model already matches the document exactly is left alone.
exact = _apply_deterministic_floor(
    _normalise_dossier({"employment": [
        {"company": "Beta Labs", "start": "June 2017", "end": "February 2021",
         "current": False},
    ]}),
    {"employment_hints": [{"title": "Platform Engineer", "company": "Beta Labs",
                           "start": "June 2017", "end": "February 2021", "current": False}]},
)
check("already-matching dates untouched",
      exact["employment"][0].get("dates_from") is None, exact["employment"][0])

# A hint the model omitted entirely still backfills.
backfill = _apply_deterministic_floor(
    _normalise_dossier({"employment": [{"company": "Initech", "title": "Engineer"}]}),
    {"employment_hints": [{"title": "Engineer", "company": "Initech",
                           "start": "March 2019", "end": "June 2022", "current": False}]},
)
check("missing dates backfilled", backfill["employment"][0]["start"] == "March 2019",
      backfill["employment"][0])
check("missing end backfilled", backfill["employment"][0]["end"] == "June 2022")
check("no hints -> AI dates kept",
      _apply_deterministic_floor(
          _normalise_dossier({"employment": [{"company": "A", "start": "2020"}]}), {}
      )["employment"][0].get("dates_from") is None)
check("malformed hints ignored",
      _apply_deterministic_floor(
          _normalise_dossier({"employment": [{"company": "A", "start": "2020"}]}),
          {"employment_hints": "nope"},
      )["employment"][0]["start"] == "2020")
check("unmatched company keeps AI dates",
      _apply_deterministic_floor(
          _normalise_dossier({"employment": [{"company": "Zeta", "start": "2020-01"}]}),
          {"employment_hints": [{"company": "Acme Systems", "start": "March 2021"}]},
      )["employment"][0]["start"] == "2020-01")

print("\n--- highlight backfill from document bullets ---")
hl = _apply_deterministic_floor(
    _normalise_dossier({"employment": [{"company": "Acme", "title": "Lead", "current": True}]}),
    {"employment_hints": [{"title": "Lead", "company": "Acme", "start": "March 2021",
                           "end": None, "current": True,
                           "highlights": ["cut p99 latency 42%", "migrated 40 services to k8s"]}]},
)
check("empty highlights backfilled", hl["employment"][0]["highlights"] == [
    "cut p99 latency 42%", "migrated 40 services to k8s"], hl["employment"][0])
check("achievements re-derived after backfill",
      hl["achievements"] == ["cut p99 latency 42%", "migrated 40 services to k8s"], hl["achievements"])

# A model that already produced highlights keeps its own.
kept_hl = _apply_deterministic_floor(
    _normalise_dossier({"employment": [
        {"company": "Acme", "highlights": ["model version"]}]}),
    {"employment_hints": [{"title": "Lead", "company": "Acme", "start": "2020",
                           "end": None, "current": True, "highlights": ["source version"]}]},
)
check("model highlights win", kept_hl["employment"][0]["highlights"] == ["model version"],
      kept_hl["employment"][0])

print("\n--- roles_in_resume (deterministic, always present) ---")
ri = _apply_deterministic_floor(
    _normalise_dossier({"current_title": "Lead Platform Engineer", "employment": [
        {"company": "Acme", "title": "Lead Platform Engineer", "current": True},
        {"company": "Beta", "title": "Platform Engineer"},
        {"company": "Gamma", "title": "Backend Engineer"},
    ]}),
    {},
)
check("roles collected from titles", ri["roles_in_resume"][:2] == ["Lead Platform Engineer", "Platform Engineer"],
      ri["roles_in_resume"])
check("current title not duplicated",
      ri["roles_in_resume"].count("Lead Platform Engineer") == 1, ri["roles_in_resume"])
check("target_roles stays empty when model said nothing",
      ri["target_roles"] == [], ri["target_roles"])
check("no employment -> roles stay empty",
      _apply_deterministic_floor(_normalise_dossier({"name": "X"}), {}).get("roles_in_resume") == [])
check("model suggestions preserved separately",
      _apply_deterministic_floor(
          _normalise_dossier({"target_roles": ["Staff SRE"], "employment": [
              {"company": "A", "title": "SRE"}]}), {}
      )["target_roles"] == ["Staff SRE"])

print("\n--- labelled-section parser ---")
from resume_server import _parse_labelled_sections  # noqa: E402

s = _parse_labelled_sections("EXPERTISE\nKubernetes\nTerraform\n- Kafka\nROLES\nPlatform Engineer\nSenior SRE")
check("expertise section", s.get("EXPERTISE") == ["Kubernetes", "Terraform", "Kafka"], s)
check("roles section", s.get("ROLES") == ["Platform Engineer", "Senior SRE"], s)

s = _parse_labelled_sections("EXPERTISE:\n1. Kubernetes\n2. Terraform\nROLES:\n1. Platform Engineer")
check("colon headers + numbering", s.get("EXPERTISE") == ["Kubernetes", "Terraform"], s)
check("numbered roles", s.get("ROLES") == ["Platform Engineer"], s)

s = _parse_labelled_sections(
    "EXPERTISE\nKubernetes\nThis is a long sentence of commentary that should be dropped.")
check("commentary dropped", s.get("EXPERTISE") == ["Kubernetes"], s)

s = _parse_labelled_sections('{"domain_expertise": ["Kubernetes"], "target_roles": ["SRE"]}')
check("json-only reply yields no sections", s == {}, s)
check("empty reply safe", _parse_labelled_sections("") == {})

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("all helper tests passed")
