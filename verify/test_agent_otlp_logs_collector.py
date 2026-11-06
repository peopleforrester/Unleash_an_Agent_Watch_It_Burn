# ABOUTME: Runs the real otelcol-contrib on each profile's shipped logs pipeline (#903): a log record sent where the
# ABOUTME: workshop-agent's exporter now sends it is accepted, and the bare base endpoint it used before answers 404.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""The agent's log batches reach the collector's logs pipeline instead of a 404.

kagent 0.10.1's Go ADK posts each log batch to the exact URL it resolves: OTEL_EXPORTER_OTLP_LOGS_ENDPOINT, then
OTEL_LOGS_EXPORTER_OTLP_ENDPOINT, then the base OTEL_EXPORTER_OTLP_ENDPOINT, path kept as given
(go/adk/pkg/telemetry/tracing.go, otlploghttp.WithEndpointURL). This resolves that URL from the Agent's env and the
Instrumentation CR, and sends a record shaped like ADK's gen_ai.choice event there, through each profile's shipped
logs pipeline on the real collector, with its debug exporter swapped for a file so the record can be seen arriving.
It also sends one to the base endpoint's path, "/", which is what the pod logged a 404 for about once a second.

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
import urllib.error
import urllib.parse
import urllib.request

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import PROFILE_APP, REPO, collector_config, feature_gate_args  # noqa: E402

OTELCOL = REPO / "verify/.tools/bin/otelcol-contrib"
LOCK = REPO / "verify/e2e-tools.lock"
AGENT = REPO / "gitops/workshop-agent/agent.yaml"
INSTR = REPO / "gitops/ai-layer-otel/instrumentation.yaml"

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

agent = next(d for d in yaml.safe_load_all(AGENT.read_text(encoding="utf-8")) if d and d.get("kind") == "Agent")
env = {e["name"]: e.get("value") for e in agent["spec"]["declarative"]["deployment"].get("env", [])}
base = yaml.safe_load(INSTR.read_text(encoding="utf-8"))["spec"]["exporter"]["endpoint"]
# kagent's resolveEndpoint("LOGS"), in its order.
resolved = env.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") or env.get("OTEL_LOGS_EXPORTER_OTLP_ENDPOINT") or base
AGENT_PATH = urllib.parse.urlsplit(resolved).path or "/"
BARE_PATH = urllib.parse.urlsplit(base).path or "/"
print(f"the agent's log exporter posts to {resolved} (path {AGENT_PATH}); the bare base endpoint's path is {BARE_PATH}")

ENV = {"PATH": "/usr/bin:/bin", "WIB_CLUSTER_NAME": "burritobot-public"}
KAGENT = {"service.name": "workshop_agent", "service.namespace": "agent", "service.version": "v0.10.1"}
MARK = "tool-execution-404-check-903"
START_BOUND = 120  # seconds a collector gets to listen; see the start loop below


def attrs(d: dict) -> list:
    return [{"key": k, "value": {"stringValue": v}} for k, v in d.items()]


# One record shaped like ADK's LogResponse: event gen_ai.choice, from the agent's resource.
RECORD = {"resourceLogs": [{"resource": {"attributes": attrs(KAGENT)}, "scopeLogs": [{
    "scope": {"name": "gcp.vertex.agent"}, "logRecords": [{
        "timeUnixNano": "1792815457397000000", "eventName": "gen_ai.choice",
        "body": {"stringValue": MARK}, "attributes": attrs({"gen_ai.system": "aws.bedrock"})}]}]}]}


def post(port: int, path: str, body: dict) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def run(profile: str, secret: bool, tmp: pathlib.Path) -> None:
    label = f"{profile} {'with' if secret else 'without'} datadog-secret"
    full = collector_config(profile, secret)
    logs = full["service"]["pipelines"].get("logs")
    check(f"{label}: the shipped config has a logs pipeline", isinstance(logs, dict))
    if not isinstance(logs, dict):
        return
    check(f"{label}: and it exports to debug alone", logs.get("exporters") == ["debug"], str(logs.get("exporters")))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    out = tmp / f"{profile}-{secret}-logs.json"
    procs = {k: full["processors"][k] for k in logs.get("processors") or []}
    if "batch" in procs:
        procs["batch"] = {"timeout": "200ms"}
    http = dict(full["receivers"]["otlp"]["protocols"]["http"], endpoint=f"127.0.0.1:{port}")
    cfg = {
        "receivers": {"otlp": {"protocols": {"http": http}}},
        "processors": procs,
        "exporters": {"file/l": {"path": str(out)}},
        "service": {"telemetry": {"metrics": {"level": "none"}}, "pipelines": {
            "logs": {"receivers": logs["receivers"], "processors": logs.get("processors") or [], "exporters": ["file/l"]}}},
    }
    cf = tmp / f"{profile}-{secret}-cfg.yaml"
    cf.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    proc = subprocess.Popen([str(OTELCOL), f"--config=file:{cf}", *feature_gate_args(profile)], env=ENV,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        # The bound only stops a collector that never listens. 30 seconds ran out on a loaded host with the
        # collector still running and its stderr empty (run 17911, #889's suite, one of six starts), so a slow start
        # gets 120, and a collector still not listening then is stopped and named with what it printed.
        start = time.time()
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                waited = time.time() - start
                if waited > START_BOUND or proc.poll() is not None:
                    alive = proc.poll() is None
                    if alive:
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                    err = proc.stderr.read() or ""
                    why = (f"still not listening on {port} after {waited:.0f} s" if alive
                           else f"exited {proc.returncode} after {waited:.0f} s")
                    check(f"{label}: the collector starts on the shipped logs pipeline", False, f"{why}: {err[-600:]}")
                    return
                time.sleep(0.3)
        code = post(port, AGENT_PATH, RECORD)
        check(f"{label}: a gen_ai.choice record sent to the agent's path {AGENT_PATH} is accepted ({code})", code == 200)
        bare = post(port, BARE_PATH, RECORD)
        check(f"{label}: the bare endpoint's path {BARE_PATH}, where the batches went before, answers 404 ({bare})",
              bare == 404)
        deadline = time.time() + 15
        while time.time() < deadline and not (out.exists() and MARK in out.read_text()):
            time.sleep(0.3)
        check(f"{label}: the record comes out of the logs pipeline", out.exists() and MARK in out.read_text())
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


check(f"the agent's path is /v1/logs ({AGENT_PATH}), not the bare base endpoint's", AGENT_PATH == "/v1/logs")
with tempfile.TemporaryDirectory() as d:
    for profile in PROFILE_APP:
        for secret in (False, True):
            print(f"== {profile} {'with' if secret else 'without'} datadog-secret: one agent log batch ==")
            run(profile, secret, pathlib.Path(d))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All agent OTLP logs collector checks passed.")
