# ABOUTME: Offline tests for the Every prompt saved view (#792): the query is the brief's, and the loader lists the LLM
# ABOUTME: Observability views before it writes, never edits or deletes a view, and creates only Every prompt.
"""Nothing here reaches Datadog or AWS. The org is a fake that records every call and holds the create schema run
18770 read off Datadog's 400s: the bare object, type and page from fixed lists, timerange with "interval" alone.

The query is read from gitops/ai-layer/web/brief.html, so the view saves what the brief's recipe gives and the two
cannot drift. The loader's contract, driven through the fake: a dry run reads nothing; --list and --apply need the
unscoped key and Whitney's org; both read only ?type=llmobs; --apply writes nothing when Every prompt is already
there, or when a view of that name holds another query; otherwise it creates exactly one view, named Every prompt,
with the brief's query on LLM Observability's trace list, and passes only when the listing read after the create
has it. A view of another explorer named Every prompt is not mistaken for it. No call is ever a PUT, PATCH or
DELETE, and no key value is ever printed.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-room"))
import every_prompt_view as ev  # noqa: E402

failures: list[str] = []
BRIEF_QUERY = "ml_app:burritobot k8s.cluster.name:burritobot-public"
API, APP = "api-key-value-123", "unscoped-app-key-456"
TYPES = {"logs", "rum", "audit", "llmobs"}
PAGES = {"stream", "analytics", "rum_explorer", "llm_obs_explorer", "llm_obs_overview"}


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


LOGS_VIEW = {"id": 32, "name": "Redis PID overview", "search": "source:redis", "type": "logs", "page": "analytics",
             "author": None, "timerange": {"interval_ms": 3600000}}
LOGS_NAMED = {"id": 35, "name": ev.NAME, "search": "source:nginx", "type": "logs", "page": "stream",
              "author": None, "timerange": {"interval_ms": 3600000}}
LLM_VIEW = {"id": 1301, "name": "Whitney's agents", "search": "ml_app:other", "type": "llmobs",
            "page": "llm_obs_explorer", "author": {"handle": "whitney@example.com"}, "timerange": {"interval_ms": 900000}}


def schema_errors(d) -> str | None:
    """The store's create validation, as run 18770 read it from Datadog, in its order."""
    if not isinstance(d, dict) or not d.get("name"):
        return "Required parameter 'name' is missing"
    if not isinstance(d.get("search"), str):
        return "'search' should be string"
    if "options" in d and not isinstance(d["options"], dict):
        return "'options' should be object"
    for k in ("facets", "tags"):
        if k in d and not isinstance(d[k], list):
            return f"'{k}' should be array"
    if d.get("type") not in TYPES:
        return "Value of parameter 'type' should be any of these [...]"
    tr = d.get("timerange")
    if not isinstance(tr, dict):
        return "'timerange' should be object"
    if set(tr) - {"interval"}:
        return f"Additional properties are not allowed ('{sorted(set(tr) - {'interval'})[0]}' was unexpected)"
    if d.get("page") not in PAGES:
        return "Value of parameter 'page' should be any of these [...]"
    return None


class FakeOrg:
    def __init__(self, views, org="Datadog", refuse=()):
        self.views = copy.deepcopy(views)
        self.org = org
        self.calls: list[tuple[str, str, dict | None]] = []
        self.refuse = list(refuse)  # statuses to answer the next POSTs with, in order
        self.next_id = 1400

    def __call__(self, method, url, headers, body):
        parsed = urllib.parse.urlparse(url)
        path, params = parsed.path, urllib.parse.parse_qs(parsed.query)
        data = json.loads(body) if body else None
        self.calls.append((method, parsed.path + (f"?{parsed.query}" if parsed.query else ""), data))
        if path == "/api/v2/current_user":
            return 200, {"included": [{"type": "orgs", "attributes": {"name": self.org}}]}
        if path == ev.VIEWS_PATH and method == "GET":
            want = params.get("type", ["logs"])[0]
            return 200, {"logs_views": [copy.deepcopy(v) for v in self.views if v["type"] == want]}
        if path == ev.VIEWS_PATH and method == "POST":
            if self.refuse:
                return self.refuse.pop(0), {"errors": ["Forbidden"]}
            err = schema_errors(data)
            if err:
                return 400, {"errors": [err]}
            self.next_id += 1
            tr = {"interval_ms": data["timerange"]["interval"]}
            self.views.append({"id": self.next_id, "author": {"handle": "michael@example.com"}, **data, "timerange": tr})
            return 200, {"logs_view": self.views[-1]}
        return 404, {"errors": ["Not found"]}

    def methods(self):
        return {m for m, _, _ in self.calls}

    def posts(self):
        return [d for m, _, d in self.calls if m == "POST"]

    def view_reads(self):
        return [p for m, p, _ in self.calls if m == "GET" and p.startswith(ev.VIEWS_PATH)]


def run(args, org=None, env=None):
    out: list[str] = []
    rc = ev.main(args, keys=lambda p, r: (API, "read-only-app-key", "datadoghq.com"), http=org,
                 env={ev.APP_KEY_ENV: APP} if env is None else env, say=out.append)
    return rc, "\n".join(out)


LIVE = ["--profile", "accen-dev", "--region", "us-west-2"]

print("== the query is the brief's ==")
brief = ev.BRIEF.read_text()
check("the brief still has the recipe's link anchor 'the query as a link</a>,'",
      "the query as a link</a>," in brief, f"reworded in {ev.BRIEF}")
