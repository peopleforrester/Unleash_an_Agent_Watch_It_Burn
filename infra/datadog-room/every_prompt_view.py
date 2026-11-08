#!/usr/bin/env python3
# ABOUTME: Saves the brief's room query as the saved view "Every prompt" in LLM Observability in Whitney's sandbox org
# ABOUTME: (#792), through Datadog's saved-view store with the unscoped key; it creates that one view and touches no other.
"""The Every prompt view (#792).

Beat 3 of gitops/ai-layer/web/brief.html tells the presenters to open the saved view Every prompt in Agent
Observability (LLM Observability's trace list), and gives its query: ml_app:burritobot
k8s.cluster.name:burritobot-public. This script saves that view in Whitney's sandbox org through the API, so it is
not left to a press in a browser.

Datadog documents no saved-view API, but its explorers share one store, /api/v1/logs/views, filtered by ?type=.
Run 18770 read its create schema off the server's own 400s on 2026-11-08, with bodies that could not be created: the
body is the bare object (a {"logs_view": ...} wrapper is answered "Required parameter 'name' is missing"); the query
is "search", a string; "type" is one of a fixed list, LLM Observability's being "llmobs"; "page" is one of a fixed
list, the trace list being "llm_obs_explorer"; "timerange" admits only "interval", in ms (the listing reads it back
as interval_ms); "options" is an object and "facets" and "tags" are arrays.

--apply lists the org's LLM Observability views first (?type=llmobs). A view already named Every prompt with the
brief's query means the work is done, and nothing is written. One named Every prompt with any other query is not
edited: the run reports it and stops. Otherwise it creates the one view, then lists again and passes only when Every
prompt is there with the exact query, which is the reload.

Nothing else is touched (#629): no view is edited or deleted, and only one is ever created, named Every prompt, whose
query selects BurritoBot's own spans. Listing the other views prints only their id, name, page and query.

The org is fenced as in fleet_monitors.py: /api/v2/current_user must name an org starting with WIB_DD_POOL_PREFIX
(default "Datadog"). The API key comes from Secrets Manager watch-it-burn/datadog; the application key from
WIB_FLEET_MONITORS_APP_KEY, the unscoped key from Michael's user in the sandbox org (the secret's write-app-key
field). The read-only app-key gets 403 on the store. Key values are never printed.

Usage:
    python3 infra/datadog-room/every_prompt_view.py                                    # dry run: nothing read
    WIB_FLEET_MONITORS_APP_KEY=<key> python3 infra/datadog-room/every_prompt_view.py \\
        --profile accen-dev --region us-west-2 --list                                  # read-only
    WIB_FLEET_MONITORS_APP_KEY=<key> python3 infra/datadog-room/every_prompt_view.py \\
        --profile accen-dev --region us-west-2 --apply
"""
from __future__ import annotations

import argparse
import html
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-fleet"))
from fleet_monitors import APP_KEY_ENV, SECRET_ID, Datadog, org_name, read_keys  # noqa: E402

BRIEF = REPO / "gitops" / "ai-layer" / "web" / "brief.html"
NAME = "Every prompt"
VIEWS_PATH = "/api/v1/logs/views"
TYPE = "llmobs"  # LLM Observability's saved-view type, from the server's list of allowed types
PAGE = "llm_obs_explorer"  # the trace list's page, from the server's list of allowed pages
# Past 1 hour, live: the session is 30 minutes (run of show, fleet.sh monitors --session), so the list holds the
# room's chats of the session and not the night before's rehearsal.
INTERVAL_MS = 60 * 60 * 1000
LLM_TRACES = "https://app.datadoghq.com/llm/traces"


def brief_query(path: pathlib.Path = BRIEF) -> str:
    """The query the brief's recipe gives, read from the <code> right after its link, so the two never drift."""
    text = path.read_text()
    anchor = "the query as a link</a>,"
    at = text.find(anchor)
    if at < 0:
        raise ValueError(f"{path}: no '{anchor}' in the recipe; the brief was reworded")
    m = re.search(r"<code>([^<]+)</code>", text[at:])
    if not m:
        raise ValueError(f"{path}: no <code> query after '{anchor}'")
    return html.unescape(m.group(1)).strip()


# ---- the views: pure, offline --------------------------------------------------------------------------

def views_of(data) -> list[dict]:
    """The listing's views: the store answers {"logs_views": [...]}, whatever the type filter."""
    if not isinstance(data, dict) or not isinstance(data.get("logs_views"), list):
        raise ValueError(f"no logs_views list in the answer: {sorted(data) if isinstance(data, dict) else type(data)}")
    return data["logs_views"]


