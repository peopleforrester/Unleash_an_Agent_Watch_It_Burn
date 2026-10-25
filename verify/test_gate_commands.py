# ABOUTME: AGENTS.md declares the offline suite as the gate's Test command and the cluster-free tier as its E2E
# ABOUTME: command, never run-e2e.sh; the live suite is by hand, with the env vars it really requires (#543, #572).
"""Holds the gate split #543 made: main is gated on the offline suite, the live suite runs by hand.

Hecaton's promotion gate runs the `E2E command:` that AGENTS.md declares, in preference to the `Test command:`,
on a host with no attendee cluster, no AWS profile and none of the live suite's tools. While
`bash verify/run-e2e.sh` was declared there, every promotion failed with `E2E SUITE CANNOT RUN` and 58 merged
changes sat on staging. AGENTS.md now declares only `Test command: bash verify/run-tests.sh` and documents
run-e2e.sh as the by-hand check during a cluster build (decisions.md, 2026-10-24, #543).

The declared lines are read the way the gate reads them: at the start of a line, optionally a list item or
bold, the label in any case, a colon, then the command in single backticks. The first such line wins. A
mention of "E2E command:" inside a sentence declares nothing, so the by-hand paragraph may name it.

The #543 follow-up, #572, declared the cluster-free tier as the E2E command: `bash verify/run-e2e-tools.sh`,
which needs pinned tools and network but no cluster or AWS (verify/test_e2e_tools_tier.py holds the tier
itself). What this holds is that line, and that it never names run-e2e.sh, which cannot pass on the gate host.
The by-hand paragraph has to name the env vars run-e2e.sh's prerequisite check actually requires, so the two
cannot drift apart.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
AGENTS = REPO / "AGENTS.md"
RUN_E2E = REPO / "verify" / "run-e2e.sh"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def declared(text: str, label: str) -> str | None:
    """The command declared on a `<label>: `cmd`` line, as hecaton's gate reads it; the first line wins."""
    pattern = rf"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?{re.escape(label)}:(?:\*\*)?[ \t]*`([^`\n]+)`"
    m = re.search(pattern, text, re.M | re.I)
    return (m.group(1).strip() or None) if m else None


agents = AGENTS.read_text(encoding="utf-8")
run_e2e = RUN_E2E.read_text(encoding="utf-8")

print("== the gate's Test command is the offline suite ==")
test_cmd = declared(agents, "Test command")
check("AGENTS.md declares a Test command", test_cmd is not None)
check(f"the Test command is `bash verify/run-tests.sh` (got {test_cmd!r})", test_cmd == "bash verify/run-tests.sh")
check("verify/run-tests.sh exists", (REPO / "verify" / "run-tests.sh").is_file())

print("== the gate's E2E command is the cluster-free tier, never the live suite ==")
e2e_cmd = declared(agents, "E2E command")
check(f"no declared E2E command runs run-e2e.sh (got {e2e_cmd!r})", e2e_cmd is None or "run-e2e.sh" not in e2e_cmd)
check(f"the E2E command is `bash verify/run-e2e-tools.sh` (got {e2e_cmd!r})", e2e_cmd == "bash verify/run-e2e-tools.sh")
check("verify/run-e2e-tools.sh exists", (REPO / "verify" / "run-e2e-tools.sh").is_file())

print("== the live suite is documented as by hand, with what it needs ==")
paras = [re.sub(r"\s+", " ", p) for p in re.split(r"\n\s*\n", agents)]
flat = next((p for p in paras if "`bash verify/run-e2e.sh`" in p and "by hand" in p), "")
check("AGENTS.md has a paragraph naming `bash verify/run-e2e.sh` as by hand", bool(flat))
check("it says the suite is run by hand during a cluster build", "run by hand during a cluster build" in flat)
check("it says the suite is not declared as the gate's E2E command", "not declared" in flat)
check("it names #543", "#543" in flat)
required = sorted(set(re.findall(r'-[nz] "\$\{([A-Z_]+):-\}"', run_e2e)))
check(f"run-e2e.sh's prerequisite check requires env vars (found {required})",
      {"CONTEXT", "IAM_PIPELINE_PROFILE", "IAM_PIPELINE_REGION"} <= set(required))
for var in required:
    check(f"the paragraph names {var}, which run-e2e.sh requires", var in flat)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All gate command checks passed.")
