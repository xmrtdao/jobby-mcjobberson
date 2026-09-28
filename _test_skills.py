"""Skills extraction across the layouts real resumes use.

The original pattern only matched a list on the same line as the label, so the
very common "SKILLS" header with the list underneath was extracted as nothing.
"""
import sys

sys.path.insert(0, ".")
from resume_ingest import _extract_skills  # noqa: E402

fails = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + ("" if cond else f"  -> {detail}"))
    if not cond:
        fails.append(label)


print("--- inline list (the case that used to work) ---")
r = _extract_skills("SKILLS: Python, Go, Kubernetes")
check("inline skills found", r == ["Python", "Go", "Kubernetes"], r)

r = _extract_skills("Technical Skills: Python, Go")
check("technical skills", r == ["Python", "Go"], r)

r = _extract_skills("Skills - Python, Go")
check("dash separator", r == ["Python", "Go"], r)

print("\n--- header on its own line (was returning []) ---")
r = _extract_skills("SKILLS\nPython, Go, Kubernetes, Terraform, AWS")
check("bare header + list", r == ["Python", "Go", "Kubernetes", "Terraform", "AWS"], r)

r = _extract_skills("SKILLS\nPython, Go\n\nEDUCATION\nState University")
check("bare header stops at next section", r == ["Python", "Go"], r)

r = _extract_skills("SKILLS\nPython, Go\nEXPERIENCE\nAcme Corp, 2021")
check("bare header stops at heading", r == ["Python", "Go"], r)

print("\n--- bulleted skills ---")
r = _extract_skills("SKILLS\n\u2022 Python\n\u2022 Go\n\u2022 Terraform")
check("bulleted block", r == ["Python", "Go", "Terraform"], r)

r = _extract_skills("SKILLS\n- Python\n- Go")
check("dash bullets", r == ["Python", "Go"], r)

r = _extract_skills("Skills: \u2022 Python \u2022 Go")
check("inline bullets", r == ["Python", "Go"], r)

print("\n--- multi-line block ---")
r = _extract_skills("CORE SKILLS\nPython, Go, SQL\nKafka, Docker\nWORK HISTORY\nAcme")
check("two continuation lines", r == ["Python", "Go", "SQL", "Kafka", "Docker"], r)

print("\n--- must NOT match prose ---")
check("skilled in", _extract_skills("Skilled in Python and Go") == [], _extract_skills("Skilled in Python and Go"))
check("pro Skills line", _extract_skills("Pro Skills: fast learner") == [], _extract_skills("Pro Skills: fast learner"))
check("no skills section", _extract_skills("Built Python services at Acme") == [], _extract_skills("Built Python services at Acme"))

print("\n--- 'Skills and Tools' label ---")
r = _extract_skills("Skills and Tools: Python, Go")
check("skills and tools", r == ["Python", "Go"], r)

print("\n--- dedupe + tidying ---")
r = _extract_skills("SKILLS: Python, python, PYTHON, Go")
check("case-insensitive dedupe", r == ["Python", "Go"], r)

r = _extract_skills("SKILLS: Python, Go.")
check("trailing dot trimmed", r == ["Python", "Go"], r)

print("\n--- multiple blocks ---")
r = _extract_skills("SKILLS: Python, Go\nTOOLS: Docker, Terraform")
check("two blocks", r == ["Python", "Go", "Docker", "Terraform"], r)

print()
if fails:
    print(f"{len(fails)} FAILED: " + "; ".join(fails))
    sys.exit(1)
print("all skills tests passed")
