# ABOUTME: deploy_app lands a room Joker the API server would refuse with a 422 (#856): a re-apply keeps the live
# ABOUTME: selector, and a Joker still refused as written is applied once more as the plain Joker HC-666 asks for.
"""What was left of HC-666's failures once deploy_app read every manifest shape (#856, run 16959, 2026-11-04).

With run 16947's change running on the public bot, 19 HC-666 asks landed 11. Three were refused with a 422 at least
once, each a re-apply of joker-agatha-the-banshee, which was already on the cluster with the selector
{app: joker-agatha-the-banshee}, while every manifest the bot showed was a Deployment the API server takes. A
Deployment's selector cannot change once it exists, and the model picks its labels afresh on each ask. The 422's own
message was not seen: the desk keeps only "HTTP 422" and the run could not read the pod's logs (hecaton#508).

So the stand-in API server here refuses what the real one refuses for a Deployment: a selector that differs from the
live one ("field is immutable"), and a template label the label syntax does not admit, which is one shape a 422 on a
first create takes. A Kyverno denial (an admission webhook's, HTTP 400) and a 422 that names an admission webhook are
left as refused, since those are the lesson. Nothing here needs a cluster.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
import types

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def get_context(self):
        # No request in flight, as the real FastMCP has none outside its transport; deploy_app reads the
        # request's X-Witch-Name through it (#995) and so finds no name here.
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_reapply_422", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

NAME = "joker-agatha-the-banshee"
IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
DEPLOY_PATH = f"/apis/apps/v1/namespaces/agent/deployments/{NAME}"
DISCOVERY = {"/apis/apps/v1": [{"name": "deployments", "kind": "Deployment"}],
             "/api/v1": [{"name": "pods", "kind": "Pod"}]}
LABEL_VALUE = re.compile(r"^([A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$")


class StandInAPIServer:
    """Answers discovery and GET of the Joker, and refuses an apply for the reasons the API server refuses one."""

    def __init__(self, live_selector: dict | None = None, deny: str = ""):
        self.live_selector, self.deny = live_selector, deny
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, path, body=None, content_type=None):
        if method == "GET" and path in DISCOVERY:
            return 200, json.dumps({"resources": DISCOVERY[path]})
        obj = json.loads(body) if body else {}
        self.calls.append((method, path.split("?")[0], obj))
        if method == "GET" and path == DEPLOY_PATH:
            if self.live_selector is None:
                return 404, json.dumps({"kind": "Status", "code": 404, "reason": "NotFound"})
            return 200, json.dumps({"kind": "Deployment", "metadata": {"name": NAME},
                                    "spec": {"replicas": 0, "selector": self.live_selector}})
        if method == "PATCH" and path.startswith(DEPLOY_PATH + "?"):
            if self.deny:
                return self.deny_code, self.deny
            why = self.invalid(obj)
            if why:
                return 422, json.dumps({"kind": "Status", "code": 422, "reason": "Invalid",
                                        "message": f'Deployment.apps "{NAME}" is invalid: {why}'})
            return 200, body
        return 404, "{}"

    deny_code = 400

    def invalid(self, obj: dict) -> str:
        spec = obj.get("spec") or {}
        selector = spec.get("selector") or {}
        labels = ((spec.get("template") or {}).get("metadata") or {}).get("labels") or {}
        if self.live_selector is not None and selector != self.live_selector:
            return (f"spec.selector: Invalid value: {json.dumps(selector)}: field is immutable")
        for k, v in labels.items():
            if not isinstance(v, str) or not LABEL_VALUE.match(v):
                return f"spec.template.metadata.labels: Invalid value: {v!r}: a valid label must be ..."
        if any(labels.get(k) != v for k, v in (selector.get("matchLabels") or {}).items()):
            return "spec.template.metadata.labels: Invalid value: `selector` does not match template `labels`"
        return ""


reports: list[dict] = []
server._report = lambda name, ok, detail, image="", requested_by="": reports.append(  # noqa: E731
    {"name": name, "ok": ok, "detail": detail, "image": image, "requested_by": requested_by})
server.JOKER_SCALE_DOWN_SECONDS = 3600.0
server._ns = lambda: "agent"  # noqa: E731
server.PUBLIC_HOST = "attackme.agenticburn.com"


def manifest(labels: dict, selector: dict | None = None, container_name: str = "maintenance-shell") -> str:
    return json.dumps({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": NAME},
                       "spec": {"replicas": 1, "selector": {"matchLabels": selector if selector is not None
                                                            else labels},
                                "template": {"metadata": {"labels": labels},
                                             "spec": {"containers": [{"name": container_name, "image": IMAGE}]}}}})


def deploy(api: StandInAPIServer, text: str):
    server._req = api
    reports.clear()
    try:
        return server.deploy_app(text, "Agatha the Banshee"), None
    except Exception as e:  # noqa: BLE001
        return None, e


def applies(api: StandInAPIServer) -> list[dict]:
    return [c[2] for c in api.calls if c[0] == "PATCH" and "/scale" not in c[1]]


def landed(api: StandInAPIServer, reply, exc, label: str, applies_expected: int) -> dict:
    sent = applies(api)
    check(f"{label}: deploy_app says it is deployed, with the Joker's own page",
          exc is None and bool(reply) and reply.startswith(f"deployed Deployment/{NAME}")
          and f"https://maintenance-shell-attackme.burritobot.co/{NAME}/" in reply, f"{reply!r} {exc}")
    check(f"{label}: {applies_expected} apply(s) sent", len(sent) == applies_expected, f"{len(sent)}")
    check(f"{label}: the desk gets one row, ok, for {NAME}",
          len(reports) == 1 and reports[0]["ok"] and reports[0]["name"] == NAME
          and reports[0]["image"] == IMAGE, f"{reports}")
    final = sent[-1] if sent else {}
    check(f"{label}: the Deployment applied is one the API server takes", not api.invalid(final), api.invalid(final))
    pod = ((final.get("spec") or {}).get("template") or {}).get("spec") or {}
    check(f"{label}: the ticket's image, one replica, and the Joker's own page (hostname, jokers Service)",
          (pod.get("containers") or [{}])[0].get("image") == IMAGE and final["spec"].get("replicas") == 1
          and pod.get("hostname") == NAME and pod.get("subdomain") == server.ROOM_JOKER_SERVICE, json.dumps(final)[:300])
    labels = final["spec"]["template"]["metadata"]["labels"]
    check(f"{label}: the workload and room-Joker labels the jokers Service selects",
          labels.get(server.WORKLOAD_LABEL) == NAME and labels.get(server.ROOM_JOKER_LABEL) == "true", f"{labels}")
    return final


LIVE = {"matchLabels": {"app": NAME}}

print("== 1. a re-apply keeps the selector the live Joker has ==")
for label, labels in (("the model's labels are {app: joker}", {"app": "joker"}),
                      ("the model adds a tier label", {"app": NAME, "tier": "maintenance"}),
                      ("the model names its app after the witch", {"app": "agatha"})):
    api = StandInAPIServer(live_selector=LIVE)
    reply, exc = deploy(api, manifest(labels))
    final = landed(api, reply, exc, label, 1)
    check(f"{label}: the selector is the live one, and the model's own labels stay on the template",
          final.get("spec", {}).get("selector") == LIVE
          and all(final["spec"]["template"]["metadata"]["labels"].get(k) == v for k, v in labels.items() if k != "app"),
          json.dumps(final.get("spec", {}))[:300])

api = StandInAPIServer(live_selector=None)
reply, exc = deploy(api, manifest({"app": "joker"}))
final = landed(api, reply, exc, "a first create", 1)
check("a first create keeps the model's own selector", final.get("spec", {}).get("selector") == {"matchLabels": {"app": "joker"}},
      json.dumps(final.get("spec", {}))[:200])

print("== 2. a Joker refused with a 422 as written is applied as the plain Joker ==")
bad_value = {"app": NAME, "requested-by": "Agatha the Banshee"}
api = StandInAPIServer(live_selector=None)
reply, exc = deploy(api, manifest(bad_value, selector={"app": NAME}, container_name="Maintenance Shell"))
final = landed(api, reply, exc, "a template label with spaces and a container name the API server refuses", 2)
check("the plain Joker keeps the model's valid selector label and drops the one the API server refuses",
      final.get("spec", {}).get("selector") == {"matchLabels": {"app": NAME}}
      and "requested-by" not in final["spec"]["template"]["metadata"]["labels"], json.dumps(final.get("spec", {}))[:300])
check("its one container is named after the Joker", final["spec"]["template"]["spec"]["containers"][0]["name"] == NAME)
check("and has the room Joker's tiny resources",
      final["spec"]["template"]["spec"]["containers"][0].get("resources") == server.JOKER_RESOURCES)

api = StandInAPIServer(live_selector=None)
reply, exc = deploy(api, manifest({"app": "Agatha the Banshee"}))
final = landed(api, reply, exc, "a selector whose only label the API server refuses", 2)
check("the plain Joker selects app: <its name>", final.get("spec", {}).get("selector") == {"matchLabels": {"app": NAME}},
      json.dumps(final.get("spec", {}))[:200])

api = StandInAPIServer(live_selector=LIVE)
reply, exc = deploy(api, manifest({"app": NAME, "owner": "Agatha the Banshee"}))
final = landed(api, reply, exc, "a re-apply with a label the API server refuses", 2)
check("the plain re-apply keeps the live selector", final.get("spec", {}).get("selector") == LIVE)

print("== 3. what is the lesson, or not a room Joker, is still refused ==")
api = StandInAPIServer(live_selector=None, deny=json.dumps({
    "kind": "Status", "code": 400, "message": 'admission webhook "validate.kyverno.svc-fail" denied the request: '
                                             "Policy restrict-image-registries failed"}))
reply, exc = deploy(api, manifest({"app": NAME}))
check("a Kyverno denial is raised as the refusal, with one apply and one refused row",
      reply is None and "restrict-image-registries" in str(exc) and len(applies(api)) == 1
      and len(reports) == 1 and not reports[0]["ok"], f"{reply!r} {exc} {reports}")

api = StandInAPIServer(live_selector=None, deny=json.dumps({
    "kind": "Status", "code": 422, "message": 'admission webhook "pod-policy.example" denied the request'}))
api.deny_code = 422
reply, exc = deploy(api, manifest({"app": NAME}))
check("a 422 an admission webhook gave is not retried", reply is None and len(applies(api)) == 1, f"{reply!r} {exc}")


other = "maintenance-shell"
api = StandInAPIServer(live_selector=None)
DEPLOY_PATH_OTHER = f"/apis/apps/v1/namespaces/agent/deployments/{other}"


def other_req(method, path, body=None, content_type=None):
    if method == "GET" and path in DISCOVERY:
        return 200, json.dumps({"resources": DISCOVERY[path]})
    if method == "PATCH" and path.startswith(DEPLOY_PATH_OTHER + "?"):
        api.calls.append((method, DEPLOY_PATH_OTHER, json.loads(body)))
        return 422, json.dumps({"kind": "Status", "code": 422, "message": "spec.template.metadata.labels: Invalid"})
    return 404, "{}"


server._req = other_req
reports.clear()
try:
    reply, exc = server.deploy_app(manifest({"app": "x y"}).replace(NAME, other), ""), None
except Exception as e:  # noqa: BLE001
    reply, exc = None, e
check("a Deployment that is not a room Joker is refused with the API server's 422, applied once",
      reply is None and "HTTP 422" in str(exc) and len(api.calls) == 1, f"{reply!r} {exc} {api.calls}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("A room Joker the API server would refuse with a 422 lands: the live selector is kept, and the plain Joker is "
      "applied when the model's own is refused.")
