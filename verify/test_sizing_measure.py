# ABOUTME: Offline check that infra/SIZING.md measures a live cluster with something the cluster has (#547):
# ABOUTME: the kubelet summary API, not `kubectl top`, while nothing in the repo installs metrics-server.
"""`kubectl top` reads the metrics API, and only metrics-server serves it. SIZING.md told the reader to measure one
live cluster with `kubectl top`, but the EKS addons in infra/terraform/aws/cluster/main.tf never included
metrics-server and no Argo CD app deploys it, so the command fails with "Metrics API not available" (#484 found
it, #547 fixed the doc). The doc now points at the kubelet summary API, which verify/backstage-footprint.sh also
reads.

Whether metrics-server is installed is read from the repo, not assumed: if the addon or a gitops manifest ever
adds it, SIZING.md may tell the reader to use `kubectl top` again. Until then, every line of SIZING.md that names
`kubectl top` must also name metrics-server, which is the line explaining why it does not work."""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SIZING = REPO / "infra" / "SIZING.md"
CLUSTER_TF = REPO / "infra" / "terraform" / "aws" / "cluster" / "main.tf"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def eks_addons(tf: str) -> list[str]:
    """The keys of the cluster module's `addons = { ... }` map, found by brace depth."""
    m = re.search(r"^\s*addons\s*=\s*\{", tf, re.M)
    if not m:
        return []
    depth, i, names = 1, m.end(), []
    while i < len(tf) and depth:
        line_end = tf.find("\n", i)
        line_end = len(tf) if line_end == -1 else line_end
        line = tf[i:line_end]
        code = line.split("#", 1)[0]
        if depth == 1:
            k = re.match(r"\s*([A-Za-z0-9_-]+)\s*=\s*\{", code)
            if k:
                names.append(k.group(1))
        depth += code.count("{") - code.count("}")
        i = line_end + 1
    return names


tf = CLUSTER_TF.read_text()
addons = eks_addons(tf)
check("the addons map in aws/cluster/main.tf is found", bool(addons))
check("the known addons are parsed (vpc-cni, coredns)", "vpc-cni" in addons and "coredns" in addons)

gitops_hits = [p.relative_to(REPO).as_posix() for p in sorted((REPO / "gitops").rglob("*"))
               if p.suffix in (".yaml", ".yml") and p.is_file()
               and re.search(r"^\s*(?:chart|name):\s*['\"]?metrics-server\b", p.read_text(errors="replace"), re.M)]
metrics_server = "metrics-server" in addons or bool(gitops_hits)
print(f"  metrics-server installed: {metrics_server} (addons: {', '.join(addons)}; gitops: {gitops_hits or 'none'})")

doc = SIZING.read_text()
check("SIZING.md points at the kubelet summary API (/proxy/stats/summary)", "/proxy/stats/summary" in doc)
check("SIZING.md names verify/backstage-footprint.sh, which reads it", "verify/backstage-footprint.sh" in doc)
check("verify/backstage-footprint.sh exists", (REPO / "verify" / "backstage-footprint.sh").is_file())

if not metrics_server:
    bad = [f"line {n}: {line.strip()[:120]}" for n, line in enumerate(doc.splitlines(), 1)
           if "kubectl top" in line and "metrics-server" not in line]
    check("without metrics-server, no SIZING.md line tells the reader to measure with `kubectl top`", not bad)
    for b in bad:
        print(f"        {b}")

# The kube-safety rule (CLAUDE.md): every kubectl command in the doc names its context.
kubectl_lines = [line for line in doc.splitlines() if re.search(r"\bkubectl (?:get|--context)", line)]
check("SIZING.md has a kubectl measurement command", bool(kubectl_lines))
check("every kubectl command in SIZING.md carries --context", all("--context" in line for line in kubectl_lines))

if failures:
    print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("\nSIZING.md measures with what the cluster has")
