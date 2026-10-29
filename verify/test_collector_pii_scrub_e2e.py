# ABOUTME: Runs spans through the real otelcol-contrib with the public cluster's traces processors (#647) and
# ABOUTME: reads what the exporter receives: attendee PII scrubbed, the demo's text and every id left whole.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""The executed half of verify/test_collector_pii_scrub.py.

The burn collector's config is rendered as attackme builds it (collector_render.py), and its traces processors,
in the burn order, are run by verify/.tools/bin/otelcol-contrib, the version the clusters' image runs. Only the
receiver and the exporter differ: OTLP/HTTP on a loopback port in, a file out. The chart's k8sattributes, which
needs the Kubernetes API, is left out; it adds resource attributes and never reads span content.

Three spans go in, shaped as guard-proxy's chat span, kagent's model call and kagent's tool call:

  - the attendee prompt (pii_scrub_cases.ATTENDEE) on gen_ai.input.messages and on a gen_ai content event comes
    out as ATTENDEE_SCRUBBED, and a session.id holding an e-mail and a phone number comes out unchanged;
  - C5's record and the other UNTOUCHED text on gen_ai.output.messages come out unchanged;
  - the tool call's arguments and result are scrubbed on the gcp.vertex.agent.* keys and on the gen_ai.tool.call.*
    copies transform/adk_tool_content makes from them, which only exist because the scrub runs after it.

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
from pii_scrub_cases import ATTENDEE, ATTENDEE_SCRUBBED, UNTOUCHED, c5_record  # noqa: E402

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


SESSION = "jo.example+kc@example.co.uk 5035550142"
TOOL_ARGS = json.dumps({"email": "jo.example+kc@example.co.uk", "phone": "(503) 555-0142"})
TOOL_ARGS_SCRUBBED = json.dumps({"email": "[EMAIL]", "phone": "[PHONE]"})
TOOL_RESULT = json.dumps({"content": [{"type": "text", "text": "Morticia Nightshade, morticia@gravemail.com, "
                                       "555-0113, card 4111 1111 1111 1111"}], "isError": False})
TOOL_RESULT_SCRUBBED = TOOL_RESULT.replace("morticia@gravemail.com", "[EMAIL]").replace(
    "4111 1111 1111 1111", "[CARD]")
KEPT = c5_record() + "\n" + "\n".join(UNTOUCHED)
TRACE = "5b8efff798038103d269b633813fc60c"
SPANS = {
    "burritobot": [{
        "traceId": TRACE, "spanId": "eee19b7ec3c1b171", "name": "chat", "kind": 1,
        "startTimeUnixNano": "1730000000000000000", "endTimeUnixNano": "1730000001000000000",
        "attributes": [kv("gen_ai.operation.name", "chat"), kv("gen_ai.input.messages", messages("user", ATTENDEE)),
                       kv("session.id", SESSION)],
        "events": [{"name": "gen_ai.content.prompt", "timeUnixNano": "1730000000000000001",
                    "attributes": [kv("content", ATTENDEE)]}]}],
    "burritobot-agent": [
        {"traceId": TRACE, "spanId": "eee19b7ec3c1b172", "parentSpanId": "eee19b7ec3c1b171",
         "name": "generate_content us.amazon.nova-pro-v1:0", "kind": 3,
         "startTimeUnixNano": "1730000000100000000", "endTimeUnixNano": "1730000000900000000",
         "attributes": [kv("gen_ai.operation.name", "generate_content"),
                        kv("gen_ai.input.messages", messages("user", ATTENDEE)),
                        kv("gen_ai.output.messages", messages("assistant", KEPT))]},
        {"traceId": TRACE, "spanId": "eee19b7ec3c1b173", "parentSpanId": "eee19b7ec3c1b172",
         "name": "execute_tool lookup_customer_records", "kind": 1,
         "startTimeUnixNano": "1730000000200000000", "endTimeUnixNano": "1730000000300000000",
         "attributes": [kv("gen_ai.operation.name", "execute_tool"),
                        kv("gcp.vertex.agent.tool_call_args", TOOL_ARGS),
                        kv("gcp.vertex.agent.tool_response", TOOL_RESULT)]},
    ],
}

