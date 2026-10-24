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

# The light and heavy suites split by a `# SUITE: e2e` line in the test, never by what the machine has.
# A runner that turned a missing tool or credential into a skip went green on machines that ran nothing.
rune2e = (VERIFY / "run-e2e.sh").read_text()
check("run-tests.sh has no skip outcome", "skipped" not in runtests)
check("run-tests.sh hands `# SUITE: e2e` tests to run-e2e.sh", "# SUITE: e2e" in runtests)
check("run-e2e.sh globs for the same marker", "# SUITE: e2e" in rune2e and 'test_*.py' in rune2e and 'test_*.sh' in rune2e)
check("run-e2e.sh has no skip outcome", "skipped" not in rune2e)
check("run-e2e.sh runs the live beat harness", "run-all.sh" in rune2e)
check("run-e2e.sh requires an explicit CONTEXT and passes it to kubectl",
      "${CONTEXT:-}" in rune2e and 'kubectl --context "${CONTEXT}"' in rune2e)
# The Backstage Playwright run (#440): yarn is the pinned yarn 4 through corepack, not whatever global
# yarn a machine has, and the browser the config launches is the one the script installs. The config's
# default channel, 'chrome', wants Google Chrome at /opt/google/chrome, which `playwright install chromium`
# never provides, so the suite failed on every machine without a system Chrome.
check("run-e2e.sh runs Backstage's yarn through corepack",
      "corepack yarn test:e2e" in rune2e and "\n        && yarn " not in rune2e)
check("run-e2e.sh requires Node 24", '!= "24"' in rune2e)
pwconfig = (REPO / "images/watch-it-burn-backstage/playwright.config.ts").read_text()
check("playwright.config.ts launches the Chromium run-e2e.sh installs",
      "playwright install chromium" in rune2e and "generateProjects({ channel: 'chromium' })" in pwconfig)
e2e = sorted(p.name for p in VERIFY.glob("test_*") if "\n# SUITE: e2e" in p.read_text())
check(f"the render and live checks are in the E2E suite ({', '.join(e2e)})",
      {"test_ai_layer_rollout.py", "test_enforce_floor.py", "test_service_naming_render.py",
       "test_datadog_service_map.py", "test_party_refresh_rate.py"} <= set(e2e))
# Anything else that shells out to kubectl, helm or node would fail the light suite on a machine without them.
renderers = [p.name for p in VERIFY.glob("test_*.py") if p.name not in e2e
             and any(f'["{t}",' in p.read_text() for t in ("kubectl", "helm", "node"))]
check(f"no light-suite test runs kubectl, helm or node ({', '.join(renderers) or 'none'})", not renderers)
for sh in sorted(VERIFY.glob("*.sh")):
    ok = subprocess.run(["bash", "-n", str(sh)], capture_output=True).returncode == 0
    check(f"bash -n clean: {sh.name}", ok)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll verify-harness (P6) checks passed.")
