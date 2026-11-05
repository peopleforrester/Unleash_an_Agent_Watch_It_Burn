# ABOUTME: Runs the real agentgateway on both gateway ConfigMaps' tracing (#864) and holds that each exports its spans
# ABOUTME: over OTLP/HTTP with no deprecation warning, keeps an incoming trace id, and samples a request with none.
# SUITE: e2e (needs the agentgateway binary of the deployed gateway version)
# E2E TIER: tools (no cluster, no AWS: the pinned agentgateway from e2e-tools.lock, run on loopback)
"""Why this exists (#864).

agentgateway v1.7.0 still reads the old `config.tracing` block, but logs `config.tracing is deprecated; migrate to
frontendPolicies.tracing` five times at startup and turns the block into a frontend policy itself
(crates/agentgateway/src/types/local.rs, merge_deprecated_frontend_policies, read at tag v1.7.0 on 2026-11-05). A
later version that drops the old key would export no spans at all, and say nothing; every BurritoBot trace would
split again with the agent's subtree orphaned, as #382 described. So both ConfigMaps now say it the new way, under
frontendPolicies.tracing, and this runs that config on the binary.

For agentgateway-config and agentgateway-c7-config in gitops/ai-layer/agentgateway.yaml, the config file is taken as
committed and changed in three places only: the collector's host:port becomes a loopback OTLP receiver this test runs,
the binds become one plain HTTP bind to a loopback upstream (the real backends are cluster services), and the admin,
stats and readiness listeners move to free ports or off. Tracing is not touched. Then each must:

  * start with no deprecation warning in its log;
  * export over OTLP/HTTP: a POST to /v1/traces, protobuf, which is what protocol http sends to the collector's 4318;
  * carry an incoming sampled traceparent's trace id into what it exports, so the gateway's span joins the caller's
    trace instead of starting one (the one-root property verify/one_root_probe.py checks live);
  * and trace a request that arrives with no traceparent at all (randomSampling true).

A negative control puts the same tracing back under config.tracing and requires the warning, so a log this test
cannot read does not pass as a clean one.

The binary is the release's agentgateway-linux-amd64 for the image tag the Deployment runs, pinned in e2e-tools.lock
(the image's own /app/agentgateway is a separate build of the same tag). Run by hand:
AGENTGATEWAY=verify/.tools/bin/agentgateway python3 verify/test_agentgateway_tracing_e2e.py
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = REPO / "gitops/ai-layer/agentgateway.yaml"
LOCK = REPO / "verify/e2e-tools.lock"
COLLECTOR = "otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4318"
DEPRECATED = "config.tracing is deprecated"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nagentgateway tracing: both ConfigMaps export spans the frontendPolicies way.")
    sys.exit(0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Receiver:
    """A loopback OTLP/HTTP receiver: keeps each POST's path, content type and body."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str, bytes]] = []
        posts = self.posts

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                posts.append((self.path, self.headers.get("content-type", ""), body))
                self.send_response(200)
                self.send_header("content-type", "application/x-protobuf")
                self.send_header("content-length", "0")
                self.end_headers()

            def log_message(self, *a) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


class Upstream:
    """The backend the one bind routes to: answers every GET with 200."""

    def __init__(self) -> None:
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("content-length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def run_gateway(binary: str, cfg: dict, tmp: pathlib.Path, label: str) -> dict:
    """Start the gateway on cfg, send one traced and one untraced request, and return what it logged and exported."""
    rx, up = Receiver(), Upstream()
    text = yaml.safe_dump(cfg).replace(COLLECTOR, f"127.0.0.1:{rx.port}")
    cfg = yaml.safe_load(text)
    bind = free_port()
    cfg.setdefault("config", {}).update(
        {"adminAddr": "off", "statsAddr": "off", "readinessAddr": f"127.0.0.1:{free_port()}"})
    cfg["binds"] = [{"port": bind, "listeners": [{"protocol": "HTTP", "routes": [
        {"backends": [{"host": f"127.0.0.1:{up.port}", "weight": 1}]}]}]}]
    path = tmp / f"{label}.yaml"
    path.write_text(yaml.safe_dump(cfg))
    log = tmp / f"{label}.log"
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp), "BEDROCK_NOVA_MODEL": "us.amazon.nova-pro-v1:0",
           "BEDROCK_REGION": "us-west-2", "OTEL_SERVICE_NAME": "burritobot-gateway"}
    trace_id = secrets.token_hex(16)
    out = {"trace_id": trace_id, "started": False, "posts": rx.posts, "log": ""}
    with log.open("w") as fh:
        proc = subprocess.Popen([binary, "-f", str(path)], stdout=fh, stderr=subprocess.STDOUT, env=env)
        try:
            deadline = time.time() + 30
            while time.time() < deadline and proc.poll() is None:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{bind}/warmup", timeout=2).read()
                    out["started"] = True
                    break
                except OSError:
                    time.sleep(0.3)
            if out["started"]:
                req = urllib.request.Request(f"http://127.0.0.1:{bind}/traced",
                                             headers={"traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01"})
                urllib.request.urlopen(req, timeout=5).read()
                urllib.request.urlopen(f"http://127.0.0.1:{bind}/untraced", timeout=5).read()
                deadline = time.time() + 20
                while time.time() < deadline and not any(bytes.fromhex(trace_id) in b for _, _, b in rx.posts):
                    time.sleep(0.3)
                time.sleep(1)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    out["log"] = re.sub(r"\x1b\[[0-9;]*m", "", log.read_text(errors="replace"))
    rx.server.shutdown()
    up.server.shutdown()
    return out


