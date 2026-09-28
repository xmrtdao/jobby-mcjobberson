#!/usr/bin/env python3
"""Upload a real PDF and watch the reported build stages.

The client-side progress UI was verified with a synthetic progress block, which
proves it renders but not that the server ever sends one. This exercises the
whole path against the running server: a real PDF upload, then repeated polls
printing whatever stage the build reports, ending with the dossier.

Run against the local origin so the Cloudflare redirect and TLS are not part of
what is being measured.
"""
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:5175"
PDF = os.path.join(HERE, "test_resume.pdf")

jar = http.cookiejar.CookieJar()


def opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


# --- upload ------------------------------------------------------------------
boundary = "----jobbypartytest0123456789"
with io.open(PDF, "rb") as handle:
    body_bytes = handle.read()
body = (
    ("--%s\r\n" % boundary).encode()
    + b'Content-Disposition: form-data; name="resume"; filename="test_resume.pdf"\r\n'
    + b"Content-Type: application/pdf\r\n\r\n"
    + body_bytes + b"\r\n"
    + ("--%s--\r\n" % boundary).encode()
)
request = urllib.request.Request(
    BASE + "/api/resume/parse", data=body, method="POST", headers={
        "Content-Type": "multipart/form-data; boundary=%s" % boundary,
        "User-Agent": "jobby-parity-check/1.0",
    })
try:
    with opener().open(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as error:
    print("  upload failed: HTTP %s %s" % (error.code, error.read()[:200]))
    sys.exit(1)

parsed = payload
print("=== PDF uploaded, signals parsed synchronously ===")
print("  skills     : %s" % ", ".join(parsed.get("skills") or []))
print("  phones     : %s" % ", ".join(parsed.get("phones") or []))
print("  urls       : %s" % ", ".join(parsed.get("urls") or []))
print("  job_fields : %s" % ", ".join(parsed.get("job_fields") or []))

# The request id is nested: the top level of the response is the parse result,
# and the dossier job is described under its own key.
job = payload.get("dossier") or {}
request_id = job.get("request_id")
print("  request_id : %s" % request_id)
if not request_id:
    print("  no request_id; cannot poll. keys were: %s" % sorted(payload))
    sys.exit(1)

# --- poll --------------------------------------------------------------------
print("\n=== stages the server actually reports ===")
seen = []
last = None
for attempt in range(60):
    poll = urllib.request.Request(
        BASE + "/api/resume/dossier?request_id=" + request_id,
        headers={"User-Agent": "jobby-parity-check/1.0"})
    try:
        with opener().open(poll, timeout=30) as response:
            body_json = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body_json = {"status": "http-%s" % error.code,
                     "error": error.read().decode("utf-8", "replace")[:200]}

    status = body_json.get("status")
    if status == "processing":
        progress = body_json.get("progress") or {}
        marker = "%s/%s %s" % (progress.get("index"), progress.get("total"),
                               progress.get("label"))
        if marker != last:
            print("  [%2ds] %s" % (attempt * 2, marker))
            last = marker
            seen.append(progress.get("stage"))
        time.sleep(2)
        continue

    print("  [%2ds] status=%s" % (attempt * 2, status))
    if status == "done":
        profile = body_json.get("profile") or {}
        print("     name         : %s" % profile.get("name"))
        print("     current_title: %s" % profile.get("current_title"))
        print("     years        : %s (%s)" % (
            profile.get("experience_years"), profile.get("experience_years_source")))
        print("     stages seen  : %s" % seen)
        # Only the three model passes are slow; reconcile, verify and onboard are
        # sub-second, so a 2s poller will often never observe them. What must hold
        # is that the stages which were observed arrived in order, and that at
        # least one did - a build reporting nothing would leave the bar frozen at
        # its initial state, which is the failure this is here to catch.
        order = ["identity", "history", "interpret", "reconcile", "verify", "onboard"]
        seen_order = [order.index(s) for s in seen if s in order]
        if seen_order != sorted(seen_order):
            print("\n  FAIL: stages arrived out of order: %s" % seen)
            sys.exit(1)
        if not seen:
            print("\n  FAIL: the build reported no stages, so the bar would never move")
            sys.exit(1)
        print("\n  stages arrived in order; the bar has something real to show")
    else:
        print("     error: %s" % body_json.get("error"))
        sys.exit(1)
    break
else:
    print("  timed out still processing after 120s")
    sys.exit(1)
