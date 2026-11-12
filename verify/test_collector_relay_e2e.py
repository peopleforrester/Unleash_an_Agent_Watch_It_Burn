# ABOUTME: Runs spans through the real otelcol-contrib over #1336's loopback: traces/intake, otlp_grpc/relay's queue,
# ABOUTME: otlp/relay and the burn traces processors, and reads each span out once, scrubbed, with its sender's address.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""The executed half of verify/test_collector_relay.py.

The burn collector's config is rendered as attackme builds it (collector_render.py), and its two trace pipelines run
in verify/.tools/bin/otelcol-contrib, the version the clusters' image runs, as rendered: traces/intake with
memory_limiter, k8s_attributes/intake and batch, exporting to otlp_grpc/relay with its queue, consumers, request size,
timeout and retry setting; and the traces pipeline behind otlp/relay with every burn processor. Only the ports and the
last exporter differ: OTLP/HTTP on a free loopback port in, otlp/relay on another, a file out. The chart's
k8s_attributes, which needs the Kubernetes API, is left out.

600 spans go in, in one request. Each must come out of the file exporter once: none lost in the queue, none sent twice.
The relay exporter cuts them into requests of at most its max_size, so otlp/relay must take them in more than one
request. Each span's e-mail address must come out as [EMAIL], so transform/scrub_pii ran behind the loopback, and each
resource must carry k8s.pod.ip 127.0.0.1, the sender's address, which k8s_attributes/intake wrote before the loopback
hid it. The collector's own metrics must count the 600 sent by otlp_grpc/relay, accepted by otlp/relay, and none
refused, failed or turned away by the queue.

Fails when the binary is missing: run it through verify/run-e2e-tools.sh, which runs it in the wib-e2e-tools image.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import REPO, collector_config, feature_gate_args  # noqa: E402

# run-e2e-tools.sh names the pinned collector in OTELCOL_CONTRIB, the image's inside wib-e2e-tools (#1188); by hand, the copied-out one.
OTELCOL = pathlib.Path(os.environ.get("OTELCOL_CONTRIB") or REPO / "verify/.tools/bin/otelcol-contrib")
LOCK = REPO / "verify/e2e-tools.lock"
START_BOUND = float(os.environ.get("COLLECTOR_START_BOUND", "120"))  # seconds the collector gets to take the spans
INTAKE, TRACES, RECEIVER, EXPORTER = "traces/intake", "traces", "otlp/relay", "otlp_grpc/relay"
SPANS = 600

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


if not os.access(OTELCOL, os.X_OK):
    print(f"FAIL: {OTELCOL} is missing; run it through bash verify/run-e2e-tools.sh, in the wib-e2e-tools image (this is a failure, not a skip)")
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


def metric(text: str, name: str, label: str) -> float:
    """The sum of every series of `name` whose labels contain `label`; 0 when there is none."""
    total = 0.0
    for line in text.splitlines():
        m = re.match(rf"^{re.escape(name)}(\{{[^}}]*\}})? ([0-9.e+]+)$", line)
        if m and label in (m.group(1) or ""):
            total += float(m.group(2))
    return total


def read(path: pathlib.Path) -> tuple[dict[str, list[dict]], list[dict]]:
    """The file exporter's spans by span id, each id with every copy of it, and every resource they came in."""
    got: dict[str, list[dict]] = {}
    resources: list[dict] = []
    for line in (path.read_text().splitlines() if path.exists() else []):
        for rs in json.loads(line)["resourceSpans"]:
            resources.append(rs.get("resource", {}))
            for ss in rs["scopeSpans"]:
                for s in ss["spans"]:
                    got.setdefault(s.get("spanId", ""), []).append(s)
    return got, resources


burn = collector_config("burn", datadog_secret=False)
pipes = burn["service"]["pipelines"]
intake, traces = pipes[INTAKE], pipes[TRACES]
check(f"{INTAKE} exports to {EXPORTER} and {TRACES} receives {RECEIVER}",
      intake["exporters"] == [EXPORTER] and traces["receivers"] == [RECEIVER], f"{intake} / {traces}")
http_port, relay_port, metrics_port = free_port(), free_port(), free_port()
relay = copy.deepcopy(burn["receivers"][RECEIVER])
relay["protocols"]["grpc"]["endpoint"] = f"localhost:{relay_port}"
exporter = copy.deepcopy(burn["exporters"][EXPORTER])
exporter["endpoint"] = f"localhost:{relay_port}"
max_size = exporter["sending_queue"]["batch"]["max_size"]
processors = {p: copy.deepcopy(burn["processors"][p]) for p in intake["processors"] + traces["processors"]}
processors["batch"]["timeout"] = "200ms"  # the 5 s the room uses only slows the test

trace = "5b8efff798038103d269b633813fc6"
spans = [{"traceId": f"{trace}{i // 256:02x}", "spanId": f"{i + 1:016x}", "name": f"chat {i}", "kind": 2,
          "startTimeUnixNano": "1730000000000000000", "endTimeUnixNano": "1730000001000000000",
          "attributes": [kv("gen_ai.operation.name", "chat"),
                         kv("gen_ai.input.messages", json.dumps([{"role": "user", "parts": [
                             {"type": "text", "content": f"order {i} for jo.example+{i}@example.co.uk"}]}]))]}
         for i in range(SPANS)]
body = json.dumps({"resourceSpans": [{"resource": {"attributes": [kv("service.name", "burritobot")]},
                                      "scopeSpans": [{"spans": spans}]}]}).encode()

