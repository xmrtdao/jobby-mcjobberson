"""Static asset delivery: cache-busted asset URLs, cache headers, 404s.

Cloudflare rewrites the origin's "no-cache" on .js/.css to max-age=14400, so
without a versioned URL a redeploy leaves clients running an old script against
new markup for up to four hours.
"""
import json
import sys
import threading
import http.client
from pathlib import Path

ROOT = Path(__file__).parent / "docs"
sys.path.insert(0, ".")

fails = []

# The assets the server stamps, read from the server rather than copied. Copied,
# this is the shape of the bug it guards: two lists that agree until somebody
# edits only one of them. i18n.js was added to the server and not to the test's
# own list, and was consequently the one asset nothing checked.
try:
    from resume_server import _VERSIONED_ASSETS as _VERSIONED_FOR_STAMP
except Exception:  # noqa: BLE001 - reported by the checks below
    _VERSIONED_FOR_STAMP = ("app.js", "styles.css", "jobby.js", "hero-scene.js", "i18n.js")



def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail!r}"))
    if not cond:
        fails.append(label)


from resume_server import create_server  # noqa: E402

server = create_server("127.0.0.1", 0, ROOT)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()


def get(path):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    headers = dict(resp.getheaders())
    status = resp.status
    conn.close()
    return status, headers, body.decode("utf-8", "replace")


try:
    print("--- index.html cache-busts its assets ---")
    status, headers, html = get("/")
    check("index served", status == 200, status)
    check("index is revalidated", headers.get("Cache-Control") == "no-cache",
          headers.get("Cache-Control"))
    import re
    scripts = re.findall(r'src="(app\.js[^"]*)"', html)
    styles = re.findall(r'href="(styles\.css[^"]*)"', html)
    check("app.js reference found", len(scripts) == 1, scripts)
    check("styles.css reference found", len(styles) == 1, styles)
    check("app.js has a version", scripts and scripts[0].startswith("app.js?v="), scripts)
    check("styles.css has a version", styles and styles[0].startswith("styles.css?v="), styles)

    expected = str(int((ROOT / "app.js").stat().st_mtime))
    check("version matches app.js mtime", scripts and scripts[0] == f"app.js?v={expected}",
          (scripts, expected))

    print("\n--- the versioned URL actually serves the file ---")
    status, headers, body = get(scripts[0])
    check("versioned app.js 200", status == 200, status)
    check("versioned app.js is js", "javascript" in headers.get("Content-Type", ""),
          headers.get("Content-Type"))
    check("versioned app.js has current content", "function appendList" in body)
    check("versioned app.js is cacheable", "max-age" in headers.get("Cache-Control", ""),
          headers.get("Cache-Control"))

    print("\n--- stylesheet ---")
    status, headers, body = get(styles[0])
    check("versioned styles.css 200", status == 200, status)
    check("versioned styles.css is css", "text/css" in headers.get("Content-Type", ""),
          headers.get("Content-Type"))
    check("dossier styles present", ".dossier-timeline" in body)

    print("\n--- unversioned asset still works (direct hits, bookmarks) ---")
    status, _, body = get("/app.js")
    check("bare app.js 200", status == 200, status)
    check("bare app.js has current content", "function appendList" in body)

    print("\n--- security headers still applied ---")
    _, headers, _ = get("/")
    check("CSP present", "default-src 'self'" in headers.get("Content-Security-Policy", ""),
          headers.get("Content-Security-Policy"))
    check("nosniff present", headers.get("X-Content-Type-Options") == "nosniff")
    check("frame options present", headers.get("X-Frame-Options") == "DENY")

    print("\n--- traversal and unknown assets still 404 ---")
    for path in ("/../resume_server.py", "/nope.js", "/sub/app.js"):
        status, _, _ = get(path)
        check(f"404 for {path}", status == 404, status)

    print("\n--- dossier panel is in the served markup ---")
    check("dossier panel present", 'id="dossier-panel"' in html)
    check("dossier heading present", 'id="dossier-heading"' in html)
    check("dossier body present", 'id="dossier-body"' in html)

    print("\n--- asset encoding is clean ---")
    # A PowerShell Get-Content/Set-Content round trip once read this BOM-less
    # file as Windows-1252 and double-encoded it, so the page rendered "Â·"
    # instead of "·". Guard against that coming back.
    MOJIBAKE = {0xC2, 0xC3, 0xE2, 0x20AC, 0x201C, 0x201D, 0x201A, 0x0192, 0x2122}
    for name in ("app.js", "index.html", "styles.css"):
        raw = (ROOT / name).read_bytes()
        check(f"{name} has no BOM", raw[:3] != b"\xef\xbb\xbf", raw[:3])
        text = raw.decode("utf-8")  # raises if not valid UTF-8
        offenders = sorted({
            hex(ord(c))
            for c in text
            if ord(c) > 127 and ord(c) in MOJIBAKE
        })
        check(f"{name} has no double-encoded characters", not offenders, offenders)

    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    check("app.js uses the intended separators",
          "·" in app_js and "Â·" not in app_js and "…" in app_js)

    print("\n--- jobby.js is served and versioned ---")
    jobby_scripts = re.findall(r'src="(jobby\.js[^"]*)"', html)
    check("jobby.js reference found", len(jobby_scripts) == 1, jobby_scripts)
    check("jobby.js has a version", jobby_scripts and jobby_scripts[0].startswith("jobby.js?v="), jobby_scripts)
    status, headers, body = get(jobby_scripts[0] if jobby_scripts else "/jobby.js")
    check("versioned jobby.js 200", status == 200, status)
    check("jobby.js is js", "javascript" in headers.get("Content-Type", ""), headers.get("Content-Type"))
    check("jobby.js defines the panel entry point", "function initJobby" in body)
    check("jobby.js is in the allowlist", "jobby.js" in (ROOT / "index.html").read_text(encoding="utf-8"))

    print("\n--- the agent panel markup is present ---")
    for needed in ('id="jobby"', 'id="jobby-log"', 'id="jobby-form"', 'id="jobby-input"',
                   'id="jobby-tracks"', 'id="jobby-plan"', 'id="jobby-edits"',
                   'id="jobby-kill-switch"', 'id="jobby-autonomy"'):
        check(f"markup has {needed}", needed in html)
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

