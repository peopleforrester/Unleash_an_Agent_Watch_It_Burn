# ABOUTME: deploy_app lands a room Joker whose manifest carries a field a Deployment does not declare (#856, run
# ABOUTME: 17687): the call's requested_by written into it, or the pod spec at spec.spec, which the API server refuses.
"""What was left of HC-666's failures once the 422 was covered (#856, run 17687, 2026-11-05).

The public bot's workshop-mcp log (watch-it-burn-community, from the pod's start at 2026-11-04 21:08 UTC to 2026-11-05
20:30 UTC) holds 19 deploy_app calls that named a joker-<name>: 14 landed, and all five that failed were one shape.
The model wrote the call's own requested_by into the manifest, as a top-level key beside apiVersion and kind, and left
the argument empty. The API server's server-side apply answers a field a Deployment does not declare with HTTP 500:

    failed to create typed patch object (agent/joker-isolde-the-troll; apps/v1, Kind=Deployment):
    .requested_by: field not declared in schema

Of the six HC-666 asks this run then sent in a row (2026-11-05 20:34 to 20:35 UTC), the second failed with the same
500 on another shape: the model closed the template after its metadata and wrote the pod's spec beside it, at
spec.spec (".spec.spec: field not declared in schema").

The manifests below are the log's own, byte for byte: joker-isolde-the-troll at 21:20:39 and 21:20:41 on 2026-11-04;
joker-agatha-the-banshee with labels at 15:36:43 and without at 15:40:28 and 16:28:49 on 2026-11-05; and the
spec.spec one at 20:35:04. The stand-in API server refuses what the real one refuses for them, with that 500: a
field a Deployment, its spec or its container does not have. Nothing here needs a cluster.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
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

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_requested_by_in_manifest", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
DISCOVERY = {"/apis/apps/v1": [{"name": "deployments", "kind": "Deployment"}],
             "/api/v1": [{"name": "pods", "kind": "Pod"}]}
TOP = {"apiVersion", "kind", "metadata", "spec", "status"}
CONTAINER = {"name", "image", "command", "args", "resources", "ports", "env", "securityContext", "imagePullPolicy",
             "volumeMounts", "workingDir", "readinessProbe", "livenessProbe"}

# The workshop-mcp log's tool_input.manifest for each failed call, as the model sent it (requested_by was empty).
ISOLDE = ('{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"joker-isolde-the-troll"},"spec":{"replicas":1,'
          '"template":{"spec":{"containers":[{"name":"maintenance-shell","image":"registry.burritobot.co/burritobot/'
          'maintenance-shell:busybox-1.38.0"}]}}},"requested_by":"Isolde the Troll"}')
AGATHA_LABELLED = ('{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"joker-agatha-the-banshee","labels":'
                   '{"app":"maintenance-shell"}},"spec":{"replicas":1,"selector":{"matchLabels":{"app":'
                   '"maintenance-shell"}},"template":{"metadata":{"labels":{"app":"maintenance-shell"}},"spec":'
                   '{"containers":[{"name":"maintenance-shell","image":"registry.burritobot.co/burritobot/'
                   'maintenance-shell:busybox-1.38.0"}]}}},"requested_by":"Agatha the Banshee"}')
AGATHA_BARE = ('{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"joker-agatha-the-banshee"},"spec":'
               '{"replicas":1,"template":{"spec":{"containers":[{"name":"maintenance-shell","image":'
               '"registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"}]}}},"requested_by":'
               '"Agatha the Banshee"}')
# The second of this run's six asks (20:35:04), requested_by given as the argument.
SPEC_SPEC = ('{"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "joker-agatha-the-banshee"}, "spec": '
             '{"replicas": 1, "template": {"metadata": {"labels": {"app": "joker-agatha-the-banshee"}}}, "spec": '
             '{"containers": [{"name": "maintenance-shell", "image": "registry.burritobot.co/burritobot/'
             'maintenance-shell:busybox-1.38.0"}]}}}')
WORKLOAD_SPEC = {"replicas", "selector", "template", "strategy", "minReadySeconds", "revisionHistoryLimit", "paused",
                 "progressDeadlineSeconds"}


class StandInAPIServer:
    """Answers discovery, has no live Joker, and refuses an apply carrying a field a Deployment does not declare."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, path, body=None, content_type=None):
        if method == "GET" and path in DISCOVERY:
            return 200, json.dumps({"resources": DISCOVERY[path]})
        obj = json.loads(body) if body else {}
        self.calls.append((method, path.split("?")[0], obj))
        if method == "GET":
            return 404, json.dumps({"kind": "Status", "code": 404, "reason": "NotFound"})
        if method == "PATCH" and "/deployments/" in path:
            why = self.undeclared(obj)
            if why:
                name = obj["metadata"]["name"]
                return 500, json.dumps({"kind": "Status", "apiVersion": "v1", "metadata": {}, "status": "Failure",
                                        "message": f"failed to create typed patch object (agent/{name}; apps/v1, "
                                                   f"Kind=Deployment): {why}: field not declared in schema",
                                        "code": 500})
            return 200, body
        return 404, "{}"

    @staticmethod
    def undeclared(obj: dict) -> str:
        for key in obj:
            if key not in TOP:
                return f".{key}"
        for key in obj.get("spec") or {}:
            if key not in WORKLOAD_SPEC:
                return f".spec.{key}"
        pod =((obj.get("spec") or {}).get("template") or {}).get("spec") or {}
        for i, c in enumerate(pod.get("containers") or []):
            for key in c:
                if key not in CONTAINER:
                    return f".spec.template.spec.containers[name=\"{c.get('name')}\"].{key}"
        return ""


