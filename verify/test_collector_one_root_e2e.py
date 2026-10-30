# ABOUTME: Runs one BurritoBot interaction's spans through the real otelcol-contrib with each profile's traces
# ABOUTME: processors (#320) and reads what the exporter receives: one root, every parent present, the noise gone.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""One interaction is one root, after filter/drop_noise has done its work.

#320: a student opening their interaction in Agent Observability got "Trace contains multiple root spans" and a
fragment. guard-proxy, agentgateway and kagent all carry the W3C context across their hops, which is why the two
roots shared a trace id. What broke the parent link was the collector. The hop from guard-proxy to kagent's
`invocation` passes through three kinds of span the noise filter dropped: agentgateway's span for the A2A request
(every gateway span but tools/call went, #265), kagent's ASGI server span for that request (every HTTP verb went,
#286), and the a2a-sdk request-handler spans (every a2a.* went, #264). With them gone, `invocation` named a
parent nothing exported, and Datadog drew it as a second root.

The spans below are the interaction as the three components emit it, with the span names, kinds and attributes
read from their source at the pinned versions: agentgateway v1.5.0 (crates/agentgateway/src/telemetry/trc.rs and
log.rs: one SERVER span per request, named "<method> <path match>", http.host the request's Host), kagent v0.10.1
(kagent-core tracing/_utils.py: FastAPIInstrumentor on the agent's app) and a2a-sdk 0.3.26, kagent's lock
(request_handlers/*: trace_class on JSONRPCHandler and DefaultRequestHandler, whose _run_event_stream task runs
the agent executor, and ADK's `invocation` under it). They go in twice: once with the a2a-sdk spans, as a pod that
does not honour OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false emits them, and once without, as the workshop-agent
does now (gitops/ai-layer/resources.yaml). Either way one root comes out.

The noise the filter exists for goes in too, and must still come out dropped: the ASGI send and receive spans, the
event-queue micro-spans, the AWS SDK's empty `chat <model>` leaf, kagent's MCP client calls, the gateway's MCP
session lifecycle, the agent-card fetch, a parentless a2a span and guard-proxy's badge poll.

Fails when the binary is missing: run verify/fetch-e2e-tools.sh (verify/run-e2e-tools.sh does).
"""
from __future__ import annotations

import hashlib
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
from collector_render import REPO, collector_config  # noqa: E402

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
GUARD, GATEWAY, AGENT = "burritobot", "burritobot-gateway", "burritobot-agent"
A2A = "a2a.server.request_handlers."
MODEL = "us.amazon.nova-pro-v1:0"
FAILED = json.dumps([{"role": "tool", "parts": [{"type": "text", "content": "command FAILED: curl blocked"}]}])
HELLO = json.dumps([{"role": "user", "parts": [{"type": "text", "content": "Hi BurritoBot!"}]}])


def sid(trace: str, key: str) -> str:
    return hashlib.sha256(f"{trace}/{key}".encode()).hexdigest()[:16]


def kv(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


# (key, service, name, kind, parent key or None, attributes, kept). The key names the span within its trace.
def interaction(with_a2a: bool) -> list[tuple]:
    run_parent = "a2a-run" if with_a2a else "agent-server"
    spans = [
        ("chat-root", GUARD, "POST /chat", SERVER, None, {}, True),
        ("chat", GUARD, "chat", INTERNAL, "chat-root", {"gen_ai.input.messages": HELLO}, True),
        ("forward", GUARD, "agent.forward", CLIENT, "chat", {}, True),
        ("forward-http", GUARD, "POST", CLIENT, "forward",
         {"http.url": "http://agentgateway.agent.svc.cluster.local:3000/"}, True),
        # agentgateway's span for the A2A hop: SERVER, "<method> <path match>", parented on guard-proxy's call.
        ("gateway", GATEWAY, "POST /", SERVER, "forward-http",
         {"http.method": "POST", "http.path": "/", "http.host": "agentgateway.agent.svc.cluster.local:3000",
          "endpoint": "workshop-agent.agent.svc.cluster.local:8080"}, True),
        # kagent's FastAPI server span, parented on the gateway's (it injects its own span as traceparent).
        ("agent-server", AGENT, "POST /", SERVER, "gateway", {"http.method": "POST", "http.route": "/"}, True),
        ("asgi-receive", AGENT, "POST / http receive", INTERNAL, "agent-server", {}, False),
        ("asgi-send", AGENT, "POST / http send", INTERNAL, "agent-server", {}, False),
    ]
    if with_a2a:
        spans += [
            ("a2a-jsonrpc", AGENT, A2A + "jsonrpc_handler.JSONRPCHandler.on_message_send", SERVER,
             "agent-server", {}, True),
            ("a2a-send", AGENT, A2A + "default_request_handler.DefaultRequestHandler.on_message_send", SERVER,
             "a2a-jsonrpc", {}, True),
            ("a2a-setup", AGENT, A2A + "default_request_handler.DefaultRequestHandler._setup_message_execution",
             SERVER, "a2a-send", {}, True),
            ("a2a-run", AGENT, A2A + "default_request_handler.DefaultRequestHandler._run_event_stream", SERVER,
             "a2a-setup", {}, True),
            ("a2a-enqueue", AGENT, "a2a.server.events.event_queue.EventQueue.enqueue_event", SERVER, "a2a-run",
             {"gen_ai.conversation.id": "c1"}, False),
        ]
    spans += [
        ("invocation", AGENT, "invocation", INTERNAL, run_parent, {"gen_ai.conversation.id": "c1"}, True),
        ("invoke-agent", AGENT, "invoke_agent burritobot", INTERNAL, "invocation",
         {"gen_ai.operation.name": "invoke_agent"}, True),
        ("call-llm-1", AGENT, "call_llm", INTERNAL, "invoke-agent", {}, True),
        ("generate-1", AGENT, f"generate_content {MODEL}", INTERNAL, "call-llm-1",
         {"gen_ai.operation.name": "generate_content", "gen_ai.input.messages": HELLO}, True),
        ("sdk-chat-1", AGENT, f"chat {MODEL}", CLIENT, "generate-1", {}, False),
        ("tool", AGENT, "execute_tool run_command", INTERNAL, "call-llm-1",
         {"gen_ai.operation.name": "execute_tool", "gcp.vertex.agent.tool_response": '{"isError": true}'}, True),
        ("tool-http", AGENT, "POST", CLIENT, "tool",
         {"http.url": "http://agentgateway.agent.svc.cluster.local:3001/mcp"}, False),
        ("call-llm-2", AGENT, "call_llm", INTERNAL, "invoke-agent", {}, True),
        ("generate-2", AGENT, f"generate_content {MODEL}", INTERNAL, "call-llm-2",
         {"gen_ai.operation.name": "generate_content", "gen_ai.input.messages": FAILED}, True),
        ("sdk-chat-2", AGENT, f"chat {MODEL}", CLIENT, "generate-2", {}, False),
    ]
    return spans


# Traces of their own, outside the interaction: what the filter is for (each would be a "No content" row).
NOISE = [
    # The gateway's MCP session lifecycle on :3001, which arrives without the agent's context (#265). tools/call
    # is the one it keeps.
    ("mcp-init", GATEWAY, "initialize", SERVER, None,
     {"http.host": "agentgateway.agent.svc.cluster.local:3001", "mcp.method.name": "initialize"}, False),
    ("mcp-list", GATEWAY, "tools/list", SERVER, None,
     {"http.host": "agentgateway.agent.svc.cluster.local:3001", "mcp.method.name": "tools/list"}, False),
    ("mcp-delete", GATEWAY, "DELETE /", SERVER, None,
     {"http.host": "agentgateway.agent.svc.cluster.local:3001", "http.method": "DELETE"}, False),
    ("mcp-call", GATEWAY, "tools/call", SERVER, None,
     {"http.host": "agentgateway.agent.svc.cluster.local:3001", "mcp.method.name": "tools/call"}, True),
    ("card", AGENT, "GET /.well-known/agent-card.json", SERVER, None, {}, False),
    # A message from a caller that sent no context: kagent's server span is then a root, and stays dropped.
    ("no-context", AGENT, "POST /", SERVER, None, {"http.method": "POST"}, False),
    ("a2a-orphan", AGENT, A2A + "default_request_handler.DefaultRequestHandler.on_get_task", SERVER, None, {},
     False),
    ("a2a-orphan-queue", AGENT, "a2a.server.events.event_queue.EventQueue.enqueue_event", SERVER, None,
     {"gen_ai.conversation.id": "c1"}, False),
    ("badge", GUARD, "GET", CLIENT, None,
     {"url.full": "https://kubernetes.default.svc/apis/kyverno.io/v1/clusterpolicies/c1"}, False),
]

# (label, trace id, spans, whether it is an interaction that must come out as one root)
TRACES = [("the interaction, a2a-sdk spans off", "5b8efff798038103d269b633813f0320", interaction(False), True),
          ("the interaction, a2a-sdk spans on", "5b8efff798038103d269b633813f1320", interaction(True), True),
          ("the noise traces", "5b8efff798038103d269b633813f2320", NOISE, False)]


def otlp_body() -> bytes:
    by_service: dict[str, list[dict]] = {}
    t0 = 1730000000000000000
    for _label, trace, spans, _one in TRACES:
        for i, (key, svc, name, kind, parent, attrs, _kept) in enumerate(spans):
            span = {"traceId": trace, "spanId": sid(trace, key), "name": name, "kind": kind,
                    "startTimeUnixNano": str(t0 + i * 1000), "endTimeUnixNano": str(t0 + 10**9 - i * 1000),
                    "attributes": [kv(k, v) for k, v in attrs.items()]}
            if parent:
                span["parentSpanId"] = sid(trace, parent)
            by_service.setdefault(svc, []).append(span)
    return json.dumps({"resourceSpans": [
        {"resource": {"attributes": [kv("service.name", svc)]}, "scopeSpans": [{"spans": spans}]}
        for svc, spans in by_service.items()]}).encode()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read_spans(out: pathlib.Path) -> list[dict]:
    """Every span the file exporter wrote, each with its resource's service.name beside it."""
    spans = []
    for line in out.read_text().splitlines() if out.exists() else []:
        for rs in json.loads(line)["resourceSpans"]:
            svc = next(a["value"]["stringValue"] for a in rs["resource"]["attributes"] if a["key"] == "service.name")
            spans += [{**s, "service": svc} for ss in rs["scopeSpans"] for s in ss["spans"]]
    return spans


def run_collector(profile: str) -> tuple[list[dict], str]:
    """The profile's traces processors, in its order, between an OTLP/HTTP receiver and a file exporter."""
    conf = collector_config(profile, datadog_secret=False)
    procs = conf["service"]["pipelines"]["traces"]["processors"]
    want = sum(1 for _label, _trace, spans, _one in TRACES for s in spans if s[6])
    port = free_port()
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "spans.json"
        cfg = {
            "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
            "processors": {p: conf["processors"][p] for p in procs},
            "exporters": {"file": {"path": str(out)}},
            "service": {"telemetry": {"metrics": {"level": "none"}},
                        "pipelines": {"traces": {"receivers": ["otlp"], "processors": procs, "exporters": ["file"]}}},
        }
        cfg_file = pathlib.Path(d) / "config.yaml"
        cfg_file.write_text(yaml.safe_dump(cfg, sort_keys=False))
        env = {**os.environ, "WIB_CLUSTER_NAME": f"burritobot-{profile}"}
        val = subprocess.run([str(OTELCOL), "validate", f"--config={cfg_file}"], capture_output=True, text=True,
                             env=env)
        check(f"the collector accepts the {profile} traces processors", val.returncode == 0, val.stderr)
        log = (pathlib.Path(d) / "collector.log").open("w")
        proc = subprocess.Popen([str(OTELCOL), f"--config={cfg_file}"], stdout=log, stderr=subprocess.STDOUT,
                                env=env)
        got: list[dict] = []
        try:
            sent, deadline = False, time.time() + 30
            while not sent and time.time() < deadline and proc.poll() is None:
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=otlp_body(),
                                                 headers={"Content-Type": "application/json"})
                    sent = urllib.request.urlopen(req, timeout=5).status == 200
                except OSError:
                    time.sleep(0.3)
            check("the collector took the spans", sent)
            # The batch processor holds spans up to its 5 s timeout. Read until the kept count arrives, then once
            # more after a further batch interval, so a span that should have been dropped has had time to show.
            deadline, settled = time.time() + 30, None
            while sent and time.time() < deadline:
                time.sleep(0.5)
                got = read_spans(out)
                if len(got) >= want and settled is None:
                    settled = time.time() + 6
                if settled is not None and time.time() > settled:
                    break
        finally:
            proc.terminate()
            proc.wait(timeout=15)
            log.close()
        return got, (pathlib.Path(d) / "collector.log").read_text()


for profile in ("instructor", "attendee", "burn"):
    print(f"== the {profile} collector ==")
    got, collector_log = run_collector(profile)
    for label, trace, spans, one_root in TRACES:
        kept = {sid(trace, s[0]): s for s in spans if s[6]}
        dropped = {sid(trace, s[0]): s for s in spans if not s[6]}
        out = {s["spanId"]: s for s in got if s["traceId"] == trace}
        missing = sorted(f"{kept[i][1]} {kept[i][2]}" for i in kept if i not in out)
        check(f"{label}: every span on the interaction's path reaches the exporter", not missing,
              f"dropped: {missing}" + ("" if got else f"\n{collector_log[-1500:]}"))
        leaked = sorted(f"{dropped[i][1]} {dropped[i][2]}" for i in dropped if i in out)
        check(f"{label}: the noise is still dropped", not leaked, f"exported: {leaked}")
        if not one_root:
            continue
        roots = sorted(f"{s['service']} {s['name']}" for s in out.values()
                       if not s.get("parentSpanId") or s["parentSpanId"] not in out)
        check(f"{label}: one root, guard-proxy's POST /chat (Datadog's 'multiple root spans' is #320)",
              roots == [f"{GUARD} POST /chat"], f"roots: {roots}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector one-root E2E checks passed.")
