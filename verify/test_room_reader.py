# ABOUTME: Holds #1050: workshop-mcp lists the room's workload kinds about every 30 s with its token and posts each read
# ABOUTME: to the desk; a 403, a timeout, a down API server or a body that is not a list posts a failed read, never an empty one.
"""Offline checks for #1050, the reader half of #1022.

The desk (ticket_site.py, #1049) greys a landed row as "removed at <time>" from a cluster read report it is sent, and
holds no token itself. workshop-mcp, which holds one, reads: read_room_workloads lists each kind
remove-untrusted-room-workloads deletes, and post_cluster_read posts the read to POST /cluster-read.

Everything here runs over HTTP on localhost: a stand-in API server that checks the bearer token, answers each list as
PartialObjectMetadataList, and can refuse a kind with a 403, hang past the reader's timeout, answer 200 with something
that is not a list, or split a list across pages; and the real ticket_site.py, whose /deployments.json says whether a
row was marked. No cluster, no node.
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import pathlib
import socket
import sys
import tempfile
import threading
import time
import types
import urllib.parse
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
MCP_SRC = (AI / "workshop-mcp-server.py").read_text()
SWEEP = yaml.safe_load((REPO / "policies/kyverno-breakout/remove-untrusted-room-workloads.yaml").read_text())
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# --- the real desk ---------------------------------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("ticket_site_room_reader", AI / "ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
site.Handler.log_message = lambda *a: None
desk_server = site.Server(("127.0.0.1", 0), site.Handler)
threading.Thread(target=desk_server.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{desk_server.server_address[1]}"


def desk_post(path: str, body) -> tuple[int, dict]:
    req = urllib.request.Request(DESK + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read() or b"{}")


def desk_row(name: str, kind: str) -> dict:
    with urllib.request.urlopen(DESK + "/deployments.json", timeout=5) as r:
        found = [x for x in json.loads(r.read()) if x["name"] == name and x["kind"] == kind]
    return found[0] if found else {}


def land(name: str, kind: str) -> None:
    code, body = desk_post("/landed", {"name": name, "ok": True, "detail": "", "kind": kind,
                                       "image": "ghcr.io/someone/tron-lightcycle-game:2", "requested_by": ""})
    check(f"the desk takes the landing of {kind}/{name}", code == 200, f"{code} {body}")


# --- the stand-in API server -----------------------------------------------------------------------------------------
TOKEN = "stand-in-token-1050"
PLURALS = {"deployments": "Deployment", "statefulsets": "StatefulSet", "daemonsets": "DaemonSet",
           "replicasets": "ReplicaSet", "jobs": "Job", "cronjobs": "CronJob", "pods": "Pod"}


class API:
    """What the stand-in answers: the names of each plural, and how to fail one."""
    names: dict[str, list[str]] = {}
    deny: set[str] = set()        # plurals answered 403
    hang: set[str] = set()        # plurals answered after HANG seconds
    garble: dict[str, str] = {}   # plural -> a 200 body that is not that kind's list
    page: int = 0                 # split each list into pages of this many names (0: one page)
    null_empty: bool = False      # answer an empty list as "items": null
    calls: list[dict] = []


HANG = 1.5


class StandInHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass   # the reader gave up on a hung answer

    def do_GET(self):  # noqa: N802
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        parts = url.path.strip("/").split("/")
        plural = parts[-1]
        API.calls.append({"path": url.path, "query": q, "accept": self.headers.get("Accept", ""),
                          "auth": self.headers.get("Authorization", ""), "at": time.time()})
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"kind": "Status", "code": 401, "reason": "Unauthorized"})
        if len(parts) < 5 or parts[-3] != "namespaces" or plural not in PLURALS:
            return self._send(404, {"kind": "Status", "code": 404, "reason": "NotFound"})
        ns = parts[-2]
        if plural in API.hang:
            time.sleep(HANG)
        if plural in API.deny:
            return self._send(403, {"kind": "Status", "code": 403, "reason": "Forbidden",
                                    "message": f'{plural} is forbidden: User "system:serviceaccount:agent:workshop-mcp" '
                                               f'cannot list resource "{plural}" in the namespace "{ns}"'})
        if plural in API.garble:
            raw = API.garble[plural].encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        names = API.names.get(plural, [])
        start = int((q.get("continue") or ["0"])[0])
        end = start + API.page if API.page else len(names)
        meta = {"resourceVersion": "1"} | ({"continue": str(end)} if end < len(names) else {})
        items = [{"metadata": {"name": n, "namespace": ns}} for n in names[start:end]]
        self._send(200, {"kind": "PartialObjectMetadataList", "apiVersion": "meta.k8s.io/v1", "metadata": meta,
                         "items": None if (API.null_empty and not items) else items})


api_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandInHandler)
api_server.daemon_threads = True
threading.Thread(target=api_server.serve_forever, daemon=True).start()
API_URL = f"http://127.0.0.1:{api_server.server_address[1]}"


def reset(**names: list[str]) -> None:
    API.names = {p: list(names.get(p, [])) for p in PLURALS}
    API.deny, API.hang, API.garble, API.page, API.null_empty, API.calls = set(), set(), {}, 0, False, []


# --- workshop-mcp, as its pod runs it, against the stand-ins ---------------------------------------------------------
class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_room_reader", AI / "workshop-mcp-server.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)

print("== what the reader reads, and how often ==")
SWEEP_KINDS = set()
for rule in SWEEP["spec"]["matchConstraints"]["resourceRules"]:
    for res in rule["resources"]:
        SWEEP_KINDS.add((rule["apiGroups"][0], res))
READ_KINDS = {(base.split("/")[2] if base.startswith("/apis/") else "", plural) for _k, base, plural in mcp.ROOM_READ_KINDS}
check("it reads exactly the kinds remove-untrusted-room-workloads deletes", READ_KINDS == SWEEP_KINDS,
      f"reads {sorted(READ_KINDS)}, the sweep deletes {sorted(SWEEP_KINDS)}")
check("each kind is named as deploy_app records it, the kind the desk's row holds",
      [k for k, _b, _p in mcp.ROOM_READ_KINDS] == [PLURALS[p] for _k, _b, p in mcp.ROOM_READ_KINDS])
check("a read every 30 s by default", mcp.CLUSTER_READ_SECONDS == 30.0, str(mcp.CLUSTER_READ_SECONDS))
check("each list gives up after 10 s, so an API server that hangs fails the read inside one cycle",
      mcp.CLUSTER_READ_TIMEOUT == 10.0, str(mcp.CLUSTER_READ_TIMEOUT))
check("the pod starts the reader before it serves MCP",
      MCP_SRC.index("    start_cluster_reader()\n") < MCP_SRC.index('    mcp.run(transport="streamable-http")')
      and MCP_SRC.index('if __name__ == "__main__":') < MCP_SRC.index("    start_cluster_reader()\n"))
check("the reader posts to the desk's /cluster-read on TICKET_SITE_URL",
      'f"{TICKET_SITE_URL}/cluster-read"' in MCP_SRC)

# The pod's mounted ServiceAccount, as the kubelet writes it, and the stand-in API server in place of the real one.
sa = pathlib.Path(tempfile.mkdtemp(prefix="room-reader-sa-"))
(sa / "token").write_text(TOKEN + "\n")
(sa / "namespace").write_text("agent")
mcp._SA, mcp._API, mcp._ctx = str(sa), API_URL, lambda: None   # plain HTTP here; the pod's TLS is _ctx's
mcp.TICKET_SITE_URL = DESK
mcp.CLUSTER_READ_TIMEOUT = 0.5

print("== a whole read ==")
reset(deployments=["guard-proxy", "bystander"], pods=["guard-proxy-abc12", "solo"], jobs=["otel-ordering-gate"])
before = time.time()
report = mcp.read_room_workloads()
after = time.time()
check("a read where every list answers is ok and covers every kind it reads",
      report["ok"] is True and sorted(report["kinds"]) == sorted(k for k, _b, _p in mcp.ROOM_READ_KINDS), str(report))
check("it lists the names each kind holds, and an empty kind as an empty list",
      report["kinds"]["Deployment"] == ["guard-proxy", "bystander"] and report["kinds"]["Pod"] == ["guard-proxy-abc12", "solo"]
      and report["kinds"]["Job"] == ["otel-ordering-gate"] and report["kinds"]["StatefulSet"] == [], str(report["kinds"]))
check("taken_at is the time before the first list, less the two-second clock margin",
      mcp.CLUSTER_READ_MARGIN == 2.0 and before - 2.0 <= report["taken_at"] <= before - 2.0 + (after - before)
      and report["taken_at"] <= min(c["at"] for c in API.calls) - 2.0 + 0.01, f"{report['taken_at']} vs {before}")
paths = {c["path"] for c in API.calls}
check("every list is in the pod's own namespace, agent, on the kind's own API path",
      paths == {f"{b}/namespaces/agent/{p}" for _k, b, p in mcp.ROOM_READ_KINDS}, str(sorted(paths)))
check("every list carries the pod's ServiceAccount token", all(c["auth"] == f"Bearer {TOKEN}" for c in API.calls))
check("every list asks for metadata alone (PartialObjectMetadataList), not whole objects",
      all("as=PartialObjectMetadataList" in c["accept"] for c in API.calls))
check("every list is read a page at a time", all(c["query"].get("limit") == ["500"] for c in API.calls))

reset(deployments=[f"app-{i}" for i in range(7)])
API.page = 3
report = mcp.read_room_workloads()
check("a list the API server splits into pages is read to its last page",
      report["ok"] and report["kinds"]["Deployment"] == [f"app-{i}" for i in range(7)]
      and sum(1 for c in API.calls if c["path"].endswith("/deployments")) == 3, str(report["kinds"].get("Deployment")))
reset()
API.null_empty = True
report = mcp.read_room_workloads()
check('a kind with nothing in it, answered as "items": null, is an empty list', report["ok"]
      and all(v == [] for v in report["kinds"].values()), str(report))

print("== a failed list fails the read, and the desk marks nothing on it ==")
cases = []
for plural in ("deployments", "pods"):
    cases.append((f"a 403 on {plural}", {"deny": {plural}}))
cases.append(("a list that hangs past the reader's timeout", {"hang": {"statefulsets"}}))
cases.append(("a 200 that is a Status, not a list", {"garble": {"deployments": json.dumps({"kind": "Status", "code": 200})}}))
cases.append(("a 200 that is not JSON", {"garble": {"jobs": "<html>proxy error</html>"}}))
cases.append(("a 200 list of another kind", {"garble": {"daemonsets": json.dumps({"kind": "DeploymentList", "items": []})}}))
cases.append(("a 200 list with no items", {"garble": {"cronjobs": json.dumps({"kind": "PartialObjectMetadataList"})}}))
cases.append(("a 200 list whose item has no name", {"garble": {"pods": json.dumps(
    {"kind": "PartialObjectMetadataList", "items": [{"metadata": {}}]})}}))
for i, (what, how) in enumerate(cases):
    reset()
    name = f"gone-{i}"
    land(name, "Deployment")
    land(f"{name}-pod", "Pod")
    time.sleep(0.05)
    API.deny, API.hang, API.garble = set(how.get("deny", ())), set(how.get("hang", ())), dict(how.get("garble", {}))
    mcp.CLUSTER_READ_MARGIN = 0.0   # rows landed just now, so the read must count as later than them
    report = mcp.read_room_workloads()
    check(f"{what}: the read is posted as failed and covers no kind",
          report["ok"] is False and report["kinds"] == {} and report.get("failed"), str(report))
    said = mcp.post_cluster_read(report)
    check(f"{what}: the desk takes the failed read", said.startswith("cluster read failed, posted as failed"), said)
    check(f"{what}: no row is marked removed, though no list named it",
          desk_row(name, "Deployment").get("removed_at") == "" and desk_row(f"{name}-pod", "Pod").get("removed_at") == "",
          f"{desk_row(name, 'Deployment')} {desk_row(f'{name}-pod', 'Pod')}")
    if how.get("hang"):
        check(f"{what}: the reader gave up at its timeout and listed nothing after it",
              not any(c["path"].endswith(("/daemonsets", "/pods")) for c in API.calls), str([c["path"] for c in API.calls]))
reset()
API.deny = {"deployments"}
report = mcp.read_room_workloads()
check("a 403's report names the kind, the status and the API server's message",
      report.get("failed", "").startswith("Deployment: HTTP 403: deployments is forbidden"), str(report))

reset()
land("api-down", "Deployment")
time.sleep(0.05)
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    closed = s.getsockname()[1]
mcp._API = f"http://127.0.0.1:{closed}"
report = mcp.read_room_workloads()
mcp._API = API_URL
check("an API server that does not answer: the read fails and covers no kind",
      report["ok"] is False and report["kinds"] == {} and "no answer" in report.get("failed", ""), str(report))
mcp.post_cluster_read(report)
check("and the desk marks nothing on it", desk_row("api-down", "Deployment").get("removed_at") == "")

print("== a whole read that omits a row's name marks it; one that lists it does not ==")
reset(deployments=["kept"])
land("kept", "Deployment")
land("swept", "Deployment")
land("swept-pod", "Pod")
time.sleep(0.05)
said = mcp.cluster_read_once()
check("a whole read is posted", said == "cluster reads posted to the desk", said)
check("the row of a Deployment the read omits reads removed", desk_row("swept", "Deployment").get("removed_at") != "")
check("so does a Pod's", desk_row("swept-pod", "Pod").get("removed_at") != "")
check("the row of a Deployment the read lists stays", desk_row("kept", "Deployment").get("removed_at") == "")

mcp.CLUSTER_READ_MARGIN = 2.0
land("just-landed", "Deployment")
mcp.cluster_read_once()
check("with the real margin, a row that landed under two seconds before the read is left for the next read",
      desk_row("just-landed", "Deployment").get("removed_at") == "", str(desk_row("just-landed", "Deployment")))
mcp.TICKET_SITE_URL = f"http://127.0.0.1:{closed}"
said = mcp.cluster_read_once()
mcp.TICKET_SITE_URL = DESK
check("a desk that does not answer is said in the log, and the reader goes on", "could not reach the desk" in said, said)

print("== the loop ==")
reset(deployments=["looped"])
mcp.CLUSTER_READ_SECONDS = 1.0   # the loop waits at least a second between reads, whatever it is set to
posted: list[dict] = []
real_post = mcp.post_cluster_read
mcp.post_cluster_read = lambda r: (posted.append(r), real_post(r))[1]
stop = mcp.start_cluster_reader()
time.sleep(3.4)
stop.set()
time.sleep(0.3)
n = len(posted)
time.sleep(1.2)
mcp.post_cluster_read = real_post
gaps = [b["taken_at"] - a["taken_at"] for a, b in zip(posted, posted[1:])]
check("the reader posts a whole read each interval, one interval apart",
      3 <= n <= 5 and all(r["ok"] for r in posted) and all(0.9 <= g <= 1.6 for g in gaps), f"{n} reads, gaps {gaps}")
check("and stops when told", len(posted) == n, f"{len(posted)} after {n}")
mcp.post_cluster_read = lambda r: (_ for _ in ()).throw(RuntimeError("boom"))
said = mcp.cluster_read_once()
mcp.post_cluster_read = real_post
check("a read that raises is said, not let out of the loop", said == "cluster read raised: boom", said)

desk_server.shutdown()
api_server.shutdown()
print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all room reader checks passed")
