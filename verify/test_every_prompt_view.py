# ABOUTME: Offline tests for the Every prompt saved view (#792): the query is the brief's, and the loader lists before it
# ABOUTME: writes, never edits or deletes a view, and creates the one view only from an LLM Observability view's shape.
"""Nothing here reaches Datadog or AWS. The org is a fake that records every call.

The query is read from gitops/ai-layer/web/brief.html, so the view saves what the brief's recipe gives and the two
cannot drift. The loader's contract, driven through the fake: a dry run reads nothing; --list and --apply need the
unscoped key and Whitney's org; --apply writes nothing when Every prompt is already there, when a view of that name
holds another query, or when the org has no LLM Observability view to copy the shape from; otherwise it creates
exactly one view, named Every prompt, with the brief's query and the template's kind, and passes only when the
listing read after the create has it. No call is ever a PUT, PATCH or DELETE, and no key value is ever printed.
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


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


LOGS_VIEW = {"id": 11, "name": "Errors", "query": "status:error", "page": "stream",
             "author": {"handle": "whitney@example.com"}, "timerange": {"interval_ms": 900000}}
LLM_VIEW = {"id": 22, "name": "Whitney's agents", "query": "ml_app:other", "page": "llm-obs-traces",
            "author": {"handle": "whitney@example.com"}, "created_at": "2026-10-01", "timerange": {"interval_ms": 900000}}


class FakeOrg:
    def __init__(self, views, org="Datadog (Whitney Lee sandbox)", refuse=()):
        self.views = copy.deepcopy(views)
        self.org = org
        self.calls: list[tuple[str, str, dict | None]] = []
        self.refuse = list(refuse)  # statuses to answer the next POSTs with, in order
        self.next_id = 900

    def __call__(self, method, url, headers, body):
        path = urllib.parse.urlparse(url).path
        data = json.loads(body) if body else None
        self.calls.append((method, path, data))
        if path == "/api/v2/current_user":
            return 200, {"included": [{"type": "orgs", "attributes": {"name": self.org}}]}
        if path == ev.VIEWS_PATH and method == "GET":
            return 200, {"logs_views": copy.deepcopy(self.views)}
        if path == ev.VIEWS_PATH and method == "POST":
            if self.refuse:
                return self.refuse.pop(0), {"errors": ["Bad Request"]}
            got = data.get("logs_view", data)
            self.next_id += 1
            self.views.append({"id": self.next_id, "author": {"handle": "michael@example.com"}, **got})
            return 200, {"logs_view": self.views[-1]}
        return 404, {"errors": ["Not found"]}

    def methods(self):
        return {m for m, _, _ in self.calls}

    def posts(self):
        return [d for m, _, d in self.calls if m == "POST"]


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

print("== the views, offline ==")
key, flat = ev.views_of({"logs_views": [LOGS_VIEW, LLM_VIEW]})
check("views_of finds the list and its key", key == "logs_views" and len(flat) == 2)
_, ja = ev.views_of({"data": [{"id": "7", "type": "saved_view", "attributes": {"name": "x", "page": "llm"}}]})
check("views_of flattens JSON:API items", ja == [{"id": "7", "_type": "saved_view", "name": "x", "page": "llm"}])
check("an LLM Observability view is recognised by its product field", ev.is_llm(LLM_VIEW))
check("a logs view is not", not ev.is_llm(LOGS_VIEW))
check("a view named for LLMs is not one by its name alone", not ev.is_llm({"name": "llm stuff", "page": "stream"}))
check("a product field one level down counts", ev.is_llm({"name": "x", "options": {"product": "llm_obs"}}))
check("an owner's handle is never a product field", "author.handle" not in ev.product_fields(LLM_VIEW))
body = ev.body_from(LLM_VIEW, BRIEF_QUERY)
check("the body copies the template's kind and window", body.get("page") == "llm-obs-traces"
      and body.get("timerange") == {"interval_ms": 900000}, str(body))
check("the body drops the template's id, owner and dates",
      not ({"id", "author", "created_at"} & set(body)), str(body))
check("the body carries the name and the brief's query", body["name"] == ev.NAME and body["query"] == BRIEF_QUERY)
nested = ev.body_from({"id": 1, "name": "t", "page": "llm", "search": {"query": "a"}}, BRIEF_QUERY)
check("a nested search query is set where the template keeps it",
      nested["search"]["query"] == BRIEF_QUERY and "query" not in nested, str(nested))
check("the listing's shape is tried first, the bare object second",
      [list(b) for b in ev.bodies("logs_views", LLM_VIEW, BRIEF_QUERY)] == [["logs_view"], sorted(body, key=list(body).index)])

print("== dry run and refusals ==")
org = FakeOrg([LLM_VIEW])
rc, out = run([], org)
check("a dry run exits 0 and reads nothing", rc == 0 and org.calls == [], out)
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
org = FakeOrg([LOGS_VIEW, LLM_VIEW])
rc, out = run(LIVE + ["--list"], org)
check("--list exits 0 with GETs only", rc == 0 and org.methods() == {"GET"}, out)
check("--list says what --apply would do", "--apply would: create" in out, out)
check("--list counts the LLM Observability views", "2 saved view(s)" in out and "1 of them" in out, out)

print("== --apply ==")
org = FakeOrg([LOGS_VIEW, LLM_VIEW])
rc, out = run(LIVE + ["--apply"], org)
posts = org.posts()
check("a missing view is created, once", rc == 0 and len(posts) == 1, out)
made = posts[0].get("logs_view", {}) if posts else {}
check("it is named Every prompt with the brief's exact query", made.get("name") == ev.NAME
      and made.get("query") == BRIEF_QUERY, str(made))
check("it is the template's kind", made.get("page") == "llm-obs-traces", str(made))
check("only GET and POST are ever sent", org.methods() <= {"GET", "POST"}, str(org.methods()))
check("the listing is read again after the create", [m for m, p, _ in org.calls if p == ev.VIEWS_PATH][-1] == "GET")
check("it prints SAVED and the view's link", "SAVED:" in out and "saved-view-id=" in out, out)
check("no key value is printed", API not in out and APP not in out)

org = FakeOrg([LOGS_VIEW, LLM_VIEW, {**LLM_VIEW, "id": 33, "name": ev.NAME, "query": BRIEF_QUERY}])
rc, out = run(LIVE + ["--apply"], org)
check("an Every prompt already saved with the query is left alone", rc == 0 and org.posts() == [] and "OK:" in out, out)

org = FakeOrg([LLM_VIEW, {**LLM_VIEW, "id": 34, "name": ev.NAME, "query": "ml_app:other"}])
rc, out = run(LIVE + ["--apply"], org)
check("an Every prompt with another query is not edited and nothing is written",
      rc == 1 and org.methods() == {"GET"}, out)

org = FakeOrg([LOGS_VIEW])
rc, out = run(LIVE + ["--apply"], org)
check("with no LLM Observability view to copy, nothing is written",
      rc == 1 and org.methods() == {"GET"} and "no LLM Observability view" in out, out)

org = FakeOrg([LLM_VIEW], refuse=[400])
rc, out = run(LIVE + ["--apply"], org)
check("a 400 on the listing's shape tries the bare object, and that one is created",
      rc == 0 and len(org.posts()) == 2 and "logs_view" not in org.posts()[1], out)

org = FakeOrg([LLM_VIEW], refuse=[403])
rc, out = run(LIVE + ["--apply"], org)
check("a 403 stops at the first create", rc == 1 and len(org.posts()) == 1, out)

org = FakeOrg([LLM_VIEW], refuse=[400, 400])
rc, out = run(LIVE + ["--apply"], org)
check("both shapes refused: nothing created, exit 1", rc == 1 and len(org.posts()) == 2
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
