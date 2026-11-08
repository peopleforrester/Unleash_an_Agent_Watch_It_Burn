# ABOUTME: Holds #1049: the desk keeps every landed row with its kind, and a cluster read report posted to /cluster-read
# ABOUTME: marks a row removed_at only when it succeeded, covers the kind, was taken after the row and omits the name.
"""Offline checks for #1049, the desk's half of #1022.

Since #990 the DeletingPolicy remove-untrusted-room-workloads deletes each room workload from outside
registry.burritobot.co once guardrails-on arms Kyverno, and the deployments page still listed it as deployed. The desk
(fake-ticket) holds no ServiceAccount token, so a reader that does (#1050) posts what the cluster still runs to
POST /cluster-read, and the desk marks a landed row removed from that report alone.

The real ticket_site.py runs here on localhost and every report goes through its HTTP endpoint. No cluster, no node.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
SITE_SRC = (AI / "ticket_site.py").read_text()
MCP_SRC = (AI / "workshop-mcp-server.py").read_text()
CONF = (AI / "console.conf").read_text()
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text()) if isinstance(d, dict)]
failures: list[str] = []
# The console.conf headings this test cuts the desk's and the deployments page's server blocks on.
DESK_ANCHOR = "# Challenge 6's ticket desk (2026-10-28 call, #685)"
PAGE_ANCHOR = "# Challenge 2's deployments page (#773)"
for anchor in (DESK_ANCHOR, PAGE_ANCHOR):
    if anchor not in CONF:
        print(f"FAILED: the anchor {anchor!r} is not in gitops/ai-layer/console.conf; reword this test with it")
        sys.exit(1)


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


spec = importlib.util.spec_from_file_location("ticket_site_removed_rows", AI / "ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
server = site.Server(("127.0.0.1", 0), site.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{server.server_address[1]}"
DOMAIN = "deployments-attackme.burritobot.co"


def post(path: str, body, host: str = "") -> tuple[int, dict]:
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} | ({"Host": host} if host else {})
    req = urllib.request.Request(DESK + path, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except ValueError:
            return e.code, {}


def get(path: str, host: str = "") -> tuple[int, str]:
    req = urllib.request.Request(DESK + path, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def rows() -> list[dict]:
    return json.loads(get("/deployments.json")[1])


def row(name: str) -> dict:
    found = [r for r in rows() if r["name"] == name]
    return found[0] if found else {}


def land(name: str, kind: str = "Deployment", image: str = "ghcr.io/someone/tron-lightcycle-game:2") -> dict:
    code, body = post("/landed", {"name": name, "ok": True, "detail": "", "image": image,
                                  "requested_by": "Edgar the Kelpie", "kind": kind})
    check(f"/landed takes {kind}/{name}", code == 200, f"{code} {body}")
    return body


def read(taken_at: float, ok: bool = True, **kinds) -> dict:
    code, body = post("/cluster-read", {"taken_at": taken_at, "ok": ok, "kinds": kinds})
    check(f"/cluster-read takes a report (ok={ok}, kinds={sorted(kinds)})", code == 200, f"{code} {body}")
    return body


print("== each landing row records the kind deploy_app created ==")
tron = land("tron")
check("the landed row holds the kind next to its name and ts",
      tron.get("kind") == "Deployment" and tron.get("name") == "tron" and isinstance(tron.get("ts"), float), str(tron))
check("it lands unmarked", tron.get("removed_at") == "", str(tron))
check("/deployments.json carries the kind and an empty removed_at",
      row("tron").get("kind") == "Deployment" and row("tron").get("removed_at") == "", str(row("tron")))
check("deploy_app sends the kind it created to /landed",
      '"kind": kind[:63]' in MCP_SRC and "requested_by=requested_by, kind=kind)" in MCP_SRC
      and re.search(r"def _report\([^)]*kind: str = \"\"\)", MCP_SRC) is not None)
ts = tron["ts"]
other = [land("bystander")]
names_left = ["bystander", "settings"]

print("== a report that cannot say the row's app is gone changes nothing ==")
time.sleep(0.05)
res = read(ts + 30, ok=False, Deployment=names_left)
check("a failed report, taken after the row and omitting its name, leaves the row unmarked",
      row("tron").get("removed_at") == "" and res == {"applied": False, "marked": []}, f"{res} {row('tron')}")
res = read(ts - 5, Deployment=names_left)
check("a successful report taken before the row's ts leaves it unmarked",
      row("tron").get("removed_at") == "" and res.get("marked") == [], f"{res} {row('tron')}")
res = read(ts, Deployment=names_left)
check("and so does one taken at the very ts the row landed", row("tron").get("removed_at") == "", str(res))
res = read(ts + 30, StatefulSet=[], Pod=[])
check("a successful later report that does not cover the row's kind leaves it unmarked",
      row("tron").get("removed_at") == "" and res.get("marked") == [], f"{res} {row('tron')}")
res = read(ts + 30, Deployment=["tron", *names_left])
check("a successful later covering report that lists the name leaves it unmarked",
      row("tron").get("removed_at") == "" and res.get("marked") == [], f"{res} {row('tron')}")
for bad, why in (({"taken_at": ts + 30, "kinds": {"Deployment": []}}, "no ok"),
                 ({"ok": True, "kinds": {"Deployment": []}}, "no taken_at"),
                 ({"taken_at": True, "ok": True, "kinds": {"Deployment": []}}, "a boolean taken_at"),
                 ({"taken_at": ts + 30, "ok": True, "kinds": {}}, "a successful read covering no kind"),
                 ({"taken_at": ts + 30, "ok": True, "kinds": {"Deployment": "tron"}}, "names as a string"),
                 ({"taken_at": ts + 30, "ok": True, "kinds": ["Deployment"]}, "kinds as a list"),
                 ([], "an array")):
    code, _ = post("/cluster-read", bad)
    check(f"a malformed report ({why}) is a 400 and marks nothing", code == 400 and row("tron").get("removed_at") == "",
          str(code))
code, _ = post("/cluster-read", b"not json")
check("a body that is not JSON is a 400", code == 400)

print("== a successful later covering report that omits the name marks it ==")
taken = ts + 30
res = read(taken, Deployment=names_left)
want = time.strftime("%H:%M:%S", time.localtime(taken))
check("the report marks the row and names it", res == {"applied": True, "marked": ["tron"]}, str(res))
check(f"/deployments.json carries removed_at {want!r}, the time the read was taken",
      row("tron").get("removed_at") == want, str(row("tron")))
check("the row is kept, with its name, app, witch and landed time",
      row("tron").get("app") == "tron-lightcycle-game" and row("tron").get("witch") == "Edgar the Kelpie"
      and row("tron").get("at") == tron["at"], str(row("tron")))
check("a row the report lists is not marked", row("bystander").get("removed_at") == "", str(row("bystander")))
res = read(taken + 30, Deployment=["tron", *names_left])
check("a removed row is never unmarked, not by a later read that lists its name again",
      row("tron").get("removed_at") == want, str(row("tron")))
res = read(taken + 60, Deployment=names_left)
check("and a second omitting read does not move its removed_at", row("tron").get("removed_at") == want and
      res.get("marked") == [], f"{res} {row('tron')}")

print("== a removed row that lands again under the same name is a new row ==")
again = land("tron")
both = [r for r in rows() if r["name"] == "tron"]
check("both rows are on the page: the new one unmarked first, the removed one kept",
      [r["removed_at"] for r in both] == ["", want], str(both))
read(again["ts"] - 1, Deployment=names_left)
check("a read taken before the new row landed leaves the new row unmarked",
      [r["removed_at"] for r in rows() if r["name"] == "tron"] == ["", want])
read(again["ts"] + 30, Deployment=["tron", *names_left])
check("a later read that lists the name leaves the new row unmarked and the old one removed",
      [r["removed_at"] for r in rows() if r["name"] == "tron"] == ["", want])

print("== rows no report can speak for ==")
site.record_landing("pre-1049", True, "", image="redis")
read(time.time() + 30, Deployment=names_left, StatefulSet=[], Pod=[], ReplicaSet=[], CronJob=[], Job=[])
check("a row with no kind (a report from before #1049) is covered by no read and never marked",
      row("pre-1049").get("removed_at") == "" and row("pre-1049").get("kind") == "", str(row("pre-1049")))
land("cache", kind="StatefulSet", image="redis:8")
read(time.time() + 30, Deployment=[])
check("a Deployment read does not mark a StatefulSet of a name it does not list", row("cache").get("removed_at") == "")
read(time.time() + 30, StatefulSet=[])
check("a StatefulSet read does", row("cache").get("removed_at") != "", str(row("cache")))
long_name = "x" * 80
land(long_name)
read(time.time() + 30, Deployment=[long_name, *names_left])
check("a name past 63 characters is compared as the row keeps it, so a listed one stays unmarked",
      row(long_name[:63]).get("removed_at") == "", str(row(long_name[:63])))
post("/landed", {"name": "refused", "ok": False, "detail": "HTTP 403: forbidden", "kind": "Deployment"})
read(time.time() + 30, Deployment=names_left)
refused = next(r for r in site.LANDINGS if r["name"] == "refused")
check("a refusal, which never ran, is never marked removed", refused["removed_at"] == "", str(refused))
check("no landed row is dropped: every row posted is still in LANDINGS",
      {"tron", "bystander", "pre-1049", "cache", long_name[:63], "refused"} <= {r["name"] for r in site.LANDINGS}
      and sum(r["name"] == "tron" for r in site.LANDINGS) == 2)
big = {"taken_at": time.time() + 30, "ok": True, "kinds": {"Deployment": names_left + [f"w{i:05d}" for i in range(4000)]}}
code, _ = post("/cluster-read", big)
check("a read listing thousands of names (past a ticket's size limit) is taken", code == 200,
      f"{code}, {len(json.dumps(big))} bytes")

print("== the page renders such a row as '..., removed at <time>' greyed ==")
code, page = get("/", host=DOMAIN)
script = page[page.find("<script>"):page.find("</script>")]
check("deployments-<cluster> serves the page", code == 200 and "Everything BurritoBot deployed" in page, str(code))
check("a row with removed_at reads ', removed at <time>' after its landed time",
      "createTextNode(' at '+x.at)" in script
      and "if(x.removed_at){li.className='removed';li.appendChild(document.createTextNode(', removed at '+x.removed_at));}"
      in script, script)
check("the page's style greys a removed line and its witch name", "li.removed,li.removed b{color:#9b93a8}" in page)
check("the page still names no Joker and no landing", "joker" not in page.lower() and "landed" not in page.lower())
mine = site.me_page("Edgar the Kelpie")
check("the visitor's own desk page says when a deploy was removed", f"removed at {want}" in mine, mine[:400])

print("== the report is in-cluster only ==")
land("outside-target")
code, _ = post("/cluster-read", {"taken_at": time.time() + 30, "ok": True, "kinds": {"Deployment": []}}, host=DOMAIN)
check("a POST /cluster-read under the deployments host is a 404", code == 404, str(code))
check("and marks nothing", row("outside-target").get("removed_at") == "", str(row("outside-target")))
desk_block = CONF[CONF.find(DESK_ANCHOR):]
desk_block = desk_block[:desk_block.find(PAGE_ANCHOR)]
check("the console refuses /cluster-read from outside on the support desk's server, as it does /landed",
      re.search(r"location = /cluster-read \{\s*deny all;", desk_block) is not None
      and re.search(r"location = /landed \{\s*deny all;", desk_block) is not None, desk_block[-800:])
check("the deployments server passes no /cluster-read (only /, /mine and /deployments.json, GET only)",
      r"location ~ ^/(|mine|deployments\.json)$ {" in CONF and "cluster-read" not in
      CONF[CONF.find(PAGE_ANCHOR):][:3000])

print("== the desk still holds no token and calls no cluster API ==")
dep = [d for d in RES if d.get("kind") == "Deployment" and d["metadata"]["name"] == "fake-ticket"]
pod = dep[0]["spec"]["template"]["spec"] if len(dep) == 1 else {}
check("the fake-ticket Deployment keeps automountServiceAccountToken: false", pod.get("automountServiceAccountToken") is False)
check("and mounts no projected ServiceAccount token",
      "serviceAccountToken" not in json.dumps(pod.get("volumes") or []), str(pod.get("volumes")))
imported: set[str] = set()
for node in ast.walk(ast.parse(SITE_SRC)):
    if isinstance(node, ast.Import):
        imported |= {a.name for a in node.names}
    elif isinstance(node, ast.ImportFrom):
        imported |= {f"{node.module}.{a.name}" for a in node.names} | {node.module or ""}
dynamic = re.findall(r"__import__\(\s*['\"]([\w.]+)['\"]", SITE_SRC)
imported |= set(dynamic)
CLIENTS = ("urllib.request", "http.client", "socket", "ssl", "subprocess", "requests", "httpx", "aiohttp", "kubernetes",
           "urllib3", "asyncio")
check("ticket_site.py imports no client it could reach the API server with",
      not any(i == c or i.startswith(c + ".") for i in imported for c in CLIENTS), str(sorted(imported)))
check("and imports only the standard modules it needs to serve", {i.split(".")[0] for i in imported} <=
      {"__future__", "hashlib", "html", "json", "logging", "os", "re", "secrets", "threading", "time", "urllib", "http"},
      str(sorted(imported)))
check("it names no API server, API path or token file",
      not re.search(r"KUBERNETES_SERVICE|kubernetes\.default|/api/v1|/apis/|serviceaccount/token|urlopen|"
                    r"Authorization", SITE_SRC), "")

server.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("Every landed row is kept with its kind; only a successful, later, covering read that omits it marks it removed.")
