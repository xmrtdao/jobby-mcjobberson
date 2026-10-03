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
# What the front page itself carries. The list above is everything the server
# stamps; this is the subset index.html is expected to reference. Conflating the
# two is what made this block report the dashboard and employer assets as missing
# from a page they were never meant to be on.
_FRONT_PAGE_ASSETS = ("app.js", "styles.css", "jobby.js", "hero-scene.js", "i18n.js",
                      # The chat became a floating panel shared with the dashboard, so
                      # the front page now references these two as well. Listed here
                      # rather than left to the union check below, because the union
                      # only proves *some* page stamps them — it would pass with the
                      # front page pointing at an unstamped copy.
                      "jobby-chat-widget.js", "chat-widget.css")



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

    # ── the other two entry points, while the server is still up ────────────
    #
    # The page-agreement checks further down read these from disk, which is
    # wrong for the stamp: `?v=` is added by the server on the way out, so a file
    # on disk never has one and reading it from disk reports every asset as
    # unstamped. Fetched here instead, which is the only place the stamped bytes
    # exist. The two new pages 404'd on first serve because the server's asset
    # allowlist did not name them, and nothing here would have caught that — the
    # status check is the point.
    print("\n--- dashboard and employer pages are served and cache-bust ---")
    _PAGE_ASSETS = {
        "/dashboard.html": {"dashboard.js", "dashboard.css", "i18n.js"},
        "/employers.html": {"employer.js", "employer.css", "i18n.js"},
    }
    served_pages = {}
    for _route, _expected in sorted(_PAGE_ASSETS.items()):
        _status, _headers, _body = get(_route)
        check("%s served" % _route, _status == 200,
              "the page is linked from the nav but the server does not serve it — "
              "is it missing from _STATIC_ASSETS?")
        if _status != 200:
            continue
        served_pages[_route] = _body
        check("%s is revalidated" % _route, _headers.get("Cache-Control") == "no-cache",
              _headers.get("Cache-Control"))
        _stamps = dict(re.findall(r'([\w.-]+\.(?:js|css))\?v=(\d+)', _body))
        for _asset in sorted(_expected):
            check("%s stamps %s" % (_route, _asset), _asset in _stamps,
                  "references %s with no ?v=, so a browser keeps the old file after "
                  "a change" % _asset)

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

    print("\n--- the conversation is a floating panel, on every candidate page ---")
    # These ids used to be asserted present in index.html, because that is where
    # the chat lived. It no longer does — jobby-chat-widget.js builds the subtree at
    # runtime, so the ids exist in the file that creates them and jobby.js finds
    # them by getElementById. The invariant is therefore "the ids exist somewhere
    # the browser will have them before jobby.js runs", not "they are in this
    # markup", and that is what is checked: the widget builds them, both pages load
    # the widget, and both load it before jobby.js.
    widget_js = (ROOT / "jobby-chat-widget.js").read_text(encoding="utf-8")
    for needed in ("jobby-log", "jobby-form", "jobby-input", "jobby-send", "jobby-hint",
                   "attach-row", "attach-list", "jobby-attach"):
        check(f"the widget builds {needed}", f"'{needed}'" in widget_js or f'"{needed}"' in widget_js)

    # jobby.js caches these once and attaches listeners to them, so a widget that
    # mounts after it produces a chat that renders perfectly and sends nothing.
    # Document order is execution order for `defer`, so the order of the two tags is
    # the whole mechanism. This is the check that would have caught a silent,
    # completely plausible "the chat is broken and I cannot see why".
    for page in ("index.html", "dashboard.html"):
        phtml = (ROOT / page).read_text(encoding="utf-8")
        wi = phtml.find("jobby-chat-widget.js")
        ji = phtml.find('src="jobby.js')
        check(f"{page} loads the chat widget", wi != -1, phtml[:200])
        check(f"{page} loads the widget before jobby.js", wi != -1 and ji != -1 and wi < ji,
              f"widget at {wi}, jobby.js at {ji}")
        check(f"{page} loads the chat stylesheet", "chat-widget.css" in phtml)
        check(f"{page} loads jobby.js", ji != -1)

    # The widget is not on the employers page, and must not be: that is a different
    # audience with a different session and a different chat. A candidate's
    # conversation appearing on the page a recruiter is using would put one
    # person's transcript in front of another.
    emp_html = (ROOT / "employers.html").read_text(encoding="utf-8")
    check("employers.html does NOT load the candidate chat", "jobby-chat-widget.js" not in emp_html)
    check("employers.html keeps its own chat script", "employer.js" in emp_html)

    # Served, not just referenced. A script tag pointing at a file the allowlist
    # does not name is a 404 that reads as a broken build.
    for asset in ("jobby-chat-widget.js", "chat-widget.css"):
        status, headers, body = get(f"/{asset}")
        check(f"{asset} is served", status == 200, status)
        check(f"{asset} is not html", "html" not in headers.get("Content-Type", ""),
              headers.get("Content-Type"))

    print("\n--- the agent panel markup is present ---")
    # The side panel and the status block stay on the front page; only the chat
    # moved. If these are missing the page has been over-trimmed.
    for needed in ('id="jobby"', 'id="jobby-tracks"', 'id="jobby-plan"', 'id="jobby-edits"',
                   'id="jobby-kill-switch"', 'id="jobby-autonomy"'):
        check(f"markup has {needed}", needed in html)
    # And the chat's own ids are gone from the markup, because a copy left behind
    # would be duplicated by the widget at runtime: two forms, two ids, and
    # getElementById returning whichever the parser saw first.
    for gone in ('id="jobby-log"', 'id="jobby-form"', 'id="jobby-input"'):
        check(f"markup no longer hardcodes {gone}", gone not in html)
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
print("\n--- the front page stamps its own assets ---")
# Index only. It is the page this block has always meant, and the other two are
# checked per-page above while the server is still running.
#
# Scoped to the front page's five assets on purpose. Running the full versioned
# list against index.html alone reported the new pages' assets as missing from
# it — which is true, and not a fault: dashboard.js is not supposed to be on the
# front page. The list belongs to the server; which page carries which asset is a
# per-page question, asked per page above.
_referenced = set(re.findall(r'(?:src|href)="([^"?]+)(?:\?[^"]*)?"', html))
# The character class includes the hyphen: hero-scene.js has one, and a class of
# \w and . cannot match it - which made this assertion report a missing stamp on
# an asset that is stamped correctly. A check that cries wolf is a check that
# gets ignored.
_stamp_of = dict(re.findall(r'([\w.-]+\.(?:js|css))\?v=(\d+)', html))
for _asset in _FRONT_PAGE_ASSETS:
    check("%s is referenced" % _asset, _asset in _referenced, sorted(_referenced))
    check("%s carries a version stamp" % _asset, _asset in _stamp_of,
          "no ?v= on %s, so a browser will keep serving the old file" % _asset)

