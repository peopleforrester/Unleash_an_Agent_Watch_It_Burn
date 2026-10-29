# ABOUTME: Offline tests for the room's read-only Datadog view (#665): every query is fenced to burritobot-public, the
# ABOUTME: names it counts exist in the platform, and the loader shares it open, unselectable and expiring.
"""Nothing here reaches Datadog or AWS. The org is a fake that records every call.

Three parts. The fence: room_view.yaml validates, and validate() refuses each way another cluster's data or an
attendee's text could reach a public page. The platform: the cluster name, span names, service and metric the
queries count are ones attackme actually produces, so the page is not a row of zeros. The loader: a fresh org gets
a dashboard and an open share, a second apply updates both in place, --check passes on what apply built and fails
on drift, and --apply refuses without the write key or in the wrong org.
"""
from __future__ import annotations

import copy
import datetime as dt
import io
import json
import pathlib
import re
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra" / "datadog-room"))
import room_view as rv  # noqa: E402
sys.path.insert(0, str(REPO / "verify"))
from collector_render import collector_config  # noqa: E402

failures: list[str] = []
NOW = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


defs = rv.load()
dash = defs["dashboard"]
qs = [q["query"] for _, q in rv.queries(dash)]

print("== the definition is fenced to attackme ==")
check("room_view.yaml validates clean", rv.validate(defs, NOW) == [], str(rv.validate(defs, NOW)))
check("it has queries to fence", len(qs) >= 4)
check("every query is a metric query on kube_cluster_name:burritobot-public",
      all(q["data_source"] == "metrics" and rv.CLUSTER_TAG in rv.filter_tags(q["query"]) for _, q in rv.queries(dash)))
check("no template variables", not dash.get("template_variables"))
check("the share is open, with nothing selectable", defs["share"]["share_type"] == "open"
      and defs["share"]["global_time_selectable_enabled"] is False and defs["share"]["selectable_template_vars"] == [])
check("the share expires the day after the talk (2026-11-12)", defs["share"]["expiration"].startswith("2026-11-13"))
check("an ordered dashboard is shared as a timeboard", rv.dashboard_type(dash) == "custom_timeboard")


def refused(mutate, needle: str) -> bool:
    d = copy.deepcopy(defs)
    mutate(d)
    return any(needle in p for p in rv.validate(d, NOW))


def first_query(d):
    return d["dashboard"]["widgets"][1]["definition"]["requests"][0]["queries"][0]


def set_query(text):
    return lambda d: first_query(d).__setitem__("query", text)


print("== validate() refuses what would leak ==")
check("a query with no cluster filter",
      refused(set_query("sum:traces.span.metrics.calls{service:burritobot}.as_count()"), "not filtered to"))
check("the presenters' cluster",
      refused(set_query("sum:traces.span.metrics.calls{kube_cluster_name:burritobot-private}.as_count()"),
              "not filtered to"))
check("both clusters by wildcard",
      refused(set_query("sum:traces.span.metrics.calls{kube_cluster_name:burritobot-*}.as_count()"), "not filtered to"))
check("a second cluster beside burritobot-public",
      refused(set_query("sum:x{kube_cluster_name:burritobot-public,kube_cluster_name:burritobot-private}"),
              "other than burritobot-public"))
check("a formula over two metrics where one is unfenced",
      refused(set_query("sum:a{kube_cluster_name:burritobot-public} + sum:b{*}"), "not filtered to"))
check("an exclusion filter",
      refused(set_query("sum:x{kube_cluster_name:burritobot-public,!service:burritobot}"), "exclusion"))
check("an LLM Observability metric (no cluster tag on ml_obs.*)",
      refused(set_query("sum:ml_obs.span{kube_cluster_name:burritobot-public}.as_count()"), "ml_obs"))
check("a group by anything but span name (a content attribute would print prompts)",
      refused(set_query("sum:x{kube_cluster_name:burritobot-public} by {gen_ai.input.messages}"), "grouped by"))
check("an LLM Observability or spans event query",
      refused(lambda d: first_query(d).update(data_source="llm_observability"), "is not metrics"))
check("a list widget (does not render on a shared dashboard, and would list traces)",
      refused(lambda d: d["dashboard"]["widgets"][1]["definition"].update(type="list_stream"), "is not one of"))
check("a template variable",
      refused(lambda d: d["dashboard"].update(template_variables=[{"name": "cluster", "prefix": "kube_cluster_name"}]),
              "template variables"))
check("an invite-only or embedded share",
      refused(lambda d: d["share"].update(share_type="invite"), "is not open"))
check("a selectable time", refused(lambda d: d["share"].update(global_time_selectable_enabled=True), "selectable"))
check("selectable template variables",
      refused(lambda d: d["share"].update(selectable_template_vars=[{"name": "x"}]), "selectable_template_vars"))