reports: list[dict] = []
server._report = lambda name, ok, detail, image="", requested_by="": reports.append(  # noqa: E731
    {"name": name, "ok": ok, "detail": detail, "image": image, "requested_by": requested_by})
server.JOKER_SCALE_DOWN_SECONDS = 3600.0
server._ns = lambda: "agent"  # noqa: E731
server.PUBLIC_HOST = "attackme.agenticburn.com"


def deploy(text: str, requested_by: str = ""):
    api = StandInAPIServer()
    server._req = api
    reports.clear()
    try:
        return api, server.deploy_app(text, requested_by), None
    except Exception as e:  # noqa: BLE001
        return api, None, e


def applies(api: StandInAPIServer) -> list[dict]:
    return [c[2] for c in api.calls if c[0] == "PATCH" and "/scale" not in c[1]]


def landed(label: str, text: str, name: str, who: str, applies_expected: int = 1, requested_by: str = "") -> dict:
    api, reply, exc = deploy(text, requested_by)
    sent = applies(api)
    check(f"{label}: deploy_app says {name} is deployed, with its own page",
          exc is None and bool(reply) and reply.startswith(f"deployed Deployment/{name}")
          and f"https://maintenance-shell-attackme.burritobot.co/{name}/" in reply, f"{reply!r} {exc}")
    check(f"{label}: {applies_expected} apply(s) sent", len(sent) == applies_expected, f"{len(sent)}")
    final = sent[-1] if sent else {}
    check(f"{label}: the Deployment applied declares only fields a Deployment has",
          bool(final) and not StandInAPIServer.undeclared(final), StandInAPIServer.undeclared(final))
    check(f"{label}: the desk gets one ok row for {name}, credited to {who!r}",
          len(reports) == 1 and reports[0]["ok"] and reports[0]["name"] == name
          and reports[0]["requested_by"] == who and reports[0]["image"] == IMAGE, f"{reports}")
    pod = ((final.get("spec") or {}).get("template") or {}).get("spec") or {}
    check(f"{label}: the ticket's image and the Joker's own hostname",
          (pod.get("containers") or [{}])[0].get("image") == IMAGE and pod.get("hostname") == name,
          json.dumps(final)[:300])
    return final


print("== 0. the log's manifests are what the API server refused ==")
for label, text in (("joker-isolde-the-troll", ISOLDE), ("joker-agatha-the-banshee, labelled", AGATHA_LABELLED),
                    ("joker-agatha-the-banshee, bare", AGATHA_BARE)):
    obj = json.loads(text)
    check(f"{label}: parses as JSON, with requested_by beside apiVersion and kind",
          "requested_by" in obj and obj["kind"] == "Deployment", text[:120])
    check(f"{label}: the stand-in refuses it as written with the log's 500",
          StandInAPIServer.undeclared(obj) == ".requested_by")
check("the spec.spec manifest parses as JSON, with the pod spec beside the template",
      "spec" in json.loads(SPEC_SPEC)["spec"] and "spec" not in json.loads(SPEC_SPEC)["spec"]["template"])
check("the stand-in refuses it as written with the log's 500",
      StandInAPIServer.undeclared(json.loads(SPEC_SPEC)) == ".spec.spec")

print("== 1. requested_by written into the manifest is the argument ==")
landed("Isolde's manifest, from the log", ISOLDE, "joker-isolde-the-troll", "Isolde the Troll")
landed("Agatha's labelled manifest, from the log", AGATHA_LABELLED, "joker-agatha-the-banshee", "Agatha the Banshee")
landed("Agatha's bare manifest, from the log", AGATHA_BARE, "joker-agatha-the-banshee", "Agatha the Banshee")
landed("the same, as YAML", "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: joker-agatha-the-banshee\n"
       "spec:\n  replicas: 1\n  template:\n    spec:\n      containers:\n      - name: maintenance-shell\n"
       f"        image: {IMAGE}\nrequested_by: Agatha the Banshee\n", "joker-agatha-the-banshee", "Agatha the Banshee")
landed("requestedBy, camel-cased", AGATHA_BARE.replace('"requested_by"', '"requestedBy"'), "joker-agatha-the-banshee",
       "Agatha the Banshee")
