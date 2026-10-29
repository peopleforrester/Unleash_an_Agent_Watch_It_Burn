# ABOUTME: Load the room's read-only burritobot-public view (#665) into Whitney's sandbox Datadog org as a public shared
# ABOUTME: dashboard, after proving offline that every query is fenced to attackme. Dry run by default.
"""Build, share and check the room's read-only Datadog view.

The definition is room_view.yaml next to this file: the dashboard body and the public share's settings. Nothing is
edited by hand in the Datadog UI, because the next apply overwrites it.

    dry run (default)  validate the definition offline and print the plan; read nothing, write nothing.
    --json             print the dashboard body as JSON, for Datadog's "Import dashboard JSON" when the view is built
                       by hand in the UI. Validated first, like every mode.
    --apply            write the dashboard (found by title, so its id survives re-applies), then create or update its
                       public share, and record the share in share.json next to this file. Prints the public URL.
    --check            read-only: the dashboard holds this repo's queries, the share is open, active, unexpired and
                       lets the viewer select nothing, and its public URL answers with no credentials. Exit 1 on any
                       drift, and when share.json is absent (the view has not been built).

The org. Whitney's sandbox org, whose keys are Secrets Manager watch-it-burn/datadog (the secret fleet.sh gives the
community and admin clusters). The org name must start with WIB_DD_POOL_PREFIX (default "Datadog", as in
verify/datadog-orgs.sh), so the view is never written into some other org. The application key in that secret is
read-only, which --check needs and --apply cannot use: sharing a dashboard takes dashboards_write and
dashboards_public_share. --apply therefore takes the application key from WIB_ROOM_VIEW_APP_KEY in this command's
environment, a key Whitney issues from her own user (the share's author is the key's user, and a shared dashboard
stops showing data if its author is deactivated). Key values are never printed.

The fence. A shared dashboard runs its queries with its author's permissions, and the author can read the whole
sandbox org. validate() is what keeps the page to attackme: metric queries only, each one's filter carrying
kube_cluster_name:burritobot-public and no other cluster, no LLM Observability metric (ml_obs.* carry no cluster
tag), grouped by nothing but span name, only widget types Datadog renders on a shared dashboard, no template
variables, and a share that lets the viewer select neither a time nor a variable.

Usage:
    python3 infra/datadog-room/room_view.py                                    # dry run
    python3 infra/datadog-room/room_view.py --json > /tmp/room-view.json        # for the UI
    WIB_ROOM_VIEW_APP_KEY=<key> python3 infra/datadog-room/room_view.py --profile accen-dev --region us-west-2 --apply
    python3 infra/datadog-room/room_view.py --profile accen-dev --region us-west-2 --check
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "datadog-fleet"))
from fleet_monitors import SECRET_ID, Datadog, find_dashboard, norm, read_keys  # noqa: E402

DEF_FILE = HERE / "room_view.yaml"
SHARE_FILE = HERE / "share.json"
CLUSTER_TAG = "kube_cluster_name:burritobot-public"
APP_KEY_ENV = "WIB_ROOM_VIEW_APP_KEY"
# Datadog's list of widgets a shared dashboard renders (docs.datadoghq.com/dashboards/sharing/shared_dashboards,
# read 2026-10-29), narrowed to the ones this view uses. Anything else shows no data when shared, silently.
WIDGET_TYPES = ("note", "query_value", "timeseries", "toplist")
# Group by span name only: a group on a content attribute would print attendee text on a public page.
GROUP_KEYS = ("span.name",)
LIVE_SPANS = ("15m", "1h", "4h", "1d", "2d", "1w", "1mo", "3mo")


def load(path: pathlib.Path = DEF_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def filter_tags(query: str) -> list[str]:
    """The tags inside a metric query's {...} filter, '' for none. One filter per metric in the query."""
    return [t.strip() for f in re.findall(r"\{([^}]*)\}", query.split(" by ")[0]) for t in f.split(",") if t.strip()]


