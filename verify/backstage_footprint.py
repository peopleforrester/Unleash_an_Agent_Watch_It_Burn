# ABOUTME: The arithmetic behind verify/backstage-footprint.sh (#484): Backstage and Postgres usage against their
# ABOUTME: requests, node allocatable against everything scheduled on it, and pods on each entity's Kubernetes tab.
"""Usage comes from the kubelet's summary API, not `kubectl top`. Nothing in this repo installs metrics-server
(the EKS addons in infra/terraform/aws/cluster/main.tf are vpc-cni, kube-proxy, coredns, pod identity and EBS
CSI), so the metrics API `kubectl top` reads does not exist on an attendee cluster. The summary API is the
source metrics-server itself scrapes: memory.workingSetBytes is the number `kubectl top` shows, rssBytes is
the "resident" figure the local measurement in #244 reported, and cpu.usageNanoCores is the same CPU rate.

Each subcommand reads JSON files the shell script saved and prints plain text. A subcommand that judges
something exits 1 when it fails, so the script's exit code is the verdict."""
from __future__ import annotations

import json
import re
import sys

NAMESPACE = "backstage"
_SUFFIX = {
    "": 1, "m": 1e-3,
    "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18,
    "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50, "Ei": 2**60,
}
_QUANTITY = re.compile(r"^([+-]?[0-9.]+(?:[eE][+-]?[0-9]+)?)([a-zA-Z]*)$")
MI = 2**20


def quantity(q: str | int | float | None) -> float:
    """A Kubernetes resource quantity as a plain number: cores for CPU, bytes for memory."""
    if q is None or q == "":
        return 0.0
    if isinstance(q, (int, float)):
        return float(q)
    m = _QUANTITY.match(str(q).strip())
    if not m or m.group(2) not in _SUFFIX:
        raise ValueError(f"not a Kubernetes quantity: {q!r}")
    return float(m.group(1)) * _SUFFIX[m.group(2)]


def _res(c: dict, kind: str, key: str) -> float:
    return quantity(((c.get("resources") or {}).get(kind) or {}).get(key))


def pod_requests(pod: dict) -> tuple[float, float]:
    """What the scheduler counts for one pod, (cores, bytes): the larger of the app containers plus sidecars
    and the largest ordinary init container (plus the sidecars started before it), then pod overhead."""
    spec = pod.get("spec") or {}
    out = []
    for key in ("cpu", "memory"):
        sidecars = 0.0
        init_peak = 0.0
        for c in spec.get("initContainers") or []:
            if c.get("restartPolicy") == "Always":
                sidecars += _res(c, "requests", key)
            else:
                init_peak = max(init_peak, sidecars + _res(c, "requests", key))
        apps = sum(_res(c, "requests", key) for c in spec.get("containers") or []) + sidecars
        out.append(max(apps, init_peak) + quantity((spec.get("overhead") or {}).get(key)))
    return out[0], out[1]


def _live(pods: dict) -> list[dict]:
    return [p for p in pods.get("items") or []
            if (p.get("status") or {}).get("phase") not in ("Succeeded", "Failed")]


def node_table(nodes: dict, pods: dict) -> list[str]:
    """Per node: allocatable, the sum of requests scheduled on it, and what is left."""
    by_node: dict[str, list[float]] = {}
    for p in _live(pods):
        n = (p.get("spec") or {}).get("nodeName")
        if not n:
            continue
        cpu, mem = pod_requests(p)
        acc = by_node.setdefault(n, [0.0, 0.0, 0])
        acc[0] += cpu
        acc[1] += mem
        acc[2] += 1
    lines = [f"{'node':<48} {'type':<12} {'pods':>4}  {'cpu req/alloc (m)':>20} {'cpu%':>5}  "
             f"{'mem req/alloc (Mi)':>20} {'mem%':>5}  {'free cpu m':>10} {'free mem Mi':>11}"]
    for node in nodes.get("items") or []:
        name = node["metadata"]["name"]
        itype = (node["metadata"].get("labels") or {}).get("node.kubernetes.io/instance-type", "?")
        alloc = node.get("status", {}).get("allocatable") or {}
        a_cpu, a_mem = quantity(alloc.get("cpu")), quantity(alloc.get("memory"))
        r_cpu, r_mem, count = by_node.get(name, [0.0, 0.0, 0])
        lines.append(
            f"{name:<48} {itype:<12} {count:>4}  "
            f"{f'{r_cpu * 1000:.0f}/{a_cpu * 1000:.0f}':>20} {_pct(r_cpu, a_cpu):>5}  "
            f"{f'{r_mem / MI:.0f}/{a_mem / MI:.0f}':>20} {_pct(r_mem, a_mem):>5}  "
            f"{(a_cpu - r_cpu) * 1000:>10.0f} {(a_mem - r_mem) / MI:>11.0f}")
    return lines


def _pct(used: float, total: float) -> str:
    return f"{100 * used / total:.0f}%" if total else "n/a"