# --- every versioned asset is stamped ---------------------------------------
# The assertions above cover app.js, styles.css and jobby.js one at a time, and
# i18n.js was never added to that list. It was also the one that went unstamped:
# the script tag read src="/i18n.js" with a leading slash while the stamper
# matched a bare quoted name, so a browser kept serving the original module
# indefinitely. The symptom was a page in Spanish around a dossier whose headings
# stayed English, and every dictionary key added after the first batch appearing
# to do nothing.
#
# Driven by the server's own list rather than a copy, because that is the shape of
# the bug: two lists that agree until somebody edits only one of them.
print("\n--- every versioned asset is stamped ---")
# The entry point the suite already read above, kept in `html`. Fetching it
# again here would fail: this runs after server.shutdown(), so the test server is
# already down.
_referenced = set(re.findall(r'(?:src|href)="([^"?]+)(?:\?[^"]*)?"', html))
# The character class includes the hyphen: hero-scene.js has one, and a class of
# \w and . cannot match it - which made this assertion report a missing stamp on
# an asset that is stamped correctly. A check that cries wolf is a check that
# gets ignored.
_stamp_of = dict(re.findall(r'([\w.-]+\.(?:js|css))\?v=(\d+)', html))
for _asset in _VERSIONED_FOR_STAMP:
    check("%s is referenced" % _asset, _asset in _referenced, sorted(_referenced))
    check("%s carries a version stamp" % _asset, _asset in _stamp_of,
          "no ?v= on %s, so a browser will keep serving the old file" % _asset)

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("all static-delivery tests passed")
