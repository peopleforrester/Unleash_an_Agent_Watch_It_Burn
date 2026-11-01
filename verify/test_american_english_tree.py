# ABOUTME: The shared American English checker passes on this repo's published paths (#745), run from the
# ABOUTME: llm-coding-workflow checkout under ~/repos, so it is in the E2E suite rather than the offline one.
# SUITE: e2e (needs ~/repos/workflow/llm-coding-workflow)
"""The live half of test_american_english_gate.py.

The offline half proves the repo opts in and the publish step runs the check before it replaces the Doc. This
runs that check: scripts/check_american_english.py --published from the repo root, as the publish step does.
A missing checkout is a failure with the path printed, never a skip.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
CHECKER = pathlib.Path.home() / "repos/workflow/llm-coding-workflow/scripts/check_american_english.py"

if not CHECKER.exists():
    print(f"  FAIL  the shared checker is present  ({CHECKER})")
    sys.exit(1)
r = subprocess.run([sys.executable, str(CHECKER), "--published"], cwd=REPO, capture_output=True, text=True)
if r.returncode != 0:
    print(f"  FAIL  check_american_english.py --published exits 0  ({(r.stdout + r.stderr).strip()[-300:]})")
    sys.exit(1)
print("  PASS  check_american_english.py --published exits 0")
print("American English check is green on the published paths.")
