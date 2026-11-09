# ABOUTME: Runs spans through the real otelcol-contrib with each profile's traces processors (#1277) and reads what the
# ABOUTME: exporter receives: a code-of-conduct term in the conversation comes out masked, HC-666's ticket unchanged.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""The executed half of verify/test_collector_coc_mask.py.

Each profile's collector config is rendered as its cluster builds it (collector_render.py), and its traces processors,
in that profile's order, are run by verify/.tools/bin/otelcol-contrib, the version the clusters' image runs. Only the
receiver and the exporter differ: OTLP/HTTP on a loopback port in, a file out. instructor (admin and full) and
attendee run the same list, so it runs once for both, and burn's, with transform/scrub_pii after the mask, once.

Three spans go in, shaped as guard-proxy's chat span, kagent's model call and kagent's tool call:

  - the chat span's prompt (gen_ai.input.messages) and a gen_ai.input.messages span-event attribute carry
    coc_mask_cases.term_cases(), each spelling of a term the RE2 form reads, one per line, JSON-encoded as guard-proxy
    writes it (a newline or a non-ASCII escape right before a term); the model call's prompt carries them as kagent writes it
    (UTF-8). All come out masked, as Python's re masks them, and session.id, which is not conversation, holding a
    term comes out whole;
  - the model call's reply (gen_ai.output.messages) carries HC-666's ticket, its injection included, and comes out
    unchanged, as does the tool call's result: read_support_ticket's reply on gcp.vertex.agent.tool_response and its
    gen_ai.tool.call.result copy;
  - the tool call's arguments hold a term and come out masked on gcp.vertex.agent.tool_call_args and on the
    gen_ai.tool.call.arguments copy transform/adk_tool_content makes, which exists only because the mask runs after it.

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
from coc_mask_cases import MASK, hc666_ticket, mask, term_cases  # noqa: E402
from collector_render import REPO, collector_config, feature_gate_args  # noqa: E402

OTELCOL = REPO / "verify/.tools/bin/otelcol-contrib"
LOCK = REPO / "verify/e2e-tools.lock"
START_BOUND = float(os.environ.get("COLLECTOR_START_BOUND", "120"))  # seconds the collector gets to take the spans

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[:1500]}" if detail and not cond else ""))
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


def messages(role: str, text: str, ascii_only: bool = True) -> str:
    """guard-proxy's envelope: json.dumps escapes every non-ASCII character (ascii_only); kagent's Go keeps UTF-8."""
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": text}]}], ensure_ascii=ascii_only)


CASES = term_cases()
PROMPT = "\n".join(text for text, _ in CASES)
PROMPT_MASKED = "\n".join(masked for _, masked in CASES)
WORD = CASES[0][0].split()[3]  # the single-word term of the first case
SESSION = f"session-{WORD}-1"  # a term inside an id: not conversation, so left whole
TICKET = hc666_ticket()
TOOL_ARGS = json.dumps({"ticket_id": "HC-666", "note": f"customer says {WORD}"})
TOOL_ARGS_MASKED = json.dumps({"ticket_id": "HC-666", "note": "customer says [redacted]"})
TOOL_RESULT = json.dumps({"content": [{"type": "text", "text": TICKET}], "isError": False})
TRACE = "6c9efff798038103d269b633813fc61d"
SPANS = {
    "burritobot": [{
        "traceId": TRACE, "spanId": "aee19b7ec3c1b171", "name": "chat", "kind": 1,
        "startTimeUnixNano": "1730000000000000000", "endTimeUnixNano": "1730000001000000000",
        "attributes": [kv("gen_ai.operation.name", "chat"), kv("gen_ai.input.messages", messages("user", PROMPT)),
                       kv("session.id", SESSION)],
        "events": [{"name": "gen_ai.client.inference.operation.details", "timeUnixNano": "1730000000000000001",
                    "attributes": [kv("gen_ai.input.messages", messages("user", PROMPT))]}]}],
    "burritobot-agent": [
        {"traceId": TRACE, "spanId": "aee19b7ec3c1b172", "parentSpanId": "aee19b7ec3c1b171",
         "name": "generate_content us.amazon.nova-pro-v1:0", "kind": 3,
         "startTimeUnixNano": "1730000000100000000", "endTimeUnixNano": "1730000000900000000",
         "attributes": [kv("gen_ai.operation.name", "generate_content"),
                        kv("gen_ai.input.messages", messages("user", PROMPT, ascii_only=False)),
                        kv("gen_ai.output.messages", messages("assistant", TICKET))]},
        {"traceId": TRACE, "spanId": "aee19b7ec3c1b173", "parentSpanId": "aee19b7ec3c1b172",
         "name": "execute_tool read_support_ticket", "kind": 1,
         "startTimeUnixNano": "1730000000200000000", "endTimeUnixNano": "1730000000300000000",
         "attributes": [kv("gen_ai.operation.name", "execute_tool"),
                        kv("gcp.vertex.agent.tool_call_args", TOOL_ARGS),
                        kv("gcp.vertex.agent.tool_response", TOOL_RESULT)]},
    ],
}
NAMES = ("chat", "generate_content us.amazon.nova-pro-v1:0", "execute_tool read_support_ticket")


