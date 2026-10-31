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
                       source without the bad-news filter) answer for each cluster; every query on the fleet
                       dashboard answers for each cluster over its widget's window. Exit 1 on any blank.

The org. For KubeCon NA 2026 the instructor org is Whitney's sandbox org: Datadog no longer issues per-student
orgs, so both clusters ship there (#629, #454), and its keys are Secrets Manager watch-it-burn/datadog (the secret
fleet.sh gives the clusters). The org name must start with WIB_DD_POOL_PREFIX (default "Datadog", as in
verify/datadog-orgs.sh and room_view.py), so the monitors are never written into, or checked against, some other
org. The application key in that secret is read-only, which --check needs and --apply cannot use: the apply
writes monitors, downtimes and dashboards. --apply therefore takes the application key from
WIB_FLEET_MONITORS_APP_KEY in this command's environment, a key Whitney issues from her own user. It must be
unscoped: Datadog refuses log monitors created with a scoped one. Key values are never printed.

The session window. The no-traces monitor only means something while students are at their keyboards; at
any other time an idle cluster is a correct cluster. Monitors marked `session: true` are muted by downtimes
this script owns: with --session START/END they are muted until START and again from END, and with no
window they are muted indefinitely, so applying outside an event never pages anybody. Every apply cancels
the downtimes the previous apply created (they carry the marker below in their message) before it creates
its own, so the window can be moved by re-running.

Usage (fleet.sh passes the profile and region; it is the normal way in):
    fleet.sh monitors                                                   # dry run
    WIB_FLEET_MONITORS_APP_KEY=<key> fleet.sh monitors --apply --session 2026-09-08T16:00Z/2026-09-08T19:30Z
    fleet.sh monitors --check
    fleet.sh monitors --data --cluster burritobot-public --cluster burritobot-private   # after a /chat on each
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
TYPES = ("metric alert", "query alert", "log alert")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# The dashboards --data reads. The leaderboard counts challenge outcomes, so it is blank until the room plays.
DATA_DASHBOARDS = ("fleet dashboard",)
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
        if flt and flt not in q:
            problems.append(f"{where}: query is not filtered to {flt}")
        if m["type"] == "log alert":
            if f'.by("{GROUP_BY}")' not in q:
                problems.append(f'{where}: log query is not grouped .by("{GROUP_BY}")')
        elif not re.search(r"\bby \{" + GROUP_BY + r"\}", q):
            problems.append(f"{where}: metric query is not grouped by {{{GROUP_BY}}}")
        th = (m["options"] or {}).get("thresholds") or {}
        if "critical" not in th:
            problems.append(f"{where}: options.thresholds.critical is required")
        else:
            tail = re.search(r"(<=|>=|<|>|==)\s*(-?[0-9.]+)\s*$", q)
            if not tail:
                problems.append(f"{where}: query does not end in a comparison with a threshold")
            elif float(tail.group(2)) != float(th["critical"]):
                problems.append(f"{where}: query threshold {tail.group(2)} != options.thresholds.critical {th['critical']}")
        problems += validate_signal(where, m, flt)
        opts = m["options"]
        if opts.get("notify_no_data") and not opts.get("no_data_timeframe"):
            problems.append(f"{where}: notify_no_data without no_data_timeframe")
        if "{{" + GROUP_BY + ".name}}" not in m["message"]:
            problems.append(f"{where}: message does not name the cluster ({{{{{GROUP_BY}.name}}}})")
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


def query_text(q: dict) -> str:
    """The filter string of a dashboard query: a metric query carries it in `query`, a logs query in
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
                if q.get("data_source") == "logs" and GROUP_BY not in {g.get("facet") for g in q.get("group_by") or []}:
                    problems.append(f"dashboard widget {i} query {q.get('name')}: logs query is not grouped by {GROUP_BY}")
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
    is no data."""
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
    if not groups:
        return False, ({"": float(nums[0])} if nums and nums[0] is not None else {})
    out = {}
    for g, v in zip(groups[0].get("values") or [], nums):
        name = g[0] if isinstance(g, list) and g else g
        if isinstance(name, str) and v is not None:
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
            need(f"monitor {m['key']} (its signal)", *scalar(dd, m["signal"], monitor_span(m["query"]), now))
            continue
        lm = live.get(m["key"])
        if lm is None:
            say(f"  MISSING  monitor {m['key']}: not in the org (run fleet.sh monitors --apply)")
            blank += 1
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


def main(argv=None, keys=read_keys, http=None, now=None, env=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True, help="AWS profile that can read the instructor org secret")
    p.add_argument("--region", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="validate with Datadog, then write (default: dry run)")
    mode.add_argument("--check", action="store_true", help="read-only: compare the live org with this repo")
    mode.add_argument("--data", action="store_true",
                      help="read-only: every monitor and fleet-dashboard query returns data for every --cluster")
    p.add_argument("--cluster", action="append", default=[],
                   help="a kube_cluster_name that must be shipping, for --data (repeatable, at least one)")
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
    if a.cluster and not a.data:
        problems.append("--cluster only means something with --data")
    outside = [c for c in a.cluster if not c.startswith(flt_prefix)]
    if outside:
        problems.append(f"--cluster {outside} is outside the queries' filter {defs.get('cluster_filter')}, "
                        "so it could never fill")
    if problems:
        print(f"REFUSING: {len(problems)} problem(s) in the definitions", file=sys.stderr)
        for pr in problems:
            print(f"  - {pr}", file=sys.stderr)
        return 1

    label = "APPLY" if a.apply else "CHECK" if a.check else "DATA" if a.data else "DRY-RUN"
    print(f"[{label}] {len(defs['monitors'])} monitor(s) and dashboards "
          + ", ".join(f"'{d['title']}'" for _, d in dashes))
    if not (a.apply or a.check or a.data):
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
        return apply(dd, defs, dashes, a.notify, session, now or dt.datetime.now(dt.timezone.utc))
    except RuntimeError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
