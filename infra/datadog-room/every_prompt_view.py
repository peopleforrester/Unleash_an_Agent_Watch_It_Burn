#!/usr/bin/env python3
# ABOUTME: Saves the brief's room query as the saved view "Every prompt" in Whitney's sandbox org (#792), through
# ABOUTME: the API with the unscoped key, creating it only from the shape of an LLM Observability view the org already has.
"""The Every prompt view (#792).

Beat 3 of gitops/ai-layer/web/brief.html tells the presenters to open the saved view Every prompt in Agent
Observability (LLM Observability's trace list), and gives its query: ml_app:burritobot
k8s.cluster.name:burritobot-public. This script saves that view in Whitney's sandbox org through the API, so it is
not left to a press in a browser.

Datadog documents no API for saved views. Its OpenAPI specs (datadog-api-client-python's .generator/schemas, read on
2026-11-05) have none, and of the more than 20 candidate paths runs 17415 and 17464 tried, only /api/v1/logs/views exists: the
read-only pair gets 403 "Failed permission authorization checks" there, and 404 everywhere else. That path is the
explorers' saved-view store. Whether it holds the LLM Observability list's views, and in what shape, is what
--list reads, with the unscoped key, because the read pair cannot.

So --apply writes nothing it has to guess. It lists the views first. A view already named Every prompt with the
brief's query means the work is done, and nothing is written. One named Every prompt with any other query is not
edited: the run reports it and stops. Otherwise it needs a template: a view the org already has whose
product field (any short string field other than its name, query, owner or dates) names LLM Observability. It
copies that view's shape, sets the name and the query, and creates the one view. Without a template it writes
nothing and says so; the listing it printed is what the next run designs from. After a create it lists the views
again and passes only when Every prompt is there with the exact query, which is the reload.

Nothing else is touched (#629): no view is edited or deleted, and only one is ever created, named Every prompt,
whose query selects BurritoBot's own spans. Listing the other views prints only their id, name and product fields.

The org is fenced as in fleet_monitors.py: /api/v2/current_user must name an org starting with WIB_DD_POOL_PREFIX
(default "Datadog"). The API key comes from Secrets Manager watch-it-burn/datadog; the application key from
WIB_FLEET_MONITORS_APP_KEY, the unscoped key from Michael's user in the sandbox org. Key values are never printed.

Usage:
    python3 infra/datadog-room/every_prompt_view.py                                    # dry run: nothing read
    WIB_FLEET_MONITORS_APP_KEY=<key> python3 infra/datadog-room/every_prompt_view.py \\
        --profile accen-dev --region us-west-2 --list                                  # read-only
    WIB_FLEET_MONITORS_APP_KEY=<key> python3 infra/datadog-room/every_prompt_view.py \\
        --profile accen-dev --region us-west-2 --apply
"""
from __future__ import annotations

import argparse
import copy
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
LLM_TRACES = "https://app.datadoghq.com/llm/traces"
# The fields a view carries that are its own, not its kind: never read as a product field, never copied.
OWN_FIELDS = {"id", "name", "query", "author", "owner", "creator", "created_at", "modified_at", "updated_at",
              "created", "modified", "is_favorite", "is_default", "is_integration", "integration_id",
              "integration_short_name", "handle", "email", "user", "org_id", "uuid"}
LLM_RE = re.compile(r"llm", re.I)


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

def views_of(data) -> tuple[str | None, list[dict]]:
    """The listing's views, flat, and the key they came under. JSON:API items are flattened to {id, **attributes}."""
    key, items = None, None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and all(isinstance(i, dict) for i in v):
                key, items = k, v
                break
    if items is None:
        raise ValueError(f"no list of views in the answer: keys {sorted(data) if isinstance(data, dict) else type(data)}")
    flat = []
    for i in items:
        if isinstance(i.get("attributes"), dict):
            flat.append({"id": i.get("id"), "_type": i.get("type"), **i["attributes"]})
        else:
            flat.append(dict(i))
    return key, flat


def query_of(view: dict):
    """The view's query string: top level, or under a nested dict's 'query' (a search block)."""
    q = view.get("query")
    if isinstance(q, str):
        return q
    for v in view.values():
        if isinstance(v, dict) and isinstance(v.get("query"), str):
            return v["query"]
    return None


def product_fields(view: dict) -> dict[str, str]:
    """The short string fields that say what kind of view it is (page, type, data source), not whose it is: the
    view's own, and one level down as parent.key, since a product can sit in an options block."""
    def short(k, v):
        return isinstance(v, str) and k not in OWN_FIELDS and len(v) <= 64 and "@" not in v
    out = {k: v for k, v in view.items() if short(k, v)}
    for k, sub in view.items():
        if isinstance(sub, dict) and k not in OWN_FIELDS:
            out.update({f"{k}.{kk}": vv for kk, vv in sub.items() if short(kk, vv)})
    return out


