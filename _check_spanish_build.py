#!/usr/bin/env python3
"""Upload a real PDF in Spanish mode and check the dossier comes back Spanish.

The claim being tested is the one the toggle makes: switching to Spanish means an
English resume produces a Spanish dossier.

What is asserted, and what deliberately is not:

  * The prose the model writes must be Spanish. That is the whole feature.
  * The machine keys must stay English - experience_years, confidence,
    roles_in_resume. The relay, the renderer and the page agent all read them;
    translating them would mean a migration and would orphan every dossier on
    file. They are translated at the point of display instead, on the client.
  * The parse signals are not asserted to be Spanish. The resume is English, so
    claiming its skills had been translated would be a lie about what was read.
  * The stage labels come back English from the server by design. They are
    translated on the client, keyed by the stage name, so what is checked here is
    that the client has a Spanish label for every stage the server can report -
    not that the server speaks Spanish, which it is not asked to.
"""
import http.cookiejar
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:5175"
PDF = os.path.join(HERE, "test_resume.pdf")

fails = []


def check(label, condition, detail=""):
    print(("  PASS  " if condition else "  FAIL  ") + label
          + ("" if condition else "   %s" % (detail,)))
    if not condition:
        fails.append(label)


if not os.path.exists(PDF):
    subprocess.run([sys.executable, os.path.join(HERE, "_make_pdf_fixture.py")],
                   check=True, capture_output=True)

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

# --- upload, asking for Spanish ---------------------------------------------
boundary = b"----spanishtest"
with io.open(PDF, "rb") as handle:
    payload = handle.read()
body = b"".join([
    b"--" + boundary + b"\r\n",
    b'Content-Disposition: form-data; name="resume"; filename="test_resume.pdf"\r\n',
    b"Content-Type: application/pdf\r\n\r\n",
    payload, b"\r\n",
    b"--" + boundary + b"\r\n",
    b'Content-Disposition: form-data; name="lang"\r\n\r\n',
    b"es\r\n",
    b"--" + boundary + b"--\r\n",
])

request = urllib.request.Request(BASE + "/api/resume/parse", data=body, method="POST", headers={
    "Content-Type": "multipart/form-data; boundary=" + boundary.decode(),
    "User-Agent": "jobby-spanish-check/1.0",
})
try:
    with opener.open(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as error:
    print("  upload failed: HTTP %s %s" % (error.code, error.read()[:200]))
    sys.exit(1)

request_id = (result.get("dossier") or {}).get("request_id")
print("=== uploaded an English PDF with lang=es ===")
print("  request_id : %s" % request_id)
print("  signals    : skills=%d phones=%d urls=%d"
      % (len(result.get("skills") or []), len(result.get("phones") or []),
         len(result.get("urls") or [])))
if not request_id:
    sys.exit("  no request_id")

# --- poll -------------------------------------------------------------------
stages = []
last = None
for attempt in range(75):
    poll = urllib.request.Request(
        BASE + "/api/resume/dossier?request_id=" + request_id,
        headers={"User-Agent": "jobby-spanish-check/1.0"})
    try:
        with opener.open(poll, timeout=30) as response:
            body_json = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body_json = {"status": "http-%s" % error.code,
                     "error": error.read().decode("utf-8", "replace")[:200]}

    if body_json.get("status") == "processing":
        progress = body_json.get("progress") or {}
        key = progress.get("stage")
        if key and key != last:
            stages.append(key)
            print("  [%2ds] stage=%s" % (attempt * 2, key))
            last = key
        time.sleep(2)
        continue
    if body_json.get("status") != "done":
        print("  build failed: %s" % body_json.get("error"))
        sys.exit(1)
    profile = body_json.get("profile") or {}
    break
else:
    print("  timed out")
    sys.exit(1)

# --- the prose the model wrote ---------------------------------------------
print("\n=== the dossier the model wrote ===")
summary = profile.get("summary") or ""
for key in ("summary", "current_title", "current_company"):
    value = profile.get(key)
    print("  %-16s %s" % (key, (value or "-")[:100].encode("ascii", "replace").decode("ascii")))

# A word an English summary would not contain.
SPANISH_MARKERS = ("-profesional", "años", "experiencia", "sistemas", "especialidad")
check("the summary is Spanish, from an English resume",
      any(m in summary.lower() for m in SPANISH_MARKERS),
      summary[:90].encode("ascii", "replace").decode("ascii"))

print("\n=== the machine keys stayed English ===")
check("confidence is a machine key", profile.get("confidence") in ("low", "medium", "high"),
      profile.get("confidence"))
check("experience_years is a number", isinstance(profile.get("experience_years"), (int, float)),
      profile.get("experience_years"))
check("roles_in_resume is a list of strings",
      isinstance(profile.get("roles_in_resume"), list)
      and all(isinstance(r, str) for r in profile.get("roles_in_resume")),
      profile.get("roles_in_resume"))
# Proper nouns stay as the document states them, which the prompt asks for.
check("the employer name was kept verbatim",
      profile.get("current_company") in ("Acme Systems", None), profile.get("current_company"))

print("\n=== every reported stage has a Spanish label on the client ===")
app = io.open("docs/app.js", encoding="utf-8").read()
block = re.search(r"const JOBBY_STAGE_LABELS = \{(.*?)\n\};", app, re.S)
mapped = set(re.findall(r"(\w+):\s*\{\s*es:", block.group(1))) if block else set()
server = io.open("resume_server.py", encoding="utf-8").read()
# Scoped to _DOSSIER_STAGES. A looser pattern over the whole file also matches
# HTTP header tuples and environment lookups, which is how this first reported
# nine stages that do not exist.
stage_table = re.search(
    r"_DOSSIER_STAGES: tuple\[tuple\[str, str\], \.\.\.\] = \((.*?)\n\)", server, re.S)
declared = set(re.findall(r'\("(\w+)",\s*"', stage_table.group(1))) if stage_table else set()
print("  the server declares : %s" % sorted(declared))
print("  the client translates: %s" % sorted(mapped))
check("every stage the server can report has a Spanish label",
      declared and declared.issubset(mapped), sorted(declared - mapped))
check("the client label is preferred over the server's English one",
      "stageLabel(progress)" in app and "textContent = label" in app)

print()
if fails:
    print("%d FAILED: %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("an English resume in Spanish mode produces a Spanish dossier")
