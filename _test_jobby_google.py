"""Live checks for the Google OAuth surface, without a real Google account.

Verifies the contract the portal depends on: the status endpoint reports what
is missing, unconfigured endpoints refuse cleanly rather than 500, no token
material is ever returned, and Drive/Gmail calls report "not connected" instead
of pretending to work.
"""
import http.client
import json
import sys

RELAY = ("127.0.0.1", 8080)
PORTAL = ("127.0.0.1", 5175)

fails = []


def check(label, cond, detail=""):
    if cond:
        print("  PASS  " + label)
        return
    fails.append(label)
    # A whole HTML page in a failure message is unreadable; show the shape.
    text = repr(detail)
    if len(text) > 300:
        text = text[:300] + f"... ({len(text)} chars)"
    print("  FAIL  " + label + "  -> " + text)


COOKIE = {}


def call(hostport, method, path, body=None, use_cookie=True, allow_redirect=False):
    conn = http.client.HTTPConnection(*hostport, timeout=120)
    headers = {"Content-Type": "application/json"}
    if use_cookie and COOKIE.get(hostport[1]):
        headers["Cookie"] = COOKIE[hostport[1]]
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = conn.getresponse()
    raw = r.read()
    sc = r.headers.get("Set-Cookie")
    if sc:
        COOKIE[hostport[1]] = sc.split(";")[0]
    loc = r.headers.get("Location")
    conn.close()
    if allow_redirect and r.status in (301, 302, 303, 307, 308):
        return r.status, {"_redirect": loc}
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw.decode("utf-8", "replace")


print("=== status endpoint is reachable and honest ===")
status, s = call(RELAY, "GET", "/api/jobby/session")
check("session created", status == 200, (status, s))
status, st = call(RELAY, "GET", "/api/jobby/google/status")
check("status 200", status == 200, (status, st))
check("reports whether configured", "configured" in st, st)
check("lists requested scopes", len(st.get("requestedScopes", [])) == 4, st.get("requestedScopes"))
check("flags restricted scopes", len(st.get("restrictedScopes", [])) == 2, st.get("restrictedScopes"))
check("restricted list is gmail.readonly + drive",
      any("gmail.readonly" in x for x in st["restrictedScopes"]) and
      any(x.endswith("/drive") for x in st["restrictedScopes"]), st.get("restrictedScopes"))
check("reports encryption availability", "available" in st.get("encryption", {}), st.get("encryption"))
check("token encryption is ready", st.get("encryption", {}).get("available") is True, st.get("encryption"))
check("connection object present", "connection" in st, list(st))
check("redirect uri is the portal callback",
      st.get("redirectUri", "").endswith("/api/jobby/google/callback"), st.get("redirectUri"))

print("\n=== no token material anywhere in the status payload ===")
blob = json.dumps(st)
for needle in ["ya29.", "1//refresh", "access_token", "refresh_token", "accessTokenEnc", "refreshTokenEnc", "BEGIN "]:
    check(f"status does not contain {needle!r}", needle not in blob, blob[:200])

print("\n=== with no client id set, endpoints refuse cleanly ===")
configured = st.get("configured")
if configured:
    print("  (Google IS configured — exercising the real path instead)")
    status, u = call(RELAY, "GET", "/api/jobby/google/auth-url")
    check("auth-url 200 when configured", status == 200, (status, u))
    check("returns a google url", "accounts.google.com" in u.get("url", ""), u)
    check("url requests offline access", "access_type=offline" in u["url"], u["url"][:200])
    check("url forces consent (needed for a refresh token)", "prompt=consent" in u["url"], u["url"][:200])
    check("url carries a state", "state=" in u["url"], u["url"][:200])
    check("url carries the redirect uri", "redirect_uri=" in u["url"], u["url"][:200])
    check("url includes all four scopes", u["url"].count("gmail") >= 2 and "drive" in u["url"], u["url"][:300])
else:
    check("names the missing vars", len(st.get("missing", [])) == 2, st.get("missing"))
    for path in ["/api/jobby/google/auth-url"]:
        status, body = call(RELAY, "GET", path)
        check(f"{path} refuses with 503", status == 503, (status, body))
        check(f"{path} says google_not_configured", body.get("error") == "google_not_configured", body)
    status, body = call(RELAY, "GET", "/api/jobby/google/drive/files")
    check("drive/files refuses with 503", status == 503, (status, body))
    status, body = call(RELAY, "GET", "/api/jobby/google/gmail/messages")
    check("gmail/messages refuses with 503", status == 503, (status, body))
    status, body = call(RELAY, "POST", "/api/jobby/google/drive/file", {"name": "x", "content": "y"})
    check("drive/file refuses with 503", status == 503, (status, body))

print("\n=== the callback never leaks a token and always redirects ===")
for qs in ["", "?error=access_denied", "?code=abc&state=nope", "?code=abc", "?state=abc"]:
    status, body = call(RELAY, "GET", "/api/jobby/google/callback" + qs, allow_redirect=True)
    check(f"callback{qs or ' (bare)'} redirects", status in (301, 302, 303, 307, 308), (status, body))
    check(f"callback{qs or ' (bare)'} goes to the portal",
          "jobby.mobilemonero.com" in str(body.get("_redirect", "")), body)
    check(f"callback{qs or ' (bare)'} reports a result flag",
          "google=" in str(body.get("_redirect", "")), body)
    check(f"callback{qs or ' (bare)'} body has no token", "ya29." not in json.dumps(body), body)