# ── the asset list, against the union of what the pages reference ───────────
#
# There are now three pages, and this section only ever read index.html. So it
# reported the new pages' assets as unreferenced and unstamped when the real
# problem was that it was looking in one file.
#
# The failure is the mirror of the one this file already documents — a list that
# agrees with reality until somebody adds a second copy of the truth. The union
# of the served pages is the honest source; the per-page stamp checks above are
# where each page is verified against its own assets.
print("\n--- every versioned asset appears on the page that uses it ---")
_all_referenced = set(_referenced)
for _body in served_pages.values():
    _all_referenced.update(re.findall(r'(?:src|href)="([^"?]+)(?:\?[^"]*)?"', _body))
for _asset in _VERSIONED_FOR_STAMP:
    check("%s is referenced by some page" % _asset, _asset in _all_referenced,
          sorted(_all_referenced))

# The three pages must link to each other and to the front page. A page
# reachable from the nav but not linking back is how a product ends up with two
# disconnected halves nobody notices until a user is stranded on one.
print("\n--- the three pages are wired to each other ---")
for _page, _expected_links in sorted({
    "index.html": {"dashboard.html", "employers.html"},
    "dashboard.html": {"index.html", "employers.html"},
    "employers.html": {"index.html", "dashboard.html"},
}.items()):
    _path = ROOT / _page
    check("%s exists" % _page, _path.is_file(), "the page is linked from the nav but not on disk")
    if not _path.is_file():
        continue
    _page_html = _path.read_text(encoding="utf-8")
    for _target in sorted(_expected_links):
        check(
            "%s links to %s" % (_page, _target),
            'href="%s"' % _target in _page_html,
            "the nav on this page does not reach %s" % _target,
        )

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("all static-delivery tests passed")
