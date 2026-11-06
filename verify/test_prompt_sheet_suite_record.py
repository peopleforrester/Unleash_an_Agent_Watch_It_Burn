# ABOUTME: Offline check that decisions.md records #952's suite result: `bash verify/run-e2e-tools.sh` finishing
# ABOUTME: green (offline suite and tools tier) with verify/test_kubecon_prompt_sheet_e2e.py recorded as passing (#975).
"""#952's criterion "`bash verify/run-tests.sh` and `bash verify/run-e2e-tools.sh` finish green (the prompt-sheet
test passing), with the result recorded in decisions.md" was held only in part (test review run 17827, #975).
verify/test_kubecon_prompt_sheet_e2e.py still checks every /kubecon prompt word for word and in order, so the
prompt-sheet test goes through the suite. But nothing read decisions.md, so the recorded suite result could be
dropped or go stale and no test would say so.

This reads decisions.md and fails unless one entry headed with #952 records the suite run whole:

  the command:  `bash verify/run-e2e-tools.sh` (which runs run-tests.sh first, so one green answers the Test
                command too);
  the offline:  the offline suite green — a `N tests ran` count and the `ALL OFFLINE RENDER-GATE TESTS GREEN` banner;
  the tier:     the tools tier green — a `N checks ran` count, a `NmNs` duration, the `ALL E2E TOOLS TIER CHECKS
                GREEN` banner, and `exit=0`;
  the sheet:    verify/test_kubecon_prompt_sheet_e2e.py named and recorded as having passed.

It then cuts the record it found in nine ways (each item above dropped or broken) and checks each one is refused, so
the checks above are shown to bite on the real entry and not only on a fixture. Before each cut it confirms the
anchor it replaces is in the record, and exits naming the anchor and the file when it is not, so a reworded record
reads as that and not as a broken check further on (Tests own their inputs, point 2). Nothing here reaches a
cluster, AWS or the network: it only reads decisions.md.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = REPO / "decisions.md"
ISSUE = "#952"

CMD = "bash verify/run-e2e-tools.sh"
OFFLINE_BANNER = "ALL OFFLINE RENDER-GATE TESTS GREEN"
TIER_BANNER = "ALL E2E TOOLS TIER CHECKS GREEN"
EXIT = "exit=0"
SHEET = "test_kubecon_prompt_sheet_e2e.py"

TESTS_RAN = re.compile(r"\b\d+ tests ran\b")
CHECKS_RAN = re.compile(r"\b\d+ checks ran\b")
DURATION = re.compile(r"\b\d+m\d+s\b")
SHEET_PASSED = re.compile(r"test_kubecon_prompt_sheet_e2e\.py`?\s*passed")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def entries(text: str) -> list[tuple[str, str]]:
    """decisions.md's entries as (heading, body), split at each `## ` line."""
    out, head, body = [], None, []
    for ln in text.splitlines():
        if ln.startswith("## "):
            if head is not None:
                out.append((head, "\n".join(body)))
            head, body = ln, []
        elif head is not None:
            body.append(ln)
    if head is not None:
        out.append((head, "\n".join(body)))
    return out


def record_problems(body: str) -> list[str]:
    """What a #952 entry leaves out of a record of the green suite run; empty when it records it whole.

    The body is flattened first: the tier's `in\\n51m34s` and `65 checks ran` phrases wrap across lines in the
    real entry, so a line-by-line read would miss them."""
    f = flat(body)
    left: list[str] = []
    if CMD not in f:
        left.append(f"the `{CMD}` command")
    if not TESTS_RAN.search(f):
        left.append("a `N tests ran` offline count")
    if OFFLINE_BANNER not in f:
        left.append(f"the `{OFFLINE_BANNER}` banner")
    if not CHECKS_RAN.search(f):
        left.append("a `N checks ran` tier count")
    if not DURATION.search(f):
        left.append("a `NmNs` run duration")
    if TIER_BANNER not in f:
        left.append(f"the `{TIER_BANNER}` banner")
    if EXIT not in f:
        left.append(f"`{EXIT}`")
    if not SHEET_PASSED.search(f):
        left.append(f"`{SHEET}` recorded as passing")
    return left


print(f"== a {ISSUE} entry in decisions.md records the green suite run and the prompt-sheet test passing ==")
text = DECISIONS.read_text(encoding="utf-8")
ours = [(h, b) for h, b in entries(text) if re.search(rf"{re.escape(ISSUE)}(?![\w'])", h)]
check(f"decisions.md has entries headed with {ISSUE}", bool(ours))

found = [(h, b, record_problems(b)) for h, b in ours]
whole = [(h, b) for h, b, p in found if not p]
if found:
    closest = min(found, key=lambda x: len(x[2]))
    check(f"one {ISSUE} entry records `{CMD}` finishing green (offline suite and tools tier) with `{SHEET}` passing",
          bool(whole),
          f"closest is {closest[0]!r}, which leaves out: {'; '.join(closest[2])}")

if whole:
    heading, body = whole[-1]
    print(f"  the record is {heading!r}")

    # ---- The record, cut: each cut must be refused, so the checks above bite on the real entry ----
    print("== the record found, cut in nine ways, is refused each time ==")
    cuts = {
        "no run-e2e-tools command": (CMD, "the offline suite"),
        "no tests-ran count": ("284 tests ran", "the offline suite"),
        "no offline banner": (OFFLINE_BANNER, "the offline suite is done"),
        "no checks-ran count": ("65 checks ran", "the tier is done"),
        "no duration": ("51m34s", "a while"),
        "no tier banner": (TIER_BANNER, "the tier finished"),
        "no exit=0": ("exit=0", "exit"),
        "prompt-sheet test not named": (SHEET, "a prompt test"),
        "prompt-sheet test not passed": (f"{SHEET}` passed", f"{SHEET}` ran"),
    }
    for name, (old, new) in cuts.items():
        if old not in body:
            print(f"{DECISIONS.name}: the record no longer holds {old!r}, which the cut '{name}' replaces; "
                  f"reword the cut with the record", file=sys.stderr)
            sys.exit(1)
        got = record_problems(body.replace(old, new))
        check(f"cut '{name}': the record is refused", bool(got))
        print(f"        ({'; '.join(got)})")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"All {ISSUE} suite-record checks passed.")