print("\n=== a replayed or unknown state is refused ===")
if configured:
    status, u = call(RELAY, "GET", "/api/jobby/google/auth-url")
    state = u["url"].split("state=")[1].split("&")[0]
    status, body = call(RELAY, "GET", f"/api/jobby/google/callback?code=fake&state={state}", allow_redirect=True)
    check("first use consumes the state", "reason=token_exchange_failed" in str(body.get("_redirect", "")), body)
    status, body = call(RELAY, "GET", f"/api/jobby/google/callback?code=fake&state={state}", allow_redirect=True)
    check("replay is refused as invalid state", "reason=invalid_or_expired_state" in str(body.get("_redirect", "")), body)
    status, body = call(RELAY, "GET", "/api/jobby/google/callback?code=fake&state=totally-made-up", allow_redirect=True)
    check("unknown state refused", "invalid_or_expired_state" in str(body.get("_redirect", "")), body)
else:
    status, body = call(RELAY, "GET", "/api/jobby/google/callback?code=fake&state=totally-made-up", allow_redirect=True)
    check("unknown state refused", "invalid_or_expired_state" in str(body.get("_redirect", "")), body)

print("\n=== input validation on the write endpoints ===")
if configured:
    status, body = call(RELAY, "POST", "/api/jobby/google/drive/file", {"name": "only-name"})
    check("missing content is a 400", status == 400, (status, body))
    status, body = call(RELAY, "POST", "/api/jobby/google/drive/file", {"content": "only-content"})
    check("missing name is a 400", status == 400, (status, body))
    status, body = call(RELAY, "POST", "/api/jobby/google/drive/trash", {})
    check("missing fileId is a 400", status == 400, (status, body))
    status, body = call(RELAY, "GET", "/api/jobby/google/drive/file")
    check("missing file_id is a 400", status == 400, (status, body))
    status, body = call(RELAY, "GET", "/api/jobby/google/gmail/message")
    check("missing message_id is a 400", status == 400, (status, body))

    # Nothing connected yet, so these must say so rather than fail opaquely.
    status, body = call(RELAY, "GET", "/api/jobby/google/drive/files")
    check("drive/files says not connected", status == 409 and body.get("code") == "GOOGLE_NOT_CONNECTED", (status, body))
    status, body = call(RELAY, "GET", "/api/jobby/google/gmail/messages")
    check("gmail says not connected", status == 409 and body.get("code") == "GOOGLE_NOT_CONNECTED", (status, body))

    print("\n=== disconnect is safe when nothing is connected ===")
    status, body = call(RELAY, "POST", "/api/jobby/google/disconnect", {})
    check("disconnect succeeds idempotently", status == 200 and body.get("ok") is True, (status, body))
    check("reports already disconnected", body.get("alreadyDisconnected") is True, body)

print("\n=== the portal proxies all of it ===")
status, s2 = call(PORTAL, "GET", "/api/jobby/google/status")
check("portal reaches google status", status == 200, (status, s2))
check("same payload through the portal", "requestedScopes" in s2, s2)
status, body = call(PORTAL, "GET", "/api/jobby/google/auth-url", allow_redirect=True)
check("portal proxies auth-url", status in (200, 503), (status, body))
status, body = call(PORTAL, "GET", "/api/jobby/google/callback?error=access_denied", allow_redirect=True)
check("portal proxies the callback redirect", status in (301, 302, 303, 307, 308), (status, body))
check("portal forwards the redirect target", "jobby.mobilemonero.com" in str(body.get("_redirect", "")), body)

print("\n=== an anonymous request gets its own empty client, never someone else's ===")
# /status deliberately mints a session rather than 401ing, so the portal panel
# works regardless of which request the browser makes first. The invariant that
# matters is isolation, not that the call is refused.
COOKIE.pop(8080, None)
COOKIE.pop(5175, None)
status, body = call(RELAY, "GET", "/api/jobby/google/status", use_cookie=False)
check("anonymous status still answers", status == 200, (status, body))
check("anonymous sees no connection", body.get("connection", {}).get("connected") is False, body.get("connection"))
check("anonymous sees no email", not body.get("connection", {}).get("email"), body.get("connection"))
check("a cookie was minted for it", bool(COOKIE.get(8080)), COOKIE.get(8080))

# And the endpoints that DO require a session still refuse without one.
COOKIE.pop(8080, None)
for path in ["/api/jobby/google/drive/files", "/api/jobby/google/gmail/messages",
             "/api/jobby/google/sent"]:
    status, body = call(RELAY, "GET", path, use_cookie=False)
    check(f"{path} still needs a session", status in (401, 502), (status, body))
status, body = call(RELAY, "GET", "/api/jobby/dossier", use_cookie=False)
check("dossier still needs a session", status in (401, 502), (status, body))

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("all google endpoint tests passed")
