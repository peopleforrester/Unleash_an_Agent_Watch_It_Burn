# ABOUTME: Holds #995 end to end: a deploy_app tools/call on a request carrying X-Witch-Name is credited to that witch with no
# ABOUTME: requested_by, and deployments-<cluster>'s own script renders "<witch> deployed <image> at <time>" or "Someone deployed",
# ABOUTME: and a row a cluster read reports gone as "..., removed at <time>", greyed (#1049).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: uv for mcp 1.29.1 and pyyaml 6.0.2 as the image pins them; node runs the page's script)
"""The executed half of the #995 checks in verify/test_public_images.py.

1. workshop-mcp-server.py runs on mcp==1.29.1 and pyyaml==6.0.2, the versions images/workshop-mcp pins, with tool_audit.py beside it as
   the ConfigMap mounts them, served over streamable HTTP on localhost with the Kubernetes API stubbed. The real MCP
   client calls deploy_app three ways: on a request carrying X-Witch-Name: Edgar the Kelpie and no requested_by (the
   chat page's deploy once guard-proxy sends the header and kagent copies it, gitops/workshop-agent/agent.yaml); on
   that request with requested_by naming someone else; and on a request with no header and no requested_by (a probe).
   Each reports to the real support desk (ticket_site.py) on localhost, whose /deployments.json is read back. This is
   the part the offline test can only fake: that the header really is on the request context deploy_app reads.
2. The deployments page's own script, served by that desk under deployments-<cluster>, runs in node against those
   rows with stub elements, and each line's text and hover text are read off what it built. Before it runs, a cluster
   read report that omits the probe's Deployment is posted to the desk's /cluster-read (#1049), so the probe's line is
   the removed one: it reads "..., removed at <time>" and carries the class the page greys.

Needs uv and the network to fetch mcp, and node. A missing tool or a failed fetch is a failure, not a skip. No cluster.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import package_cache  # noqa: E402
import threading
import time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("A chat deploy carries the request's witch name, and each line reads '<witch> deployed <image> at <time>'.")
    sys.exit(0)


for tool in ("uv", "node"):
    if shutil.which(tool) is None:
        print(f"FAILED: {tool} not on PATH; this E2E check cannot run, which is a failure, not a skip")
        sys.exit(1)

spec = importlib.util.spec_from_file_location("ticket_site_witch_line", AI / "ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
desk = site.Server(("127.0.0.1", 0), site.Handler)
threading.Thread(target=desk.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{desk.server_address[1]}"

EDGAR = "Edgar the Kelpie"
AGATHA = "Agatha the Banshee"
DOMAIN = "deployments-attackme.burritobot.co"

# The server half and the client half in one process on the pinned library: the server on its own thread, as the pod
# runs it (mcp.run(transport="streamable-http")), and the client on the main one. The Kubernetes API is stubbed the
# way verify/test_public_images.py stubs it; the support desk is the real one above.
PROBE = r"""
import asyncio, importlib.util, json, socket, sys, threading, time
ai, desk, edgar, agatha = sys.argv[1:5]
sys.path.insert(0, ai)
spec = importlib.util.spec_from_file_location("srv", ai + "/workshop-mcp-server.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m._ns = lambda: "agent"
m.TICKET_SITE_URL = desk
KINDS = (("Deployment", "deployments"),)

def fake_req(method, path, body=None, content_type="application/json"):
    if method == "GET":
        return 200, json.dumps({"resources": [{"kind": k, "name": n} for k, n in KINDS]})
    return 201, "{}"

m._req = fake_req
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
m.mcp.settings.host = "127.0.0.1"
m.mcp.settings.port = port
threading.Thread(target=m.mcp.run, kwargs={"transport": "streamable-http"}, daemon=True).start()
for _ in range(150):
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            break
    time.sleep(0.2)

def manifest(name, image):
    return json.dumps({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name},
                       "spec": {"selector": {"matchLabels": {"app": name}}, "template": {
                           "metadata": {"labels": {"app": name}}, "spec": {"containers": [{"name": name, "image": image}]}}}})

