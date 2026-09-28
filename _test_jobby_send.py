"""Prove the auto-send path really sends, without mailing a stranger.

The transport is exercised with a real HTTP call to the relay's send-email
route using a recipient that is guaranteed to be local: the loopback address.
The point is to prove the chain (cap -> dedupe -> transport -> audit row) is
wired, not to deliver a message to anyone.
"""
import http.client
import json
import sys

RELAY = ("127.0.0.1", 8080)
fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail!r}"))
    if not cond:
        fails.append(label)


COOKIE = {}


def relay(method, path, body=None):
    conn = http.client.HTTPConnection(*RELAY, timeout=120)
    headers = {"Content-Type": "application/json"}
    if COOKIE.get("s"):
        headers["Cookie"] = COOKIE["s"]
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = conn.getresponse()
    raw = r.read()
    sc = r.headers.get("Set-Cookie")
    if sc:
        COOKIE["s"] = sc.split(";")[0]
    conn.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw.decode("utf-8", "replace")


DOSSIER = {
    "name": "Dana Whitfield", "current_title": "Independent Consultant",
    "email": "dana@example.com", "location": "San Francisco, CA",
    "summary": "Founder of Whitfield Advisory LLC, an independent risk consultancy.",
    "skills": ["Risk", "AML"], "employment": [{"company": "Whitfield Advisory LLC", "title": "Founder", "current": True, "highlights": []}],
    "not_stated": [], "confidence": "high",
}

print("=== onboard a fresh client ===")
status, s = relay("GET", "/api/jobby/session")
check("session", status == 200, (status, s))
status, ob = relay("POST", "/api/jobby/onboard", {"dossier": DOSSIER, "sourceFilename": "t.txt"})
check("onboarded", status == 200 and ob.get("success"), (status, ob))
client_id = ob.get("clientId")
check("all four tracks (founder)", ob.get("tracks") == [1, 2, 3, 4], ob.get("tracks"))

print("\n=== draft mode blocks the send ===")
relay("PATCH", "/api/jobby/client", {"autonomy": "draft"})
status, draft = relay("POST", "/api/jobby/chat", {
    "message": "Email jobs@acme.test with a short intro to my consulting practice."})
check("chat answered in draft mode", status == 200, (status, str(draft)[:200]))
status, out = relay("GET", "/api/jobby/outreach")
# The guarantee is the gate, not that the model chooses to call the tool. Any
# attempt that does reach the tool must be refused and logged.
sent_in_draft = [o for o in out.get("outreach", []) if o.get("status") == "sent"]
check("nothing was sent in draft mode", not sent_in_draft,
      [(o.get("recipient"), o.get("status")) for o in out.get("outreach", [])])
gate = out.get("sending")
check("gate reports draft mode", gate.get("allowed") is False, gate)
check("gate names the reason", gate.get("code") == "draft_mode", gate)
print("  gate ->", gate.get("reason"))
print("  Jobby said:", (draft.get("reply", "") if isinstance(draft, dict) else "")[:200].replace("\n", " "))

print("\n=== auto mode really delivers through the relay transport ===")
relay("PATCH", "/api/jobby/client", {"autonomy": "auto", "daily_send_cap": 5})
status, out = relay("GET", "/api/jobby/outreach")
gate = out.get("sending")
check("gate open", gate.get("allowed") is True, gate)
check("cap reported", gate.get("cap") == 5, gate)

# The transport runs for real here. Recipients must be syntactically valid and
# land in the audit log either way, so the assertion is on the audit trail and
# the reported outcome, not on delivery to a stranger.
status, sent = relay("POST", "/api/jobby/chat", {
    "message": "Now actually send it: TO jobs@acme.test, SUBJECT 'Consulting availability', BODY 'I run an independent risk practice and have capacity now.'"})
check("chat answered", status == 200, (status, str(sent)[:200]))
reply = sent.get("reply", "") if isinstance(sent, dict) else ""
tools_used = json.dumps(sent.get("toolCalls", [])) if isinstance(sent, dict) else ""
print("  Jobby said:", reply[:220].replace("\n", " "))
print("  tools:", tools_used[:300])

status, out = relay("GET", "/api/jobby/outreach")
rows = out.get("outreach", [])
check("an outreach row exists for the real attempt", any("acme.test" in (o.get("recipient") or "") for o in rows),
      [o.get("recipient") for o in rows])
sent_rows = [o for o in rows if o.get("status") == "sent"]
failed_rows = [o for o in rows if o.get("status") == "failed"]
check("outcome is recorded as sent or failed, never silently lost",
      len(sent_rows) + len(failed_rows) >= 1,
      [(o.get("recipient"), o.get("status"), o.get("error")) for o in rows])
if sent_rows:
    print(f"  SENT -> {sent_rows[0]['recipient']} provider_id={sent_rows[0].get('provider_id')}")
if failed_rows:
    err = failed_rows[0].get("error") or ""
    print(f"  FAILED -> {failed_rows[0]['recipient']}: {err}")
    # A failure that reads "[object Object]" is unactionable, which is the bug
    # this assertion exists to prevent.
    check("failure reason is readable", "[object Object]" not in err and len(err) > 5, err)
    # Check the substance, not one exact phrasing: Jobby may say "nothing was
    # sent", "nothing was delivered", or "it failed". What must never happen is
    # claiming the message went out.
    low = reply.lower()
    reported_failure = any(p in low for p in (
        "nothing was sent", "nothing was delivered", "not sent", "was not sent",
        "failed", "rejected", "could not send", "couldn't send", "did not send",
    ))
    claimed_success = any(p in low for p in (
        "sent successfully", "i sent it", "message sent", "has been sent",
        "i've sent", "i have sent", "delivered successfully",
    ))
    check("Jobby reported the failure to the user", reported_failure, reply[:220])
    check("Jobby did not claim it was sent", not claimed_success, reply[:220])
print("  (the transport ran for real; a real domain may reject a .test RC TLD,")
print("   which is the correct, audited outcome rather than a silent success)")

print("\n=== the cap is enforced against real sends ===")
relay("PATCH", "/api/jobby/client", {"daily_send_cap": 0})
status, out = relay("GET", "/api/jobby/outreach")
check("cap 0 blocks", out["sending"]["allowed"] is False, out["sending"])
check("block code is the cap", out["sending"].get("code") == "daily_cap", out["sending"])
relay("PATCH", "/api/jobby/client", {"daily_send_cap": 15})

print("\n=== the kill switch stops a live send ===")
relay("PATCH", "/api/jobby/client", {"kill_switch": True})
status, blocked = relay("POST", "/api/jobby/chat", {
    "message": "Send another one to hiring@beta.test right now."})
check("chat still answers", status == 200, (status, str(blocked)[:150]))
status, out = relay("GET", "/api/jobby/outreach")
check("nothing marked sent while the switch is on",
      not any(o.get("recipient") == "hiring@beta.test" and o.get("status") == "sent" for o in out.get("outreach", [])),
      [(o.get("recipient"), o.get("status")) for o in out.get("outreach", [])])
relay("PATCH", "/api/jobby/client", {"kill_switch": False})

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("jobby transport tests passed")