binary = os.environ.get("AGENTGATEWAY", "")
print("== the agentgateway under test is the deployed version ==")
if not binary or not os.access(binary, os.X_OK):
    check("AGENTGATEWAY names an executable agentgateway (run-e2e-tools.sh points it at verify/.tools/bin/agentgateway)",
          False, f"AGENTGATEWAY={binary!r}: run bash verify/fetch-e2e-tools.sh, then AGENTGATEWAY=verify/.tools/bin/agentgateway")
    finish()
docs = [d for d in yaml.safe_load_all(GATEWAY.read_text(encoding="utf-8")) if d]
deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "agentgateway")
tags = {c["image"].split("@", 1)[0].rsplit(":", 1)[-1] for c in deployment["spec"]["template"]["spec"]["containers"]}
try:
    version = json.loads(subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30).stdout)["version"]
except (ValueError, KeyError, subprocess.TimeoutExpired) as e:
    version = f"unreadable ({e})"
check(f"every gateway container runs one tag ({sorted(tags)})", len(tags) == 1)
check(f"$AGENTGATEWAY is that version ({version!r})", tags == {f"v{version}"})
pinned = next((ln.split()[1] for ln in LOCK.read_text().splitlines() if ln.startswith("agentgateway ")), "")
check(f"and e2e-tools.lock's agentgateway ({pinned!r})", pinned == f"v{version}")

configmaps = {d["metadata"]["name"]: yaml.safe_load(d["data"]["config.yaml"])
              for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"].startswith("agentgateway")}
check(f"both gateway ConfigMaps are there ({sorted(configmaps)})",
      set(configmaps) == {"agentgateway-config", "agentgateway-c7-config"})

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    for name, cfg in sorted(configmaps.items()):
        print(f"== {name}, as committed ==")
        tracing = (cfg.get("frontendPolicies") or {}).get("tracing") or {}
        check(f"{name} sends its spans to the collector ({tracing.get('host')!r})", tracing.get("host") == COLLECTOR)
        r = run_gateway(binary, cfg, tmp, name)
        check(f"{name}: the gateway started and served the bind", r["started"], r["log"][-2000:])
        dep = [ln for ln in r["log"].splitlines() if "deprecated" in ln]
        check(f"{name}: it logs no deprecation warning ({len(dep)})", not dep, "\n".join(dep[:3]))
        posts = r["posts"]
        check(f"{name}: it exported spans ({len(posts)} POSTs)", bool(posts), r["log"][-2000:])
        check(f"{name}: every export is OTLP/HTTP protobuf to /v1/traces ({sorted({(p, c) for p, c, _ in posts})})",
              bool(posts) and all(p == "/v1/traces" and c.startswith("application/x-protobuf") for p, c, _ in posts))
        check(f"{name}: the incoming traceparent's trace id is in what it exported",
              any(bytes.fromhex(r["trace_id"]) in b for _, _, b in posts))
        # The warmup and the untraced request both arrive with no traceparent, so each is a random-sampling decision;
        # randomSampling true traces them, and their spans carry trace ids the test did not choose.
        spans_text = b"".join(b for _, _, b in posts)
        check(f"{name}: a request with no traceparent is traced too (randomSampling true)",
              b"/untraced" in spans_text or b"/warmup" in spans_text)

    print("== the negative control: the same tracing under the deprecated config.tracing ==")
    cfg = yaml.safe_load(yaml.safe_dump(configmaps.get("agentgateway-config", {})))
    tracing = (cfg.pop("frontendPolicies", None) or {}).get("tracing") or {}
    cfg.setdefault("config", {})["tracing"] = {"otlpEndpoint": f"http://{tracing.get('host', COLLECTOR)}",
                                               "otlpProtocol": tracing.get("protocol", "http"),
                                               "randomSampling": tracing.get("randomSampling", True)}
    r = run_gateway(binary, cfg, tmp, "deprecated")
    dep = [ln for ln in r["log"].splitlines() if DEPRECATED in ln]
    check(f"config.tracing logs the deprecation warning, so this test reads the gateway's log ({len(dep)} lines)",
          len(dep) >= 1, r["log"][-2000:])
    check("and exports the same way, so the two forms are the same configuration",
          any(bytes.fromhex(r["trace_id"]) in b for _, _, b in r["posts"]))

finish()
