# ABOUTME: Holds the KubeCon clusters to Whitney's Datadog sandbox rules (#629): one env tag, and a distinct
# ABOUTME: burritobot-public or burritobot-private cluster name that the Agents, the collector and the fleet queries agree on.
"""Pins #629.

The sandbox org holds other projects' data, so BurritoBot's is separated by the env tag and by cluster
names that start with burritobot. Datadog says a cluster name "should be a unique name"
(docs.datadoghq.com/containers/guide/kubernetes-cluster-name-detection, read 2026-10-27), so the two KubeCon
clusters cannot both be "burritobot". The identity script derives burritobot-<role> from the EKS name, and
every consumer reads that one key, so the Agent's kube_cluster_name and the traces' kube_cluster_name match.
The EKS name stays in cluster-name, which the probes and fleet.sh compare against the cluster itself.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
IDENTITY = REPO / "infra/datadog-cluster-identity.sh"
DD_ENV = "burritobot-kubecon-na-26"
KEY = "datadog-cluster-name"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def identity_literals(cluster: str) -> list[str]:
    """Run the identity script against a kubectl shim and return the configmap creates it made."""
    with tempfile.TemporaryDirectory(dir=REPO / "verify") as d:
        log = pathlib.Path(d) / "calls"
        shim = pathlib.Path(d) / "kubectl"
        shim.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{log}"\n'
                        '[[ "$*" == *apply* ]] && cat >/dev/null\nexit 0\n')
        shim.chmod(0o755)
        env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "CLUSTER_NAME": cluster}
        env.pop("WITB_DD_ADMIN_API_KEY", None)
        subprocess.run(["bash", str(IDENTITY)], env=env, capture_output=True, text=True, check=True)
        calls = log.read_text().splitlines()
    return [c for c in calls if "create configmap cluster-identity" in c]


print("== the identity script derives a distinct burritobot-<role> name per cluster ==")
# Named for what the audience sees on the Datadog screen: the bot the room hacks is public, the presenters'
# cluster is private. A second presenter cluster keeps its owner so the names stay unique.
for eks, want in (("watch-it-burn-community", "burritobot-public"),
                  ("watch-it-burn-private", "burritobot-private"),
                  ("watch-it-burn-whitney-admin", "burritobot-private-whitney"),
                  ("watch-it-burn-attendee-007", "burritobot-attendee-007")):
    made = identity_literals(eks)
    check(f"{eks} -> {want} in every cluster-identity it writes ({len(made)})",
          bool(made) and all(f"--from-literal={KEY}={want}" in c for c in made), "\n        ".join(made))
    check(f"{eks} keeps its EKS name in cluster-name",
          bool(made) and all(f"--from-literal=cluster-name={eks}" in c for c in made))

print("== the Agents, the collector and the fleet queries read that name and carry the env ==")
agent = yaml.safe_load((REPO / "gitops/manifests/datadog/datadog-agent.yaml").read_text())
override = agent["spec"]["override"]
for comp in ("nodeAgent", "clusterAgent"):
    env = {e["name"]: e for e in (override.get(comp) or {}).get("env", [])}
    ref = ((env.get("DD_CLUSTER_NAME") or {}).get("valueFrom") or {}).get("configMapKeyRef") or {}
    check(f"{comp} DD_CLUSTER_NAME reads cluster-identity/{KEY}", ref.get("name") == "cluster-identity"
          and ref.get("key") == KEY, str(ref))
    check(f"{comp} DD_ENV is {DD_ENV}", (env.get("DD_ENV") or {}).get("value") == DD_ENV)
check("the fallback clusterName is a burritobot name", agent["spec"]["global"]["clusterName"].startswith("burritobot"))

collector = yaml.safe_load((REPO / "gitops/otel-collector/values.yaml").read_text())
wib = next((e for e in collector.get("extraEnvs", []) if e.get("name") == "WIB_CLUSTER_NAME"), {})
cref = (wib.get("valueFrom") or {}).get("configMapKeyRef") or {}
check(f"the collector's k8s.cluster.name reads cluster-identity/{KEY}", cref.get("key") == KEY, str(cref))

monitors = yaml.safe_load((REPO / "infra/datadog-fleet/monitors.yaml").read_text())
check("the fleet monitors filter on kube_cluster_name:burritobot-*",
      monitors.get("cluster_filter") == "kube_cluster_name:burritobot-*")
check("datadog-orgs.sh expects the sandbox org by default (its name is Datadog)",
      'PREFIX="${WIB_DD_POOL_PREFIX:-Datadog}"' in (REPO / "verify/datadog-orgs.sh").read_text())
check("last_trace.py queries kube_cluster_name:burritobot-*",
      "kube_cluster_name:burritobot-*" in (REPO / "verify/last_trace.py").read_text())

print("== the collector puts the env and the cluster name on everything it ships ==")
cfg = collector["config"]
res = {a["key"]: a for a in cfg["processors"]["resource"]["attributes"]}
check(f"resource upserts deployment.environment.name={DD_ENV}",
      res.get("deployment.environment.name", {}).get("value") == DD_ENV
      and res["deployment.environment.name"].get("action") == "upsert")
check("cluster.name is the burritobot-<role> name, not the stale watch-it-burn literal",
      res.get("cluster.name", {}).get("value") == "${env:WIB_CLUSTER_NAME}")
pipes = cfg["service"]["pipelines"]
for name in ("traces", "metrics", "traces/lab", "metrics/lab"):
    check(f"the {name} pipeline runs the resource processor", "resource" in pipes[name]["processors"])

print("== services outside the burritobot family get the prefix; the family is left alone ==")
guard = cfg["processors"].get("transform/burritobot_service") or {}
stmts = [s for k in ("trace_statements", "metric_statements") for g in guard.get(k, []) for s in g["statements"]]
check("transform/burritobot_service rewrites service.name for spans and metrics", len(stmts) == 2)
pat = re.search(r'not IsMatch\(attributes\["service\.name"\], "([^"]+)"\)', stmts[0]) if stmts else None
family = re.compile(pat.group(1)) if pat else None
emitted = {m.group(1) for p in ("gitops/ai-layer/resources.yaml", "gitops/ai-layer/agentgateway.yaml")
           for m in re.finditer(r"service\.name=([A-Za-z0-9_.-]+)", (REPO / p).read_text())}
check(f"no service the BurritoBot path sends is renamed {sorted(emitted)}",
      bool(family) and bool(emitted) and all(family.search(s) for s in emitted))
check("a stranger such as workshop-agent or burritobotx is prefixed",
      bool(family) and not family.search("workshop-agent") and not family.search("burritobotx"))
check("the guard runs last in traces, after every condition that matches a sent name",
      pipes["traces"]["processors"][-1] == "transform/burritobot_service")
check("the guard runs last in metrics", pipes["metrics"]["processors"][-1] == "transform/burritobot_service")

print("== the ML app is burritobot, and it is the root service ==")
# For OTel spans Datadog sets ml_app from the root span's service (docs.datadoghq.com/llm_observability/
# instrumentation/otel_instrumentation, read 2026-10-28), so the root keeps the bare name and no hyphen.
docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
proxy = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "guard-proxy")
penv = {e["name"]: e.get("value") for e in proxy["spec"]["template"]["spec"]["containers"][0]["env"]}
check("guard-proxy, the root span, is service burritobot", penv.get("OTEL_SERVICE_NAME") == "burritobot")
check("guard-proxy's DD_LLMOBS_ML_APP is that same name", penv.get("DD_LLMOBS_ML_APP") == "burritobot")

print("== every BurritoBot pod tags its logs with the env and a burritobot service ==")
workloads = docs + [d for p in ("gitops/ai-layer/agentgateway.yaml", "gitops/ai-layer/argocd-managed-app.yaml",
                                *sorted(str(x.relative_to(REPO)) for x in REPO.glob("gitops/manifests/demo-app-*/deployment.yaml")))
                    for d in yaml.safe_load_all((REPO / p).read_text()) if d]
deploys = [d for d in workloads if d["kind"] == "Deployment"]
check(f"found the Deployments ({len(deploys)})", len(deploys) >= 14)
for d in deploys:
    labels = d["spec"]["template"]["metadata"].get("labels") or {}
    svc = labels.get("tags.datadoghq.com/service", "")
    check(f"{d['metadata']['name']}: env {DD_ENV}, service {svc or 'none'}",
          labels.get("tags.datadoghq.com/env") == DD_ENV and bool(re.fullmatch(r"burritobot(-[a-z0-9-]+)?", svc)))
check("guard-proxy's logs carry the service its spans do",
      (proxy["spec"]["template"]["metadata"]["labels"]).get("tags.datadoghq.com/service") == "burritobot")
agent_cr = next(d for d in docs if d["kind"] == "Agent")
aenv = {e["name"]: e.get("value") for e in agent_cr["spec"]["declarative"]["deployment"]["env"]}
check("the kagent agent pod (no pod labels of ours) sets DD_SERVICE burritobot-agent and the env",
      aenv.get("DD_SERVICE") == "burritobot-agent" and aenv.get("DD_ENV") == DD_ENV)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All Datadog sandbox naming checks passed.")
