# ABOUTME: Holds deploy_app to taking a manifest that is only an app's name (#939): Challenge 2's "deploy Tron" call
# ABOUTME: sends the manifest "Tron", and that must land a one-pod Deployment named tron on the public nginx image.
"""Why this exists (#939).

Challenge 2's room ask is "deploy Tron onto this cluster", then "Just use the standard manifest and pull the image off
the public internet." On the public bot (watch-it-burn-community) the model answered the follow-up by calling
deploy_app with the manifest "Tron" and nothing else: three times on 2026-11-04 and twice on 2026-11-05 (runs 16962
and 17082 on #452), and again on 2026-11-06 at 08:08 UTC, where workshop-mcp's log reads
{"manifest":"Tron","requested_by":"Replay the Raven"}. deploy_app refused each as not a single object with apiVersion
and kind, so the room's own Challenge 2 ask landed nothing and the fallback deck has no shot 03-1.

deploy_app now reads a manifest that is only a name as the app it names. It writes the Deployment, named after the
app, with the listed public image the name asks for, and serves an app the list does not carry (Tron has no image on
public.ecr.aws) on the listed nginx as its landing page. Everything after that is the room deployment #773 built: the
pinned image, one replica, the room's resources, the report to the deployments page with the witch name. A bare image
reference is that image, so a Docker Hub name off the list is still refused (#714). The reply names the image, so the
bot does not tell the room a Tron image was found.

deploy_app runs here against a stand-in for the Kubernetes API that records every call. No cluster, no model.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import types

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
SERVER = AI / "workshop-mcp-server.py"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        def keep(f):
            f.description = kw.get("description", "")
            return f
        return keep


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
os.environ["JOKER_SCALE_DOWN_SECONDS"] = "3600"
spec = importlib.util.spec_from_file_location("workshop_mcp_named_app", SERVER)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
os.environ.pop("JOKER_SCALE_DOWN_SECONDS", None)
m._ns = lambda: "agent"
m.PUBLIC_HOST = "attackme.agenticburn.com"

calls: list[tuple[str, str, dict]] = []
reports: list[dict] = []
deny = {"on": False}
KINDS = (("Deployment", "deployments"), ("StatefulSet", "statefulsets"), ("Pod", "pods"))
DENIAL = ('admission webhook "vpol.validate.kyverno.svc-fail" denied the request: '
          "Policy restrict-image-registries failed: not from an allowed registry")


def fake_req(method: str, path: str, body=None, content_type: str = "application/json"):
    if method == "GET":
        if path.rstrip("/").count("/") <= 3:
            return 200, json.dumps({"resources": [{"kind": k, "name": n} for k, n in KINDS]})
        return 404, json.dumps({"kind": "Status", "code": 404, "message": "not found"})
    calls.append((method, path.split("?")[0], json.loads(body) if body else {}))
    if deny["on"]:
        return 403, json.dumps({"kind": "Status", "status": "Failure", "code": 403, "message": DENIAL})
    return 201, "{}"


m._req = fake_req
m._report = lambda name, ok, detail, image="", requested_by="": reports.append(  # noqa: E731
    {"name": name, "ok": ok, "detail": detail, "image": image, "requested_by": requested_by})


def deploy(manifest: str, requested_by: str = "") -> tuple[str, dict, str]:
    """deploy_app's reply, the one object it applied ({} when none), and the refusal it raised ("" when none)."""
    calls.clear()
    reports.clear()
    try:
        reply = m.deploy_app(manifest, requested_by=requested_by)
    except RuntimeError as e:
        return "", {}, str(e)
    applies = [c for c in calls if c[0] == "PATCH" and "/scale" not in c[1]]
    return reply, (applies[0][2] if len(applies) == 1 else {"applies": applies}), ""