check("no expiration", refused(lambda d: d["share"].pop("expiration"), "expiration"))
check("a passed expiration", any("has passed" in p for p in rv.validate(defs, dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc))))
check("a formula naming no query",
      refused(lambda d: d["dashboard"]["widgets"][1]["definition"]["requests"][0]["formulas"][0].update(formula="nope"),
              "names a query"))

print("== the names it counts are attackme's ==")
ident = (REPO / "infra/datadog-cluster-identity.sh").read_text()
check("the community cluster (attackme) reports as burritobot-public",
      re.search(r'watch-it-burn-community\)\s+DATADOG_CLUSTER_NAME="burritobot-public"', ident) is not None)
col = collector_config("burn", datadog_secret=True)
check("burn's collector stamps k8s.cluster.name from that name",
      any(a.get("key") == "k8s.cluster.name" and "WIB_CLUSTER_NAME" in str(a.get("value"))
          for a in col["processors"]["resource"]["attributes"]))
check("burn turns spans into traces.span.metrics.* with the resource attributes kept",
      "span_metrics" in col["service"]["pipelines"]["traces"]["exporters"]
      and "span_metrics" in col["service"]["pipelines"]["metrics"]["receivers"]
      and "resource" in col["service"]["pipelines"]["metrics"]["processors"]
      and (col["connectors"]["span_metrics"] or {}).get("add_resource_attributes") is True
      and "namespace" not in (col["connectors"]["span_metrics"] or {}))
proxy = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text()
check("guard-proxy's chat span is named chat", 'start_as_current_span("chat"' in proxy)
check("guard-proxy records gen_ai.client.cost", "gen_ai.client.cost" in proxy)
res = (REPO / "gitops/ai-layer/resources.yaml").read_text()
check("guard-proxy's service is burritobot", "service.name=burritobot," in res)
check("tool spans are execute_tool <tool> (the toplist's wildcard)",
      "execute_tool read_internal_config" in (REPO / "verify/test_segment6_view.py").read_text())
for t in sorted({t for q in qs for t in rv.filter_tags(q) if t.startswith("service:")}):
    check(f"service filter {t} is a service in the bundle", f"service.name={t.split(':', 1)[1]}," in res)


class FakeOrg:
    """Records every call. Holds dashboards and shares the way Datadog does, keyed by id and token."""

    def __init__(self, org="Datadog Whitney Sandbox"):
        self.org, self.calls, self.dashboards, self.shares, self.n = org, [], {}, {}, 0

    def __call__(self, method, url, headers, body):
        path = url.split("datadoghq.com", 1)[1]
        data = json.loads(body) if body else None
        self.calls.append((method, path, headers.get("DD-APPLICATION-KEY"), data))
        if path == "/api/v2/current_user":
            return 200, {"included": [{"type": "orgs", "attributes": {"name": self.org}}]}
        if path == "/api/v1/dashboard" and method == "GET":
            return 200, {"dashboards": [{"id": i, "title": d["title"]} for i, d in self.dashboards.items()]}
        if path == "/api/v1/dashboard" and method == "POST":
            self.n += 1
            i = f"abc-{self.n:03d}"
            self.dashboards[i] = data
            return 200, {"id": i, **data}
        m = re.fullmatch(r"/api/v1/dashboard/([a-z0-9-]+)", path)
        if m and m.group(1) != "public":
            if method == "PUT":
                self.dashboards[m.group(1)] = data
            return 200, {"id": m.group(1), **self.dashboards[m.group(1)]}
        if path == "/api/v1/dashboard/public" and method == "POST":
            self.n += 1
            tok = f"tok{self.n:03d}"
            self.shares[tok] = {**data, "token": tok, "status": "active",
                                "public_url": f"https://p.datadoghq.com/sb/xyz-{tok}"}
            return 200, self.shares[tok]
        m = re.fullmatch(r"/api/v1/dashboard/public/(\w+)", path)
        if m:
            if m.group(1) not in self.shares:
                return 404, {"errors": ["not found"]}
            if method == "PUT":
                self.shares[m.group(1)].update(data)
            return 200, self.shares[m.group(1)]
        return 404, {"errors": [f"unexpected {method} {path}"]}

    def writes(self):
        return [(m, p) for m, p, _, _ in self.calls if m != "GET"]


def keys(*_):
    return "API", "READ-ONLY-APP", "datadoghq.com"


def run(argv, org, env=None, share_file=None, public=lambda url: 200, now=NOW):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = rv.main(argv, keys=keys, http=org, now=now, env=env if env is not None else {},
                     share_file=share_file, public=public)
    return rc, out.getvalue() + err.getvalue()


AWS = ["--profile", "accen-dev", "--region", "us-west-2"]
WRITE = {rv.APP_KEY_ENV: "WRITE-APP"}

