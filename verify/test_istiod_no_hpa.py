# ABOUTME: istiod renders no HorizontalPodAutoscaler: no profile installs metrics-server, so the HPA never reads CPU,
# ABOUTME: Argo CD reports istiod Degraded on every cluster, and fleet.sh converge counts it as not converged.
"""Found 2026-10-31 building the #643 standbys: watch-it-burn-private-b01 did not converge after three rounds, 36 of 37
apps healthy, istiod Degraded with ScalingActive=False FailedGetResourceMetric. watch-it-burn-private read the same.
The istiod pod was running; only its autoscaler had no metrics. One replica is what the chart's autoscaleMin gave."""
from __future__ import annotations

import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
APP = next(d for d in yaml.safe_load_all((REPO / "gitops/bootstrap/apps/istio.yaml").read_text(encoding="utf-8"))
           if d and d.get("metadata", {}).get("name") == "istiod")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


values = APP["spec"]["source"]["helm"]["valuesObject"]
check("istiod's values turn the chart's autoscaler off", values.get("pilot", {}).get("autoscaleEnabled") is False,
      str(values.get("pilot", {}).get("autoscaleEnabled")))
# What would install it: an EKS addon in the Terraform, or a Helm chart in an Argo CD app (infra/SIZING.md says neither).
listed = subprocess.run(["git", "-C", str(REPO), "grep", "-lE", r'addon_name\s*=\s*"metrics-server"|chart:\s*metrics-server',
                         "--", "infra/*.tf", "infra/**/*.tf", "gitops"], capture_output=True, text=True).stdout.split()
check("no profile installs metrics-server, so an autoscaler would have nothing to read", not listed, str(listed))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("istiod has no autoscaler to report it Degraded.")
