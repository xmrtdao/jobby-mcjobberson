"""Encoding guard for the portal's static assets.

A PowerShell Get-Content/Set-Content round trip once read a BOM-less file as
Windows-1252 and double-encoded it, so the page rendered "Â·" instead of "·".
This fails the build rather than letting that come back.
"""
import sys
from pathlib import Path

ASSETS = ["index.html", "app.js", "jobby.js", "styles.css"]
MOJIBAKE = {0xC2, 0xC3, 0xE2, 0x20AC, 0x201C, 0x201D, 0x201A, 0x0192, 0x2122}

root = Path(__file__).parent / "docs"
fails = []

for name in ASSETS:
    path = root / name
    if not path.is_file():
        fails.append(f"{name}: missing")
        continue
    raw = path.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        fails.append(f"{name}: has a UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        fails.append(f"{name}: not valid UTF-8 ({e})")
        continue
    offenders = sorted({hex(ord(c)) for c in text if ord(c) > 127 and ord(c) in MOJIBAKE})
    if offenders:
        fails.append(f"{name}: double-encoded characters {offenders}")
    else:
        non_ascii = sorted({hex(ord(c)) for c in text if ord(c) > 127})
        print(f"  PASS  {name}: clean ({len(raw)}b, non-ascii: {non_ascii or 'none'})")

if fails:
    print()
    for f in fails:
        print("  FAIL  " + f)
    sys.exit(1)
print("\nall portal assets are clean UTF-8")
