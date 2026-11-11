# ABOUTME: Live check of #1335's criterion (#1341): on both KubeCon clusters every collector pod runs on the live coc-mask
# ABOUTME: list's checksum/coc-mask annotation, is ready with no restart, and its start-up log says Everything is ready.
# SUITE: e2e
"""Needs kubectl, COMMUNITY_CONTEXT naming the kube-context of watch-it-burn-community and PRIVATE_CONTEXT naming the
kube-context of watch-it-burn-private, with rights to get pods and nodes/proxy. Every missing prerequisite is a
failure, never a skip.

#1335 synced #1332's collector onto both clusters and recorded, in decisions.md only, that each collector pod rolled
onto the `checksum/coc-mask` annotation, logged `Everything is ready. Begin running and processing data.` and showed
0 restarts. test_collector_coc_mask_live.py holds the DaemonSet's template and rollout counts; this holds the pods
themselves. The criterion stops holding in any of these ways on either cluster, and each one fails here:

- the kube-context is not that cluster;
- the ConfigMap monitoring/otel-collector-coc-mask, whose coc-mask.yaml the annotation is the SHA-256 of, is gone or
  has no such key;
- the collector DaemonSet is gone, or fewer or more of its pods run than it schedules (none counts as fewer);
- a pod is not on the DaemonSet's current template (its pod-template-generation label), or its checksum/coc-mask
  annotation is not the live file's SHA-256, so it runs an older list;
- a pod is not Running, its collector container is not ready, or any of its containers has restarted;
- the collector's start-up log, read from the node through kubelet (`nodes/<node>/proxy/logs/pods/...`), has no
  `Everything is ready` line from that pod.

The log is read from the node, not through `kubectl logs`, because kubelet rotates a container's log at 10Mi and
`kubectl logs` reads only the newest file: the collector writes about 1MB an hour, so its start-up line leaves
`kubectl logs` within a day. The node keeps five files, the older ones gzipped, and this reads the oldest of the
running container's. When even that no longer reaches back to the start, the check fails and says the start-up log
has rotated away, since the line can no longer be seen; a fresh roll of the collector brings it back.

verify/test_collector_pods_ready_live_checks.py runs `run` offline against fake clusters, a healthy pair and one fake
per way above, and holds that each way fails here. This spends nothing and changes nothing: read-only kubectl gets.

Usage: COMMUNITY_CONTEXT=<kube-context> PRIVATE_CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] \\
           python3 verify/test_collector_pods_ready_live.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_collector_coc_mask_live as mask  # noqa: E402

NAMESPACE = mask.NAMESPACE
CONFIGMAP = mask.CONFIGMAP
KEY = mask.KEY
ANNOTATION = mask.ANNOTATION
DAEMONSET = mask.DAEMONSET
CLUSTERS = mask.CLUSTERS
CONTAINER = "opentelemetry-collector"
READY = "Everything is ready. Begin running and processing data."
TEMPLATE_GENERATION = "deprecated.daemonset.template.generation"
# kubelet names a container's log <restart count>.log, and a rotated one <restart count>.log.<YYYYmmdd-HHMMSS>[.gz].
LOG_FILE = re.compile(r"^(\d+)\.log(?:\.(\d{8}-\d{6})(\.gz)?)?$")


class Cluster(mask.Cluster):
    """Read-only kubectl gets on one cluster, every call naming its context. The offline checks fake all three."""

    def _kubectl(self, *args: str) -> bytes:
        r = subprocess.run(["kubectl", "--context", self.context, "--request-timeout=30s", *args],
                           capture_output=True, timeout=90)
        if r.returncode != 0:
            raise RuntimeError(f"kubectl --context {self.context} {' '.join(args)}: "
                               f"{r.stderr.decode('utf-8', 'replace').strip()}")
        return r.stdout

    def pods(self, namespace: str, selector: str) -> list[dict]:
        return json.loads(self._kubectl("-n", namespace, "get", "pods", "-l", selector, "-o", "json"))["items"]

    def node_log(self, node: str, path: str) -> bytes:
        """A file or directory listing under the node's /var/log/, as kubelet serves it."""
        return self._kubectl("get", "--raw", f"/api/v1/nodes/{node}/proxy/logs/{path}")


def oldest_log(files: list[str], restarts: int) -> str | None:
    """The oldest file kubelet keeps of the container instance that has restarted `restarts` times."""
    mine = [(m.group(2) or "~", f) for f in files if (m := LOG_FILE.match(f)) and int(m.group(1)) == restarts]
    return min(mine)[1] if mine else None


def startup_log(cluster: Cluster, pod: dict, restarts: int) -> tuple[str | None, str]:
    """The text of the oldest log file of the collector container's running instance, and which file it was."""
    meta = pod.get("metadata") or {}
    node = (pod.get("spec") or {}).get("nodeName")
    if not node:
        return None, "the pod has no node"
    directory = f"pods/{NAMESPACE}_{meta.get('name')}_{meta.get('uid')}/{CONTAINER}/"
    listing = cluster.node_log(node, directory).decode("utf-8", "replace")
    files = re.findall(r'href="([^"/]+)"', listing)
    oldest = oldest_log(files, restarts)
    if oldest is None:
        return None, f"no {restarts}.log under {directory} on {node}: {files}"
    data = cluster.node_log(node, directory + oldest)
    if oldest.endswith(".gz"):
        data = gzip.decompress(data)
    return data.decode("utf-8", "replace"), f"{directory}{oldest} on {node} (of {sorted(files)})"


