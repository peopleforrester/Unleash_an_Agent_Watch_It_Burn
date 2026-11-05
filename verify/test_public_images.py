# ABOUTME: Holds Challenge 2's breakout path (#773): a plain name becomes a pinned public image, one replica, and every
# ABOUTME: landed deployment shows on the deployments page by name, image and witch name; refusals and the desk do not.
"""Why this exists (#773, Michael's approval 2026-11-01).

The breakout room has only phones, so nobody types a registry path. "Deploy nginx" or "run busybox" is the ask, and
workshop-mcp's real deploy_app puts the pinned public image in from PUBLIC_IMAGES, caps the workload at one replica
and scales it to zero after the Joker window, so a phone cannot fill the node. Every successful deploy reports its
image and the witch name the bot passed as requested_by, and deployments-<cluster> (deployments.burritobot.co for the
room) lists it, with no Joker anywhere and nothing of the support desk reachable under that name. The chat page shows
"see your deployments" once the visitor's first one lands. A Docker Hub name the list does not carry is refused,
naming the list, since nothing here pulls from Docker Hub (#714); an image with a registry of its own, the villains
included, is left exactly as written, because whether it runs is the cluster's call.

deploy_app runs here against a stand-in for the Kubernetes API that records every call, and reports to the real ticket
site on localhost. No cluster, no model. test_public_images_served.py reads each pinned digest from public.ecr.aws.
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


def deploy(obj: dict, requested_by: str = "") -> tuple[str, dict, str]:
    """deploy_app's reply, the object it applied, and the refusal it raised ("" when none)."""
    calls.clear()
    try:
        reply = m.deploy_app(yaml.safe_dump(obj), requested_by=requested_by)
    except RuntimeError as e:
        return "", {}, str(e)
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

print("== the list: public images on public.ecr.aws, pinned by digest, declared in images.lock ==")
lock = {line.split()[0]: line.split()[1] for line in (REPO / "images.lock").read_text().splitlines()
        if line and not line.startswith("#")}
check("busybox and nginx are on it, as Michael named them", {"busybox", "nginx"} <= set(m.PUBLIC_IMAGES))
check("it stays small: six images or fewer", len(m.PUBLIC_IMAGES) <= 6, str(list(m.PUBLIC_IMAGES)))
for name, ref in m.PUBLIC_IMAGES.items():
    digest = ref.split("@", 1)[1] if "@" in ref else ""
    check(f"{name}: on public.ecr.aws, so nothing comes from Docker Hub", ref.startswith("public.ecr.aws/"), ref)
    check(f"{name}: pinned by an index digest", bool(re.fullmatch(r"sha256:[0-9a-f]{64}", digest)), ref)
    check(f"{name}: images.lock declares it at that digest", lock.get(ref) == digest, str(lock.get(ref)))
check("every alias names an image on the list", set(m.PUBLIC_IMAGE_ALIASES.values()) <= set(m.PUBLIC_IMAGES))
check("the tool tells the model the names it can use", all(n in m.deploy_app.description for n in m.PUBLIC_IMAGES),
      m.deploy_app.description)
check("and that requested_by is the name the person chatting gave", "requested_by" in m.deploy_app.description
      and "the person chatting with you gave" in m.deploy_app.description)

print("== restrict-image-registries refuses every one of them, so the private cluster says no ==")
policy = yaml.safe_load((REPO / "policies/kyverno/restrict-image-registries.yaml").read_text())
vars_ = {v["name"]: v["expression"] for v in policy["spec"]["variables"]}
allowed = re.findall(r"'([^']+)'", vars_["allowedRegistries"])
ecr = re.search(r"r'(.+)'", vars_["ecr"]).group(1).replace("\\\\", "\\")
check("the policy's allow-list and ECR pattern are read", bool(allowed) and bool(ecr), f"{allowed} {ecr}")
check("the ECR pattern is the private-registry one (a check that it is read right)",
      bool(re.match(ecr, "123456789012.dkr.ecr.us-west-2.amazonaws.com/x")))
