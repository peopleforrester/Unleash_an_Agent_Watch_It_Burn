# ABOUTME: deploy_app applies the manifest shapes the room's model sends for HC-666 (#856): a whole manifest with the
# ABOUTME: rest of the call after it, one short of its braces, fenced, nested a level off, or with no selector.
"""HC-666 failed on about one ask in three on the public bot (#856). Run 16947 sent three HC-666 asks on 2026-11-04
and asked the bot in each failed session to quote its deploy_app call. One quoted the error deploy_app raised:

    could not parse it as JSON or YAML, so send the whole manifest again: expected '<document start>', but found '}'
      in "<unicode string>", line 1, column 447:
        ... ance-shell:busybox-1.38.0\\"}]}}}}}, requested_by=

and the manifest: a whole joker-agatha-the-banshee Deployment. Written with json.dumps' default separators that
manifest is 446 characters, so column 447 is one "}" more than it closes, followed by ', requested_by=': the model
wrote the end of its own call into the manifest string. MEASURED_1104 below is that string, and the first check holds
that it raises the error the bot quoted at that column. On 2026-10-30 the manifest was three closing braces short
(#648). The 422 on 2026-11-04 ('Refused by the cluster (HTTP 422).' on the wall) is a Deployment the API server
cannot take as written; the cases after the parse shapes are the ones it refuses for: no selector, a selector that
matches no template label, a container with no name, fields one level off.

Each case runs deploy_app against a stand-in API server that answers discovery and records the apply, and checks the
body it applied is a Deployment the API server would take. Nothing here needs a cluster.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

import yaml

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
spec = importlib.util.spec_from_file_location("workshop_mcp_manifest_shapes", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

DISCOVERY = {
    "/apis/apps/v1": [{"name": "deployments", "kind": "Deployment"}, {"name": "statefulsets", "kind": "StatefulSet"}],
    "/api/v1": [{"name": "pods", "kind": "Pod"}, {"name": "services", "kind": "Service"}],
}
applied: list[dict] = []
reports: list[dict] = []


def fake_req(method, path, body=None, content_type=None):
    if method == "GET" and path in DISCOVERY:
        return 200, json.dumps({"resources": DISCOVERY[path]})
    if method == "PATCH" and "/scale" not in path:
        applied.append({"path": path, "obj": json.loads(body)})
        return 201, body
    return 404, "{}"


server._req = fake_req
server._report = lambda name, ok, detail, image="", requested_by="", kind="": reports.append(  # noqa: E731
    {"name": name, "ok": ok, "requested_by": requested_by, "kind": kind})
server.JOKER_SCALE_DOWN_SECONDS = 3600.0
server._ns = lambda: "agent"  # noqa: E731

NAME = "joker-agatha-the-banshee"
IMAGE = "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"
WITCH = "Agatha the Banshee"
# The manifest the bot quoted on 2026-11-04 (session check-856-16947-3).
QUOTED = {"apiVersion": "apps/v1", "kind": "Deployment",
          "metadata": {"name": NAME, "labels": {"app": NAME}},
          "spec": {"replicas": 1, "selector": {"matchLabels": {"app": NAME}},
                   "template": {"metadata": {"labels": {"app": NAME}},
                                "spec": {"containers": [{"name": "maintenance-shell", "image": IMAGE}]}}}}
MEASURED_1104 = json.dumps(QUOTED) + f'}}, requested_by="{WITCH}"'
# The 2026-10-30 manifest's shape: the same Deployment, three closing braces short.
SHORT_1030 = json.dumps(QUOTED, separators=(",", ":"))[:-3]


def valid_deployment(obj: dict) -> str:
    """Why the API server would refuse this Deployment with a 422, or "" when it would take it."""
    if obj.get("apiVersion") != "apps/v1" or obj.get("kind") != "Deployment":
        return f"apiVersion/kind {obj.get('apiVersion')}/{obj.get('kind')}"
    extra = set(obj) - {"apiVersion", "kind", "metadata", "spec"}
    if extra:
        return f"top-level fields the API server drops: {sorted(extra)}"
    spec = obj.get("spec") or {}
    if not isinstance(spec.get("replicas"), int):
        return f"replicas {spec.get('replicas')!r}"
    match = ((spec.get("selector") or {}).get("matchLabels")) or {}
    labels = ((spec.get("template") or {}).get("metadata") or {}).get("labels") or {}
    if not match:
        return "spec.selector: Required value"
    if any(labels.get(k) != v for k, v in match.items()):
        return f"selector {match} does not match template labels {labels}"
    pod = (spec.get("template") or {}).get("spec") or {}
    extra = set(spec) - {"replicas", "selector", "template", "strategy", "minReadySeconds",
                         "revisionHistoryLimit", "progressDeadlineSeconds", "paused"}
    if extra:
        return f"spec fields a Deployment does not have: {sorted(extra)}"
    containers = pod.get("containers")
    if not isinstance(containers, list) or not containers:
        return "spec.template.spec.containers: Required value"
    for c in containers:
        if not isinstance(c, dict) or not c.get("name") or not c.get("image"):
            return f"container without a name or image: {c}"
        for key in ("command", "args"):
            if key in c and not (isinstance(c[key], list) and all(isinstance(x, str) for x in c[key])):
                return f"container {key} is not a list of strings: {c[key]!r}"
    return ""


def deploy(manifest: str, requested_by: str = ""):
    applied.clear()
    reports.clear()
    try:
        return server.deploy_app(manifest, requested_by), None
    except Exception as e:  # noqa: BLE001
        return None, e


print("== 0. the measured manifest is the one deploy_app refused on 2026-11-04 ==")
try:
    yaml.safe_load(MEASURED_1104)
    yaml_error = ""
except yaml.YAMLError as e:
    yaml_error = str(e)
check("the 2026-11-04 manifest is neither JSON nor YAML as written, at column 447 as the bot quoted",
      "expected '<document start>', but found '}'" in yaml_error and "column 447" in yaml_error, yaml_error[:200])

print("== 1. the shapes the model sends deploy_app are applied ==")
YAML_TEXT = yaml.safe_dump(QUOTED, sort_keys=False)
PARSE_SHAPES = (
    ("2026-11-04: a whole manifest, one more '}' and ', requested_by=\"...\"' after it", MEASURED_1104, WITCH),
    ("2026-11-04's shape compact, with the name unquoted after it",
     json.dumps(QUOTED, separators=(",", ":")) + f"}}, requested_by={WITCH}", WITCH),
    ("2026-11-04's shape with the name as a JSON key after it",
     json.dumps(QUOTED) + f'}}, "requested_by": "{WITCH}"}}', WITCH),
    ("a whole manifest with text after it and no name", json.dumps(QUOTED) + "}}", ""),
    # 2026-11-05 (#906): the call's argument written as a top-level field of the Deployment, which the API server
    # refused twice in three asks with ".requested_by: field not declared in schema".
    ("2026-11-05: requested_by as a field of the manifest itself",
     json.dumps({"apiVersion": "apps/v1", "kind": "Deployment", "requested_by": WITCH,
                 **{k: v for k, v in QUOTED.items() if k not in ("apiVersion", "kind")}}), WITCH),
    ("2026-11-05's shape with requested_by last", json.dumps({**QUOTED, "requested_by": WITCH}), WITCH),
    ("requested_by as a field that is not a name", json.dumps({**QUOTED, "requested_by": None}), ""),
    ("2026-10-30: three closing braces short", SHORT_1030, ""),
    ("short of its braces with a comma left after the last value", json.dumps(QUOTED)[:-4] + ",", ""),
    ("JSON in a ```json fence", "```json\n" + json.dumps(QUOTED, indent=2) + "\n```", ""),
    ("YAML in a ```yaml fence", "```yaml\n" + YAML_TEXT + "```", ""),
    ("plain YAML", YAML_TEXT, ""),
    ("the manifest as a JSON string of itself", json.dumps(json.dumps(QUOTED)), ""),
    ("a list of the one Deployment", json.dumps([QUOTED]), ""),
    ("a kind: List of the one Deployment", json.dumps({"apiVersion": "v1", "kind": "List", "items": [QUOTED]}), ""),
)
for label, manifest, who in PARSE_SHAPES:
    print(f"-- {label}")
    reply, exc = deploy(manifest)
    check(f"{label}: deploy_app applies it", exc is None and len(applied) == 1, f"{exc}")
    if exc is not None or not applied:
        continue
    obj = applied[0]["obj"]
    check(f"{label}: as {NAME}, running the ticket's image",
          obj["metadata"]["name"] == NAME and applied[0]["path"].endswith(f"/deployments/{NAME}"
                                                                          "?fieldManager=workshop-mcp&force=true")
          and obj["spec"]["template"]["spec"]["containers"][0]["image"] == IMAGE, json.dumps(obj)[:300])
    why = valid_deployment(obj)
    check(f"{label}: a Deployment the API server takes", not why, why)
    check(f"{label}: the reply says it was deployed", bool(reply) and reply.startswith(f"deployed Deployment/{NAME}"),
          str(reply))
    check(f"{label}: the desk is told who asked ({who or 'nobody named'})",
          reports and reports[0]["ok"] and reports[0]["requested_by"] == who, f"{reports}")

reply, exc = deploy(MEASURED_1104, requested_by="Hazel the Ghoul")
check("a requested_by passed as its own argument wins over one written after the manifest",
      exc is None and reports and reports[0]["requested_by"] == "Hazel the Ghoul", f"{exc} {reports}")
reply, exc = deploy(json.dumps({**QUOTED, "requested_by": WITCH}), requested_by="Hazel the Ghoul")
check("a requested_by passed as its own argument wins over one written as a field of the manifest",
      exc is None and reports and reports[0]["requested_by"] == "Hazel the Ghoul"
      and applied and "requested_by" not in applied[0]["obj"], f"{exc} {reports}")

print("== 2. the Deployments the API server refuses with a 422 are mended ==")


def variant(edit) -> dict:
    d = json.loads(json.dumps(QUOTED))
    edit(d)
    return d


def no_selector(d):
    del d["spec"]["selector"]


def no_template_labels(d):
    del d["spec"]["template"]["metadata"]


def selector_without_its_label(d):
    d["spec"]["template"]["metadata"]["labels"] = {"tier": "maintenance"}


def nothing_but_containers(d):
    d["spec"] = {"replicas": 1, "template": {"spec": d["spec"]["template"]["spec"]}}


def containers_on_spec(d):
    d["spec"] = {"replicas": 1, "containers": d["spec"]["template"]["spec"]["containers"]}


def containers_on_template(d):
    d["spec"]["template"]["containers"] = d["spec"]["template"].pop("spec")["containers"]


def spec_fields_at_top(d):
    d.update(d.pop("spec"))


def container_without_name(d):
    del d["spec"]["template"]["spec"]["containers"][0]["name"]


def container_not_in_a_list(d):
    pod = d["spec"]["template"]["spec"]
    pod["containers"] = pod["containers"][0]


def replicas_as_text(d):
    d["spec"]["replicas"] = "1"


def command_as_text(d):
    d["spec"]["template"]["spec"]["containers"][0]["command"] = "sleep 3600"


def no_api_version(d):
    del d["apiVersion"]


for edit in (no_selector, no_template_labels, selector_without_its_label, nothing_but_containers, containers_on_spec,
             containers_on_template, spec_fields_at_top, container_without_name, container_not_in_a_list,
             replicas_as_text, command_as_text, no_api_version):
    label = edit.__name__.replace("_", " ")
    before = variant(edit)
    reply, exc = deploy(json.dumps(before))
    check(f"{label}: deploy_app applies it", exc is None and len(applied) == 1, f"{exc}")
    if exc is None and applied:
        obj = applied[0]["obj"]
        why = valid_deployment(obj)
        check(f"{label}: a Deployment the API server takes", not why, why + " " + json.dumps(obj)[:300])
        check(f"{label}: the ticket's image and the Joker's name kept",
              obj["metadata"]["name"] == NAME
              and obj["spec"]["template"]["spec"]["containers"][0]["image"] == IMAGE, json.dumps(obj)[:300])
        check(f"{label}: the Joker still gets its own page (hostname and the jokers Service)",
              obj["spec"]["template"]["spec"].get("hostname") == NAME
              and obj["spec"]["template"]["spec"].get("subdomain") == server.ROOM_JOKER_SERVICE)

print("== 3. what the model wrote on purpose is left as written ==")
labeled = variant(lambda d: d["spec"]["template"]["metadata"]["labels"].update({"requested_by": "x", "tier": "ops"}))
reply, exc = deploy(json.dumps(labeled))
obj = applied[0]["obj"] if applied else {}
check("a label called requested_by inside a manifest that parses is not cut off as a trailer",
      exc is None and obj.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {}).get("requested_by")
      == "x", f"{exc}")
check("its own selector and labels stay", exc is None and obj["spec"]["selector"] == {"matchLabels": {"app": NAME}}
      and {"app": NAME, "requested_by": "x", "tier": "ops"}.items()
      <= obj["spec"]["template"]["metadata"]["labels"].items(), f"{obj.get('spec')}")
own = variant(lambda d: d["spec"]["selector"].update({"matchLabels": {"run": "shell"}}))
own["spec"]["template"]["metadata"]["labels"] = {"run": "shell"}
reply, exc = deploy(json.dumps(own))
obj = applied[0]["obj"] if applied else {}
check("a selector and labels that already match are not given an app label",
      exc is None and obj["spec"]["selector"] == {"matchLabels": {"run": "shell"}}
      and "app" not in obj["spec"]["template"]["metadata"]["labels"], f"{obj.get('spec')}")

print("== 4. what cannot be read without guessing is still refused ==")
for label, manifest in (
        ("cut off inside the image's string", json.dumps(QUOTED)[:-40]),
        ("a closing bracket where a brace belongs", json.dumps(QUOTED)[:-1] + "]"),
        ("two keys with no comma between them", '{"apiVersion": "apps/v1" "kind": "Deployment"}')):
    reply, exc = deploy(manifest)
    check(f"{label}: refused with the parse error, nothing applied",
          reply is None and "could not parse" in str(exc) and not applied, f"{reply!r} {exc}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every manifest shape the room's model sends for HC-666 is applied as a Deployment the API server takes.")
