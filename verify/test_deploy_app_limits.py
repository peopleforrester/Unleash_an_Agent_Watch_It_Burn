# ABOUTME: deploy_app gives every container the CPU and memory limits require-resource-limits asks for, so the
# ABOUTME: only policy the C2 villain breaks is restrict-image-registries, whatever Deployment the model writes (#538).
"""In Challenge 2 the model writes the villain's Deployment itself and hands it to workshop-mcp's deploy_app. Each
Kyverno ValidatingPolicy is its own webhook and the first to answer is the deny message read aloud. A Deployment
without limits breaks require-resource-limits as well as restrict-image-registries, so with both at Deny the
refusal could name the wrong policy. #529 fixed that for the probe and the C2 fallback; this holds the live path.

The server runs here as it runs in the pod, with a stand-in for tool_audit (the offline suite has no `mcp`) and the
Kubernetes API call captured instead of sent. verify/resource_limits.py reads the required keys from the policy.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import resource_limits  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = REPO / "gitops/ai-layer/workshop-mcp-server.py"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f": {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class _StandInMCP:
    def __init__(self, *a, **kw) -> None:
        pass

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp", SERVER)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

sent: list[dict] = []


def fake_req(method: str, path: str, body=None, content_type: str = "application/json"):
    if method == "GET":
        return 200, json.dumps({"resources": [{"kind": k, "name": n} for k, n in (
            ("Deployment", "deployments"), ("Pod", "pods"), ("CronJob", "cronjobs"), ("ConfigMap", "configmaps"))]})
    sent.append(json.loads(body))
    return 201, "{}"


m._req = fake_req
m._ns = lambda: "agent"


def deploy(obj: dict, as_yaml: bool = False) -> dict:
    sent.clear()
    reply = m.deploy_app(yaml.safe_dump(obj) if as_yaml else json.dumps(obj))
    check(f"deploy_app applies {obj['kind']}/{obj['metadata']['name']}", len(sent) == 1 and "deployed" in reply, reply)
    return sent[0] if sent else {}


VILLAIN = "docker.io/peopleforrester/promo-mascot:latest"


def villain(resources: dict | None = None, kind: str = "Deployment") -> dict:
    c = {"name": "promo-mascot", "image": VILLAIN}
    if resources is not None:
        c["resources"] = resources
    pod = {"containers": [c]}
    if kind == "Pod":
        return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "promo-mascot"}, "spec": pod}
    template = {"metadata": {"labels": {"app": "promo-mascot"}}, "spec": pod}
    if kind == "CronJob":
        return {"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": "promo-mascot"},
                "spec": {"schedule": "* * * * *", "jobTemplate": {"spec": {"template": template}}}}
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "promo-mascot"},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "promo-mascot"}}, "template": template}}


def pod_of(obj: dict) -> dict:
    return obj["spec"]["jobTemplate"]["spec"]["template"]["spec"] if obj.get("kind") == "CronJob" \
        else resource_limits.pod_spec(obj)


print("== the defaults are what require-resource-limits requires ==")
need = resource_limits.required()
check(f"_DEFAULT_LIMITS sets every key the policy requires ({sorted(need)})", need <= set(m._DEFAULT_LIMITS),
      f"defaults {sorted(m._DEFAULT_LIMITS)}")

print("== the stuck prompt's Deployment, as a model writes it without limits ==")
for as_yaml in (False, True):
    out = deploy(villain(), as_yaml=as_yaml)
    check(f"a {'YAML' if as_yaml else 'JSON'} Deployment with no resources leaves deploy_app with every limit set",
          bool(out) and resource_limits.missing(out) == [], f"{resource_limits.missing(out) if out else out}")
    check("the image is left as the model wrote it, so restrict-image-registries still refuses it",
          bool(out) and pod_of(out)["containers"][0]["image"] == VILLAIN)

print("== partial limits are completed, the model's own values kept ==")
out = deploy(villain({"requests": {"cpu": "5m"}, "limits": {"memory": "256Mi"}}))
res = pod_of(out)["containers"][0]["resources"] if out else {}
check("the missing cpu limit is filled in", res.get("limits", {}).get("cpu") == m._DEFAULT_LIMITS["cpu"], str(res))
check("the model's memory limit is kept", res.get("limits", {}).get("memory") == "256Mi", str(res))
check("the model's requests are kept", res.get("requests") == {"cpu": "5m"}, str(res))
out = deploy(villain({"limits": {"cpu": "2", "memory": "1Gi"}}))
check("limits the model set in full are left alone",
      bool(out) and pod_of(out)["containers"][0]["resources"] == {"limits": {"cpu": "2", "memory": "1Gi"}})
out = deploy(villain({"limits": None}))
check("an explicit null limits block is replaced by the defaults", bool(out) and resource_limits.missing(out) == [])

print("== every shape the policy judges, and every container ==")
out = deploy(villain(kind="Pod"))
check("a bare Pod gets the limits", bool(out) and resource_limits.missing(out) == [])
out = deploy(villain(kind="CronJob"))
check("a CronJob's job template gets the limits",
      bool(out) and all(need <= set(c["resources"]["limits"]) for c in pod_of(out)["containers"]))
two = villain()
two["spec"]["template"]["spec"]["containers"].append({"name": "sidecar", "image": "docker.io/library/busybox"})
out = deploy(two)
check("every container of a two-container Deployment gets the limits",
      bool(out) and len(pod_of(out)["containers"]) == 2 and resource_limits.missing(out) == [])
out = deploy({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "promo-copy"}, "data": {"a": "b"}})
check("a resource with no pod spec is applied unchanged", out.get("data") == {"a": "b"} and "spec" not in out)

print("== the defaults match the limits the probe's C2 manifest sets ==")
probe = (REPO / "verify/kubecon_probe.py").read_text(encoding="utf-8")
check("the probe's C2 manifest sets the same limits deploy_app defaults to",
      f'"limits": {{"cpu": "{m._DEFAULT_LIMITS["cpu"]}", "memory": "{m._DEFAULT_LIMITS["memory"]}"}}' in probe)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All deploy_app limit checks passed.")
