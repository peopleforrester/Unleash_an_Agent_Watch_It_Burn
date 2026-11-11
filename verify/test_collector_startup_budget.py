# ABOUTME: The collector's probes leave it time to parse its own config, which builds in under 10 s of CPU: the OTTL parse
# ABOUTME: costs the square of each statement's length, and #1316's 108 KB statements crashlooped the DaemonSet (#1326).
"""Holds each collector profile's startup budget to what its rendered config costs to build.

What happened (#1326, 2026-11-11). #1316 put the code-of-conduct pattern into transform/coc_mask as four OTTL
statements of 108,437 characters. The pinned otelcol-contrib 0.160.0 parses an OTTL string in time that grows with
the square of its length: `validate` on a single `set(attributes["x"], "<n x a>")` cost 0.54 s of CPU at n = 13,500,
1.41 s at 27,000, 4.51 s at 54,000 and 15.45 s at 108,000. The whole live config cost about 46 s of CPU, against 3 s
before #1316. On watch-it-burn-community the collector's own image ran `validate` on the live relay.yaml in 110 s
at the DaemonSet's 500m limit and 30 s at 2 CPUs. The liveness probe, the chart's with Kubernetes' defaults (every
10 s, 3 failures, no delay), killed the container at about 30 s before it logged a line, so the DaemonSet
crashlooped and the cluster shipped no traces.

#1328 cut the pattern into floor.portable_patterns(), 36 patterns of at most 4,000 characters, each applied twice in
each context (the second pass where the first masked something): 144 statements of at most 4,880 characters.
`validate` on each profile's rendered config then took 6.1 to 6.4 s of CPU with the pinned binary, Datadog overlay
included, and 0.7 s with the mask left out (decisions.md, #1328).

The checks: for each profile's rendered config (collector_render, the Datadog overlay included), estimate the CPU the
build costs as BASE_CPU_S plus K_CPU_S_PER_CHAR times the length of every processor string plus K_CPU_S_PER_CHAR2
times the sum of their squares. It must be under BUILD_LIMIT_S (#1328), and the time the probes allow before a kill
must be at least SAFETY times it at the CPU limit. The constants are fit to #1328's measurements of the cut at 2,000
to 8,000 characters and rounded up: the estimate is about 6.8 s for the cut config, against the 6.1 to 6.4 s
measured, and 59 s for #1316's, against 45 s. SAFETY covers the in-cluster time running about 1.2 to 1.3 times CPU
over limit. Mutants with #1316's single statements must fail: at the old 500m limit without the startup probe (so the
check would have caught #1326), and the build limit itself.

The ConfigMaps (#1332). Written in values.yaml's `config`, transform/coc_mask put each pattern into the chart's relay
ConfigMap four times, since helm writes the span-event context's alias out in full, and the relay reached about
885 KB, 84% of the 1,048,576 bytes a ConfigMap's data may hold. The mask is now the otel-collector-coc-mask ConfigMap,
loaded with a further --config (collector_render.py), which goes to the cluster as written, so each pattern sits in it
twice. Each profile's relay config, as helm writes it (every alias written out, no line wrapped), and the coc-mask
ConfigMap's file must each stay under HEADROOM of a ConfigMap, so the code-of-conduct list can grow by a third or more
before either nears the cap. A mutant with the mask written back into the relay config must fail that check.

Usage: python3 verify/test_collector_startup_budget.py
"""
from __future__ import annotations

import copy
import pathlib
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from collector_render import (COC_MASK_KEY, COC_MASK_MANIFEST, PROFILE_APP, coc_mask_configmap,  # noqa: E402
                              collector_config, config_paths, helm_values)

# otelcol-contrib 0.160.0, fit to `validate` on the mask cut at 2,000, 3,000, 5,000 and 8,000 characters and on #1316's
# single form (#1328, 2026-11-11), rounded up: 1.06e-9 s a character squared between the cuts, 0.93e-9 on #1316's.
K_CPU_S_PER_CHAR2 = 1.2e-9
K_CPU_S_PER_CHAR = 3e-6                    # the parse's part that grows with the length, the where clauses' among it
BASE_CPU_S = 1.0                           # burn's config with the Datadog overlay and no mask: 0.7 s
BUILD_LIMIT_S = 10.0                       # #1328's criterion: the config builds in under 10 s of CPU
CONFIGMAP_BYTES = 1_048_576                # what a ConfigMap's data may hold
HEADROOM = 0.75                            # #1332's criterion: each ConfigMap under 75% of that
SAFETY = 2.0
# Kubernetes' probe defaults, which the chart's livenessProbe (httpGet only) takes.
PROBE_DEFAULTS = {"initialDelaySeconds": 0, "periodSeconds": 10, "failureThreshold": 3}

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
    return (BASE_CPU_S + K_CPU_S_PER_CHAR * sum(map(len, texts)) + K_CPU_S_PER_CHAR2 * sum(len(t) ** 2 for t in texts),
            max(map(len, texts)))


def needed_s(vals: dict, config: dict) -> float:
    return SAFETY * build_cpu_s(config)[0] / cores(vals["resources"]["limits"]["cpu"])


class _Expanded(yaml.SafeDumper):
    """Writes an object as often as the config holds it, as helm's toYaml does, where PyYAML would write an alias."""

    def ignore_aliases(self, data) -> bool:
        return True


def relay_bytes(config: dict) -> int:
    return len(yaml.dump(config, Dumper=_Expanded, sort_keys=False, width=10 ** 9).encode())


