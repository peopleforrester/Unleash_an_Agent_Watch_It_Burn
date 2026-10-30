# ABOUTME: Live probe for #320, run by hand on an admin or full cluster: one chat through guard-proxy under a trace id
# ABOUTME: it picks, read back out of Tempo as the collector exported it. One root, guard-proxy's POST /chat.
"""Needs kubectl and CONTEXT naming an admin or full cluster, the profiles that run Tempo. Every missing
prerequisite is a failure with the reason. It is a probe rather than a `test_*` file because run-e2e.sh runs
every test against an attendee cluster, which has no Tempo (#475) and so nothing for this to read; a session
with a cluster runs it by hand, as it runs kubecon_probe.py. It spends one model call.

verify/test_collector_one_root_e2e.py runs the interaction's spans through the real collector, shaped from the
components' source. This reads the spans the components really emit, after the collector this cluster runs:

1. a one-shot pod in namespace agent (verify/probe_pod.py, so the armed admin profile admits it) POSTs one /chat
   to guard-proxy with a W3C traceparent this probe made up. guard-proxy extracts it for its POST /chat span, so
   the whole interaction lands in a trace whose id is known here, under a parent that exists nowhere;
2. the trace is read from Tempo, through a port-forward, until ADK's `invocation` is in it and it has stopped
   growing. Tempo gets what Datadog gets: the same traces pipeline, after filter/drop_noise, feeds both;
3. it has exactly one root, guard-proxy's POST /chat, whose parent is the made-up span; the gateway's span and the
   agent's server span are in it; `invocation` hangs off the agent's server span; and no a2a-sdk span is in it,
   which is what OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false on the workshop-agent should make true.

Datadog's banner ("Trace contains multiple root spans") is drawn from the same parent links, so a pass here is
the trace a student opens there. Reading the student's view itself, in Agent Observability, stays a look by eye.

Usage: CONTEXT=<kube-context> [NAMESPACE=agent] python3 verify/one_root_probe.py
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import probe_pod  # noqa: E402

CONTEXT = os.environ.get("CONTEXT", "")
NS = os.environ.get("NAMESPACE", "agent")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("One interaction, one root.")


def kubectl(*args: str, timeout: int = 60, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", CONTEXT, *args], capture_output=True, text=True, timeout=timeout,
                          input=stdin)


def run_pod(pod: dict, timeout: int = 300) -> tuple[str, str]:
    """Create the pod, wait for it to stop, and return its phase and its stdout. The pod is deleted either way."""
    name = pod["metadata"]["name"]
    made = kubectl("create", "-f", "-", stdin=json.dumps(pod))
    if made.returncode != 0:
        return "Refused", made.stderr.strip()
    try:
        phase, deadline = "", time.time() + timeout
        while time.time() < deadline and phase not in ("Succeeded", "Failed"):
            time.sleep(3)
            phase = kubectl("-n", NS, "get", "pod", name, "-o", "jsonpath={.status.phase}").stdout.strip()
        return phase or "Unknown", kubectl("-n", NS, "logs", name).stdout
    finally:
        kubectl("-n", NS, "delete", "pod", name, "--ignore-not-found", "--wait=false")


def hex_id(v: str) -> str:
    """Tempo writes OTLP ids as base64 in JSON; the traceparent and this test use hex."""
    if re.fullmatch(r"[0-9a-f]{16}|[0-9a-f]{32}", v or ""):
        return v
    return base64.b64decode(v).hex() if v else ""


def spans_of(doc) -> list[dict]:
    """Every span in a Tempo trace answer, with its resource's service.name, whatever the envelope."""
    out = []

    def walk(node, svc):
        if isinstance(node, dict):
            res = node.get("resource")
            if isinstance(res, dict):
                svc = next((a["value"].get("stringValue") for a in res.get("attributes", [])
                            if a.get("key") == "service.name"), svc)
            if "spanId" in node and "name" in node:
                out.append({"service": svc, "name": node["name"], "kind": node.get("kind"),
                            "id": hex_id(node["spanId"]), "parent": hex_id(node.get("parentSpanId", ""))})
                return
            for v in node.values():
                walk(v, svc)
        elif isinstance(node, list):
            for v in node:
                walk(v, svc)

    walk(doc, None)
    return out


print("== prerequisites ==")
check("CONTEXT names the cluster (never the current-context)", bool(CONTEXT))
check("kubectl is on PATH", shutil.which("kubectl") is not None)
if failures:
    finish()
