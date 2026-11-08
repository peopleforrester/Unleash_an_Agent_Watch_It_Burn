# ABOUTME: CLAUDE.md's "Dispatched runs" point 6 says a run tests only what it changed: prose runs the prose gate and
# ABOUTME: its reading tests and never the tools tier, and the full tier is the promotion gate's (#1191). Offline.
"""Holds #1191's rule in CLAUDE.md, so a later edit cannot drop it without this failing.

Michael, 2026-11-08: "it still sounds like we're running the end-to-end tools way too fucking much for reasons that
aren't fucking clear, for fucking file edits." Point 6 of "Dispatched runs" says what a run tests. This test holds:

  1. Point 6 is in the "Dispatched runs" section, and carries the scoped command form (`HECATON_BASE_SHA`).
  2. Its three rules: a prose change never runs `run-e2e-tools.sh`; a code change runs the tests that read the changed
     files; the full tools tier runs only on FULL and at release points, never on every promotion to main.
  3. It says how to run one tier test alone.
  4. Point 1 no longer tells every run to run both suites whole.

Each cut on CLAUDE.md checks its literal first and exits naming it when it is gone ("Tests own their inputs"), and
each check is run again on a copy with its sentence removed, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CLAUDE = REPO / "CLAUDE.md"
SECTION, NEXT = "## Dispatched runs (hecaton)", "## Tests own their inputs"
POINT6 = "6. **A run tests what it changed, and never the whole tools tier.**"

RULES = {
    "the scoped command form": 'HECATON_BASE_SHA="$(git merge-base HEAD origin/staging)" bash verify/<script>',
    "a prose change never runs the tools tier": (
        "A change to .md, .html or other prose files runs the prose gate and the offline tests that read those files, "
        "and never `run-e2e-tools.sh`."),
    "a code change runs the tests that read it": "A code change runs the tests that read the changed files",
    "the full tier runs only on FULL and at release points": (
        "The full tools tier runs only when `verify/scope_tests.py` returns FULL for the change, and at release points"),
    "never on every promotion to main": "never on every promotion to main and never inside a run.",
    "one tier test alone": "To run one tier test alone, change it and run the scoped `run-e2e-tools.sh`",
}
OLD_POINT1 = "run `bash verify/run-tests.sh` and `bash verify/run-e2e-tools.sh`, run the live check"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def need(text: str, literal: str) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {CLAUDE}; the #1191 checks cut on it")


def flat(text: str) -> str:
    return " ".join(text.split())


def problems(doc: str) -> dict[str, list[str]]:
    need(doc, SECTION)
    need(doc, NEXT)
    section = doc.split(SECTION, 1)[1].split(NEXT, 1)[0]
    out: dict[str, list[str]] = {}
    out["point 6 is in the Dispatched runs section"] = [] if POINT6 in section else [POINT6]
    point = flat(section.split(POINT6, 1)[1]) if POINT6 in section else ""
    for label, sentence in RULES.items():
        out[f"point 6 states: {label}"] = [] if flat(sentence) in point else [sentence]
    out["point 1 no longer runs both suites whole"] = [OLD_POINT1] if OLD_POINT1 in flat(section) else []
    return out


doc = CLAUDE.read_text(encoding="utf-8")
for name, errs in problems(doc).items():
    check(name, not errs, "; ".join(errs))

print("== each check can fail ==")
for label, sentence in RULES.items():
    first_line = sentence.split("\n")[0][:40]
    raw = next((ln for ln in doc.splitlines() if first_line[:30] in ln), None)
    if raw is None:
        sys.exit(f"ANCHOR MISSING: no CLAUDE.md line holds {first_line[:30]!r}; the self-check edits on it")
    broken = doc.replace(raw, "   - (removed)", 1)
    check(f"dropping '{label}' fails its check", bool(problems(broken)[f"point 6 states: {label}"]))
need(doc, "run the tests point 6 names, run the live check")
put_back = doc.replace("run the tests point 6 names, run the live check", OLD_POINT1, 1)
check("putting point 1's old run-both-suites wording back fails", bool(problems(put_back)["point 1 no longer runs both suites whole"]))

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nCLAUDE.md's point 6 holds #1191: a run tests what it changed, and the full tools tier runs on FULL and at release points")
