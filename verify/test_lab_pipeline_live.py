# ABOUTME: Live half of the fleet-analytics path (#150, #587): the lab page's own markers, posted to a real attendee
# ABOUTME: cluster's public /lab-events, arrive in the instructor org as witb.lab.calls, feed the dashboard and pass 6.
# SUITE: e2e
"""Needs node, kubectl, CONTEXT naming an attendee cluster that dual-ships (#242), and the instructor org's keys in
WITB_DD_ADMIN_API_KEY and WITB_DD_ADMIN_APP_KEY (WITB_DD_ADMIN_SITE, default datadoghq.com), the same keys harvest
pass 6 reads. The admin app key is never on a cluster (#272), so it comes from the operator's environment. Every
missing prerequisite is a failure with the reason, never a skip.

What the offline and binary checks (test_lab_events.py, test_lab_events_behaviour.py, test_lab_pipeline_collector.py)
cannot say, one link per section, in the order docs/fleet-analytics.md "Validating on a cluster" lists them:
1. the collector Service exposes the lab receiver on 4319 and its pods run, so the config was accepted;
2. the console's public /lab-events takes what the shipped lab-events.js sends (run under node by
   lab-events-harness.js, as committed) and refuses a GET;
3. those markers arrive in the instructor org as witb.lab.calls, tagged with this cluster's kube_cluster_name and
   by span.name, and nothing of them reaches the student's own org;
4. the fleet-analytics dashboard in the instructor org is the committed fleet-analytics.json, and every one of its
   queries is accepted with this cluster selected, with data wherever the markers just sent should show;
5. harvest pass 6 (scripts/harvest/06-lab-progress.py) turns the result into a lab-progress.csv row for them.

The markers carry a fresh alias (verify-<hex>), so the series found are this run's and no student's. The dashboard is
checked, not applied: applying infra/terraform/dashboards is an operator step with the instructor org's DD_API_KEY and
DD_APP_KEY, and this check fails until the applied dashboard matches the file.

Usage: CONTEXT=<kube-context> WITB_DD_ADMIN_API_KEY=... WITB_DD_ADMIN_APP_KEY=... python3 verify/test_lab_pipeline_live.py
"""
from __future__ import annotations

import base64
import csv
import json
import os
import pathlib
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
CONTEXT = os.environ.get("CONTEXT", "")
ADMIN_API = os.environ.get("WITB_DD_ADMIN_API_KEY", "")
ADMIN_APP = os.environ.get("WITB_DD_ADMIN_APP_KEY", "")
ADMIN_SITE = os.environ.get("WITB_DD_ADMIN_SITE", "datadoghq.com")
# The collector ships the student's own org with DD_SITE "datadoghq.com" (gitops/otel-collector/values.yaml).
STUDENT_SITE = "datadoghq.com"
COLLECTOR_SVC = "otel-collector-opentelemetry-collector"
DASH = json.loads((REPO / "infra/terraform/dashboards/fleet-analytics.json").read_text(encoding="utf-8"))
PASS6 = REPO / "scripts/harvest/06-lab-progress.py"
STUDENT_CLUSTER = re.compile(r"-attendee-\d+$")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All live lab-pipeline checks passed.")


def kubectl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", CONTEXT, *args], capture_output=True, text=True, timeout=timeout)


