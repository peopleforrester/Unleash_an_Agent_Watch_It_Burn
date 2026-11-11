# ABOUTME: Offline tests for the stage views and the seeds' retention filter (#648): seven views in presentation order
# ABOUTME: built from the seed's views file, written only under 'WIB stage ', updated in place, and read back.
"""Nothing here reaches Datadog or AWS. The org is a fake that records every call. Its saved-view store holds the
create schema runs 18770 and 20202 read off Datadog's 400s (the bare object, type and page from fixed lists,
timerange with "interval" alone) and answers PUT on a view's id; its retention-filter store answers the v2 list and
create.

The contract, driven through the fake: the seven views are built from tmp/stage-traces.json's sessions, a `-2` ask
included, in presentation order (Challenge 1 to 4, the PII refusal after Challenge 3 in APM, then burritobot-public
and burritobot-private), with each challenge's attack and fixed seed in one view; their titles are the run-of-show's
segment headings; --apply creates what is missing, updates a stale one in place, leaves a current one alone, never
writes or deletes a view of another name, refuses a name two views hold, and passes only on read-back. The retention
filter is created once, left alone when present, and not edited when its name holds another query. No key value is
printed.
"""
from __future__ import annotations

import copy
import json
import pathlib
import re
import sys
import tempfile
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-room"))
import stage_views as sv  # noqa: E402

failures: list[str] = []
API, APP = "api-key-value-123", "unscoped-app-key-456"
TYPES = {"logs", "rum", "audit", "llmobs", "trace"}
PAGES = {"stream", "analytics", "rum_explorer", "llm_obs_explorer", "llm_obs_overview", "traces"}
STAMP = "202611110040"
ROS = REPO / "facilitation" / "kubecon-na-2026-run-of-show.md"


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def traces(sessions: dict[str, str] | None = None) -> dict:
    keys = ["c1-attack", "c1-fixed", "c2-attack", "c2-fixed", "c3-attack", "c3-fixed", "c3-pii", "c4-attack",
            "c4-fixed"]
    rows = [{"key": k, "session": (sessions or {}).get(k, f"wib-stage-{k}-{STAMP}")} for k in keys]
    rows += [{"key": "room", "session": None, "query": "k8s.cluster.name:burritobot-public"},
             {"key": "presenters", "session": None, "query": "k8s.cluster.name:burritobot-private"}]
    return {"stamp": STAMP, "views": rows}


def schema_errors(d) -> str | None:
    if not isinstance(d, dict) or not d.get("name"):
        return "Required parameter 'name' is missing"
    if not isinstance(d.get("search"), str):
        return "'search' should be string"
    for k in ("facets", "tags"):
        if k in d and not isinstance(d[k], list):
            return f"'{k}' should be array"
    if d.get("type") not in TYPES:
        return "Value of parameter 'type' should be any of these [...]"
    tr = d.get("timerange")
    if not isinstance(tr, dict) or set(tr) != {"interval"}:
        return "timerange admits 'interval' alone"
    if d.get("page") not in PAGES:
        return "Value of parameter 'page' should be any of these [...]"
    return None


OTHER = {"id": 4805197, "name": "Every prompt", "type": "llmobs", "page": "llm_obs_explorer",
         "search": "ml_app:burritobot k8s.cluster.name:burritobot-public", "timerange": {"interval_ms": 3600000}}
LOGS = {"id": 32, "name": "WIB stage 1: Challenge 1, the CEO's secret", "type": "logs", "page": "stream",
        "search": "source:redis", "timerange": {"interval_ms": 3600000}}
OTHER_FILTER = {"id": "kXys", "attributes": {"name": "Error Default", "filter": {"query": "status:error"},
                                              "rate": 1.0, "trace_rate": 0.0, "enabled": True}}


class FakeOrg:
    def __init__(self, views=(), filters=(), org="Datadog", refuse=()):
        self.views = copy.deepcopy(list(views))
        self.filters = copy.deepcopy(list(filters))
        self.org = org
        self.refuse = list(refuse)
        self.calls: list[tuple[str, str, dict | None]] = []
        self.next_id = 5000

    def __call__(self, method, url, headers, body):
        parsed = urllib.parse.urlparse(url)
        path, params = parsed.path, urllib.parse.parse_qs(parsed.query)
        data = json.loads(body) if body else None
        self.calls.append((method, path + (f"?{parsed.query}" if parsed.query else ""), data))
        if path == "/api/v2/current_user":
            return 200, {"included": [{"type": "orgs", "attributes": {"name": self.org}}]}
        if path == sv.VIEWS_PATH and method == "GET":
            want = params.get("type", ["logs"])[0]
            return 200, {"logs_views": [copy.deepcopy(v) for v in self.views if v["type"] == want]}
        if path == sv.VIEWS_PATH and method == "POST":
            if self.refuse:
                return self.refuse.pop(0), {"errors": ["Forbidden"]}
            err = schema_errors(data)
            if err:
                return 400, {"errors": [err]}
            self.next_id += 1
            self.views.append({"id": self.next_id, **data, "timerange": {"interval_ms": data["timerange"]["interval"]}})
            return 200, {"logs_view": self.views[-1]}
        m = re.fullmatch(re.escape(sv.VIEWS_PATH) + r"/(\d+)", path)
        if m and method == "PUT":
            err = schema_errors(data)
            if err:
                return 400, {"errors": [err]}
            for i, v in enumerate(self.views):
                if v["id"] == int(m.group(1)):
                    self.views[i] = {"id": v["id"], **data, "timerange": {"interval_ms": data["timerange"]["interval"]}}
                    return 200, {"logs_view": self.views[i]}
            return 404, {"errors": ["Not found"]}
        if path == sv.RETENTION_PATH and method == "GET":
            return 200, {"data": copy.deepcopy(self.filters)}
        if path == sv.RETENTION_PATH and method == "POST":
            a = data["data"]["attributes"]
            self.filters.append({"id": "new1", "type": "apm_retention_filter",
                                 "attributes": {**a, "rate": float(a["rate"]), "trace_rate": float(a["trace_rate"])}})
            return 200, {"data": self.filters[-1]}
        return 404, {"errors": ["Not found"]}

    def writes(self):
        return [(m, p, d) for m, p, d in self.calls if m not in ("GET",)]


