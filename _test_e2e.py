"""End-to-end over HTTP: upload -> immediate parse -> poll for dossier.

Also checks the failure modes the UI depends on: a bad request_id must 404
rather than hang, and a missing request_id must 400.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:5175"
RESUME = Path("test_resume.txt").read_text(encoding="utf-8")

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail}"))
    if not cond:
        fails.append(label)


def upload(text, name="test_resume.txt"):
    boundary = "----jobbytest%d" % int(time.time() * 1000)
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="resume"; filename="{name}"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode(),
        text.encode(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        f"{BASE}/api/resume/parse",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


print("--- upload returns fast with a dossier job ---")
t0 = time.time()
result = upload(RESUME)
elapsed = time.time() - t0
print(f"  parse took {elapsed:.2f}s")
check("parse is not blocking on the LLM", elapsed < 5.0, f"{elapsed:.2f}s")
check("source text returned", "Jordan Ellis" in (result.get("text") or ""))
check("deterministic skills now found", result.get("skills") != [], result.get("skills"))
print("  deterministic skills:", result.get("skills"))
check("dossier job advertised", bool(result.get("dossier", {}).get("request_id")), result.get("dossier"))
request_id = result["dossier"]["request_id"]

print("\n--- dossier endpoint error handling ---")
try:
    urllib.request.urlopen(f"{BASE}/api/resume/dossier?request_id=bogus", timeout=10)
    check("unknown id -> 404", False, "got 200")
except urllib.error.HTTPError as e:
    check("unknown id -> 404", e.code == 404, f"got {e.code}")

try:
    urllib.request.urlopen(f"{BASE}/api/resume/dossier", timeout=10)
    check("missing id -> 400", False, "got 200")
except urllib.error.HTTPError as e:
    check("missing id -> 400", e.code == 400, f"got {e.code}")

print("\n--- poll until the dossier is ready ---")
profile = None
saw_processing = False
t0 = time.time()
for _ in range(120):
    try:
        with urllib.request.urlopen(
            f"{BASE}/api/resume/dossier?request_id={request_id}", timeout=15
        ) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        check("poll 2xx", False, f"HTTP {e.code}")
        break
    if body.get("status") == "processing":
        saw_processing = True
    elif body.get("status") == "done":
        profile = body.get("profile")
        break
    else:
        check("dossier produced", False, f"status={body.get('status')} {body.get('error')}")
        break
    time.sleep(2)
else:
    check("dossier produced", False, "timed out after 240s")

print(f"  dossier ready in {time.time() - t0:.1f}s (saw processing: {saw_processing})")
check("polling saw the processing state", saw_processing)

if not profile:
    print("\nno dossier to inspect")
    sys.exit(1)

print("\n--- dossier contents ---")
for key in ("name", "current_title", "current_company", "email", "phone", "location",
            "experience_years", "seniority", "confidence"):
    print(f"   {key}: {profile.get(key)!r}")
print(f"   links: {profile.get('links')}")
print(f"   skills ({len(profile.get('skills') or [])}): {profile.get('skills')}")
print(f"   job_fields: {profile.get('job_fields')}")
print(f"   domain_expertise: {profile.get('domain_expertise')}")
print(f"   certifications: {profile.get('certifications')}")
print(f"   target_roles: {profile.get('target_roles')}")
print(f"   not_stated: {profile.get('not_stated')}")
print(f"   verification_flags: {profile.get('verification_flags')}")
print(f"   summary: {profile.get('summary')}")
print(f"   employment ({len(profile.get('employment') or [])}):")
for job in profile.get("employment") or []:
    print(f"      - {job.get('title')} @ {job.get('company')} | {job.get('start')} -> "
          f"{job.get('end')} | current={job.get('current')} | team={job.get('team_size')}")
    for h in job.get("highlights") or []:
        print(f"          * {h}")
print(f"   education: {profile.get('education')}")
print(f"   achievements ({len(profile.get('achievements') or [])}):")
for a in profile.get("achievements") or []:
    print(f"      - {a}")

print("\n--- assertions ---")
check("name present", profile.get("name"), profile.get("name"))
check("employment parsed", len(profile.get("employment") or []) == 3,
      len(profile.get("employment") or []))
check("employment companies correct",
      [j.get("company") for j in profile.get("employment") or []]
      == ["Acme Systems", "Beta Labs", "Gamma Systems"],
      [j.get("company") for j in profile.get("employment") or []])
check("email from deterministic floor", profile.get("email") == "john@example.com",
      profile.get("email"))
check("skills present", len(profile.get("skills") or []) >= 5, profile.get("skills"))
check("education present", len(profile.get("education") or []) >= 1, profile.get("education"))
check("confidence is a known value",
      profile.get("confidence") in ("high", "medium", "low"), profile.get("confidence"))
check("current_company present", bool(profile.get("current_company")), profile.get("current_company"))
check("experience_years present", profile.get("experience_years") is not None,
      profile.get("experience_years"))

# The timeline must agree with the resume's own dates, and must not overlap.
starts = [j.get("start") for j in profile.get("employment") or []]
check("Acme start matches the document (not 2017-03)",
      starts and starts[0] == "March 2021", starts)
check("all three starts verbatim from the document",
      starts == ["March 2021", "June 2017", "Aug 2015"], starts)
check("current role flagged", (profile.get("employment") or [{}])[0].get("current") is True,
      profile.get("employment", [{}])[0])
check("roles_in_resume populated", bool(profile.get("roles_in_resume")), profile.get("roles_in_resume"))
check("links resolved", profile.get("links", {}).get("github") is not None
      or profile.get("links", {}).get("linkedin") is not None, profile.get("links"))
check("domain_expertise or roles section present",
      bool(profile.get("domain_expertise")) or bool(profile.get("roles_in_resume")),
      (profile.get("domain_expertise"), profile.get("roles_in_resume")))

# Highlights are the substance of a resume; every job must carry some.
missing_hl = [j.get("company") for j in profile.get("employment") or []
              if not (j.get("highlights") or [])]
check("every job has highlights", not missing_hl, missing_hl)
check("achievements present", len(profile.get("achievements") or []) >= 3,
      len(profile.get("achievements") or []))
print(f"  highlights per job: {[len(j.get('highlights') or []) for j in profile.get('employment') or []]}")

# The timeline must be internally consistent: the current role must start on or
# after the role before it ended.
print("\n--- timeline consistency ---")


def year_of(value):
    import re
    m = re.search(r"(19|20)\d{2}", value or "")
    return int(m.group(0)) if m else None


emp = profile.get("employment") or []
ok = True
for earlier, later in zip(emp[1:], emp):
    ye, yl = year_of(earlier.get("end")), year_of(later.get("start"))
    if ye and yl and yl < ye:
        ok = False
        print(f"  OVERLAP: {later.get('company')} starts {later.get('start')} but "
              f"{earlier.get('company')} ended {earlier.get('end')}")
check("no overlapping roles", ok)

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("e2e async dossier flow passed")
