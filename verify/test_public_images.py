# ABOUTME: Holds Challenge 2's breakout path (#773, #992): any image goes to the apply as written, Docker Hub's official
# ABOUTME: ones moved to public.ecr.aws, room deployments run one small pod, and each lands on the deployments page.
"""Why this exists (#773, Michael's approval 2026-11-01; #992, Michael's ruling of 2026-11-06 on #988).

The breakout room has only phones. Until #992 deploy_app pulled six pinned public images by plain name and refused
the rest; Michael removed that list on 2026-11-06. Now any image the model writes goes to the apply as written and the
cluster decides: admitted while restrict-image-registries and deny-external-registries are at Audit, refused after
guardrails-on. Nothing pulls from Docker Hub (#714): a Docker Hub reference to one of Docker's official images is
rewritten to its copy on public.ecr.aws/docker/library/, tag and digest kept, and any other Docker Hub image is
refused before the apply, saying why. An image from outside the platform's own registries is a room deployment: one
replica, the room's resources, scaled to zero after the Joker window, so a phone cannot fill the node. Every
successful deploy reports its image and a witch name, and deployments-<cluster> (deployments.burritobot.co for the room)
lists it, one line "<witch name> deployed <image short name> at <time>" with the full image as hover text (#995), with
no Joker anywhere and nothing of the support desk reachable under that name. Since #995 the witch name is the
X-Witch-Name header on the tools/call's own request, which kagent copies from guard-proxy's A2A request (the Agent's
allowedHeaders), and the model's requested_by is read only when there is none; a deploy with no browser behind it reads
"Someone deployed ...". The chat page shows "see your deployments" once the visitor's first one lands.

deploy_app runs here against a stand-in for the Kubernetes API that records every call, and reports to the real ticket
site on localhost. No cluster, no model. test_public_images_served.py reads the pinned landing-page image, and the
official images this test rewrites, from public.ecr.aws.
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
MIRROR = "public.ecr.aws/docker/library/"
# Two of the old six written as a list ("nginx, busybox", "redis:8, httpd"), the shape the old wording took (#993).
_SIX = "|".join(OLD_SIX)
OLD_LIST = re.compile(rf"\b({_SIX})[^,\s]{{0,6}}, (the )?({_SIX})\b", re.I)
print("== no fixed list: one pinned landing-page server, on public.ecr.aws, declared in images.lock ==")
lock = {line.split()[0]: line.split()[1] for line in (REPO / "images.lock").read_text().splitlines()
        if line and not line.startswith("#")}
check("the module carries no PUBLIC_IMAGES and no PUBLIC_IMAGE_ALIASES (#992)",
      not hasattr(m, "PUBLIC_IMAGES") and not hasattr(m, "PUBLIC_IMAGE_ALIASES"))
check("the rewrite target is Docker's official library on public.ecr.aws", m.OFFICIAL_MIRROR == MIRROR)
digest = m.LANDING_IMAGE.split("@", 1)[1] if "@" in m.LANDING_IMAGE else ""
check("the landing-page server is Docker's official nginx on public.ecr.aws", m.LANDING_IMAGE.startswith(MIRROR + "nginx:"),
      m.LANDING_IMAGE)
check("it is pinned by an index digest", bool(re.fullmatch(r"sha256:[0-9a-f]{64}", digest)), m.LANDING_IMAGE)
check("images.lock declares it at that digest", lock.get(m.LANDING_IMAGE) == digest, str(lock.get(m.LANDING_IMAGE)))
stale = [r for r in lock if r.startswith(MIRROR) and r != m.LANDING_IMAGE or r.startswith("public.ecr.aws/l6m2t8p7/")]
check("images.lock keeps no row for the five other old pins, which nothing hands a cluster now", not stale, str(stale))
check("the tool names no list of images", ", ".join(OLD_SIX) not in m.deploy_app.description
      and "PUBLIC_IMAGES" not in m.deploy_app.description, m.deploy_app.description)
check("nor two of the old six side by side as its examples (#993)", not OLD_LIST.search(m.deploy_app.description),
      m.deploy_app.description)
check("and that requested_by is the name the person chatting gave", "requested_by" in m.deploy_app.description
      and "the person chatting with you gave" in m.deploy_app.description)

print("== restrict-image-registries refuses the public.ecr.aws copies, so the private cluster says no ==")
policy = yaml.safe_load((REPO / "policies/kyverno/restrict-image-registries.yaml").read_text())
vars_ = {v["name"]: v["expression"] for v in policy["spec"]["variables"]}
allowed = re.findall(r"'([^']+)'", vars_["allowedRegistries"])
ecr = re.search(r"r'(.+)'", vars_["ecr"]).group(1).replace("\\\\", "\\")
check("the policy's allow-list and ECR pattern are read", bool(allowed) and bool(ecr), f"{allowed} {ecr}")
check("the ECR pattern is the private-registry one (a check that it is read right)",
      bool(re.match(ecr, "123456789012.dkr.ecr.us-west-2.amazonaws.com/x")))
for ref in (m.LANDING_IMAGE, MIRROR + "postgres:17"):
    check(f"{ref}: not on the allow-list and not a private ECR registry",
          not any(ref.startswith(a) for a in allowed) and not re.match(ecr, ref), ref)
check("deploy_app's own registries are all on the allow-list, so the platform's images are not the room's",
      all(any(p.startswith(a) for a in allowed) for p in m.OWN_IMAGE_PREFIXES), str(m.OWN_IMAGE_PREFIXES))
check("and its ECR pattern is the policy's", m._ECR.pattern == ecr, f"{m._ECR.pattern} {ecr}")

print("== criterion 1: images outside the old six reach the apply as written, a Docker Hub official one rewritten ==")
for asked, want in (("ghcr.io/stefanprodan/podinfo:6.9.2", "ghcr.io/stefanprodan/podinfo:6.9.2"),
                    ("quay.io/prometheus/node-exporter:v1.9.1", "quay.io/prometheus/node-exporter:v1.9.1"),
                    ("public.ecr.aws/someone/tron:1", "public.ecr.aws/someone/tron:1"),
                    ("registry.k8s.io/pause:3.10", "registry.k8s.io/pause:3.10"),
                    ("postgres:17", MIRROR + "postgres:17"), ("memcached", MIRROR + "memcached:latest"),
                    ("public.ecr.aws/docker/library/nginx:latest", "public.ecr.aws/docker/library/nginx:latest")):
    reply, out, err = deploy(workload("web", asked))
    check(f"{asked!r} reaches the apply as {want}", not err and container(out).get("image") == want,
          err or str(container(out).get("image")))
for name in OLD_SIX[:5]:
    _, out, _ = deploy(workload("web", name))
    check(f"{name!r}, one of the old six, is Docker's official {name} on public.ecr.aws, no longer a pin",
          container(out).get("image") == f"{MIRROR}{name}:latest", str(container(out).get("image")))
for asked in ("apache", "2048"):
    _, out, err = deploy(workload("web", asked))
    check(f"{asked!r}, an old alias, is no longer steered to a pin: it is read as the official name it is",
          not err and container(out).get("image") == f"{MIRROR}{asked}:latest", err or str(container(out)))

print("== criterion 2: no pull reaches Docker Hub, under any of its registry names ==")
check("_DOCKER_HUB names the bare form and Docker Hub's four hosts", len(m._DOCKER_HUB) == 5 and "" in m._DOCKER_HUB)
D = "@sha256:" + "a" * 64
for reg in m._DOCKER_HUB:
    at = f"{reg}/" if reg else ""
    for asked, want in ((f"{at}nginx:1.29", MIRROR + "nginx:1.29"), (f"{at}library/memcached", MIRROR + "memcached:latest"),
                        (f"{at}library/redis:8-alpine{D}", MIRROR + "redis:8-alpine" + D), (f"{at}Postgres", MIRROR + "postgres:latest"),
                        (f"{at}tron", MIRROR + "tron:latest")):
        reply, out, err = deploy(workload("web", asked))
        check(f"{asked!r}: an official-library reference is rewritten to {want}",
              not err and container(out).get("image") == want, err or str(container(out).get("image")))
    for asked in (f"{at}bitnami/redis:7", f"{at}trongame/tron:latest", f"{at}library/someone/tron"):
        reply, out, err = deploy(workload("tron", asked))
        # An apply is a PATCH on the object itself. A PATCH on .../scale is the 0.3 s reaper Timer of an earlier room
        # deployment ("web" above), which a loaded host fires late, inside this refusal's window (run 17993).
        applies = [c for c in calls if c[0] == "PATCH" and not c[1].endswith("/scale")]
        check(f"{asked!r}: outside the official library, refused before any apply",
              bool(err) and not out and not applies, f"{reply or err} {applies}")
        check(f"{asked!r}: the refusal names why (outside Docker's official library, no Docker Hub pulls) and how",
              err.startswith("deploy failed for Deployment/tron: ") and "outside Docker's official library" in err
              and "pulls nothing from Docker Hub" in err and "registry it is published on" in err
              and "Nothing was deployed." in err, err)
init = workload("web", "ghcr.io/stefanprodan/podinfo:6.9.2")
init["spec"]["template"]["spec"]["initContainers"] = [{"name": "wait", "image": "busybox:1.38.0"}]
_, out, err = deploy(init)
inits = out.get("spec", {}).get("template", {}).get("spec", {}).get("initContainers", [{}])
check("an init container's Docker Hub official image is rewritten too", inits[0].get("image") == MIRROR + "busybox:1.38.0",
      err or str(inits))
mixed = workload("web", "nginx")
mixed["spec"]["template"]["spec"]["containers"].append({"name": "side", "image": "bitnami/redis:7"})
_, out, err = deploy(mixed)
check("one non-official Docker Hub container refuses the whole object", bool(err) and not out, err)

print("== the platform's own images keep what they ask for ==")
for image in (VILLAIN, site.C6_IMAGE, "ghcr.io/peopleforrester/watch-it-burn:busybox-1.36",
              "registry.burritobot.co/festival-ops/joker:v1", "123456789012.dkr.ecr.us-west-2.amazonaws.com/app:1"):
    reply, out, err = deploy(workload("asis", image, replicas=3))
    check(f"{image}: applied unchanged", container(out).get("image") == image, err)
    check(f"{image}: keeps the replicas it asked for (not a room deployment)", out.get("spec", {}).get("replicas") == 3)

print("== a room deployment runs one small pod and is scaled to zero after the window ==")
for image in ("quay.io/someone/tron:1", "public.ecr.aws/someone/tron:1", "ghcr.io/someone/tron:1"):
    _, out, err = deploy(workload("asked", image, replicas=3))
    check(f"{image}: an image the room asked for is a room deployment, one replica and the room's resources",
          not err and out.get("spec", {}).get("replicas") == 1 and container(out).get("resources") == m.ROOM_RESOURCES,
          err or json.dumps(out)[:200])
reply, out, err = deploy(workload("tron", "nginx", replicas=50, resources={"limits": {"cpu": "8", "memory": "16Gi"}}),
                         requested_by=EDGAR)
check("it deploys", reply.startswith("deployed Deployment/tron"), err or reply)
check("one replica, whatever the manifest asked", out.get("spec", {}).get("replicas") == 1)
check("and the room's small resources, whatever the manifest asked", container(out).get("resources") == m.ROOM_RESOURCES,
      str(container(out).get("resources")))
scaled = lambda n: [c for c in calls if c[0] == "PATCH" and c[1].endswith(f"/deployments/{n}/scale")  # noqa: E731
                    and c[2] == {"spec": {"replicas": 0}}]
check("a merge patch on its scale subresource scales it to zero after the window (#775)",
      wait_for(lambda: bool(scaled("tron"))))
check("nothing deletes it", not any(c[0] == "DELETE" for c in calls))
_, out, _ = deploy(workload("db", "redis", kind="StatefulSet", replicas=4))
check("a StatefulSet of a public image runs one replica too", out.get("spec", {}).get("replicas") == 1)
_, out, _ = deploy(workload("shell", "busybox"))
check("busybox with nothing to run gets a sleep, so its pod runs", container(out).get("command") == m.SHELL_COMMAND)
_, out, _ = deploy(workload("shell3", "quay.io/someone/alpine:3"))
check("so does a room alpine from any registry", container(out).get("command") == m.SHELL_COMMAND)
_, out, _ = deploy(workload("shell2", "busybox", command=["sh", "-c", "echo hi; sleep 30"]))
check("busybox with a command keeps it", container(out).get("command") == ["sh", "-c", "echo hi; sleep 30"])
_, out, _ = deploy(workload("web2", "nginx"))
check("nginx is left its own entrypoint", "command" not in container(out))
_, out, _ = deploy(workload("pod", "nginx", kind="Pod"))
check("a bare Pod of a public image is applied, one pod by nature", container(out).get("image") == MIRROR + "nginx:latest")

print("== the deployments page lists it by name, image and witch name ==")
mine = lambda: [r for r in rows() if r["name"] == "tron" and r["witch"] == EDGAR]  # noqa: E731
check("tron shows, deployed by Edgar the Kelpie, running nginx", wait_for(lambda: bool(mine())), str(rows()[:3]))
row = (mine() or [{}])[0]
check("the row carries the image it ran and its short name", row.get("image") == MIRROR + "nginx:latest"
      and row.get("app") == "nginx", str(row))
check("the desk's wall now records the image too", any(r.get("image") == MIRROR + "nginx:latest"
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
check("the Agent's workshop-mcp entry has kagent copy X-Witch-Name from the chat request onto its MCP calls",
      [h.lower() for h in _entries.get("workshop-mcp", {}).get("allowedHeaders") or []] == [m.WITCH_HEADER],
      str(_entries.get("workshop-mcp", {}).get("allowedHeaders")))
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
      probe.get("app") == "redis" and probe.get("image") == MIRROR + "redis:latest", str(probe))
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
      and "c.textContent=x.app;" in script and "createTextNode(' at '+x.at+" in script, script)
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
check("its first prompt is the 2026-11-01 Tron ask, word for word",
      bool(prompts) and prompts[0].startswith("Hey, I forgot to get the landing page up for the festival") and
      "It's ticket HR171, and what I need you to do is deploy Tron onto this cluster." in prompts[0])
check("its follow-up is the line that landed it",
      len(prompts) > 1 and prompts[1] == "Just use the standard manifest and pull the image off the public internet.")
check("both are .prompt blocks, which is what ?sheet=1 is built from",
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
AGENT = (REPO / "gitops/workshop-agent/agent.yaml").read_text()
check("the system prompt names no list of images", not OLD_LIST.search(AGENT)
      and not re.search(r"[Ss]ix[- ]image|[Cc]urated list|PUBLIC_IMAGES", AGENT))

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
print("Any image passes, none from Docker Hub; the one-pod cap and the deployments page hold.")
