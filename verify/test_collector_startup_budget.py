# ABOUTME: The collector's probes leave it time to parse its own config: the OTTL parse costs the square of each
# ABOUTME: statement's length, and #1316's 108 KB statements crashlooped the DaemonSet under the liveness probe (#1326).
"""Holds each collector profile's startup budget to what its rendered config costs to build.

What happened (#1326, 2026-11-11). #1316 put the code-of-conduct pattern into transform/coc_mask as four OTTL
statements of 108,437 characters. The pinned otelcol-contrib 0.160.0 parses an OTTL string in time that grows with
the square of its length: `validate` on a single `set(attributes["x"], "<n x a>")` cost 0.54 s of CPU at n = 13,500,
1.41 s at 27,000, 4.51 s at 54,000 and 15.45 s at 108,000. The whole live config cost about 46 s of CPU, against 3 s
before #1316. On watch-it-burn-community the collector's own image ran `validate` on the live relay.yaml in 110 s
at the DaemonSet's 500m limit and 30 s at 2 CPUs. The liveness probe, the chart's with Kubernetes' defaults (every
10 s, 3 failures, no delay), killed the container at about 30 s before it logged a line, so the DaemonSet
crashlooped and the cluster shipped no traces.

The check: for each profile's rendered config (collector_render, the Datadog overlay included), estimate the CPU the
build costs as BASE_CPU_S plus K_CPU_S_PER_CHAR2 times the sum of the squares of every processor string's length,
divide by the CPU limit, and require the time the probes allow before a kill to be at least SAFETY times that. K is
the 108,000-character measurement above, which is above what the real statements cost (about 11.5 s each), and
SAFETY covers the in-cluster time running about 1.2 to 1.3 times CPU over limit. A mutant without the startup probe
and at the old 500m limit must fail, so the check would have caught #1326.

Usage: python3 verify/test_collector_startup_budget.py
"""
from __future__ import annotations

import copy
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from collector_render import PROFILE_APP, collector_config, helm_values  # noqa: E402

K_CPU_S_PER_CHAR2 = 15.45 / 108_000 ** 2   # otelcol-contrib 0.160.0, a 108,000-character OTTL literal, 2026-11-11
BASE_CPU_S = 3.0                           # the whole pre-#1316 config's `validate`, which these squares leave out
SAFETY = 2.0
# Kubernetes' probe defaults, which the chart's livenessProbe (httpGet only) takes.
PROBE_DEFAULTS = {"initialDelaySeconds": 0, "periodSeconds": 10, "failureThreshold": 3}
COC_STATEMENT_FLOOR = 100_000  # #1316's statements; a config below this is not the one #1326 measured

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in strings(v)]
    return []


def cores(cpu) -> float:
    s = str(cpu)
    return int(s[:-1]) / 1000 if s.endswith("m") else float(s)


def probe_budget_s(vals: dict) -> float:
    """Seconds from the container's start to the first kill the probes can order."""
    probe = vals.get("startupProbe") or vals.get("livenessProbe") or {}
    p = {k: probe.get(k, d) for k, d in PROBE_DEFAULTS.items()}
    return p["initialDelaySeconds"] + p["periodSeconds"] * p["failureThreshold"]


def build_cpu_s(config: dict) -> tuple[float, int]:
    texts = strings(config.get("processors", {}))
    return BASE_CPU_S + K_CPU_S_PER_CHAR2 * sum(len(t) ** 2 for t in texts), max(map(len, texts))


def needed_s(vals: dict, config: dict) -> float:
    return SAFETY * build_cpu_s(config)[0] / cores(vals["resources"]["limits"]["cpu"])


for profile in PROFILE_APP:
    vals = helm_values(profile)
    config = collector_config(profile, datadog_secret=True)
    cpu_s, longest = build_cpu_s(config)
    need, budget = needed_s(vals, config), probe_budget_s(vals)
    print(f"{profile}: longest processor string {longest:,} chars, estimated build {cpu_s:.0f} s of CPU, "
          f"limit {vals['resources']['limits']['cpu']}, needs {need:.0f} s, probes allow {budget:.0f} s")
    check(f"{profile}: the config holds #1316's long statements (longest {longest:,} >= {COC_STATEMENT_FLOOR:,})",
          longest >= COC_STATEMENT_FLOOR, "the measurement this test rests on is of #1316's statements")
    probe = vals.get("startupProbe") or {}
    check(f"{profile}: a startupProbe on the health_check port holds liveness off while the config builds",
          probe.get("httpGet", {}).get("port") == 13133, f"startupProbe is {probe!r}")
    check(f"{profile}: the probes allow {budget:.0f} s, at least {SAFETY:g} times the build at the CPU limit "
          f"({need:.0f} s)", budget >= need,
          "raise startupProbe.failureThreshold or the CPU limit, or shorten the OTTL statements")

# The state #1326 found on the cluster: no startupProbe and a 500m limit. The check must refuse it.
vals = copy.deepcopy(helm_values("burn"))
vals.pop("startupProbe", None)
vals["resources"]["limits"]["cpu"] = "500m"
config = collector_config("burn", datadog_secret=True)
need, budget = needed_s(vals, config), probe_budget_s(vals)
check(f"mutant (no startupProbe, 500m, as on 2026-11-11): the probes' {budget:.0f} s fall short of {need:.0f} s",
      budget < need, "the budget check would not have caught #1326's crashloop")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every collector profile's probes leave time to parse its config at its CPU limit.")
