# ABOUTME: Live half of #773 on a cluster: deployments-<cluster> serves the deployments page and none of the desk, and
# ABOUTME: a room deployment's public image is admitted or refused exactly as restrict-image-registries is set there.
# SUITE: e2e (needs kubectl, CONTEXT naming a cluster that runs the ai-layer, and the network to reach its public host)
"""Usage: CONTEXT=<kube-context> python3 verify/test_deployments_page_live.py

1. The fake-ticket site answers /deployments.json in the agent namespace, read over a kubectl port-forward to
   svc/fake-ticket :8080 (verify/kube_forward.py), which goes through the kubelet. The API server's service proxy
   dials the pod from the control plane, and neither KubeCon cluster's node security group admits that on 8080:
   both lack #869's rule, so the proxy read timed out on both (#998).
2. The cluster's public host, from the cluster-identity ConfigMap, has a deployments-<label> twin that serves the
   page through the console (fleet.sh routes publishes it from WIB_VILLAIN_HOSTS), and a desk page under that name is
   a 404.
3. A server-side dry run, as workshop-mcp, of the Deployment deploy_app makes from "deploy nginx" (one replica, the
   room's resources, Docker's official nginx moved to public.ecr.aws, #992) is admitted where restrict-image-registries is Audit or absent (the public
   cluster, the attack) and refused by it where it is Deny (the private cluster, the fix). Nothing is created.

2b. The chat request's witch name reaches workshop-mcp without the model (#995): the Agent CR's workshop-mcp entry
   names X-Witch-Name in allowedHeaders, and kagent rendered it into the agent's config Secret.

What it leaves to a person: a real chat on a cluster whose guard-proxy pin sends X-Witch-Name (the guard-proxy half of
#995), its deploy showing on deployments.<domain> under the sender's witch name, and the chat page's "see your
deployments" link appearing.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import types
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import kube_forward  # noqa: E402

CONTEXT = os.environ.get("CONTEXT", "")
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("The deployments page and the room's public image hold on this cluster.")


def kubectl(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """kubectl on CONTEXT; one that runs past 60 s is a failed call naming the timeout, so its check fails, never a
    traceback that ends the run before the later checks (2026-11-06: the service proxy hung on both clusters)."""
    cmd = ["kubectl", "--context", CONTEXT, *args]
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"kubectl {' '.join(args)[:120]} timed out after 60 s")


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def get_context(self):
        # No request in flight, as the real FastMCP has none outside its transport; deploy_app reads the
        # request's X-Witch-Name through it (#995) and so finds no name here.
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        return lambda f: f


check("kubectl is on PATH", shutil.which("kubectl") is not None)
check("CONTEXT is set (the kube-context of a cluster running the ai-layer)", bool(CONTEXT))
if failures:
    finish()
check(f"cluster for context {CONTEXT} is reachable", kubectl("get", "--raw", "/readyz").returncode == 0)
if failures:
    finish()

print("== 1. the fake-ticket site answers /deployments.json ==")
status, body, err = kube_forward.get(["kubectl", "--context", CONTEXT], "agent", "svc/fake-ticket", 8080,
                                     "/deployments.json")
try:
    listed = json.loads(body) if status == "200" else None
except ValueError:
    listed = None
check("it answers a JSON list over a port-forward to svc/fake-ticket :8080", isinstance(listed, list),
      err or f"HTTP {status}: {body.strip()[:200]}")
if isinstance(listed, list):
    print(f"  INFO  /deployments.json lists {len(listed)} deployment(s)")

print("== 2. deployments-<cluster> serves the page through the console ==")
r = kubectl("-n", "agent", "get", "configmap", "cluster-identity", "-o", "jsonpath={.data.public-host}")
public = r.stdout.strip()
check("the cluster-identity ConfigMap names this cluster's public host", r.returncode == 0 and bool(public),
      r.stderr.strip()[:200])
if public:
    host = f"deployments-{public}"
    try:
        with urllib.request.urlopen(f"https://{host}/", timeout=20) as resp:
            page = resp.read().decode("utf-8", "replace")
        check(f"https://{host}/ is the deployments page", "Everything BurritoBot deployed" in page)
        check("and names no Joker", "joker" not in page.lower())
        check("each line reads '<witch name> deployed <image short name> at <time>', 'Someone' with no name (#995)",
              "b.textContent=x.witch||'Someone';" in page and "createTextNode(' deployed ')" in page
              and "deployed by" not in page)
        check("with the full image as the short name's hover text", "c.title=x.image;" in page)
    except (urllib.error.URLError, TimeoutError) as e:
        check(f"https://{host}/ answers", False, f"{type(e).__name__}: {e}")
    try:
        urllib.request.urlopen(f"https://{host}/HC-666", timeout=20)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, TimeoutError) as e:
        code = f"{type(e).__name__}: {e}"
    check("a desk page under that name is a 404", code == 404, str(code))

print("== 2b. the chat request's witch name reaches workshop-mcp, the kagent half (#995) ==")
r = kubectl("-n", "agent", "get", "agent", "workshop-agent", "-o", "json")
try:
    tools = {(t.get("mcpServer") or {}).get("name"): t.get("mcpServer") or {}
             for t in json.loads(r.stdout)["spec"]["declarative"]["tools"]} if r.returncode == 0 else {}
except (ValueError, KeyError):
    tools = {}
check("the Agent CR's workshop-mcp entry names X-Witch-Name in allowedHeaders",
      "X-Witch-Name" in (tools.get("workshop-mcp", {}).get("allowedHeaders") or []), r.stderr.strip()[:200])
r = kubectl("-n", "agent", "get", "secret", "workshop-agent", "-o", "jsonpath={.data.config\\.json}")
try:
    rendered = json.loads(base64.b64decode(r.stdout)) if r.returncode == 0 else {}
except ValueError:
    rendered = {}
mcp_tools = [t for t in rendered.get("http_tools") or [] if "deploy_app" in (t.get("tools") or [])]
check("kagent rendered it into the agent's config Secret, which the ADK runtime reads",
      bool(mcp_tools) and "X-Witch-Name" in (mcp_tools[0].get("allowed_headers") or []),
      str([t.get("allowed_headers") for t in mcp_tools]))

print("== 3. the room's nginx is admitted or refused as restrict-image-registries is set here ==")
sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_live", REPO / "gitops/ai-layer/workshop-mcp-server.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
obj = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "tron", "namespace": "agent"},
       "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "tron"}},
                "template": {"metadata": {"labels": {"app": "tron", m.WORKLOAD_LABEL: "tron"}},
                             "spec": {"containers": [{"name": "tron", "image": "nginx"}]}}}}
m._move_off_docker_hub(obj, "Deployment/tron")
m._default_limits(obj)
if m._room_workload(obj):
    m._shrink_room_deployment(obj)
check("the manifest is deploy_app's: Docker's official nginx on public.ecr.aws, one replica",
      obj["spec"]["template"]["spec"]["containers"][0]["image"] == m.OFFICIAL_MIRROR + "nginx:latest"
      and obj["spec"]["replicas"] == 1)
r = kubectl("get", "validatingpolicies.policies.kyverno.io", "restrict-image-registries", "-o",
            "jsonpath={.spec.validationActions}")
actions = r.stdout.strip() if r.returncode == 0 else ""
denies = "Deny" in actions
print(f"  INFO  restrict-image-registries validationActions here: {actions or '(not installed)'}")
r = kubectl("--as=system:serviceaccount:agent:workshop-mcp", "-n", "agent", "create", "-f", "-",
            "--dry-run=server", "-o", "name", stdin=json.dumps(obj))
out = (r.stdout + r.stderr).strip()
if denies:
    check("at Deny, the room's image is refused, and the refusal names restrict-image-registries",
          r.returncode != 0 and "restrict-image-registries" in out, out[:300])
else:
    check("with no Deny, the room's image is admitted (the attack lands)", r.returncode == 0, out[:300])
finish()