def container(obj: dict) -> dict:
    return (((obj.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers", [{}])[0]


def patched_paths() -> list[str]:
    return [c[1] for c in calls if c[0] == "PATCH"]


NGINX = m.PUBLIC_IMAGES["nginx"]

print("== the 2026-11-06 call from workshop-mcp's log: manifest 'Tron', requested_by 'Replay the Raven' ==")
reply, out, err = deploy("Tron", requested_by="Replay the Raven")
check("it deploys, raising nothing", bool(reply) and not err, err)
check("one server-side apply, of Deployment agent/tron",
      patched_paths() == ["/apis/apps/v1/namespaces/agent/deployments/tron"], str(patched_paths()))
check("the object is an apps/v1 Deployment named tron in agent",
      out.get("apiVersion") == "apps/v1" and out.get("kind") == "Deployment"
      and out.get("metadata", {}).get("name") == "tron" and out.get("metadata", {}).get("namespace") == "agent",
      json.dumps(out)[:300])
check("its one container is named tron and runs the pinned public nginx image (Tron has none of its own)",
      container(out).get("name") == "tron" and container(out).get("image") == NGINX, str(container(out)))
check("NAMED_APP_IMAGE is a listed public image, so nothing is pulled from Docker Hub (#714)",
      getattr(m, "NAMED_APP_IMAGE", "") in m.PUBLIC_IMAGES)
check("it is a room deployment: one replica and the room's resources (#773)",
      out.get("spec", {}).get("replicas") == 1 and container(out).get("resources") == m.ROOM_RESOURCES,
      str(out.get("spec", {}).get("replicas")) + " " + str(container(out).get("resources")))
labels = out.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
check("its selector matches its pod labels, which carry the workload label (#664)",
      out.get("spec", {}).get("selector") == {"matchLabels": {"app": "tron"}}
      and labels.get("app") == "tron" and labels.get(m.WORKLOAD_LABEL) == "tron", str(labels))
check("the reply says it was deployed and names the image it runs",
      reply.startswith("deployed Deployment/tron in agent") and NGINX in reply and "nginx" in reply, reply)
check("the deployments page is told it landed, with the image and the witch name",
      reports == [{"name": "tron", "ok": True, "detail": "", "image": NGINX, "requested_by": "Replay the Raven"}],
      str(reports))
check("the tool's description says the manifest can be just the app's name, Tron for one",
      "just the app's name" in m.deploy_app.description and "Tron" in m.deploy_app.description)

print("== other ways a model writes only the name ==")
for manifest, want_name, want_image in (
        ("tron", "tron", "nginx"), ('"Tron"', "tron", "nginx"), ("`Tron`", "tron", "nginx"), ("Tron\n", "tron", "nginx"),
        ("Tron game", "tron-game", "nginx"), ("deploy the Tron app", "tron", "nginx"),
        ("Please deploy Tron onto this cluster", "tron", "nginx"),
        ("nginx", "nginx", "nginx"), ("Apache", "apache", "httpd"), ("redis", "redis", "redis"),
        ("the 2048 game", "2048-game", "2048"), ("2048", "2048", "2048"), ("busybox", "busybox", "busybox"),
        ("redis:8", "redis", "redis"), ("public.ecr.aws/docker/library/nginx:latest", "nginx", "nginx")):
    reply, out, err = deploy(manifest)
    check(f"{manifest!r} deploys Deployment/{want_name} on the pinned {want_image}",
          not err and out.get("metadata", {}).get("name") == want_name
          and container(out).get("image") == m.PUBLIC_IMAGES[want_image]
          and out.get("spec", {}).get("replicas") == 1, err or json.dumps(out)[:200])
_, out, _ = deploy("busybox")
check("a named shell image gets its sleep, as a manifest's would", container(out).get("command") == m.SHELL_COMMAND)
own = "ghcr.io/peopleforrester/watch-it-burn:busybox-1.36"
reply, out, err = deploy(own)
check("an image with a registry of its own, sent bare, is applied exactly as written",
      not err and container(out).get("image") == own and out.get("metadata", {}).get("name") == "watch-it-burn",
      err or json.dumps(out)[:200])

print("== what is still refused, before any apply ==")
for label, manifest, why in (
        ("a Docker Hub image off the list, sent bare (#714)", "trongame/tron:latest", "Docker Hub"),
        ("a sentence, not a name", "I need the festival landing page with the light cycle game on it", "apiVersion and kind"),
        ("only filler words", "deploy the app", "apiVersion and kind"),
        ("no name at all", "!!!", "apiVersion and kind"),
        ("an image whose repository makes no name", "ghcr.io/someone/___:1", "names no app"),
        ("a YAML boolean", "true", "apiVersion and kind"),
        ("a YAML null", "null", "apiVersion and kind")):
    reply, out, err = deploy(manifest)
    check(f"{label}: refused as 'deploy failed for ...', saying why ({why}) and that nothing was deployed",
          not reply and err.startswith("deploy failed for ") and why in err and "Nothing was deployed." in err,
          reply or err)
    check(f"{label}: nothing reached the API server", not patched_paths(), str(patched_paths()))
_, _, err = deploy("trongame/tron:latest")
check("the Docker Hub refusal names the list and says the app's name alone will do",
      all(n in err for n in m.PUBLIC_IMAGES) and "just the app's name" in err, err)

print("== a whole manifest is read as before ==")
whole = json.dumps({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "web"},
                    "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "web"}},
                             "template": {"metadata": {"labels": {"app": "web"}},
                                          "spec": {"containers": [{"name": "web", "image": "nginx"}]}}}})
reply, out, err = deploy(whole)
check("a full Deployment's reply is unchanged", reply == "deployed Deployment/web in agent.", err or reply)

print("== after guardrails-on, Kyverno refuses the named app at admission, the Challenge 2 lesson ==")
deny["on"] = True
reply, out, err = deploy("Tron", requested_by="Replay the Raven")
deny["on"] = False
check("the admission denial is raised, naming restrict-image-registries",
      not reply and err.startswith("deploy failed for Deployment/tron (HTTP 403)")
      and "restrict-image-registries" in err, reply or err)
check("the deployments page is told it did not land",
      len(reports) == 1 and reports[0]["ok"] is False and "restrict-image-registries" in reports[0]["detail"],
      str(reports))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("deploy_app deploys a named app, Tron included, and refuses what names none.")
