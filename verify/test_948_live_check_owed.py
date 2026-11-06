# ABOUTME: Pins #948's two-doc criterion (#960): the decisions.md entry names the owed live check on both KubeCon
# ABOUTME: bots under "Not yet run on a cluster", and PROGRESS.md carries the #948 entry that completes #922.
"""Holds the criterion of #948 that test review run 17797 found no test checked (#960).

#948 asked for two records of its chat-page change, and both are history read as literal text, not derived from the
code:
  1. decisions.md's "## 2026-11-06 · #948 · run 17755" entry must carry a "Not yet run on a cluster" section that
     names the owed live check on the public bot (watch-it-burn-community, `https://attackme.burritobot.co`) and the
     private bot (watch-it-burn-private, `https://burritobot-private.burritobot.co`).
  2. PROGRESS.md must carry #948's changelog bullet, in [Unreleased] under a ### heading, once and dated, recording
     that it completes #922 in the repo and pointing at its decisions.md entry.

Each cut this test makes on repo text first checks the literal is there and exits naming the literal and the file
when it is not (per "Tests own their inputs"), so a reworded anchor reads as that, not as a broken check further on.
Every criterion check is also run against a mutated copy with the thing it reads struck out, so a check that could
never fail would show up here: the decisions entry with its heading gone, the owed block with its label gone, the
owed block with each bot name or URL struck, and the PROGRESS bullet removed, moved out of [Unreleased], undated,
doubled and with no ### heading above it.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
PROGRESS = (REPO / "PROGRESS.md").read_text(encoding="utf-8")

DEC_HEAD = "## 2026-11-06 · #948 · run 17755"
OWED_LABEL = "**Not yet run on a cluster.**"
PROG_HEAD = "- (2026-11-06) #948, completing #922 in the repo:"

# The four things the owed live check must name: each bot's cluster context and its URL.
BOTS = [
    ("the public bot's cluster context", "watch-it-burn-community"),
    ("the public bot's URL", "https://attackme.burritobot.co"),
    ("the private bot's cluster context", "watch-it-burn-private"),
    ("the private bot's URL", "https://burritobot-private.burritobot.co"),
]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_948_live_check_owed.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def dec_entry(text: str, head: str) -> str:
    """The decisions.md entry starting `head`, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(head) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def owed_block(section: str) -> str:
    """The 'Not yet run on a cluster' paragraph of `section`, to the next bold label or EOF; empty when absent."""
    m = re.search(re.escape(OWED_LABEL) + r"(.*?)(?=\n\n\*\*|\Z)", section, flags=re.S)
    return m.group(1) if m else ""


def owed_names_all(block: str) -> bool:
    return all(lit in block for _, lit in BOTS)


# ---- decisions.md: #948's entry names the owed live check on both bots ----
anchor(DECISIONS, DEC_HEAD, "decisions.md")
section = dec_entry(DECISIONS, DEC_HEAD)
print(f"== decisions.md carries #948's entry {DEC_HEAD!r} ==")
check("the #948 decisions.md entry is present", bool(section),
      f"no entry starting {DEC_HEAD!r} found in decisions.md")

print("== it names the owed live check on both bots under 'Not yet run on a cluster' ==")
check("the entry has a 'Not yet run on a cluster' section", OWED_LABEL in section)
owed = owed_block(section)
check("the owed section is found", bool(owed))
for name, literal in BOTS:
    check(f"the owed live check names {name}", literal in owed, f"the owed block does not hold {literal!r}")

print("== the decisions checks fail when the criterion stops holding ==")
anchor(section, OWED_LABEL, "decisions.md #948 entry")
for _, literal in BOTS:
    anchor(owed, literal, "decisions.md #948 owed block")
# Heading struck -> the whole entry is no longer found.
check("with the #948 heading struck, the entry is not found",
      dec_entry(DECISIONS.replace(DEC_HEAD, "## 2026-11-06 · #000 · struck", 1), DEC_HEAD) == "")
# Owed label struck -> the owed block is empty, so the bot checks have nothing to read.
check("with the 'Not yet run on a cluster' label struck, the owed block is empty",
      owed_block(section.replace(OWED_LABEL, "**Shipped.**", 1)) == "")
check("the owed block as written names all four bot literals", owed_names_all(owed))
for name, literal in BOTS:
    check(f"with {literal!r} struck from the owed block, the all-named check fails",
          not owed_names_all(owed.replace(literal, "", 1)))

# ---- PROGRESS.md: the #948 bullet that completes #922 ----
anchor(PROGRESS, PROG_HEAD, "PROGRESS.md")


def unreleased(text: str) -> str:
    """The [Unreleased] section: from its heading to the next level-2 heading, or EOF."""
    m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(1) if m else ""


def entry(text: str, head: str) -> str:
    """The one line starting `head` in [Unreleased], under a ### heading; empty when not exactly one."""
    section_ = unreleased(text)
    lines = [ln for ln in section_.splitlines() if ln.startswith(head)]
    if len(lines) != 1:
        return ""
    before = section_[: section_.index(lines[0])]
    return lines[0] if re.search(r"^### \S", before, flags=re.M) else ""


print(f"== PROGRESS.md carries #948's bullet {PROG_HEAD!r}, once, under a ### heading in [Unreleased] ==")
found = entry(PROGRESS, PROG_HEAD)
check("the #948 PROGRESS.md bullet is found", bool(found),
      f"no single line starting {PROG_HEAD!r} under a ### heading in [Unreleased]")

print("== the #948 PROGRESS.md bullet records that it completes #922 and points at its decisions.md entry ==")
check("it says it completes #922 in the repo", "completing #922 in the repo" in found)
check("it points at its decisions.md entry", "(decisions.md, 2026-11-06, #948)" in found)

print("== the PROGRESS check fails when the bullet stops holding ==")
line = found or PROG_HEAD
without = PROGRESS.replace(line + "\n", "", 1)
check("with the bullet removed, it is not found", entry(without, PROG_HEAD) == "")
moved = without + "\n## [0.0.0]\n\n### Added\n" + line + "\n"
check("moved out of [Unreleased], it is not found", entry(moved, PROG_HEAD) == "")
undated = re.sub(r"^- \(\d{4}-\d{2}-\d{2}\) ", "- ", PROG_HEAD)
anchor(PROGRESS, PROG_HEAD, "PROGRESS.md (for the undated mutation)")
check("without its date, it is not found",
      entry(PROGRESS.replace(line, undated + line[len(PROG_HEAD):], 1), PROG_HEAD) == "")
check("duplicated, it is not found",
      entry(PROGRESS.replace(line, line + "\n" + line, 1), PROG_HEAD) == "")
check("with no ### heading above it, it is not found",
      entry("# Changelog\n\n## [Unreleased]\n\n" + line + "\n", PROG_HEAD) == "")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("All #948 live-check-owed checks passed (decisions.md entry and PROGRESS.md #922 bullet).")
