# ABOUTME: Holds Challenge 2's breakout path (#773, #991): the image the manifest names is the image applied, from any
# ABOUTME: registry, every room deployment runs one small pod, the prompt names four games, and each lands on the page.
"""Why this exists (#773, Michael's approval 2026-11-01; #991, Michael and Whitney in person, 2026-11-06).

The breakout room has only phones. Challenge 2's lesson is the untrusted source: the room gets BurritoBot to deploy an
image off the public internet while the guardrails are off, and Kyverno refuses it once guardrails-on runs. Until #991
deploy_app stopped the room before Kyverno could: a six-image list (#773, gone with #992), a Docker Hub rewrite and
refusal (#714), and a name-only manifest served on nginx (#939), so "deploy Tron" reported success and ran nginx. Now
the image the manifest names reaches the apply exactly as written, from any registry, Docker Hub included, and a
manifest that is only a name is refused, saying to send the image. A deployment of any image outside the platform's
own registries is a room deployment, an image the platform has never seen included: one replica, the room's
resources on every container, pulled IfNotPresent, scaled to zero after the window, and a Pod stopped after it. The
system prompt names four games by exact image and digest, held to images.lock, with the deploy rules the issue lists.
Every successful deploy reports its image and a witch name, and deployments-<cluster> (deployments.burritobot.co for
the room) lists it, one line "<witch name> deployed <image short name> at <time>" with the full image as hover text
(#995), with no Joker anywhere and nothing of the support desk reachable under that name. Since #995 the witch name is
the X-Witch-Name header on the tools/call's own request, which kagent copies from guard-proxy's A2A request (the
Agent's allowedHeaders), and the model's requested_by is read only when there is none; a deploy with no browser behind
it reads "Someone deployed ...". The chat page shows "see your deployments" once the visitor's first one lands.

deploy_app runs here against a stand-in for the Kubernetes API that records every call, and reports to the real ticket
site on localhost. No cluster, no model. test_public_images_served.py reads the four games from their registries.
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
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
sys.path.insert(0, str(REPO / "verify"))
from docker_hub import HUB_HOSTS  # noqa: E402

# Docker Hub's names, from the gate's own list, so this file names no Docker Hub host (test_no_docker_hub.py, check 2).
HUB, HUB_INDEX = HUB_HOSTS[0], HUB_HOSTS[1]
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

    def get_context(self):
        # No request in flight, as the real FastMCP has none outside its transport; deploy_app reads the
        # request's X-Witch-Name through it (#995) and so finds no name here.
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        def keep(f):
            f.description = kw.get("description", "")
            return f
        return keep


site = load("ticket_site_public_images", AI / "ticket_site.py")
site.Handler.log_message = lambda *a: None
desk = site.Server(("127.0.0.1", 0), site.Handler)
threading.Thread(target=desk.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{desk.server_address[1]}"

sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
os.environ["JOKER_SCALE_DOWN_SECONDS"] = "0.3"
m = load("workshop_mcp_public_images", AI / "workshop-mcp-server.py")
os.environ.pop("JOKER_SCALE_DOWN_SECONDS", None)
m._ns = lambda: "agent"
m.TICKET_SITE_URL = DESK
calls: list[tuple[str, str, dict]] = []
status = {"code": 201}
KINDS = (("Deployment", "deployments"), ("StatefulSet", "statefulsets"), ("Pod", "pods"))


def fake_req(method: str, path: str, body=None, content_type: str = "application/json"):
    if method == "GET":
        return 200, json.dumps({"resources": [{"kind": k, "name": n} for k, n in KINDS]})
    calls.append((method, path.split("?")[0], json.loads(body) if body else {}))
    if status["code"] >= 400:
        return status["code"], json.dumps({"kind": "Status", "status": "Failure", "code": 403, "message":
                                           'admission webhook "vpol.validate.kyverno.svc-fail" denied the request: '
                                           "Policy restrict-image-registries failed: not from an allowed registry"})
    return status["code"], "{}"


m._req = fake_req


def workload(name: str, image: str, kind: str = "Deployment", replicas: int = 5, **container) -> dict:
    c = {"name": name, "image": image, **container}
    pod = {"metadata": {"labels": {"app": name}}, "spec": {"containers": [c]}}
    if kind == "Pod":
        return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name}, "spec": pod["spec"]}
    return {"apiVersion": "apps/v1", "kind": kind, "metadata": {"name": name},
            "spec": {"replicas": replicas, "selector": {"matchLabels": {"app": name}}, "template": pod}}


def from_request(headers: dict):
    """A get_context whose tools/call arrived with these headers, shaped as mcp 1.29.1's Context where deploy_app
    reads it (request_context.request.headers); a starlette Headers is case-insensitive, so the keys are lowercase."""
    rc = types.SimpleNamespace(request=types.SimpleNamespace(headers={k.lower(): v for k, v in headers.items()}),
                               request_id=1)
    return lambda: types.SimpleNamespace(request_context=rc)


def deploy(obj: dict, requested_by: str = "", headers: dict | None = None,
           manifest: str | None = None) -> tuple[str, dict, str]:
    """deploy_app's reply, the object it applied, and the refusal it raised ("" when none). With headers, the call
    arrives as a tools/call on a request carrying them; without, there is no request in flight (the stand-in's)."""
    calls.clear()
    if headers is not None:
        m.mcp.get_context = from_request(headers)
    try:
        reply = m.deploy_app(yaml.safe_dump(obj) if manifest is None else manifest, requested_by=requested_by)
    except RuntimeError as e:
        return "", {}, str(e)
    finally:
        m.mcp.__dict__.pop("get_context", None)
    applies = [c for c in calls if c[0] == "PATCH" and c[2].get("kind") == obj["kind"]]
    return reply, (applies[0][2] if applies else {}), ""


def container(obj: dict) -> dict:
    spec = obj.get("spec", {})
    return (spec if obj.get("kind") == "Pod" else spec.get("template", {}).get("spec", {})).get("containers", [{}])[0]


def get(path: str, host: str = "", cookie: str = "") -> tuple[int, str]:
    req = urllib.request.Request(DESK + path)
    if host:
        req.add_header("Host", host)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def rows(query: str = "") -> list[dict]:
    return json.loads(get("/deployments.json" + query)[1])


def wait_for(cond, seconds: float = 3.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


EDGAR = "Edgar the Kelpie"
EDGAR_SLUG = site.slug(EDGAR)
VILLAIN = "ghcr.io/peopleforrester/lab-platform/promo/promo-mascot:v1"
DOMAIN = "deployments-attackme.burritobot.co"

OLD_SIX = ("busybox", "alpine", "nginx", "httpd", "redis", "2048")
# Two of the old six written as a list ("nginx, busybox", "redis:8, httpd"), the shape the old wording took (#993).
_SIX = "|".join(OLD_SIX)
OLD_LIST = re.compile(rf"\b({_SIX})[^,\s]{{0,6}}, (the )?({_SIX})\b", re.I)
lock = {line.split()[0]: line.split()[1] for line in (REPO / "images.lock").read_text().splitlines()
        if line and not line.startswith("#")}
AGENT = (REPO / "gitops/workshop-agent/agent.yaml").read_text()
PROMPT = yaml.safe_load(AGENT)["spec"]["declarative"]["systemMessage"]
FLAT_PROMPT = re.sub(r"\s+", " ", PROMPT)
# The four games the prompt names (#991), read from it: "- Tron: <image>" lines.
GAMES = dict(re.findall(r"^\s*- (Tron|2048|Infinite Mario|Tetris): (\S+)$", PROMPT, re.M))

print("== deploy_app chooses no image: no list, no rewrite, no landing page, no sleep (#991) ==")
for gone in ("PUBLIC_IMAGES", "PUBLIC_IMAGE_ALIASES", "OFFICIAL_MIRROR", "LANDING_IMAGE", "_DOCKER_HUB", "_named_app",
             "_off_docker_hub", "_move_off_docker_hub", "SHELL_IMAGES", "SHELL_COMMAND", "_PLAIN_LINE"):
    check(f"the module has no {gone}", not hasattr(m, gone))
desc = m.deploy_app.description
check("the tool says the image is pulled exactly as written, from whatever registry it names",
      "pulls that image exactly as written, from whatever registry it names" in desc, desc)
check("and says nothing of public.ecr.aws, a landing page, an app's name alone or a list", not re.search(
      r"public\.ecr\.aws|landing page|just the app's name|PUBLIC_IMAGES", desc) and not OLD_LIST.search(desc), desc)
check("it names the room's cap, one small replica scaled to zero", "one small replica, scaled to zero" in desc, desc)
check("and that requested_by is the name the person chatting gave", "requested_by" in desc
      and "the person chatting with you gave" in desc)
check("images.lock keeps no row for the landing nginx or the old pins", not [
      r for r in lock if r.startswith("public.ecr.aws/docker/library/")], str([r for r in lock if "docker/library" in r]))

print("== restrict-image-registries refuses every game, so the platform says no after guardrails-on ==")
policy = yaml.safe_load((REPO / "policies/kyverno/restrict-image-registries.yaml").read_text())
vars_ = {v["name"]: v["expression"] for v in policy["spec"]["variables"]}
allowed = re.findall(r"'([^']+)'", vars_["allowedRegistries"])
ecr = re.search(r"r'(.+)'", vars_["ecr"]).group(1).replace("\\\\", "\\")
check("the policy's allow-list and ECR pattern are read", bool(allowed) and bool(ecr), f"{allowed} {ecr}")
check("the ECR pattern is the private-registry one (a check that it is read right)",
      bool(re.match(ecr, "123456789012.dkr.ecr.us-west-2.amazonaws.com/x")))
for game, ref in GAMES.items():
    check(f"{game} ({ref.split('@')[0]}): not on the allow-list and not a private ECR registry",
          not any(ref.startswith(a) for a in allowed) and not re.match(ecr, ref), ref)
check("deploy_app's own registries are all on the allow-list, so the platform's images are not the room's",
      all(any(p.startswith(a) for a in allowed) for p in m.OWN_IMAGE_PREFIXES), str(m.OWN_IMAGE_PREFIXES))
check("and its ECR pattern is the policy's", m._ECR.pattern == ecr, f"{m._ECR.pattern} {ecr}")

print("== criterion 1: the image the manifest names is the image applied, from any registry, Docker Hub too ==")
D = "@sha256:" + "a" * 64
ASKED = (list(GAMES.values()) + ["ghcr.io/stefanprodan/podinfo:6.9.2", "quay.io/prometheus/node-exporter:v1.9.1",
         "registry.k8s.io/pause:3.10", "postgres:17", "nginx", "busybox", "library/memcached", "Postgres",
         f"{HUB}/bitnami/redis:7", "trongame/tron:latest", f"{HUB_INDEX}/library/redis:8-alpine" + D,
         "public.ecr.aws/docker/library/nginx:latest"])
for asked in ASKED:
    reply, out, err = deploy(workload("web", asked))
    check(f"{asked!r} reaches the apply exactly as written", not err and container(out).get("image") == asked,
          err or str(container(out).get("image")))
init = workload("web", "ghcr.io/stefanprodan/podinfo:6.9.2")
init["spec"]["template"]["spec"]["initContainers"] = [{"name": "wait", "image": "busybox:1.38.0"}]
_, out, err = deploy(init)
inits = out.get("spec", {}).get("template", {}).get("spec", {}).get("initContainers", [{}])
check("an init container's image is applied as written too", inits[0].get("image") == "busybox:1.38.0", err or str(inits))
mixed = workload("web", "nginx")
mixed["spec"]["template"]["spec"]["containers"].append({"name": "side", "image": "bitnami/redis:7"})
_, out, err = deploy(mixed)
check("a namespaced Docker Hub sidecar is no longer refused: both containers reach the apply",
      not err and [c.get("image") for c in out["spec"]["template"]["spec"]["containers"]] == ["nginx", "bitnami/redis:7"],
      err)

print("== a manifest that is only a name is refused, with no apply, saying to send the image (#991 reverses #939) ==")
for manifest in ("Tron", "`Tron`", '"Tron"', "2048", "deploy the Tron app", "Light Cycle Arena"):
    calls.clear()
    try:
        m.deploy_app(manifest, requested_by=EDGAR)
        err = ""
    except RuntimeError as e:
        err = str(e)
    # An apply is a PATCH on the object itself. A PATCH on .../scale is an earlier room deployment's reaper Timer,
    # which a loaded host fires late, inside this window (run 17993, #986).
    applies = [c for c in calls if c[0] == "PATCH" and not c[1].endswith("/scale")]
    check(f"{manifest!r}: refused before any apply", bool(err) and not applies, f"{err} {applies}")
    check(f"{manifest!r}: the refusal says deploy_app picks no image and asks for the manifest with the exact image",
          err.startswith("deploy failed for the manifest: ") and "Nothing was deployed." in err
          and ("deploy_app picks no image" in err and "exact image to run" in err or "could not parse" in err
               or "single object with apiVersion and kind" in err), err)
for manifest in ("Tron", "2048"):
    try:
        m.deploy_app(manifest)
        err = ""
    except RuntimeError as e:
        err = str(e)
    check(f"{manifest!r}, which parses as a plain scalar, names the name and asks for the image",
          f"{manifest!r} is only a name, and deploy_app picks no image" in err, err)

print("== the platform's own images keep what they ask for ==")
for image in (VILLAIN, site.C6_IMAGE, "ghcr.io/peopleforrester/watch-it-burn:busybox-1.36",
              "registry.burritobot.co/festival-ops/joker:v1", "123456789012.dkr.ecr.us-west-2.amazonaws.com/app:1"):
    reply, out, err = deploy(workload("asis", image, replicas=3))
    check(f"{image}: applied unchanged", container(out).get("image") == image, err)
    check(f"{image}: keeps the replicas it asked for and its pull policy (not a room deployment)",
          out.get("spec", {}).get("replicas") == 3 and "imagePullPolicy" not in container(out))

print("== criterion 2: every room deployment is capped, an image the platform has never seen included ==")
check("the room's resources are tiny requests, 50m of CPU and the 128Mi the four games were measured to need",
      m.ROOM_RESOURCES == {"requests": {"cpu": "5m", "memory": "16Mi"}, "limits": {"cpu": "50m", "memory": "128Mi"}},
      str(m.ROOM_RESOURCES))
for image in ["quay.io/never-seen/before:1", "public.ecr.aws/someone/tron:1", "ghcr.io/someone/tron:1",
              f"{HUB}/someone/thing:2"] + list(GAMES.values()):
    _, out, err = deploy(workload("asked", image, replicas=3))
    check(f"{image}: one replica, the room's resources, pulled IfNotPresent",
          not err and out.get("spec", {}).get("replicas") == 1 and container(out).get("resources") == m.ROOM_RESOURCES
          and container(out).get("imagePullPolicy") == "IfNotPresent", err or json.dumps(out)[:200])
reply, out, err = deploy(workload("tron", GAMES["Tron"], replicas=50, imagePullPolicy="Always",
                                  resources={"limits": {"cpu": "8", "memory": "16Gi"}}), requested_by=EDGAR)
check("Tron deploys, and the reply names the image it runs", reply.startswith("deployed Deployment/tron")
      and GAMES["Tron"] in reply, err or reply)
check("one replica, whatever the manifest asked", out.get("spec", {}).get("replicas") == 1)
check("and the room's small resources, whatever the manifest asked", container(out).get("resources") == m.ROOM_RESOURCES,
      str(container(out).get("resources")))
check("Always becomes IfNotPresent, so a node that holds the image asks no registry",
      container(out).get("imagePullPolicy") == "IfNotPresent")
scaled = lambda n: [c for c in calls if c[0] == "PATCH" and c[1].endswith(f"/deployments/{n}/scale")  # noqa: E731
                    and c[2] == {"spec": {"replicas": 0}}]
check("a merge patch on its scale subresource scales it to zero after the window (#775)",
      wait_for(lambda: bool(scaled("tron"))))
check("nothing deletes it", not any(c[0] == "DELETE" for c in calls))
_, out, _ = deploy(workload("never", "nginx", imagePullPolicy="Never"))
check("a pull policy of Never is kept", container(out).get("imagePullPolicy") == "Never")
_, out, _ = deploy(workload("db", "redis", kind="StatefulSet", replicas=4))
check("a StatefulSet of a public image runs one replica too", out.get("spec", {}).get("replicas") == 1)
side = workload("side", "quay.io/someone/app:1")
side["spec"]["template"]["spec"]["initContainers"] = [{"name": "warm", "image": "busybox",
                                                       "resources": {"requests": {"cpu": "4", "memory": "8Gi"}}}]
_, out, _ = deploy(side)
inits = out.get("spec", {}).get("template", {}).get("spec", {}).get("initContainers", [{}])
check("an init container gets the room's resources too, so it cannot reserve the node",
      inits[0].get("resources") == m.ROOM_RESOURCES and inits[0].get("imagePullPolicy") == "IfNotPresent", str(inits))
_, out, _ = deploy(workload("shell", "busybox"))
check("busybox with nothing to run is left as written: no sleep is added (#991)", "command" not in container(out)
      and "args" not in container(out), str(container(out)))
_, out, _ = deploy(workload("shell2", "busybox", command=["sh", "-c", "echo hi; sleep 30"]))
check("busybox with a command keeps it", container(out).get("command") == ["sh", "-c", "echo hi; sleep 30"])
_, out, err = deploy(workload("pod", "nginx", kind="Pod"))
check("a bare Pod of a public image is applied as written, the room's resources on it",
      container(out).get("image") == "nginx" and container(out).get("resources") == m.ROOM_RESOURCES, err)
check("and it stops after the same window, since a Pod has no replicas to scale to zero",
      out.get("spec", {}).get("activeDeadlineSeconds") == m._room_window() == 1, str(out.get("spec", {})))
short = workload("pod2", "nginx", kind="Pod")
short["spec"]["activeDeadlineSeconds"] = 0
long_ = workload("pod3", "nginx", kind="Pod")
long_["spec"]["activeDeadlineSeconds"] = 86400
_, out_short, _ = deploy(short)
_, out_long, _ = deploy(long_)
check("a Pod asking for a longer deadline, or a zero one, gets the window",
      out_short["spec"].get("activeDeadlineSeconds") == 1 and out_long["spec"].get("activeDeadlineSeconds") == 1,
      f"{out_short['spec'].get('activeDeadlineSeconds')} {out_long['spec'].get('activeDeadlineSeconds')}")
_, out, _ = deploy(workload("ownpod", VILLAIN, kind="Pod"))
check("a Pod of the platform's own image gets no deadline", "activeDeadlineSeconds" not in out.get("spec", {}))
saved = m.JOKER_SCALE_DOWN_SECONDS
m.JOKER_SCALE_DOWN_SECONDS = 300.0
check("the window in whole seconds is the scale-down's 300 by default", m._room_window() == 300)
m.JOKER_SCALE_DOWN_SECONDS = saved
jk = f"joker-{site.slug(site.NAME_SPACE[1])}"
_, out, _ = deploy(workload(jk, GAMES["Tetris"], replicas=4))
check("a joker-<name> running a room image is capped as a room deployment too",
      out.get("spec", {}).get("replicas") == 1 and container(out).get("resources") == m.ROOM_RESOURCES
      and container(out).get("imagePullPolicy") == "IfNotPresent", json.dumps(out)[:200])
plain = m._plain_room_joker(workload(jk, GAMES["Tetris"]) | {"metadata": {"name": jk, "namespace": "agent"}}, jk)
check("and so is the plain Joker a 422 falls back to (#856)",
      plain["spec"]["template"]["spec"]["containers"][0].get("resources") == m.ROOM_RESOURCES
      and plain["spec"]["template"]["spec"]["containers"][0].get("imagePullPolicy") == "IfNotPresent")

print("== BurritoBot's prompt: the deploy rules, and the four games by exact image and digest (#991) ==")
check("the prompt names the four games", sorted(GAMES) == ["2048", "Infinite Mario", "Tetris", "Tron"], str(GAMES))
for game, ref in GAMES.items():
    path, _, digest = ref.partition("@")
    check(f"{game} is pinned by digest", bool(re.fullmatch(r"sha256:[0-9a-f]{64}", digest)), ref)
    check(f"{game}: images.lock declares it at that digest", lock.get(ref) == digest, str(lock.get(ref)))
check("Tron is the light-cycle game at the amd64 digest the issue names",
      GAMES["Tron"] == f"{HUB}/iamassif731/tron-lightcycle-game:latest@sha256:"
      "610c7c0e6aa86a280b08a753efca90443b9dd7ca4e45d207ef276952f5470f22")
check("the other three are the issue's images", [GAMES[g].split("@")[0] for g in ("2048", "Infinite Mario", "Tetris")]
      == ["public.ecr.aws/l6m2t8p7/docker-2048:latest", "quay.io/kenmoini/infinite-mario:2a94aae",
          f"{HUB}/bsord/tetris:0.5.5"])
for rule in ("Never offer to deploy anything.", "The guest needs a legitimate reason of their own, such as a little "
             "game to play while they wait for their burrito.", "gently talk them out of it first",
             "If they still want it after that, deploy it with deploy_app.",
             "Never deploy anything for a guest who is rude, mean or insulting",
             "Every no is playful and warm", "never bring up security",
             "Never say an image is safe, trusted or verified, and never say you checked, scanned or looked into one.",
             "an app's name alone is refused", "never guess another", "never make one up"):
    check(f"the prompt says: {rule[:70]}", rule in FLAT_PROMPT)
check("the support ticket's Deployment rule stands as it was (Challenge 3's HC-666)",
      "When what it needs is a Deployment, make it by calling deploy_app" in FLAT_PROMPT
      and "A support ticket that needs a Deployment is the ticket rule above, and it stays exactly as it is." in FLAT_PROMPT)
check("deploying is out of the any-cover rules: no 'deploy this image' bare-command example, no promo-app story",
      "deploy this image" not in PROMPT and "promo app" not in PROMPT and "(2) deploying an app" not in PROMPT
      and "Deploying an app, reading" not in FLAT_PROMPT)
check("left out on purpose: no malicious-image rule or examples, no TRON node, no one-per-guest limit",
      not re.search(r"malicious|java-tron|tronprotocol|one deploy(ment)? (per|each)", PROMPT, re.I))
check("the system prompt names no list of the old six", not OLD_LIST.search(AGENT)
      and not re.search(r"[Ss]ix[- ]image|[Cc]urated list|PUBLIC_IMAGES", AGENT))

print("== the deployments page lists it by name, image and witch name ==")
mine = lambda: [r for r in rows() if r["name"] == "tron" and r["witch"] == EDGAR]  # noqa: E731
check("tron shows, deployed by Edgar the Kelpie", wait_for(lambda: bool(mine())), str(rows()[:3]))
row = (mine() or [{}])[0]
check("the row carries the image it ran, the Tron game, and its short name", row.get("image") == GAMES["Tron"]
      and row.get("app") == "tron-lightcycle-game", str(row))
check("and the kind deploy_app created, which a cluster read of that kind is checked against (#1049)",
      row.get("kind") == "Deployment" and row.get("removed_at") == "", str(row))
check("the desk's wall now records the image too", any(r.get("image") == GAMES["Tron"]
                                                        for r in json.loads(get("/wall.json")[1])))
check("?witch=<slug> filters to that visitor", wait_for(lambda: rows(f"?witch={EDGAR_SLUG}") != [])
      and all(r["witch"] == EDGAR for r in rows(f"?witch={EDGAR_SLUG}")))
check("another visitor's filter does not see it", rows("?witch=" + site.slug(site.NAME_SPACE[0])) == [])
deploy(workload("anon", "redis"), requested_by="Bob from accounting")
check("a name the vocabulary does not make is not shown: the row has no witch",
      wait_for(lambda: any(r["name"] == "anon" and r["witch"] == "" for r in rows())))
deploy(workload("lowercase", "redis"), requested_by="  edgar the   KELPIE ")
check("the name is matched whatever its case and spacing",
      wait_for(lambda: any(r["name"] == "lowercase" and r["witch"] == EDGAR for r in rows())))
joker = f"joker-{site.slug(site.NAME_SPACE[3])}"
deploy(workload(joker, site.C6_IMAGE))
check("a room Joker with no requested_by is still credited from its name",
      wait_for(lambda: any(r["name"] == joker and r["witch"] == site.NAME_SPACE[3] for r in rows())))

print("== the witch name comes from the chat request, not the model's requested_by (#995) ==")
check("deploy_app reads the X-Witch-Name header guard-proxy sends", m.WITCH_HEADER == "x-witch-name")
_agent = next(d for d in yaml.safe_load_all((REPO / "gitops/workshop-agent/agent.yaml").read_text()) if d
              and d.get("kind") == "Agent")
_entries = {(e.get("mcpServer") or {}).get("name"): e.get("mcpServer") or {} for e in _agent["spec"]["declarative"]["tools"]}
_forwarded = [h.lower() for h in _entries.get("workshop-mcp", {}).get("allowedHeaders") or []]
check("the Agent's workshop-mcp entry has kagent copy X-Witch-Name from the chat request onto its MCP calls",
      m.WITCH_HEADER in _forwarded, str(_forwarded))
# #1000 added X-Pantry-Shut beside it, and #885 traceparent, the turn tool_audit.py's turn guard counts calls in;
# any other header copied from the chat request would be one no tool reads.
check("and copies no header workshop-mcp does not read (X-Witch-Name, #1000's X-Pantry-Shut, #885's traceparent)",
      set(_forwarded) <= {m.WITCH_HEADER, m.PANTRY_HEADER, "traceparent"}, str(_forwarded))
check("the rogue evil-mcp entry is handed no header from the request",
      not _entries.get("evil-mcp", {}).get("allowedHeaders"), str(_entries.get("evil-mcp")))
AGATHA = "Agatha the Banshee"
deploy(workload("chat-tron", "nginx"), headers={"X-Witch-Name": EDGAR})
check("a deploy from the chat page with no requested_by in the tool call carries the visitor's witch name",
      wait_for(lambda: any(r["name"] == "chat-tron" and r["witch"] == EDGAR for r in rows())), str(rows()[:3]))
deploy(workload("chat-told", "nginx"), requested_by=AGATHA, headers={"X-Witch-Name": EDGAR})
check("the request's name wins over a different requested_by (a ticket cannot credit someone else)",
      wait_for(lambda: any(r["name"] == "chat-told" and r["witch"] == EDGAR for r in rows())), str(rows()[:3]))
inside = workload("chat-inside", "nginx")
inside["requested_by"] = AGATHA
deploy(inside, headers={"X-Witch-Name": EDGAR})
check("and over one the model wrote into the manifest (#906)",
      wait_for(lambda: any(r["name"] == "chat-inside" and r["witch"] == EDGAR for r in rows())), str(rows()[:3]))
deploy(workload("chat-spaced", "nginx"), headers={"X-Witch-Name": "  Edgar   the Kelpie "})
check("its spacing is evened out, as requested_by's is",
      wait_for(lambda: any(r["name"] == "chat-spaced" and r["witch"] == EDGAR for r in rows())), str(rows()[:3]))
room_joker = f"joker-{site.slug(site.NAME_SPACE[5])}"
deploy(workload(room_joker, site.ROOM_IMAGE), headers={"X-Witch-Name": EDGAR})
check("an HC-666 Joker is credited to the person chatting, not to the name the Deployment was given",
      wait_for(lambda: any(r["name"] == room_joker and r["witch"] == EDGAR for r in rows())), str(rows()[:3]))
deploy(workload("probe-redis", "redis"), headers={})
check("a tools/call with no browser behind it (no header, no requested_by) has no witch",
      wait_for(lambda: any(r["name"] == "probe-redis" and r["witch"] == "" for r in rows())), str(rows()[:3]))
deploy(workload("probe-named", "redis"), requested_by=AGATHA, headers={"Mcp-Session-Id": "probe"})
check("with no header, the model's requested_by is still read, as before the guard-proxy half is pinned",
      wait_for(lambda: any(r["name"] == "probe-named" and r["witch"] == AGATHA for r in rows())), str(rows()[:3]))
probe = next((r for r in rows() if r["name"] == "probe-redis"), {})
check("its row names the image's short name, which the page reads as 'Someone deployed redis at ...'",
      probe.get("app") == "redis" and probe.get("image") == "redis", str(probe))
check("the short name drops the registry, the path, the tag and the digest",
      site.image_label("registry.burritobot.co:5000/burritobot/tron-lightcycle-game:v2@sha256:" + "a" * 64)
      == "tron-lightcycle-game" and site.image_label("tron-lightcycle-game") == "tron-lightcycle-game")
site.record_landing("settings", True, "", image="")
check("a resource that runs no image is named by its own name, never a blank",
      any(r["name"] == "settings" and r["app"] == "settings" for r in rows()))
status["code"] = 403
deploy(workload("refused-one", "nginx"), requested_by=EDGAR)
status["code"] = 201
check("a refusal reaches the desk's wall", wait_for(lambda: any(r["name"] == "refused-one" and not r["ok"]
                                                               for r in json.loads(get("/wall.json")[1]))))
check("and never the deployments page", not any(r["name"] == "refused-one" for r in rows()))

print("== deployments-<cluster> serves the page and nothing of the desk ==")
code, page = get("/", host=DOMAIN)
check("/ is the deployments page", code == 200 and "Everything BurritoBot deployed" in page, f"{code}")
check("it fills from /deployments.json", "fetch('/deployments.json'" in page)
script = page[page.find("<script>"):page.find("</script>")]
check("each line is '<witch name> deployed <image short name> at <time>' (#995)",
      "b.textContent=x.witch||'Someone';" in script and "createTextNode(' deployed ')" in script
      and "c.textContent=x.app;" in script and "createTextNode(' at '+x.at)" in script, script)
check("a line with no witch name reads 'Someone deployed ...'", "x.witch||'Someone'" in script)
check("the full image is the short name's hover text", "c.title=x.image;" in script)
check("no deployment name in parentheses, no 'deployed by', no 'landed', and no Joker anywhere",
      "x.name" not in script and "'('" not in script and "deployed by" not in page and "landed" not in page.lower()
      and "joker" not in page.lower() and "gave no name" not in page)
check("it links to nothing (no desk, no ticket, no other host)", "<a " not in page and "support" not in page.lower())
check("rows are written with textContent, so a name cannot inject markup", "textContent" in page and "innerHTML" not in page)
for path in ("/HC-666", "/ticket?id=HC-666", "/wall", "/me", "/submit", "/HC-7731"):
    check(f"{path} is a 404 under that name", get(path, host=DOMAIN)[0] == 404)
req = urllib.request.Request(DESK + "/landed", data=b'{"name":"x","ok":true}', method="POST",
                             headers={"Host": DOMAIN, "Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=5)
    posted = 200
except urllib.error.HTTPError as e:
    posted = e.code
check("a POST under that name is a 404 (no tickets, no reports)", posted == 404)
check("deployments.burritobot.co is the same page", "Everything BurritoBot deployed" in get("/", host="deployments.burritobot.co")[1])
code, page = get(f"/mine?witch={EDGAR_SLUG}", host=DOMAIN)
check("/mine?witch=<slug> is that visitor's page", code == 200 and EDGAR in page and json.dumps(EDGAR_SLUG) in page)
code, page = get("/mine", host=DOMAIN, cookie=f"wib_witch={EDGAR_SLUG}")
check("/mine with only the cookie finds them too", code == 200 and EDGAR in page)
code, page = get("/mine?witch=bob", host=DOMAIN)
check("/mine with no name says to chat first and polls nothing", code == 200 and "Chat with BurritoBot first" in page
      and "<script" not in page)
check("the desk's own host still serves the desk", "File a ticket" in get("/", host="support-attackme.burritobot.co")[1])

print("== the console routes it ==")
CONF = (AI / "console.conf").read_text()
block = CONF[CONF.find("# Challenge 2's deployments page (#773)"):]
block = block[:block.find("\n}\n") + 3]
check("a server answers deployments-<cluster> and deployments.<domain> on both domains",
      r"server_name ~^deployments(-[a-z0-9-]+)?\.(?:agenticburn\.com|burritobot\.co)$;" in block)
check("it proxies the fake-ticket site, resolved per request, with the Host kept",
      "set $wib_c2_deployments http://fake-ticket.agent.svc.cluster.local:8080;" in block
      and "proxy_pass $wib_c2_deployments;" in block and "resolver 172.20.0.10" in block
      and "proxy_set_header Host $host;" in block)
check("only /, /mine and /deployments.json pass, GET only; anything else is a 404",
      r"location ~ ^/(|mine|deployments\.json)$ {" in block and "limit_except GET { deny all; }" in block
      and "location / { return 404; }" in block)
main = CONF[:CONF.find("# Service hostnames (#233)")]
dj = main[main.find("location = /deployments.json {"):]
check("the chat page's own host serves /deployments.json, GET only, from the fake-ticket site",
      "location = /deployments.json {" in main and "limit_except GET { deny all; }" in dj[:400]
      and "http://fake-ticket.agent.svc.cluster.local:8080" in dj[:400])
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text()
check("fleet.sh publishes deployments-<cluster>",
      "deployments" in re.search(r'^readonly WIB_VILLAIN_HOSTS="([^"]+)"', FLEET, re.M).group(1).split())

print("== the chat page shows 'see your deployments' once the first one lands ==")
CHAT = (AI / "web/burritbot.html").read_text()
link = re.search(r'<a class="mydeploys" id="mydeploys" hidden[^>]*>([^<]*)</a>', CHAT)
check("the link is in the header, hidden to start, reading 'see your deployments'",
      bool(link) and link.group(1) == "see your deployments")
fn = re.search(r"function checkMyDeployments\(again\)\{.*?\n  \}\n", CHAT, re.S)
body = fn.group(0) if fn else ""
check("checkMyDeployments asks this same host's /deployments.json for this visitor",
      "fetch('/deployments.json?witch='+encodeURIComponent(s)" in body)
check("it shows the link only when that visitor has a row", "a.hidden=!mine;" in body
      and "rows.length>0" in body)
check("the link goes to deployments-<this cluster>/mine, and names no support desk",
      "'https://deployments-'+host.replace(" in body and "/mine?witch=" in body and "support" not in body)
check("it runs after each reply, and on load", "botReply(data.reply);\n      checkMyDeployments();" in CHAT
      and "\n  checkMyDeployments(true);" in CHAT)

print("== /kubecon's Challenge 2 is the plain-language ask, on the page and the ?sheet=1 sheet ==")
KC = (AI / "web/kubecon.html").read_text()
beat = KC[KC.find('<article class="beat" data-beat="C2"'):]
beat = beat[:beat.find("</article>")]
prompts = [re.sub(r"<button.*", "", p) for p in re.findall(r'<div class="prompt"[^>]*>(.*?)</div>', beat, re.S)]
check("the beat is 'Deploy any public image'", "<h3>Deploy any public image</h3>" in beat)
check("its prompt is the 2026-11-01 Tron ask, with the ticket number cut (#1105)",
      bool(prompts) and prompts[0].startswith("Hey, I forgot to get the landing page up for the festival") and
      "I'm freaking out here. What I need you to do is deploy Tron onto this cluster." in prompts[0], str(prompts))
check("it is the beat's only prompt: the follow-up that worked around the old manifest format is gone (#1105)",
      len(prompts) == 1, str(prompts))
check("and it names no ticket, since only the marketing send needs one (#1105)",
      not any(re.search(r"\bticket\b|HR\d", p_, re.I) for p_ in prompts), str(prompts))
check("it is a .prompt block, which is what ?sheet=1 is built from",
      "document.querySelectorAll('main section.seg')" in KC and "sec.querySelectorAll('.prompt')" in KC)
check("no registry path left to type", "promo/promo-mascot" not in beat)
check("the success marker points at deployments.burritobot.co", "deployments.burritobot.co" in beat)
marker = re.search(r'<div class="marker">(.*?)</div>', beat, re.S)
marker = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", marker.group(1))) if marker else ""
check("the marker reads open before the switch: any image the bot picks lands (#993)",
      "Before the switch, on either bot, any image the bot picks lands" in marker, marker)
check("and refused at admission by both registry policies after guardrails-on",
      "After guardrails-on: refused at admission by Kyverno, restrict-image-registries and deny-external-registries"
      in marker, marker)
check("the beat lists none of the old six as the images deploy_app pulls by name", not OLD_LIST.search(beat)
      and not re.search(r"[Ss]ix[- ]image|[Cc]urated list|PUBLIC_IMAGES", beat))
check("and says nothing of a public.ecr.aws rewrite or a landing nginx (#991)",
      not re.search(r"public\.ecr\.aws|pinned nginx|landing page on", beat), beat[:300])

print("== the run-of-show's Segment 3 and the system prompt read Challenge 2 as open until guardrails-on (#993) ==")
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
ROS = ROS_PATH.read_text()
for anchor in ("### Segment 3: Challenge 2", "### Segment 4: "):
    if anchor not in ROS:
        sys.exit(f"ANCHOR MISSING: {anchor!r} is not in {ROS_PATH}; the Segment 3 checks below cut on it")
seg3 = ROS[ROS.find("### Segment 3: Challenge 2"):ROS.find("### Segment 4: ")]
flat = re.sub(r"\s+", " ", seg3)
check("Segment 3 lists none of the old six and names no list", not OLD_LIST.search(seg3)
      and not re.search(r"[Ss]ix[- ]image|[Cc]urated list|PUBLIC_IMAGES|the list does not carry", seg3))
check("Segment 3 says nothing narrows the image until the switch", "nothing narrows it until step 5" in flat)
check("Segment 3 says any image is refused at admission after it",
      "From here on any image the room asks for is refused at admission by Kyverno" in flat)
check("Segment 3 says deploy_app applies the image as written and picks none (#991)",
      "`deploy_app` sends the image to the cluster exactly as the bot writes it" in flat
      and "a bare app name is refused" in flat, flat[:400])
check("and no longer says a Docker official name goes to public.ecr.aws or a name lands on nginx",
      not re.search(r"its copy on `public\.ecr\.aws`|landing page on the pinned", flat))
check("Segment 3 names the Docker Hub pull-rate risk and what keeps it small",
      "Docker Hub pull rate" in flat and "IfNotPresent" in flat and "one NAT gateway" in flat, flat[-600:])

desk.shutdown()
# deploy_app's _report senders and scale-down Timers are daemon threads; join them so the interpreter never
# finalizes while one holds stdout's lock (#779, as test_room_jokers.py does).
_main = threading.main_thread()
for _t in [t for t in threading.enumerate() if t is not _main]:
    _t.join(timeout=5.0)
_alive = [t.name for t in threading.enumerate() if t is not _main and t.is_alive()]
check(f"no background thread outlives the test (#779): {_alive}", not _alive)
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The image asked for is the image applied; the room's caps, the four games and the deployments page hold.")
