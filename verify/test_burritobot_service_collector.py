# ABOUTME: Runs the REAL collector on the shipped traces and metrics processors (#629): every resource leaves with
# ABOUTME: env burritobot-kubecon-na-26 and a burritobot service, and the BurritoBot path's own names are untouched.
# SUITE: e2e (needs otelcol-contrib at the chart's collector version)
#
# Why the binary. Whitney's sandbox org holds other projects, and the rules that keep BurritoBot's data apart there
# are an env tag and a burritobot service prefix. transform/burritobot_service and the resource processor enforce
# both at the collector, and what an OTTL statement does to a real payload is something only the OTTL engine can
# say. The root service must stay exactly "burritobot": Datadog names the LLM Observability ml_app after it.
#
# Install: the otelcol-contrib release tarball for 0.160.0 from
# github.com/open-telemetry/opentelemetry-collector-releases, on PATH or at $OTELCOL_CONTRIB.
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
OTELCOL_VERSION = "0.160.0"  # the appVersion of the chart the collector Applications pin; test_lab_pipeline_collector.py holds the pair
DD_ENV = "burritobot-kubecon-na-26"
sys.path.insert(0, str(REPO / "verify"))
import collector_render  # noqa: E402  each profile's config as a cluster builds it
failures: list[str] = []


def check(n: str, c: bool, detail: str = "") -> None:
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)
        if detail:
            print(f"        {detail}")


binary = os.environ.get("OTELCOL_CONTRIB") or shutil.which("otelcol-contrib")
if not binary:
    print("this E2E check runs the real collector and cannot run without it:\n"
          "  - otelcol-contrib is not on PATH and OTELCOL_CONTRIB is not set", file=sys.stderr)
    sys.exit(1)
version = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout.strip()
check(f"the binary is the chart's collector ({version})", version.endswith(OTELCOL_VERSION))

ENV = {"PATH": "/usr/bin:/bin", "DD_API_KEY": "x", "DD_SITE": "datadoghq.com",
       "WIB_CLUSTER_NAME": "burritobot-private", "MY_POD_IP": "127.0.0.1"}
# service.name sent -> service.name Datadog must see. None is a resource with no service.name at all.
CASES = {
    "burritobot": "burritobot",                  # the root: names the ML app, so no hyphen and no prefix
    "burritobot-agent": "burritobot-agent",
    "workshop-agent": "burritobot-workshop-agent",  # what the OTel Operator would name an unpinned pod
    "burritobotx": "burritobot-burritobotx",     # a prefix without the hyphen is not the family
}


def attrs(d: dict) -> list[dict]:
    return [{"key": k, "value": {"stringValue": v}} for k, v in d.items()]


def resource(svc: str | None) -> dict:
    # A sender that claims another env is overridden: the org's rule is one env on everything.
    return {"attributes": attrs({**({"service.name": svc} if svc else {}), "deployment.environment.name": "production"})}


with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    full = collector_render.collector_config("instructor", True)
    pipes = full["service"]["pipelines"]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    out_t, out_m = tmp / "traces.json", tmp / "metrics.json"
    used = set(pipes["traces"]["processors"]) | set(pipes["metrics"]["processors"])
    cfg = {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
        "processors": {k: full["processors"][k] for k in used},
        "exporters": {"file/t": {"path": str(out_t)}, "file/m": {"path": str(out_m)}},
        "service": {"telemetry": {"metrics": {"level": "none"}}, "pipelines": {
            # The shipped processors in the shipped order; only the receivers and exporters are swapped.
            "traces": {"receivers": ["otlp"], "processors": pipes["traces"]["processors"], "exporters": ["file/t"]},
            "metrics": {"receivers": ["otlp"], "processors": pipes["metrics"]["processors"], "exporters": ["file/m"]}}},
    }
    cfg["processors"]["batch"] = {"timeout": "200ms"}
    cf = tmp / "cfg.yaml"
    cf.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    proc = subprocess.Popen([binary, f"--config=file:{cf}"], env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def post(path: str, body: dict) -> int:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status

    try:
        deadline = time.time() + 30
        while True:
            try:
                post("/v1/traces", {"resourceSpans": []})
                break
            except OSError:
                if time.time() > deadline or proc.poll() is not None:
                    print((proc.stderr.read() if proc.poll() is not None else "")[-600:], file=sys.stderr)
                    check("the collector starts on the shipped processors", False)
                    raise SystemExit(1)
                time.sleep(0.3)
        spans = {"resourceSpans": [
            {"resource": resource(svc), "scopeSpans": [{"scope": {"name": "t"}, "spans": [{
                "traceId": f"{i + 1:032x}", "spanId": f"{i + 1:016x}", "name": "invoke_agent", "kind": 2,
                "startTimeUnixNano": "1792815457297000000", "endTimeUnixNano": "1792815457298000000",
                "attributes": attrs({"witb.case": svc or "none"})}]}]}
            for i, svc in enumerate([*CASES, None])]}
        metrics = {"resourceMetrics": [
            {"resource": resource(svc), "scopeMetrics": [{"scope": {"name": "t"}, "metrics": [{
                "name": "witb.case", "gauge": {"dataPoints": [{"timeUnixNano": "1792815457297000000", "asDouble": 1,
                                                               "attributes": attrs({"witb.case": svc or "none"})}]}}]}]}
            for svc in [*CASES, None]]}
        check("spans and metrics are accepted (200)", post("/v1/traces", spans) == 200 and post("/v1/metrics", metrics) == 200)
        deadline = time.time() + 20
        while time.time() < deadline and not (out_t.exists() and out_t.stat().st_size and out_m.exists() and out_m.stat().st_size):
            time.sleep(0.3)
        time.sleep(1.5)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    def seen(path: pathlib.Path, top: str, scope: str, items: str) -> dict[str, dict]:
        """witb.case -> the resource attributes it left the collector with."""
        got = {}
        for line in (path.read_text().splitlines() if path.exists() else []):
            for r in json.loads(line)[top]:
                ra = {a["key"]: a["value"].get("stringValue") for a in r["resource"]["attributes"]}
                for sc in r[scope]:
                    for it in sc[items]:
                        points = it.get("gauge", {}).get("dataPoints", [it])
                        for p in points:
                            case = {a["key"]: a["value"]["stringValue"] for a in p["attributes"]}.get("witb.case")
                            got[case] = ra
        return got

    for kind, got in (("span", seen(out_t, "resourceSpans", "scopeSpans", "spans")),
                      ("metric", seen(out_m, "resourceMetrics", "scopeMetrics", "metrics"))):
        print(f"== {kind}s ==")
        check(f"every {kind} sent came out ({len(got)} of {len(CASES) + 1})", len(got) == len(CASES) + 1, str(sorted(got)))
        for sent, want in CASES.items():
            check(f"{kind} from {sent} leaves as {want}", got.get(sent, {}).get("service.name") == want,
                  str(got.get(sent)))
        # Left alone on purpose: datadog/connector's APM stats reach the metrics pipeline as a payload the Datadog
        # exporter decodes, with no service.name of their own, and the services inside it are already the family.
        check(f"a {kind} with no service.name is left without one",
              "service.name" not in got.get("none", {"service.name": "?"}))
        check(f"every {kind} carries env {DD_ENV}, whatever the sender claimed",
              bool(got) and all(r.get("deployment.environment.name") == DD_ENV for r in got.values()))
        check(f"every {kind} carries the burritobot-<role> cluster name",
              bool(got) and all(r.get("k8s.cluster.name") == r.get("cluster.name") == "burritobot-private" for r in got.values()))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All burritobot service collector checks passed.")
