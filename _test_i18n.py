#!/usr/bin/env python3
"""The Spanish layer, checked as a system rather than spot-checked.

Three things can go wrong here that no browser test would reliably catch, so
they are asserted directly against the files:

  1. Coverage. The dictionary is keyed by the English source string, which means
     an English string with no Spanish entry silently stays English. That is the
     failure mode this approach trades for not touching 93 places of markup, so
     it is checked exhaustively rather than sampled - and with a real HTML parser,
     because the browser walks actual text nodes and a regex approximation
     merges nodes the browser sees separately, which would either invent
     failures or hide real ones.

  2. The name rule. In Spanish the agent is "Don Trabajo" and never "Don" on its
     own. The user asked for that explicitly, and "Don" is a title: a Spanish
     reader reads it as a courtesy, not a name. Asserted so nobody reintroduces
     it with a quick edit.

  3. The runtime rename. A string the dictionary does not know is still passed
     through the name substitution, because the agent's name appears in strings
     built at runtime - status lines, chat replies - that never pass through the
     dictionary at all.
"""
import io
import json
import re
import subprocess
import sys
from html.parser import HTMLParser

fails = []


def check(label, condition, detail=""):
    print(("  PASS  " if condition else "  FAIL  ") + label
          + ("" if condition else "   %s" % (detail,)))
    if not condition:
        fails.append(label)


