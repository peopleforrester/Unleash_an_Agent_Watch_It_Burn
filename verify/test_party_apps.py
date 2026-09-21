# ABOUTME: Render gate for the five party pages: each creature is its own animal, and every page moves
# ABOUTME: at the same speed on a 60 Hz screen and a 144 Hz one.
"""Why this exists (#393).

Two defects, both measured rather than guessed.

**The unicorn page drew a hedgehog.** Normalising the name token out, `demo-app-unicorn` and
`demo-app-hedgehog` were byte-identical: one template, specialised for wombat, spider and mantis
shrimp, and left unspecialised for the other two. Both drew a round brown body with eight quills, so
the unicorn app rendered a hedgehog and the hedgehog app rendered the same hedgehog.

**Nothing was scaled by elapsed time.** Positions advanced by a fixed `vx` per FRAME, so speed was a
function of the viewer's refresh rate: 2x on a 120 Hz laptop, 2.4x on a 144 Hz panel. Measured with
`verify/party-refresh-rate.js`, two creatures that start together ended 236 px apart after three
simulated seconds. After the fix, 1.3 px, which is integration error.

The refresh-rate half needs node. When node is absent the structural checks still run and the
measurement is reported as skipped, rather than the whole file quietly passing.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APPS = ("unicorn", "hedgehog", "wombat", "spider", "mantis-shrimp")
HARNESS = REPO / "verify/party-refresh-rate.js"
MAX_DRIFT_PX = 15.0

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def page(app: str) -> str:
    doc = yaml.safe_load((REPO / f"gitops/manifests/demo-app-{app}/configmap.yaml").read_text(encoding="utf-8"))
    return next(iter(doc["data"].values()))


def script(app: str) -> str:
    return "\n".join(re.findall(r"<script>(.*?)</script>", page(app), re.S))


pages = {a: page(a) for a in APPS}
scripts = {a: script(a) for a in APPS}

print("== every page advances by elapsed time, not by frame ==")
for app in APPS:
    js = scripts[app]
    check(f"{app}: declares a delta-time factor", re.search(r"let dt=1,lastT=0;", js) is not None)
    check(f"{app}: computes it from a timestamp, clamped",
          "performance.now()" in js and "Math.min(3,Math.max(0.25," in js)
    check(f"{app}: the loop takes the timestamp the browser hands it",
          re.search(r"function loop\(ts\)", js) is not None)
    # The exact sites that made speed a function of refresh rate.
    check(f"{app}: no unscaled position integration", "this.x+=this.vx;" not in js)
    check(f"{app}: no unscaled velocity damping", "this.vx*=0.98;" not in js and "this.vx*=0.99;" not in js)
    check(f"{app}: frame counter advances by dt (it drives the wander phase)", "frame+=dt;" in js)

print("== each page draws its own animal ==")
def normalised(app: str) -> str:
    return re.sub(r"(?i)unicorn|hedgehog|wombat|spider|mantis[- ]?shrimp", "CREATURE", pages[app])

for a in APPS:
    for b in APPS:
        if a >= b:
            continue
        check(f"{a} and {b} are not the same page with the name swapped", normalised(a) != normalised(b))

check("the unicorn has a horn", "horn" in scripts["unicorn"].lower())
check("and a mane rather than quills", "manePhase" in scripts["unicorn"] and "spikePhase" not in scripts["unicorn"])
check("the hedgehog keeps its spikes", "spikePhase" in scripts["hedgehog"])
check("the unicorn is not wearing the hedgehog's browns",
      "#8B4513" not in scripts["unicorn"] and "#8B4513" in scripts["hedgehog"])

print("== the speed is the same on a 60 Hz screen and a 144 Hz one ==")
if shutil.which("node") is None:
    print("  skipped (needs node): refresh-rate measurement")
else:
    with tempfile.TemporaryDirectory(dir=REPO) as tmp:
        for app in APPS:
            f = pathlib.Path(tmp) / f"{app}.js"
            f.write_text(scripts[app], encoding="utf-8")
            out = subprocess.run(["node", str(HARNESS), str(f), app], capture_output=True, text=True)
            m = re.search(r"worst drift after 3s = ([\d.]+) px", out.stdout or "")
            if not m:
                check(f"{app}: the harness ran", False)
                print(f"        {(out.stdout or out.stderr).strip()[:200]}")
                continue
            drift = float(m.group(1))
            check(f"{app}: 3 seconds at 144 Hz lands within {MAX_DRIFT_PX:.0f} px of 60 Hz (measured {drift:.1f})",
                  drift <= MAX_DRIFT_PX)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll party-app checks passed.")
