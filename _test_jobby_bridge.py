"""End-to-end check of the Jobby bridge, portal -> relay -> database.

Runs against the live services on 127.0.0.1:5175 (portal) and 8080 (relay).
Uses a cookie jar so the session behaves like a real browser's.
"""
import http.client
import json
import sys
import time

PORTAL = ("127.0.0.1", 5175)
RELAY = ("127.0.0.1", 8080)

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail!r}"))
    if not cond:
        fails.append(label)


COOKIE_JAR = {}


def request(hostport, method, path, body=None, use_cookie=True):
    conn = http.client.HTTPConnection(*hostport, timeout=200)
    headers = {"Content-Type": "application/json"}
    if use_cookie and COOKIE_JAR.get(hostport[1]):
        headers["Cookie"] = COOKIE_JAR[hostport[1]]
    payload = json.dumps(body) if body is not None else None
    conn.request(method, path, body=payload, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    set_cookie = resp.headers.get("Set-Cookie")
    if set_cookie:
        COOKIE_JAR[hostport[1]] = set_cookie.split(";")[0]
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except ValueError:
        return resp.status, raw.decode("utf-8", "replace")


DOSSIER = {
    "name": "Dana Whitfield",
    "current_title": "Independent Consultant",
    "current_company": None,
    "email": "dana@example.com",
    "phone": "(415) 555-0188",
    "location": "San Francisco, CA",
    "summary": "Independent consultant advising fintech companies on risk and compliance. Founder of Whitfield Advisory LLC, nine years in the domain.",
    "experience_years": 9,
    "skills": ["Risk", "Compliance", "AML", "Python", "SQL"],
    "job_fields": ["Architecture"],
    "employment": [
        {"company": "Whitfield Advisory LLC", "title": "Founder & Principal Consultant",
         "start": "March 2021", "end": None, "current": True, "highlights": ["Built a nine-client advisory practice"]},
        {"company": "Bankcorp", "title": "Head of Risk", "start": "June 2017", "end": "February 2021",
         "current": False, "highlights": ["Cut SAR filings backlog 60%"]},
    ],
    "education": [{"institution": "State University", "degree": "B.S.", "field": "Economics", "year": "2013"}],
    "certifications": ["CAMS"],
    "not_stated": ["seniority"],
    "verification_flags": [],
    "confidence": "high",
}

print("=== session is created and a cookie is set ===")
status, session = request(PORTAL, "GET", "/api/jobby/session")
check("portal proxies the session", status == 200, (status, session))
check("relay cookie reached the browser", bool(COOKIE_JAR.get(5175)), COOKIE_JAR)
if status == 200:
    check("client id issued", isinstance(session.get("client", {}).get("id"), int), session)
    check("no dossier yet", session.get("hasDossier") is False, session)
    check("all four tracks described", len(session.get("tracks", [])) == 4, session.get("tracks"))
    check("kill switch reported", session["client"].get("killSwitch") is False, session["client"])
    check("sending gate exposed", "sending" in session, list(session))

print("\n=== a parsed resume onboards immediately ===")
status, onboard = request(PORTAL, "POST", "/api/jobby/onboard",
                          {"dossier": DOSSIER, "sourceFilename": "dana.txt"})
check("onboard accepted", status == 200, (status, onboard))
if status == 200:
    check("success", onboard.get("success") is True, onboard)
    check("revision 1", onboard.get("revision") == 1, onboard)
    check("consultant gets all four tracks", onboard.get("tracks") == [1, 2, 3, 4], onboard.get("tracks"))
    check("sells services detected", onboard.get("sellsServices") is True, onboard)
    check("plan built", onboard.get("actions", 0) > 5, onboard.get("actions"))
    check("track reasons given", len(onboard.get("trackReasons", {})) >= 4, onboard.get("trackReasons"))
    check("summary returned", isinstance(onboard.get("summary"), str) and len(onboard["summary"]) > 40)

print("\n=== the session now reflects the dossier and the plan ===")
status, session = request(PORTAL, "GET", "/api/jobby/session")
check("dossier present", session.get("hasDossier") is True, session)
check("tracks persisted on the client", session["client"]["tracks"] == [1, 2, 3, 4], session["client"]["tracks"])
check("plan actions returned", len(session.get("actions", [])) > 5, len(session.get("actions", [])))
check("consulting action present", any("consulting" in a["title"].lower() for a in session["actions"]), [a["title"] for a in session["actions"]])
check("track-1 actions tagged", any(a["track"] == 1 for a in session["actions"]), session["actions"][:3])

print("\n=== the dossier and its audit trail are readable ===")
status, dossier = request(PORTAL, "GET", "/api/jobby/dossier")
check("dossier returned", status == 200, (status, dossier))
check("dossier content", dossier.get("dossier", {}).get("name") == "Dana Whitfield", dossier.get("dossier", {}).get("name"))
check("revision reported", dossier.get("revision") == 1, dossier.get("revision"))
check("provenance", dossier.get("updatedBy") == "resume-parse", dossier.get("updatedBy"))
check("filename", dossier.get("sourceFilename") == "dana.txt", dossier.get("sourceFilename"))
check("parse is audited", len(dossier.get("edits", [])) == 1, dossier.get("edits"))
check("audit names the actor", dossier["edits"][0]["actor"] == "resume-parse", dossier["edits"][0])

print("\n=== chat works through the proxy ===")
status, chat = request(PORTAL, "POST", "/api/jobby/chat",
                       {"message": "What tracks am I running and why?"})
check("chat answered", status == 200, (status, str(chat)[:300]))
if status == 200 and isinstance(chat, dict) and "reply" in chat:
    check("reply is prose", isinstance(chat["reply"], str) and len(chat["reply"]) > 20, chat["reply"][:200])
    check("no raw tool line leaked", "TOOL_CALL:" not in chat["reply"], chat["reply"][:300])
    check("client state returned", chat.get("client", {}).get("tracks") == [1, 2, 3, 4], chat.get("client"))
    print("  --- Jobby said ---")
    for line in chat["reply"].splitlines()[:12]:
        print("  " + line[:150])
    print("  ---")

print("\n=== chat history is stored ===")
status, history = request(PORTAL, "GET", "/api/jobby/history")
check("history returned", status == 200, status)
msgs = history.get("messages", []) if isinstance(history, dict) else []
check("user turn stored", any(m["role"] == "user" for m in msgs), [m["role"] for m in msgs])
check("jobby turn stored", any(m["role"] == "jobby" for m in msgs), [m["role"] for m in msgs])

print("\n=== the kill switch is honoured through the proxy ===")
status, patched = request(PORTAL, "PATCH", "/api/jobby/client", {"kill_switch": True})
check("kill switch set", status == 200 and patched.get("client", {}).get("kill_switch") is True, (status, patched))
status, session = request(PORTAL, "GET", "/api/jobby/session")
check("session reflects it", session["client"]["killSwitch"] is True, session["client"])
check("sending gate blocks", session["sending"]["allowed"] is False, session["sending"])
check("block reason is the switch", session["sending"].get("code") == "kill_switch", session["sending"])
request(PORTAL, "PATCH", "/api/jobby/client", {"kill_switch": False})

print("\n=== validation is enforced server-side ===")
status, bad = request(PORTAL, "PATCH", "/api/jobby/client", {"daily_send_cap": 99999})
check("absurd cap refused", status == 400, (status, bad))
status, bad = request(PORTAL, "PATCH", "/api/jobby/client", {"autonomy": "yolo"})
check("bad autonomy refused", status == 400, (status, bad))
status, bad = request(PORTAL, "POST", "/api/jobby/chat", {"message": ""})
check("empty message refused", status == 400, (status, bad))
status, bad = request(PORTAL, "POST", "/api/jobby/chat", {"message": 12345})
check("non-string message refused", status == 400, (status, bad))
status, bad = request(PORTAL, "POST", "/api/jobby/onboard", {"dossier": "not an object"})
check("non-object dossier refused", status == 400, (status, bad))

print("\n=== no session cookie means no dossier access ===")
COOKIE_JAR.pop(5175, None)
COOKIE_JAR.pop(8080, None)
status, denied = request(PORTAL, "GET", "/api/jobby/dossier")
check("dossier without a session is refused", status in (401, 502), (status, denied))
status, denied = request(PORTAL, "GET", "/api/jobby/history")
check("history without a session is refused", status in (401, 502), (status, denied))

print("\n=== isolation: a second browser gets its own empty client ===")
status, other = request(RELAY, "GET", "/api/jobby/session", use_cookie=False)
check("second session minted", status == 200, (status, other))
check("second client has no dossier", other.get("hasDossier") is False, other)
if status == 200 and isinstance(other, dict):
    check("different client id", other["client"]["id"] != session["client"]["id"], other["client"]["id"])
    status, other_dossier = request(RELAY, "GET", "/api/jobby/dossier")
    check("second client sees an empty dossier", other_dossier.get("dossier") is None, other_dossier)

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("all jobby bridge tests passed")
