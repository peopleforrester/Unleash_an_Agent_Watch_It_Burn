# ABOUTME: Runs the REAL collector binary on the shipped traces and metrics pipelines (#634): kagent's spans and
# ABOUTME: metrics arrive as service workshop_agent, and nothing may leave the collector outside the burritobot names.
# SUITE: e2e (needs otelcol-contrib at the chart's collector version)
#
# Why the binary. kagent 0.10.1 names its resource after the Agent (workshop_agent) whatever OTEL_SERVICE_NAME says,
# and transform/kagent_service_name maps it back. What matters is the outcome Whitney measures in Datadog: no service
# outside burritobot*, in the spans and in traces.span.metrics.calls, and the noise rules keyed on burritobot-agent
# firing again. Only the real OTTL engine, in the shipped processor order, can say that.
#
# Install: the otelcol-contrib release tarball for OTELCOL_VERSION from
# github.com/open-telemetry/opentelemetry-collector-releases, on PATH or at $OTELCOL_CONTRIB.
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
OTELCOL_VERSION = "0.160.0"  # test_lab_pipeline_collector.py holds this to the pinned chart
sys.path.insert(0, str(REPO / "verify"))
import collector_render  # noqa: E402
failures: list[str] = []


def check(n: str, c: bool) -> None:
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


binary = os.environ.get("OTELCOL_CONTRIB") or shutil.which("otelcol-contrib")
if not binary:
    print("this E2E check runs the real collector and cannot run without it:\n"
          "  - otelcol-contrib is not on PATH and OTELCOL_CONTRIB is not set", file=sys.stderr)
    sys.exit(1)
version = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout.strip()
check(f"the binary is the chart's collector ({version})", version.endswith(OTELCOL_VERSION))

ENV = {"PATH": "/usr/bin:/bin", "WIB_CLUSTER_NAME": "burritobot-public"}
# What kagent's pod sends: its own name, plus the env it merged in (Resource.create keeps those).
KAGENT = {"service.name": "workshop_agent", "service.namespace": "agent", "service.version": "v0.10.1",
          "deployment.environment.name": "burritobot-kubecon-na-26"}
PROXY = {"service.name": "burritobot", "service.version": "1.0.0", "deployment.environment.name": "burritobot-kubecon-na-26"}


def attrs(d: dict) -> list:
    return [{"key": k, "value": {"stringValue": v}} for k, v in d.items()]


def flat(a: list) -> dict:
    return {x["key"]: next(iter(x["value"].values())) for x in a}


def span(name: str, sid: str, parent: str = "", **at) -> dict:
    return {"traceId": "d" * 32, "spanId": sid * 16, "parentSpanId": parent * 16 if parent else "", "name": name,
            "kind": 2, "startTimeUnixNano": "1792815457297000000", "endTimeUnixNano": "1792815457397000000",
            "attributes": attrs(at)}


