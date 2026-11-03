# ABOUTME: PROGRESS.md carries #764's changelog entry for the Challenge 3 plain question (#808): a dated bullet
# ABOUTME: under [Unreleased] that names the probe, the question, the stage name, the removed ask and the #803 wait.
"""Pins #764's "Update PROGRESS.md with a changelog entry" criterion, which no test checked (#808).

The entry is the 2026-11-02 bullet for verify/kubecon_probe.py's Challenge 3 beat. The checks read the facts the
entry records as literal text, not from kubecon_probe.py's constants: a changelog line is history, and a later
change to the stage prompt gets its own entry rather than rewriting this one. The finder is also run on
PROGRESS.md with the entry taken out, moved below [Unreleased] or stripped of its date, so a check that could
never fail would show up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PROGRESS = (REPO / "PROGRESS.md").read_text(encoding="utf-8")
ENTRY_HEAD = "- (2026-11-02) #764:"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def unreleased(text: str) -> str:
    """The [Unreleased] section: from its heading to the next level-2 heading, or the end of the file."""
    m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(1) if m else ""


def entry(text: str) -> str:
    """The one #764 bullet dated 2026-11-02 in [Unreleased], under a ### heading; empty when there is none."""
    section = unreleased(text)
    lines = [ln for ln in section.splitlines() if ln.startswith(ENTRY_HEAD)]
    if len(lines) != 1:
        return ""
    before = section[: section.index(lines[0])]
    return lines[0] if re.search(r"^### \S", before, flags=re.M) else ""


ENTRY = entry(PROGRESS)

print("== PROGRESS.md is a Keep a Changelog file with an [Unreleased] section ==")
check("PROGRESS.md opens with the Changelog title", PROGRESS.startswith("# Changelog\n"))
check("it has an [Unreleased] section", bool(unreleased(PROGRESS).strip()))

print("== #764's 2026-11-02 entry is there, once, as a dated bullet under a ### heading in [Unreleased] ==")
check("the entry is found", bool(ENTRY), f"no single line starting {ENTRY_HEAD!r} under a ### heading in [Unreleased]")

print("== the entry records what #764's Challenge 3 change did ==")
check("it names the probe it changed", "verify/kubecon_probe.py" in ENTRY and "Challenge 3" in ENTRY)
check("it quotes the plain question the room asks",
      "\"What's the status of my support ticket HC-666?\"" in ENTRY)
check("it says the stage name rides as the /chat body's witch, as the chat page sends it",
      "Agatha the Banshee" in ENTRY and "`witch`" in ENTRY and "/chat" in ENTRY)
check("it names the stage traces' Challenge 3 seeds", "stage_traces.py" in ENTRY)
check("it records the removed copied ask", "Removed ticket_site.ask_for()" in ENTRY)
check("it names the presenter-side pages that changed", "/kubecon" in ENTRY and "run-of-show" in ENTRY)
check("it says the live probe pass waits on the guard-proxy repin (#803) and #764 stays open",
      "#803" in ENTRY and "#764 stays open" in ENTRY)

print("== the finder fails when the criterion stops holding ==")
# An empty ENTRY has already failed above; these still run so the suite never branches on the result.
check("with the entry removed, it is not found", entry(PROGRESS.replace(ENTRY + "\n", "")) == "")
_moved = PROGRESS.replace(ENTRY + "\n", "") + "\n## [0.0.0]\n\n### Added\n" + ENTRY + "\n"
check("moved out of [Unreleased], it is not found", entry(_moved) == "")
check("without its date, it is not found", entry(PROGRESS.replace(ENTRY, ENTRY.replace("(2026-11-02) ", ""))) == "")
check("duplicated, it is not found", entry(PROGRESS.replace(ENTRY, ENTRY + "\n" + ENTRY)) == "")
check("with no ### heading above it, it is not found",
      entry("# Changelog\n\n## [Unreleased]\n\n" + ENTRY + "\n") == "")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("All #764 PROGRESS.md entry checks passed.")
