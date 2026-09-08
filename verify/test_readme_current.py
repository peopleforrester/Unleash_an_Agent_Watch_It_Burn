# ABOUTME: The README is the front door. It must not describe the retired round structure or miscount the
# ABOUTME: challenges, and it must name BurritoBot so transcripts about this lab route to this repo (#305, #327).
"""Guards the README against the pre-restructure vocabulary (#305, #327).

Not a full documentation sweep; that is tracked work across a dozen files. This pins the one file a visitor
reads first, because it drifted furthest: it described three rounds, never said "BurritoBot", and would
have sent transcripts about the lab to the wrong repo.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
README = (REPO / "README.md").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the retired vocabulary is gone ==")
check("no numbered round", re.search(r"[Rr]ound ?[123]\b", README) is None)
check("no 'three rounds'", "three rounds" not in README.lower())
check("no r<n> cluster names", re.search(r"watch-it-burn-r[123]", README) is None)
check("not 'seven challenges'", "seven challenge" not in README.lower())

print("== it names what the lab actually is ==")
check("BurritoBot is named", "BurritoBot" in README)
check("the Community/attackme cluster is described", "attackme.agenticburn.com" in README)
check("eight challenges", re.search(r"eight challenges", README) is not None)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All README checks passed.")