def plan(views: list[dict], query: str) -> tuple[str, dict | None]:
    """('present', view) | ('conflict', view) | ('create', None), over the LLM Observability views alone."""
    named = [v for v in views if v.get("name") == NAME and v.get("type") == TYPE]
    for v in named:
        if v.get("search") == query and v.get("page") == PAGE:
            return "present", v
    if named:
        return "conflict", named[0]
    return "create", None


def body(query: str) -> dict:
    """The one view this script creates, in the shape the store's create validates."""
    return {"name": NAME, "type": TYPE, "page": PAGE, "search": query, "timerange": {"interval": INTERVAL_MS},
            "options": {}, "facets": [], "tags": []}


def describe(view: dict) -> str:
    return (f"id {view.get('id')}: '{view.get('name')}' [type={view.get('type')}, page={view.get('page')}, "
            f"query '{view.get('search')}']")


def view_url(view: dict) -> str:
    return f"{LLM_TRACES}?saved-view-id={view.get('id')}"


# ---- the org -------------------------------------------------------------------------------------------

def list_views(dd: Datadog) -> list[dict]:
    views = views_of(dd.call("GET", f"{VIEWS_PATH}?type={TYPE}"))
    # The filter is Datadog's; the type test is ours, so a listing that returns more never reaches a decision.
    return [v for v in views if v.get("type") == TYPE]


def show(views: list[dict], say=print) -> None:
    say(f"  {len(views)} LLM Observability saved view(s) at {VIEWS_PATH}?type={TYPE}")
    for v in views:
        say(f"    {describe(v)}")


def apply(dd: Datadog, query: str, say=print) -> int:
    views = list_views(dd)
    show(views, say)
    action, view = plan(views, query)
    if action == "present":
        say(f"OK: '{NAME}' is already saved, {describe(view)}; nothing written")
        say(f"  {view_url(view)}")
        return 0
    if action == "conflict":
        say(f"FAILED: a view named '{NAME}' exists as {describe(view)}; it is not edited. Nothing written")
        return 1
    status, data = dd.http("POST", dd.base + VIEWS_PATH, dd.headers, json.dumps(body(query)).encode())
    if status not in (200, 201):
        say(f"FAILED: POST {VIEWS_PATH} -> {status}: {str(data.get('errors', data))[:300]}; nothing was created")
        return 1
    again = list_views(dd)
    saved = [v for v in again if v.get("name") == NAME and v.get("search") == query and v.get("page") == PAGE]
    if not saved:
        say(f"FAILED: the create answered {status}, but the listing read after it has no '{NAME}' with query '{query}'")
        return 1
    say(f"SAVED: '{NAME}', {describe(saved[0])}, read back after the create")
    say(f"  {view_url(saved[0])}")
    return 0


def main(argv=None, keys=read_keys, http=None, env=None, say=print) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", help="AWS profile that can read the instructor org secret")
    p.add_argument("--region")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="read-only: list the LLM Observability views")
    mode.add_argument("--apply", action="store_true", help="create Every prompt if it is missing (default: dry run)")
    a = p.parse_args(argv)
    env = os.environ if env is None else env
    try:
        query = brief_query()
    except ValueError as e:
        say(f"FAILED: {e}")
        return 1
    if "ml_app:burritobot" not in query.split() or not any(t.startswith("k8s.cluster.name:") for t in query.split()):
        say(f"FAILED: the brief's query '{query}' is not BurritoBot's on one cluster; nothing read or written")
        return 1
    label = "APPLY" if a.apply else "LIST" if a.list else "DRY-RUN"
    say(f"[{label}] saved view '{NAME}' in LLM Observability, query '{query}'")
    if not (a.apply or a.list):
        say(f"  dry run: nothing read or written. --apply would create: {body(query)}")
        return 0
    if not (a.profile and a.region):
        say("FAILED: --list and --apply need --profile and --region, for the api key in " + SECRET_ID)
        return 1
    if not env.get(APP_KEY_ENV):
        say(f"FAILED: {APP_KEY_ENV} is empty. The views answer the read-only key in {SECRET_ID} with 403, so even "
            "--list needs the unscoped application key from Michael's user in the sandbox org")
        return 1
    prefix = env.get("WIB_DD_POOL_PREFIX", "Datadog")
    try:
        api, _, site = keys(a.profile, a.region)
        dd = Datadog(site, api, env[APP_KEY_ENV], http=http)
        org = org_name(dd)
        if not org.startswith(prefix):
            say(f"FAILED: the keys reach org '{org}', not the sandbox org (prefix {prefix}); nothing read or written")
            return 1
        say(f"  instructor org: {org} ({site}), api key from {SECRET_ID}, application key from {APP_KEY_ENV}")
        if a.list:
            views = list_views(dd)
            show(views, say)
            action, view = plan(views, query)
            say(f"  --apply would: {action}" + (f" ({describe(view)})" if view else ""))
            return 0
        return apply(dd, query, say)
    except (RuntimeError, ValueError) as e:
        say(f"FAILED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
