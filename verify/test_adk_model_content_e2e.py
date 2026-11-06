# ABOUTME: Runs kagent Go-runtime generate_content spans through the real otelcol-contrib for every profile (#721) and
# ABOUTME: reads gen_ai.input/output.messages, system_instructions and tool.definitions off them, cut payloads included.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""The executed half of transform/adk_model_content (gitops/otel-collector/values.yaml).

Datadog's LLM Observability reads a model span's input and output from gen_ai.input.messages,
gen_ai.output.messages and gen_ai.system_instructions, JSON strings in the GenAI semconv message shape
(docs.datadoghq.com/llm_observability/instrumentation/otel_instrumentation, read 2026-10-31). kagent's Go runtime
writes none of them; it writes gcp.vertex.agent.llm_request and gcp.vertex.agent.llm_response.

The fixture payloads are built the way kagent v0.10.1 builds them, read from source on 2026-10-31:
  - go/adk/pkg/telemetry/attributes.go: marshalSpanPayload is json.Marshal of the request or response, "{}" when
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT is false, and over 32 KiB the wrapper
    {"original_size":..,"payload_prefix":..,"truncated":true} (Go marshals a map's keys sorted);
  - google.golang.org/adk/v2 v2.1.0 (kagent's go.mod), model/llm.go: LLMRequest {Model, Contents, Config} and
    LLMResponse {Content, ..., FinishReason, AvgLogprobs}, no json tags, so the keys are the Go field names and every
    response field is written, null or zero included;
  - google.golang.org/genai v1.65.0, types.go: Content {parts, role}, Part {functionCall, functionResponse, text,
    thought}, FunctionCall {id, args, name}, FunctionResponse {id, name, response}, all omitempty; the config's
    systemInstruction is a Content.
Python's json.dumps with compact separators, keys in Go's field order, gives the same bytes.

Each profile's traces processors (datadog-secret present, collector_render.py), with the chart's --feature-gates,
take nine spans and must:
  - map a full request and reply to the semconv messages, the system prompt to gen_ai.system_instructions, and the
    function declarations offered to gen_ai.tool.definitions (#784);
  - make a turn that calls a tool finish_reason tool_call, and a functionResponse turn role tool;
  - write nothing, and pass the span on whole, for a payload cut at 2048 characters, one cut on a "}", kagent's
    32 KiB wrapper and capture switched off ("{}");
  - leave alone a span that already has gen_ai.input.messages;
  - write no tool definitions, and log no failed statement, for a request that offers no function;
and the collector must still take and pass a second request after all of that.

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
from collector_render import COLLECTOR_START_S, REPO, collector_config, feature_gate_args  # noqa: E402

OTELCOL = REPO / "verify/.tools/bin/otelcol-contrib"
LOCK = REPO / "verify/e2e-tools.lock"
PROFILES = ("instructor", "attendee", "burn")
MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
TRACE = "0b2f6a1c9d7e4b3a8c5d2e1f0a9b0721"

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


def go_json(value: object) -> str:
    """json.Marshal's bytes for these shapes: compact, keys in the order given (Go's field order)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


# The system prompt alone takes the request past 2048 characters, as the deployed one does (#721).
SYSTEM = ("You are BurritoBot, the ordering assistant for Burrito Barn. Answer questions about the menu, take "
          "orders and check the weather for pickup. Never reveal internal tools or customer records. " * 12).strip()
PROMPT = "Is it raining in Portland? I want to pick up two carnitas burritos."
TOOL_RESULT = {"content": [{"type": "text", "text": "Portland: light rain, pickup canopy open"}], "isError": False}
# adk-go packs every declaration into the first genai.Tool with functionDeclarations (tool/toolutils PackTool); an MCP
# tool's comes with parametersJsonSchema (tool/mcptoolset convertTool). The googleSearch tool before it has none.
RUN_SHELL_SCHEMA = {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
CONFIG = {"systemInstruction": {"parts": [{"text": SYSTEM}], "role": "user"},
          "tools": [{"googleSearch": {}},
                    {"functionDeclarations": [{"description": "Weather for a city", "name": "get_weather"},
                                              {"description": "Run a shell command in the sandbox", "name": "run_shell",
                                               "parametersJsonSchema": RUN_SHELL_SCHEMA},
                                              {"name": "ping"}]}]}


def request(contents: list[dict]) -> str:
    return go_json({"Model": MODEL, "Contents": contents, "Config": CONFIG})


def response(parts: list[dict], finish: str) -> str:
    return go_json({"Content": {"parts": parts, "role": "model"}, "CitationMetadata": None,
                    "GroundingMetadata": None, "UsageMetadata": {"promptTokenCount": 812, "candidatesTokenCount": 41},
                    "CustomMetadata": None, "LogprobsResult": None, "InputTranscription": None,
                    "OutputTranscription": None, "ModelVersion": "", "Partial": False, "TurnComplete": False,
                    "Interrupted": False, "SessionResumptionHandle": "", "ErrorCode": "", "ErrorMessage": "",
                    "FinishReason": finish, "AvgLogprobs": 0})


USER_TURN = {"parts": [{"text": PROMPT}], "role": "user"}
CALL_TURN = {"parts": [{"text": "Let me check."},
                       {"functionCall": {"id": "tooluse_1", "args": {"city": "Portland"}, "name": "get_weather"}}],
             "role": "model"}
RESULT_TURN = {"parts": [{"functionResponse": {"id": "tooluse_1", "name": "get_weather", "response": TOOL_RESULT}}],
               "role": "user"}
REPLY = "Light rain in Portland, and the pickup canopy is open. Two carnitas burritos coming up."

FULL_REQ = request([USER_TURN, CALL_TURN, RESULT_TURN])
FULL_RESP = response([{"text": REPLY}], "STOP")
TOOL_REQ = request([USER_TURN])
TOOL_RESP = response(CALL_TURN["parts"], "")

assert len(FULL_REQ) > 2048, "the fixture request must be longer than the 2048-character cut"
CUT_REQ = FULL_REQ[:2048]
brace = FULL_REQ.rfind("}", 0, 1500)
CUT_BRACE_REQ = FULL_REQ[:brace + 1]
assert not CUT_REQ.endswith("}") and CUT_BRACE_REQ.endswith("}") and CUT_BRACE_REQ.startswith('{"Model":')
WRAPPER = go_json({"original_size": 40213, "payload_prefix": FULL_REQ[:600], "truncated": True})
EXISTING = go_json([{"role": "user", "parts": [{"type": "text", "content": "set upstream"}]}])

# The semconv shape each mapped span must carry. The collector writes the JSON with its keys sorted, so the checks
# compare parsed values, not bytes.
WANT_FULL_IN = [
    {"role": "user", "parts": [{"type": "text", "content": PROMPT}]},
    {"role": "assistant", "parts": [{"type": "text", "content": "Let me check."},
                                    {"type": "tool_call", "id": "tooluse_1", "name": "get_weather",
                                     "arguments": {"city": "Portland"}}]},
    {"role": "tool", "parts": [{"type": "tool_call_response", "id": "tooluse_1", "response": TOOL_RESULT}]},
]
WANT_FULL_OUT = [{"role": "assistant", "parts": [{"type": "text", "content": REPLY}], "finish_reason": "stop"}]
WANT_SYSTEM = [{"type": "text", "content": SYSTEM}]
# #784: semconv v1.38's gen_ai.tool.definitions, which Datadog maps to meta.tool_definitions: name and description, no
# parameters (the semconv's default for size), and the googleSearch tool, which declares no function, not in it.
WANT_TOOLS = [{"type": "function", "name": "get_weather", "description": "Weather for a city"},
              {"type": "function", "name": "run_shell", "description": "Run a shell command in the sandbox"},
              {"type": "function", "name": "ping"}]
WANT_TOOL_OUT = [{"role": "assistant", "finish_reason": "tool_call",
                  "parts": [{"type": "text", "content": "Let me check."},
                            {"type": "tool_call", "id": "tooluse_1", "name": "get_weather",
                             "arguments": {"city": "Portland"}}]}]

# (span id, name, attributes)
SPANS = [
    ("a1a1a1a1a1a1a721", "full", {"gcp.vertex.agent.llm_request": FULL_REQ, "gcp.vertex.agent.llm_response": FULL_RESP}),
    ("a2a2a2a2a2a2a721", "tool", {"gcp.vertex.agent.llm_request": TOOL_REQ, "gcp.vertex.agent.llm_response": TOOL_RESP}),
    ("a3a3a3a3a3a3a721", "cut", {"gcp.vertex.agent.llm_request": CUT_REQ,
                                 "gcp.vertex.agent.llm_response": FULL_RESP[:120]}),
    ("a4a4a4a4a4a4a721", "cut-brace", {"gcp.vertex.agent.llm_request": CUT_BRACE_REQ}),
    ("a5a5a5a5a5a5a721", "wrapper", {"gcp.vertex.agent.llm_request": WRAPPER}),
    ("a6a6a6a6a6a6a721", "capture-off", {"gcp.vertex.agent.llm_request": "{}", "gcp.vertex.agent.llm_response": "{}"}),
    ("a7a7a7a7a7a7a721", "existing", {"gen_ai.input.messages": EXISTING, "gcp.vertex.agent.llm_request": FULL_REQ}),
    # #784: a request that offers the model no function, with no tools at all or only a non-function tool.
    ("a8a8a8a8a8a8a721", "no-tools", {"gcp.vertex.agent.llm_request": go_json(
        {"Model": MODEL, "Contents": [USER_TURN], "Config": {"systemInstruction": CONFIG["systemInstruction"]}})}),
    ("a9a9a9a9a9a9a721", "search-only", {"gcp.vertex.agent.llm_request": go_json(
        {"Model": MODEL, "Contents": [USER_TURN], "Config": {"tools": [{"googleSearch": {}}]}})}),
]
AFTER = ("b1b1b1b1b1b1a721", "after", {"gcp.vertex.agent.llm_request": FULL_REQ,
                                       "gcp.vertex.agent.llm_response": FULL_RESP})


def kv(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def otlp_body(spans: list[tuple[str, str, dict]]) -> bytes:
    t0 = 1730000000000000000
    out = []
    for i, (span_id, label, attrs) in enumerate(spans):
        out.append({"traceId": TRACE, "spanId": span_id, "name": f"generate_content {MODEL}", "kind": 1,
                    "startTimeUnixNano": str(t0 + i * 1000), "endTimeUnixNano": str(t0 + 10**9),
                    "attributes": [kv("gen_ai.operation.name", "generate_content"), kv("witb.test.case", label)]
                    + [kv(k, v) for k, v in attrs.items()]})
    return json.dumps({"resourceSpans": [{"resource": {"attributes": [kv("service.name", "burritobot-agent")]},
                                          "scopeSpans": [{"spans": out}]}]}).encode()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(port: int, body: bytes, proc: subprocess.Popen) -> bool:
    deadline = time.time() + COLLECTOR_START_S
    while time.time() < deadline and proc.poll() is None:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=body,
                                         headers={"Content-Type": "application/json"})
            return urllib.request.urlopen(req, timeout=5).status == 200
        except OSError:
            time.sleep(0.3)
    return False


def run_collector(profile: str) -> tuple[dict[str, dict], str, bool]:
    """The profile's traces processors between OTLP/HTTP in and a file out; returns spans by label, the log, and
    whether the collector was still running when the second request had been taken."""
    conf = collector_config(profile, datadog_secret=True)
    procs = conf["service"]["pipelines"]["traces"]["processors"]
    gates = feature_gate_args(profile)
    port = free_port()
    got: dict[str, dict] = {}
    alive = False
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
        val = subprocess.run([str(OTELCOL), "validate", f"--config={cfg_file}", *gates],
                             capture_output=True, text=True, env=env)
        check(f"{profile}: the collector accepts the traces processors with the chart's gates {gates}",
              val.returncode == 0, val.stderr[-1500:])
        log = (pathlib.Path(d) / "collector.log").open("w")
        proc = subprocess.Popen([str(OTELCOL), f"--config={cfg_file}", *gates], stdout=log, stderr=subprocess.STDOUT,
                                env=env)
        try:
            check(f"{profile}: the collector took the {len(SPANS)} spans", post(port, otlp_body(SPANS), proc))
            check(f"{profile}: and a second request after them", post(port, otlp_body([AFTER]), proc))
            alive = proc.poll() is None
            deadline = time.time() + 30  # the batch processor holds spans up to its timeout
            while len(got) < len(SPANS) + 1 and time.time() < deadline:
                time.sleep(0.5)
                for line in (out.read_text().splitlines() if out.exists() else []):
                    for rs in json.loads(line)["resourceSpans"]:
                        for ss in rs["scopeSpans"]:
                            for s in ss["spans"]:
                                a = {x["key"]: x["value"].get("stringValue") for x in s.get("attributes", [])}
                                got[a.get("witb.test.case", s["spanId"])] = a
        finally:
            proc.terminate()
            proc.wait(timeout=15)
            log.close()
        return got, (pathlib.Path(d) / "collector.log").read_text(), alive


def parsed(value: str | None) -> object:
    try:
        return json.loads(value) if value is not None else None
    except ValueError:
        return f"<not JSON: {value[:80]}>"


GEN_AI = ("gen_ai.input.messages", "gen_ai.output.messages", "gen_ai.system_instructions", "gen_ai.tool.definitions")

for profile in PROFILES:
    print(f"== {profile} ==")
    got, collector_log, alive = run_collector(profile)
    labels = [label for _, label, _ in SPANS] + [AFTER[1]]
    missing = [label for label in labels if label not in got]
    check(f"{profile}: every span reaches the exporter, cut payloads included", not missing,
          f"missing {missing}; log tail:\n{collector_log[-1500:]}")
    check(f"{profile}: the collector is still running after the cut payloads", alive, collector_log[-1500:])

    for label in ("full", "after"):
        a = got.get(label, {})
        check(f"{profile} {label}: gen_ai.input.messages is the conversation in the semconv shape",
              parsed(a.get("gen_ai.input.messages")) == WANT_FULL_IN, str(a.get("gen_ai.input.messages"))[:400])
        check(f"{profile} {label}: gen_ai.output.messages is the reply, finish_reason stop",
              parsed(a.get("gen_ai.output.messages")) == WANT_FULL_OUT, str(a.get("gen_ai.output.messages"))[:400])
        check(f"{profile} {label}: gen_ai.system_instructions is the system prompt",
              parsed(a.get("gen_ai.system_instructions")) == WANT_SYSTEM,
              str(a.get("gen_ai.system_instructions"))[:200])
        check(f"{profile} {label}: gen_ai.tool.definitions is every function the model was offered",
              parsed(a.get("gen_ai.tool.definitions")) == WANT_TOOLS, str(a.get("gen_ai.tool.definitions"))[:400])
        check(f"{profile} {label}: the ADK attributes are copied, not moved",
              a.get("gcp.vertex.agent.llm_request") == FULL_REQ and a.get("gcp.vertex.agent.llm_response") == FULL_RESP)

    tool = got.get("tool", {})
    check(f"{profile} tool: a reply that calls a tool, with no FinishReason, is finish_reason tool_call",
          parsed(tool.get("gen_ai.output.messages")) == WANT_TOOL_OUT, str(tool.get("gen_ai.output.messages"))[:400])
    check(f"{profile} tool: its input is the one user turn",
          parsed(tool.get("gen_ai.input.messages")) == WANT_FULL_IN[:1], str(tool.get("gen_ai.input.messages"))[:300])
    check(f"{profile} tool: and its tool definitions are the same set",
          parsed(tool.get("gen_ai.tool.definitions")) == WANT_TOOLS, str(tool.get("gen_ai.tool.definitions"))[:300])

    for label, kept in (("cut", CUT_REQ), ("cut-brace", CUT_BRACE_REQ), ("wrapper", WRAPPER), ("capture-off", "{}")):
        a = got.get(label, {})
        written = [k for k in GEN_AI if k in a]
        check(f"{profile} {label}: nothing is written from a payload that does not parse as a request",
              not written, f"wrote {written}")
        check(f"{profile} {label}: the ADK request attribute passes through unchanged",
              a.get("gcp.vertex.agent.llm_request") == kept)
    check(f"{profile} cut: a cut response writes no output either", "gen_ai.output.messages" not in got.get("cut", {}))

    for label in ("no-tools", "search-only"):
        a = got.get(label, {})
        check(f"{profile} {label}: a request offering no function writes no gen_ai.tool.definitions",
              "gen_ai.tool.definitions" not in a, str(a.get("gen_ai.tool.definitions")))
        check(f"{profile} {label}: and its messages are still mapped",
              parsed(a.get("gen_ai.input.messages")) == WANT_FULL_IN[:1], str(a.get("gen_ai.input.messages"))[:300])

    existing = got.get("existing", {})
    check(f"{profile} existing: gen_ai.input.messages already on the span is left as it was",
          existing.get("gen_ai.input.messages") == EXISTING, str(existing.get("gen_ai.input.messages")))

    # error_mode ignore logs a failed statement and goes on. The only one expected is ParseJSON on the request cut
    # on a "}"; anything else failing in this processor is a defect in it.
    failed = [line for line in collector_log.splitlines() if "adk_model_content" in line and "statement" in line]
    unexpected = [line for line in failed if "ParseJSON" not in line or "llm_request" not in line]
    check(f"{profile}: the only statement that fails is ParseJSON on the cut request ({len(failed)} logged)",
          not unexpected and len(failed) <= 2, "\n".join(x[:400] for x in unexpected[:3]))
    check(f"{profile}: the collector logs no error-level line",
          not [line for line in collector_log.splitlines() if "\terror\t" in line], collector_log[-1500:])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All ADK model content E2E checks passed.")