with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    full = collector_render.collector_config("attendee", True)
    pipes = full["service"]["pipelines"]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    out_t, out_m = tmp / "traces.json", tmp / "metrics.json"
    procs = {k: full["processors"][k] for k in pipes["traces"]["processors"] + pipes["metrics"]["processors"]}
    procs["batch"] = {"timeout": "200ms"}
    cfg = {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
        "processors": procs,
        "connectors": {"span_metrics": {**full["connectors"]["span_metrics"], "metrics_flush_interval": "1s"}},
        "exporters": {"file/t": {"path": str(out_t)}, "file/m": {"path": str(out_m)}},
        "service": {"telemetry": {"metrics": {"level": "none"}}, "pipelines": {
            # The shipped processors in the shipped order; the Datadog exporters become files, and the span_metrics
            # connector stays, because traces.span.metrics.calls is where the stray service was measured.
            "traces": {"receivers": ["otlp"], "processors": pipes["traces"]["processors"], "exporters": ["file/t", "span_metrics"]},
            "metrics": {"receivers": ["otlp", "span_metrics"], "processors": pipes["metrics"]["processors"], "exporters": ["file/m"]}}},
    }
    cf = tmp / "cfg.yaml"
    cf.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    proc = subprocess.Popen([binary, f"--config=file:{cf}"], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def post(path: str, body: dict) -> int:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status

    try:
        deadline = time.time() + 30
        while True:
            try:
                post("/v1/traces", {"resourceSpans": []})
                break
            except OSError:
                if time.time() > deadline or proc.poll() is not None:
                    print((proc.stderr.read() if proc.poll() is not None else "")[-600:], file=sys.stderr)
                    check("the collector starts on the shipped pipelines", False)
                    raise SystemExit(1)
                time.sleep(0.3)
        # One /chat as it reaches the collector: guard-proxy's root, then kagent's spans, the ASGI POST among them.
        chat = {"resourceSpans": [
            {"resource": {"attributes": attrs(PROXY)}, "scopeSpans": [{"scope": {"name": "proxy"}, "spans": [
                span("POST /chat", "1")]}]},
            {"resource": {"attributes": attrs(KAGENT)}, "scopeSpans": [{"scope": {"name": "gcp.vertex.agent"}, "spans": [
                span("invocation", "2", "1"),
                span("invoke_agent workshop_agent", "3", "2", **{"gen_ai.operation.name": "invoke_agent"}),
                span("call_llm", "4", "3"),
                span("POST /", "5", "1", **{"http.method": "POST"})]}]}]}
        token = {"resourceMetrics": [{"resource": {"attributes": attrs(KAGENT)}, "scopeMetrics": [{"scope": {"name": "adk"}, "metrics": [
            {"name": "gen_ai.client.token.usage", "sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": [
                {"asInt": "42", "timeUnixNano": "1792815457397000000", "attributes": attrs({"gen_ai.token.type": "input"})}]}}]}]}]}
        check("one /chat's spans and kagent's token metric are accepted (200)",
              post("/v1/traces", chat) == 200 and post("/v1/metrics", token) == 200)
        deadline = time.time() + 20
        while time.time() < deadline and not (out_t.exists() and out_t.stat().st_size and out_m.exists()
                                              and "traces.span.metrics.calls" in out_m.read_text()
                                              and "gen_ai.client.token.usage" in out_m.read_text()):
            time.sleep(0.3)
        time.sleep(1.5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    spans: dict[str, tuple[dict, dict]] = {}
    for line in (out_t.read_text().splitlines() if out_t.exists() else []):
        for rs in json.loads(line)["resourceSpans"]:
            res = flat(rs["resource"]["attributes"])
            for ss in rs["scopeSpans"]:
                for sp in ss["spans"]:
                    spans[sp["name"]] = (res, flat(sp.get("attributes", [])))
    services = {r["service.name"] for r, _ in spans.values()}
    check(f"the spans' services {sorted(services)} are burritobot and burritobot-agent", services == {"burritobot", "burritobot-agent"})
    agent = spans.get("invoke_agent workshop_agent", ({}, {}))[0]
    check("kagent's span is burritobot-agent and keeps its version and env",
          agent.get("service.name") == "burritobot-agent" and agent.get("service.version") == "v0.10.1"
          and agent.get("deployment.environment.name") == "burritobot-kubecon-na-26")
    check("filter/drop_noise fires on the agent again: its ASGI 'POST /' span is dropped", "POST /" not in spans)
    check("transform/set_llmobs_workflow fires on the agent again: call_llm is stamped invoke_agent",
          spans.get("call_llm", ({}, {}))[1].get("gen_ai.operation.name") == "invoke_agent")
    check("the raw name workshop_agent is in no resource", "workshop_agent" not in json.dumps([r for r, _ in spans.values()]))

    calls, token_services = set(), set()
    for line in (out_m.read_text().splitlines() if out_m.exists() else []):
        for rm in json.loads(line)["resourceMetrics"]:
            res = flat(rm["resource"].get("attributes", []))
            for sm in rm["scopeMetrics"]:
                for m in sm["metrics"]:
                    for dp in (m.get("sum") or {}).get("dataPoints", []):
                        svc = flat(dp.get("attributes", [])).get("service.name") or res.get("service.name")
                        (calls if m["name"] == "traces.span.metrics.calls" else token_services if m["name"] == "gen_ai.client.token.usage" else set()).add(svc)
    check(f"traces.span.metrics.calls carries services {sorted(calls)}, all burritobot*",
          calls == {"burritobot", "burritobot-agent"})
    check(f"kagent's token metric arrives as {sorted(token_services)}", token_services == {"burritobot-agent"})

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All kagent service-name collector checks passed.")