def run(args, org=None, env=None, tr=None):
    out: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "stage-traces.json"
        f.write_text(json.dumps(traces() if tr is None else tr))
        rc = sv.main(args + ["--traces", str(f)], keys=lambda p, r: (API, "read-only-app-key", "datadoghq.com"),
                     http=org, env={sv.APP_KEY_ENV: APP} if env is None else env, say=out.append,
                     run=lambda *a, **k: (_ for _ in ()).throw(AssertionError("the secret was read")))
    return rc, "\n".join(out)


LIVE = ["--profile", "accen-dev", "--region", "us-west-2"]

print("== the seven views, offline ==")
w = sv.wanted(traces())
names = [v["name"] for v in w]
check("seven views", len(w) == 7, str(names))
check("names sort into presentation order, as Datadog lists them", sorted(names) == names, str(names))
check("every view is a 'WIB stage ' view", all(n.startswith(sv.PREFIX) for n in names), str(names))
check("every body passes the store's create validation", all(schema_errors(v) is None for v in w),
      str([schema_errors(v) for v in w]))
c1 = w[0]
check("Challenge 1's view holds its attack and fixed seeds, LLM Observability, Past 7 Days",
      c1["search"] == f"ml_app:burritobot session_id:(wib-stage-c1-attack-{STAMP} OR wib-stage-c1-fixed-{STAMP})"
      and (c1["type"], c1["page"]) == sv.LLMOBS and c1["timerange"] == {"interval": 7 * 86400000}, str(c1))
pii = w[3]
check("the PII refusal follows Challenge 3, in APM on the guard-proxy root span",
      names[2].startswith("WIB stage 3:") and (pii["type"], pii["page"]) == ("trace", "traces")
      and pii["search"] == f"service:burritobot @session.id:wib-stage-c3-pii-{STAMP}", str(pii))
check("Challenge 4 is fifth", names[4].startswith("WIB stage 4: Challenge 4"), str(names))
check("burritobot-public and burritobot-private close the list, live 15 minutes",
      [v["search"] for v in w[5:]] == ["ml_app:burritobot k8s.cluster.name:burritobot-public",
                                       "ml_app:burritobot k8s.cluster.name:burritobot-private"]
      and all(v["timerange"] == {"interval": 900000} for v in w[5:]), str(w[5:]))
retry = sv.wanted(traces({"c2-fixed": f"wib-stage-c2-fixed-{STAMP}-2"}))
check("a seed asked again is viewed on the session that made the call (#1210)",
      f"wib-stage-c2-fixed-{STAMP}-2)" in retry[1]["search"], retry[1]["search"])
for bad, why in ((traces({"c4-fixed": ""}), "a seed with no session"),
                 (traces({"c1-attack": "wib-stage-c2-attack-x"}), "a session of another seed"),
                 ({"stamp": STAMP}, "a file with no views")):
    try:
        sv.wanted(bad)
        check(f"{why} is refused", False)
    except ValueError:
        check(f"{why} is refused", True)

print("== the titles are the run-of-show's segment headings ==")
ros = ROS.read_text()
for n, title, _ in sv.CHALLENGES:
    check(f"'{title}' heads a segment", re.search(r"^### Segment \d: " + re.escape(title) + r" \(", ros, re.M)
          is not None, f"no '### Segment N: {title} (' in {ROS}")

print("== dry run and refusals ==")
org = FakeOrg()
rc, out = run(["views"], org)
check("a dry run exits 0, reads nothing and names the seven", rc == 0 and org.calls == [] and out.count(sv.PREFIX) == 7,
      out)
rc, out = run(["views", "--apply"], FakeOrg())
check("--apply without --profile and --region fails", rc == 1 and "--profile" in out, out)
org = FakeOrg(org="Some Other Org")
rc, out = run(["views"] + LIVE + ["--apply"], org)
check("another org is refused before any view is read",
      rc == 1 and [p for _, p, _ in org.calls] == ["/api/v2/current_user"], out)