with tempfile.TemporaryDirectory() as d:
    out = pathlib.Path(d) / "spans.json"
    cfg = {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{http_port}"}}}, RECEIVER: relay},
        "processors": processors,
        "exporters": {EXPORTER: exporter, "file": {"path": str(out)}},
        "service": {
            "telemetry": {"metrics": {"level": "detailed", "readers": [{"pull": {"exporter": {"prometheus": {
                "host": "127.0.0.1", "port": metrics_port}}}}]}},
            "pipelines": {INTAKE: intake,
                          TRACES: {"receivers": [RECEIVER], "processors": traces["processors"], "exporters": ["file"]}}},
    }
    cfg_file = pathlib.Path(d) / "config.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg, sort_keys=False))
    env = {**os.environ, "WIB_CLUSTER_NAME": "burritobot-public"}
    val = subprocess.run([str(OTELCOL), "validate", f"--config={cfg_file}", *feature_gate_args("burn")],
                         capture_output=True, text=True, env=env)
    check("the collector accepts the two pipelines, the relay exporter's queue and its receiver", val.returncode == 0,
          val.stderr[-2000:])
    log_path = pathlib.Path(d) / "collector.log"
    log = log_path.open("w")
    proc = subprocess.Popen([str(OTELCOL), f"--config={cfg_file}", *feature_gate_args("burn")], stdout=log,
                            stderr=subprocess.STDOUT, env=env)
    got: dict[str, list[dict]] = {}
    resources: list[dict] = []
    metrics = ""
    try:
        # Spans go only once the collector says it is ready, since free_port's port is free for any process until then.
        sent, start = False, time.time()
        while not sent and time.time() - start < START_BOUND and proc.poll() is None:
            if "Everything is ready" not in log_path.read_text():
                time.sleep(0.3)
                continue
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{http_port}/v1/traces", data=body,
                                             headers={"Content-Type": "application/json"})
                sent = urllib.request.urlopen(req, timeout=10).status == 200
            except OSError:
                time.sleep(0.3)
        waited = time.time() - start
        why = ("" if sent else f"exited {proc.returncode} after {waited:.0f} s" if proc.poll() is not None
               else f"still not taking spans on {http_port} after {waited:.0f} s")
        check(f"the collector took the {SPANS} spans", sent, why)
        deadline = time.time() + 60
        while sent and sum(map(len, got.values())) < SPANS and time.time() < deadline:
            time.sleep(0.5)
            got, resources = read(out)
        if sent:
            time.sleep(1)  # one more read, so a span sent twice shows
            got, resources = read(out)
            with urllib.request.urlopen(f"http://127.0.0.1:{metrics_port}/metrics", timeout=10) as r:
                metrics = r.read().decode()
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        log.close()
    collector_log = log_path.read_text()

print("== every span through the loopback, once ==")
check(f"all {SPANS} spans reached the exporter ({len(got)})", len(got) == SPANS, collector_log[-2000:])
twice = [k for k, v in got.items() if len(v) > 1]
check("no span came out twice", not twice, f"{len(twice)} spans, the first {twice[:3]}")
print("== the processors ran behind otlp/relay ==")


def attrs(obj: dict) -> dict:
    return {a["key"]: a["value"].get("stringValue") for a in obj.get("attributes", [])}


masked = [s for v in got.values() for s in v if "[EMAIL]" in (attrs(s).get("gen_ai.input.messages") or "")
          and "example.co.uk" not in (attrs(s).get("gen_ai.input.messages") or "")]
check("every span's e-mail address came out as [EMAIL] (transform/scrub_pii ran)", len(masked) == len(got) > 0,
      f"{len(masked)} of {len(got)}")
check("every span came out with gen_ai.provider.name aws.bedrock (transform/set_genai_provider ran)",
      all(attrs(s).get("gen_ai.provider.name") == "aws.bedrock" for v in got.values() for s in v) and bool(got))
ips = {attrs(r).get("k8s.pod.ip") for r in resources}
check("each resource carries the sender's address as k8s.pod.ip, written before the loopback", ips == {"127.0.0.1"},
      str(ips))
print("== the collector's own count ==")
sent_relay = metric(metrics, "otelcol_exporter_sent_spans", f'exporter="{EXPORTER}"')
accepted_relay = metric(metrics, "otelcol_receiver_accepted_spans", f'receiver="{RECEIVER}"')
check(f"{EXPORTER} sent {SPANS} ({sent_relay:g})", sent_relay == SPANS, metrics[-1500:])
check(f"{RECEIVER} accepted {SPANS} ({accepted_relay:g})", accepted_relay == SPANS)
for name, label in (("otelcol_exporter_send_failed_spans", EXPORTER), ("otelcol_exporter_enqueue_failed_spans", EXPORTER),
                    ("otelcol_receiver_refused_spans", RECEIVER), ("otelcol_receiver_refused_spans", 'receiver="otlp"')):
    n = metric(metrics, name, label)
    check(f"{name} for {label.split('=')[-1].strip(chr(34))} is 0 ({n:g})", n == 0)
# The gRPC server's own instrumentation counts each Export call otlp/relay served, at the `detailed` level.
calls = {m.group(1): float(m.group(3)) for m in re.finditer(r"^(rpc_server_[a-z_]*duration[a-z_]*_count)\{([^}]*TraceService[^}]*)\} (\S+)$",
                                                          metrics, re.M)}
requests = max(calls.values(), default=0.0)
check(f"the relay exporter cut {SPANS} spans into requests of at most {max_size}: otlp/relay served {requests:g} calls",
      requests >= -(-SPANS // max_size), str(calls) or "no rpc server duration series in the collector's metrics")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All collector relay E2E checks passed.")
