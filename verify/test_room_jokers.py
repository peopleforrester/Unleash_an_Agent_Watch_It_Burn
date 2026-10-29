# ABOUTME: Holds deploy_app's side of #685: every result is reported to the support desk's wall, a room Joker
# ABOUTME: (joker-<name>) runs tiny, and it is scaled to zero replicas after the desk's window so 300 fit one node.
"""workshop-mcp's real deploy_app runs here against a stand-in for the Kubernetes API that records every call, and
reports to the real ticket site served on localhost. No cluster, no model.

Capacity (Michael, 2026-10-29): the public node allocates 110 pods with about 53 in use, so each room Joker is tiny
and is scaled to 0 replicas after JOKER_SCALE_DOWN_SECONDS (300 on the cluster); the Deployment stays as the proof.
Raising the pod cap is #686, deferred to the next node rebuild.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import threading
import time
import types
import urllib.request
from http.server import ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f


site = load("ticket_site_jokers", AI / "ticket_site.py")
site.Handler.log_message = lambda *a: None
desk = ThreadingHTTPServer(("127.0.0.1", 0), site.Handler)
threading.Thread(target=desk.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{desk.server_address[1]}"

sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
os.environ["JOKER_SCALE_DOWN_SECONDS"] = "0.3"
m = load("workshop_mcp_jokers", AI / "workshop-mcp-server.py")
os.environ.pop("JOKER_SCALE_DOWN_SECONDS", None)
m._ns = lambda: "agent"
m.TICKET_SITE_URL = DESK
calls: list[tuple[str, str, dict]] = []
status = {"code": 201}


def fake_req(method: str, path: str, body=None, content_type: str = "application/json"):
    if method == "GET":
        return 200, json.dumps({"resources": [{"kind": "Deployment", "name": "deployments"}]})
    calls.append((method, path.split("?")[0], json.loads(body) if body else {}))
    if status["code"] >= 400:
        return status["code"], '{"message":"admission webhook denied: restrict-image-registries"}'
    return status["code"], "{}"


m._req = fake_req


def joker(name: str, resources: dict | None = None) -> str:
    c = {"name": "joker", "image": "docker.io/peopleforrester/joker:latest"}
    if resources is not None:
        c["resources"] = resources
    return json.dumps({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name},
                       "spec": {"replicas": 3, "selector": {"matchLabels": {"app": name}},
                                "template": {"metadata": {"labels": {"app": name}}, "spec": {"containers": [c]}}}})


def wall() -> list[dict]:
    with urllib.request.urlopen(f"{DESK}/wall.json", timeout=5) as r:
        return json.load(r)


def wait_for(cond, seconds: float = 3.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


NAME = site.NAME_SPACE[0]
SLUG = site.slug(NAME)

print("== a room Joker lands, tiny, and the desk hears about it ==")
reply = m.deploy_app(joker(f"joker-{SLUG}", {"limits": {"cpu": "4", "memory": "8Gi"}}))
check("deploy_app reports success", reply.startswith(f"deployed Deployment/joker-{SLUG}"), reply)
applied = calls[0][2]
c = applied["spec"]["template"]["spec"]["containers"][0]
check("a room Joker runs one replica, whatever the manifest asked", applied["spec"]["replicas"] == 1)
check("and tiny: requests 5m CPU and 16Mi, limits 20m and 32Mi, whatever the manifest asked",
      c["resources"] == {"requests": {"cpu": "5m", "memory": "16Mi"}, "limits": {"cpu": "20m", "memory": "32Mi"}},
      str(c["resources"]))
check("the wall shows it under the visitor's name",
      wait_for(lambda: any(r["who"] == NAME and r["ok"] for r in wall())), str(wall()))

print("== after the window it is scaled to zero, and the Deployment stays ==")
scaled = lambda: [x for x in calls if x[0] == "PATCH" and x[1].endswith(f"/deployments/joker-{SLUG}")  # noqa: E731
                  and x[2] == {"spec": {"replicas": 0}}]
check("a merge patch sets replicas to 0", wait_for(lambda: bool(scaled()), 3), str(calls[-2:]))
check("nothing deletes it", not any(x[0] == "DELETE" for x in calls))

print("== the stage's maintenance-shell and other names are not room Jokers ==")
calls.clear()
m.deploy_app(joker("maintenance-shell"))
time.sleep(0.6)
applied = calls[0][2]
check("maintenance-shell keeps the replicas it asked for", applied["spec"]["replicas"] == 3)
check("and is never scaled down", not any(x[2] == {"spec": {"replicas": 0}} for x in calls))
check("the desk still hears about it, as an unnamed Joker",
      wait_for(lambda: any(r["name"] == "maintenance-shell" and r["who"] == "an unnamed Joker" for r in wall())))

print("== a refusal is reported as refused ==")
status["code"] = 403
reply = m.deploy_app(joker(f"joker-{site.slug(site.NAME_SPACE[1])}"))
check("deploy_app says it failed", "deploy failed" in reply, reply)
check("the wall shows the refusal with the admission message",
      wait_for(lambda: any(r["who"] == site.NAME_SPACE[1] and not r["ok"] and "restrict-image-registries" in r["detail"]
                           for r in wall())))

print("== a desk that does not answer never fails a deploy ==")
status["code"] = 201
m.TICKET_SITE_URL = "http://127.0.0.1:9"
reply = m.deploy_app(joker(f"joker-{site.slug(site.NAME_SPACE[2])}"))
check("deploy_app still reports the deploy", reply.startswith("deployed Deployment/"), reply)

desk.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Room Jokers land tiny, report to the desk and scale to zero.")
