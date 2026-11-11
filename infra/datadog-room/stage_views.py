#!/usr/bin/env python3
# ABOUTME: Saves the stage's Datadog views in Whitney's sandbox org (#648): one per challenge in presentation order on
# ABOUTME: the seeded traces, the PII refusal in APM, burritobot-public and burritobot-private, plus the seeds' retention filter.
"""The stage views and the seeds' retention filter (#648).

`verify/stage_traces.py seed` runs the stage's seeds on the private bot the Night Before and writes
`tmp/stage-traces.json`: each seed's session id (`wib-stage-<key>-<stamp>`, or the `-2` ask that made its slide's
call, #1210) and the query that finds it. This script turns that file into saved views, through the saved-view store
#792 found (`/api/v1/logs/views`, filtered by `?type=`; run 18770 read its create schema off Datadog's 400s, and run
20202 read the type and page lists the same way):

    WIB stage 1: Challenge 1, the CEO's secret                          c1-attack and c1-fixed, LLM Observability
    WIB stage 2: Challenge 2, the Kubernetes catch-all                  c2-attack and c2-fixed
    WIB stage 3: Challenge 3, prompt injection through a support ticket c3-attack and c3-fixed
    WIB stage 3b: Challenge 3, someone else's PII refused               c3-pii, APM Trace Explorer (type trace)
    WIB stage 4: Challenge 4, the poisoned weather tool                 c4-attack and c4-fixed
    WIB stage 5: burritobot-public                                      the room's bot, live
    WIB stage 6: burritobot-private                                     the presenters' bot, live

Datadog lists saved views by name, so the number keeps them in presentation order. A view keeps only a live range,
so the seed views are saved on Past 7 Days, which each view's session filter keeps to its own seeds, and the two
cluster views on Past 15 Minutes, as the run-of-show's room tab is.

`views --apply` lists the org's LLM Observability and APM views, then for each of the seven: a view of that name and
type with the same query, page and range is left alone; one with anything else is updated in place (PUT, the seeds
of a new run); none is created. It then lists again and passes only when all seven read back as built. A name
held by two views of one type is not touched, and the run fails. No view whose name does not start `WIB stage ` is
ever written, and nothing is deleted.

`retention --apply` makes the APM retention filter that keeps the seeds past Live Search's 15 minutes, which the
PII seed needs because a refused prompt has no gen_ai span and so lives in APM alone: query
`service:burritobot @session.id:wib-stage-*`, every span and every trace. One already there with that query and
those rates means nothing is written; one of its name with anything else is not edited and the run fails. A
retention filter applies as spans arrive, so it runs before `seed`.

The org is fenced as in fleet_monitors.py: /api/v2/current_user must name an org starting with WIB_DD_POOL_PREFIX
(default "Datadog"). The API key comes from Secrets Manager watch-it-burn/datadog. The application key is
WIB_FLEET_MONITORS_APP_KEY when set, else the same secret's write-app-key field, the unscoped key from Michael's user
in the sandbox org; the secret's read-only app-key gets 403 on both stores. Key values are never printed.

Usage:
    python3 infra/datadog-room/stage_views.py views                                     # dry run: nothing read
    python3 infra/datadog-room/stage_views.py retention --profile accen-dev --region us-west-2 --apply
    python3 infra/datadog-room/stage_views.py views --profile accen-dev --region us-west-2 --list
    python3 infra/datadog-room/stage_views.py views --profile accen-dev --region us-west-2 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
from fleet_monitors import APP_KEY_ENV, SECRET_ID, Datadog, org_name, read_keys  # noqa: E402

TRACES = REPO / "tmp" / "stage-traces.json"
VIEWS_PATH = "/api/v1/logs/views"
PREFIX = "WIB stage "
LLMOBS = ("llmobs", "llm_obs_explorer")  # LLM Observability's trace list (#792)
APM = ("trace", "traces")  # APM Trace Explorer, from the store's own type and page lists (run 20202)
ML_APP = "burritobot"
SERVICE = "burritobot"  # guard-proxy's service, which stamps session.id on its /chat root span
SEED_RANGE_MS = 7 * 24 * 3600 * 1000  # Past 7 Days: the seeds are sent the Night Before
LIVE_RANGE_MS = 15 * 60 * 1000  # Past 15 Minutes, the room tab's range
TAG = "wib:stage-traces"

# Presentation order: the run-of-show's segment 2 to 5 headings, then the two live tabs.
CHALLENGES = (
    ("1", "Challenge 1, the CEO's secret", ("c1-attack", "c1-fixed")),
    ("2", "Challenge 2, the Kubernetes catch-all", ("c2-attack", "c2-fixed")),
    ("3", "Challenge 3, prompt injection through a support ticket", ("c3-attack", "c3-fixed")),
    ("4", "Challenge 4, the poisoned weather tool", ("c4-attack", "c4-fixed")),
)
PII_KEY, PII_NAME = "c3-pii", "3b: Challenge 3, someone else's PII refused"
CLUSTERS = (("5", "burritobot-public"), ("6", "burritobot-private"))

RETENTION_NAME = "WIB stage seeds (#648)"
RETENTION_QUERY = f"service:{SERVICE} @session.id:wib-stage-*"
RETENTION_PATH = "/api/v2/apm/config/retention-filters"


# ---- the views: pure, offline --------------------------------------------------------------------------

def sessions_of(traces: dict) -> dict[str, str]:
    """Each seed's session from the seed's views file, refusing a file that lacks one the views need."""
    rows = traces.get("views") if isinstance(traces, dict) else None
    if not isinstance(rows, list):
        raise ValueError("the traces file has no views list: run verify/stage_traces.py seed first")
    out = {r["key"]: r["session"] for r in rows if isinstance(r, dict) and r.get("key") and r.get("session")}
    need = [k for _, _, keys in CHALLENGES for k in keys] + [PII_KEY]
    missing = [k for k in need if not out.get(k, "").startswith(f"wib-stage-{k}-")]
    if missing:
        raise ValueError(f"the traces file has no wib-stage session for {', '.join(missing)}")
    return out


def wanted(traces: dict) -> list[dict]:
    """The seven views, in presentation order, each the body the store's create validates."""
    sess = sessions_of(traces)
    out = []
    for n, title, keys in CHALLENGES:
        q = f"ml_app:{ML_APP} session_id:({' OR '.join(sess[k] for k in keys)})"
        out.append(body(f"{PREFIX}{n}: {title}", LLMOBS, q, SEED_RANGE_MS))
        if n == "3":
            out.append(body(PREFIX + PII_NAME, APM, f"service:{SERVICE} @session.id:{sess[PII_KEY]}", SEED_RANGE_MS))
    for n, cluster in CLUSTERS:
        out.append(body(f"{PREFIX}{n}: {cluster}", LLMOBS, f"ml_app:{ML_APP} k8s.cluster.name:{cluster}",
                        LIVE_RANGE_MS))
    return out