for name, ref in m.PUBLIC_IMAGES.items():
    check(f"{name}: not on the allow-list and not a private ECR registry",
          not any(ref.startswith(a) for a in allowed) and not re.match(ecr, ref), ref)

print("== a plain name, any way the model writes it, becomes the pinned image ==")
for asked, want in (("nginx", "nginx"), ("nginx:latest", "nginx"), ("NGINX", "nginx"), ("library/nginx", "nginx"),
                    ("docker.io/library/nginx:1.27-alpine", "nginx"), ("docker.io/nginx", "nginx"),  # refused (#714)
                    ("apache", "httpd"), ("httpd:2.4", "httpd"), ("redis:7", "redis"), ("alpine", "alpine"),
                    ("2048", "2048"), ("docker-2048", "2048"), ("busybox@sha256:" + "0" * 64, "busybox"),
                    ("public.ecr.aws/docker/library/nginx:latest", "nginx"),
                    ("public.ecr.aws/l6m2t8p7/docker-2048", "2048")):
    reply, out, err = deploy(workload("web", asked))
    check(f"{asked!r} deploys {want}'s pinned image", container(out).get("image") == m.PUBLIC_IMAGES[want],
          err or str(container(out).get("image")))

print("== a Docker Hub name the list does not carry is refused, naming the list ==")
for asked in ("tron", "someone/tron:latest", "docker.io/someone/tron", "index.docker.io/library/tron"):  # refused (#714)
    reply, out, err = deploy(workload("tron", asked))
    check(f"{asked!r} raises before any apply", bool(err) and not out and not [c for c in calls if c[0] == "PATCH"],
          reply or err)
    check(f"{asked!r}: the refusal says 'deploy failed for', names every image on the list, and that nothing landed",
          err.startswith("deploy failed for Deployment/tron: ") and all(n in err for n in m.PUBLIC_IMAGES)
          and "Nothing was deployed." in err and "Docker Hub" in err, err)

print("== an image with a registry of its own is left as written ==")
for image in (VILLAIN, site.C6_IMAGE, "ghcr.io/peopleforrester/watch-it-burn:busybox-1.36", "quay.io/someone/tron:1",
              "public.ecr.aws/someone/tron:1"):
    reply, out, err = deploy(workload("asis", image, replicas=3))
    check(f"{image}: applied unchanged", container(out).get("image") == image, err)
    check(f"{image}: keeps the replicas it asked for (not a room deployment)", out.get("spec", {}).get("replicas") == 3)

print("== a room deployment runs one small pod and is scaled to zero after the window ==")
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
_, out, _ = deploy(workload("shell2", "busybox", command=["sh", "-c", "echo hi; sleep 30"]))
check("busybox with a command keeps it", container(out).get("command") == ["sh", "-c", "echo hi; sleep 30"])
_, out, _ = deploy(workload("web2", "nginx"))
check("nginx is left its own entrypoint", "command" not in container(out))
_, out, _ = deploy(workload("pod", "nginx", kind="Pod"))
check("a bare Pod of a public image is applied, one pod by nature", container(out).get("image") == m.PUBLIC_IMAGES["nginx"])

print("== the deployments page lists it by name, image and witch name ==")
mine = lambda: [r for r in rows() if r["name"] == "tron" and r["witch"] == EDGAR]  # noqa: E731
check("tron shows, deployed by Edgar the Kelpie, running nginx", wait_for(lambda: bool(mine())), str(rows()[:3]))
row = (mine() or [{}])[0]
check("the row carries the pinned image and its short name", row.get("image") == m.PUBLIC_IMAGES["nginx"]
      and row.get("app") == "nginx", str(row))
check("the desk's wall now records the image too", any(r.get("image") == m.PUBLIC_IMAGES["nginx"]
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
check("it says 'deployed by' and names no Joker anywhere", "deployed by" in page and "joker" not in page.lower())
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
print("Challenge 2's public images, the one-pod cap and the deployments page hold.")