def dd(site: str, api: str, app: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"https://api.{site}{path}", data=json.dumps(body).encode() if body else None,
                                 headers={"DD-API-KEY": api, "DD-APPLICATION-KEY": app,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {"errors": [e.read().decode(errors="replace")[:300]]}


def metric(site: str, api: str, app: str, q: str, frm: int, to: int) -> tuple[bool, list[dict]]:
    """(accepted, series) for a metrics query over [frm, to]."""
    code, body = dd(site, api, app, "/api/v1/query?" + urllib.parse.urlencode({"from": frm, "to": to, "query": q}))
    ok = code == 200 and body.get("status") != "error"
    if not ok:
        print(f"        {q}: HTTP {code} {body.get('error') or body.get('errors')}")
    return ok, (body.get("series") or []) if ok else []


print("== prerequisites ==")
check("node is on PATH (it runs the shipped lab-events.js)", shutil.which("node") is not None)
check("kubectl is on PATH", shutil.which("kubectl") is not None)
check("CONTEXT names the cluster to check (it is never guessed)", bool(CONTEXT))
check("WITB_DD_ADMIN_API_KEY and WITB_DD_ADMIN_APP_KEY name the instructor org", bool(ADMIN_API and ADMIN_APP))
if failures:
    finish()


def config_value(ns: str, name: str, key: str) -> str:
    got = kubectl("-n", ns, "get", "configmap", name, "-o", f"jsonpath={{.data.{key.replace('.', chr(92) + '.')}}}")
    return got.stdout.strip() if got.returncode == 0 else ""


def secret_value(ns: str, name: str, key: str) -> str:
    got = kubectl("-n", ns, "get", "secret", name, "-o", f"jsonpath={{.data.{key.replace('.', chr(92) + '.')}}}")
    return base64.b64decode(got.stdout).decode() if got.returncode == 0 and got.stdout.strip() else ""


print(f"== on {CONTEXT}: an attendee cluster that dual-ships ==")
CLUSTER = config_value("monitoring", "cluster-identity", "cluster-name")
HOST = config_value("agent", "cluster-identity", "public-host")
check(f"cluster-identity names an attendee cluster ({CLUSTER or 'none'})", bool(STUDENT_CLUSTER.search(CLUSTER)))
check(f"cluster-identity in agent carries the public console host ({HOST or 'none'})", bool(HOST))
check("datadog-admin-secret is in monitoring, so the collector ships the lab markers to the instructor org",
      bool(secret_value("monitoring", "datadog-admin-secret", "api-key")))
STUDENT_API = secret_value("datadog", "datadog-secret", "api-key")
STUDENT_APP = secret_value("datadog", "datadog-secret", "app-key")
check("datadog-secret in datadog carries the student org's api and app keys", bool(STUDENT_API and STUDENT_APP))
check("the student org is not the instructor org (else the absence check below means nothing)",
      bool(STUDENT_API) and STUDENT_API != ADMIN_API)
if failures:
    finish()

print("== 1. the collector runs the lab receiver ==")
svc = kubectl("-n", "monitoring", "get", "svc", COLLECTOR_SVC, "-o", "json")
check(f"Service {COLLECTOR_SVC} is readable", svc.returncode == 0)
spec = json.loads(svc.stdout).get("spec", {}) if svc.returncode == 0 else {}
check("it lists port 4319 (otlp/lab)", any(p.get("port") == 4319 for p in spec.get("ports", [])))
selector = ",".join(f"{k}={v}" for k, v in (spec.get("selector") or {}).items())
pods = kubectl("-n", "monitoring", "get", "pods", "-l", selector, "-o", "json") if selector else None
items = json.loads(pods.stdout).get("items", []) if pods is not None and pods.returncode == 0 else []
check(f"the Service selects collector pods ({len(items)})", bool(items))
check("every collector pod is Running with every container ready (a rejected config CrashLoops it)", bool(items) and all(
    p.get("status", {}).get("phase") == "Running"
    and all(c.get("ready") for c in p.get("status", {}).get("containerStatuses", [])) for p in items))

print(f"== 2. https://{HOST}/lab-events takes what the shipped page sends ==")
h = subprocess.run(["node", str(REPO / "verify/lab-events-harness.js"), str(REPO / "gitops/ai-layer/web/lab-events.js"),
                    "shipped"], capture_output=True, text=True, timeout=60)
posts = [p["body"] for p in json.loads(h.stdout)["posts"]] if h.returncode == 0 else []
check(f"the shipped lab-events.js sends markers ({len(posts)} posts)", bool(posts))
ALIAS = f"verify-{uuid.uuid4().hex[:10]}"
SENT: set[tuple[str, str]] = set()  # (span.name, witb.lab.challenge) of every marker sent
ROLES: set[str] = set()
for body in posts:
    for rs in body["resourceSpans"]:
        for ss in rs["scopeSpans"]:
            for s in ss["spans"]:
                attrs = {a["key"]: a["value"] for a in s["attributes"]}
                attrs["witb.lab.alias"] = {"stringValue": ALIAS}
                s["attributes"] = [{"key": k, "value": v} for k, v in attrs.items()]
                SENT.add((s["name"], attrs.get("witb.lab.challenge", {}).get("stringValue", "")))
                ROLES.add(attrs.get("witb.lab.role", {}).get("stringValue", ""))
URL = f"https://{HOST}/lab-events"
TLS = ssl.create_default_context()


def send(method: str, data: bytes | None) -> int:
    req = urllib.request.Request(URL, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=TLS) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError as e:
        print(f"        {method} {URL}: {e}")
        return 0


START = int(time.time())
codes = [send("POST", json.dumps(b).encode()) for b in posts]
check(f"every POST answers 200 ({codes})", bool(codes) and all(c == 200 for c in codes))
check("a GET is refused with 403", send("GET", None) == 403)

print(f"== 3. witb.lab.calls reaches the instructor org tagged kube_cluster_name:{CLUSTER} ==")
scope = f"kube_cluster_name:{CLUSTER},witb.lab.alias:{ALIAS}"
names: set[str] = set()
deadline = time.time() + 300
while time.time() < deadline and names != {n for n, _ in SENT}:
    time.sleep(20)
    ok, series = metric(ADMIN_SITE, ADMIN_API, ADMIN_APP, f"sum:witb.lab.calls{{{scope}}} by {{span.name}}.as_count()",
                        START - 300, int(time.time()))
    names = {t.partition(":")[2] for s in series for t in s.get("tag_set", []) if t.startswith("span.name:")}
check(f"every marker sent is there by span.name ({sorted(names)})", names == {n for n, _ in SENT})
ok, series = metric(STUDENT_SITE, STUDENT_API, STUDENT_APP, f"sum:witb.lab.calls{{{scope}}}.as_count()",
                    START - 300, int(time.time()))
check("the student org accepts the query and has no witb.lab.calls for them", ok and not series)
code, body = dd(STUDENT_SITE, STUDENT_API, STUDENT_APP, "/api/v2/spans/events/search", {"data": {
    "type": "search_request", "attributes": {"filter": {"query": f"service:burritobot-lab @witb.lab.alias:{ALIAS}",
                                                        "from": "now-30m", "to": "now"}, "page": {"limit": 1}}}})
check("the student org has no burritobot-lab spans for them", code == 200 and not body.get("data"))


def widget_queries(widgets: list[dict]):
    """(data_source, query) of every widget, group widgets included."""
    for w in widgets:
        d = w.get("definition", {})
        for r in d.get("requests", []) if isinstance(d.get("requests"), list) else []:
            for q in r.get("queries", []):
                yield q.get("data_source"), q.get("query") or (q.get("search") or {}).get("query", "")
        yield from widget_queries(d.get("widgets", []))


print("== 4. the fleet-analytics dashboard ==")
want = sorted(widget_queries(DASH["widgets"]))
code, listing = dd(ADMIN_SITE, ADMIN_API, ADMIN_APP, "/api/v1/dashboard")
ids = [d["id"] for d in listing.get("dashboards", []) if d.get("title") == DASH["title"]] if code == 200 else []
check(f"the instructor org has one dashboard titled {DASH['title']!r} (apply infra/terraform/dashboards)", len(ids) == 1)
code, live = dd(ADMIN_SITE, ADMIN_API, ADMIN_APP, f"/api/v1/dashboard/{ids[0]}") if len(ids) == 1 else (0, {})
check("its widgets run the committed fleet-analytics.json's queries", code == 200 and sorted(
    widget_queries(live.get("widgets", []))) == want)
check("its template variables are the committed ones", code == 200 and [
    (v.get("name"), v.get("prefix"), v.get("default")) for v in live.get("template_variables", [])] == [
    (v["name"], v["prefix"], v["default"]) for v in DASH["template_variables"]])

check(f"the markers carry one role ({sorted(ROLES)})", len(ROLES) == 1)
sub = {"$cluster": f"kube_cluster_name:{CLUSTER}", "$role": f"witb.lab.role:{min(ROLES, default='')}"}
now = int(time.time())
for source, q in want:
    q = re.sub(r"\$(cluster|role)\b", lambda m: sub[m.group(0)], q)
    if source == "metrics":
        ok, series = metric(ADMIN_SITE, ADMIN_API, ADMIN_APP, q, START - 300, now)
        ev = re.search(r"span\.name:(lab\.[a-z.]+)", q)
        ch = re.search(r"witb\.lab\.challenge:(\d+)", q)
        # Data is required only where this run's markers fall inside the widget's filter; elsewhere a real
        # student on the same cluster may or may not have produced some, so acceptance is all that is asserted.
        expect = "witb.lab.calls" in q and ev is not None and any(
            n == ev.group(1) and (ch is None or c == ch.group(1)) for n, c in SENT)
        check(f"{'data for' if expect else 'accepted:'} {q}", ok and (bool(series) or not expect))
    else:
        code, _ = dd(ADMIN_SITE, ADMIN_API, ADMIN_APP, "/api/v2/logs/events/search", {
            "filter": {"query": q, "from": "now-1h", "to": "now"}, "page": {"limit": 1}})
        check(f"accepted (logs): {q}", code == 200)

print("== 5. harvest pass 6 reads them back ==")
event = f"verify-lab-pipeline-{ALIAS}"
out = REPO / ".harvest" / event
try:
    run = subprocess.run([sys.executable, str(PASS6)], capture_output=True, text=True, timeout=300, env={
        **os.environ, "WIB_EVENT": event, "WIB_FROM": str(START - 300), "WIB_TO": str(int(time.time()))})
    print("        " + (run.stdout + run.stderr).strip().replace("\n", "\n        "))
    check("06-lab-progress.py exits 0", run.returncode == 0)
    csv_path = out / "lab-progress.csv"
    rows = [r for r in csv.DictReader(csv_path.open(encoding="utf-8")) if r["alias"] == ALIAS] if csv_path.exists() else []
    check(f"lab-progress.csv has one row for {ALIAS} on {CLUSTER}", len(rows) == 1 and rows[0]["cluster"] == CLUSTER)
    fixed = sorted({c for n, c in SENT if n == "lab.control.installed"}, key=int)
    check(f"that row has the fixes the page measured on ({';'.join(fixed)})",
          len(rows) == 1 and rows[0]["fixed"] == ";".join(fixed))
    check("LAB-PROGRESS.md was written", (out / "LAB-PROGRESS.md").exists())
finally:
    # Synthetic markers, not an event's data: nothing of this run stays in .harvest/.
    shutil.rmtree(out, ignore_errors=True)

finish()
