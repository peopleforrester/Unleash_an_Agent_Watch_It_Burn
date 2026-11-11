# ABOUTME: Live check of #1335's criterion (#1339): on both KubeCon clusters the otel-collector Application is Synced and
# ABOUTME: Healthy, and the otel-collector-coc-mask ConfigMap it deploys is in monitoring, mounted and rolled into the collector.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of watch-it-burn-community and PRIVATE_CONTEXT naming the
kube-context of watch-it-burn-private. Every missing prerequisite is a failure, never a skip.

#1332 moved the collector's code-of-conduct mask (`transform/coc_mask`) out of relay.yaml into a ConfigMap of its own,
otel-collector-coc-mask, which each profile's `otel-collector` Application deploys from gitops/otel-collector/coc-mask/
into its destination, monitoring. relay.yaml names the processor in the traces pipeline and defines it nowhere, so a
collector without that ConfigMap refuses its config. test_collector_coc_mask.py holds the source offline; this holds
the clusters. The criterion stops holding in any of these ways on either cluster, and each one fails here:

- the kube-context is not that cluster;
- Argo CD has no `otel-collector` Application, or it is not Synced, or not Healthy;
- the Application's destination is not monitoring, or it no longer deploys gitops/otel-collector/coc-mask from this
  repo;
- Argo CD does not track the ConfigMap monitoring/otel-collector-coc-mask among the Application's resources, or tracks
  it out of sync;
- the ConfigMap is not in monitoring, was not put there by the `otel-collector` Application (its tracking id), or its
  coc-mask.yaml does not define transform/coc_mask alone;
- the collector DaemonSet does not mount it, mounts it optionally, carries a checksum/coc-mask annotation that is not
  the SHA-256 of the live file (so the pods run an older list), or has not rolled that template out to every node.

verify/test_collector_coc_mask_live_checks.py runs `run` offline against fake clusters built from this checkout's
ConfigMap, a healthy pair and one fake per way above, and holds that each way fails here. This spends nothing and
changes nothing: read-only kubectl gets.

Usage: COMMUNITY_CONTEXT=<kube-context> PRIVATE_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] \\
           python3 verify/test_collector_coc_mask_live.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys

import yaml

REPO_URL = "https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn.git"
APP = "otel-collector"
NAMESPACE = "monitoring"
CONFIGMAP = "otel-collector-coc-mask"
KEY = "coc-mask.yaml"
SOURCE_PATH = "gitops/otel-collector/coc-mask"
MASK = "transform/coc_mask"
ANNOTATION = "checksum/coc-mask"
TRACKING = f"{APP}:/ConfigMap:{NAMESPACE}/{CONFIGMAP}"
DAEMONSET = "otel-collector-opentelemetry-collector-agent"
CLUSTERS = (("watch-it-burn-community", "COMMUNITY_CONTEXT"), ("watch-it-burn-private", "PRIVATE_CONTEXT"))


def _repo_key(url: str) -> str:
    return url.strip().lower().removesuffix("/").removesuffix(".git")


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


def mask_file_problems(text: str | None) -> list[str]:
    """What keeps the ConfigMap's file from being the mask relay.yaml needs; empty when it is."""
    if text is None:
        return [f"the ConfigMap has no {KEY} key"]
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [f"{KEY} does not parse as YAML: {str(e)[:200]}"]
    if not isinstance(doc, dict) or list(doc) != ["processors"]:
        return [f"{KEY} holds {list(doc) if isinstance(doc, dict) else type(doc).__name__}, not processors alone"]
    procs = doc["processors"]
    if not isinstance(procs, dict) or list(procs) != [MASK]:
        return [f"{KEY} defines {list(procs) if isinstance(procs, dict) else procs!r}, not {MASK} alone"]
    if not isinstance(procs[MASK], dict) or not procs[MASK].get("trace_statements"):
        return [f"{MASK} in {KEY} has no trace_statements"]
    return []