def group_keys(query: str) -> list[str]:
    m = re.search(r"\bby \{([^}]*)\}", query)
    return [k.strip() for k in m.group(1).split(",")] if m else []


def queries(dash: dict):
    """(widget number, query) for every query on the dashboard."""
    for i, w in enumerate(dash.get("widgets") or [], 1):
        for r in (w.get("definition") or {}).get("requests") or []:
            for q in r.get("queries") or []:
                yield i, q


def validate(defs: dict, now: dt.datetime) -> list[str]:
    """Everything that would put another cluster's data, or attendee text, on a public page. Empty is good."""
    problems: list[str] = []
    dash, share = defs.get("dashboard") or {}, defs.get("share") or {}
    for k in ("title", "layout_type", "widgets"):
        if not dash.get(k):
            problems.append(f"dashboard: missing {k}")
    if dash.get("layout_type") not in ("ordered", "free"):
        problems.append(f"dashboard: layout_type '{dash.get('layout_type')}' is not ordered or free")
    if dash.get("template_variables"):
        problems.append("dashboard: template variables let a viewer widen the cluster filter; remove them")
    for i, w in enumerate(dash.get("widgets") or [], 1):
        d = w.get("definition") or {}
        if d.get("type") not in WIDGET_TYPES:
            problems.append(f"widget {i}: type '{d.get('type')}' is not one of {WIDGET_TYPES}")
        for r in d.get("requests") or []:
            names = {q.get("name") for q in r.get("queries") or []}
            if not r.get("queries"):
                problems.append(f"widget {i}: a request with no formula queries")
            for f in r.get("formulas") or []:
                refs = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", f.get("formula", "")))
                if not refs <= names:
                    problems.append(f"widget {i}: formula '{f.get('formula')}' names a query that does not exist")
    for i, q in queries(dash):
        where = f"widget {i} query {q.get('name')}"
        if q.get("data_source") != "metrics":
            problems.append(f"{where}: data source '{q.get('data_source')}' is not metrics")
            continue
        text = q.get("query", "")
        tags = filter_tags(text)
        if not tags:
            problems.append(f"{where}: no tag filter")
        elif not all(CLUSTER_TAG in [t.strip() for t in f.split(",")]
                     for f in re.findall(r"\{([^}]*)\}", text.split(" by ")[0])):
            problems.append(f"{where}: not filtered to {CLUSTER_TAG}")
        if [t for t in tags if t.startswith("kube_cluster_name:") and t != CLUSTER_TAG]:
            problems.append(f"{where}: names a cluster other than burritobot-public")
        if [t for t in tags if t.startswith("!") or t.startswith("-")]:
            problems.append(f"{where}: an exclusion filter; this view only includes")
        if "ml_obs." in text:
            problems.append(f"{where}: ml_obs.* metrics carry no cluster tag, so they cannot be fenced to attackme")
        bad = [k for k in group_keys(text) if k not in GROUP_KEYS]
        if bad:
            problems.append(f"{where}: grouped by {bad}; only {GROUP_KEYS} is allowed")
    if share.get("share_type") != "open":
        problems.append(f"share: share_type '{share.get('share_type')}' is not open (no login, no invite)")
    if share.get("global_time_selectable_enabled") is not False:
        problems.append("share: global_time_selectable_enabled must be false")
    if share.get("selectable_template_vars"):
        problems.append("share: selectable_template_vars must be empty")
    if (share.get("global_time") or {}).get("live_span") not in LIVE_SPANS:
        problems.append(f"share: global_time.live_span must be one of {LIVE_SPANS}")
    try:
        exp = dt.datetime.fromisoformat(str(share.get("expiration", "")).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            problems.append("share: expiration must end in Z")
        elif exp <= now:
            problems.append(f"share: expiration {share['expiration']} has passed")
    except ValueError:
        problems.append("share: expiration must be an ISO-8601 UTC time, so the link dies after the talk")
    return problems


def dashboard_type(dash: dict) -> str:
    return "custom_timeboard" if dash["layout_type"] == "ordered" else "custom_screenboard"


def share_body(defs: dict, dashboard_id: str) -> dict:
    return {**defs["share"], "dashboard_id": dashboard_id, "dashboard_type": dashboard_type(defs["dashboard"]),
            "title": defs["dashboard"]["title"]}


def live_queries(dash: dict) -> list[str]:
    return [norm(q.get("query", "")) for _, q in queries(dash)]


def org_name(dd: Datadog) -> str:
    # /api/v2/current_user, not /api/v1/org: the sandbox org's read-only key answers that one 403 (#629).
    me = dd.call("GET", "/api/v2/current_user")
    return next((i["attributes"]["name"] for i in me.get("included", []) if i.get("type") == "orgs"), "?")


def fetch_public(url: str) -> int:
    """The status the public URL answers with, sent with no credentials at all, as a phone in the room would."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except urllib.error.URLError:
        return 0


def apply(dd: Datadog, defs: dict, share_file: pathlib.Path = SHARE_FILE, say=print) -> int:
    dash = defs["dashboard"]
    existing = find_dashboard(dd, dash["title"])
    if existing:
        out = dd.call("PUT", f"/api/v1/dashboard/{existing['id']}", dash)
        say(f"  dashboard updated: {dash['title']}")
    else:
        out = dd.call("POST", "/api/v1/dashboard", dash)
        say(f"  dashboard created: {dash['title']}")
    dash_id = str(out["id"])

    body = share_body(defs, dash_id)
    recorded = json.loads(share_file.read_text()) if share_file.exists() else {}
    live = None
    if recorded.get("token") and recorded.get("dashboard_id") == dash_id:
        try:
            live = dd.call("GET", f"/api/v1/dashboard/public/{recorded['token']}")
        except RuntimeError:
            say(f"  the recorded share {recorded['token']} is gone; sharing again")
    if live:
        upd = {k: v for k, v in body.items() if k not in ("dashboard_id", "dashboard_type")}
        upd["status"] = "active"
        shared = dd.call("PUT", f"/api/v1/dashboard/public/{recorded['token']}", upd)
        say("  public share updated")
    else:
        shared = dd.call("POST", "/api/v1/dashboard/public", body)
        say("  public share created")
    token, url = shared.get("token") or recorded.get("token"), shared.get("public_url") or recorded.get("public_url")
    if not (token and url):
        say("FAILED: Datadog's share answer carried no token or public_url")
        return 1
    share_file.write_text(json.dumps({"dashboard_id": dash_id, "token": token, "public_url": url}, indent=2) + "\n")
    say(f"  recorded in {share_file.name}; commit it so --check and the run-of-show can find the share")
    say(f"  room view (no login): {url}")
    say(f"  expires: {defs['share']['expiration']}")
    return 0


def check(dd: Datadog, defs: dict, now: dt.datetime, share_file: pathlib.Path = SHARE_FILE, public=fetch_public,
          say=print) -> int:
    if not share_file.exists():
        say(f"  MISSING  {share_file.name}: the room view has not been built (run --apply with {APP_KEY_ENV})")
        return 1
    rec = json.loads(share_file.read_text())
    drift = 0
    dash = defs["dashboard"]
    found = find_dashboard(dd, dash["title"])
    if found is None:
        say(f"  MISSING  dashboard '{dash['title']}'")
        return 1
    if str(found["id"]) != rec.get("dashboard_id"):
        say(f"  DRIFT    dashboard id {found['id']} is not the shared one in {share_file.name} ({rec.get('dashboard_id')})")
        drift += 1
    full = dd.call("GET", f"/api/v1/dashboard/{found['id']}")
    if live_queries(full) != live_queries(dash):
        say("  DRIFT    the live dashboard's queries differ from room_view.yaml (an edit in the UI?)")
        drift += 1
    if full.get("template_variables"):
        say("  DRIFT    the live dashboard has template variables")
        drift += 1
    try:
        sh = dd.call("GET", f"/api/v1/dashboard/public/{rec['token']}")
    except RuntimeError as e:
        say(f"  MISSING  public share {rec.get('token')}: {e}")
        return 1
    want = defs["share"]
    for k, ok in (("share_type", sh.get("share_type") == "open"),
                  ("status", sh.get("status") == "active"),
                  ("global_time_selectable_enabled", not sh.get("global_time_selectable_enabled")),
                  ("selectable_template_vars", not sh.get("selectable_template_vars")),
                  ("dashboard_id", str(sh.get("dashboard_id")) == str(found["id"]))):
        if not ok:
            say(f"  DRIFT    share {k} is {sh.get(k)!r}")
            drift += 1
    exp = sh.get("expiration")
    if not exp:
        say("  DRIFT    share has no expiration; it would outlive the talk")
        drift += 1
    else:
        when = dt.datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
        when = when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)
        if when <= now:
            say(f"  EXPIRED  share expired {exp}")
            drift += 1
        elif when > dt.datetime.fromisoformat(want["expiration"].replace("Z", "+00:00")):
            say(f"  DRIFT    share expires {exp}, later than room_view.yaml's {want['expiration']}")
            drift += 1
    status = public(rec["public_url"])
    if status != 200:
        say(f"  FAIL     {rec['public_url']} answered {status or 'nothing'} with no credentials")
        drift += 1
    if not drift:
        say(f"  OK       {rec['public_url']} is open, scoped to burritobot-public and answers with no login")
    return 1 if drift else 0


def main(argv=None, keys=read_keys, http=None, now=None, env=None, share_file: pathlib.Path = SHARE_FILE,
         public=fetch_public) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", help="AWS profile that can read watch-it-burn/datadog (--apply and --check)")
    p.add_argument("--region", help="its region (--apply and --check)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the dashboard and its public share")
    mode.add_argument("--check", action="store_true", help="read-only: compare the live view with this repo")
    mode.add_argument("--json", action="store_true", help="print the dashboard body for Datadog's JSON import")
    a = p.parse_args(argv)
    env = os.environ if env is None else env
    now = now or dt.datetime.now(dt.timezone.utc)

    defs = load()
    problems = validate(defs, now)
    if problems:
        print(f"REFUSING: {len(problems)} problem(s) in room_view.yaml", file=sys.stderr)
        for pr in problems:
            print(f"  - {pr}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(defs["dashboard"], indent=2))
        return 0
    label = "APPLY" if a.apply else "CHECK" if a.check else "DRY-RUN"
    print(f"[{label}] '{defs['dashboard']['title']}': {len(defs['dashboard']['widgets'])} widgets, "
          f"every query on {CLUSTER_TAG}, shared {defs['share']['share_type']} until {defs['share']['expiration']}")
    if not (a.apply or a.check):
        for i, q in queries(defs["dashboard"]):
            print(f"  widget {i}: {q['query']}")
        print("  dry run: nothing read or written. Re-run with --apply, or --json to build it by hand.")
        return 0
    if not (a.profile and a.region):
        print("FAILED: --apply and --check need --profile and --region (the account holding watch-it-burn/datadog)",
              file=sys.stderr)
        return 1
    if a.apply and not env.get(APP_KEY_ENV):
        print(f"FAILED: --apply needs {APP_KEY_ENV}, an application key from Whitney's user in the sandbox org with "
              "dashboards_write and dashboards_public_share; the key in watch-it-burn/datadog is read-only",
              file=sys.stderr)
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
        print(f"  org: {org} ({site}), api key from {SECRET_ID}"
              + (f", application key from {APP_KEY_ENV}" if a.apply else ""))
        if a.check:
            return check(dd, defs, now, share_file=share_file, public=public)
        return apply(dd, defs, share_file=share_file)
    except RuntimeError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
