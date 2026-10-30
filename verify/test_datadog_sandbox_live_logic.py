# ABOUTME: Offline tests for test_datadog_sandbox_live.py (#629): a fake sandbox org that meets Whitney's rules passes,
# ABOUTME: and each way of breaking one (a stray service, a missing env, a silent cluster, a renamed ml_app) fails it.
"""Nothing here reaches Datadog or AWS. The org is a fake fleet_monitors.Datadog transport answering the two
endpoints the live check reads, /api/v1/query and /api/v2/logs/analytics/aggregate, and refuses anything else. A live check that
passes whatever it is fed proves nothing on the day it finally runs, so each break below must turn it red.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sandbox_live", HERE / "test_datadog_sandbox_live.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
fm = live.fm

ENV = "burritobot-kubecon-na-26"
PUB, PRIV = "burritobot-public", "burritobot-private"


def series(**tags) -> dict:
    return {"tag_set": [f"{k}:{v}" for k, v in tags.items()], "pointlist": [[0, 1.0]]}


GOOD = {
    "datadog.agent.running": [series(kube_cluster_name=PUB, env=ENV), series(kube_cluster_name=PRIV, env=ENV)],
    "traces.span.metrics.calls": [series(kube_cluster_name=c, service=s, env=ENV)
                                  for c in (PUB, PRIV) for s in ("burritobot", "burritobot-gateway", "burritobot-agent")],
    "ml_obs.trace": [series(ml_app="burritobot")],
    "logs": [{"kube_cluster_name": c, "service": s, "env": ENV}
             for c in (PUB, PRIV) for s in ("burritobot", "burritobot-agent", "burritobot-coredns")],
}


class FakeOrg:
    def __init__(self, data: dict):
        self.data = data
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, headers: dict, body: bytes | None):
        path, _, qs = url.partition("?")
        self.calls.append((method, path))
        if path.endswith("/api/v1/query"):
            q = urllib.parse.parse_qs(qs)["query"][0]
            metric = q.split(":", 1)[1].split("{", 1)[0]
            return 200, {"series": self.data.get(metric, [])}
        if path.endswith("/api/v2/logs/analytics/aggregate"):
            req = json.loads(body)
            assert req["filter"]["query"] == "kube_cluster_name:burritobot-*", req
            return 200, {"data": {"buckets": [{"by": b, "computes": {"c0": 3}} for b in self.data["logs"]]}}
        return 404, {"errors": [f"unexpected {method} {path}"]}


failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def judge(data: dict) -> tuple[list[str], list[str]]:
    org = FakeOrg(data)
    out: list[str] = []
    failed = live.run(fm.Datadog("datadoghq.com", "api", "app", http=org), minutes=60, now=1_800_000_000, say=out.append)
    return failed, out


print("== a sandbox org that meets every rule ==")
failed, out = judge(GOOD)
check("passes every check", failed == [])
check("checks the Agents, the logs, the spans and ml_app", sum(line.startswith("==") for line in out) == 4)


def broken(name: str, mutate, expect: str) -> None:
    data = copy.deepcopy(GOOD)
    mutate(data)
    failed, out = judge(data)
    check(f"{name}: fails '{expect}'", any(expect in f for f in failed))
    return out


print("== each break turns it red ==")
out = broken("kagent's workshop_agent span service (#634)",
             lambda d: d["traces.span.metrics.calls"].append(series(kube_cluster_name=PUB, service="workshop_agent", env=ENV)),
             "spans: every group's service")
check("and names the stray service", any("service:workshop_agent" in line for line in out))
broken("a log with no service", lambda d: d["logs"].append({"kube_cluster_name": PRIV, "service": "(none)", "env": ENV}),
       "logs: every group's service")
broken("a bare burritobot- service", lambda d: d["logs"].append({"kube_cluster_name": PRIV, "service": "burritobot-", "env": ENV}),
       "logs: every group's service")
broken("a log under the old env", lambda d: d["logs"].append({"kube_cluster_name": PUB, "service": "burritobot-agent",
                                                              "env": "production"}),
       "logs: every group carries env")
broken("an Agent with no env", lambda d: d["datadog.agent.running"].append(series(kube_cluster_name=PRIV)),
       "Agent: every group carries env")
broken("burritobot-private silent", lambda d: d.update({"datadog.agent.running": d["datadog.agent.running"][:1]}),
       "Agent: burritobot-private reports")
broken("both clusters named burritobot", lambda d: d.update({"datadog.agent.running": [series(kube_cluster_name="burritobot",
                                                                                              env=ENV)]}),
       "Agent: burritobot-public reports")
broken("no /chat on burritobot-public", lambda d: d.update({"traces.span.metrics.calls": [
    s for s in d["traces.span.metrics.calls"] if f"kube_cluster_name:{PUB}" not in s["tag_set"]]}),
       "spans: burritobot-public reports")
broken("the root service renamed burritobot-guard-proxy", lambda d: d.update({"ml_obs.trace": [series(ml_app="burritobot-guard-proxy")]}),
       "as ml_app burritobot")
broken("a second ml_app beside burritobot", lambda d: d["ml_obs.trace"].append(series(ml_app="workshop_agent")),
       "no other ml_app")

print("== a refused query is a failure, not a pass ==")
try:
    live.run(fm.Datadog("datadoghq.com", "api", "app", http=lambda *a: (403, {"errors": ["Forbidden"]})),
             now=1_800_000_000, say=lambda _: None)
    check("a 403 raises", False)
except RuntimeError as exc:
    check("a 403 raises, naming the status", "403" in str(exc))

print("== the live file is in the E2E suite, the logic test is not ==")
check("test_datadog_sandbox_live.py carries '# SUITE: e2e'",
      "\n# SUITE: e2e" in (HERE / "test_datadog_sandbox_live.py").read_text())
check("this file does not", not any(line.startswith("# SUITE: e2e") for line in pathlib.Path(__file__).read_text().splitlines()))

print(f"\n  {'all passed' if not failures else f'{len(failures)} failed'}")
sys.exit(1 if failures else 0)