burn = collector_config("burn", datadog_secret=False)
procs = burn["service"]["pipelines"]["traces"]["processors"]
port = free_port()
with tempfile.TemporaryDirectory() as d:
    out = pathlib.Path(d) / "spans.json"
    cfg = {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
        "processors": {p: burn["processors"][p] for p in procs},
        "exporters": {"file": {"path": str(out)}},
        "service": {"telemetry": {"metrics": {"level": "none"}},
                    "pipelines": {"traces": {"receivers": ["otlp"], "processors": procs, "exporters": ["file"]}}},
    }
    cfg_file = pathlib.Path(d) / "config.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg, sort_keys=False))
    env = {**os.environ, "WIB_CLUSTER_NAME": "burritobot-public"}
    val = subprocess.run([str(OTELCOL), "validate", f"--config={cfg_file}"], capture_output=True, text=True, env=env)
    check("the collector accepts the burn traces processors", val.returncode == 0, val.stderr)
    log = (pathlib.Path(d) / "collector.log").open("w")
    proc = subprocess.Popen([str(OTELCOL), f"--config={cfg_file}"], stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        body = json.dumps({"resourceSpans": [
            {"resource": {"attributes": [kv("service.name", svc)]}, "scopeSpans": [{"spans": spans}]}
            for svc, spans in SPANS.items()]}).encode()
        sent, deadline = False, time.time() + 30
        while not sent and time.time() < deadline and proc.poll() is None:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=body,
                                             headers={"Content-Type": "application/json"})
                sent = urllib.request.urlopen(req, timeout=5).status == 200
            except OSError:
                time.sleep(0.3)
        check("the collector took the spans", sent)
        got: dict[str, dict] = {}
        deadline = time.time() + 30  # the batch processor holds spans up to its 5 s timeout
        while sent and len(got) < 3 and time.time() < deadline:
            time.sleep(0.5)
            for line in (out.read_text().splitlines() if out.exists() else []):
                for rs in json.loads(line)["resourceSpans"]:
                    for ss in rs["scopeSpans"]:
                        for s in ss["spans"]:
                            got[s["name"]] = s
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        log.close()
    collector_log = (pathlib.Path(d) / "collector.log").read_text()

check(f"all three spans reached the exporter ({sorted(got)})", len(got) == 3, collector_log[-2000:])


def attrs(span: dict) -> dict:
    return {a["key"]: a["value"].get("stringValue") for a in span.get("attributes", [])}


chat = attrs(got.get("chat", {}))
model = attrs(got.get("generate_content us.amazon.nova-pro-v1:0", {}))
tool = attrs(got.get("execute_tool lookup_customer_records", {}))
print("== guard-proxy's chat span ==")
check("the prompt is scrubbed", chat.get("gen_ai.input.messages") == messages("user", ATTENDEE_SCRUBBED),
      str(chat.get("gen_ai.input.messages")))
check("session.id is not content and is left whole", chat.get("session.id") == SESSION, str(chat.get("session.id")))
event = next(iter(got.get("chat", {}).get("events", [])), {})
check("the content event is scrubbed", attrs(event).get("content") == ATTENDEE_SCRUBBED, str(attrs(event)))
print("== kagent's model call ==")
check("the prompt is scrubbed", model.get("gen_ai.input.messages") == messages("user", ATTENDEE_SCRUBBED))
check("the reply carrying C5's record and the demo text is unchanged",
      model.get("gen_ai.output.messages") == messages("assistant", KEPT), str(model.get("gen_ai.output.messages")))
check("the processors before the scrub still ran (gen_ai.provider.name stamped)",
      model.get("gen_ai.provider.name") == "aws.bedrock", str(model))
print("== kagent's tool call, and the gen_ai copies adk_tool_content makes ==")
check("gcp.vertex.agent.tool_call_args is scrubbed", tool.get("gcp.vertex.agent.tool_call_args") == TOOL_ARGS_SCRUBBED,
      str(tool.get("gcp.vertex.agent.tool_call_args")))
check("gen_ai.tool.call.arguments is scrubbed", tool.get("gen_ai.tool.call.arguments") == TOOL_ARGS_SCRUBBED,
      str(tool.get("gen_ai.tool.call.arguments")))
check("gcp.vertex.agent.tool_response is scrubbed", tool.get("gcp.vertex.agent.tool_response") == TOOL_RESULT_SCRUBBED,
      str(tool.get("gcp.vertex.agent.tool_response")))
check("gen_ai.tool.call.result is scrubbed", tool.get("gen_ai.tool.call.result") == TOOL_RESULT_SCRUBBED,
      str(tool.get("gen_ai.tool.call.result")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector PII scrub E2E checks passed.")
