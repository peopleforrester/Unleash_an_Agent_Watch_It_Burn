# ABOUTME: Runs the real otelcol-contrib on each profile's shipped traces and metrics pipelines (#634): kagent's spans
# ABOUTME: and metrics arrive as service workshop_agent, and nothing may leave the collector outside the burritobot names.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""No service outside burritobot* leaves the collector after one /chat.

kagent 0.10.1 names its resource after the Agent (workshop_agent) whatever OTEL_SERVICE_NAME says: configure_tracing
in kagent-core's tracing/_utils.py passes service.name to Resource.create, which outranks the env, and _config.py
turns KAGENT_NAME's "-" into "_". transform/kagent_service_name maps it back. What Whitney measures in Datadog is the
outcome: the spans' services and the services on traces.span.metrics.calls, both after one /chat on attackme (the
burn profile). The noise rules keyed on burritobot-agent have to fire on the agent's spans as well. Only the real
OTTL engine, in each profile's shipped processor order, can say all of that.

The spans go in as kagent sends them, with workshop_agent and the env it merges in (service.version and
deployment.environment.name survive Resource.create). The Datadog exporters become file exporters; the span_metrics
connector stays, because traces.span.metrics.calls is where the stray service was measured.

Fails when the binary is missing: run verify/fetch-e2e-tools.sh (verify/run-e2e-tools.sh does).
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import PROFILE_APP, REPO, collector_config, feature_gate_args  # noqa: E402

OTELCOL = REPO / "verify/.tools/bin/otelcol-contrib"
LOCK = REPO / "verify/e2e-tools.lock"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


if not os.access(OTELCOL, os.X_OK):
    print(f"FAIL: {OTELCOL} is missing; run bash verify/fetch-e2e-tools.sh (this is a failure, not a skip)")
    sys.exit(1)
pinned = next(line.split()[1] for line in LOCK.read_text().splitlines() if line.startswith("otelcol-contrib "))
version = subprocess.run([str(OTELCOL), "--version"], capture_output=True, text=True, check=True).stdout.strip()
check(f"the binary is the pinned {pinned} ({version})", version.endswith(" " + pinned.lstrip("v")))

INTERNAL, SERVER, CLIENT = 1, 2, 3
ENV = {"PATH": "/usr/bin:/bin", "WIB_CLUSTER_NAME": "burritobot-public"}
# What kagent's pod sends: its own name, plus the env Resource.create merged in.
KAGENT = {"service.name": "workshop_agent", "service.namespace": "agent", "service.version": "v0.10.1",
          "deployment.environment.name": "burritobot-kubecon-na-26"}
PROXY = {"service.name": "burritobot", "service.version": "1.0.0", "deployment.environment.name": "burritobot-kubecon-na-26"}
MODEL = "us.amazon.nova-pro-v1:0"


def attrs(d: dict) -> list:
    return [{"key": k, "value": {"stringValue": v}} for k, v in d.items()]


def flat(a: list) -> dict:
    return {x["key"]: next(iter(x["value"].values())) for x in a}


def span(name: str, sid: str, parent: str, kind: int, **at) -> dict:
    return {"traceId": "d" * 32, "spanId": sid * 16, "parentSpanId": parent * 16 if parent else "", "name": name,
            "kind": kind, "startTimeUnixNano": "1792815457297000000", "endTimeUnixNano": "1792815457397000000",
            "attributes": attrs(at)}


# One /chat as it reaches the collector: guard-proxy's root, then kagent's spans. The last two are noise that
# filter/drop_noise removes only when it sees burritobot-agent: an ASGI send leaf and the AWS SDK's empty chat leaf.
CHAT = {"resourceSpans": [
    {"resource": {"attributes": attrs(PROXY)}, "scopeSpans": [{"scope": {"name": "proxy"}, "spans": [
        span("POST /chat", "1", "", SERVER)]}]},
    {"resource": {"attributes": attrs(KAGENT)}, "scopeSpans": [{"scope": {"name": "gcp.vertex.agent"}, "spans": [
        span("POST /", "2", "1", SERVER, **{"http.method": "POST", "http.route": "/"}),
        span("invocation", "3", "2", INTERNAL),
        span("invoke_agent workshop_agent", "4", "3", INTERNAL, **{"gen_ai.operation.name": "invoke_agent"}),
        span("call_llm", "5", "4", INTERNAL),
        span(f"generate_content {MODEL}", "6", "5", INTERNAL, **{"gen_ai.operation.name": "generate_content"}),
        span("POST / http send", "7", "2", INTERNAL),
        span(f"chat {MODEL}", "8", "6", CLIENT)]}]}]}
TOKEN = {"resourceMetrics": [{"resource": {"attributes": attrs(KAGENT)}, "scopeMetrics": [{"scope": {"name": "adk"}, "metrics": [
    {"name": "gen_ai.client.token.usage", "sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": [
        {"asInt": "42", "timeUnixNano": "1792815457397000000", "attributes": attrs({"gen_ai.token.type": "input"})}]}}]}]}]}