landed("the argument wins when both are given", ISOLDE, "joker-isolde-the-troll", "Isolde the Troll",
       requested_by="Isolde the Troll")
landed("an argument other than the manifest's key stays the argument", ISOLDE, "joker-isolde-the-troll",
       "Hazel the Ghoul", requested_by="Hazel the Ghoul")

print("== 2. a manifest that is the whole call is its manifest ==")
inner = json.loads(AGATHA_BARE)
inner.pop("requested_by")
landed("{manifest: <object>, requested_by}", json.dumps({"manifest": inner, "requested_by": "Agatha the Banshee"}),
       "joker-agatha-the-banshee", "Agatha the Banshee")
landed("{manifest: <JSON string>, requested_by}",
       json.dumps({"manifest": json.dumps(inner), "requested_by": "Agatha the Banshee"}),
       "joker-agatha-the-banshee", "Agatha the Banshee")
landed("{manifest: <JSON string with requested_by inside>}", json.dumps({"manifest": AGATHA_BARE}),
       "joker-agatha-the-banshee", "Agatha the Banshee")

print("== 3. any other top-level field a Deployment does not have is dropped ==")
odd = json.loads(ISOLDE)
odd["namespace_note"] = "maintenance"
odd["witch"] = "Isolde the Troll"
landed("two more top-level fields the kind does not have", json.dumps(odd), "joker-isolde-the-troll",
       "Isolde the Troll")

print("== 3b. the pod's spec, or the template's metadata, written beside the template goes into it ==")
final = landed("the 20:35:04 manifest, from the log", SPEC_SPEC, "joker-agatha-the-banshee", "Agatha the Banshee",
               requested_by="Agatha the Banshee")
check("its template keeps the model's label, and the selector matches it",
      final["spec"]["template"]["metadata"]["labels"].get("app") == "joker-agatha-the-banshee"
      and final["spec"]["selector"] == {"matchLabels": {"app": "joker-agatha-the-banshee"}}, json.dumps(final["spec"]))
beside = json.loads(SPEC_SPEC)
beside["spec"]["metadata"] = beside["spec"]["template"].pop("metadata")
beside["spec"].pop("template")
landed("template metadata and pod spec both in the workload's spec, no template", json.dumps(beside),
       "joker-agatha-the-banshee", "Agatha the Banshee", requested_by="Agatha the Banshee")

print("== 4. a nested field the API server refuses with that 500 is applied as the plain Joker ==")
nested = json.loads(ISOLDE)
nested["spec"]["template"]["spec"]["containers"][0]["requested_by"] = "Isolde the Troll"
final = landed("requested_by inside the container", json.dumps(nested), "joker-isolde-the-troll", "Isolde the Troll",
               applies_expected=2)
check("the plain Joker's container has only its name, image and the room Joker's resources",
      set(final["spec"]["template"]["spec"]["containers"][0]) == {"name", "image", "resources"},
      json.dumps(final["spec"]["template"]["spec"]["containers"][0]))

print("== 5. a wrapped name is that name; what is not one of these is still refused ==")
# Since #939 a manifest that is only an app's name ("Tron") is the Deployment it asks for, so a call wrapping one
# lands what the bare name lands, credited to the witch the wrapper names.
api_bare, reply_bare, exc_bare = deploy("Tron", "Quentin the Mummy")
bare_rows = list(reports)
api, reply, exc = deploy(json.dumps({"manifest": "Tron", "requested_by": "Quentin the Mummy"}))
check("a call wrapping only an app's name lands what the bare name lands",
      exc is None and exc_bare is None and reply == reply_bare and applies(api) == applies(api_bare),
      f"{reply!r} {exc} / {reply_bare!r} {exc_bare}")
check("and credits the witch the wrapper names",
      len(reports) == 1 and reports[0]["requested_by"] == "Quentin the Mummy" and reports == bare_rows, f"{reports}")

api, reply, exc = deploy(json.dumps({"manifest": [{"kind": "Deployment"}, {"kind": "Service"}],
                                     "requested_by": "Quentin the Mummy"}))
check("a call wrapping two objects is refused before any apply",
      reply is None and "single object with apiVersion and kind" in str(exc) and not applies(api), f"{reply!r} {exc}")

other = json.loads(ISOLDE.replace("joker-isolde-the-troll", "maintenance-shell"))
other["spec"]["template"]["spec"]["containers"][0]["requested_by"] = "x"
api, reply, exc = deploy(json.dumps(other))
check("a Deployment that is not a room Joker is refused with the API server's 500, applied once",
      reply is None and "HTTP 500" in str(exc) and len(applies(api)) == 1, f"{reply!r} {exc}")

cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "menu"}, "data": {"a": "b"}}
obj = dict(cm)
server._drop_undeclared_top_keys(obj)
check("a ConfigMap's own top-level fields are not dropped", obj == cm, json.dumps(obj))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("A room Joker whose manifest carries the call's requested_by lands, credited to that witch.")