check("brief_query() reads the recipe's <code> query", ev.brief_query() == BRIEF_QUERY, ev.brief_query())
link = "https://app.datadoghq.com/llm/traces?query=" + urllib.parse.quote_plus(BRIEF_QUERY)
check("the brief's link fills in the same query", f'href="{link}"' in brief, link)
check("the brief names the view Every prompt", f"saved view <b>{ev.NAME}</b>" in brief)

print("== the body, offline ==")
b = ev.body(BRIEF_QUERY)
check("the body passes the store's create validation", schema_errors(b) is None, str(schema_errors(b)))
check("the body is the bare object, not a logs_view wrapper", "logs_view" not in b and b["name"] == ev.NAME, str(b))
check("it is LLM Observability's trace list", b["type"] == "llmobs" and b["page"] == "llm_obs_explorer", str(b))
check("it carries the brief's exact query", b["search"] == BRIEF_QUERY, str(b))
check("its window is a live hour, as 'interval'", b["timerange"] == {"interval": 3600000}, str(b))
check("a logs_view wrapper is what the store answers 'name' missing to",
      schema_errors({"logs_view": b}) == "Required parameter 'name' is missing")
check("interval_ms, the listing's own key, is refused on create",
      "interval_ms" in str(schema_errors({**b, "timerange": {"interval_ms": 3600000}})))
check("plan: no Every prompt among the LLM views is a create", ev.plan([LLM_VIEW], BRIEF_QUERY) == ("create", None))
check("plan: a logs view named Every prompt is not the LLM one",
      ev.plan([LLM_VIEW, LOGS_NAMED], BRIEF_QUERY) == ("create", None))

print("== dry run and refusals ==")
org = FakeOrg([LLM_VIEW])
rc, out = run([], org)
check("a dry run exits 0, reads nothing and shows the body it would create",
      rc == 0 and org.calls == [] and "llm_obs_explorer" in out, out)
org = FakeOrg([LLM_VIEW])
rc, out = run(LIVE + ["--list"], org, env={})
check("--list without the unscoped key fails and reads nothing", rc == 1 and org.calls == [] and ev.APP_KEY_ENV in out, out)
org = FakeOrg([LLM_VIEW])
rc, out = run(["--apply"], org)
check("--apply without --profile and --region fails and reads nothing", rc == 1 and org.calls == [], out)
org = FakeOrg([LLM_VIEW], org="Some Other Org")
rc, out = run(LIVE + ["--apply"], org)
check("another org is refused before any view is read",
      rc == 1 and [p for _, p, _ in org.calls] == ["/api/v2/current_user"], out)

print("== --list ==")
org = FakeOrg([LOGS_VIEW, LOGS_NAMED, LLM_VIEW])
rc, out = run(LIVE + ["--list"], org)
check("--list exits 0 with GETs only", rc == 0 and org.methods() == {"GET"}, out)
check("--list reads the LLM Observability views alone", org.view_reads() == [f"{ev.VIEWS_PATH}?type=llmobs"],
      str(org.view_reads()))
check("--list counts them and says what --apply would do",
      "1 LLM Observability saved view(s)" in out and "--apply would: create" in out, out)
check("--list prints no owner's handle", "whitney@example.com" not in out, out)

print("== --apply ==")
org = FakeOrg([LOGS_VIEW, LOGS_NAMED, LLM_VIEW])
rc, out = run(LIVE + ["--apply"], org)
posts = org.posts()
check("a missing view is created, once", rc == 0 and len(posts) == 1, out)
check("the create is the body, and the fake store accepted it", posts == [ev.body(BRIEF_QUERY)], str(posts))
check("only GET and POST are ever sent", org.methods() <= {"GET", "POST"}, str(org.methods()))
check("the listing is read again after the create", org.calls[-1][0] == "GET"
      and org.calls[-1][1] == f"{ev.VIEWS_PATH}?type=llmobs", str(org.calls[-1]))
check("it prints SAVED and the view's link", "SAVED:" in out and "saved-view-id=1401" in out, out)
check("no key value is printed", API not in out and APP not in out)
check("the other views are as they were", [v for v in org.views if v["id"] != 1401]
      == [LOGS_VIEW, LOGS_NAMED, LLM_VIEW])

made = {**ev.body(BRIEF_QUERY), "id": 1350, "timerange": {"interval_ms": 3600000}}
org = FakeOrg([LLM_VIEW, made])
rc, out = run(LIVE + ["--apply"], org)
check("an Every prompt already saved with the query is left alone", rc == 0 and org.posts() == [] and "OK:" in out, out)
check("its link is printed", "saved-view-id=1350" in out, out)

org = FakeOrg([LLM_VIEW, {**LLM_VIEW, "id": 1351, "name": ev.NAME, "search": "ml_app:other"}])
rc, out = run(LIVE + ["--apply"], org)
check("an Every prompt with another query is not edited and nothing is written",
      rc == 1 and org.methods() == {"GET"}, out)

org = FakeOrg([LLM_VIEW], refuse=[403])
rc, out = run(LIVE + ["--apply"], org)
check("a 403 on the create fails with nothing created", rc == 1 and len(org.posts()) == 1
      and not [v for v in org.views if v.get("name") == ev.NAME], out)


class LostOrg(FakeOrg):
    def __call__(self, method, url, headers, body):
        status, data = super().__call__(method, url, headers, body)
        if method == "POST":
            self.views.pop()  # answered 200, but the view is not there on reload
        return status, data


org = LostOrg([LLM_VIEW])
rc, out = run(LIVE + ["--apply"], org)
check("a create that is not there on reload fails", rc == 1 and "listing read after it" in out, out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("ALL EVERY PROMPT VIEW CHECKS GREEN")
