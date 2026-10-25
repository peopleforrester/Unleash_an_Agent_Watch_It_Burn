# ABOUTME: Holds the working copies under specs/ to the personal-knowledge versions they name (#536): each header's
# ABOUTME: source line, a body unchanged from that sha256, and spec 001's schedule pointing at a real run-of-show section.
"""The specs/ working copies (#536).

personal-knowledge sends a spec down by its sha256 and keeps that hash in its specs/registry.yaml; its
scripts/spec-drift.py reads each copy here and compares the `source: personal-knowledge <file> @ sha256:<x>`
header with the registry. A copy is the source text with that one line added after `spec:`, so taking the
line back out must give bytes whose sha256 is the one the line records. Anything else means the copy was
edited here, which a change to a spec never is: it goes back to personal-knowledge and is sent down again.

Spec 001's `schedule:` line names this repo's run-of-show and its "Dates to hold (#447)" section, so the
section has to exist, and the two dates the spec keeps for people (M6 by 2026-11-08, M7 on 2026-11-12) have
to be the ones held there.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SPECS = REPO / "specs"
# The same pattern personal-knowledge scripts/spec-drift.py reads a copy's header with.
SOURCE = re.compile(r"source:\s*personal-knowledge\s+(specs/\S+)\s*@\s*sha256:([0-9a-f]+)")
BURRITOBOT = SPECS / "001-ready-by-11-08-delivered-11-12.md"
SENT = "4e127440568a302d374bc5eff51bd87a158485a5604267e65db19bdaed41474b"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


copies = sorted(SPECS.glob("*.md"))
print("== every copy under specs/ names its source and is that source unchanged ==")
check("specs/ holds at least one copy", bool(copies))
for path in copies:
    raw = path.read_bytes().decode("utf-8")
    lines = raw.splitlines(keepends=True)
    source = [i for i, l in enumerate(lines) if SOURCE.match(l)]
    check(f"{path.name}: exactly one source line", len(source) == 1)
    if len(source) != 1:
        continue
    i = source[0]
    check(f"{path.name}: the source line follows the spec: line", i > 0 and lines[i - 1].startswith("spec: "))
    sha = SOURCE.match(lines[i]).group(2)
    body = "".join(lines[:i] + lines[i + 1:]).encode("utf-8")
    check(f"{path.name}: the text without the source line hashes to sha256:{sha[:12]}",
          hashlib.sha256(body).hexdigest() == sha)

print("== spec 001 is the version sent as #536 ==")
text = BURRITOBOT.read_text(encoding="utf-8") if BURRITOBOT.exists() else ""
m = SOURCE.search(text)
check("the copy exists", bool(text))
check("it names personal-knowledge specs/talks/burritobot/001-ready-by-11-08-delivered-11-12.md",
      bool(m) and m.group(1) == "specs/talks/burritobot/001-ready-by-11-08-delivered-11-12.md")
check(f"it records sha256:{SENT[:12]}", bool(m) and m.group(2) == SENT)

print("== spec 001's schedule line points at a real section that holds its dates ==")
sched = re.search(r'^schedule:\s*(\S+), section "([^"]+)"', text, re.M)
check("the header has a schedule: line naming a file and a section", bool(sched))
if sched:
    target = REPO / sched.group(1)
    check(f"{sched.group(1)} exists", target.exists())
    ros = target.read_text(encoding="utf-8") if target.exists() else ""
    head = re.search(rf"^## {re.escape(sched.group(2))}\s*$", ros, re.M)
    check(f'it has the section "{sched.group(2)}"', bool(head))
    rest = ros[head.end():] if head else ""
    nxt = re.search(r"^## ", rest, re.M)
    section = rest[: nxt.start()] if nxt else rest
    rows = {r[0]: r for r in (
        [c.strip() for c in l.strip().strip("|").split("|")] for l in text.splitlines() if re.match(r"^\| M\d", l)
    )}
    check("M6 is by 2026-11-08 in the spec", "M6" in rows and "2026-11-08" in rows["M6"][-1])
    check("M7 is 2026-11-12 in the spec", "M7" in rows and "2026-11-12" in rows["M7"][-1])
    check("the run-of-show holds the run-throughs by 2026-11-08",
          re.search(r"^\| Two timed run-throughs \|.*By 2026-11-08", section, re.M) is not None)
    check("the run-of-show holds delivery on 2026-11-12",
          re.search(r"^\| Delivered \|.*2026-11-12", section, re.M) is not None)
    for mid in ("M1", "M3", "M4", "M5"):
        check(f"{mid} is agent-built with no date", mid in rows and rows[mid][-1].startswith("no date"))

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nspec copies OK")