org = FakeOrg()
rc, out = run(["views"] + LIVE + ["--apply"], org, tr={"stamp": STAMP})
check("a views file without the seeds reads and writes nothing", rc == 1 and org.calls == [], out)

print("== views --apply ==")
org = FakeOrg([OTHER, LOGS])
rc, out = run(["views"] + LIVE + ["--list"], org)
check("--list sends GETs only and says it would create seven",
      rc == 0 and not org.writes() and out.count("--apply would create") == 7, out)
rc, out = run(["views"] + LIVE + ["--apply"], org)
check("--apply creates the seven and ends GREEN", rc == 0 and len(org.writes()) == 7
      and "STAGE VIEWS GREEN" in out, out)
check("only POSTs to the store", {(m, p) for m, p, _ in org.writes()} == {("POST", sv.VIEWS_PATH)}, str(org.writes()))
check("the other views are untouched", OTHER in org.views and LOGS in org.views)
check("each saved view's link is printed", out.count("saved-view-id=") == 7 and "apm/traces?saved-view-id" in out, out)
check("no key value is printed", API not in out and APP not in out)
before = copy.deepcopy(org.views)
org.calls.clear()
rc, out = run(["views"] + LIVE + ["--apply"], org)
check("a second apply writes nothing", rc == 0 and not org.writes() and org.views == before, out)

org.calls.clear()
rc, out = run(["views"] + LIVE + ["--apply"], org, tr=traces({k: f"wib-stage-{k}-202611120900" for k in
                                                              ("c1-attack", "c1-fixed", "c2-attack", "c2-fixed",
                                                               "c3-attack", "c3-fixed", "c3-pii", "c4-attack",
                                                               "c4-fixed")}))
puts = [p for m, p, _ in org.writes() if m == "PUT"]
check("a new seed's sessions update the five seed views in place, by id", rc == 0 and len(puts) == 5
      and len(org.writes()) == 5 and len(org.views) == len(before), str(org.writes()))
check("after the update the seed views name the new stamp",
      all("202611120900" in v["search"] for v in org.views if v["name"].startswith("WIB stage ")
          and v["type"] != "logs" and "k8s.cluster.name" not in v["search"]))
check("the logs view of a stage view's name is untouched", LOGS in org.views)

dup = sv.body(sv.PREFIX + "1: Challenge 1, the CEO's secret", sv.LLMOBS, "x", 1)
org = FakeOrg([{**dup, "id": 1}, {**dup, "id": 2}])
rc, out = run(["views"] + LIVE + ["--apply"], org)
check("a name two views hold is not touched, and the run is RED",
      rc == 1 and not [c for c in org.writes() if c[1].endswith(("/1", "/2"))] and "STAGE VIEWS RED" in out, out)

org = FakeOrg(refuse=[403])
rc, out = run(["views"] + LIVE + ["--apply"], org)
check("a refused create is RED", rc == 1 and "-> 403" in out and "STAGE VIEWS RED" in out, out)

print("== retention ==")
org = FakeOrg(filters=[OTHER_FILTER])
rc, out = run(["retention"] + LIVE + ["--list"], org)
check("--list reads only and says it would create", rc == 0 and not org.writes() and "would create" in out, out)
rc, out = run(["retention"] + LIVE + ["--apply"], org)
f = org.filters[-1]["attributes"]
check("--apply creates the one filter and reads it back", rc == 0 and len(org.writes()) == 1 and "CREATED" in out
      and f["filter"]["query"] == "service:burritobot @session.id:wib-stage-*" and f["rate"] == 1.0
      and f["trace_rate"] == 1.0 and f["enabled"] is True, out)
org.calls.clear()
rc, out = run(["retention"] + LIVE + ["--apply"], org)
check("present, nothing written", rc == 0 and not org.writes() and "OK:" in out, out)
org = FakeOrg(filters=[{"id": "x", "attributes": {"name": sv.RETENTION_NAME, "filter": {"query": "service:other"},
                                                  "rate": 1.0, "trace_rate": 1.0, "enabled": True}}])
rc, out = run(["retention"] + LIVE + ["--apply"], org)
check("its name with another query is not edited", rc == 1 and not org.writes(), out)

print("== the key ==")
seen = []


def fake_aws(cmd, **k):
    seen.append(cmd)
    return type("R", (), {"returncode": 0, "stdout": json.dumps({"write-app-key": "from-secret"}), "stderr": ""})()


check("WIB_FLEET_MONITORS_APP_KEY wins and the secret is not read",
      sv.write_key("p", "r", {sv.APP_KEY_ENV: "env-key"}, run=fake_aws) == "env-key" and not seen)
check("else the secret's write-app-key", sv.write_key("p", "r", {}, run=fake_aws) == "from-secret"
      and "--profile" in seen[0] and "p" in seen[0])

print()
if failures:
    print(f"STAGE VIEWS TESTS RED: {len(failures)} failed: {failures}")
    sys.exit(1)
print("ALL STAGE VIEWS TESTS GREEN")