def is_llm(view: dict) -> bool:
    return any(LLM_RE.search(k) or LLM_RE.search(v) for k, v in product_fields(view).items())


def plan(views: list[dict], query: str) -> tuple[str, dict | None]:
    """('present', view) | ('conflict', view) | ('no-template', None) | ('create', template)."""
    named = [v for v in views if v.get("name") == NAME]
    for v in named:
        if query_of(v) == query and is_llm(v):
            return "present", v
    if named:
        return "conflict", named[0]
    templates = [v for v in views if is_llm(v)]
    if not templates:
        return "no-template", None
    return "create", templates[0]


def body_from(template: dict, query: str) -> dict:
    """The template's shape with its own fields dropped and the name and query set, where the template keeps them."""
    body = {k: copy.deepcopy(v) for k, v in template.items() if k not in OWN_FIELDS and not k.startswith("_")}
    body["name"] = NAME
    if isinstance(template.get("query"), str) or query_of(template) is None:
        body["query"] = query
    else:
        for k, v in body.items():
            if isinstance(v, dict) and isinstance(v.get("query"), str):
                v["query"] = query
                break
    return body


def bodies(key: str | None, template: dict, query: str) -> list[dict]:
    """The create bodies to try, in order: the shape the listing used first, then the bare object."""
    body = body_from(template, query)
    if template.get("_type"):
        return [{"data": {"type": template["_type"], "attributes": body}}]
    out = []
    if key and key.endswith("s"):
        out.append({key[:-1]: body})
    out.append(body)
    return out


def describe(view: dict) -> str:
    fields = ", ".join(f"{k}={v}" for k, v in sorted(product_fields(view).items()))
    return f"id {view.get('id')}: '{view.get('name')}' [{fields or 'no product fields'}]"


def view_url(view: dict) -> str:
    return f"{LLM_TRACES}?saved-view-id={view.get('id')}"


# ---- the org -------------------------------------------------------------------------------------------

def list_views(dd: Datadog) -> tuple[str | None, list[dict]]:
    return views_of(dd.call("GET", VIEWS_PATH))


def show(views: list[dict], say=print) -> None:
    llm = [v for v in views if is_llm(v)]
    say(f"  {len(views)} saved view(s) at {VIEWS_PATH}, {len(llm)} of them LLM Observability's")
    kinds: dict[str, int] = {}
    for v in views:
        k = json.dumps(product_fields(v), sort_keys=True)
        kinds[k] = kinds.get(k, 0) + 1
    for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        say(f"    {n:>3} x {k}")
    for v in llm:
        say(f"    LLM view {describe(v)}")
    if views:
        say(f"  one view's field names: {sorted(views[0])}")


def apply(dd: Datadog, query: str, say=print) -> int:
    key, views = list_views(dd)
    show(views, say)
    action, view = plan(views, query)
    if action == "present":
        say(f"OK: '{NAME}' is already saved, {describe(view)}, query '{query_of(view)}'; nothing written")
        say(f"  {view_url(view)}")
        return 0
    if action == "conflict":
        say(f"FAILED: a view named '{NAME}' exists with query '{query_of(view)}' and {describe(view)}; it is not "
            "edited. Nothing written")
        return 1
    if action == "no-template":
        say(f"FAILED: no LLM Observability view in the listing to copy the shape from; nothing written. The listing "
            "above is what the next run designs the create from")
        return 1
    say(f"  template: {describe(view)}")
    last = None
    for body in bodies(key, view, query):
        status, data = dd.http("POST", dd.base + VIEWS_PATH, dd.headers, json.dumps(body).encode())
        if status in (200, 201):
            break
        last = f"POST {VIEWS_PATH} -> {status}: {json.dumps(data.get('errors', data))[:300]}"
        say(f"  {last}")
        if status not in (400, 422):
            break
    else:
        say(f"FAILED: Datadog refused every create shape; nothing was created ({last})")
        return 1
    if status not in (200, 201):
        say(f"FAILED: {last}; nothing was created")
        return 1
    _, again = list_views(dd)
    saved = [v for v in again if v.get("name") == NAME and query_of(v) == query]
    if not saved:
        say(f"FAILED: the create answered {status}, but the listing read after it has no '{NAME}' with query '{query}'")
        return 1
    say(f"SAVED: '{NAME}', {describe(saved[0])}, query '{query_of(saved[0])}', read back after the create")
    say(f"  {view_url(saved[0])}")
    return 0


def main(argv=None, keys=read_keys, http=None, env=None, say=print) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", help="AWS profile that can read the instructor org secret")
    p.add_argument("--region")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="read-only: list the saved views and say what --apply would do")
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
        say("  dry run: nothing read or written. Re-run with --list or --apply.")
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
            key, views = list_views(dd)
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