MASK = "transform/coc_mask"
SINGLE_STATEMENT_CHARS = 108_437  # #1316's replace statement, as #1326 read it in the live relay.yaml


def single_form(config: dict) -> dict:
    """The config with transform/coc_mask's statements as #1316 had them, by length, which is all the estimate reads:
    the cache and keep statements, the 108,437-character replace statement twice, the merge, in each context."""
    mutant = copy.deepcopy(config)
    for group in mutant["processors"][MASK]["trace_statements"]:
        kept = [st for st in group["statements"] if not st.startswith("replace_all_patterns(")]
        group["statements"] = kept[:2] + ["x" * SINGLE_STATEMENT_CHARS] * 2 + kept[2:]
    return mutant


for profile in PROFILE_APP:
    vals = helm_values(profile)
    config = collector_config(profile, datadog_secret=True)
    cpu_s, longest = build_cpu_s(config)
    need, budget = needed_s(vals, config), probe_budget_s(vals)
    print(f"{profile}: longest processor string {longest:,} chars, estimated build {cpu_s:.1f} s of CPU, "
          f"limit {vals['resources']['limits']['cpu']}, needs {need:.0f} s, probes allow {budget:.0f} s")
    check(f"{profile}: the config builds in an estimated {cpu_s:.1f} s of CPU, under {BUILD_LIMIT_S:g} s (#1328)",
          cpu_s < BUILD_LIMIT_S, "shorten the OTTL statements: floor.PORTABLE_LIMIT sets the longest pattern")
    probe = vals.get("startupProbe") or {}
    check(f"{profile}: a startupProbe on the health_check port holds liveness off while the config builds",
          probe.get("httpGet", {}).get("port") == 13133, f"startupProbe is {probe!r}")
    check(f"{profile}: the probes allow {budget:.0f} s, at least {SAFETY:g} times the build at the CPU limit "
          f"({need:.0f} s)", budget >= need,
          "raise startupProbe.failureThreshold or the CPU limit, or shorten the OTTL statements")
    size = relay_bytes(vals["config"])
    check(f"{profile}: the relay config is {size:,} bytes as helm writes it, {size / CONFIGMAP_BYTES:.0%} of the "
          f"{CONFIGMAP_BYTES:,} a ConfigMap holds, under {HEADROOM:.0%} (#1332)", size < HEADROOM * CONFIGMAP_BYTES,
          "move what grows into a ConfigMap of its own, as transform/coc_mask is (gitops/otel-collector/coc-mask/)")
    check(f"{profile}: transform/coc_mask is not in the relay config but loaded from /coc-mask/{COC_MASK_KEY} "
          f"({config_paths(vals)})", MASK not in vals["config"].get("processors", {})
          and f"/coc-mask/{COC_MASK_KEY}" in config_paths(vals))

# The coc-mask ConfigMap goes to the cluster as its directory source writes it, so its file is its data as written.
coc_text = coc_mask_configmap()["data"][COC_MASK_KEY]
coc_size = len(coc_text.encode("utf-8"))
check(f"the coc-mask ConfigMap's {COC_MASK_KEY} is {coc_size:,} bytes, {coc_size / CONFIGMAP_BYTES:.0%} of a "
      f"ConfigMap, under {HEADROOM:.0%} (#1332)", coc_size < HEADROOM * CONFIGMAP_BYTES,
      f"{COC_MASK_MANIFEST.name} carries each pattern twice; a longer list needs a shorter form or a second file")
check("it writes the span-event context as an alias of the span context's list, so each pattern sits in it twice",
      coc_text.count("statements: &coc_mask_statements") == 1 and coc_text.count("statements: *coc_mask_statements") == 1)

# #1328's layout: transform/coc_mask in values.yaml's config, so helm writes each pattern into the relay four times.
# The size check must refuse it.
for profile in PROFILE_APP:
    vals = helm_values(profile)
    inline = copy.deepcopy(vals["config"])
    inline.setdefault("processors", {})[MASK] = collector_config(profile, datadog_secret=False)["processors"][MASK]
    size = relay_bytes(inline)
    check(f"mutant ({profile}, the mask back in relay.yaml as #1328 had it): {size:,} bytes, "
          f"{size / CONFIGMAP_BYTES:.0%}, over {HEADROOM:.0%}", size >= HEADROOM * CONFIGMAP_BYTES,
          "the size check would not have caught #1332's 84%")

# The state #1326 found on the cluster: #1316's single statements, no startupProbe and a 500m limit. The checks must
# refuse it, and the build limit must refuse those statements on any probes.
vals = copy.deepcopy(helm_values("burn"))
vals.pop("startupProbe", None)
vals["resources"]["limits"]["cpu"] = "500m"
config = single_form(collector_config("burn", datadog_secret=True))
need, budget = needed_s(vals, config), probe_budget_s(vals)
cpu_s, longest = build_cpu_s(config)
check(f"mutant (#1316's {longest:,}-character statements, no startupProbe, 500m, as on 2026-11-11): the probes' "
      f"{budget:.0f} s fall short of {need:.0f} s", budget < need,
      "the budget check would not have caught #1326's crashloop")
check(f"mutant: #1316's statements build in an estimated {cpu_s:.0f} s, over {BUILD_LIMIT_S:g} s, so the build "
      "check refuses them", cpu_s >= BUILD_LIMIT_S)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every collector profile's probes leave time to parse its config at its CPU limit.")