tempo = kubectl("-n", "monitoring", "get", "service", "tempo", "-o", "name")
check("the cluster runs Tempo (admin and full do; attendee has none, #475)", tempo.returncode == 0,
      tempo.stderr.strip())
ds = (REPO / "gitops/tempo/grafana-datasource.yaml").read_text(encoding="utf-8")
port = re.search(r"url:\s*http://tempo\.monitoring:(\d+)", ds)
check("gitops/tempo/grafana-datasource.yaml names Tempo's HTTP port", port is not None)
img = kubectl("-n", NS, "get", "deployment", "workshop-mcp", "-o",
              'jsonpath={.spec.template.spec.containers[?(@.name=="shim")].image}')
image = img.stdout.strip() if img.returncode == 0 else ""
check("the workshop-mcp Deployment names the shim image the probe pod runs", bool(image))
if failures:
    finish()

print("== one chat, under a trace id picked here ==")
trace_id, parent_id = uuid.uuid4().hex, uuid.uuid4().hex[:16]
body = json.dumps({"prompt": "Hi BurritoBot! What is on the menu today?", "session": f"one-root-{trace_id[:8]}"})
script = (f"curl -s -m 120 -o /dev/null -w '%{{http_code}}' -X POST http://guard-proxy.{NS}.svc.cluster.local:8080/chat "
          f"-H 'Content-Type: application/json' -H 'traceparent: 00-{trace_id}-{parent_id}-01' -d '{body}'")
phase, answer = run_pod(probe_pod.shell_pod(f"oneroot-{trace_id[:6]}", NS, image, script))
check("guard-proxy answered the chat 200", phase == "Succeeded" and answer.strip() == "200",
      f"pod {phase}: {answer.strip()[:300]}")
if failures:
    finish()

print(f"== trace {trace_id}, out of Tempo ==")
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    local = s.getsockname()[1]
pf = subprocess.Popen(["kubectl", "--context", CONTEXT, "-n", "monitoring", "port-forward", "service/tempo",
                       f"{local}:{port.group(1)}"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
spans: list[dict] = []
try:
    # The collector batches for 5 s and Tempo flushes its ingester on its own clock, so read until `invocation` is
    # there and two reads 15 s apart agree.
    last, deadline = -1, time.time() + 180
    while time.time() < deadline:
        time.sleep(15)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{local}/api/v2/traces/{trace_id}", timeout=15) as r:
                spans = spans_of(json.load(r))
        except OSError:
            continue
        if any(s["name"] == "invocation" for s in spans) and len(spans) == last:
            break
        last = len(spans)
finally:
    pf.terminate()
    pf.wait(timeout=15)

ids = {s["id"] for s in spans}
check("the trace reached Tempo with the agent's invocation in it", any(s["name"] == "invocation" for s in spans),
      f"{len(spans)} spans: {sorted({s['service'] + ' ' + s['name'] for s in spans})}")
roots = [s for s in spans if not s["parent"] or s["parent"] not in ids]
check("one root (Datadog's 'Trace contains multiple root spans' is #320)", len(roots) == 1,
      f"roots: {[(r['service'], r['name']) for r in roots]}")
check("it is guard-proxy's POST /chat, under the traceparent this probe sent",
      [(r["service"], r["name"], r["parent"]) for r in roots] == [("burritobot", "POST /chat", parent_id)],
      f"{roots}")
gateway = [s for s in spans if s["service"] in ("burritobot-gateway", "agentgateway") and s["kind"] in (2, "SPAN_KIND_SERVER")]
check("the gateway's span for the A2A hop is in it", bool(gateway))
server = [s for s in spans if s["service"] == "burritobot-agent" and s["kind"] in (2, "SPAN_KIND_SERVER")
          and re.match(r"POST( |$)", s["name"])]
check("the agent's server span for the message is in it, under the gateway's",
      any(s["parent"] in {g["id"] for g in gateway} for s in server), f"{server}")
# Both kagent's FastAPIInstrumentor and the OTel Operator's injected SDK may wrap the app, so the agent can have a
# server span inside its server span; invocation hangs off one of them.
invocation = [s for s in spans if s["name"] == "invocation"]
check("invocation hangs off the agent's server span",
      bool(invocation) and invocation[0]["parent"] in {s["id"] for s in server}, f"{invocation}")
check("no a2a-sdk span is emitted (OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false on the workshop-agent)",
      not [s for s in spans if s["name"].startswith("a2a.")],
      f"{sorted({s['name'] for s in spans if s['name'].startswith('a2a.')})}")
finish()