def run(profile: str) -> dict[str, dict]:
    """The three spans as the file exporter wrote them, after the profile's traces processors."""
    rendered = collector_config(profile, datadog_secret=False)
    procs = rendered["service"]["pipelines"]["traces"]["processors"]
    port = free_port()
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "spans.json"
        cfg = {
            "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
            "processors": {p: rendered["processors"][p] for p in procs},
            "exporters": {"file": {"path": str(out)}},
            "service": {"telemetry": {"metrics": {"level": "none"}},
                        "pipelines": {"traces": {"receivers": ["otlp"], "processors": procs, "exporters": ["file"]}}},
        }
        cfg_file = pathlib.Path(d) / "config.yaml"
        cfg_file.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
        env = {**os.environ, "WIB_CLUSTER_NAME": f"burritobot-{profile}"}
        gates = feature_gate_args(profile)
        val = subprocess.run([str(OTELCOL), "validate", f"--config={cfg_file}", *gates], capture_output=True,
                             text=True, env=env)
        check(f"{profile}: the collector accepts the traces processors, {MASK} among them", val.returncode == 0,
              val.stderr)
        log_path = pathlib.Path(d) / "collector.log"
        log = log_path.open("w")
        proc = subprocess.Popen([str(OTELCOL), f"--config={cfg_file}", *gates], stdout=log, stderr=subprocess.STDOUT,
                                env=env)
        got: dict[str, dict] = {}
        try:
            body = json.dumps({"resourceSpans": [
                {"resource": {"attributes": [kv("service.name", svc)]}, "scopeSpans": [{"spans": spans}]}
                for svc, spans in SPANS.items()]}).encode()
            # Spans go only once the collector says it is ready: free_port's port is free for any process until then
            # (#799), and a loaded host can take far longer than an idle one to compile the processors.
            sent, start = False, time.time()
            while not sent and time.time() - start < START_BOUND and proc.poll() is None:
                if "Everything is ready" not in log_path.read_text():
                    time.sleep(0.3)
                    continue
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=body,
                                                 headers={"Content-Type": "application/json"})
                    sent = urllib.request.urlopen(req, timeout=5).status == 200
                except OSError:
                    time.sleep(0.3)
            waited = time.time() - start
            why = ("" if sent else f"exited {proc.returncode} after {waited:.0f} s" if proc.poll() is not None
                   else f"still not taking spans on {port} after {waited:.0f} s")
            check(f"{profile}: the collector took the spans", sent, why)
            deadline = time.time() + 30  # the batch processor holds spans up to its 5 s timeout
            while sent and len(got) < len(NAMES) and time.time() < deadline:
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
        check(f"{profile}: all three spans reached the exporter ({sorted(got)})", len(got) == len(NAMES),
              log_path.read_text()[-2000:])
    return got


def attrs(span: dict) -> dict:
    return {a["key"]: a["value"].get("stringValue") for a in span.get("attributes", [])}


print("== the cases, as Python's re masks them ==")
check("every term case masks to its expected text", all(mask(t) == m for t, m in CASES))
check("HC-666's ticket is left as it is", mask(TICKET) == TICKET)

lists = {p: collector_config(p, datadog_secret=False)["service"]["pipelines"]["traces"]["processors"]
         for p in ("instructor", "attendee", "burn")}
check("attendee runs instructor's traces processors, so one run covers both",
      lists["attendee"] == lists["instructor"], f"{lists['attendee']} vs {lists['instructor']}")
for profile in ("instructor", "burn"):
    print(f"== {profile} ({'admin, full and attendee' if profile == 'instructor' else 'community'}) ==")
    got = run(profile)
    chat, model, tool = (attrs(got.get(n, {})) for n in NAMES)
    check(f"{profile}: the chat span's prompt comes out masked",
          chat.get("gen_ai.input.messages") == messages("user", PROMPT_MASKED), str(chat.get("gen_ai.input.messages")))
    check(f"{profile}: session.id is not conversation and is left whole", chat.get("session.id") == SESSION,
          str(chat.get("session.id")))
    event = attrs(next(iter(got.get("chat", {}).get("events", [])), {}))
    check(f"{profile}: the span event's messages come out masked",
          event.get("gen_ai.input.messages") == messages("user", PROMPT_MASKED), str(event))
    check(f"{profile}: the model call's prompt, JSON in UTF-8 as kagent writes it, comes out masked",
          model.get("gen_ai.input.messages") == messages("user", PROMPT_MASKED, ascii_only=False),
          str(model.get("gen_ai.input.messages")))
    check(f"{profile}: the model's reply carrying HC-666's ticket is unchanged",
          model.get("gen_ai.output.messages") == messages("assistant", TICKET), str(model.get("gen_ai.output.messages")))
    check(f"{profile}: the processors before the mask still ran (gen_ai.provider.name stamped)",
          model.get("gen_ai.provider.name") == "aws.bedrock", str(model))
    for key in ("gcp.vertex.agent.tool_call_args", "gen_ai.tool.call.arguments"):
        check(f"{profile}: the tool call's {key} comes out masked", tool.get(key) == TOOL_ARGS_MASKED, str(tool.get(key)))
    for key in ("gcp.vertex.agent.tool_response", "gen_ai.tool.call.result"):
        check(f"{profile}: read_support_ticket's HC-666 on {key} is unchanged", tool.get(key) == TOOL_RESULT,
              str(tool.get(key)))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector code-of-conduct mask E2E checks passed.")
