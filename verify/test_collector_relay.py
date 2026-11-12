# ABOUTME: The traces pipeline's masks run on more than one core (#1336): traces/intake batches the senders' spans onto
# ABOUTME: a queued loopback exporter, and the traces pipeline behind otlp/relay runs every processor per request.
"""Pins #1336's shape of the traces pipeline, on every profile, with and without the Datadog overlays.

#1334's 500-phone replay held the community collector at one core for about 70 s past the last reply: every processor
after `batch` ran on the batch processor's one export goroutine, the receiver stopped taking spans while that goroutine
was busy, and agentgateway and the agent dropped spans when their 10 s export deadlines passed. Since #1336:

  - traces/intake takes the senders' spans on otlp, and runs memory_limiter, k8s_attributes/intake and batch, nothing
    that reads span content, and exports only to otlp_grpc/relay;
  - otlp_grpc/relay is a queued exporter to this pod's own otlp/relay receiver, on 127.0.0.1, with at least two
    consumers and no more than the container's CPU limit, requests of at most 512 spans, a timeout of 30 s or more, no
    retry (a retried request would run the masks twice and export its spans twice), and a receive limit above gRPC's
    default 4 MiB;
  - the traces pipeline takes otlp/relay alone, and carries no batch processor, which would put its processors back
    on one goroutine, and no memory_limiter, which the intake already applies;
  - otlp/relay feeds the traces pipeline alone, and otlp_grpc/relay is fed by traces/intake alone;
  - k8s_attributes/intake is a passthrough that writes the sender's connection address as k8s.pod.ip, so the chart's
    k8s_attributes, which it prepends to the traces pipeline, still finds each span's pod behind the loopback.

The loopback is 127.0.0.1, not localhost. The receiver binds localhost's IPv4 address alone, and the exporter's gRPC
client also resolves localhost to [::1], is refused there, and logs a connect warning every two minutes; the community
collector did that from the split's rollout until run 20576 pinned the address. The exporter waits for its connection
(wait_for_ready): it dials as the collector starts, often before otlp/relay listens, and a request that fails fast
on that refused first connection is not retried, so its spans are lost.

A config with `batch` put back into the traces pipeline must fail the checks, so they tell the two shapes apart.
test_collector_relay_e2e.py runs spans through the real collector over the loopback.

Offline: reads the collector value files and the overlays through collector_render.py.
"""
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collector_render import collector_config, helm_values  # noqa: E402

INTAKE, TRACES = "traces/intake", "traces"
RECEIVER, EXPORTER, PASS = "otlp/relay", "otlp_grpc/relay", "k8s_attributes/intake"
INTAKE_PROCESSORS = ["memory_limiter", PASS, "batch"]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def cpu_limit(vals: dict) -> float:
    raw = str(vals["resources"]["limits"]["cpu"])
    return float(raw[:-1]) / 1000 if raw.endswith("m") else float(raw)


