# ABOUTME: Runs the REAL collector binary on the lab-marker pipeline (#150): validates both shipped configs, then
# ABOUTME: feeds it the page's own payload and a forged one and asserts only the documented contract comes out.
# SUITE: e2e (needs otelcol-contrib at the chart's collector version, and node for the page's payload)
#
# Why the binary and not just YAML checks. A config the collector rejects CrashLoops the DaemonSet and takes every
# trace on the cluster down with it, the student's own included (test_collector_config.py has the history). And
# the lab route is public, so what matters about filter/lab_contract and transform/lab_contract is what they do to
# a hostile payload, which only the real OTTL engine can say.
#
# Install: the otelcol-contrib release tarball for OTELCOL_VERSION from
# github.com/open-telemetry/opentelemetry-collector-releases, on PATH or at $OTELCOL_CONTRIB.
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
# The collector the pinned chart ships: opentelemetry-collector chart 0.173.1 has appVersion 0.160.0. A chart
# bump must bump this too, which the first check below enforces.
CHART = "0.173.1"
OTELCOL_VERSION = "0.160.0"
sys.path.insert(0, str(REPO / "verify"))
import collector_render  # noqa: E402  each profile's config as a cluster builds it: value files, then the Datadog overlay
failures: list[str] = []


def check(n: str, c: bool) -> None:
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


binary = os.environ.get("OTELCOL_CONTRIB") or shutil.which("otelcol-contrib")
missing = []
if not binary:
    missing.append("otelcol-contrib is not on PATH and OTELCOL_CONTRIB is not set")
if shutil.which("node") is None:
    missing.append("node is not on PATH")
if missing:
    print("this E2E check runs the real collector and cannot run without it:\n  - " + "\n  - ".join(missing), file=sys.stderr)
    sys.exit(1)

version = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout.strip()
check(f"the binary is the chart's collector ({version})", version.endswith(OTELCOL_VERSION))
apps = list(collector_render.PROFILE_APP.values())
check(f"every collector Application pins chart {CHART}",
      all(re.search(rf'targetRevision: "{re.escape(CHART)}"', p.read_text()) for p in apps))


ENV = {"PATH": "/usr/bin:/bin", "DD_API_KEY": "x", "DD_SITE": "datadoghq.com", "DD_ADMIN_API_KEY": "y",
       "WIB_CLUSTER_NAME": "watch-it-burn-attendee-001", "MY_POD_IP": "127.0.0.1"}

