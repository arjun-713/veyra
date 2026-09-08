"""Fail CI if internal Markdown links point at missing files."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+\.md[^)\s]*)\)")
errors: list[str] = []

for md in [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").glob("*.md"))]:
    if not md.exists():
        continue
    for i, line in enumerate(md.read_text().splitlines(), 1):
        for m in LINK.findall(line):
            target = (md.parent / m.split("#")[0]).resolve()
            try:
                target.relative_to(ROOT)
            except ValueError:
                continue
            if not target.exists():
                errors.append(f"{md.relative_to(ROOT)}:{i} -> missing {m}")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print("docs links OK")