class TextNodes(HTMLParser):
    """The text nodes the browser's TreeWalker would see."""

    SKIP = {"script", "style", "code", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        text = " ".join(data.split())
        if len(text) > 1:
            self.nodes.append(text)


i18n_path = "docs/i18n.js"
i18n_src = io.open(i18n_path, encoding="utf-8").read()
i18n_path_text = i18n_src
html = io.open("docs/index.html", encoding="utf-8").read()

# --- 1. load the module in node and switch it to Spanish ---------------------
PROBE = """
const fs = require('fs');
const store = { v: null };
const localStorage = { getItem: () => null, setItem: (k, v) => { store.v = v; } };
// The module reaches for window.localStorage, so the window stub has to carry
// it. Without it the module's own try/catch swallows the TypeError and the
// language silently fails to persist - which is exactly the bug this stub
// would otherwise have hidden.
global.window = { localStorage };
global.document = {
  documentElement: {},
  addEventListener(){}, dispatchEvent(){},
  querySelectorAll(){ return []; },
  createTreeWalker(){ return { nextNode(){ return null; } }; },
  // The applier walks document.body when the language changes, so the stub has
  // to be a body too - not just a top-level document.
  body: { querySelectorAll(){ return []; } },
};
global.localStorage = { getItem: () => null, setItem: (k, v) => { store.v = v; } };
global.CustomEvent = function(){};
global.NodeFilter = { SHOW_TEXT: 4, FILTER_ACCEPT: 1, FILTER_REJECT: 2 };
global.Node = function(){};
global.FileReader = function(){};
const src = fs.readFileSync('docs/i18n.js', 'utf8');
new Function('window','document','localStorage','CustomEvent','NodeFilter','Node','FileReader', src)(
  global.window, global.document, global.localStorage, global.CustomEvent,
  global.NodeFilter, global.Node, global.FileReader);
const I = global.window.JobbyI18n;
I.setLang('es');
console.log(JSON.stringify({
  es: I.dict.es,
  agentName: I.agentName(),
  agentShort: I.agentShort(),
  isSpanish: I.isSpanish(),
  brand: I.tn('Jobby McJobberson'),
  short: I.tn('Jobby'),
  full: I.tn('Jobby writes to your dossier when you tell it something. Every change is logged and you can see it below.'),
  unknownButNamed: I.tn('Jobby is thinking about the role you mentioned.'),
  unknownPlain: I.tn('a string nobody translated'),
  persisted: store.v,
}));
"""

result = subprocess.run(["node", "-e", PROBE], capture_output=True, text=True,
                       # Node writes UTF-8; without this Windows decodes the
                       # Spanish as CP1252 and the reader thread dies on the
                       # first accented character.
                       encoding="utf-8", errors="replace")
if result.returncode != 0:
    print("  FAIL: could not load the module in node")
    print((result.stderr or "")[:700])
    sys.exit(1)
data = json.loads(result.stdout)
es = data["es"]

print("=== the dictionary loads and switches ===")
check("the Spanish dictionary is populated", len(es) > 80, len(es))
check("switching to Spanish is recorded", data["isSpanish"] is True)
check("the choice is persisted for the next visit", data["persisted"] == "es",
      data["persisted"])
check("the agent's full name is Don Trabajo", data["agentName"] == "Don Trabajo",
      data["agentName"])
check("the short name is Don Trabajo too, never Don",
      data["agentShort"] == "Don Trabajo", data["agentShort"])
check("the brand substitutes rather than translating the surname",
      data["brand"] == "Don Trabajo", data["brand"])

print("\n=== the name rule: never Don on its own ===")
bare = []
for key, value in es.items():
    for m in re.finditer(r"\bDon\b(?! Trabajo)", value):
        bare.append((key[:44], value[max(0, m.start() - 16):m.end() + 16]))
check("no Spanish string uses Don on its own", not bare, bare[:3])
check("Don Trabajo is really used in the copy",
      sum(v.count("Don Trabajo") for v in es.values()) >= 8,
      sum(v.count("Don Trabajo") for v in es.values()))
check("a bare Jobby becomes Don Trabajo", data["short"] == "Don Trabajo", data["short"])
check("an untranslated runtime string is still renamed",
      data["unknownButNamed"] == "Don Trabajo is thinking about the role you mentioned.",
      data["unknownButNamed"])
check("an unrelated untranslated string passes through untouched",
      data["unknownPlain"] == "a string nobody translated", data["unknownPlain"])

print("\n=== translation and renaming compose ===")
check("a known string is translated and renamed together",
      "expediente" in data["full"] and "Jobby" not in data["full"], data["full"][:96])

print("\n=== coverage: every visible text node is translated ===")
parser = TextNodes()
parser.feed(html)
nodes = list(dict.fromkeys(parser.nodes))

# Not prose: the monogram becomes DT, the numerals stay numerals, and the toggle
# label is deliberately the language code rather than a translated word.
SKIP = {"JM", "01", "02", "03", "04", "ES", "EN"}
untranslated = [n for n in nodes if n not in es and n not in SKIP]
check("every visible text node has a Spanish entry", not untranslated,
      untranslated[:6])
print("       %d text nodes, %d untranslated" % (len(nodes), len(untranslated)))

print("\n=== the monogram and the brand ===")
check("the monogram becomes DT", es.get("JM") == "DT", es.get("JM"))
check("the brand line is Don Trabajo",
      es.get("Jobby McJobberson") == "Don Trabajo", es.get("Jobby McJobberson"))

print("\n=== the toggle is reachable and labelled ===")
check("there is a language toggle in the nav", 'id="lang-toggle"' in html)
check("its accessible name is Spanish, naming the language it switches to",
      'aria-label="Cambiar el idioma a espa&ntilde;ol"' in html)
check("it is a real button, so it is keyboard operable",
      re.search(r'<button[^>]*id="lang-toggle"', html) is not None)
check("i18n.js loads before app.js so runtime strings can use it",
      html.index('src="i18n.js"') < html.index('src="app.js"'))
# Referenced without a leading slash, because the version stamper matches a bare
# quoted name. As "/i18n.js" it was never stamped and a browser kept serving the
# original module indefinitely - the page went Spanish around a dossier whose
# headings stayed English. _test_static.py now asserts that every versioned asset
# is stamped, which is the check whose absence let that ship.
check("i18n.js is referenced so the version stamper can find it",
      'src="i18n.js"' in html and 'src="/i18n.js"' not in html)

print("\n=== every string app.js translates actually exists ===")
# The sharp edge of keying by the English source: a key that does not match the
# page byte for byte silently leaves English there and the suite stays green. One
# of these ended in a full stop where the page writes U+2026, which is how that
# is found - not by reading the dictionary, which looked complete.
app = io.open("docs/app.js", encoding="utf-8").read()
asked = sorted(set(re.findall(r"tn\('([^']+)'\)", app)))
panel = io.open("docs/jobby.js", encoding="utf-8").read()
asked += sorted(set(re.findall(r"tn\('([^']+)'\)", panel)))
missing = [k for k in asked if ("'" + k + "':") not in i18n_src]
check("every tn() key exists in the dictionary", not missing,
      [m.encode("unicode_escape").decode("ascii")[:60] for m in missing[:5]])
print("       %d keys asked for, %d missing" % (len(asked), len(missing)))

print("\n=== the live agent panel is translated too ===")
# Its checkboxes were translated while the figures beside them were not, which
# read as a half-finished feature rather than an untranslated one.
for phrase in ("{n} of {total} tracks active", "No tracks active",
               "{used} of {cap} sends used in the last 24 hours"):
    check("the panel string %r is translated" % phrase[:38], phrase in es)
check("the mission state is looked up by key, not hardcoded",
      "JOBBY_MISSION_LABELS" in panel and "missionLabel(" in panel)
# The English text is supposed to exist - as the en: entry of the lookup table,
# and as the key handed to tn(). What must not happen is it being rendered
# directly, so these check the shape of the code rather than the absence of a
# string.
_mission_entries = re.findall(r"^\s*(seeking|placed|advancing|paused):\s*(.+?),?$",
                              panel, re.M)


def _mission_entry_ok(value):
    """Either a lookup call, or a table row carrying both languages.

    Both forms are correct and both appear: the table defines the two languages
    and the call sites resolve one of them. What would be wrong is a bare English
    literal in either place, so that is what is excluded.
    """
    if "missionLabel(" in value:
        return True
    return "en:" in value and "es:" in value


check("every mission entry is a lookup or a bilingual table row",
      bool(_mission_entries)
      and all(_mission_entry_ok(value) for _, value in _mission_entries),
      [e for e in _mission_entries if not _mission_entry_ok(e[1])])
check("the English mission text lives only in the lookup table",
      panel.count("No income secured. Every day counts.") == 1
      and "en:" in panel)
check("the tracks figure is built inside tn()",
      re.search(r"tn\('\{n\} of \{total\} tracks active'\)", panel) is not None)
check("the send-cap figure is built inside tn()",
      re.search(r"tn\('\{used\} of \{cap\} sends used", panel) is not None)
check("no English figure line is assigned to textContent directly",
      not re.search(r"textContent\s*=\s*`?\$\{?s?\.?sent", panel))

# Declaration order, not syntax. The mission table was appended to the end of
# jobby.js while the state map near the top called it during module evaluation,
# and a const later in the file sits in its temporal dead zone until execution
# reaches it: the panel threw "Cannot access JOBBY_MISSION_LABELS before
# initialization" and never drew at all. node --check passed throughout, because
# this is an ordering fault rather than a syntax one.
_decl = panel.find("const JOBBY_MISSION_LABELS")
_define = panel.find("function missionLabel")
_uses = [u for u in (panel.find("missionLabel('%s')" % s)
                     for s in ("seeking", "placed", "advancing", "paused"))
         if u != -1]
check("the mission table is declared before it is first called",
      bool(_decl != -1 and _uses) and _decl < min(_uses),
      "declared %d, first called %d" % (_decl, min(_uses) if _uses else -1))
check("the mission function is declared before it is first called",
      bool(_define != -1 and _uses) and _define < min(_uses),
      "defined %d, first called %d" % (_define, min(_uses) if _uses else -1))
check("the mission table is not left in the tail of the file",
      _decl == -1 or _decl < len(panel) * 0.5,
      "declared at %d of %d" % (_decl, len(panel)))

print("\n=== the dossier is translated, not just the page ===")
for label in ("Identity", "Summary", "Skills", "Experience", "Education",
              "Certifications", "Extraction confidence", "Team size",
              "Confirmed achievements", "Flagged for verification",
              "Name not stated", "None listed", "None inferred", "Job fields",
              "Domain expertise", "Roles named in the resume",
              "Suggested target roles", "Dossier for", "Dossier unavailable"):
    check("the dossier label %r is translated" % label, label in es)

# Confidence values and gap names are stored as English machine keys and
# translated at the point of display, so they need lookups rather than entries.
check("confidence is looked up by key, not printed raw", "JOBBY_CONFIDENCE" in app)
check("the confidence value is routed through it",
      "confidenceLabel(profile.confidence)" in app)
check("gap names are translated at display time",
      "JOBBY_GAP_LABELS" in app and "gapList(" in app)
# Built inline from the profile rather than through a helper, so the earlier
# replace of a "(profile.not_stated || [])" shape never matched. These two lists
# are what a candidate reads when something is missing or doubtful, which makes
# them the worst place in the dossier to print a stored English key.
check("the not_stated list goes through the lookup",
      "const gaps = gapList(profile.not_stated)" in app)
check("the verification flags go through the lookup",
      "const flags = gapList(profile.verification_flags)" in app)
check("no dossier card title is hardcoded English",
      not re.search(r"dossierCard\(\s*'[A-Z]", app))

# The subheadings pass their title as the third argument to el(), not the second,
# so the pattern that found the card titles walked past them - and two of the
# most-read headings in the panel stayed English because of it.
dossier_start = app.find("function renderDossier")
dossier_end = app.find("function renderDossierUnavailable", dossier_start)
dossier_seg = app[dossier_start:dossier_end]
bare_subheads = re.findall(r"el\('h3',\s*'dossier-subhead',\s*'([A-Z][^']+)'\)",
                           dossier_seg)
check("no dossier subheading is hardcoded English", not bare_subheads, bare_subheads)

# The build-stage labels are defined server-side in one language only, so the
# client translates them by stage key. A live Spanish build is what found this:
# the summary came back in Spanish while the progress bar stayed English.
server_src = io.open("resume_server.py", encoding="utf-8").read()
stage_table = re.search(
    r"_DOSSIER_STAGES: tuple\[tuple\[str, str\], \.\.\.\] = \((.*?)\n\)",
    server_src, re.S)
declared = set(re.findall(r'\("(\w+)",\s*"', stage_table.group(1))) if stage_table else set()
stage_block = re.search(r"const JOBBY_STAGE_LABELS = \{(.*?)\n\};", app, re.S)
mapped = set(re.findall(r"(\w+):\s*\{\s*es:", stage_block.group(1))) if stage_block else set()
check("every build stage the server can report has a Spanish label",
      bool(declared) and declared.issubset(mapped), sorted(declared - mapped))
check("the client's stage label is preferred over the server's English one",
      "stageLabel(progress)" in app)

print("\n=== alignment ===")
css = io.open("docs/styles.css", encoding="utf-8").read()
section = re.search(r"\.parsed-profile-section \{[^}]*\}", css)
check("the dossier section is left-aligned",
      bool(section) and "text-align: left" in section.group(0),
      section.group(0)[:80] if section else "rule not found")
check("the section intro stays centred, deliberately",
      ".parsed-profile-section .section-heading" in css
      and "text-align: center" in css)

print("\n=== the language reaches the server ===")
app = io.open("docs/app.js", encoding="utf-8").read()
server = io.open("resume_server.py", encoding="utf-8").read()
render = io.open("resume_render.py", encoding="utf-8").read()
check("the upload sends the language", "append('lang', currentLang())" in app)
check("the download link carries it", "resume/document?lang=" in app)
check("the build is told which language to write in", "_language_rule" in server)
check("the language is read from the upload, not a cookie at build time",
      'fields.get("lang")' in server)
check("the rendered resume takes a language", "lang: str = \"en\"" in render)
check("the resume headings are looked up, not hardcoded",
      "_SECTION_NAMES" in render and 'heading.add_run("SKILLS")' not in render)

print()
if fails:
    print("%d FAILED: %s" % (len(fails), "; ".join(fails)))
    sys.exit(1)
print("the Spanish layer is complete and self-consistent")
