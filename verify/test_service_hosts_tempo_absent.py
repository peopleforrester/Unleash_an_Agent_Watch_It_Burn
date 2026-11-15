# ABOUTME: The live service-hosts test reads "no tempo data source" on an attendee cluster from Grafana's plain
# ABOUTME: GET by uid (404), not from /health, which answers a missing uid with 500, and names the Grafana it read (#544).
"""Why (#544). #475 took Tempo off the attendee profile, and test_service_hosts_live.py was given an attendee
branch that expected HTTP 404 from GET /api/datasources/uid/tempo/health. Grafana 13.2.2, the tag the prometheus
Application pins, answers that path for a uid it does not have with 500 "Unable to load datasource metadata"
(CheckDatasourceHealthWithUID in pkg/api/datasources.go); only GetDataSourceByUID, the plain
GET /api/datasources/uid/<uid>, answers 404 "Data source not found". The research run on #544 read both answers on
watch-it-burn-private on 2026-11-05. So the first correctly built attendee cluster would have failed the live test
on a right platform.

This holds the attendee branch to the plain GET and the 404, and holds the Grafana version its comment names to the
tag the chart pins, so a Grafana bump points back at the comment and the API behaviour it rests on.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
LIVE_PATH = REPO / "verify/test_service_hosts_live.py"
PROM_PATH = REPO / "gitops/bootstrap/apps/prometheus.yaml"
LIVE = LIVE_PATH.read_text(encoding="utf-8")
PROM = yaml.safe_load(PROM_PATH.read_text(encoding="utf-8"))

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


ANCHOR = 'if uid == "tempo" and attendee:'
if ANCHOR not in LIVE:
    sys.exit(f"anchor {ANCHOR!r} is not in {LIVE_PATH.relative_to(REPO)}: the attendee tempo branch moved or was "
             "reworded, so this test cannot find what it holds")
# The branch runs from its `if` to the `continue` that ends it.
branch = LIVE.split(ANCHOR, 1)[1].split("continue", 1)[0]

print("== the attendee branch reads absence from the plain GET by uid ==")
urls = re.findall(r'fetch\(f"([^"]+)"', branch)
check("it requests /api/datasources/uid/{uid} with no /health, and nothing else",
      urls == ["https://grafana-{host}/api/datasources/uid/{uid}"], f"{urls}")
check("it passes only on a 404 that says the data source is not found",
      "status == 404" in branch and '"not found" in body.lower()' in branch, branch.strip()[:300])
check("every other uid is still read on /health and must answer OK",
      'api/datasources/uid/{uid}/health"' in LIVE.split(ANCHOR, 1)[1] and '.get("status") == "OK"' in LIVE)

print("== the Grafana the comment names is the one the chart pins ==")
tag = PROM["spec"]["source"]["helm"]["valuesObject"]["grafana"]["image"]["tag"]
pinned = re.match(r"(\d+\.\d+\.\d+)", tag)
named = re.search(r"Grafana (\d+\.\d+\.\d+)'s", branch)
check("prometheus.yaml pins a Grafana version", bool(pinned), f"tag={tag!r}")
check("the attendee branch's comment names the Grafana version whose API it relies on", bool(named),
      branch.strip()[:300])
if pinned and named:
    check(f"the comment's Grafana {named.group(1)} is the pinned {pinned.group(1)} (on a bump, reread "
          "CheckDatasourceHealthWithUID and GetDataSourceByUID and update the comment)",
          named.group(1) == pinned.group(1))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All service-hosts tempo-absence checks passed.")