def problems(cfg: dict, cpus: float) -> list[str]:
    """Every way cfg falls short of #1336's shape, each named; empty when it holds."""
    out: list[str] = []
    pipes = cfg["service"]["pipelines"]
    intake, traces = pipes.get(INTAKE, {}), pipes.get(TRACES, {})
    if intake.get("receivers") != ["otlp"]:
        out.append(f"{INTAKE} receives {intake.get('receivers')}, not ['otlp']")
    if intake.get("processors") != INTAKE_PROCESSORS:
        out.append(f"{INTAKE} runs {intake.get('processors')}, not {INTAKE_PROCESSORS}")
    if intake.get("exporters") != [EXPORTER]:
        out.append(f"{INTAKE} exports to {intake.get('exporters')}, not [{EXPORTER!r}]")
    if traces.get("receivers") != [RECEIVER]:
        out.append(f"{TRACES} receives {traces.get('receivers')}, not [{RECEIVER!r}]")
    for p in ("batch", "memory_limiter"):
        if p in traces.get("processors", []):
            out.append(f"{TRACES} runs {p}")
    for name, pipe in pipes.items():
        if name != TRACES and RECEIVER in pipe.get("receivers", []):
            out.append(f"{name} receives {RECEIVER} too")
        if name != INTAKE and EXPORTER in pipe.get("exporters", []):
            out.append(f"{name} exports to {EXPORTER} too")
        if name.startswith("traces") and name not in (INTAKE, "traces/lab") and "otlp" in pipe.get("receivers", []):
            out.append(f"{name} takes the senders' spans on otlp, past the intake")
    grpc = (cfg["receivers"].get(RECEIVER, {}).get("protocols") or {}).get("grpc") or {}
    exp = cfg["exporters"].get(EXPORTER, {})
    if set((cfg["receivers"].get(RECEIVER, {}).get("protocols") or {})) != {"grpc"}:
        out.append(f"{RECEIVER} serves {sorted(cfg['receivers'].get(RECEIVER, {}).get('protocols') or {})}, not grpc alone")
    if not str(grpc.get("endpoint", "")).startswith("127.0.0.1:"):
        out.append(f"{RECEIVER} listens on {grpc.get('endpoint')!r}, not on 127.0.0.1")
    if exp.get("endpoint") != grpc.get("endpoint"):
        out.append(f"{EXPORTER} sends to {exp.get('endpoint')!r}, not {RECEIVER}'s {grpc.get('endpoint')!r}")
    if (grpc.get("max_recv_msg_size_mib") or 4) <= 4:
        out.append(f"{RECEIVER} takes gRPC's default 4 MiB message; a batch of model-call spans is larger")
    if exp.get("wait_for_ready") is not True:
        out.append(f"{EXPORTER} has no wait_for_ready, so a request sent before its first connection drops its spans")
    if not (exp.get("tls") or {}).get("insecure"):
        out.append(f"{EXPORTER} does not send in the clear to the loopback")
    q = exp.get("sending_queue") or {}
    consumers = q.get("num_consumers", 10)
    if not q.get("enabled"):
        out.append(f"{EXPORTER} has no sending queue, so the batch goroutine would run the masks again")
    if not 2 <= consumers <= cpus:
        out.append(f"{EXPORTER} has {consumers} consumers, not 2 to the container's {cpus:g} CPUs")
    if not 0 < ((q.get("batch") or {}).get("max_size") or 0) <= 512:
        out.append(f"{EXPORTER}'s requests are not cut to 512 spans or fewer ({q.get('batch')})")
    if (q.get("batch") or {}).get("sizer", q.get("sizer")) != "items" or q.get("sizer") != "items":
        out.append(f"{EXPORTER}'s queue and batches are not counted in spans ({q})")
    timeout = str(exp.get("timeout", "5s"))
    if not (timeout.endswith("s") and timeout[:-1].isdigit() and int(timeout[:-1]) >= 30):
        out.append(f"{EXPORTER}'s timeout is {timeout}, under the 30 s a 256-span request can take")
    if (exp.get("retry_on_failure") or {}).get("enabled", True):
        out.append(f"{EXPORTER} retries, so a timed-out request would be masked and exported twice")
    k8s = cfg["processors"].get(PASS, {})
    sources = [s.get("from") for a in k8s.get("pod_association", []) for s in a.get("sources", [])]
    if k8s.get("passthrough") is not True or "connection" not in sources:
        out.append(f"{PASS} is not a passthrough that reads the connection ({k8s})")
    return out


for profile in ("instructor", "attendee", "burn"):
    cpus = cpu_limit(helm_values(profile))
    states = [("no datadog-secret", False, False), ("datadog-secret", True, False)]
    if profile == "attendee":
        states.append(("datadog-secret and datadog-admin-secret", True, True))
    print(f"== {profile} (CPU limit {cpus:g}) ==")
    for label, secret, admin in states:
        cfg = collector_config(profile, datadog_secret=secret, admin_secret=admin)
        found = problems(cfg, cpus)
        check(f"{label}: the masks run behind {RECEIVER}, on {EXPORTER}'s consumers", not found, "; ".join(found))

print("== the checks tell the two shapes apart ==")
cfg = collector_config("burn", datadog_secret=True)
cpus = cpu_limit(helm_values("burn"))
mutant = copy.deepcopy(cfg)
mutant["service"]["pipelines"][TRACES]["processors"].insert(0, "batch")
check("batch put back into the traces pipeline fails them", any("runs batch" in p for p in problems(mutant, cpus)))
mutant = copy.deepcopy(cfg)
mutant["service"]["pipelines"][INTAKE]["processors"].append("transform/coc_mask")
check("the mask moved into the intake fails them", any(INTAKE in p for p in problems(mutant, cpus)))
mutant = copy.deepcopy(cfg)
mutant["exporters"][EXPORTER]["retry_on_failure"] = {"enabled": True}
check("a retrying relay exporter fails them", any("retries" in p for p in problems(mutant, cpus)))
mutant = copy.deepcopy(cfg)
mutant["exporters"][EXPORTER]["sending_queue"]["num_consumers"] = 1
check("one consumer fails them", any("consumers" in p for p in problems(mutant, cpus)))
mutant = copy.deepcopy(cfg)
mutant["receivers"][RECEIVER]["protocols"]["grpc"]["endpoint"] = "localhost:4320"
mutant["exporters"][EXPORTER]["endpoint"] = "localhost:4320"
check("a relay on localhost, which the exporter also dials as [::1], fails them",
      any("not on 127.0.0.1" in p for p in problems(mutant, cpus)))
mutant = copy.deepcopy(cfg)
del mutant["exporters"][EXPORTER]["wait_for_ready"]
check("a relay exporter that fails fast before its first connection fails them",
      any("wait_for_ready" in p for p in problems(mutant, cpus)))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALL CHECKS PASSED")
