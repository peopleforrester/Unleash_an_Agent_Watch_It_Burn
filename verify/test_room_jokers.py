# ABOUTME: Holds deploy_app's side of #685: every result is reported to the support desk's wall, a room Joker
# ABOUTME: (joker-<name>) runs tiny with a page of its own (#775), and is scaled to zero after the desk's window.
"""workshop-mcp's real deploy_app runs here against a stand-in for the Kubernetes API that records every call, and
reports to the real ticket site served on localhost. No cluster, no model.

Capacity (Michael, 2026-10-29): the public node allocates 110 pods with about 53 in use, so each room Joker is tiny
and is scaled to 0 replicas after JOKER_SCALE_DOWN_SECONDS (300 on the cluster); the Deployment stays as the proof.
Raising the pod cap is #686, deferred to the next node rebuild.

Each room Joker's own page (#775): deploy_app gives its pod the Deployment's name as hostname under the headless
jokers Service, the console proxies maintenance-shell-<cluster>/<name>/ to that one pod, and deploy_app's reply names
that address, which HC-666 asks the bot to hand over. The reaper scales through deployments/scale, which the
least-privilege Role (guard-agency-on) keeps, so a Joker that landed before the fix is still scaled down.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
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
    if status.get("rbac"):
        # The API server's own Status body for an RBAC refusal, as guard-agency-on's Role gets one.
        return 403, json.dumps({
            "kind": "Status", "apiVersion": "v1", "metadata": {}, "status": "Failure", "reason": "Forbidden",
            "message": 'deployments.apps "x" is forbidden: User "system:serviceaccount:agent:workshop-mcp" cannot '
                       'patch resource "deployments" in API group "apps" in the namespace "agent"', "code": 403})
    if status["code"] >= 400:
        # The API server's own Status body for a Kyverno deny, as the private cluster returns it.
        return status["code"], json.dumps({
            "kind": "Status", "apiVersion": "v1", "metadata": {}, "status": "Failure",
            "message": 'admission webhook "vpol.validate.kyverno.svc-fail" denied the request: Policy '
                       "restrict-image-registries failed: image ghcr.io/peopleforrester/festival-ops/maintenance-shell:busybox-1.38.0 is not from "
                       "an allowed registry", "reason": "Forbidden", "code": 403})
    return status["code"], "{}"


m._req = fake_req


def joker(name: str, resources: dict | None = None) -> str:
    c = {"name": "joker", "image": "ghcr.io/peopleforrester/festival-ops/maintenance-shell:busybox-1.38.0"}
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
scaled = lambda: [x for x in calls if x[0] == "PATCH"  # noqa: E731
                  and x[1] == f"/apis/apps/v1/namespaces/agent/deployments/joker-{SLUG}/scale"
                  and x[2] == {"spec": {"replicas": 0}}]
check("a merge patch on its scale subresource sets replicas to 0 (#775)", wait_for(lambda: bool(scaled()), 3),
      str(calls[-2:]))
check("nothing deletes it", not any(x[0] == "DELETE" for x in calls))

print("== each room Joker has a page of its own (#775) ==")
pod = applied["spec"]["template"]
check("its pod's hostname is the Deployment's name, under the jokers Service",
      pod["spec"].get("hostname") == f"joker-{SLUG}" and pod["spec"].get("subdomain") == m.ROOM_JOKER_SERVICE == "jokers",
      str(pod["spec"]))
check("and it is labeled into that Service, beside the model's own label and the workload label",
      pod["metadata"]["labels"] == {"app": f"joker-{SLUG}", m.WORKLOAD_LABEL: f"joker-{SLUG}", m.ROOM_JOKER_LABEL: "true"},
      str(pod["metadata"]))
check("with no public host the reply names no address", "https://" not in reply, reply)
m.PUBLIC_HOST = "attackme.agenticburn.com"
calls.clear()
reply = m.deploy_app(joker(f"joker-{SLUG}"))
want = f"https://maintenance-shell-attackme.burritobot.co/joker-{SLUG}/"
check("the reply names the person's own page, on the burritobot.co twin of the published maintenance-shell host",
      reply.endswith(f"Once its pod is ready it answers at {want}"), reply)
calls.clear()
reply = m.deploy_app(joker("joker-a.b"))
check("a Joker whose name is not one DNS label gets no hostname and no address",
      "https://" not in reply and "hostname" not in calls[0][2]["spec"]["template"]["spec"], reply)
docs = [d for d in __import__("yaml").safe_load_all((AI / "resources.yaml").read_text()) if d]
svc = next((d for d in docs if d.get("kind") == "Service" and d["metadata"]["name"] == m.ROOM_JOKER_SERVICE), {})
port = re.search(r"--env PORT=(\d+)", (REPO / "images/villains/build.sh").read_text())
check("resources.yaml ships the jokers Service: headless, selecting the label, on the Joker's PORT",
      svc.get("spec", {}).get("clusterIP") == "None" and svc["spec"].get("selector") == {m.ROOM_JOKER_LABEL: "true"}
      and port is not None and [p["port"] for p in svc["spec"].get("ports", [])] == [int(port.group(1))], str(svc))
conf = (AI / "console.conf").read_text()
srv = conf.split("server_name ~^maintenance-shell-[a-z0-9-]+\\.(?:agenticburn\\.com|burritobot\\.co)$;", 1)
loc = re.search(r'location ~ "(\^/\(\?<wib_joker>[^"]+)" \{(.*?)\n  \}', srv[1] if len(srv) == 2 else "", re.S)
check("the console's maintenance-shell server has a location for /joker-<name>/", loc is not None)
if loc:
    rx = re.compile(loc.group(1).replace("(?<", "(?P<"))
    check("it matches the address deploy_app names, with or without the slash",
          bool(rx.match(f"/joker-{SLUG}/")) and bool(rx.match(f"/joker-{SLUG}")))
    check("and no other path: not maintenance-shell's root, a dotted name or a deeper path",
          not any(rx.match(x) for x in ("/", "/maintenance-shell/", "/joker-a.b/", f"/joker-{SLUG}/x", "/joker-/")))
    body = loc.group(2)
    check("it proxies GET alone to that one pod, by its hostname under jokers, on the Joker's PORT",
          "limit_except GET { deny all; }" in body and port is not None
          and f"proxy_pass http://$wib_joker.jokers.agent.svc.cluster.local:{port.group(1)}/;" in body, body)
    check("a Joker that is not there, or scaled to zero, shows the console's nothing-yet page",
          "error_page 502 503 504 = @wib_c6_nothing_yet;" in body and "proxy_intercept_errors on;" in body)
m.PUBLIC_HOST = ""
time.sleep(0.6)  # the Jokers above are scaled down now, before the next section counts scale-downs

print("== the stage's maintenance-shell and other names are not room Jokers ==")
calls.clear()
m.deploy_app(joker("maintenance-shell"))
time.sleep(0.6)
applied = calls[0][2]
check("maintenance-shell keeps the replicas it asked for", applied["spec"]["replicas"] == 3)
check("and gets no room Joker hostname", "hostname" not in applied["spec"]["template"]["spec"])
check("and is never scaled down", not any(x[2] == {"spec": {"replicas": 0}} for x in calls))
check("the desk still hears about it, as an unnamed Joker",
      wait_for(lambda: any(r["name"] == "maintenance-shell" and r["who"] == "an unnamed Joker" for r in wall())))

print("== a refusal is reported as refused ==")
status["code"] = 403
# A refusal raises, so FastMCP answers it as an error result and the execute_tool span is marked (#712).
try:
    reply = m.deploy_app(joker(f"joker-{site.slug(site.NAME_SPACE[1])}"))
    raised = ""
except RuntimeError as e:
    reply, raised = "", str(e)
check("deploy_app raises on a refused deploy, with the refusal in the message",
      raised.startswith("deploy failed for Deployment/joker-") and "HTTP 403" in raised and not reply, raised or reply)
refused = lambda: [r for r in wall() if r["who"] == site.NAME_SPACE[1] and not r["ok"]]  # noqa: E731
check("the wall shows the refusal", wait_for(lambda: bool(refused())))
check("as one plain sentence naming the policy, not the API server's JSON (#685)",
      bool(refused()) and refused()[0]["detail"] == site.REFUSED_REGISTRY, str(refused()[:1]))

print("== least privilege's refusal is reported as one plain sentence too (#775) ==")
status["rbac"] = True
name3 = site.NAME_SPACE[3]
try:
    m.deploy_app(joker(f"joker-{site.slug(name3)}"))
    raised = ""
except RuntimeError as e:
    raised = str(e)
check("deploy_app raises on an RBAC refusal", "HTTP 403" in raised and "cannot patch resource" in raised, raised)
forbidden = lambda: [r for r in wall() if r["who"] == name3 and not r["ok"]]  # noqa: E731
check("the wall says the bot is not allowed to create it",
      wait_for(lambda: bool(forbidden())) and forbidden()[0]["detail"]
      == "Refused: the bot's ServiceAccount is not allowed to create that.", str(forbidden()[:1]))
status["rbac"] = False

print("== a desk that does not answer never fails a deploy ==")
status["code"] = 201
m.TICKET_SITE_URL = "http://127.0.0.1:9"
reply = m.deploy_app(joker(f"joker-{site.slug(site.NAME_SPACE[2])}"))
check("deploy_app still reports the deploy", reply.startswith("deployed Deployment/"), reply)

desk.shutdown()
# deploy_app starts daemon threads (the _report sender to the desk, and a short scale-down threading.Timer).
# If the interpreter finalizes while one of them holds stdout's lock, Python 3.13 aborts with SIGABRT (exit
# 134) at shutdown, which failed the gate after every check had passed (#779). Join every thread other than
# the main thread with a bounded timeout, then fail naming any still alive, so the run never exits while a
# _report sender or a scale-down Timer is still running. workshop-mcp-server.py itself is unchanged: it is
# long-lived and its scale-down Timers are rightly daemon threads.
_main = threading.main_thread()
for _t in [t for t in threading.enumerate() if t is not _main]:
    _t.join(timeout=5.0)
_still_alive = [t.name for t in threading.enumerate() if t is not _main and t.is_alive()]
check(f"no background thread outlives the test (#779): {_still_alive}", not _still_alive)
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Room Jokers land tiny, report to the desk and scale to zero.")