def cluster_checks(name: str, context: str, cluster: Cluster) -> list[tuple[str, bool, str]]:
    """The criterion on one cluster: the Application Synced and Healthy, the ConfigMap in monitoring and in use."""
    out: list[tuple[str, bool, str]] = []
    out.append((f"{name}: the context {context!r} is that cluster", context == name or context.endswith(f"/{name}"),
                "the context must be the cluster's name or its EKS ARN (…:cluster/<name>)"))
    if not out[-1][1]:
        return out
    app = cluster.get("application", APP, "argocd")
    out.append((f"{name}: Argo CD has the {APP} Application", app is not None, ""))
    if app is None:
        return out
    status = app.get("status") or {}
    sync = (status.get("sync") or {}).get("status")
    health = (status.get("health") or {}).get("status")
    out.append((f"{name}: {APP} is Synced and Healthy", sync == "Synced" and health == "Healthy",
                f"sync {sync}, health {health}: {(status.get('health') or {}).get('message', '')}"))
    spec = app.get("spec") or {}
    dest = (spec.get("destination") or {}).get("namespace")
    sources = spec.get("sources") or ([spec["source"]] if spec.get("source") else [])
    deploys = [s for s in sources if _repo_key(s.get("repoURL", "")) == _repo_key(REPO_URL)
               and (s.get("path") or "").rstrip("/") == SOURCE_PATH]
    out.append((f"{name}: {APP} deploys {SOURCE_PATH} from this repo into {NAMESPACE}",
                dest == NAMESPACE and len(deploys) == 1,
                f"destination {dest}; sources {[(s.get('repoURL'), s.get('path'), s.get('chart')) for s in sources]}"))
    tracked = [r for r in status.get("resources") or [] if r.get("kind") == "ConfigMap"
               and r.get("name") == CONFIGMAP and r.get("namespace") == NAMESPACE]
    out.append((f"{name}: Argo CD tracks ConfigMap {NAMESPACE}/{CONFIGMAP} as {APP}'s, Synced",
                len(tracked) == 1 and tracked[0].get("status") == "Synced",
                f"tracked as {tracked}" if tracked else "it is not among the Application's resources"))

    cm = cluster.get("configmap", CONFIGMAP, NAMESPACE)
    out.append((f"{name}: ConfigMap {CONFIGMAP} is in {NAMESPACE}", cm is not None, ""))
    if cm is None:
        return out
    tracking = ((cm.get("metadata") or {}).get("annotations") or {}).get("argocd.argoproj.io/tracking-id")
    out.append((f"{name}: {NAMESPACE}/{CONFIGMAP} was put there by the {APP} Application", tracking == TRACKING,
                f"tracking id {tracking!r}, not {TRACKING!r}"))
    text = (cm.get("data") or {}).get(KEY)
    problems = mask_file_problems(text)
    out.append((f"{name}: its {KEY} defines {MASK} and nothing else", not problems, "; ".join(problems)))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else ""

    ds = cluster.get("daemonset", DAEMONSET, NAMESPACE)
    out.append((f"{name}: the collector DaemonSet {NAMESPACE}/{DAEMONSET} exists", ds is not None, ""))
    if ds is None:
        return out
    template = (ds.get("spec") or {}).get("template") or {}
    volumes = [v for v in (template.get("spec") or {}).get("volumes") or []
               if (v.get("configMap") or {}).get("name") == CONFIGMAP]
    out.append((f"{name}: the collector mounts {CONFIGMAP}, not optionally",
                len(volumes) == 1 and not volumes[0]["configMap"].get("optional"),
                f"volumes naming it: {volumes}"))
    annotation = ((template.get("metadata") or {}).get("annotations") or {}).get(ANNOTATION)
    out.append((f"{name}: the collector's {ANNOTATION} is the live {KEY}'s SHA-256, so its pods load this list",
                bool(digest) and annotation == digest, f"annotation {annotation}, live file {digest or 'missing'}"))
    st = ds.get("status") or {}
    desired = st.get("desiredNumberScheduled", 0)
    rolled = (desired > 0 and st.get("observedGeneration") == (ds.get("metadata") or {}).get("generation")
              and st.get("updatedNumberScheduled") == desired and st.get("numberAvailable") == desired)
    out.append((f"{name}: that template runs, available, on every node", rolled,
                f"generation {(ds.get('metadata') or {}).get('generation')}, observed {st.get('observedGeneration')}, "
                f"desired {desired}, updated {st.get('updatedNumberScheduled')}, available {st.get('numberAvailable')}"))
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
        print(f"== #1335's criterion on {name} ({contexts[env]}) ==")
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
        print("FAIL: test_collector_coc_mask_live.py cannot run; this is a failure, not a skip:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    failed = run(contexts, Cluster)
    if failed:
        print(f"\nFAILED: {len(failed)}: the otel-collector Application or its coc-mask ConfigMap is not right on "
              f"both clusters", file=sys.stderr)
        return 1
    print(f"\nOn watch-it-burn-community and watch-it-burn-private the {APP} Application is Synced and Healthy, and "
          f"{NAMESPACE}/{CONFIGMAP} is there, Argo CD's, and loaded by the rolled-out collector.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
