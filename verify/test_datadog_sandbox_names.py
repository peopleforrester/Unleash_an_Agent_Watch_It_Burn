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

# Every profile's collector, as its Application layers the value files: Helm replaces extraEnvs rather than
# merging it, so the attendee overlay (values-dual.yaml) restates WIB_CLUSTER_NAME, and it read cluster-name
# until #587. Attendee markers were then tagged watch-it-burn-attendee-NNN while the Agents said burritobot-attendee-NNN.
sys.path.insert(0, str(REPO / "verify"))
import collector_render  # noqa: E402
for profile in collector_render.PROFILE_APP:
    wib = next((e for e in collector_render.helm_values(profile).get("extraEnvs", [])
                if e.get("name") == "WIB_CLUSTER_NAME"), {})
    cref = (wib.get("valueFrom") or {}).get("configMapKeyRef") or {}
    check(f"the {profile} collector's k8s.cluster.name reads cluster-identity/{KEY}", cref.get("key") == KEY, str(cref))

monitors = yaml.safe_load((REPO / "infra/datadog-fleet/monitors.yaml").read_text())
check("the fleet monitors filter on kube_cluster_name:burritobot-*",
      monitors.get("cluster_filter") == "kube_cluster_name:burritobot-*")
check("datadog-orgs.sh expects the sandbox org by default (its name is Datadog)",
      'PREFIX="${WIB_DD_POOL_PREFIX:-Datadog}"' in (REPO / "verify/datadog-orgs.sh").read_text())
check("last_trace.py queries kube_cluster_name:burritobot-*",
      "kube_cluster_name:burritobot-*" in (REPO / "verify/last_trace.py").read_text())

print("== every BurritoBot pod labels its logs with the env and the service its spans carry ==")
# The Agent tags a container's logs from the pod's tags.datadoghq.com/* labels (Unified Service Tagging,
# docs.datadoghq.com/getting_started/tagging/unified_service_tagging, read 2026-10-28); without them a log's
# service is the image short name (nginx, workshop-mcp) and sits outside BurritoBot in the shared org.
# guard-proxy's service is the root span's, burritobot, which Datadog takes as the LLM Obs ml_app.
pods = {}
for path in ("gitops/ai-layer/resources.yaml", "gitops/ai-layer/agentgateway.yaml",
             "gitops/ai-layer/argocd-managed-app.yaml"):
    for d in yaml.safe_load_all((REPO / path).read_text()):
        if not d or d.get("kind") not in ("Deployment", "Agent"):
            continue
        if d["kind"] == "Agent":
            dep = d["spec"]["declarative"]["deployment"]
            env = {e["name"]: e.get("value", "") for e in dep.get("env", [])}
            pods[d["metadata"]["name"]] = (dep.get("labels") or {}, env)
        else:
            c = d["spec"]["template"]["spec"]["containers"][0]
            env = {e["name"]: e.get("value", "") for e in c.get("env", [])}
            pods[d["metadata"]["name"]] = (d["spec"]["template"]["metadata"].get("labels") or {}, env)
check("the AI layer's workloads were found (10 Deployments and the workshop-agent)", len(pods) == 11, sorted(pods))
for name, (labels, env) in sorted(pods.items()):
    svc = labels.get("tags.datadoghq.com/service", "")
    otel = env.get("OTEL_SERVICE_NAME")
    named = svc == "burritobot" if name == "guard-proxy" else svc.startswith("burritobot-")
    check(f"{name} labels service={svc or '<none>'} env={labels.get('tags.datadoghq.com/env', '<none>')}",
          named and svc == (otel or svc) and labels.get("tags.datadoghq.com/env") == DD_ENV,
          f"OTEL_SERVICE_NAME={otel}")

print("== tags.datadoghq.com/* are pod labels everywhere, never annotations (#662) ==")
# The Agent reads these keys from pod labels only (comp/core/tagger/collectors/workloadmeta_extract.go, read
# 2026-10-29). As annotations they set nothing, which is how the five platform charts logged under image names
# while looking tagged. verify/test_datadog_log_services_render.py renders every chart to hold the labels.


def annotated(node, where: str) -> list[str]:
    """Every annotations or podAnnotations map under node that holds a tags.datadoghq.com/* key."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("annotations", "podAnnotations") and isinstance(v, dict) \
                    and any(str(a).startswith("tags.datadoghq.com/") for a in v):
                out.append(f"{where}.{k}")
            out += annotated(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += annotated(v, f"{where}[{i}]")
    return out


swept, found = 0, []
for path in sorted([*(REPO / "gitops").rglob("*.yaml"), *(REPO / "infra").glob("*values*.yaml")]):
    if "templates" in path.relative_to(REPO).parts:
        continue  # gitops/bootstrap/templates is Go template text, not YAML
    for i, d in enumerate(yaml.safe_load_all(path.read_text())):
        swept += 1
        found += annotated(d, f"{path.relative_to(REPO)}#{i}")
check(f"no annotations carry tags.datadoghq.com/* ({swept} documents swept)", swept > 100 and not found,
      "\n        ".join(found))
for comp, want in (("nodeAgent", "burritobot-datadog-agent"), ("clusterAgent", "burritobot-datadog-cluster-agent")):
    labels = (override.get(comp) or {}).get("labels") or {}
    check(f"the DatadogAgent's {comp} pods carry service={want} env={DD_ENV}",
          labels.get("tags.datadoghq.com/service") == want and labels.get("tags.datadoghq.com/env") == DD_ENV)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All Datadog sandbox naming checks passed.")
