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

# The offline runner must DISCOVER its tests. It carried a hand-written list of filenames until a commit
# removing one test deleted the whole `for` line with it; the suite then failed to parse for four days,
# undetected, because the only thing that reports the suite broken is the suite. A list also omits every
# test written after it, which is the quieter half of the same failure.
runtests = (VERIFY / "run-tests.sh").read_text()
check("run-tests.sh globs for its tests", 'test_*.py' in runtests and 'test_*.sh' in runtests)
check("run-tests.sh names no individual test", "test_fleet_contract.py" not in runtests)
check("run-tests.sh fails when it finds nothing to run", "NO TESTS FOUND" in runtests)
# Every test in the directory has to be reachable by that glob, or it is dead weight nothing runs.
strays = [p.name for p in VERIFY.glob("test_*") if p.suffix not in (".py", ".sh")]
check(f"no test is unreachable by the runner's glob ({', '.join(strays) or 'none'})", not strays)
for sh in sorted(VERIFY.glob("*.sh")):
    ok = subprocess.run(["bash", "-n", str(sh)], capture_output=True).returncode == 0
    check(f"bash -n clean: {sh.name}", ok)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll verify-harness (P6) checks passed.")
