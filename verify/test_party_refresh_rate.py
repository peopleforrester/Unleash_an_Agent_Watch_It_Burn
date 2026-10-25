# ABOUTME: Every party page moves at the same speed on a 60 Hz screen and a 144 Hz one, measured by running
# ABOUTME: each page's script in verify/party-refresh-rate.js. The structural checks are in test_party_apps.py.
# SUITE: e2e (needs node: the measurement runs each page's script)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why (#393). Positions advanced by a fixed `vx` per FRAME, so speed was a function of the viewer's refresh
# rate: two creatures that start together ended 236 px apart after three simulated seconds. After the fix,
# 1.3 px, which is integration error.
import pathlib, re, subprocess, sys, tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APPS = ("unicorn", "hedgehog", "wombat", "spider", "mantis-shrimp")
HARNESS = REPO / "verify/party-refresh-rate.js"
MAX_DRIFT_PX = 15.0
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def script(app):
    doc = yaml.safe_load((REPO / f"gitops/manifests/demo-app-{app}/configmap.yaml").read_text(encoding="utf-8"))
    return "\n".join(re.findall(r"<script>(.*?)</script>", next(iter(doc["data"].values())), re.S))


print("== the speed is the same on a 60 Hz screen and a 144 Hz one ==")
with tempfile.TemporaryDirectory(dir=REPO) as tmp:
    for app in APPS:
        f = pathlib.Path(tmp) / f"{app}.js"
        f.write_text(script(app), encoding="utf-8")
        out = subprocess.run(["node", str(HARNESS), str(f), app], capture_output=True, text=True)
        m = re.search(r"worst drift after 3s = ([\d.]+) px", out.stdout or "")
        if not m:
            check(f"{app}: the harness ran", False)
            print(f"        {(out.stdout or out.stderr).strip()[:200]}")
            continue
        drift = float(m.group(1))
        check(f"{app}: 3 seconds at 144 Hz lands within {MAX_DRIFT_PX:.0f} px of 60 Hz (measured {drift:.1f})",
              drift <= MAX_DRIFT_PX)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All party refresh-rate checks passed.")
