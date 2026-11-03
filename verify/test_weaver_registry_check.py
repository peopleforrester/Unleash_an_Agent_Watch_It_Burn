# ABOUTME: Runs the pinned weaver on weaver/registry: `registry check` passes, a typo'd ref fails it, and the resolved
# ABOUTME: groups carry the attributes the Go guard-proxy generates its keys from, and the values proxy.py sends (#782).
# SUITE: e2e (needs the pinned weaver binary, and network for the OTel semconv v1.37.0 archive the manifest pins)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. guard-proxy-agenticburn's scripts/gen-semconv.sh generates the Go build's attribute keys from this registry, so
# a ref that does not resolve breaks the Go build's next regeneration, not just the GitHub workflow. Until #782 the
# check ran only in .github/workflows/weaver-registry-check.yml, which the hecaton gate never sees; this runs the same
# weaver (test_e2e_tools_tier.py holds the lock to the workflow's pin) where the gate does. The offline lockstep with
# proxy.py is test_weaver_guard_proxy_spans.py and test_weaver_guard_proxy_stamps.py.
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
REG = REPO / "weaver/registry"
WANT_VERSION = "0.24.2"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


weaver = shutil.which("weaver")
if weaver is None:
    print("FAILED: weaver is not on PATH. run-e2e-tools.sh and run-e2e.sh put the pinned one there "
          "(verify/fetch-e2e-tools.sh); this is a failure, not a skip.")
    sys.exit(1)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([weaver, *args], capture_output=True, text=True, timeout=600)


print("== the weaver on PATH is the pinned one ==")
v = run("--version")
check(f"weaver --version is {WANT_VERSION} ({v.stdout.strip()})",
      v.returncode == 0 and v.stdout.split()[-1:] == [WANT_VERSION])

print("== weaver registry check ==")
r = run("registry", "check", "--registry", str(REG))
check(f"weaver/registry passes `weaver registry check` (exit {r.returncode})", r.returncode == 0, r.stdout + r.stderr)

with tempfile.TemporaryDirectory() as t:
    bad = pathlib.Path(t) / "registry"
    shutil.copytree(REG, bad)
    spans = bad / "guard-proxy-spans.yaml"
    text = spans.read_text()
    spans.write_text(text.replace("ref: error.type", "ref: error.typo", 1))
    r = run("registry", "check", "--registry", str(bad))
    check("a ref that names no upstream attribute fails the check, so a pass above means something",
          "ref: error.type" in text and r.returncode != 0 and "error.typo" in r.stdout + r.stderr, r.stdout + r.stderr)

    out = pathlib.Path(t) / "resolved.json"
    r = run("registry", "resolve", "--registry", str(REG), "--format", "json", "--output", str(out))
    check(f"weaver resolves the registry to JSON (exit {r.returncode})", r.returncode == 0 and out.is_file(),
          r.stdout + r.stderr)
    resolved = json.loads(out.read_text()) if out.is_file() else {"groups": []}

groups = {g["id"]: g for g in resolved.get("groups", [])}


def attrs(gid: str) -> dict:
    return {a["name"]: a for a in groups.get(gid, {}).get("attributes", [])}


print("== the resolved groups carry what the Go build generates its keys from (#782) ==")
for gid, need in (("span.witb.guard_proxy.http", {"gen_ai.request.model", "gen_ai.operation.name"}),
                  ("span.witb.guard_proxy.sanitize", {"gen_ai.request.model"}),
                  ("span.witb.guard_proxy.egress", {"error.type"}),
                  ("span.witb.guard_proxy.chat", {"gen_ai.operation.name", "gen_ai.request.model",
                                                  "gen_ai.input.messages", "gen_ai.output.messages"}),
                  ("metric.witb.guard_proxy.cost", {"gen_ai.provider.name", "gen_ai.request.model"})):
    have = set(attrs(gid))
    check(f"{gid} resolves with {sorted(need)}", need <= have, f"resolved: {sorted(have)}")

chat = groups.get("span.witb.guard_proxy.chat", {})
check("span.witb.guard_proxy.chat resolves as an INTERNAL span", chat.get("type") == "span"
      and chat.get("span_kind") == "internal", str({k: chat.get(k) for k in ("type", "span_kind")}))
cost = groups.get("metric.witb.guard_proxy.cost", {})
check("metric.witb.guard_proxy.cost resolves as the gen_ai.client.cost gauge in USD",
      (cost.get("type"), cost.get("metric_name"), cost.get("instrument"), cost.get("unit"))
      == ("metric", "gen_ai.client.cost", "gauge", "USD"), str(cost.get("metric_name")))



def member_values(gid: str, name: str) -> set:
    t = attrs(gid).get(name, {}).get("type")
    return {m.get("value") for m in t.get("members") or []} if isinstance(t, dict) else set()


members = member_values("metric.witb.guard_proxy.cost", "gen_ai.provider.name")
check("aws.bedrock, which proxy.py observes on the gauge, is a gen_ai.provider.name member in semconv v1.37.0",
      "aws.bedrock" in members, f"members: {sorted(m for m in members if m)}")
check("gen_ai.request.model resolves as a string", attrs("span.witb.guard_proxy.sanitize")
      .get("gen_ai.request.model", {}).get("type") == "string")
check("error.type resolves (a string enum whose fallback is _OTHER)",
      "_OTHER" in member_values("span.witb.guard_proxy.egress", "error.type"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("weaver/registry passes the pinned weaver's check and resolves what the guard-proxy builds generate from.")
