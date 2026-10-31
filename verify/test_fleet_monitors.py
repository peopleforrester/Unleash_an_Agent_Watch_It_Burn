# ABOUTME: Offline tests for the instructor-org fleet monitors and dashboard (#267): the definitions name
# ABOUTME: real deployments and metrics, and the loader validates everything before it writes anything.
"""Nothing here reaches Datadog or AWS. The org is a fake that records every call.

Two halves. The first holds the definitions to the platform they watch: every Deployment a monitor names
exists in the ai-layer bundle, every metric a monitor reads is one this repo actually produces, and every
query is per-cluster. A monitor on a name that does not exist is the quietest failure there is: it never
fires, and its silence reads as health. The second drives fleet_monitors.py through a fake org and asserts
the pool-loader contract: one rejected monitor means no writes at all, re-applies update in place, and the
session monitors stay muted outside the declared window.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import pathlib
import re
import sys
from contextlib import redirect_stdout, redirect_stderr

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
import fleet_monitors as fm  # noqa: E402
sys.path.insert(0, str(REPO / "verify"))
from collector_render import collector_config  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


defs = fm.load_monitors()
dash = fm.load_dashboard()
mons = {m["key"]: m for m in defs["monitors"]}
FILTER = defs["cluster_filter"]

print("== the definitions are well-formed ==")
check("monitors.yaml validates clean", fm.validate_monitors(defs) == [])
check("dashboard.yaml validates clean", fm.validate_dashboard(dash, FILTER) == [])
check("the cluster filter is the fleet's own name prefix",
      FILTER == "kube_cluster_name:burritobot-*")
fleet_src = (REPO / "infra/terraform/fleet/fleet.sh").read_text()
check("fleet.sh names every cluster watch-it-burn-<something>",
      re.search(r'NAME_PREFIX="?\$\{NAME_PREFIX:-watch-it-burn-|NAME_PREFIX="watch-it-burn-', fleet_src) is not None)

print("== every signal the issue asks for is a monitor ==")
check("six monitors", len(mons) == 6)
cs = mons.get("cluster-silent", {})
check("cluster stopped reporting: datadog.agent.running by kube_cluster_name",
      "datadog.agent.running" in cs.get("query", "") and "by {kube_cluster_name}" in cs.get("query", ""))
check("cluster stopped reporting: absence alerts after 5 minutes",
      cs.get("options", {}).get("notify_no_data") is True and cs["options"].get("no_data_timeframe") == 5)
check("console Deployment unavailable", "kube_deployment:console" in mons.get("console-unavailable", {}).get("query", ""))
check("BurritoBot agent pod not ready", "kube_deployment:workshop-agent" in mons.get("burritobot-not-ready", {}).get("query", ""))
gp = mons.get("guard-proxy-erroring", {})
check("guard-proxy erroring: a log monitor on its error-status logs",
      gp.get("type") == "log alert" and "kube_deployment:guard-proxy" in gp["query"] and "status:error" in gp["query"])
check("node NotReady", "kubernetes_state.node.by_condition" in mons.get("node-not-ready", {}).get("query", "")
      and "condition:ready" in mons["node-not-ready"]["query"])
nt = mons.get("no-traces", {})
check("no traces for 10 minutes, during the session window only",
      "last_10m" in nt.get("query", "") and nt.get("session") is True
      and nt["options"].get("notify_no_data") is True and nt["options"].get("no_data_timeframe") == 10)
# The direction is what makes a liveness monitor a liveness monitor: "> 1" on a heartbeat is valid syntax
# that fires on a healthy cluster and never on a dead one.
for k in ("cluster-silent", "console-unavailable", "burritobot-not-ready", "no-traces"):
    check(f"{k} fires when the signal drops below 1", mons.get(k, {}).get("query", "").rstrip().endswith("< 1"))
for k in ("node-not-ready", "guard-proxy-erroring"):
    check(f"{k} fires when its bad-news count rises", re.search(r">\s*[0-9]+$", mons.get(k, {}).get("query", "").rstrip()) is not None)
check("only the traces monitor is session-scoped", [k for k, m in mons.items() if m.get("session")] == ["no-traces"])

print("== the names they watch exist in the platform ==")
docs = [d for p in ("gitops/ai-layer/resources.yaml", "gitops/workshop-agent/agent.yaml")  # the Agent's bundle (#707)
        for d in yaml.safe_load_all((REPO / p).read_text()) if d]
deployments = {d["metadata"]["name"] for d in docs if d.get("kind") == "Deployment"}
agents = {d["metadata"]["name"] for d in docs if d.get("kind") == "Agent"}
kust = yaml.safe_load((REPO / "gitops/ai-layer/kustomization.yaml").read_text())
check("the ai-layer bundle lands in namespace agent", kust.get("namespace") == "agent")
watched = set()
for m in defs["monitors"] + [{"query": q["query"]} for w in dash["widgets"]
                              for r in w["definition"].get("requests", []) for q in r.get("queries", [])]:
    watched |= set(re.findall(r"kube_deployment:([a-z0-9-]+)", m["query"]))
    if "kube_namespace:" in m["query"]:
        check(f"namespace in '{m['query'][:60]}...' is agent", "kube_namespace:agent" in m["query"])
check(f"every watched Deployment exists ({sorted(watched)})", watched <= deployments | agents)
check("workshop-agent is the kagent Agent (kagent runs it as a Deployment of that name)", "workshop-agent" in agents)

print("== the metrics they read are ones this repo produces ==")
agent_cr = (REPO / "gitops/manifests/datadog/datadog-agent.yaml").read_text()
check("the node Agent reports its real cluster name (DD_CLUSTER_NAME from cluster-identity)",
      "DD_CLUSTER_NAME" in agent_cr and "cluster-identity" in agent_cr)
check("kube-state-metrics core is not switched off", "kubeStateMetricsCore" not in agent_cr
      or "enabled: false" not in agent_cr.split("kubeStateMetricsCore", 1)[1][:80])
col = yaml.safe_load((REPO / "gitops/otel-collector/values.yaml").read_text())["config"]
mp = col["service"]["pipelines"]["metrics"]
check("span_metrics feeds the metrics pipeline (traces.span.metrics.calls)",
      "span_metrics" in col["connectors"] and "span_metrics" in mp["receivers"]
      and "span_metrics" in col["service"]["pipelines"]["traces"]["exporters"]
      and "namespace" not in (col["connectors"]["span_metrics"] or {}))
res = {a["key"]: a for a in col["processors"]["resource"]["attributes"]}
check("the metrics pipeline stamps k8s.cluster.name (-> kube_cluster_name)",
      "resource" in mp["processors"] and "k8s.cluster.name" in res)
# The Datadog exporters are in the overlay the datadog-gate loads once datadog-secret exists (#500).
dual = collector_config("attendee", datadog_secret=True)
check("dual-shipped clusters send those metrics to the instructor org too",
      "datadog/admin" in dual["service"]["pipelines"]["metrics"]["exporters"])
proxy = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text()
check("guard-proxy exports gen_ai.client.cost (the spend column)", '"gen_ai.client.cost"' in proxy)
check("guard-proxy logs JSON with a level (Datadog maps it to status)", '"level": record.levelname' in proxy)
check("guard-proxy logs a forward failure at ERROR", 'log.error("agent forward failed' in proxy)

print("== the dashboard is the per-cluster screen ==")
types = [w["definition"]["type"] for w in dash["widgets"]]
tables = [w["definition"] for w in dash["widgets"] if w["definition"]["type"] == "query_table"]
check("one per-cluster table", len(tables) == 1)
t = tables[0] if tables else {"requests": [{"queries": [], "formulas": []}]}
aliases = [f.get("alias") for f in t["requests"][0]["formulas"]]
check(f"columns: agent up, console up, traces, spend ({aliases})",
      {"agent up", "console up", "spans (5 min)", "spend so far (USD)"} <= set(aliases))
check("every table query is one row per kube_cluster_name",
      all(q["query"].count("by {kube_cluster_name}") == 1 for q in t["requests"][0]["queries"]))
check("the table answers 'now': a fixed 5-minute window", t.get("time", {}).get("live_span") == "5m")
check("a dead cluster sorts first", t["requests"][0]["sort"]["order_by"][0] == {"type": "formula", "index": 0, "order": "asc"})
check("the fleet alerts are on the same screen", "manage_status" in types)
ms = next(w["definition"] for w in dash["widgets"] if w["definition"]["type"] == "manage_status")
check("the alert widget lists exactly the managed monitors", fm.MANAGED_TAG in ms["query"])

print("== validation catches the mistakes that would make a monitor silent ==")
def broken(**over):
    d = json.loads(json.dumps(defs))
    d["monitors"][1].update(over)
    return fm.validate_monitors(d)
check("an unfiltered query", any("not filtered" in p for p in broken(query="max(last_5m):max:x{*} by {kube_cluster_name} < 1")))
check("an ungrouped query", any("not grouped" in p for p in broken(query="max(last_5m):max:x{kube_cluster_name:burritobot-*} < 1")))
check("a threshold that disagrees with the query", any("!=" in p for p in broken(options={"thresholds": {"critical": 3}})))
check("a message that does not name the cluster", any("name the cluster" in p for p in broken(message="down")))
check("a duplicate key", any("duplicate" in p for p in broken(key="cluster-silent")))
bad_dash = json.loads(json.dumps(dash))
bad_dash["widgets"][-1]["definition"]["requests"][0]["formulas"] = [{"formula": "nope"}]
check("a dashboard formula naming no query", fm.validate_dashboard(bad_dash, FILTER) != [])

print("== rendering ==")
r = fm.render_monitor(mons["no-traces"], ["@oncall@example.test"])
check("managed tag, key tag and session tag", {fm.MANAGED_TAG, "wib-monitor:no-traces", fm.SESSION_TAG} <= set(r["tags"]))
check("a non-session monitor has no session tag", fm.SESSION_TAG not in fm.render_monitor(mons["cluster-silent"], [])["tags"])
check("notify handles are appended to the message", r["message"].rstrip().endswith("@oncall@example.test"))
check("the message points at the outside check for that cluster", "fleet.sh verify {{kube_cluster_name.name}}" in r["message"])
check("no repo-only fields leak into the API body", not {"key", "session"} & set(r) and r["priority"] == 3)

print("== planning ==")
rendered = {k: fm.render_monitor(m, []) for k, m in mons.items()}
existing = [{"id": 11, "tags": [fm.MANAGED_TAG, "wib-monitor:cluster-silent"]},
            {"id": 12, "tags": [fm.MANAGED_TAG, "wib-monitor:cluster-silent"]},
            {"id": 13, "tags": [fm.MANAGED_TAG, "wib-monitor:retired-one"]},
            {"id": 14, "tags": [fm.MANAGED_TAG]}]
pl = {(a, k, i) for a, k, i, _ in fm.plan_monitors(rendered, existing)}
check("an existing key is updated in place", ("update", "cluster-silent", 11) in pl)
check("a duplicate of a key is deleted", ("delete", "cluster-silent", 12) in pl)
check("a key that left the file is deleted", ("delete", "retired-one", 13) in pl)
check("a monitor without a key tag is never touched", not any(i == 14 for _, _, i in pl))
check("a new key is created", ("create", "console-unavailable", None) in pl)

print("== the session window ==")
S = fm.parse_session("2026-09-08T16:00Z/2026-09-08T19:30Z")
start, end = S
check("before the session: muted until start and again from end",
      fm.mute_windows(S, start - dt.timedelta(hours=2)) == [(None, start), (end, None)])
check("during the session: muted only from end", fm.mute_windows(S, start + dt.timedelta(minutes=5)) == [(end, None)])
check("after the session: muted indefinitely", fm.mute_windows(S, end + dt.timedelta(minutes=1)) == [(None, None)])
check("no window declared: muted indefinitely", fm.mute_windows(None, start) == [(None, None)])
dt_body = fm.render_downtime((end, None), S)["data"]["attributes"]
check("a downtime targets the session monitors by tag, every group",
      dt_body["monitor_identifier"] == {"monitor_tags": [fm.MANAGED_TAG, fm.SESSION_TAG]} and dt_body["scope"] == "*")
check("an open-ended downtime has a UTC start and no end",
      dt_body["schedule"] == {"start": "2026-09-08T19:30:00+00:00"})
check("an immediate, endless downtime has no schedule", "schedule" not in fm.render_downtime((None, None), None)["data"]["attributes"])
for bad in ("2026-09-08T16:00/2026-09-08T19:30", "2026-09-08T19:30Z/2026-09-08T16:00Z", "tomorrow"):
    try:
        fm.parse_session(bad)
        check(f"--session '{bad}' is refused", False)
    except ValueError:
        check(f"--session '{bad}' is refused", True)


class FakeOrg:
    """A Datadog org in memory. Records every call; rejects validation for the queries in `reject`."""

    def __init__(self, monitors=(), dashboards=(), downtimes=(), reject=(), org="Datadog Whitney Sandbox",
                 data=None, groups=None):
        self.calls, self.reject, self.org = [], set(reject), org
        self.monitors = {m["id"]: m for m in monitors}
        self.dashboards, self.downtimes, self.next_id = list(dashboards), list(downtimes), 100
        # data: query text -> {cluster: value}, or {"": value} for an ungrouped answer; what /api/v2/query/scalar
        # answers. groups: monitor key -> {cluster: status}; what group_states=all adds to each monitor.
        self.data, self.groups, self.scalars, self.urls = dict(data or {}), dict(groups or {}), [], []

    def __call__(self, method, url, headers, body):
        path = url.split("datadoghq.com", 1)[1]
        data = json.loads(body) if body else None
        self.calls.append((method, path.split("?")[0], headers))
        self.urls.append(path)
        p = path.split("?")[0]
        if p == "/api/v1/org":
            # What the sandbox org's read-only key gets here (#629): the loader must name the org another way.
            return 403, {"errors": ["Forbidden"]}
        if p == "/api/v2/current_user":
            return 200, {"included": [{"type": "orgs", "attributes": {"name": self.org}}]}
        if p == "/api/v1/monitor/validate":
            return (400, {"errors": ["bad query"]}) if data["query"] in self.reject else (200, {})
        if p == "/api/v1/monitor" and method == "GET":
            if "group_states=all" not in path:
                return 200, list(self.monitors.values())
            return 200, [{**m, "state": {"groups": {
                f"kube_cluster_name:{c}": {"name": f"kube_cluster_name:{c}", "status": st}
                for c, st in self.groups.get(fm.key_of(m), {}).items()}}} for m in self.monitors.values()]
        if p == "/api/v2/query/scalar":
            a = data["data"]["attributes"]
            text = fm.query_text(a["queries"][0])
            self.scalars.append((text, a["to"] - a["from"], a["queries"][0]))
            vals = self.data.get(text, {})
            if "" in vals:
                cols = [{"name": "q", "type": "number", "values": [vals[""]]}]
            elif vals:
                cols = [{"name": "kube_cluster_name", "type": "group", "values": [[c] for c in vals]},
                        {"name": "q", "type": "number", "values": list(vals.values())}]
            else:
                cols = []
            return 200, {"data": {"type": "scalar_response", "attributes": {"columns": cols}}}
        if p == "/api/v1/monitor" and method == "POST":
            self.next_id += 1
            self.monitors[self.next_id] = {**data, "id": self.next_id, "overall_state": "OK"}
            return 200, self.monitors[self.next_id]
        if p.startswith("/api/v1/monitor/"):
            mid = int(p.rsplit("/", 1)[1])
            if method == "DELETE":
                self.monitors.pop(mid)
                return 200, {"deleted_monitor_id": mid}
            self.monitors[mid] = {**data, "id": mid, "overall_state": "Alert"}
            return 200, self.monitors[mid]
        if p == "/api/v1/dashboard" and method == "GET":
            return 200, {"dashboards": self.dashboards}
        if p == "/api/v1/dashboard" and method == "POST":
            did = ["abc-def-ghi", "lea-der-brd"][len(self.dashboards)]
            self.dashboards.append({"id": did, "title": data["title"], "url": f"/dashboard/{did}/fleet"})
            return 200, self.dashboards[-1]
        if p.startswith("/api/v1/dashboard/"):
            return 200, {"id": p.rsplit("/", 1)[1], "url": f"/dashboard/{p.rsplit('/', 1)[1]}/fleet"}
        if p == "/api/v2/downtime" and method == "GET":
            return 200, {"data": self.downtimes}
        if p == "/api/v2/downtime" and method == "POST":
            self.downtimes.append({"id": f"dt{len(self.downtimes)}", "attributes": {**data["data"]["attributes"], "status": "active"}})
            return 200, {"data": self.downtimes[-1]}
        if p.startswith("/api/v2/downtime/") and method == "DELETE":
            did = p.rsplit("/", 1)[1]
            for d in self.downtimes:
                if d["id"] == did:
                    d["attributes"]["status"] = "canceled"
            return 204, {}
        return 404, {"errors": [f"fake org has no {method} {p}"]}

    def writes(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET" and not p.endswith("/validate")]


WRITE_ENV = {fm.APP_KEY_ENV: "WRITEKEY777777"}


def run(argv, org, now=None, env=None, keys=None):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fm.main(["--profile", "p", "--region", "r", *argv],
                     keys=keys or (lambda *_: ("APIKEY123456", "APPKEY654321", "datadoghq.com")),
                     http=org, now=now or dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc),
                     env=WRITE_ENV if env is None else env)
    return rc, out.getvalue() + err.getvalue()


print("== apply: one rejected monitor writes nothing ==")
org = FakeOrg(reject={mons["node-not-ready"]["query"]})
rc, text = run(["--apply"], org)
check("exit 1", rc == 1)
check("every monitor was validated, not just up to the first failure",
      sum(1 for _, p, _ in org.calls if p.endswith("/validate")) == len(mons))
check("no write reached the org", org.writes() == [])
check("the rejected monitor is named", "node-not-ready" in text)

print("== apply: a fresh org ==")
stale = {"id": "old1", "attributes": {"message": f"{fm.DOWNTIME_MARK} old", "status": "scheduled"}}
foreign = {"id": "theirs", "attributes": {"message": "someone else's maintenance", "status": "active"}}
org = FakeOrg(downtimes=[stale, foreign])
rc, text = run(["--apply", "--session", "2026-09-08T16:00Z/2026-09-08T19:30Z"], org)
check("exit 0", rc == 0)
check("six monitors created, all managed", len(org.monitors) == 6
      and all(fm.MANAGED_TAG in m["tags"] for m in org.monitors.values()))
check("the dashboard was created and its URL printed", "fleet dashboard: https://app.datadoghq.com/dashboard/abc-def-ghi/fleet" in text)
check("the leaderboard was created and its URL printed",
      "challenge leaderboard: https://app.datadoghq.com/dashboard/lea-der-brd/fleet" in text)
check("the railway command that points monitoring.agenticburn.com at the fleet dashboard is printed (#550)",
      "railway variables --service watch-it-burn-apex --set "
      "WIB_MONITORING_URL='https://app.datadoghq.com/dashboard/abc-def-ghi/fleet'" in text)
check("only the fleet dashboard gets a railway command", text.count("railway variables") == 1)
check("the reminder says the variable redeploys the apex router, so run it in setup, not in a session",
      "redeploys watch-it-burn-apex, which restarts the router" in text
      and "during event setup, not during a session" in text)
check("our previous downtime was cancelled", stale["attributes"]["status"] == "canceled")
check("someone else's downtime was left alone", foreign["attributes"]["status"] == "active")
new_dts = [d for d in org.downtimes if d["attributes"]["status"] == "active" and fm.ours(d)]
check("two new mutes: until the session starts, and from when it ends", len(new_dts) == 2)
check("the dashboard is written before any monitor",
      [p for _, p in org.writes()].index("/api/v1/dashboard") < [p for _, p in org.writes()].index("/api/v1/monitor"))
check("no key value is printed", "APIKEY" not in text and "APPKEY" not in text and "WRITEKEY" not in text)
check("the keys travel only as headers", all(h.get("DD-API-KEY") == "APIKEY123456" for _, _, h in org.calls))
check(f"the apply writes with {fm.APP_KEY_ENV}, not the secret's read-only application key (#629)",
      all(h.get("DD-APPLICATION-KEY") == "WRITEKEY777777" for _, _, h in org.calls))
check("the org is named from /api/v2/current_user, which the read-only key may call, not /api/v1/org",
      "instructor org: Datadog Whitney Sandbox" in text and all(p != "/api/v1/org" for _, p, _ in org.calls))

print("== apply again: in place, nothing duplicated ==")
ids_before = set(org.monitors)
rc, text = run(["--apply", "--session", "2026-09-08T16:00Z/2026-09-08T19:30Z"], org)
check("exit 0", rc == 0)
check("the same six monitor ids", set(org.monitors) == ids_before)
check("both dashboards were updated, not duplicated", len(org.dashboards) == 2 and text.count("dashboard updated") == 2)
check("exactly two of our mutes are active afterwards",
      len([d for d in org.downtimes if d["attributes"]["status"] == "active" and fm.ours(d)]) == 2)

print("== check: the live org against the repo ==")
calls_before = len(org.calls)
rc, text = run(["--check"], org, env={})
check("an org holding exactly the repo passes", rc == 0 and "MISSING" not in text and "DRIFT" not in text)
check("check needs no write key: it reads with the secret's read-only application key",
      all(h.get("DD-APPLICATION-KEY") == "APPKEY654321" for _, _, h in org.calls[calls_before:]))
check("each monitor's state is reported", "Alert" in text)
victim = next(i for i, m in org.monitors.items() if "wib-monitor:console-unavailable" in m["tags"])
org.monitors[victim]["query"] = "max(last_5m):max:something.else{*} < 1"
rc, text = run(["--check"], org)
check("a monitor edited in the UI is drift", rc == 1 and "DRIFT    console-unavailable" in text)
check("check never writes", all(m == "GET" for m, _, _ in org.calls[-6:]))
rc, text = run(["--check"], FakeOrg())
check("an empty org fails the check, naming every monitor and both dashboards",
      rc == 1 and text.count("MISSING") == len(mons) + 2 and "MISSING  challenge leaderboard" in text)

print("== data: every query returns data for every cluster (#706) ==")
CLUSTERS = ["burritobot-public", "burritobot-private"]
DATA_ARGS = ["--data", "--cluster", CLUSTERS[0], "--cluster", CLUSTERS[1]]
fleet_queries = [(w["definition"], q) for w in dash["widgets"]
                 for r in w["definition"].get("requests", []) for q in r.get("queries", [])]
signals = {k: m["signal"] for k, m in mons.items() if m.get("signal")}
absence = [k for k in mons if k not in signals]


def is_grouped(q):
    if q.get("data_source") == "logs":
        return fm.GROUP_BY in {g.get("facet") for g in q.get("group_by") or []}
    return "by {kube_cluster_name}" in q["query"] and not q["query"].startswith("count_not_null(")


def shipping():
    """What the org answers when both clusters ship and each has had a /chat inside the window."""
    data = {}
    for q in [q for _, q in fleet_queries] + list(signals.values()):
        data[fm.query_text(q)] = {c: 1.0 for c in CLUSTERS} if is_grouped(q) else {"": 2.0}
    return data, {k: {c: "OK" for c in CLUSTERS} for k in absence}


check("the monitors that fire on a rising count are the ones with a signal",
      sorted(signals) == sorted(k for k, m in mons.items() if fm.fires_on_rise(m["query"]))
      and sorted(signals) == ["guard-proxy-erroring", "node-not-ready"])
check("node-not-ready's signal is its metric without the status filter",
      fm.query_text(signals.get("node-not-ready", {"query": ""})) ==
      "max:kubernetes_state.node.by_condition{kube_cluster_name:burritobot-*,condition:ready} by {kube_cluster_name}")
check("guard-proxy-erroring's signal is its log search without status:error",
      fm.query_text(signals.get("guard-proxy-erroring", {})) ==
      "kube_cluster_name:burritobot-* kube_namespace:agent kube_deployment:guard-proxy")
check("no repo-only signal leaks into the API body",
      all("signal" not in fm.render_monitor(m, []) for m in mons.values()))

org = FakeOrg()
run(["--apply"], org)
org.data, org.groups = shipping()
calls_before = len(org.calls)
rc, text = run(DATA_ARGS, org, env={})
check("an org where both clusters fill every query passes", rc == 0 and "NO DATA" not in text and "MISSING" not in text)
check("every absence monitor's state is read, with its groups",
      text.count("DATA     monitor") == len(mons) and any("group_states=all" in u for u in org.urls[calls_before:]))
sent = [t for t, _, _ in org.scalars]
check("every fleet-dashboard query and every signal is sent to the scalar API",
      sorted(sent) == sorted([fm.query_text(q) for _, q in fleet_queries] + [fm.query_text(q) for q in signals.values()]))
check("no leaderboard query is sent: its cells are blank until the room plays",
      not any("workshop-mcp" in t or "kube_namespace:security" in t for t in sent))
# The traces query is both a table column (5 minutes) and the timeseries widget (no window of its own).
table = next(q for d, q in fleet_queries if d.get("title") == "Every cluster, last 5 minutes" and q["name"] == "traces")
check("the traces query is read over the table's 5 minutes and the picker's default hour",
      sorted(w for t, w, _ in org.scalars if t == fm.query_text(table)) == [300_000, 3_600_000])
check("a signal is read over its monitor's window",
      [w for t, w, _ in org.scalars if t == fm.query_text(signals["node-not-ready"])] == [300_000])
check("data needs no write key: it reads with the secret's read-only application key",
      all(h.get("DD-APPLICATION-KEY") == "APPKEY654321" for _, _, h in org.calls[calls_before:]))
check("data never writes", all(m == "GET" or p == "/api/v2/query/scalar" for m, p, _ in org.calls[calls_before:]))
rc, text = run(["--check"], org, env={})
check("the same org passes --check", rc == 0)


def blanked(mutate):
    o = FakeOrg()
    run(["--apply"], o)
    o.data, o.groups = shipping()
    mutate(o)
    rc, text = run(DATA_ARGS, o, env={})
    crc, _ = run(["--check"], o, env={})
    return rc, text, crc


rc, text, crc = blanked(lambda o: o.data[fm.query_text(table)].pop(CLUSTERS[1]))
check("a fleet-dashboard column blank for one cluster fails, naming the column and the cluster",
      rc == 1 and "NO DATA  fleet dashboard / Every cluster, last 5 minutes / traces: burritobot-private" in text)
check("--check alone passes that org: loaded is not fed", crc == 0)
rc, text, crc = blanked(lambda o: o.groups["cluster-silent"].update({CLUSTERS[0]: "No Data"}))
check("a monitor whose group for a cluster is No Data fails, naming both",
      rc == 1 and "NO DATA  monitor cluster-silent" in text and "burritobot-public" in text.split("NO DATA  monitor cluster-silent", 1)[1].splitlines()[0])
check("--check alone passes an org whose monitor is No Data", crc == 0)
rc, text, _ = blanked(lambda o: o.groups["console-unavailable"].pop(CLUSTERS[1]))
check("a monitor with no group for a cluster fails", rc == 1 and "NO DATA  monitor console-unavailable" in text)
rc, text, _ = blanked(lambda o: o.data[fm.query_text(signals["guard-proxy-erroring"])].pop(CLUSTERS[0]))
check("a signal that answers nothing for a cluster fails",
      rc == 1 and "NO DATA  monitor guard-proxy-erroring (its signal): burritobot-public" in text)
spend = next(q for d, q in fleet_queries if d.get("title") == "Room spend so far (USD)")
rc, text, _ = blanked(lambda o: o.data.update({fm.query_text(spend): {"": None}}))
check("an ungrouped tile that answers null fails", rc == 1 and "NO DATA  fleet dashboard / Room spend so far (USD)" in text)
rc, text, _ = blanked(lambda o: o.data.pop(fm.query_text(table)))
check("a column that answers nothing at all fails", rc == 1 and "NO DATA  fleet dashboard / Every cluster, last 5 minutes / traces" in text)
rc, text, _ = blanked(lambda o: o.monitors.pop(next(i for i, m in o.monitors.items() if "wib-monitor:no-traces" in m["tags"])))
check("a monitor not in the org fails --data too", rc == 1 and "MISSING  monitor no-traces" in text)
o3 = FakeOrg()
run(["--apply"], o3)
o3.data, o3.groups = shipping()
rc, text = run([*DATA_ARGS, "--cluster", "burritobot-attendee-007"], o3, env={})
check("a named cluster that ships nothing fails every per-cluster query",
      rc == 1 and text.count("burritobot-attendee-007") >= len(absence) + 1)

def keys_unread(*_):
    raise AssertionError("keys read before the arguments were checked")
org = FakeOrg()
rc, text = run(["--data"], org, env={}, keys=keys_unread)
check("--data without a --cluster exits 1 and calls nothing", rc == 1 and "--cluster" in text and org.calls == [])
rc, text = run(["--data", "--cluster", "watch-it-burn-community"], org, env={}, keys=keys_unread)
check("a --cluster outside the queries' filter is refused", rc == 1 and "could never fill" in text and org.calls == [])
rc, text = run(["--check", "--cluster", CLUSTERS[0]], org, env={})
check("--cluster without --data is refused", rc == 1 and "only means something with --data" in text)

print("== validation: a bad-news monitor needs a signal on its own source ==")
def broken_signal(key, **over):
    d = json.loads(json.dumps(defs))
    m = next(m for m in d["monitors"] if m["key"] == key)
    for k, v in over.items():
        if v is None:
            m.pop(k, None)
        else:
            m[k] = v
    return fm.validate_monitors(d)
check("a monitor that fires on a rising count without a signal is refused",
      any("give it a signal" in p for p in broken_signal("node-not-ready", signal=None)))
check("a signal on another metric is refused", any("not the monitor's metric" in p for p in broken_signal(
      "node-not-ready", signal={"data_source": "metrics", "query": "max:kubernetes_state.node.count{kube_cluster_name:burritobot-*} by {kube_cluster_name}"})))
check("a signal filtering on a tag the monitor does not is refused", any("which the monitor does not" in p for p in broken_signal(
      "node-not-ready", signal={"data_source": "metrics", "query": "max:kubernetes_state.node.by_condition{kube_cluster_name:burritobot-*,condition:memorypressure} by {kube_cluster_name}"})))
check("an ungrouped signal is refused", any("signal is not grouped" in p for p in broken_signal(
      "node-not-ready", signal={"data_source": "metrics", "query": "max:kubernetes_state.node.by_condition{kube_cluster_name:burritobot-*,condition:ready}"})))
check("a logs signal searching a term the monitor does not is refused", any("which the monitor does not" in p for p in broken_signal(
      "guard-proxy-erroring", signal={**signals["guard-proxy-erroring"], "search": {"query": "kube_cluster_name:burritobot-* kube_deployment:console"}})))
check("a signal on a monitor that fires on absence is refused",
      any("fires on absence" in p for p in broken_signal("cluster-silent", signal=signals["node-not-ready"])))

print("== apply needs the write key, and only ever the sandbox org ==")
def no_keys_read(*_):
    raise AssertionError("keys read before the write key was checked")
org = FakeOrg()
rc, text = run(["--apply"], org, env={}, keys=no_keys_read)
check(f"--apply without {fm.APP_KEY_ENV} exits 1, reads no keys and calls nothing",
      rc == 1 and fm.APP_KEY_ENV in text and "read-only" in text and org.calls == [])
for mode in (["--apply"], ["--check"]):
    org = FakeOrg(org="event-001")
    rc, text = run(mode, org)
    check(f"{mode[0]} against an org not named Datadog* exits 1 having written nothing",
          rc == 1 and "'event-001', not the sandbox org" in text and org.writes() == []
          and [p for _, p, _ in org.calls] == ["/api/v2/current_user"])
org = FakeOrg(org="Acme Pool 3")
rc, text = run(["--apply"], org, env={**WRITE_ENV, "WIB_DD_POOL_PREFIX": "Acme Pool"})
check("WIB_DD_POOL_PREFIX names a per-event pool's org instead", rc == 0 and len(org.monitors) == 6)

print("== dry run touches nothing ==")
def no_keys(*_):
    raise AssertionError("a dry run must not read keys")
out = io.StringIO()
with redirect_stdout(out):
    rc = fm.main(["--profile", "p", "--region", "r"], keys=no_keys, http=FakeOrg(), env={})
check("a dry run reads no keys and exits 0", rc == 0 and "dry run" in out.getvalue())
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    check("a notify handle without @ is refused", fm.main(["--profile", "p", "--region", "r", "--notify", "oncall"], keys=no_keys, env={}) == 1)

print("== fleet.sh is the way in ==")
check("fleet.sh has a monitors verb", re.search(r"^\s+monitors\) exec python3 .*fleet_monitors\.py", fleet_src, re.M) is not None)
verb = fleet_src.split("monitors) exec python3", 1)[1].split(";;", 1)[0] if "monitors) exec python3" in fleet_src else ""
check("it passes the account and region explicitly", '--profile "${WIB_DEFAULT_ACCOUNT}"' in verb and '--region "${WIB_REGION}"' in verb)
check("usage documents it", "monitors [--apply|--check]" in fleet_src)
check("usage documents the data check", "monitors --data --cluster NAME" in fleet_src)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All fleet monitor checks passed.")
