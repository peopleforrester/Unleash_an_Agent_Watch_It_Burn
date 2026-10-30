# ABOUTME: Render gate for #320: the collector's exemptions that keep one interaction one root name the hop that
# ABOUTME: is really deployed, and the workshop-agent turns the a2a-sdk spans off at source.
"""The offline half of verify/test_collector_one_root_e2e.py.

The E2E runs the interaction through the real collector. What it cannot see is whether the exemptions still name
the deployment. The gateway's A2A span is kept by its server.port, 3000, because that is the port
guard-proxy's AGENT_URL dials and the gateway bind that proxies to workshop-agent. If either moved, the rule would
quietly stop matching, the gateway span would be dropped with the MCP noise again, and the agent's work would be
a second root in the student's trace. So the three are held to one port here.

And the workshop-agent sets OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false, so its trace has no a2a-sdk spans on the
path from the server span to `invocation` for the collector to drop.
"""
from __future__ import annotations

import pathlib
import re
import sys
from urllib.parse import urlparse

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
RESOURCES = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text()) if d]
GATEWAY = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/agentgateway.yaml").read_text()) if d]
VALUES = yaml.safe_load((REPO / "gitops/otel-collector/values.yaml").read_text())

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


rules = VALUES["config"]["processors"]["filter/drop_noise"]["traces"]["span"]

print("== the gateway's A2A span is kept by the port guard-proxy dials ==")
proxy = next(d for d in RESOURCES if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
env = {e["name"]: e.get("value") for c in proxy["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])}
agent_port = urlparse(env.get("AGENT_URL") or "").port
check("guard-proxy's AGENT_URL names a port", agent_port is not None, f"AGENT_URL={env.get('AGENT_URL')!r}")
config = yaml.safe_load(next(d for d in GATEWAY if d.get("kind") == "ConfigMap"
                             and d["metadata"]["name"] == "agentgateway-config")["data"]["config.yaml"])
a2a_binds = [b["port"] for b in config["binds"]
             if any(be.get("host", "").startswith("workshop-agent.")
                    for l in b.get("listeners", []) for r in l.get("routes", []) for be in r.get("backends", []))]
check("the gateway bind that proxies to workshop-agent is the port AGENT_URL dials", a2a_binds == [agent_port],
      f"binds to workshop-agent: {a2a_binds}, AGENT_URL port: {agent_port}")
gateway_rules = [r for r in rules if "burritobot-gateway" in r]
check("one filter rule drops the gateway's spans", len(gateway_rules) == 1, f"{gateway_rules}")
# The gateway names the bind's port in server.port, an int, and sets no http.host (read from Tempo on
# burritobot-private 2026-10-30, #703); a rule keyed on http.host never matched and dropped the A2A hop.
host = re.search(r'not attributes\["server\.port"\] == (\d+)', gateway_rules[0] if gateway_rules else "")
check("it exempts the gateway span whose server.port is AGENT_URL's port",
      host is not None and int(host.group(1)) == agent_port, f"{gateway_rules}")
check("and no longer keys on http.host, which the gateway does not set", "http.host" not in (gateway_rules[0] if gateway_rules else ""))

print("== kagent's server span for the message, and the a2a request handlers, are exempt ==")
agent_http = [r for r in rules if "burritobot-agent" in r and "(GET|POST|" in r]
check("one filter rule drops the agent's HTTP spans", len(agent_http) == 1, f"{agent_http}")
check("it exempts a POST server span that has a parent",
      bool(agent_http) and agent_http[0].endswith(
          'and not (kind == SPAN_KIND_SERVER and IsMatch(name, "^POST( |$)") and not IsRootSpan())'),
      f"{agent_http}")
a2a = [r for r in rules if r.startswith('IsMatch(name, "^a2a[.]")')]
check("the a2a rule exempts the request handlers that have a parent",
      a2a == ['IsMatch(name, "^a2a[.]") and (IsRootSpan() or not IsMatch(name, "^a2a[.]server[.]request_handlers[.]"))'],
      f"{a2a}")

print("== the workshop-agent emits no a2a-sdk spans ==")
agent = next(d for d in RESOURCES if d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent")
agent_env = {e["name"]: e.get("value") for e in agent["spec"]["declarative"]["deployment"]["env"]}
check("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED is \"false\"",
      agent_env.get("OTEL_INSTRUMENTATION_A2A_SDK_ENABLED") == "false",
      f"{agent_env.get('OTEL_INSTRUMENTATION_A2A_SDK_ENABLED')!r}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector one-root render checks passed.")