def body(name: str, kind: tuple[str, str], query: str, interval_ms: int) -> dict:
    return {"name": name, "type": kind[0], "page": kind[1], "search": query, "timerange": {"interval": interval_ms},
            "options": {}, "facets": [], "tags": [TAG]}


def interval_of(view: dict) -> int | None:
    """The listing reads the range back as interval_ms; the create takes interval."""
    tr = view.get("timerange") or {}
    return tr.get("interval_ms", tr.get("interval"))


def same(view: dict, want: dict) -> bool:
    return (view.get("search") == want["search"] and view.get("page") == want["page"]
            and interval_of(view) == want["timerange"]["interval"])


def plan(existing: list[dict], want: dict) -> tuple[str, dict | None]:
    """('present', view) | ('update', view) | ('conflict', view) | ('create', None) for one wanted view."""
    named = [v for v in existing if v.get("name") == want["name"] and v.get("type") == want["type"]]
    if len(named) > 1:
        return "conflict", named[0]
    if named:
        return ("present" if same(named[0], want) else "update"), named[0]
    return "create", None


def describe(view: dict) -> str:
    return (f"id {view.get('id')}: '{view.get('name')}' [type={view.get('type')}, page={view.get('page')}, "
            f"range {interval_of(view)} ms, query '{view.get('search')}']")


