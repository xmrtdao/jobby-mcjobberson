"""URL extraction, including the bare domains resumes actually use."""
import sys

sys.path.insert(0, ".")
from resume_ingest import _extract_urls  # noqa: E402

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail!r}"))
    if not cond:
        fails.append(label)


print("--- bare domains (previously dropped entirely) ---")
u = _extract_urls("github.com/jellis | linkedin.com/in/jordanellis | jellis.dev")
check("all three found", len(u) == 3, u)
check("github with path", "github.com/jellis" in u, u)
check("linkedin with path", "linkedin.com/in/jordanellis" in u, u)
check("apex domain", "jellis.dev" in u, u)

print("\n--- scheme'd URLs still work, and do not duplicate ---")
u = _extract_urls("see https://jane.example.com and jane.example.org")
check("https captured", "https://jane.example.com" in u, u)
check("bare captured", "jane.example.org" in u, u)
check("no scheme duplicate", len([x for x in u if "jane.example.com" in x]) == 1, u)

print("\n--- email domains are not links ---")
u = _extract_urls("john@example.com and github.com/jellis")
check("email host excluded", not any("example.com" in x for x in u), u)
check("real link kept", "github.com/jellis" in u, u)

u = _extract_urls("mail me at jane@mail.example.co.uk or visit example.co.uk")
check("email subdomain excluded", not any(x.startswith("mail.example") for x in u), u)

print("\n--- prose must not become links ---")
for text, why in [
    ("Built with Node.js and React", "Node.js"),
    ("Saved as resume.docx", "resume.docx"),
    ("Version 1.2 shipped", "1.2"),
    ("Check config.json for details", "config.json"),
    ("wrote main.py daily", "main.py"),
    ("No links here at all", "prose"),
]:
    check(f"no false positive: {why}", _extract_urls(text) == [], _extract_urls(text))

print("\n--- mixed document ---")
u = _extract_urls(
    "Jordan Ellis\njohn@example.com\n(804) 555-0142\n"
    "github.com/jellis | linkedin.com/in/jordanellis | jellis.dev\n"
    "Portfolio: https://jellis.dev/portfolio\n"
)
check("five distinct links", len(u) == 4, u)
check("portfolio path kept", "https://jellis.dev/portfolio" in u, u)
check("apex jellis.dev not duplicated by the portfolio URL",
      len([x for x in u if x.rstrip("/") == "jellis.dev"]) == 1, u)

print("\n--- trailing punctuation stripped ---")
u = _extract_urls("Visit github.com/jellis, or linkedin.com/in/jordanellis.")
check("no trailing comma/period", "github.com/jellis" in u, u)
check("second link clean", "linkedin.com/in/jordanellis" in u, u)

print("\n--- empty ---")
check("empty text", _extract_urls("") == [], _extract_urls(""))

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("all url tests passed")