def pod_status(pods: dict) -> tuple[list[str], bool]:
    """The Backstage namespace's pods: node, readiness, restarts, last termination reason and the running image
    digest. ok is False when there are none or any is not Ready."""
    items = [p for p in pods.get("items") or [] if p["metadata"].get("namespace") == NAMESPACE]
    lines, ok = [], bool(items)
    if not items:
        lines.append(f"no pods in namespace {NAMESPACE}: is the backstage app synced on this cluster?")
    for p in items:
        st = p.get("status") or {}
        ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in st.get("conditions") or [])
        ok = ok and ready
        for cs in st.get("containerStatuses") or []:
            last = ((cs.get("lastState") or {}).get("terminated") or {}).get("reason", "-")
            lines.append(f"{p['metadata']['name']:<40} {cs['name']:<12} node={p['spec'].get('nodeName', '-')} "
                         f"ready={'yes' if ready else 'NO'} restarts={cs.get('restartCount', 0)} "
                         f"last-termination={last} image={cs.get('imageID') or cs.get('image')}")
    return lines, ok


def usage_table(pods: dict, summaries: list[dict]) -> tuple[list[str], bool]:
    """Each Backstage-namespace container's usage over the samples (last and peak) beside its request and
    limit. ok is False when a container had no sample at all, so a missing reading never looks like zero."""
    spec = {}
    for p in pods.get("items") or []:
        if p["metadata"].get("namespace") != NAMESPACE:
            continue
        for c in (p.get("spec") or {}).get("containers") or []:
            spec[(p["metadata"]["name"], c["name"])] = c
    seen: dict[tuple[str, str], dict[str, list[float]]] = {k: {"cpu": [], "ws": [], "rss": []} for k in spec}
    for s in summaries:
        for ps in s.get("pods") or []:
            ref = ps.get("podRef") or {}
            if ref.get("namespace") != NAMESPACE:
                continue
            for c in ps.get("containers") or []:
                acc = seen.get((ref.get("name"), c.get("name")))
                if acc is None:
                    continue
                cpu = (c.get("cpu") or {}).get("usageNanoCores")
                mem = c.get("memory") or {}
                if cpu is not None:
                    acc["cpu"].append(cpu / 1e6)
                if mem.get("workingSetBytes") is not None:
                    acc["ws"].append(mem["workingSetBytes"] / MI)
                if mem.get("rssBytes") is not None:
                    acc["rss"].append(mem["rssBytes"] / MI)
    lines = [f"{'pod/container':<52} {'cpu m last/peak':>16} {'req':>5} {'lim':>5}  "
             f"{'working set Mi last/peak':>25} {'rss Mi peak':>11} {'req':>5} {'lim':>5}  samples"]
    ok = bool(spec)
    for (pod, name), c in sorted(spec.items()):
        acc = seen[(pod, name)]
        n = len(acc["ws"])
        ok = ok and n > 0
        rss = f"{max(acc['rss']):.0f}" if acc["rss"] else "-"
        lines.append(
            f"{pod + '/' + name:<52} {_lp(acc['cpu']):>16} "
            f"{_res(c, 'requests', 'cpu') * 1000:>5.0f} {_res(c, 'limits', 'cpu') * 1000:>5.0f}  "
            f"{_lp(acc['ws']):>25} {rss:>11} "
            f"{_res(c, 'requests', 'memory') / MI:>5.0f} {_res(c, 'limits', 'memory') / MI:>5.0f}  {n}")
    return lines, ok


def _lp(vals: list[float]) -> str:
    return f"{vals[-1]:.0f}/{max(vals):.0f}" if vals else "no sample"


def guest_token(refresh: dict) -> str:
    """The Backstage token out of a guest provider's /api/auth/guest/refresh response."""
    tok = ((refresh or {}).get("backstageIdentity") or {}).get("token")
    if not tok:
        raise ValueError("the guest refresh response carries no backstageIdentity.token")
    return tok


def tab_pods(response: dict) -> tuple[list[str], list[str]]:
    """The pods and the errors a Kubernetes tab shows, from POST /api/kubernetes/services/<name>."""
    pods, errors = [], []
    for item in (response or {}).get("items") or []:
        cluster = (item.get("cluster") or {}).get("name", "?")
        for e in item.get("errors") or []:
            errors.append(f"{cluster}: {e.get('errorType', '?')} {e.get('message') or e.get('resourcePath', '')}")
        for group in item.get("resources") or []:
            if group.get("type") != "pods":
                continue
            for r in group.get("resources") or []:
                meta = r.get("metadata") or {}
                phase = (r.get("status") or {}).get("phase", "?")
                pods.append(f"{cluster}: {meta.get('namespace', '?')}/{meta.get('name', '?')} {phase}")
    return pods, errors


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str]) -> int:
    cmd, args = argv[0], argv[1:]
    if cmd == "requests":
        print("\n".join(node_table(_load(args[0]), _load(args[1]))))
        return 0
    if cmd == "pods":
        lines, ok = pod_status(_load(args[0]))
        print("\n".join(lines))
        return 0 if ok else 1
    if cmd == "usage":
        lines, ok = usage_table(_load(args[0]), [_load(a) for a in args[1:]])
        print("\n".join(lines))
        return 0 if ok else 1
    if cmd == "token":
        print(guest_token(_load(args[0])))
        return 0
    if cmd == "tab":
        ref, resp = args[0], _load(args[1])
        pods, errors = tab_pods(resp)
        for p in pods:
            print(f"  {ref}: {p}")
        for e in errors:
            print(f"  {ref}: ERROR {e}")
        if not pods:
            print(f"  {ref}: the Kubernetes tab lists NO pods")
        return 0 if pods and not errors else 1
    print(f"unknown subcommand {cmd!r}: requests|pods|usage|token|tab", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
