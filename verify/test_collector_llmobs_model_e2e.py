# ABOUTME: Runs kagent model calls named by application profile ARNs through the real otelcol-contrib for every profile
# ABOUTME: (#784): Agent Observability's copy names the system id Datadog prices, APM's keeps the ARN.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: the pinned otelcol-contrib from e2e-tools.lock, run on loopback)
"""Agent Observability can price a BurritoBot model call only by a model name in Datadog's catalog.

On 2026-11-05 a fresh chat on each KubeCon bot reached Agent Observability with its token counts, and every
generate_content row read cost_estimate_status skipped_unsupported_model_pricing: its model is the cluster's tagged
application profile ARN (#513). A row of the same spans named us.amazon.nova-pro-v1:0 read success. This test sends a
turn's model calls as kagent writes them on a pinned cluster, with the ARNs in the environment the way
monitoring/bedrock-profile-models gives them to the collector, through each profile's traces and traces/llmobs
pipelines as built with datadog-secret present (collector_render.py), and reads both copies:

  - in Agent Observability's copy, the nova and opus calls name their system id, on gen_ai.request.model,
    gen_ai.response.model and the span name, keep their token counts, and carry the ARN as
    witb.bedrock.application_profile (#876);
  - APM's copy keeps the ARN on all three, since the profile is what the bill's tags trace;
  - a call to an ARN the map does not name (another cluster's profile) goes out unchanged;
  - with no map at all, a cluster that fleet.sh has not pinned yet, nothing is renamed and the collector still starts.

The offline half, verify/test_collector_llmobs_model.py, holds the rules against resources.yaml and fleet.sh.
Fails when the binary is missing: run verify/fetch-e2e-tools.sh (verify/run-e2e-tools.sh does).
"""
from __future__ import annotations

import hashlib
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
from collector_render import REPO, collector_config, feature_gate_args  # noqa: E402

OTELCOL = REPO / "verify/.tools/bin/otelcol-contrib"
LOCK = REPO / "verify/e2e-tools.lock"
PROFILES = ("instructor", "attendee", "burn")

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

INTERNAL = 1
AGENT = "burritobot-agent"
NOVA, OPUS = "us.amazon.nova-pro-v1:0", "us.anthropic.claude-opus-4-8"


def arn(suffix: str) -> str:
    return f"arn:aws:bedrock:us-west-2:111122223333:application-inference-profile/{suffix}"


# The map as fleet.sh writes it on this cluster, and a profile it does not name (the other cluster's nova).
MAP = {"WIB_BEDROCK_PROFILE_NOVA": arn("5l72jg8rnz71"), "WIB_BEDROCK_PROFILE_HAIKU": arn("3awxpzvcwthh"),
       "WIB_BEDROCK_PROFILE_SONNET": arn("pzme042z8bar"), "WIB_BEDROCK_PROFILE_OPUS": arn("3hwzcjrng207")}
OTHER = arn("88hce5o0zw45")
TRACE = "5d3c0e9f1a2b4c6d8e0f1a2b3c4d0784"
# (key, model ARN, parent key, the system id the copy must name, or None for unchanged, input tokens, output tokens)
CALLS = [
    ("nova", MAP["WIB_BEDROCK_PROFILE_NOVA"], NOVA, 5312, 44),
    ("opus", MAP["WIB_BEDROCK_PROFILE_OPUS"], OPUS, 2015, 31),
    ("other", OTHER, None, 1702, 12),
]


def sid(key: str) -> str:
    return hashlib.sha256(f"{TRACE}/{key}".encode()).hexdigest()[:16]


