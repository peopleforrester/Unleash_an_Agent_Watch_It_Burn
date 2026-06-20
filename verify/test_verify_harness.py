# ABOUTME: Render-gate check for P6: beat-cost is wired into run-all.sh and every verify script is
# ABOUTME: syntactically valid (bash -n). Live assertions run on a cluster; this is the offline gate.
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
VERIFY = REPO / "verify"
runall = (VERIFY / "run-all.sh").read_text()

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


check("run-all.sh declares BEAT_COST", "BEAT_COST" in runall)
check("run-all.sh runs beat-cost in ORDER", "beat-cost" in runall)
check("beat-cost.sh exists and is executable", (VERIFY / "beat-cost.sh").stat().st_mode & 0o111 != 0)
for sh in sorted(VERIFY.glob("*.sh")):
    ok = subprocess.run(["bash", "-n", str(sh)], capture_output=True).returncode == 0
    check(f"bash -n clean: {sh.name}", ok)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll verify-harness (P6) checks passed.")
