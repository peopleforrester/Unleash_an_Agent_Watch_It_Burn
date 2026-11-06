# ABOUTME: Holds #1022 end to end: workshop-mcp's presence report reaches the real desk over HTTP, and the deployments
# ABOUTME: page's own script, run in node, reads a removed app as "<witch> deployed <app> at <time>, removed at <time>".
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: node runs the page's script)
"""The executed half of verify/test_deployments_removed.py.

1. The real support desk (ticket_site.py) serves on localhost. workshop-mcp-server.py is loaded with FastMCP stood in
   and the Kubernetes API stubbed: deploy_app lands two Deployments, credited to two witch names, and reports them to
   the desk; then the API's Deployment list loses one, as remove-untrusted-room-workloads deletes it once guardrails-on
   arms Kyverno (#990), and _report_presence posts what is left to the desk's /present.
2. The deployments page's own script, served under deployments-<cluster>, runs in node against the desk's
   /deployments.json, and each line's text and class are read off what it built.

Needs node. A missing tool is a failure, not a skip. No cluster.
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
import threading
import time
import types
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
    print("A removed app stays on the deployments page and reads 'removed at <time>'.")
    sys.exit(0)


if shutil.which("node") is None:
    print("FAILED: node not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def get_context(self):
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        def keep(f):
            return f
        return keep


site = load("ticket_site_removed_e2e", AI / "ticket_site.py")
site.Handler.log_message = lambda *a: None
desk = site.Server(("127.0.0.1", 0), site.Handler)
threading.Thread(target=desk.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{desk.server_address[1]}"

sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
os.environ["JOKER_SCALE_DOWN_SECONDS"] = "3600"
m = load("workshop_mcp_removed_e2e", AI / "workshop-mcp-server.py")
m._ns = lambda: "agent"
m.TICKET_SITE_URL = DESK
on_cluster = {"deployments": ["guard-proxy", "tron-landing", "joker-edgar-the-kelpie"], "pods": []}


def fake_req(method: str, path: str, body=None, content_type: str = "application/json"):
    if method == "GET":
        for plural, names in on_cluster.items():
            if path.endswith(f"/namespaces/agent/{plural}"):
                return 200, json.dumps({"kind": "List", "items": [{"metadata": {"name": n}} for n in names]})
        return 200, json.dumps({"resources": [{"kind": "Deployment", "name": "deployments"}]})
    return 201, "{}"


m._req = fake_req
EDGAR, TABITHA = "Edgar the Kelpie", "Tabitha the Troll"


def manifest(name: str, image: str) -> str:
    return json.dumps({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name},
                       "spec": {"selector": {"matchLabels": {"app": name}}, "template": {
                           "metadata": {"labels": {"app": name}}, "spec": {"containers": [{"name": "c", "image": image}]}}}})


print("== deploy_app lands two apps and the presence report tells the desk one is gone ==")
m.deploy_app(manifest("tron-landing", "public.ecr.aws/nginx/nginx:1.29"), requested_by=TABITHA)
m.deploy_app(manifest("joker-edgar-the-kelpie", "registry.burritobot.co/burritobot/maintenance-shell:busybox-1.38.0"),
             requested_by=EDGAR)
deadline = time.time() + 5
while time.time() < deadline and len(site.LANDINGS) < 2:
    time.sleep(0.05)
check("the desk has both rows, each with its kind", sorted((r["name"], r["kind"]) for r in site.LANDINGS)
      == [("joker-edgar-the-kelpie", "Deployment"), ("tron-landing", "Deployment")], str(site.LANDINGS))
check("a report while both are there goes through and marks nothing", m._report_presence() == ""
      and not any(r["removed"] for r in site.LANDINGS))
# Both landed a minute ago, as on stage: the sweep runs at the minute, after the room's deploys.
for r in site.LANDINGS:
    r["ts"] -= 60
on_cluster["deployments"].remove("tron-landing")
check("the report after Kyverno deleted tron-landing goes through", m._report_presence() == "")


def rows() -> list[dict]:
    with urllib.request.urlopen(DESK + "/deployments.json", timeout=5) as resp:
        return json.loads(resp.read())


by = {r["name"]: r for r in rows()}
check("/deployments.json still lists both", set(by) == {"tron-landing", "joker-edgar-the-kelpie"}, str(by))
check("tron-landing carries the time it was found gone",
      re.fullmatch(r"\d\d:\d\d:\d\d", by.get("tron-landing", {}).get("removed", "")) is not None, str(by))
check("the Joker, still on the cluster, carries none", by.get("joker-edgar-the-kelpie", {}).get("removed") == "")

print("== the deployments page's own script renders the removed line ==")
req = urllib.request.Request(DESK + "/", headers={"Host": "deployments-attackme.burritobot.co"})
with urllib.request.urlopen(req, timeout=5) as resp:
    page = resp.read().decode()
found = re.search(r"<script>(.*?)</script>", page, re.S)
check("deployments-<cluster> serves the page with its script", bool(found))
if not found:
    finish()
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
vm.runInContext(script, vm.createContext({document, fetch, setInterval: () => 0, encodeURIComponent, console}));
setTimeout(() => process.stdout.write(JSON.stringify(ul.children.map(li => ({text: li.textContent,
  cls: li.className})))), 200);
"""
n = subprocess.run(["node", "-e", HARNESS], input=json.dumps([found.group(1), rows()]), capture_output=True, text=True,
                   timeout=60)
check(f"node runs the page's script (exit {n.returncode})", n.returncode == 0 and n.stdout.startswith("["), n.stderr[-600:])
if n.returncode != 0 or not n.stdout.startswith("["):
    finish()
lines = {x["text"]: x["cls"] for x in json.loads(n.stdout)}
want_gone = f"{TABITHA} deployed nginx at {by['tron-landing']['at']}, removed at {by['tron-landing']['removed']}"
want_kept = f"{EDGAR} deployed maintenance-shell at {by['joker-edgar-the-kelpie']['at']}"
check(f"the removed app's line reads {want_gone!r}", want_gone in lines, str(list(lines)))
check("and is greyed with the removed class", lines.get(want_gone) == "removed", str(lines))
check(f"the app still there reads {want_kept!r}, with no removal", want_kept in lines and lines[want_kept] == "",
      str(lines))
desk.shutdown()
finish()
