# ABOUTME: Live check of #1335's criterion (#1340): on both KubeCon clusters the collector's relay ConfigMap no longer
# ABOUTME: defines transform/coc_mask, still names it in the traces pipeline, and its relay.yaml reads about 25 KB.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of watch-it-burn-community and PRIVATE_CONTEXT naming the
kube-context of watch-it-burn-private. Every missing prerequisite is a failure, never a skip.

#1332 moved the code-of-conduct mask (`transform/coc_mask`) out of values.yaml's `config`, which the chart writes into
the relay ConfigMap (monitoring/otel-collector-opentelemetry-collector-agent, key `relay`), and into a ConfigMap of its
own. Written in the relay, helm wrote each pattern four times and the relay reached about 704 KB live, 885 KB at
worst, against the 1,048,576 bytes a ConfigMap's data may hold. #1335 read the relay on both clusters after the move:
26,210 bytes on watch-it-burn-community and 24,498 on watch-it-burn-private, with no mask definition. The offline
tests (test_collector_coc_mask.py, test_collector_startup_budget.py) hold the source; this holds the clusters. The
criterion stops holding in any of these ways on either cluster, and each one fails here:

- the kube-context is not that cluster;
- the relay ConfigMap is not in monitoring, or was not put there by the `otel-collector` Application (its tracking id);
- it has no `relay` key, or the key does not parse as a YAML map;
- the relay defines transform/coc_mask among its processors;
- the traces pipeline no longer names transform/coc_mask, so the mask is not run at all and "not defined here" would
  hold for the wrong reason;
- the relay is not about 25 KB: under LOW_BYTES (a relay cut short) or over HIGH_BYTES (the mask, or something else
  that grows, written back into it).

"About 25 KB" is read as 25,000 bytes within 40% either way. Both live relays sit near the middle, and the mask
written back in, as #1328 had it, is over twenty times the upper bound. A change that grows the relay past it on
purpose moves HIGH_BYTES here with its own record in decisions.md, and test_collector_startup_budget.py still holds the
relay under 75% of a ConfigMap.

verify/test_collector_relay_live_checks.py runs `run` offline against fake clusters whose relay is this checkout's
render, a healthy pair and one fake per way above, and holds that each way fails here. This spends nothing and changes
nothing: read-only kubectl gets.

Usage: COMMUNITY_CONTEXT=<kube-context> PRIVATE_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] \\
           python3 verify/test_collector_relay_live.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import yaml

APP = "otel-collector"
NAMESPACE = "monitoring"
CONFIGMAP = "otel-collector-opentelemetry-collector-agent"
KEY = "relay"
MASK = "transform/coc_mask"
TRACKING = f"{APP}:/ConfigMap:{NAMESPACE}/{CONFIGMAP}"
ABOUT_BYTES = 25_000
LOW_BYTES = 15_000                         # 40% under
HIGH_BYTES = 35_000                        # 40% over
CLUSTERS = (("watch-it-burn-community", "COMMUNITY_CONTEXT"), ("watch-it-burn-private", "PRIVATE_CONTEXT"))


