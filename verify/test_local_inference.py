# ABOUTME: Render gate for the local-inference profile (#394, question 657): the vLLM it adds is what agentgateway's
# ABOUTME: /local route asks for, it is taken by that one root only, and it keeps the sister's measured shape. Offline.
"""Why this exists.

The /local route and the gateway-local-qwen3 ModelConfig were committed first and pointed at a server that
did not exist yet, so the toggle was half-built. This profile adds the server. The two halves meet only at
a host, a port and a model name, in three files, and a mismatch would show up as a 404 or a connection
refused from the gateway on a cluster built for exactly one demo. So they are checked against each other.

The second concern is containment. A 4-CPU, 10Gi model server is fine on one instructor cluster and a
disaster on fifty student nodes. Every fleet root takes gitops/apps by glob, which is why the vLLM
Application lives in gitops/opt-in/local-inference instead, and why this checks that no root but the
local-inference one sources that directory.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
OPT_IN = "gitops/opt-in/local-inference"
MANIFESTS = REPO / "gitops/manifests/vllm-qwen3/vllm-qwen3.yaml"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


docs = [d for d in yaml.safe_load_all(MANIFESTS.read_text(encoding="utf-8")) if d]
deploy = next(d for d in docs if d["kind"] == "Deployment")
svc = next(d for d in docs if d["kind"] == "Service")
pod = deploy["spec"]["template"]["spec"]
c = pod["containers"][0]
args = c["args"]

gw_docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/agentgateway.yaml").read_text(encoding="utf-8")) if d]
cm = next(d for d in gw_docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "agentgateway-config")
config = yaml.safe_load(cm["data"]["config.yaml"])
bind = next(b for b in config["binds"] if b["port"] == 3002)
routes = [r for l in bind["listeners"] for r in l["routes"]]
local = next(r for r in routes if any(m.get("path", {}).get("pathPrefix") == "/local" for m in r.get("matches", [])))
ai = local["backends"][0]["ai"]

print("== the server is what the /local route asks for ==")
host, port = ai["hostOverride"].rsplit(":", 1)
check(f"the route's host {host} is this Service", host == f"{svc['metadata']['name']}.{svc['metadata']['namespace']}.svc.cluster.local")
check(f"on port {port}, which reaches the container's port",
      [p["port"] for p in svc["spec"]["ports"]] == [int(port)]
      and svc["spec"]["ports"][0]["targetPort"] in ("http", 8000) and "--port=8000" in args)
check("the Service selects the Deployment's pods",
      svc["spec"]["selector"].items() <= deploy["spec"]["template"]["metadata"]["labels"].items())
model = ai["provider"]["openAI"]["model"]
check(f"vLLM serves the model name the route requests ({model})", f"--served-model-name={model}" in args)
mcs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8"))
       if d and d.get("kind") == "ModelConfig" and d["metadata"]["name"] == "gateway-local-qwen3"]
check("the gateway-local-qwen3 ModelConfig points at the /local route",
      len(mcs) == 1 and mcs[0]["spec"]["openAI"]["baseUrl"].endswith(":3002/local/v1"))
check("tool calling is on: kagent sends tool_choice=auto on every request",
      "--enable-auto-tool-choice" in args and "--tool-call-parser=hermes" in args)

print("== it keeps the shape the sister measured on the same node type ==")
check("requests 4 CPU / 10Gi, limits 6 CPU / 16Gi",
      c["resources"] == {"requests": {"cpu": "4", "memory": "10Gi"}, "limits": {"cpu": "6", "memory": "16Gi"}})
check("KV cache 2 GiB, the value paired with the 16Gi limit",
      {"name": "VLLM_CPU_KVCACHE_SPACE", "value": "2"} in c["env"])
sc = c["securityContext"]
check("non-root at a numeric uid, every capability dropped but SYS_NICE",
      sc["runAsNonRoot"] is True and isinstance(sc["runAsUser"], int) and sc["capabilities"] == {"drop": ["ALL"], "add": ["SYS_NICE"]}
      and sc["allowPrivilegeEscalation"] is False)
dshm = next((v for v in pod["volumes"] if v["name"] == "dshm"), {})
check("a memory-backed /dev/shm, without which it crash-loops",
      dshm.get("emptyDir", {}).get("medium") == "Memory" and {"name": "dshm", "mountPath": "/dev/shm"} in c["volumeMounts"])
check("the image is pinned by digest", re.search(r"@sha256:[0-9a-f]{64}$", c["image"]) is not None)
check("startup, readiness and liveness probes, the startup one wide enough for a CPU model load",
      all(k in c for k in ("startupProbe", "readinessProbe", "livenessProbe"))
      and c["startupProbe"]["periodSeconds"] * c["startupProbe"]["failureThreshold"] >= 600)
check("Recreate, so an update never schedules a second 10Gi pod beside the first",
      deploy["spec"]["strategy"]["type"] == "Recreate")

print("== only the local-inference root takes it ==")
app = yaml.safe_load((REPO / OPT_IN / "vllm-qwen3.yaml").read_text(encoding="utf-8"))
check("the opt-in Application deploys gitops/manifests/vllm-qwen3 into the agent namespace",
      app["spec"]["source"]["path"] == "gitops/manifests/vllm-qwen3" and app["spec"]["destination"]["namespace"] == "agent")
check("nothing in gitops/apps deploys it (every fleet root takes that directory by glob)",
      not any("vllm-qwen3" in p.read_text(encoding="utf-8") for p in (REPO / "gitops/apps").glob("*.yaml")))
takers = []
for root in sorted((REPO / "gitops/bootstrap").glob("*/*.yaml")):
    doc = yaml.safe_load(root.read_text(encoding="utf-8"))
    if any(s.get("path") == OPT_IN for s in doc["spec"]["sources"]):
        takers.append(root.parent.name)
check(f"the roots that source {OPT_IN}: {takers}", takers == ["local-inference"])
full = yaml.safe_load((REPO / "gitops/bootstrap/full/app-of-apps.yaml").read_text(encoding="utf-8"))
li = yaml.safe_load((REPO / "gitops/bootstrap/local-inference/app-of-apps-local-inference.yaml").read_text(encoding="utf-8"))
sel = lambda d: next(s for s in d["spec"]["sources"] if s["path"] == "gitops/apps")["directory"]  # noqa: E731
check("otherwise it is the full build: the same gitops/apps selection", sel(full) == sel(li))
fleet = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
check("fleet.sh arms its guardrails as it does for full", '"${profile}" == "local-inference"' in fleet)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll local-inference checks passed.")