with tempfile.TemporaryDirectory() as d:
    sf = pathlib.Path(d) / "share.json"

    print("== dry run and --json touch nothing ==")
    org = FakeOrg()
    rc, out = run([], org, share_file=sf)
    check("dry run exits 0 and makes no call", rc == 0 and org.calls == [])
    rc, out = run(["--json"], org, share_file=sf)
    check("--json prints the dashboard body and makes no call",
          rc == 0 and org.calls == [] and json.loads(out)["title"] == dash["title"])

    print("== --apply refuses before writing ==")
    rc, out = run(["--apply"] + AWS, org, share_file=sf)
    check("without the write key: exit 1, no call, and it names the key", rc == 1 and org.calls == []
          and rv.APP_KEY_ENV in out)
    rc, out = run(["--apply"], org, env=WRITE, share_file=sf)
    check("without --profile/--region: exit 1, no call", rc == 1 and org.calls == [])
    wrong = FakeOrg(org="Some Other Org")
    rc, out = run(["--apply"] + AWS, wrong, env=WRITE, share_file=sf)
    check("in an org that is not the sandbox org: exit 1, nothing written", rc == 1 and wrong.writes() == [])
    rc, out = run(["--apply"] + AWS, org, env=WRITE, share_file=sf, now=dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc))
    check("after the expiration: exit 1, no call", rc == 1 and org.calls == [])

    print("== --apply on a fresh org ==")
    rc, out = run(["--apply"] + AWS, org, env=WRITE, share_file=sf)
    check("exit 0", rc == 0, out)
    check("one dashboard and one share", len(org.dashboards) == 1 and len(org.shares) == 1)
    check("every write used the write key, not the read-only one",
          all(k == "WRITE-APP" for m, _, k, _ in org.calls if m != "GET"))
    sh = next(iter(org.shares.values()))
    check("the share is open, unselectable, expiring, on the new dashboard",
          sh["share_type"] == "open" and sh["global_time_selectable_enabled"] is False
          and sh["selectable_template_vars"] == [] and sh["expiration"] == defs["share"]["expiration"]
          and sh["dashboard_id"] in org.dashboards and sh["dashboard_type"] == "custom_timeboard")
    rec = json.loads(sf.read_text())
    check("share.json records the dashboard, token and public URL",
          rec["dashboard_id"] in org.dashboards and rec["token"] == sh["token"] and rec["public_url"] == sh["public_url"])
    check("the public URL is printed", sh["public_url"] in out)

    print("== --apply again: in place ==")
    rc, out = run(["--apply"] + AWS, org, env=WRITE, share_file=sf)
    check("exit 0, still one dashboard and one share", rc == 0 and len(org.dashboards) == 1 and len(org.shares) == 1)
    check("the share was updated with PUT, not created again",
          ("PUT", f"/api/v1/dashboard/public/{rec['token']}") in org.writes()
          and org.writes().count(("POST", "/api/v1/dashboard/public")) == 1)
    check("the URL is unchanged", json.loads(sf.read_text())["public_url"] == rec["public_url"])

    print("== --check ==")
    before, start = len(org.writes()), len(org.calls)
    rc, out = run(["--check"] + AWS, org, share_file=sf)
    check("passes on what apply built, with the read-only key, writing nothing",
          rc == 0 and len(org.writes()) == before
          and all(k == "READ-ONLY-APP" for _, _, k, _ in org.calls[start:]), out)
    rc, out = run(["--check"] + AWS, org, share_file=sf, public=lambda url: 403)
    check("fails when the public URL asks for a login", rc == 1 and "403" in out)
    org.shares[rec["token"]]["share_type"] = "invite"
    rc, out = run(["--check"] + AWS, org, share_file=sf)
    check("fails when the share was made invite-only", rc == 1 and "share_type" in out)
    org.shares[rec["token"]]["share_type"] = "open"
    org.shares[rec["token"]]["status"] = "paused"
    rc, out = run(["--check"] + AWS, org, share_file=sf)
    check("fails when the share is paused", rc == 1 and "status" in out)
    org.shares[rec["token"]]["status"] = "active"
    org.shares[rec["token"]]["expiration"] = None
    rc, out = run(["--check"] + AWS, org, share_file=sf)
    check("fails when the share has no expiration", rc == 1 and "expiration" in out)
    org.shares[rec["token"]]["expiration"] = defs["share"]["expiration"]
    live = org.dashboards[rec["dashboard_id"]]
    live["widgets"][1]["definition"]["requests"][0]["queries"][0]["query"] = "sum:x{*}"
    rc, out = run(["--check"] + AWS, org, share_file=sf)
    check("fails when a query was edited in the UI", rc == 1 and "queries differ" in out)
    sf.unlink()
    rc, out = run(["--check"] + AWS, FakeOrg(), share_file=sf)
    check("fails, saying so, when the view has not been built", rc == 1 and "has not been built" in out)

print()
if failures:
    print(f"{len(failures)} room view check(s) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All room view checks passed.")