def run(profile: str, tmp: pathlib.Path) -> tuple[dict, set, set]:
    """One /chat and one token metric through the profile's pipelines; returns spans by name and metric services."""
    full = collector_config(profile, True)
    pipes = full["service"]["pipelines"]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    out_t, out_m = tmp / f"{profile}-traces.json", tmp / f"{profile}-metrics.json"
    procs = {k: full["processors"][k] for k in pipes["traces"]["processors"] + pipes["metrics"]["processors"]}
    procs["batch"] = {"timeout": "200ms"}
    cfg = {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
        "processors": procs,
        "connectors": {"span_metrics": {**full["connectors"]["span_metrics"], "metrics_flush_interval": "1s"}},
        "exporters": {"file/t": {"path": str(out_t)}, "file/m": {"path": str(out_m)}},
        "service": {"telemetry": {"metrics": {"level": "none"}}, "pipelines": {
            "traces": {"receivers": ["otlp"], "processors": pipes["traces"]["processors"], "exporters": ["file/t", "span_metrics"]},
            "metrics": {"receivers": ["otlp", "span_metrics"], "processors": pipes["metrics"]["processors"], "exporters": ["file/m"]}}},
    }
    cf = tmp / f"{profile}-cfg.yaml"
    cf.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    # stderr goes to a file: a pipe nobody reads fills and blocks a collector that logs, at shutdown too (#1012).
    log = tmp / f"{profile}-stderr.log"
    log_f = log.open("w", encoding="utf-8")
    proc = subprocess.Popen([str(OTELCOL), f"--config=file:{cf}", *feature_gate_args(profile)], env=ENV, stdout=subprocess.DEVNULL,
                            stderr=log_f, text=True)

    def post(path: str, body: dict) -> int:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status

    try:
        # A minute to answer: run 18059 saw one start with no answer in 30s and nothing on stderr (#1012).
        deadline = time.time() + 60
        while True:
            try:
                post("/v1/traces", {"resourceSpans": []})
                break
            except OSError:
                if time.time() > deadline or proc.poll() is not None:
                    code = proc.poll()
                    said = log.read_text(encoding="utf-8", errors="replace")[-600:]
                    check(f"{profile}: the collector starts on the shipped pipelines", False,
                          f"exited {code}: {said}" if code is not None else f"no answer on {port} in 60s: {said}")
                    return {}, set(), set()
                time.sleep(0.3)
        check(f"{profile}: one /chat's spans and kagent's token metric are accepted (200)",
              post("/v1/traces", CHAT) == 200 and post("/v1/metrics", TOKEN) == 200)
        deadline = time.time() + 20
        while time.time() < deadline and not (out_t.exists() and out_t.stat().st_size and out_m.exists()
                                              and "traces.span.metrics.calls" in out_m.read_text()
                                              and "gen_ai.client.token.usage" in out_m.read_text()):
            time.sleep(0.3)
        time.sleep(1.5)
    finally:
        # A killed collector leaves its file exporter's buffered last line cut off, and run 18059's tier read such a
        # line as a JSONDecodeError. So it gets a minute to stop on SIGTERM, which flushes the files; a kill is waited
        # on and failed by name, and the cut-off output is never parsed (#1012).
        proc.terminate()
        try:
            proc.wait(timeout=60)
            stopped = True
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            stopped = False
        log_f.close()
    check(f"{profile}: the collector stops on SIGTERM within 60s, so its file output is whole", stopped,
          "killed; its output is not read")
    if not stopped:
        return {}, set(), set()

    spans: dict[str, tuple[dict, dict]] = {}
    for line in (out_t.read_text().splitlines() if out_t.exists() else []):
        for rs in json.loads(line)["resourceSpans"]:
            res = flat(rs["resource"]["attributes"])
            for ss in rs["scopeSpans"]:
                for sp in ss["spans"]:
                    spans[sp["name"]] = (res, flat(sp.get("attributes", [])))
    calls, tokens = set(), set()
    for line in (out_m.read_text().splitlines() if out_m.exists() else []):
        for rm in json.loads(line)["resourceMetrics"]:
            res = flat(rm["resource"].get("attributes", []))
            for sm in rm["scopeMetrics"]:
                for m in sm["metrics"]:
                    for dp in (m.get("sum") or {}).get("dataPoints", []):
                        svc = flat(dp.get("attributes", [])).get("service.name") or res.get("service.name")
                        if m["name"] == "traces.span.metrics.calls":
                            calls.add(svc)
                        elif m["name"] == "gen_ai.client.token.usage":
                            tokens.add(svc)
    return spans, calls, tokens


with tempfile.TemporaryDirectory() as d:
    for profile in PROFILE_APP:
        print(f"== {profile}: one /chat through the shipped pipelines ==")
        spans, calls, tokens = run(profile, pathlib.Path(d))
        services = {r["service.name"] for r, _ in spans.values()}
        check(f"{profile}: the spans' services {sorted(services)} are burritobot and burritobot-agent",
              services == {"burritobot", "burritobot-agent"})
        agent = spans.get("invoke_agent workshop_agent", ({}, {}))[0]
        check(f"{profile}: kagent's span is burritobot-agent and keeps its version and env",
              agent.get("service.name") == "burritobot-agent" and agent.get("service.version") == "v0.10.1"
              and agent.get("deployment.environment.name") == "burritobot-kubecon-na-26", json.dumps(agent))
        check(f"{profile}: filter/drop_noise fires on the agent: its ASGI send span and empty chat span are dropped",
              "POST / http send" not in spans and f"chat {MODEL}" not in spans, sorted(spans))
        check(f"{profile}: the agent's parented server span stays, so the trace keeps one root (#320)", "POST /" in spans)
        check(f"{profile}: transform/set_llmobs_workflow fires on the agent: call_llm is stamped invoke_agent",
              spans.get("call_llm", ({}, {}))[1].get("gen_ai.operation.name") == "invoke_agent")
        check(f"{profile}: the raw name workshop_agent is in no resource",
              "workshop_agent" not in json.dumps([r for r, _ in spans.values()]))
        check(f"{profile}: traces.span.metrics.calls carries services {sorted(calls)}, all burritobot*",
              calls == {"burritobot", "burritobot-agent"})
        check(f"{profile}: kagent's token metric arrives as {sorted(tokens)}", tokens == {"burritobot-agent"})

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All kagent service-name collector checks passed.")