def text(result):
    return "".join(getattr(b, "text", "") or "" for b in result.content or [])

async def call(headers, args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("deploy_app", args)
            return {"error": bool(res.isError), "text": text(res)}

async def main():
    out = {
        "chat": await call({"X-Witch-Name": edgar}, {"manifest": manifest("tron-lightcycle-game", "ghcr.io/someone/tron-lightcycle-game:2")}),
        "told": await call({"X-Witch-Name": edgar}, {"manifest": manifest("told", "quay.io/someone/arcade:1"), "requested_by": agatha}),
        "probe": await call({}, {"manifest": manifest("probe-redis", "redis:8")}),
    }
    print("RESULT " + json.dumps(out), flush=True)

asyncio.run(main())
# deploy_app reports to the desk on daemon threads, each named for _report's send(); let them finish first.
for t in threading.enumerate():
    if t.name.endswith("(send)"):
        t.join(timeout=5)
"""

print("== a deploy_app tools/call over the real MCP transport takes the witch name from its request ==")
data = tempfile.mkdtemp(prefix="deployments-witch-line-")
# The two libraries images/workshop-mcp pins, at its versions: deploy_app reads a manifest with yaml.
r = subprocess.run([*package_cache.run_cmd("mcp"), "python", "-I", "-c",
                    PROBE, str(AI), DESK,
                    EDGAR, AGATHA],
                   capture_output=True, text=True, cwd="/", timeout=600,
                   env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "WORKSHOP_DATA_DIR": data,
                        "JOKER_SCALE_DOWN_SECONDS": "3600"})
results = [json.loads(line[len("RESULT "):]) for line in r.stdout.splitlines() if line.startswith("RESULT ")]
check("workshop-mcp serves and answers three deploy_app calls under mcp 1.29.1", r.returncode == 0 and len(results) == 1,
      (r.stderr.strip() or r.stdout.strip())[-800:])
if not results:
    finish()
res = results[0]
check("each call deployed", all(not v["error"] and v["text"].startswith("deployed Deployment/") for v in res.values()),
      json.dumps(res)[:600])


def rows() -> list[dict]:
    with urllib.request.urlopen(DESK + "/deployments.json", timeout=5) as resp:
        return json.loads(resp.read())


deadline = time.time() + 5
while time.time() < deadline and len(rows()) < 3:
    time.sleep(0.1)
by_name = {row["name"]: row for row in rows()}
check("the desk has all three rows", {"tron-lightcycle-game", "told", "probe-redis"} <= set(by_name), str(list(by_name)))
check("the chat deploy, with no requested_by in the tool call, is credited to the request's witch name",
      by_name.get("tron-lightcycle-game", {}).get("witch") == EDGAR, str(by_name.get("tron-lightcycle-game")))
check("the request's witch name wins over a requested_by naming someone else",
      by_name.get("told", {}).get("witch") == EDGAR, str(by_name.get("told")))
check("the probe's deploy, with no header and no requested_by, has no witch name",
      by_name.get("probe-redis", {}).get("witch") == "", str(by_name.get("probe-redis")))
check("each row carries the kind deploy_app created, sent over /landed (#1049)",
      all(by_name.get(n, {}).get("kind") == "Deployment" for n in ("tron-lightcycle-game", "told", "probe-redis")),
      str(by_name))

print("== a cluster read that omits the probe's Deployment marks its row removed (#1049) ==")
taken = time.time() + 1
read = urllib.request.Request(DESK + "/cluster-read", method="POST", headers={"Content-Type": "application/json"},
                              data=json.dumps({"taken_at": taken, "ok": True,
                                               "kinds": {"Deployment": ["tron-lightcycle-game", "told"]}}).encode())
with urllib.request.urlopen(read, timeout=5) as resp:
    marked = json.loads(resp.read())
check("the desk marks the probe's row and only it", marked == {"applied": True, "marked": ["probe-redis"]}, str(marked))
removed_at = time.strftime("%H:%M:%S", time.localtime(taken))

print("== the deployments page's own script renders each line ==")
req = urllib.request.Request(DESK + "/", headers={"Host": DOMAIN})
with urllib.request.urlopen(req, timeout=5) as resp:
    page = resp.read().decode()
found = re.search(r"<script>(.*?)</script>", page, re.S)
check("deployments-<cluster> serves the page with its script", bool(found))
if not found:
    finish()

# Stub elements: enough of the DOM for what the script builds. An element's text is its own textContent, or its
# children's text in order, which is what a browser shows for these elements.
HARNESS = r"""
const [script, rows] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
function el(tag){return {tag, children:[], className:'', title:'', _text:null,
  set textContent(v){this._text=String(v);this.children=[];}, get textContent(){return this._text!==null?this._text:
  this.children.map(c=>c.textContent).join('');}, appendChild(c){this.children.push(c);return c;},
  replaceChildren(...cs){this.children=cs;this._text=null;}};}
const ul = el('ul');
const document = {getElementById: id => id === 'deployments' ? ul : null, createElement: el,
  createTextNode: t => ({tag:'#text', title:'', get textContent(){return String(t);}, children:[]})};
const fetch = async () => ({json: async () => rows});
const vm = require('vm');
const ctx = vm.createContext({document, fetch, setInterval: () => 0, encodeURIComponent, console});
vm.runInContext(script, ctx);
setTimeout(() => {
  const lines = ul.children.map(li => ({text: li.textContent, cls: li.className,
    hover: li.children.filter(c => c.tag === 'code').map(c => c.title)}));
  process.stdout.write(JSON.stringify(lines));
}, 200);
"""
n = subprocess.run(["node", "-e", HARNESS], input=json.dumps([found.group(1), rows()]), capture_output=True, text=True,
                   timeout=60)
check(f"node runs the page's script (exit {n.returncode})", n.returncode == 0 and n.stdout.startswith("["), n.stderr[-600:])
if n.returncode != 0 or not n.stdout.startswith("["):
    finish()
lines = json.loads(n.stdout)
texts = [x["text"] for x in lines]
at = {row["name"]: row["at"] for row in rows()}
want_chat = f"{EDGAR} deployed tron-lightcycle-game at {at.get('tron-lightcycle-game')}"
check(f"the chat deploy's line reads {want_chat!r}", want_chat in texts, str(texts))
chat = next((x for x in lines if x["text"] == want_chat), {})
check("its hover text is the full image", chat.get("hover") == ["ghcr.io/someone/tron-lightcycle-game:2"], str(chat))
want_probe = f"Someone deployed redis at {at.get('probe-redis')}, removed at {removed_at}"
check(f"the probe's line reads {want_probe!r}", want_probe in texts, str(texts))
probe = next((x for x in lines if x["text"] == want_probe), {})
check("its hover text is the full image, Docker Hub's redis as written (#991 applies it unchanged)",
      probe.get("hover") == ["redis:8"], str(probe))
check("the removed line carries the class the page greys, and only it does",
      probe.get("cls") == "removed" and "li.removed,li.removed b{color:" in page
      and [x["cls"] for x in lines].count("removed") == 1, str(lines))
check("every line reads '<witch name or Someone> deployed <short name> at <HH:MM:SS>[, removed at <HH:MM:SS>]', "
      "and none 'deployed by'",
      len(lines) == 3 and all(re.fullmatch(r"(Someone|[A-Z][a-z]+ the [A-Z][a-z]+) deployed [a-z0-9._-]+ at "
                                           r"\d\d:\d\d:\d\d(, removed at \d\d:\d\d:\d\d)?", t) for t in texts), str(texts))
check("no line names a Deployment in parentheses", not any("(" in t for t in texts), str(texts))
check("both deploys from the chat request read the witch name, and only the probe's reads 'Someone'",
      sum(t.startswith(EDGAR + " deployed ") for t in texts) == 2 and sum(t.startswith("Someone ") for t in texts) == 1,
      str(texts))
desk.shutdown()
finish()