def pod_checks(name: str, cluster: Cluster, pod: dict, generation: str | None, digest: str) -> list[tuple[str, bool, str]]:
    meta = pod.get("metadata") or {}
    pname = meta.get("name")
    label = f"{name}: pod {pname}"
    out: list[tuple[str, bool, str]] = []
    gen = (meta.get("labels") or {}).get("pod-template-generation")
    out.append((f"{label} is on the DaemonSet's current template", generation is not None and gen == generation,
                f"pod-template-generation {gen}, the DaemonSet's {generation}"))
    annotation = (meta.get("annotations") or {}).get(ANNOTATION)
    out.append((f"{label} rolled onto {ANNOTATION}, the live {KEY}'s SHA-256", bool(digest) and annotation == digest,
                f"annotation {annotation}, live file {digest or 'missing'}"))
    status = pod.get("status") or {}
    statuses = status.get("containerStatuses") or []
    collector = [c for c in statuses if c.get("name") == CONTAINER]
    out.append((f"{label} is Running with its {CONTAINER} container ready",
                status.get("phase") == "Running" and len(collector) == 1 and collector[0].get("ready") is True,
                f"phase {status.get('phase')}, containers {[(c.get('name'), c.get('ready')) for c in statuses]}"))
    restarts = {c.get("name"): c.get("restartCount") for c in statuses}
    out.append((f"{label} has no restart", bool(restarts) and all(n == 0 for n in restarts.values()),
                f"restart counts {restarts}"))
    count = restarts.get(CONTAINER)
    if not isinstance(count, int):
        out.append((f"{label} logged {READY!r} at start-up", False, f"no {CONTAINER} container status to read"))
        return out
    text, where = startup_log(cluster, pod, count)
    if text is None:
        out.append((f"{label} logged {READY!r} at start-up", False, where))
        return out
    first = text[:30] if text else "empty"
    started = ((collector[0].get("state") or {}).get("running") or {}).get("startedAt") if collector else None
    out.append((f"{label} logged {READY!r} at start-up", READY in text,
                f"not in {where}, which begins {first!r} while the container started {started}; a file that begins "
                f"well after the start means the start-up log has rotated away and the line can no longer be seen"))
    return out


def cluster_checks(name: str, context: str, cluster: Cluster) -> list[tuple[str, bool, str]]:
    """The criterion on one cluster: every collector pod on the live list's checksum, ready, unrestarted, logged ready."""
    out: list[tuple[str, bool, str]] = []
    out.append((f"{name}: the context {context!r} is that cluster", context == name or context.endswith(f"/{name}"),
                "the context must be the cluster's name or its EKS ARN (…:cluster/<name>)"))
    if not out[-1][1]:
        return out
    cm = cluster.get("configmap", CONFIGMAP, NAMESPACE)
    text = ((cm or {}).get("data") or {}).get(KEY)
    out.append((f"{name}: ConfigMap {NAMESPACE}/{CONFIGMAP} holds {KEY}", text is not None,
                "the ConfigMap is gone" if cm is None else f"its keys are {sorted((cm.get('data') or {}))}"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else ""
    ds = cluster.get("daemonset", DAEMONSET, NAMESPACE)
    out.append((f"{name}: the collector DaemonSet {NAMESPACE}/{DAEMONSET} exists", ds is not None, ""))
    if ds is None:
        return out
    generation = ((ds.get("metadata") or {}).get("annotations") or {}).get(TEMPLATE_GENERATION)
    labels = ((ds.get("spec") or {}).get("selector") or {}).get("matchLabels") or {}
    selector = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    uid = (ds.get("metadata") or {}).get("uid")
    pods = [p for p in cluster.pods(NAMESPACE, selector) if not (p.get("metadata") or {}).get("deletionTimestamp")
            and any(o.get("kind") == "DaemonSet" and o.get("uid") == uid and o.get("controller")
                    for o in (p.get("metadata") or {}).get("ownerReferences") or [])]
    desired = ((ds.get("status") or {}).get("desiredNumberScheduled")) or 0
    out.append((f"{name}: the DaemonSet runs one collector pod on each of its {desired} node(s)",
                desired > 0 and len(pods) == desired,
                f"{len(pods)} pod(s) of it: {[(p.get('metadata') or {}).get('name') for p in pods]}"))
    for pod in pods:
        out += pod_checks(name, cluster, pod, generation, digest)
    return out


def run(contexts: dict[str, str], cluster_for) -> list[str]:
    """Every check on both clusters; the failed labels. `cluster_for(context)` gives the Cluster to read."""
    failed: list[str] = []
    for name, env in CLUSTERS:
        print(f"== #1335's collector pods on {name} ({contexts[env]}) ==")
        try:
            failed += mask.report(cluster_checks(name, contexts[env], cluster_for(contexts[env])))
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError, EOFError) as e:
            failed += mask.report([(f"{name}: the cluster can be read", False, str(e))])
    return failed


def main() -> int:
    missing = ["kubectl is not on PATH"] if shutil.which("kubectl") is None else []
    contexts = {env: os.environ.get(env, "") for _n, env in CLUSTERS}
    missing += [f"{env} is not set: name the kube-context of {n}" for n, env in CLUSTERS if not contexts[env]]
    if missing:
        print("FAIL: test_collector_pods_ready_live.py cannot run; this is a failure, not a skip:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    failed = run(contexts, Cluster)
    if failed:
        print(f"\nFAILED: {len(failed)}: the collector pods are not all on the live coc-mask list, ready, unrestarted "
              f"and logged ready on both clusters", file=sys.stderr)
        return 1
    print(f"\nOn watch-it-burn-community and watch-it-burn-private every collector pod carries the live {KEY}'s "
          f"{ANNOTATION}, is ready with no restart, and logged {READY!r} at start-up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