def view_url(site: str, view: dict) -> str:
    path = "llm/traces" if view.get("type") == LLMOBS[0] else "apm/traces"
    return f"https://app.{site}/{path}?saved-view-id={view.get('id')}"


# ---- the views: the org --------------------------------------------------------------------------------

def list_views(dd: Datadog) -> list[dict]:
    out = []
    for kind in (LLMOBS[0], APM[0]):
        data = dd.call("GET", f"{VIEWS_PATH}?type={kind}")
        if not isinstance(data, dict) or not isinstance(data.get("logs_views"), list):
            raise ValueError(f"no logs_views list in the answer for type {kind}")
        # The filter is Datadog's; the type test is ours, so a listing that returns more never reaches a decision.
        out += [v for v in data["logs_views"] if v.get("type") == kind]
    return out


def apply_views(dd: Datadog, wants: list[dict], write: bool, say=print) -> int:
    existing = list_views(dd)
    ours = sum(1 for v in existing if str(v.get("name", "")).startswith(PREFIX))
    say(f"  {len(existing)} LLM Observability and APM saved view(s), {ours} of them named '{PREFIX}...'")
    failed = 0
    for w in wants:
        action, view = plan(existing, w)
        if not w["name"].startswith(PREFIX):  # never write a view this script does not own
            raise ValueError(f"refusing to write '{w['name']}': not a '{PREFIX}' view")
        if action == "present":
            say(f"  OK       {describe(view)}")
            continue
        if action == "conflict":
            say(f"  FAILED   two {w['type']} views are named '{w['name']}'; neither is touched")
            failed += 1
            continue
        if not write:
            say(f"  --apply would {action}: '{w['name']}' query '{w['search']}'")
            continue
        method, path = ("PUT", f"{VIEWS_PATH}/{view['id']}") if action == "update" else ("POST", VIEWS_PATH)
        status, data = dd.http(method, dd.base + path, dd.headers, json.dumps(w).encode())
        if status not in (200, 201):
            say(f"  FAILED   {method} {path} -> {status}: {str(data.get('errors', data))[:300]}")
            failed += 1
            continue
        say(f"  {'UPDATED' if action == 'update' else 'CREATED'}  '{w['name']}'")
    if not write:
        return 1 if failed else 0
    again = list_views(dd)
    for w in wants:
        action, view = plan(again, w)
        if action != "present":
            say(f"  FAILED   '{w['name']}' does not read back as built ({action})")
            failed += 1
        else:
            say(f"  SAVED    {describe(view)}\n           {view_url(dd.site, view)}")
    say(f"STAGE VIEWS {'RED' if failed else 'GREEN'}: {len(wants)} views, {failed} not saved as built")
    return 1 if failed else 0


# ---- the retention filter -------------------------------------------------------------------------------

def retention_body() -> dict:
    return {"data": {"type": "apm_retention_filter", "attributes": {
        "name": RETENTION_NAME, "enabled": True, "filter_type": "spans-sampling-processor",
        "filter": {"query": RETENTION_QUERY}, "rate": 1.0, "trace_rate": 1.0}}}


def retention_plan(filters: list[dict]) -> tuple[str, dict | None]:
    def attrs(f):
        return f.get("attributes") or {}
    for f in filters:
        a = attrs(f)
        if ((a.get("filter") or {}).get("query") == RETENTION_QUERY and a.get("enabled")
                and a.get("rate") == 1.0 and a.get("trace_rate") == 1.0):
            return "present", f
    named = [f for f in filters if attrs(f).get("name") == RETENTION_NAME]
    return ("conflict", named[0]) if named else ("create", None)


def describe_filter(f: dict) -> str:
    a = f.get("attributes") or {}
    return (f"id {f.get('id')}: '{a.get('name')}' query '{(a.get('filter') or {}).get('query')}' rate {a.get('rate')} "
            f"trace_rate {a.get('trace_rate')} enabled {a.get('enabled')}")