class Cluster:
    """Read-only kubectl gets on one cluster, every call naming its context. The offline checks fake `get`."""

    def __init__(self, context: str) -> None:
        self.context = context

    def get(self, kind: str, name: str, namespace: str) -> dict | None:
        r = subprocess.run(["kubectl", "--context", self.context, "--request-timeout=30s", "-n", namespace,
                            "get", kind, name, "-o", "json"], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            if "NotFound" in r.stderr or "not found" in r.stderr:
                return None
            raise RuntimeError(f"kubectl --context {self.context} -n {namespace} get {kind} {name}: {r.stderr.strip()}")
        return json.loads(r.stdout)


def cluster_checks(name: str, context: str, cluster: Cluster) -> list[tuple[str, bool, str]]:
    """The criterion on one cluster: the relay ConfigMap is Argo CD's, has no mask definition and reads about 25 KB."""
    out: list[tuple[str, bool, str]] = []
    out.append((f"{name}: the context {context!r} is that cluster", context == name or context.endswith(f"/{name}"),
                "the context must be the cluster's name or its EKS ARN (…:cluster/<name>)"))
    if not out[-1][1]:
        return out
    cm = cluster.get("configmap", CONFIGMAP, NAMESPACE)
    out.append((f"{name}: the relay ConfigMap {NAMESPACE}/{CONFIGMAP} exists", cm is not None, ""))
    if cm is None:
        return out
    tracking = ((cm.get("metadata") or {}).get("annotations") or {}).get("argocd.argoproj.io/tracking-id")
    out.append((f"{name}: it was put there by the {APP} Application", tracking == TRACKING,
                f"tracking id {tracking!r}, not {TRACKING!r}"))
    text = (cm.get("data") or {}).get(KEY)
    relay = None
    why = f"the ConfigMap has no {KEY} key; it holds {sorted(cm.get('data') or {})}"
    if text is not None:
        try:
            relay = yaml.safe_load(text)
            why = f"{KEY} parses to {type(relay).__name__}, not a map"
        except yaml.YAMLError as e:
            why = f"{KEY} does not parse as YAML: {str(e)[:200]}"
    out.append((f"{name}: its {KEY} key parses as a YAML map", isinstance(relay, dict), why))
    if not isinstance(relay, dict):
        return out
    procs = relay.get("processors") or {}
    out.append((f"{name}: the relay does not define {MASK}", MASK not in procs,
                f"processors defined: {sorted(procs)}"))
    traces = ((((relay.get("service") or {}).get("pipelines") or {}).get("traces") or {}).get("processors")) or []
    out.append((f"{name}: the relay's traces pipeline still names {MASK}, so the coc-mask ConfigMap's definition runs",
                MASK in traces, f"traces processors: {traces}"))
    size = len(text.encode("utf-8"))
    out.append((f"{name}: the relay reads about {ABOUT_BYTES / 1000:g} KB ({size:,} bytes, between {LOW_BYTES:,} and "
                f"{HIGH_BYTES:,})", LOW_BYTES <= size <= HIGH_BYTES,
                f"{size:,} bytes: over {HIGH_BYTES:,} means something that grows, the mask among them, is back in the "
                f"relay; under {LOW_BYTES:,} means the relay was cut short"))
    return out


def report(results: list[tuple[str, bool, str]]) -> list[str]:
    failed = []
    for label, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))
        if not ok:
            failed.append(label)
    return failed


def run(contexts: dict[str, str], cluster_for) -> list[str]:
    """Every check on both clusters; the failed labels. `cluster_for(context)` gives the Cluster to read."""
    failed: list[str] = []
    for name, env in CLUSTERS:
        print(f"== #1335's relay criterion on {name} ({contexts[env]}) ==")
        try:
            failed += report(cluster_checks(name, contexts[env], cluster_for(contexts[env])))
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            failed += report([(f"{name}: the cluster can be read", False, str(e))])
    return failed


def main() -> int:
    missing = ["kubectl is not on PATH"] if shutil.which("kubectl") is None else []
    contexts = {env: os.environ.get(env, "") for _n, env in CLUSTERS}
    missing += [f"{env} is not set: name the kube-context of {n}" for n, env in CLUSTERS if not contexts[env]]
    if missing:
        print("FAIL: test_collector_relay_live.py cannot run; this is a failure, not a skip:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    failed = run(contexts, Cluster)
    if failed:
        print(f"\nFAILED: {len(failed)}: the relay ConfigMap is not right on both clusters", file=sys.stderr)
        return 1
    print(f"\nOn watch-it-burn-community and watch-it-burn-private the relay ConfigMap {NAMESPACE}/{CONFIGMAP} "
          f"defines no {MASK}, still runs it in the traces pipeline, and reads about {ABOUT_BYTES / 1000:g} KB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