def kv(key: str, value: str | int) -> dict:
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def otlp_body() -> bytes:
    """kagent's invocation and invoke_agent, with one generate_content per call under it, as adk-go v2.1.0 names them:
    "generate_content <model>", the model on gen_ai.request.model and gen_ai.response.model."""
    t0 = 1730000000000000000
    spans = [
        {"traceId": TRACE, "spanId": sid("invocation"), "name": "invocation", "kind": INTERNAL,
         "startTimeUnixNano": str(t0), "endTimeUnixNano": str(t0 + 10**9),
         "attributes": [kv("gen_ai.conversation.id", "c784")]},
        {"traceId": TRACE, "spanId": sid("agent"), "parentSpanId": sid("invocation"), "name": "invoke_agent burritobot",
         "kind": INTERNAL, "startTimeUnixNano": str(t0 + 1000), "endTimeUnixNano": str(t0 + 10**9 - 1000),
         "attributes": [kv("gen_ai.operation.name", "invoke_agent"), kv("gen_ai.agent.name", "burritobot")]},
    ]
    for i, (key, model, _, tin, tout) in enumerate(CALLS):
        spans.append({"traceId": TRACE, "spanId": sid(key), "parentSpanId": sid("agent"),
                      "name": f"generate_content {model}", "kind": INTERNAL,
                      "startTimeUnixNano": str(t0 + 10**6 * (i + 1)), "endTimeUnixNano": str(t0 + 10**6 * (i + 2)),
                      "attributes": [kv("gen_ai.operation.name", "generate_content"), kv("gen_ai.request.model", model),
                                     kv("gen_ai.response.model", model), kv("gen_ai.usage.input_tokens", tin),
                                     kv("gen_ai.usage.output_tokens", tout)]})
    return json.dumps({"resourceSpans": [{"resource": {"attributes": [kv("service.name", AGENT)]},
                                          "scopeSpans": [{"spans": spans}]}]}).encode()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read_spans(out: pathlib.Path) -> dict[str, dict]:
    """Every span the file exporter wrote, by its span id."""
    got: dict[str, dict] = {}
    for line in (out.read_text().splitlines() if out.exists() else []):
        for rs in json.loads(line)["resourceSpans"]:
            for ss in rs["scopeSpans"]:
                for s in ss["spans"]:
                    got[s["spanId"].lower()] = s
    return got


def values(span: dict) -> dict:
    return {a["key"]: next(iter(a["value"].values())) for a in span.get("attributes", [])}


def run_collector(profile: str, env_map: dict[str, str]) -> tuple[dict[str, dict], dict[str, dict], str]:
    """The profile's two trace pipelines with datadog-secret present, from OTLP/HTTP in to a file per Datadog intake,
    with env_map in the collector's environment as extraEnvsFrom puts the ConfigMap's keys there."""
    conf = collector_config(profile, datadog_secret=True)
    pipes = conf["service"]["pipelines"]
    procs, lprocs = pipes["traces"]["processors"], pipes["traces/llmobs"]["processors"]
    port = free_port()
    with tempfile.TemporaryDirectory() as d:
        out, lout = pathlib.Path(d) / "apm.json", pathlib.Path(d) / "llmobs.json"
        cfg = {
            "receivers": {"otlp": {"protocols": {"http": {"endpoint": f"127.0.0.1:{port}"}}}},
            "processors": {p: conf["processors"][p] for p in procs + lprocs},
            "connectors": {"forward/llmobs": conf["connectors"]["forward/llmobs"]},
            "exporters": {"file/apm": {"path": str(out)}, "file/llmobs": {"path": str(lout)}},
            "service": {"telemetry": {"metrics": {"level": "none"}},
                        "pipelines": {"traces": {"receivers": ["otlp"], "processors": procs,
                                                 "exporters": ["file/apm", "forward/llmobs"]},
                                      "traces/llmobs": {"receivers": ["forward/llmobs"], "processors": lprocs,
                                                        "exporters": ["file/llmobs"]}}},
        }
        cfg_file = pathlib.Path(d) / "config.yaml"
        cfg_file.write_text(yaml.safe_dump(cfg, sort_keys=False))
        env = {k: v for k, v in os.environ.items() if not k.startswith("WIB_BEDROCK_PROFILE_")}
        env.update({"WIB_CLUSTER_NAME": f"burritobot-{profile}", **env_map})
        val = subprocess.run([str(OTELCOL), "validate", f"--config={cfg_file}", *feature_gate_args(profile)],
                             capture_output=True, text=True, env=env)
        check(f"{profile}: the collector accepts the pipelines", val.returncode == 0, val.stderr)
        log_file = pathlib.Path(d) / "collector.log"
        log = log_file.open("w")
        proc = subprocess.Popen([str(OTELCOL), f"--config={cfg_file}", *feature_gate_args(profile)], stdout=log,
                                stderr=subprocess.STDOUT, env=env)
        want = 2 + len(CALLS)
        try:
            # Polls, not wall seconds, as test_trace_shape_e2e.py waits (#799): a host stall spends none of them, and
            # the port is the collector's own only once it says it is ready.
            sent, polls = False, 0
            while not sent and polls < 100 and proc.poll() is None:
                polls += 1
                if "Everything is ready" not in log_file.read_text():
                    time.sleep(0.3)
                    continue
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=otlp_body(),
                                                 headers={"Content-Type": "application/json"})
                    sent = urllib.request.urlopen(req, timeout=5).status == 200
                except OSError:
                    time.sleep(0.3)
            check(f"{profile}: the collector took the spans", sent, f"collector log tail:\n{log_file.read_text()[-1500:]}")
            got, lgot, polls = {}, {}, 0
            while sent and (len(got) < want or len(lgot) < want) and polls < 60:
                time.sleep(0.5)
                got, lgot, polls = read_spans(out), read_spans(lout), polls + 1
        finally:
            proc.terminate()
            proc.wait(timeout=15)
            log.close()
        return got, lgot, log_file.read_text()


