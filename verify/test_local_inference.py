# ABOUTME: Render gate for the local-inference profile (#394, question 657): the vLLM it adds is what agentgateway's
# ABOUTME: /local route asks for, only that profile lists it, and it keeps the sister's measured shape. Offline.
"""Why this exists.

The /local route and the gateway-local-qwen3 ModelConfig were committed first and pointed at a server that
did not exist yet, so the toggle was half-built. This profile adds the server. The two halves meet only at
a host, a port and a model name, in three files, and a mismatch would show up as a 404 or a connection
refused from the gateway on a cluster built for exactly one demo. So they are checked against each other.

The second concern is containment. A 4-CPU, 10Gi model server is fine on one instructor cluster and a
disaster on fifty student nodes. Since #609 a profile is an explicit list, so containment is that no list but
values-local-inference.yaml names vllm-qwen3, and that list is otherwise full's.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import APPS, REPO, all_profiles, app_names, profiles  # noqa: E402

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

print("== only the local-inference profile lists it ==")
app = yaml.safe_load((APPS / "vllm-qwen3.yaml").read_text(encoding="utf-8").replace("{{ .Values.revision }}", "REV"))
check("the Application deploys gitops/manifests/vllm-qwen3 into the agent namespace, at the root's revision",
      app["spec"]["source"]["path"] == "gitops/manifests/vllm-qwen3" and app["spec"]["destination"]["namespace"] == "agent"
      and app["spec"]["source"]["targetRevision"] == "REV")
check("it syncs after the ai-layer that holds the gateway",
      int(app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])
      > int(yaml.safe_load((APPS / "ai-layer.yaml").read_text(encoding="utf-8").split("\nspec:", 1)[0])
            ["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]))
takers = [p for p in all_profiles() if "vllm-qwen3" in app_names(p)]
check(f"the profiles that list vllm-qwen3: {takers}", takers == ["local-inference"])
others = sorted(set(app_names("local-inference")) ^ set(app_names("full")))
check(f"otherwise it is the full build: the two lists differ by vllm-qwen3 alone {others}", others == ["vllm-qwen3"])
check("lab-platform.yaml does not present it, so labctl never builds it on a roster or attendee cluster",
      "local-inference" not in profiles() and "local-inference" not in (REPO / "lab-platform.yaml").read_text(encoding="utf-8"))
deploy_sh = (REPO / "infra/deploy-full-idp.sh").read_text(encoding="utf-8")
check("deploy-full-idp.sh local-inference picks values-local-inference.yaml",
      re.search(r'local-inference\)\s+VALUES="values-local-inference\.yaml"', deploy_sh) is not None)
print("== nothing else names the workload ==")
names = [p.relative_to(REPO).as_posix() for p in (REPO / "gitops").rglob("*.yaml")
         if "vllm-qwen3" in p.read_text(encoding="utf-8")]
check(f"only the Application, its manifests, the gateway route and the ModelConfig name vllm-qwen3 {names}",
      sorted(names) == ["gitops/ai-layer/agentgateway.yaml", "gitops/ai-layer/resources.yaml",
                        "gitops/bootstrap/apps/vllm-qwen3.yaml", "gitops/bootstrap/values-local-inference.yaml",
                        "gitops/manifests/vllm-qwen3/vllm-qwen3.yaml"])

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll local-inference checks passed.")
