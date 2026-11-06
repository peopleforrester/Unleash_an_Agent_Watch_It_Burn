# ABOUTME: Holds #1022: the deployments page keeps every landed row and marks one removed once the cluster has taken the
# ABOUTME: app off, from workshop-mcp's presence report of the namespace's Deployments and Pods, read with its own token.
"""Why this exists (#1022).

Since #990, once guardrails-on arms Kyverno, remove-untrusted-room-workloads deletes within a minute every room
workload from outside registry.burritobot.co. The deployments page listed rows from the desk's own record of what
landed, so an app Kyverno had removed still read as deployed on the projector and on phones. The page now keeps each
row, as the record of the room's asks, and marks it "removed at <time>" once the app is gone from the cluster.

What tells the desk: workshop-mcp lists the namespace's Deployments and bare Pods every 15 seconds with the token it
already holds and posts the names to the desk's /present. This test holds, offline:

1. the desk marks a landed row removed only when its kind is listed and its name is not, and never a refused row, a
   row that landed after the report's lists were read, a row of a kind the report does not list, or a row already
   marked;
2. /present takes that report over HTTP, refuses a malformed one, takes one larger than a ticket, and is not served on
   the deployments host or from outside (console.conf);
3. deploy_app reports each landing's kind, and workshop-mcp's presence report lists both kinds through the API and
   posts them, posts nothing when a list fails, and leaves out Pods a controller owns;
4. every Role workshop-mcp may run under (the shipped one and the c5, c6 and c8 Roles the switch and the challenges
   apply) keeps list on Deployments and Pods, so the report works with the guardrails on, and the desk holds no token;
5. the pod starts the report beside the MCP server, and the run-of-show says what the page does.

The page's own script rendering a removed line is executed in node by verify/test_deployments_removed_e2e.py.
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
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

    def tool(self, *a, **kw):
        def keep(f):
            f.description = kw.get("description", "")
            return f
        return keep


site = load("ticket_site_removed", AI / "ticket_site.py")
site.Handler.log_message = lambda *a: None
OLD = 60.0  # a row that landed a minute ago, well before any report below was read


def landed(name: str, kind: str = "Deployment", ok: bool = True, age: float = OLD) -> dict:
    row = site.record_landing(name, ok, "" if ok else "HTTP 403: forbidden", image="public.ecr.aws/nginx/nginx:1",
                              kind=kind)
    row["ts"] = time.time() - age
    return row


print("== the desk marks a landed row removed once its name is gone from its kind's list ==")
site.LANDINGS.clear()
gone = landed("tron-landing")
kept = landed("joker-edgar-the-kelpie")
bare = landed("bare-pod", kind="Pod")
young = landed("just-landed", age=20)
refused = landed("refused-one", ok=False)
config = landed("a-configmap", kind="ConfigMap")
kindless = landed("no-kind", kind="")
check("a new row is not removed", all(not r["removed"] for r in site.LANDINGS))
# This report's lists were read 12 seconds ago: just-landed, 20 seconds old, landed only 8 seconds before that read.
marked = site.mark_present({"Deployment": ["joker-edgar-the-kelpie", "guard-proxy"], "Pod": []}, 12)
check("the report marks exactly the gone Deployment and the gone bare Pod", marked == 2, str(marked))
check("the gone Deployment is removed, with a time", re.fullmatch(r"\d\d:\d\d:\d\d", gone["removed"]) is not None,
      str(gone))
check("the bare Pod gone from the Pod list is removed", bool(bare["removed"]))
check("a Deployment still listed is not", kept["removed"] == "")
check("a row that landed within the grace before the lists were read is not, though they lack it", young["removed"] == "")
check("a refused row is not: it never landed", refused["removed"] == "")
check("a row of a kind the report does not list is not", config["removed"] == "" and kindless["removed"] == "")
first = gone["removed"]
check("a report whose lists were read before the young row landed does not mark it",
      site.mark_present({"Deployment": ["joker-edgar-the-kelpie"], "Pod": []}, 25) == 0 and young["removed"] == "")
check("a report read just now marks it", site.mark_present({"Deployment": ["joker-edgar-the-kelpie"], "Pod": []}, 0) == 1
      and bool(young["removed"]))
check("a report without the kept Deployment marks it, and only it",
      site.mark_present({"Deployment": [], "Pod": []}, 0) == 1 and bool(kept["removed"]))
check("a removed row keeps its first removal time", gone["removed"] == first)
site.mark_present({"Deployment": ["tron-landing"], "Pod": ["bare-pod"]}, 0)
check("and stays removed when the name comes back: a new deploy is its own row", gone["removed"] == first)
again = landed("tron-landing")
site.mark_present({"Deployment": ["tron-landing"], "Pod": []}, 0)
check("the new row of that name, listed, is not removed", again["removed"] == "")
rows = {(r["name"], r["removed"] != "") for r in site.deployments()}
check("deployments() carries the removed time and keeps every landed row",
      ("tron-landing", True) in rows and ("tron-landing", False) in rows and ("a-configmap", False) in rows
      and not any(n == "refused-one" for n, _ in rows), str(rows))
check("each row of deployments() has a removed field", all("removed" in r for r in site.deployments()))
check("a report with a non-list value for a kind marks nothing of that kind",
      site.mark_present({"Deployment": "tron-landing"}, 0) == 0)

print("== /present takes the report over HTTP ==")
desk = site.Server(("127.0.0.1", 0), site.Handler)
threading.Thread(target=desk.serve_forever, daemon=True).start()
DESK = f"http://127.0.0.1:{desk.server_address[1]}"


def post(path: str, body: bytes, host: str = "") -> tuple[int, str]:
    req = urllib.request.Request(DESK + path, data=body, method="POST", headers={"Content-Type": "application/json"})
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


site.LANDINGS.clear()
h1 = landed("http-gone")
code, body = post("/present", json.dumps({"present": {"Deployment": [], "Pod": []}, "listed_seconds_ago": 0.4}).encode())
check("a report is accepted and says how many rows it marked", code == 200 and json.loads(body) == {"marked": 1}, body)
check("and the row is marked", bool(h1["removed"]))
for bad in (b"{}", b'{"present": ["a"], "listed_seconds_ago": 0}', b'{"present": {}}',
            b'{"present": {}, "listed_seconds_ago": "1"}', b'{"present": {}, "listed_seconds_ago": true}', b"not json"):
    code, _ = post("/present", bad)
    check(f"a malformed report ({bad.decode()}) is refused with 400", code == 400, str(code))
big = json.dumps({"present": {"Deployment": [f"joker-{i:04d}-" + "x" * 50 for i in range(2000)], "Pod": []},
                  "listed_seconds_ago": 1}).encode()
check("the big report is past a ticket's limit", len(big) > site.MAX_BODY * 3, str(len(big)))
code, _ = post("/present", big)
check("a report naming 2,000 Deployments is still accepted", code == 200, str(code))
code, _ = post("/submit", b"body=" + b"x" * (site.MAX_BODY * 3 + 10))
check("a ticket past its limit is still refused: only /present takes more", code == 413, str(code))
code, _ = post("/present", json.dumps({"present": {"Deployment": []}, "listed_seconds_ago": 0}).encode(),
               host="deployments-attackme.burritobot.co")
check("the deployments host takes no report", code == 404, str(code))

CONF = (AI / "console.conf").read_text()
support = re.search(r"server \{[^{}]*server_name ~\^support[^;]*;.*?\n\}\n", CONF, re.S)
check("console.conf refuses /present on the desk's public host",
      bool(support) and re.search(r"location = /present \{\s*deny all;", support.group(0)) is not None)
deploys = re.search(r"server \{[^{}]*server_name ~\^deployments[^;]*;.*?\n\}\n", CONF, re.S)
check("and the deployments host passes only GET on its three paths",
      bool(deploys) and "location ~ ^/(|mine|deployments\\.json)$" in deploys.group(0)
      and "limit_except GET { deny all; }" in deploys.group(0))

print("== workshop-mcp reports each landing's kind and what is still on the cluster ==")
sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
os.environ["JOKER_SCALE_DOWN_SECONDS"] = "3600"
m = load("workshop_mcp_removed", AI / "workshop-mcp-server.py")
os.environ.pop("JOKER_SCALE_DOWN_SECONDS", None)
m._ns = lambda: "agent"
m.TICKET_SITE_URL = DESK
api = {"lists": {"deployments": [], "pods": []}, "fail": "", "gets": []}


def item(name: str, owned: bool = False) -> dict:
    meta = {"name": name, "namespace": "agent"}
    if owned:
        meta["ownerReferences"] = [{"kind": "ReplicaSet", "name": name.rsplit("-", 1)[0]}]
    return {"metadata": meta}


def fake_req(method: str, path: str, body=None, content_type: str = "application/json"):
    if method == "GET":
        api["gets"].append(path)
        for plural, items in api["lists"].items():
            if path == f"/{'apis/apps/v1' if plural == 'deployments' else 'api/v1'}/namespaces/agent/{plural}":
                if api["fail"] == plural:
                    return 403, json.dumps({"kind": "Status", "message": f"{plural} is forbidden"})
                return 200, json.dumps({"kind": "List", "items": [item(*i) for i in items]})
        return 200, json.dumps({"resources": [{"kind": "Deployment", "name": "deployments"},
                                              {"kind": "Pod", "name": "pods"}]})
    return 201, "{}"


m._req = fake_req
site.LANDINGS.clear()


def wait_rows(n: int) -> None:
    deadline = time.time() + 5
    while time.time() < deadline and len(site.LANDINGS) < n:
        time.sleep(0.05)


manifest = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "tron-landing"},
            "spec": {"selector": {"matchLabels": {"app": "tron"}}, "template": {
                "metadata": {"labels": {"app": "tron"}}, "spec": {"containers": [{"name": "web",
                                                                                    "image": "public.ecr.aws/nginx/nginx:1"}]}}}}
reply = m.deploy_app(json.dumps(manifest))
pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "bare-tron"},
       "spec": {"containers": [{"name": "web", "image": "public.ecr.aws/nginx/nginx:1"}]}}
m.deploy_app(json.dumps(pod))
wait_rows(2)
kinds = {r["name"]: r.get("kind") for r in site.LANDINGS}
check("deploy_app lands the Deployment", reply.startswith("deployed Deployment/tron-landing"), reply)
check("its report to the desk names the kind of each", kinds == {"tron-landing": "Deployment", "bare-tron": "Pod"},
      str(kinds))
for r in site.LANDINGS:
    r["ts"] -= OLD

api["lists"] = {"deployments": [("tron-landing",), ("guard-proxy",)],
                "pods": [("bare-tron",), ("guard-proxy-6f7d9-abcde", True)]}
present, why = m._present_names()
check("the presence report lists both kinds in the namespace through the API",
      {"/apis/apps/v1/namespaces/agent/deployments", "/api/v1/namespaces/agent/pods"} <= set(api["gets"]), str(api["gets"]))
check("it names every Deployment and only the Pods no controller owns",
      present == {"Deployment": ["guard-proxy", "tron-landing"], "Pod": ["bare-tron"]}, f"{present} {why}")
check("with both still there, a report marks nothing", m._report_presence() == ""
      and not any(r["removed"] for r in site.LANDINGS))

api["lists"]["deployments"] = [("guard-proxy",)]
api["fail"] = "pods"
why = m._report_presence()
check("a failed list says what failed", "pods" in why and "403" in why, why)
check("and posts nothing: the desk marks no row on a list it did not get",
      not any(r["removed"] for r in site.LANDINGS))
api["fail"] = ""
check("once the list works, the report goes through", m._report_presence() == "")
by = {r["name"]: r["removed"] for r in site.LANDINGS}
check("the Deployment Kyverno deleted is marked removed, the bare Pod still there is not",
      bool(by.get("tron-landing")) and by.get("bare-tron") == "", str(by))
m.TICKET_SITE_URL = "http://127.0.0.1:9"
check("a desk that does not answer is reported, not raised", "support desk" in m._report_presence())
m.TICKET_SITE_URL = DESK

SRV = (AI / "workshop-mcp-server.py").read_text()
main = SRV[SRV.index('if __name__ == "__main__":'):]
check("the pod starts the presence report on a thread before it serves MCP",
      re.search(r"threading\.Thread\(target=_report_presence_forever[^)]*daemon=True\)\.start\(\)", main) is not None
      and main.index("_report_presence_forever") < main.index("mcp.run("))
check("the report runs every 15 seconds unless told otherwise", m.PRESENCE_SECONDS == 15.0)
check("its post's timeout fits inside the desk's grace, which covers that trip",
      re.search(r'/present".*?urlopen\(req, timeout=(\d+)\)', SRV, re.S) is not None
      and int(re.search(r'/present".*?urlopen\(req, timeout=(\d+)\)', SRV, re.S).group(1)) < site.REMOVED_GRACE_SECONDS)

print("== the token that reads the lists is workshop-mcp's, under every Role it may run as ==")
docs = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text()) if d]
fixes = next(d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "challenge-fixes")["data"]
roles = {"shipped": next(d for d in docs if d.get("kind") == "Role" and d["metadata"]["name"] == "workshop-agent")}
for f in ("c5-scoped-role.yaml", "c6-least-privilege-role.yaml", "c8-broad-role.yaml", "c8-scoped-role.yaml"):
    roles[f] = yaml.safe_load(fixes[f])


def can_list(role: dict, group: str, resource: str) -> bool:
    return any(group in r.get("apiGroups", []) and resource in r.get("resources", []) and "list" in r.get("verbs", [])
               and not r.get("resourceNames") for r in role.get("rules", []))


for label, role in roles.items():
    check(f"the {label} workshop-agent Role keeps list on Deployments and Pods",
          can_list(role, "apps", "deployments") and can_list(role, "", "pods"))
binding = next(d for d in docs if d.get("kind") == "RoleBinding" and d["metadata"]["name"] == "workshop-agent")
check("workshop-mcp is bound to it", {"kind": "ServiceAccount", "name": "workshop-mcp"} in binding["subjects"])
ticket = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "fake-ticket")
check("the desk still holds no token", ticket["spec"]["template"]["spec"].get("automountServiceAccountToken") is False)
check("and makes no outbound call", "urlopen" not in (AI / "ticket_site.py").read_text())

print("== the page says it, and so does the run-of-show ==")
page = site.deployments_page()
check("the page's lead says a removed app stays on the list, marked removed",
      "An app the cluster has since taken off stays on the list, marked removed." in page)
check("its script writes ', removed at <time>' and greys the line",
      "', removed at '+x.removed" in page and "li.className='removed'" in page and ".removed{" in page)
ros = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text()
check("the run-of-show says the page marks a removed app, and no longer that it lists only what landed",
      "marks each app the sweep took off" in ros and "still lists what landed" not in ros)
desk.shutdown()

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The deployments page keeps every landed row and marks one removed once the cluster has taken the app off.")