for profile in PROFILES:
    print(f"== {profile}: a pinned cluster, monitoring/bedrock-profile-models loaded ==")
    got, lgot, collector_log = run_collector(profile, MAP)
    for key, model, system_id, tin, tout in CALLS:
        apm, copy = got.get(sid(key), {}), lgot.get(sid(key), {})
        check(f"{profile}: the {key} call reaches both copies", bool(apm) and bool(copy),
              f"APM {sorted(got)}, copy {sorted(lgot)}\n{collector_log[-1500:]}")
        a, c = values(apm), values(copy)
        name = system_id or model
        check(f"{profile}: Agent Observability's {key} call names {name} as its model, request and response",
              c.get("gen_ai.request.model") == name and c.get("gen_ai.response.model") == name,
              f'{c.get("gen_ai.request.model")} / {c.get("gen_ai.response.model")}')
        check(f"{profile}: and its row is generate_content {name}", copy.get("name") == f"generate_content {name}",
              str(copy.get("name")))
        check(f"{profile}: the copy keeps the {key} call's profile as witb.bedrock.application_profile (#876)"
              if system_id else f"{profile}: an unmapped call gets no witb.bedrock.application_profile",
              c.get("witb.bedrock.application_profile") == (model if system_id else None),
              str(c.get("witb.bedrock.application_profile")))
        check(f"{profile}: with its token counts as sent, which Datadog prices by that name",
              c.get("gen_ai.usage.input_tokens") == str(tin) and c.get("gen_ai.usage.output_tokens") == str(tout),
              f'{c.get("gen_ai.usage.input_tokens")} / {c.get("gen_ai.usage.output_tokens")}')
        check(f"{profile}: APM's {key} call keeps the profile ARN everywhere",
              a.get("gen_ai.request.model") == model and a.get("gen_ai.response.model") == model
              and apm.get("name") == f"generate_content {model}", f'{a.get("gen_ai.request.model")} {apm.get("name")}')
    agent = values(lgot.get(sid("agent"), {}))
    check(f"{profile}: a span with no model is left as it was", "gen_ai.request.model" not in agent
          and agent.get("gen_ai.operation.name") == "invoke_agent", str(agent))

    print(f"== {profile}: a cluster fleet.sh has not pinned, no map ==")
    got, lgot, collector_log = run_collector(profile, {})
    renamed = sorted(key for key, model, *_ in CALLS
                     if values(lgot.get(sid(key), {})).get("gen_ai.request.model") != model
                     or "witb.bedrock.application_profile" in values(lgot.get(sid(key), {}))
                     or lgot.get(sid(key), {}).get("name") != f"generate_content {model}")
    check(f"{profile}: every call reaches Agent Observability as sent, nothing renamed",
          all(sid(key) in lgot for key, *_ in CALLS) and not renamed, f"{renamed}\n{collector_log[-1500:]}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All llmobs model-name E2E checks passed.")
