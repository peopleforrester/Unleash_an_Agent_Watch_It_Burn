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

The keys are the instructor org's, from Secrets Manager watch-it-burn/datadog (the secret the pool loader
writes the admin-instructor row to and fleet.sh reads for dual shipping). The APP key must be unscoped:
Datadog refuses log monitors created with a scoped one. Key values are never printed.

The session window. The no-traces monitor only means something while students are at their keyboards; at
any other time an idle cluster is a correct cluster. Monitors marked `session: true` are muted by downtimes
this script owns: with --session START/END they are muted until START and again from END, and with no
window they are muted indefinitely, so applying outside an event never pages anybody. Every apply cancels
the downtimes the previous apply created (they carry the marker below in their message) before it creates
its own, so the window can be moved by re-running.

Usage (fleet.sh passes the profile and region; it is the normal way in):
    fleet.sh monitors                                                   # dry run
    fleet.sh monitors --apply --session 2026-09-08T16:00Z/2026-09-08T19:30Z
    fleet.sh monitors --check
    python3 infra/datadog-fleet/fleet_monitors.py --profile accen-dev --region us-west-2 [--apply|--check]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
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
SECRET_ID = "watch-it-burn/datadog"
MANAGED_TAG = "managed-by:wib-fleet-monitors"
KEY_TAG_PREFIX = "wib-monitor:"
SESSION_TAG = "window:session"
DOWNTIME_MARK = "[wib-fleet-monitors]"
GROUP_BY = "kube_cluster_name"
TYPES = ("metric alert", "query alert", "log alert")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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
        opts = m["options"]
        if opts.get("notify_no_data") and not opts.get("no_data_timeframe"):
            problems.append(f"{where}: notify_no_data without no_data_timeframe")
        if "{{" + GROUP_BY + ".name}}" not in m["message"]:
            problems.append(f"{where}: message does not name the cluster ({{{{{GROUP_BY}.name}}}})")
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


def managed_monitors(dd: Datadog) -> list[dict]:
    q = urllib.parse.urlencode({"monitor_tags": MANAGED_TAG})
    return dd.call("GET", f"/api/v1/monitor?{q}")


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


def main(argv=None, keys=read_keys, http=None, now=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True, help="AWS profile that can read the instructor org secret")
    p.add_argument("--region", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="validate with Datadog, then write (default: dry run)")
    mode.add_argument("--check", action="store_true", help="read-only: compare the live org with this repo")
    p.add_argument("--session", help="START/END in ISO-8601 UTC; session monitors are muted outside it")
    p.add_argument("--notify", action="append", default=[],
                   help="a Datadog handle to page, e.g. @someone@example.com (repeatable; default: none)")
    a = p.parse_args(argv)

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
    if problems:
        print(f"REFUSING: {len(problems)} problem(s) in the definitions", file=sys.stderr)
        for pr in problems:
            print(f"  - {pr}", file=sys.stderr)
        return 1

    label = "APPLY" if a.apply else "CHECK" if a.check else "DRY-RUN"
    print(f"[{label}] {len(defs['monitors'])} monitor(s) and dashboards "
          + ", ".join(f"'{d['title']}'" for _, d in dashes))
    if not (a.apply or a.check):
        for m in defs["monitors"]:
            print(f"  P{m.get('priority', '-')} {m['key']:<22} {m['type']:<12} {m['name']}")
        windows = mute_windows(session, now or dt.datetime.now(dt.timezone.utc))
        print(f"  session monitors muted in {len(windows)} window(s): "
              + ("indefinitely, no --session given" if session is None
                 else f"outside {session[0]:%Y-%m-%dT%H:%MZ}/{session[1]:%Y-%m-%dT%H:%MZ}"))
        print(f"  notify: {' '.join(a.notify) or 'nobody (the dashboard and the Monitors page only)'}")
        print("  dry run: nothing read or written. Re-run with --apply.")
        return 0

    try:
        api, app, site = keys(a.profile, a.region)
        dd = Datadog(site, api, app, http=http)
        org = dd.call("GET", "/api/v1/org").get("orgs", [{}])[0].get("name", "?")
        print(f"  instructor org: {org} ({site}), keys from {SECRET_ID}")
        if a.check:
            return check(dd, defs, dashes)
        return apply(dd, defs, dashes, a.notify, session, now or dt.datetime.now(dt.timezone.utc))
    except RuntimeError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
