# ABOUTME: The workshop-agent's OTLP log exporter names its URL with the /v1/logs path, and every profile's collector
# ABOUTME: has a logs pipeline that serves that path and drops what it gets (#903).
"""The agent's log exporter has to hit /v1/logs, and the collector has to answer it.

kagent 0.10.1's Go ADK builds its log exporter with otlploghttp.WithEndpointURL(endpoint), which keeps the URL's
path exactly as given. It reads OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, then OTEL_LOGS_EXPORTER_OTLP_ENDPOINT, then the base
OTEL_EXPORTER_OTLP_ENDPOINT the OTel Operator injects from the Instrumentation CR, which has no path. On that base
URL every batch went to "/", and the pod logged "failed to send logs to http://...:4318: 404 Not Found" about once a
second while it worked. The fix is the logs endpoint on the Agent with its path, and a logs pipeline the collector
states itself instead of inheriting it from the chart's defaults. verify/test_agent_otlp_logs_collector.py runs the
real collector on it.
"""
from __future__ import annotations

import pathlib
import sys
import urllib.parse

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import PROFILE_APP, REPO, collector_config  # noqa: E402

AGENT = REPO / "gitops/workshop-agent/agent.yaml"
INSTR = REPO / "gitops/ai-layer-otel/instrumentation.yaml"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


agent = next(d for d in yaml.safe_load_all(AGENT.read_text(encoding="utf-8")) if d and d.get("kind") == "Agent")
env = {e["name"]: e.get("value") for e in agent["spec"]["declarative"]["deployment"].get("env", [])}
instr = yaml.safe_load(INSTR.read_text(encoding="utf-8"))
ienv = {e["name"]: e.get("value") for e in instr["spec"].get("env", [])}
base = instr["spec"]["exporter"]["endpoint"]

print("== the agent's log exporter is given a URL with the /v1/logs path ==")
logs_url = env.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
check("the Agent sets OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", bool(logs_url), str(sorted(env)))
u = urllib.parse.urlsplit(logs_url or "")
check(f"its path is /v1/logs ({u.path!r}), since kagent's exporter sends to the path it is given", u.path == "/v1/logs")
check(f"it is the Instrumentation CR's endpoint {base} plus /v1/logs, the same collector the traces go to",
      logs_url == base.rstrip("/") + "/v1/logs", str(logs_url))
check("the base endpoint the Operator injects has no path, which is what sent the batches to '/'",
      urllib.parse.urlsplit(base).path in ("", "/"), base)
check("OTEL_LOGS_EXPORTER_OTLP_ENDPOINT, which kagent reads before the base endpoint, is not set to another URL",
      "OTEL_LOGS_EXPORTER_OTLP_ENDPOINT" not in env)
proto = env.get("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL") or env.get("OTEL_EXPORTER_OTLP_PROTOCOL") \
    or ienv.get("OTEL_EXPORTER_OTLP_PROTOCOL")
check(f"the logs protocol is http/protobuf ({proto}), the branch that builds the HTTP exporter the URL is for",
      proto == "http/protobuf")

print("== every profile's collector serves /v1/logs on that port and drops what it gets ==")
for profile in PROFILE_APP:
    for secret in (False, True):
        label = f"{profile} {'with' if secret else 'without'} datadog-secret"
        cfg = collector_config(profile, datadog_secret=secret)
        logs = (cfg.get("service") or {}).get("pipelines", {}).get("logs")
        check(f"{label}: there is a logs pipeline", isinstance(logs, dict))
        if not isinstance(logs, dict):
            continue
        check(f"{label}: it takes the otlp receiver", "otlp" in (logs.get("receivers") or []), str(logs))
        check(f"{label}: it exports to debug alone, so the gen_ai events in the records leave nowhere",
              logs.get("exporters") == ["debug"], str(logs.get("exporters")))
        declared = set(cfg.get("processors") or {})
        check(f"{label}: its processors are declared", set(logs.get("processors") or []) <= declared,
              str(logs.get("processors")))
        http = cfg["receivers"]["otlp"]["protocols"]["http"]
        check(f"{label}: the otlp receiver's HTTP port is the URL's ({u.port})",
              http.get("endpoint", "").rsplit(":", 1)[-1] == str(u.port), str(http))
        check(f"{label}: the receiver keeps the default logs path, /v1/logs",
              http.get("logs_url_path", "/v1/logs") == "/v1/logs", str(http))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All agent OTLP logs checks passed.")