def apply_retention(dd: Datadog, write: bool, say=print) -> int:
    filters = dd.call("GET", RETENTION_PATH).get("data", [])
    say(f"  {len(filters)} APM retention filter(s)")
    action, f = retention_plan(filters)
    if action == "present":
        say(f"OK: the seeds are kept: {describe_filter(f)}; nothing written")
        return 0
    if action == "conflict":
        say(f"FAILED: '{RETENTION_NAME}' exists as {describe_filter(f)}; it is not edited. Nothing written")
        return 1
    if not write:
        say(f"  --apply would create: {json.dumps(retention_body())}")
        return 0
    status, data = dd.http("POST", dd.base + RETENTION_PATH, dd.headers, json.dumps(retention_body()).encode())
    if status not in (200, 201):
        say(f"FAILED: POST {RETENTION_PATH} -> {status}: {str(data.get('errors', data))[:300]}; nothing was created")
        return 1
    action, f = retention_plan(dd.call("GET", RETENTION_PATH).get("data", []))
    if action != "present":
        say(f"FAILED: the create answered {status}, but no filter with query '{RETENTION_QUERY}' reads back")
        return 1
    say(f"CREATED: {describe_filter(f)}, read back after the create")
    return 0


# ---- the command ----------------------------------------------------------------------------------------

def write_key(profile: str, region: str, env, run=subprocess.run) -> str:
    """WIB_FLEET_MONITORS_APP_KEY, else the secret's write-app-key; never printed."""
    if env.get(APP_KEY_ENV):
        return env[APP_KEY_ENV]
    out = run(["aws", "secretsmanager", "get-secret-value", "--secret-id", SECRET_ID, "--profile", profile,
               "--region", region, "--query", "SecretString", "--output", "text"],
              capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"cannot read {SECRET_ID} as profile {profile} in {region}: {out.stderr.strip()[:200]}")
    key = json.loads(out.stdout).get("write-app-key")
    if not key:
        raise RuntimeError(f"{APP_KEY_ENV} is empty and {SECRET_ID} has no write-app-key: the read-only app-key "
                           "gets 403 on the saved views and the retention filters")
    return key


def main(argv=None, keys=read_keys, http=None, env=None, run=subprocess.run, say=print) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", choices=("views", "retention"))
    p.add_argument("--profile", help="AWS profile that can read " + SECRET_ID)
    p.add_argument("--region")
    p.add_argument("--traces", type=pathlib.Path, default=TRACES, help="the seed's views file (views only)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="read-only: what --apply would do")
    mode.add_argument("--apply", action="store_true", help="write what is missing or stale (default: dry run)")
    a = p.parse_args(argv)
    env = os.environ if env is None else env
    wants = []
    if a.what == "views":
        try:
            wants = wanted(json.loads(a.traces.read_text()))
        except (OSError, ValueError, KeyError) as e:
            say(f"FAILED: {a.traces}: {e}")
            return 1
    label = "APPLY" if a.apply else "LIST" if a.list else "DRY-RUN"
    say(f"[{label}] {a.what} in Whitney's sandbox org")
    if not (a.apply or a.list):
        for w in wants:
            say(f"  {w['name']}  [{w['type']}] {w['search']}")
        if a.what == "retention":
            say(f"  {json.dumps(retention_body())}")
        say("  dry run: nothing read or written")
        return 0
    if not (a.profile and a.region):
        say("FAILED: --list and --apply need --profile and --region, for the keys in " + SECRET_ID)
        return 1
    prefix = env.get("WIB_DD_POOL_PREFIX", "Datadog")
    try:
        api, _, site = keys(a.profile, a.region)
        dd = Datadog(site, api, write_key(a.profile, a.region, env, run), http=http)
        org = org_name(dd)
        if not org.startswith(prefix):
            say(f"FAILED: the keys reach org '{org}', not the sandbox org (prefix {prefix}); nothing read or written")
            return 1
        say(f"  org: {org} ({site}), api key from {SECRET_ID}, the unscoped application key")
        if a.what == "retention":
            return apply_retention(dd, a.apply, say)
        return apply_views(dd, wants, a.apply, say)
    except (RuntimeError, ValueError) as e:
        say(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