with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    print("== the collector accepts every profile's config, with and without datadog-secret ==")
    for profile, secret in [(p, sec) for p in collector_render.PROFILE_APP for sec in (False, True)]:
        label = f"{profile}, datadog-secret {'present' if secret else 'absent'}"
        f = tmp / "cfg.yaml"
        f.write_text(yaml.safe_dump(collector_render.collector_config(profile, secret)), encoding="utf-8")
        r = subprocess.run([binary, "validate", f"--config=file:{f}"], capture_output=True, text=True, env=ENV, timeout=60)
        check(f"{label} validates", r.returncode == 0)
        if r.returncode:
            print("        " + (r.stderr or r.stdout).strip()[-400:])

    print("== the lab pipeline enforces the contract on real traffic ==")
    # The attendee profile with its secret: the pipeline that carries real students' markers.
    full = collector_render.collector_config("attendee", True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    out_t, out_m = tmp / "traces.json", tmp / "metrics.json"
    pipes = full["service"]["pipelines"]
    lab = {
        "receivers": {"otlp/lab": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
        "processors": {k: full["processors"][k] for k in pipes["traces/lab"]["processors"]},
        "connectors": {"span_metrics/lab": {**full["connectors"]["span_metrics/lab"], "metrics_flush_interval": "1s"}},
        "exporters": {"file/t": {"path": str(out_t)}, "file/m": {"path": str(out_m)}},
        "service": {"telemetry": {"metrics": {"level": "none"}}, "pipelines": {
            # The shipped processors in the shipped order; only the Datadog exporters are swapped for files.
            "traces/lab": {**pipes["traces/lab"], "exporters": ["file/t", "span_metrics/lab"]},
            "metrics/lab": {**pipes["metrics/lab"], "exporters": ["file/m"]}}},
    }
    lab["processors"]["batch"] = {"timeout": "200ms"}
    lab["processors"].setdefault("memory_limiter", full["processors"]["memory_limiter"])
    for k in pipes["metrics/lab"]["processors"]:
        lab["processors"].setdefault(k, full["processors"][k])
    cf = tmp / "lab.yaml"
    cf.write_text(yaml.safe_dump(lab), encoding="utf-8")
    proc = subprocess.Popen([binary, f"--config=file:{cf}"], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    url = f"http://127.0.0.1:{port}/v1/traces"

    def post(body: dict) -> int:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status

    try:
        deadline = time.time() + 30
        while True:
            try:
                post({"resourceSpans": []})
                break
            except OSError:
                if time.time() > deadline or proc.poll() is not None:
                    print((proc.stderr.read() if proc.poll() is not None else "")[-600:], file=sys.stderr)
                    check("the lab pipeline starts", False)
                    raise SystemExit(1)
                time.sleep(0.3)
        h = subprocess.run(["node", str(REPO / "verify/lab-events-harness.js"), str(REPO / "gitops/ai-layer/web/lab-events.js")],
                           capture_output=True, text=True, timeout=60)
        real = [p["body"] for p in json.loads(h.stdout)["posts"]]

        def span(name, attrs, events=None, tid="0" * 31 + "1"):
            return {"traceId": tid, "spanId": tid[:16], "name": name, "kind": 1, "startTimeUnixNano": "1792815457297000000",
                    "endTimeUnixNano": "1792815457297000000", "events": events or [],
                    "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()]}
        forged = {"resourceSpans": [{
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "burritobot"}},
                                        {"key": "k8s.cluster.name", "value": {"stringValue": "watch-it-burn-attendee-999"}}]},
            "scopeSpans": [{"scope": {"name": "x"}, "spans": [
                span("chat", {"gen_ai.input.messages": "FORGED-PROMPT"}, tid="a" * 32),
                span("lab.step.open", {"witb.lab.challenge": "3", "user.email": "FORGED@x", "witb.lab.alias": "A" * 200},
                     events=[{"name": "leak", "timeUnixNano": "1792815457297000000",
                              "attributes": [{"key": "content", "value": {"stringValue": "FORGED-EVENT"}}]}], tid="b" * 32),
                span("lab.not.a.marker.name", {}, tid="c" * 32),
            ]}]}]}
        check("the page's payloads and the forged one are accepted (200)", all(post(b) == 200 for b in real + [forged]))
        deadline = time.time() + 20
        while time.time() < deadline and not (out_t.exists() and out_m.exists() and out_t.stat().st_size and "witb.lab.calls" in out_m.read_text()):
            time.sleep(0.3)
        time.sleep(1.5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    spans, resources = [], set()
    for line in (out_t.read_text().splitlines() if out_t.exists() else []):
        for rs in json.loads(line)["resourceSpans"]:
            resources.add(json.dumps({a["key"]: a["value"]["stringValue"] for a in rs["resource"]["attributes"]}, sort_keys=True))
            for ss in rs["scopeSpans"]:
                spans.extend(ss["spans"])
    names = [s["name"] for s in spans]
    wire = out_t.read_text() if out_t.exists() else ""
    check(f"every span the page sent arrives ({len(names)} spans)",
          {"lab.session.start", "lab.step.open", "lab.hint.open", "lab.command.send", "lab.feedback.open",
           "lab.control.installed", "lab.heartbeat"} <= set(names))
    check("a forged non-lab span (chat, with a prompt) is dropped", "chat" not in names and "FORGED-PROMPT" not in wire)
    check("a name outside lab.<a>[.<b>] is dropped", "lab.not.a.marker.name" not in names)
    check("the resource is burritobot-lab with the cluster's REAL name, whatever the sender claimed",
          resources == {json.dumps({"cluster.name": "watch-it-burn", "k8s.cluster.name": "watch-it-burn-attendee-001",
                                    "service.name": "burritobot-lab"}, sort_keys=True)})
    forged_lab = [s for s in spans if s["name"] == "lab.step.open"
                  and {a["key"]: a["value"]["stringValue"] for a in s["attributes"]}.get("witb.lab.challenge") == "3"]
    fa = {a["key"]: a["value"]["stringValue"] for a in forged_lab[0]["attributes"]} if forged_lab else {}
    check("an undocumented attribute is stripped", forged_lab and "user.email" not in fa and "FORGED@x" not in wire)
    check("span events are stripped", forged_lab and not forged_lab[0].get("events") and "FORGED-EVENT" not in wire)
    check("values are truncated to 64", len(fa.get("witb.lab.alias", "")) == 64)

    mt = out_m.read_text() if out_m.exists() else ""
    series = set()
    for line in mt.splitlines():
        for rm in json.loads(line)["resourceMetrics"]:
            for sm in rm["scopeMetrics"]:
                for m in sm["metrics"]:
                    for dp in (m.get("sum") or {}).get("dataPoints", []):
                        at = {a["key"]: a["value"]["stringValue"] for a in dp.get("attributes", [])}
                        series.add((m["name"], at.get("span.name"), at.get("witb.lab.challenge"), at.get("witb.lab.kind")))
    check("witb.lab.calls is produced, by span.name and the dashboard's dimensions",
          ("witb.lab.calls", "lab.control.installed", "1", None) in series
          and ("witb.lab.calls", "lab.hint.open", "1", "solution") in series)
    check("session.id never becomes a metric tag", "session.id" not in mt)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All lab-pipeline collector checks passed.")
