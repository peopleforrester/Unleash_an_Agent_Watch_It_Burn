# ABOUTME: Load the fleet monitors, the fleet dashboard and the challenge leaderboard into the INSTRUCTOR Datadog
# ABOUTME: org after validating every definition. Dry run by default, --apply writes, --check compares (#267, #307).
"""Load the instructor-org fleet monitors and dashboards, deterministically.

The definitions are monitors.yaml, dashboard.yaml and leaderboard.yaml next to this file. They are the source
of truth: a monitor is found in the org by its wib-monitor:<key> tag and updated in place, a managed monitor
that is no longer in the file is deleted, and each dashboard is found by its title and replaced. Nothing is
edited by hand in the Datadog UI, because the next apply overwrites it.

Same shape as the Datadog pool loader (provisioning-agenticburn scripts/load_datadog_pool.py, #256):
    dry run (default)  render and validate every definition offline; print the plan; touch nothing.
    --apply            read the instructor org keys, ask Datadog to validate EVERY monitor, and only if all
                       of them pass write the dashboards, the monitors and the session downtimes. One bad
                       definition aborts the load before any write.
    --check            read-only against the live org: every defined monitor and both dashboards exist, the
                       monitors with the queries in this repo. Prints each monitor's state. Exit 1 on any drift.
    --data --cluster NAME [--cluster NAME ...]
                       read-only: every query returns data for every named cluster (#706). Each monitor that
                       fires on absence has a group per cluster in a state other than No Data; each monitor that
                       fires on a rising count, which is empty on a healthy cluster, has its `signal` (the same
                       source without the bad-news filter) answer for each cluster, over the monitor's window or
                       the signal's own `window` when it names one (#485); every query on the fleet
                       dashboard answers for each cluster over its widget's window. Exit 1 on any blank. A
                       `scope: org` monitor (#810), on a metric with no cluster tag, must be in a state other
                       than No Data as a whole.
    --board --cluster NAME [--cluster NAME ...]
                       read-only, once a cluster has been walked through challenges 1 to 6 (#489, #862): the
                       challenge leaderboard is in the org with the table this repo defines, and the table's
                       request, sent whole the way the widget sends it, fills every column for every named cluster
                       over the widget's window. Filled means the cell the room reads as done: green under the
                       column's conditional format, or above 0 for the bill. Exit 1 on any blank cell.

The org. For KubeCon NA 2026 the instructor org is Whitney's sandbox org: Datadog no longer issues per-student
orgs, so both clusters ship there (#629, #454), and its keys are Secrets Manager watch-it-burn/datadog (the secret
fleet.sh gives the clusters). The org name must start with WIB_DD_POOL_PREFIX (default "Datadog", as in
verify/datadog-orgs.sh and room_view.py), so the monitors are never written into, or checked against, some other
org. The application key in that secret is read-only, which --check needs and --apply cannot use: the apply
writes monitors, downtimes and dashboards. --apply therefore takes the application key from
WIB_FLEET_MONITORS_APP_KEY in this command's environment, a key Whitney issues from her own user. It must be
unscoped: Datadog refuses log monitors created with a scoped one. Key values are never printed.

The session window. The no-traces and agent-obs-silent monitors only mean something while students are at
their keyboards; at any other time an idle cluster is a correct cluster. Monitors marked `session: true` are muted by downtimes
this script owns: with --session START/END they are muted until START and again from END, and with no
window they are muted indefinitely, so applying outside an event never pages anybody. Every apply cancels
the downtimes the previous apply created (they carry the marker below in their message) before it creates
its own, so the window can be moved by re-running.

Usage (fleet.sh passes the profile and region; it is the normal way in):
    fleet.sh monitors                                                   # dry run
    WIB_FLEET_MONITORS_APP_KEY=<key> fleet.sh monitors --apply --session 2026-09-08T16:00Z/2026-09-08T19:30Z
    fleet.sh monitors --check
    fleet.sh monitors --data --cluster burritobot-public --cluster burritobot-private   # after a /chat on each
    fleet.sh monitors --board --cluster burritobot-private        # after walking that cluster through 1 to 6
    python3 infra/datadog-fleet/fleet_monitors.py --profile accen-dev --region us-west-2 [--apply|--check]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

HERE = pathlib.Path(__file__).resolve().parent
MONITORS_FILE = HERE / "monitors.yaml"
DASHBOARD_FILE = HERE / "dashboard.yaml"
LEADERBOARD_FILE = HERE / "leaderboard.yaml"
# (label, file): the label is what the apply prints in front of each dashboard's URL.
DASHBOARDS = (("fleet dashboard", DASHBOARD_FILE), ("challenge leaderboard", LEADERBOARD_FILE))
# The dashboard monitoring.agenticburn.com redirects to, and the apex Railway service that holds the target.
MONITORING_LABEL = "fleet dashboard"
APEX_SERVICE = "watch-it-burn-apex"
SECRET_ID = "watch-it-burn/datadog"
APP_KEY_ENV = "WIB_FLEET_MONITORS_APP_KEY"
MANAGED_TAG = "managed-by:wib-fleet-monitors"
KEY_TAG_PREFIX = "wib-monitor:"
SESSION_TAG = "window:session"
DOWNTIME_MARK = "[wib-fleet-monitors]"
GROUP_BY = "kube_cluster_name"
# The group value Datadog's scalar API gives a series that lacks the tag, and a rollup that removed it (#485).
NO_GROUP = "N/A"
# A signal's own read window, for a source that is quiet on a healthy cluster even with traffic (#485): guard-proxy
# logs only events, never a plain chat. Without it a signal is read over its monitor's window.
SIGNAL_WINDOW = "window"
TYPES = ("metric alert", "query alert", "log alert")
# The metrics that carry no cluster tag, so a monitor on them is one alert for the whole org (`scope: org`, #810).
# Agent Observability's ml_obs.* carry env, ml_app, service, version and a few more, never a span's k8s.cluster.name
# (docs.datadoghq.com/llm_observability/monitoring/metrics, read 2026-11-03). Every other metric is per cluster.
ORG_SCOPE_METRICS = ("ml_obs.",)
ORG_SCOPE = "org"
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# The dashboards --data reads. The leaderboard counts challenge outcomes, so it is blank until the room plays;
# --board reads it, for clusters that have played (#862).
DATA_DASHBOARDS = ("fleet dashboard",)
BOARD_LABEL = "challenge leaderboard"
COMPARATORS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}
# A widget without its own time follows the dashboard's time picker, which opens on the last hour.
DEFAULT_SPAN_S = 3600
SPAN_RE = re.compile(r"^([0-9]+)([mhd])$")


# ---- definitions: pure, offline ------------------------------------------------------------------------

def load_monitors(path: pathlib.Path = MONITORS_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_dashboard(path: pathlib.Path = DASHBOARD_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_dashboards() -> list[tuple[str, dict]]:
    return [(label, load_dashboard(path)) for label, path in DASHBOARDS]


def validate_monitors(defs: dict) -> list[str]:
    """Problems with the monitor file that Datadog would accept and the room would regret. Empty is good."""
    problems: list[str] = []
    flt = str(defs.get("cluster_filter") or "")
    if not flt.startswith(f"{GROUP_BY}:"):
        problems.append(f"cluster_filter '{flt}' does not filter on {GROUP_BY}")
    mons = defs.get("monitors") or []
    if not mons:
        problems.append("no monitors defined")
    seen: set[str] = set()
    for i, m in enumerate(mons, 1):
        key = str(m.get("key", ""))
        where = f"monitor {i} ({key or 'no key'})"
        missing = [k for k in ("key", "name", "type", "query", "message", "options") if not m.get(k)]
        if missing:
            problems.append(f"{where}: missing {missing}")
            continue
        if not KEY_RE.match(key):
            problems.append(f"{where}: key must be lowercase letters, digits and hyphens")
        if key in seen:
            problems.append(f"{where}: duplicate key")
        seen.add(key)
        if m["type"] not in TYPES:
            problems.append(f"{where}: type '{m['type']}' not in {TYPES}")
        q = m["query"]
        org_metric = m["type"] != "log alert" and metric_source(q)[0].startswith(ORG_SCOPE_METRICS)
        if "scope" in m and m["scope"] != ORG_SCOPE:
            problems.append(f"{where}: scope '{m['scope']}' is not '{ORG_SCOPE}'; leave it out for a per-cluster monitor")
            continue
        if m.get("scope") == ORG_SCOPE or org_metric:
            problems += validate_org_scope(where, m, org_metric)
        else:
            if flt and flt not in q:
                problems.append(f"{where}: query is not filtered to {flt}")
            if m["type"] == "log alert":
                if f'.by("{GROUP_BY}")' not in q:
                    problems.append(f'{where}: log query is not grouped .by("{GROUP_BY}")')
            elif not re.search(r"\bby \{" + GROUP_BY + r"\}", q):
                problems.append(f"{where}: metric query is not grouped by {{{GROUP_BY}}}")
            if "{{" + GROUP_BY + ".name}}" not in m["message"]:
                problems.append(f"{where}: message does not name the cluster ({{{{{GROUP_BY}.name}}}})")
            problems += validate_signal(where, m, flt)
        th = (m["options"] or {}).get("thresholds") or {}
        if "critical" not in th:
            problems.append(f"{where}: options.thresholds.critical is required")
        else:
            tail = re.search(r"(<=|>=|<|>|==)\s*(-?[0-9.]+)\s*$", q)
            if not tail:
                problems.append(f"{where}: query does not end in a comparison with a threshold")
            elif float(tail.group(2)) != float(th["critical"]):
                problems.append(f"{where}: query threshold {tail.group(2)} != options.thresholds.critical {th['critical']}")
        opts = m["options"]
        if opts.get("notify_no_data") and not opts.get("no_data_timeframe"):
            problems.append(f"{where}: notify_no_data without no_data_timeframe")
    return problems


def validate_org_scope(where: str, m: dict, org_metric: bool) -> list[str]:
    """A `scope: org` monitor (#810) is one alert for the whole org, on a metric that carries no cluster tag. A
    cluster filter on such a metric never fills and a group by cluster is empty, so either would make it silent;
    and on a metric that does carry the cluster, org scope would average a dead cluster into the room."""
    q = m["query"]
    if not org_metric:
        return [f"{where}: scope: org on '{metric_source(q)[0] or m['type']}', which carries the cluster; only "
                f"{', '.join(ORG_SCOPE_METRICS)}* are org-wide, everything else is one alert group per {GROUP_BY}"]
    problems = []
    if m.get("scope") != ORG_SCOPE:
        problems.append(f"{where}: {metric_source(q)[0]} carries no cluster tag, so it cannot be per cluster; "
                        f"mark it scope: {ORG_SCOPE}")
    if GROUP_BY in q:
        problems.append(f"{where}: {metric_source(q)[0]} carries no {GROUP_BY}, so a filter or group on it never fills")
    if re.search(r"\bby \{", q):
        problems.append(f"{where}: an org-wide monitor is one alert group; drop the 'by {{...}}'")
    if fires_on_rise(q) or m.get("signal"):
        problems.append(f"{where}: an org-wide monitor fires on absence ('< n' and notify_no_data); "
                        "--data reads its state, so it takes no signal")
    if not (m["options"] or {}).get("notify_no_data"):
        problems.append(f"{where}: an org-wide absence monitor needs notify_no_data: a count with nothing in it is No Data")
    if "{{" + GROUP_BY in m["message"]:
        problems.append(f"{where}: the message names {{{{{GROUP_BY}...}}}}, which is empty on an org-wide alert")
    return problems


def fires_on_rise(query: str) -> bool:
    return re.search(r">=?\s*-?[0-9.]+\s*$", query.rstrip()) is not None


def metric_source(q: str) -> tuple[str, set[str]]:
    """(metric name, tag filters) of the first metric{...} in a query."""
    m = re.search(r"([A-Za-z_][\w.]*)\{([^}]*)\}", q)
    return (m.group(1), {t.strip() for t in m.group(2).split(",") if t.strip()}) if m else ("", set())


def log_search(q: str) -> str:
    m = re.search(r'logs\("((?:[^"\\]|\\.)*)"\)', q)
    return m.group(1) if m else ""


def validate_signal(where: str, m: dict, flt: str) -> list[str]:
    """A monitor that fires on a rising count reads nothing on a healthy cluster, so --data cannot tell a right name
    from a wrong one by its state. Its `signal` is a dashboard-style query on the same source with the bad-news
    filter dropped: the same metric with a subset of its tags, or a subset of its log search terms."""
    sig = m.get("signal")
    if not fires_on_rise(m["query"]):
        return [f"{where}: a signal on a monitor that fires on absence; --data reads its own state"] if sig else []
    if not sig:
        return [f"{where}: fires on a rising count, so its query is empty on a healthy cluster; "
                "give it a signal (the same source without the bad-news filter) for --data to read"]
    problems = []
    window = sig.get(SIGNAL_WINDOW)
    if window is not None and not SPAN_RE.match(str(window)):
        problems.append(f"{where}: signal window '{window}' is not <n>m, <n>h or <n>d")
    text = query_text(sig)
    if flt not in text:
        problems.append(f"{where}: signal is not filtered to {flt}")
    if sig.get("data_source", "metrics") == "metrics":
        name, tags = metric_source(text)
        want, have = metric_source(m["query"])
        if m["type"] == "log alert" or not name or name != want:
            problems.append(f"{where}: signal reads '{name}', not the monitor's metric '{want}'")
        elif not tags <= have:
            problems.append(f"{where}: signal filters on {sorted(tags - have)}, which the monitor does not")
        if not re.search(r"\bby \{" + GROUP_BY + r"\}", text):
            problems.append(f"{where}: signal is not grouped by {{{GROUP_BY}}}")
    elif sig.get("data_source") == "logs":
        have = set(log_search(m["query"]).split())
        if m["type"] != "log alert":
            problems.append(f"{where}: a logs signal on a monitor that is not a log alert")
        elif not set(text.split()) <= have:
            problems.append(f"{where}: signal searches {sorted(set(text.split()) - have)}, which the monitor does not")
        if GROUP_BY not in {g.get("facet") for g in sig.get("group_by") or []}:
            problems.append(f"{where}: signal is not grouped by {GROUP_BY}")
    else:
        problems.append(f"{where}: signal data_source must be metrics or logs")
    return problems


# The dashboard data sources whose queries are a search plus a group_by (logs, and the leaderboard's /chat spans,
# #489), as opposed to a metric query that carries its grouping in `by {...}`.
EVENT_SOURCES = ("logs", "spans")


def query_text(q: dict) -> str:
    """The filter string of a dashboard query: a metric query carries it in `query`, a logs or spans query in
    `search.query`."""
    if q.get("data_source", "metrics") == "metrics":
        return q.get("query", "")
    return (q.get("search") or {}).get("query", "")


def validate_dashboard(dash: dict, cluster_filter: str) -> list[str]:
    problems: list[str] = []
    for k in ("title", "layout_type", "widgets"):
        if not dash.get(k):
            problems.append(f"dashboard: missing {k}")
    for i, w in enumerate(dash.get("widgets") or [], 1):
        d = w.get("definition") or {}
        if not d.get("type"):
            problems.append(f"dashboard widget {i}: no definition.type")
        for r in d.get("requests") or []:
            names = {q.get("name") for q in r.get("queries") or []}
            for q in r.get("queries") or []:
                if cluster_filter and cluster_filter not in query_text(q):
                    problems.append(f"dashboard widget {i} query {q.get('name')}: not filtered to {cluster_filter}")
                if q.get("data_source") in EVENT_SOURCES and GROUP_BY not in {g.get("facet") for g in q.get("group_by") or []}:
                    problems.append(f"dashboard widget {i} query {q.get('name')}: {q.get('data_source')} query is not grouped by {GROUP_BY}")
            for f in r.get("formulas") or []:
                refs = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", f.get("formula", ""))) - {"count_not_null"}
                if not refs <= names:
                    problems.append(f"dashboard widget {i}: formula '{f.get('formula')}' names a query that does not exist")
    return problems


def render_monitor(m: dict, notify: list[str]) -> dict:
    """The API body for one monitor definition. Pure; the tests assert on this."""
    tags = [MANAGED_TAG, f"{KEY_TAG_PREFIX}{m['key']}", "service:watch-it-burn"]
    if m.get("session"):
        tags.append(SESSION_TAG)
    message = m["message"].rstrip()
    if m.get("scope") != ORG_SCOPE:  # an org-wide alert names no cluster; its message says how to find one
        message += "\n\nFrom outside, for this cluster: fleet.sh verify {{" + GROUP_BY + ".name}}"
    if notify:
        message += "\n\n" + " ".join(notify)
    opts = {"include_tags": True, "notify_audit": False, **m["options"]}
    body = {"name": m["name"], "type": m["type"], "query": m["query"], "message": message,
            "tags": tags, "options": opts}
    if m.get("priority"):
        body["priority"] = int(m["priority"])
    return body


def key_of(monitor: dict) -> str:
    for t in monitor.get("tags") or []:
        if t.startswith(KEY_TAG_PREFIX):
            return t[len(KEY_TAG_PREFIX):]
    return ""


def plan_monitors(rendered: dict[str, dict], existing: list[dict]) -> list[tuple]:
    """(action, key, monitor_id, body) for every change. Pure: existing is what the org already holds."""
    live = {}
    for m in existing:
        k = key_of(m)
        if k:
            live.setdefault(k, []).append(m)
    actions: list[tuple] = []
    for k, body in rendered.items():
        found = live.pop(k, [])
        if found:
            actions.append(("update", k, found[0]["id"], body))
            actions.extend(("delete", k, extra["id"], None) for extra in found[1:])  # a duplicate key
        else:
            actions.append(("create", k, None, body))
    for k, ms in live.items():
        actions.extend(("delete", k, m["id"], None) for m in ms)
    # A monitor carrying the managed tag and no key tag was made by hand to look like ours. Leave it alone.
    return actions


def parse_session(spec: str | None) -> tuple[dt.datetime, dt.datetime] | None:
    if not spec:
        return None
    try:
        a, b = spec.split("/", 1)
        start, end = (dt.datetime.fromisoformat(x.strip().replace("Z", "+00:00")) for x in (a, b))
    except ValueError as e:
        raise ValueError(f"--session must be START/END in ISO-8601 UTC, got '{spec}'") from e
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("--session times must carry a UTC offset (end them in Z)")
    start, end = start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)
    if end <= start:
        raise ValueError("--session END must be after START")
    return start, end


def mute_windows(session, now: dt.datetime) -> list[tuple]:
    """(start, end) pairs in which the session monitors are muted; None means now, or never ending."""
    if session is None:
        return [(None, None)]
    start, end = session
    if now >= end:
        return [(None, None)]
    windows = []
    if now < start:
        windows.append((None, start))
    windows.append((end, None))
    return windows


def render_downtime(window: tuple, session) -> dict:
    start, end = window
    why = ("no session window declared" if session is None
           else f"outside the session window {session[0]:%Y-%m-%dT%H:%MZ}/{session[1]:%Y-%m-%dT%H:%MZ}")
    attrs = {
        "scope": "*",
        "monitor_identifier": {"monitor_tags": [MANAGED_TAG, SESSION_TAG]},
        "message": f"{DOWNTIME_MARK} {why}. Re-run fleet.sh monitors --apply --session START/END to move it.",
        "mute_first_recovery_notification": True,
    }
    schedule = {}
    if start is not None:
        schedule["start"] = start.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if end is not None:
        schedule["end"] = end.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if schedule:
        attrs["schedule"] = schedule
    return {"data": {"type": "downtime", "attributes": attrs}}


def ours(downtime: dict) -> bool:
    a = downtime.get("attributes") or {}
    return str(a.get("message", "")).startswith(DOWNTIME_MARK) and a.get("status") in ("active", "scheduled")


def norm(q: str) -> str:
    return re.sub(r"\s+", "", q or "")


# ---- the org: everything below talks to Datadog -----------------------------------------------------

class Datadog:
    def __init__(self, site: str, api_key: str, app_key: str, http=None):
        self.base = f"https://api.{site}"
        self.site = site
        self.headers = {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key,
                        "Content-Type": "application/json", "Accept": "application/json"}
        self.http = http or self._urllib

    def _urllib(self, method: str, url: str, headers: dict, body: bytes | None):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"errors": [raw[:300]]}

    def call(self, method: str, path: str, body=None, ok=(200, 201, 202, 204)):
        status, data = self.http(method, self.base + path, self.headers,
                                 None if body is None else json.dumps(body).encode())
        if status not in ok:
            raise RuntimeError(f"{method} {path.split('?')[0]} -> {status}: {json.dumps(data.get('errors', data))[:300]}")
        return data


def read_keys(profile: str, region: str, run=subprocess.run) -> tuple[str, str, str]:
    out = run(["aws", "secretsmanager", "get-secret-value", "--secret-id", SECRET_ID, "--profile", profile,
               "--region", region, "--query", "SecretString", "--output", "text"],
              capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"cannot read {SECRET_ID} as profile {profile} in {region}: {out.stderr.strip()[:200]}")
    d = json.loads(out.stdout)
    if not (d.get("api-key") and d.get("app-key")):
        raise RuntimeError(f"{SECRET_ID} has no api-key/app-key pair")
    return d["api-key"], d["app-key"], d.get("site") or "datadoghq.com"


def org_name(dd: Datadog) -> str:
    # /api/v2/current_user, not /api/v1/org: the sandbox org's read-only key answers that one 403 (#629).
    me = dd.call("GET", "/api/v2/current_user")
    return next((i["attributes"]["name"] for i in me.get("included", []) if i.get("type") == "orgs"), "?")


def managed_monitors(dd: Datadog, group_states: bool = False) -> list[dict]:
    params = {"monitor_tags": MANAGED_TAG}
    if group_states:
        params["group_states"] = "all"  # state.groups: one entry per kube_cluster_name, with its status
    return dd.call("GET", f"/api/v1/monitor?{urllib.parse.urlencode(params)}")


def all_downtimes(dd: Datadog, limit: int = 100) -> list[dict]:
    """Every downtime in the org, scheduled ones included: the end-of-session mute starts in the future."""
    out, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"page[limit]": limit, "page[offset]": offset})
        page = dd.call("GET", f"/api/v2/downtime?{q}").get("data", [])
        out.extend(page)
        if len(page) < limit:
            return out
        offset += limit


def find_dashboard(dd: Datadog, title: str) -> dict | None:
    hits = [d for d in dd.call("GET", "/api/v1/dashboard").get("dashboards", []) if d.get("title") == title]
    return hits[0] if hits else None


def apply(dd: Datadog, defs: dict, dashes: list[tuple[str, dict]], notify: list[str], session, now: dt.datetime,
          say=print) -> int:
    rendered = {m["key"]: render_monitor(m, notify) for m in defs["monitors"]}
    session_keys = [m["key"] for m in defs["monitors"] if m.get("session")]

    # 1. Datadog validates every monitor before anything is written. One failure aborts the whole load.
    problems = []
    for k, body in rendered.items():
        try:
            dd.call("POST", "/api/v1/monitor/validate", body)
        except RuntimeError as e:
            problems.append(f"{k}: {e}")
    if problems:
        say(f"REFUSING to apply: Datadog rejected {len(problems)} monitor(s); nothing was written")
        for p in problems:
            say(f"  - {p}")
        return 1

    # 2. The dashboards, each found by title so its URL survives re-applies.
    urls = []
    for label, dash in dashes:
        existing = find_dashboard(dd, dash["title"])
        if existing:
            out = dd.call("PUT", f"/api/v1/dashboard/{existing['id']}", dash)
            say(f"  dashboard updated: {dash['title']}")
        else:
            out = dd.call("POST", "/api/v1/dashboard", dash)
            say(f"  dashboard created: {dash['title']}")
        urls.append((label, f"https://app.{dd.site}{out.get('url') or '/dashboard/' + str(out.get('id'))}"))

    # 3. Monitors: update in place by key, create what is new, delete what left the file.
    for action, k, mid, body in plan_monitors(rendered, managed_monitors(dd)):
        if action == "create":
            mid = dd.call("POST", "/api/v1/monitor", body)["id"]
        elif action == "update":
            dd.call("PUT", f"/api/v1/monitor/{mid}", body)
        else:
            dd.call("DELETE", f"/api/v1/monitor/{mid}")
        say(f"  monitor {action}d: {k} (id {mid})")

    # 4. Session downtimes: cancel the previous apply's, then mute outside the declared window.
    if session_keys:
        for d in all_downtimes(dd):
            if ours(d):
                dd.call("DELETE", f"/api/v2/downtime/{d['id']}")
                say(f"  downtime cancelled: {d['id']}")
        for w in mute_windows(session, now):
            dd.call("POST", "/api/v2/downtime", render_downtime(w, session))
            s = "now" if w[0] is None else f"{w[0]:%Y-%m-%dT%H:%MZ}"
            e = "indefinitely" if w[1] is None else f"until {w[1]:%Y-%m-%dT%H:%MZ}"
            say(f"  session monitors ({', '.join(session_keys)}) muted from {s} {e}")

    for label, url in urls:
        say(f"  {label}: {url}")
    # monitoring.agenticburn.com is a 302 to WIB_MONITORING_URL on the apex Railway service
    # (apex-agenticburn#34), and answers 503 until it is set. Setting it is deploy configuration, so the
    # apply only prints the command (#550).
    for label, url in urls:
        if label == MONITORING_LABEL:
            say("  point monitoring.agenticburn.com at it (by hand):")
            say(f"    railway variables --service {APEX_SERVICE} --set WIB_MONITORING_URL='{url}'")
            say(f"  changing a Railway variable redeploys {APEX_SERVICE}, which restarts the router:"
                " run it during event setup, not during a session.")
    return 0


def check(dd: Datadog, defs: dict, dashes: list[tuple[str, dict]], say=print) -> int:
    """Read-only: does the live org hold exactly what this repo defines? Exit 1 on any drift."""
    drift = 0
    live = {key_of(m): m for m in managed_monitors(dd) if key_of(m)}
    for m in defs["monitors"]:
        lm = live.pop(m["key"], None)
        if lm is None:
            say(f"  MISSING  {m['key']}: not in the org (run fleet.sh monitors --apply)")
            drift += 1
        elif norm(lm.get("query")) != norm(m["query"]):
            say(f"  DRIFT    {m['key']}: live query differs from monitors.yaml")
            drift += 1
        else:
            say(f"  {lm.get('overall_state', '?'):<8} {m['key']}")
    for k in live:
        say(f"  EXTRA    {k}: managed monitor no longer in monitors.yaml (the next apply deletes it)")
        drift += 1
    for label, dash in dashes:
        d = find_dashboard(dd, dash["title"])
        if d is None:
            say(f"  MISSING  {label} '{dash['title']}'")
            drift += 1
        else:
            say(f"  OK       {label} https://app.{dd.site}{d.get('url', '')}")
    return 1 if drift else 0


def span_seconds(widget: dict) -> int:
    live = str((widget.get("time") or {}).get("live_span") or "")
    m = SPAN_RE.match(live)
    if not live:
        return DEFAULT_SPAN_S
    if not m:
        raise RuntimeError(f"widget '{widget.get('title')}': live_span '{live}' is not <n>m, <n>h or <n>d")
    return int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]


def monitor_span(query: str) -> int:
    """The window a monitor evaluates: max(last_5m):... or ....last("5m")."""
    m = re.search(r'last(?:_|\(")([0-9]+[mhd])', query)
    if not m:
        raise RuntimeError(f"cannot read the evaluation window of '{query[:60]}'")
    return span_seconds({"time": {"live_span": m.group(1)}})


def scalar(dd: Datadog, query: dict, span: int, now: dt.datetime) -> tuple[bool, dict[str, float]]:
    """One query through POST /api/v2/query/scalar, the API the dashboard widgets use. Returns (grouped, values):
    grouped when the answer has a kube_cluster_name column, values per cluster then, else under ''. A null cell
    is no data.

    N/A is Datadog's group value for a series without the tag, and the only one a room-wide rollup has: the
    Clusters reporting tile's count_not_null(... by {kube_cluster_name}) answers a kube_cluster_name column holding
    [["N/A"]] next to the count (read in Whitney's sandbox org on 2026-11-05, #485). It names no cluster, so an
    answer whose groups are all N/A is the ungrouped value, and an N/A row beside real clusters is dropped."""
    q = {**query, "name": "q"}
    if q.get("data_source", "metrics") == "metrics":
        q.setdefault("aggregator", "avg")
    to_ms = int(now.timestamp() * 1000)
    body = {"data": {"type": "scalar_request", "attributes": {
        "from": to_ms - span * 1000, "to": to_ms, "queries": [q], "formulas": [{"formula": "q"}]}}}
    resp = dd.call("POST", "/api/v2/query/scalar", body)
    cols = ((resp.get("data") or {}).get("attributes") or {}).get("columns")
    if cols is None:
        raise RuntimeError(f"scalar answer has no data.attributes.columns: {json.dumps(resp)[:200]}")
    groups = [c for c in cols if c.get("type") == "group" and c.get("name") == GROUP_BY]
    numbers = [c.get("values") or [] for c in cols if c.get("type") == "number"]
    nums = numbers[0] if numbers else []
    names = [g[0] if isinstance(g, list) and g else g for g in (groups[0].get("values") or [])] if groups else []
    if not groups or (names and all(n == NO_GROUP for n in names)):
        return False, ({"": float(nums[0])} if nums and nums[0] is not None else {})
    out = {}
    for name, v in zip(names, nums):
        if isinstance(name, str) and name != NO_GROUP and v is not None:
            out[name] = float(v)
    return True, out


def data_check(dd: Datadog, defs: dict, dashes: list[tuple[str, dict]], clusters: list[str], now: dt.datetime,
               say=print) -> int:
    """Read-only: does every query return data for every named cluster (#706)? Exit 1 on any blank.

    A blank is a wrong metric, tag or log name, a cluster that is not shipping, or (for traces and spend) nobody
    having chatted with that cluster inside the window: drive one /chat on each cluster before running it."""
    blank = 0

    def need(what: str, grouped: bool, got: dict) -> None:
        nonlocal blank
        missing = [c for c in clusters if c not in got] if grouped else ([] if got else ["(no value)"])
        if missing:
            say(f"  NO DATA  {what}: {', '.join(missing)}")
            blank += 1
        else:
            say(f"  DATA     {what}")

    live = {key_of(m): m for m in managed_monitors(dd, group_states=True) if key_of(m)}
    for m in defs["monitors"]:
        if m.get("signal"):
            sig = {k: v for k, v in m["signal"].items() if k != SIGNAL_WINDOW}
            window = m["signal"].get(SIGNAL_WINDOW)
            span = span_seconds({"time": {"live_span": window}}) if window else monitor_span(m["query"])
            need(f"monitor {m['key']} (its signal{f', last {window}' if window else ''})", *scalar(dd, sig, span, now))
            continue
        lm = live.get(m["key"])
        if lm is None:
            say(f"  MISSING  monitor {m['key']}: not in the org (run fleet.sh monitors --apply)")
            blank += 1
            continue
        if m.get("scope") == ORG_SCOPE:
            # One alert for the org (#810): fed when the whole monitor is in a state other than No Data. It cannot say
            # which cluster is feeding it; verify/agent_obs_flow.py chat does that per cluster.
            st = lm.get("overall_state", "?")
            need(f"monitor {m['key']} ({st}, the whole org: no cluster tag)", False,
                 {"": 1.0} if st in ("OK", "Warn", "Alert") else {})
            continue
        # Keyed kube_cluster_name:<name>. No Data, Unknown and Skipped all mean the query answered nothing for it.
        groups = ((lm.get("state") or {}).get("groups") or {}).items()
        evaluated = {str(g.get("name") or k).split(":", 1)[-1]: 1.0 for k, g in groups
                     if g.get("status") in ("OK", "Warn", "Alert")}
        need(f"monitor {m['key']} ({lm.get('overall_state', '?')})", True, evaluated)
    for label, dash in dashes:
        if label not in DATA_DASHBOARDS:
            continue
        for w in dash.get("widgets") or []:
            d = w.get("definition") or {}
            for r in d.get("requests") or []:
                for q in r.get("queries") or []:
                    need(f"{label} / {d.get('title', d.get('type'))} / {q.get('name')}",
                         *scalar(dd, q, span_seconds(d), now))
    return 1 if blank else 0


def board_table(dash: dict) -> tuple[dict, dict]:
    """(widget definition, request) of the leaderboard's one per-cluster table."""
    tables = [(w.get("definition") or {}) for w in dash.get("widgets") or []
              if (w.get("definition") or {}).get("type") == "query_table"]
    if len(tables) != 1 or len(tables[0].get("requests") or []) != 1:
        raise RuntimeError(f"'{dash.get('title')}' must hold exactly one query_table with one request, "
                           f"holds {len(tables)} table(s)")
    return tables[0], tables[0]["requests"][0]


def table_shape(dash: dict) -> dict:
    """What decides the leaderboard's cells, comparable between the repo and the org: the window, each query's
    source, filter, aggregator and grouping, and each column's formula, title and green rule. Whitespace aside."""
    d, req = board_table(dash)
    queries = {}
    for q in req.get("queries") or []:
        src = q.get("data_source", "metrics")
        queries[q.get("name")] = (src, norm(query_text(q)), q.get("aggregator") if src == "metrics" else
                                  tuple(g.get("facet") for g in q.get("group_by") or []))
    columns = [(f.get("formula"), f.get("alias"),
                tuple((c.get("comparator"), float(c.get("value")), c.get("palette"))
                      for c in f.get("conditional_formats") or []))
               for f in req.get("formulas") or []]
    return {"window": (d.get("time") or {}).get("live_span"), "queries": queries, "columns": columns}


def table_drift(live: dict, repo: dict) -> list[str]:
    """How the org's leaderboard table differs from leaderboard.yaml. Empty is the same board."""
    try:
        have = table_shape(live)
    except RuntimeError as e:
        return [f"the org's leaderboard: {e}"]
    want = table_shape(repo)
    out = []
    if have["window"] != want["window"]:
        out.append(f"window {have['window']} in the org, {want['window']} in leaderboard.yaml")
    for name in sorted(set(want["queries"]) | set(have["queries"]), key=str):
        if name not in have["queries"]:
            out.append(f"query {name} is in leaderboard.yaml, not in the org")
        elif name not in want["queries"]:
            out.append(f"query {name} is in the org, not in leaderboard.yaml")
        elif have["queries"][name] != want["queries"][name]:
            out.append(f"query {name} differs: the org has {have['queries'][name]}")
    if have["columns"] != want["columns"]:
        out.append(f"columns differ: the org has {[c[1] or c[0] for c in have['columns']]} and its green rules, "
                   f"leaderboard.yaml {[c[1] or c[0] for c in want['columns']]}")
    return out


def table_scalar(dd: Datadog, req: dict, span: int, now: dt.datetime) -> dict[str, dict[str, float | None]]:
    """The table's whole request in one POST /api/v2/query/scalar, every query and formula together, which is how
    query_table joins its metrics, logs and spans on kube_cluster_name. Returns {cluster: {formula: value}}."""
    queries = []
    for q in req["queries"]:
        q = dict(q)
        if q.get("data_source", "metrics") == "metrics":
            q.setdefault("aggregator", "avg")
        queries.append(q)
    to_ms = int(now.timestamp() * 1000)
    body = {"data": {"type": "scalar_request", "attributes": {
        "from": to_ms - span * 1000, "to": to_ms, "queries": queries,
        "formulas": [{"formula": f["formula"]} for f in req["formulas"]]}}}
    resp = dd.call("POST", "/api/v2/query/scalar", body)
    cols = ((resp.get("data") or {}).get("attributes") or {}).get("columns")
    if cols is None:
        raise RuntimeError(f"scalar answer has no data.attributes.columns: {json.dumps(resp)[:200]}")
    if not cols:
        return {}
    groups = [c for c in cols if c.get("type") == "group" and c.get("name") == GROUP_BY]
    if not groups:
        raise RuntimeError(f"the joined table answered without a {GROUP_BY} column, so it has no row per cluster: "
                           f"{[c.get('name') for c in cols]}")
    numbers = {c.get("name"): c.get("values") or [] for c in cols if c.get("type") == "number"}
    absent = [f["formula"] for f in req["formulas"] if f["formula"] not in numbers]
    if absent:
        raise RuntimeError(f"the joined table answered no column for {absent}; it answered {sorted(numbers)}")
    rows: dict[str, dict[str, float | None]] = {}
    for i, g in enumerate(groups[0].get("values") or []):
        name = g[0] if isinstance(g, list) and g else g
        if isinstance(name, str):
            rows[name] = {f: (float(v[i]) if i < len(v) and v[i] is not None else None) for f, v in numbers.items()}
    return rows


def filled(formula: dict, value: float | None) -> bool:
    """Is the cell what the room reads as done? Green under the column's conditional format, or, for a column with
    no green rule (the bill), a value above 0."""
    if value is None:
        return False
    greens = [c for c in formula.get("conditional_formats") or [] if "green" in str(c.get("palette", ""))]
    if not greens:
        return value > 0
    return any(COMPARATORS[c["comparator"]](value, float(c["value"])) for c in greens)


def board_check(dd: Datadog, dashes: list[tuple[str, dict]], clusters: list[str], now: dt.datetime,
                say=print) -> int:
    """Read-only (#489, #862): the leaderboard is in the org with this repo's table, and every column of that table
    is filled for every named cluster over the widget's window. Exit 1 on a missing or drifted board or a blank
    cell. Run it after walking each named cluster through challenges 1 to 6 inside that window."""
    dash = dict(dashes)[BOARD_LABEL]
    found = find_dashboard(dd, dash["title"])
    if found is None:
        say(f"  MISSING  {BOARD_LABEL} '{dash['title']}': not in the org (run fleet.sh monitors --apply)")
        return 1
    live = dd.call("GET", f"/api/v1/dashboard/{found['id']}")
    drift = table_drift(live, dash)
    for line in drift:
        say(f"  DRIFT    {BOARD_LABEL}: {line}")
    if drift:
        say("  the org's table is not leaderboard.yaml's, so its cells say nothing about the repo's; re-apply first")
        return 1
    say(f"  OK       {BOARD_LABEL} https://app.{dd.site}{found.get('url') or live.get('url', '')}")
    widget, req = board_table(dash)
    rows = table_scalar(dd, req, span_seconds(widget), now)
    blank = 0
    for f in req["formulas"]:
        column = f.get("alias") or f["formula"]
        values = {c: (rows.get(c) or {}).get(f["formula"]) for c in clusters}
        empty = [c for c in clusters if not filled(f, values[c])]
        if empty:
            say(f"  BLANK    {BOARD_LABEL} / {column}: "
                + ", ".join(f"{c} ({'no value' if values[c] is None else f'{values[c]:g}'})" for c in empty))
            blank += 1
        else:
            say(f"  FILLED   {BOARD_LABEL} / {column}")
    return 1 if blank else 0


def main(argv=None, keys=read_keys, http=None, now=None, env=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True, help="AWS profile that can read the instructor org secret")
    p.add_argument("--region", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="validate with Datadog, then write (default: dry run)")
    mode.add_argument("--check", action="store_true", help="read-only: compare the live org with this repo")
    mode.add_argument("--data", action="store_true",
                      help="read-only: every monitor and fleet-dashboard query returns data for every --cluster")
    mode.add_argument("--board", action="store_true",
                      help="read-only: the leaderboard is applied and every column is filled for every --cluster")
    p.add_argument("--cluster", action="append", default=[],
                   help="a kube_cluster_name that must be shipping, for --data, or that has walked challenges 1 to 6, "
                        "for --board (repeatable, at least one)")
    p.add_argument("--session", help="START/END in ISO-8601 UTC; session monitors are muted outside it")
    p.add_argument("--notify", action="append", default=[],
                   help="a Datadog handle to page, e.g. @someone@example.com (repeatable; default: none)")
    a = p.parse_args(argv)
    env = os.environ if env is None else env

    defs, dashes = load_monitors(), load_dashboards()
    problems = validate_monitors(defs)
    for _, dash in dashes:
        problems += validate_dashboard(dash, defs.get("cluster_filter", ""))
    try:
        session = parse_session(a.session)
    except ValueError as e:
        problems.append(str(e))
    bad_handles = [h for h in a.notify if not h.startswith("@")]
    if bad_handles:
        problems.append(f"--notify handles must start with @: {bad_handles}")
    flt_prefix = str(defs.get("cluster_filter", "")).split(":", 1)[-1].rstrip("*")
    if a.data and not a.cluster:
        problems.append("--data needs every cluster that should be shipping, one --cluster each")
    if a.board and not a.cluster:
        problems.append("--board needs every cluster that has walked challenges 1 to 6, one --cluster each")
    if a.cluster and not (a.data or a.board):
        problems.append("--cluster only means something with --data or --board")
    outside = [c for c in a.cluster if not c.startswith(flt_prefix)]
    if outside:
        problems.append(f"--cluster {outside} is outside the queries' filter {defs.get('cluster_filter')}, "
                        "so it could never fill")
    if problems:
        print(f"REFUSING: {len(problems)} problem(s) in the definitions", file=sys.stderr)
        for pr in problems:
            print(f"  - {pr}", file=sys.stderr)
        return 1

    label = ("APPLY" if a.apply else "CHECK" if a.check else "DATA" if a.data else "BOARD" if a.board
             else "DRY-RUN")
    print(f"[{label}] {len(defs['monitors'])} monitor(s) and dashboards "
          + ", ".join(f"'{d['title']}'" for _, d in dashes))
    if not (a.apply or a.check or a.data or a.board):
        for m in defs["monitors"]:
            print(f"  P{m.get('priority', '-')} {m['key']:<22} {m['type']:<12} {m['name']}")
        windows = mute_windows(session, now or dt.datetime.now(dt.timezone.utc))
        print(f"  session monitors muted in {len(windows)} window(s): "
              + ("indefinitely, no --session given" if session is None
                 else f"outside {session[0]:%Y-%m-%dT%H:%MZ}/{session[1]:%Y-%m-%dT%H:%MZ}"))
        print(f"  notify: {' '.join(a.notify) or 'nobody (the dashboard and the Monitors page only)'}")
        print("  dry run: nothing read or written. Re-run with --apply.")
        return 0

    if a.apply and not env.get(APP_KEY_ENV):
        print(f"FAILED: --apply needs {APP_KEY_ENV}, an unscoped application key from Whitney's user in the sandbox "
              "org; the key in watch-it-burn/datadog is read-only", file=sys.stderr)
        return 1
    prefix = env.get("WIB_DD_POOL_PREFIX", "Datadog")
    try:
        api, app, site = keys(a.profile, a.region)
        dd = Datadog(site, api, env[APP_KEY_ENV] if a.apply else app, http=http)
        org = org_name(dd)
        if not org.startswith(prefix):
            print(f"FAILED: the keys reach org '{org}', not the sandbox org (prefix {prefix}); nothing written",
                  file=sys.stderr)
            return 1
        print(f"  instructor org: {org} ({site}), api key from {SECRET_ID}"
              + (f", application key from {APP_KEY_ENV}" if a.apply else ""))
        if a.check:
            return check(dd, defs, dashes)
        if a.data:
            print(f"  every query must answer for: {', '.join(a.cluster)}")
            return data_check(dd, defs, dashes, a.cluster, now or dt.datetime.now(dt.timezone.utc))
        if a.board:
            print(f"  every leaderboard column must be filled for: {', '.join(a.cluster)}")
            return board_check(dd, dashes, a.cluster, now or dt.datetime.now(dt.timezone.utc))
        return apply(dd, defs, dashes, a.notify, session, now or dt.datetime.now(dt.timezone.utc))
    except RuntimeError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
