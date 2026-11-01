# ABOUTME: Live half of the American English gate (#745): the shared checker passes on the published design-doc
# ABOUTME: paths .american-english lists. Needs ~/repos/workflow/llm-coding-workflow, a private repo.
# SUITE: e2e (needs ~/repos/workflow/llm-coding-workflow, which only a machine with Michael's repos has)
#
# The offline half (test_american_english_gate.py) proves the opt-in lists the published docs and that
# compile-design-doc.py --publish runs the checker before the Doc is replaced. This runs the checker itself,
# the same file the publish step runs, so a British form in a published doc turns this red before a publish
# does. It is not in the `# E2E TIER: tools` tier: the gate host has no ~/repos, and the repo is private, so
# nothing can fetch it there. A missing checker is a failure with its path printed, never a skip.
from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
CHECKER = pathlib.Path.home() / "repos/workflow/llm-coding-workflow/scripts/check_american_english.py"

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


print("== the check passes on the current tree ==")
if not CHECKER.exists():
    check("the shared checker is present", False, str(CHECKER))
else:
    r = subprocess.run([sys.executable, str(CHECKER), "--published"], cwd=REPO, capture_output=True, text=True)
    check("check_american_english.py --published exits 0", r.returncode == 0,
          (r.stdout + r.stderr).strip()[-300:])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The published design-doc paths pass the American English check.")
