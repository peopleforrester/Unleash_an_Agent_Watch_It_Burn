# ABOUTME: VERSIONS.lock, docs/TECH-STATUS.md and cost/README.md name kagent_usage_metadata as the A2A usage key,
# ABOUTME: the workshop-agent runs the Python runtime that emits it, and guard-proxy meters it ahead of adk_.
#
# Why (#578). The 2026-06-20 research spike read kagent's docs as emitting `adk_usage_metadata`, and VERSIONS.lock
# and TECH-STATUS recorded that. The live check on kagent 0.9.9 (2026-06-21) found `kagent_usage_metadata`, and
# record_usage() was changed to read it first, but the lock line kept saying the opposite. A rebuild reading the
# lock would re-key the counter to the fallback. Re-checked in the kagent v0.10.1 source (2026-10-25): the Python
# ADK event converter writes get_kagent_metadata_key("usage_metadata") = kagent_usage_metadata; only the Go
# runtime (spec.declarative.runtime: go) writes adka2a.ToA2AMetaKey("usage_metadata") = adk_usage_metadata.
import importlib.util
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


# "the key is X", "key is X (NOT Y)", "parses X": each names X as the key the counter uses.
CLAIM = re.compile(r"(?i)\b(?:key is|parses|reads)\s+`?(adk|kagent)_usage_metadata")

print("== the docs name kagent_usage_metadata as the usage key ==")
for rel in ("VERSIONS.lock", "docs/TECH-STATUS.md", "cost/README.md"):
    text = (REPO / rel).read_text(encoding="utf-8")
    claims = CLAIM.findall(text)
    if rel == "cost/README.md":
        claims += re.findall(r"result\.metadata\.(adk|kagent)_usage_metadata", text)
    check(f"{rel} names the usage key", bool(claims))
    check(f"{rel} names only kagent_usage_metadata as the key (found {claims})",
          claims and all(c.lower() == "kagent" for c in claims))

print("== the workshop-agent runs the runtime that emits kagent_usage_metadata ==")
docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
agents = [d for d in docs if d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent"]
check("resources.yaml has one workshop-agent Agent", len(agents) == 1, f"found {len(agents)}")
runtime = (agents[0]["spec"].get("declarative") or {}).get("runtime", "python") if agents else None
# kagent defaults an unset runtime to python (EffectiveDeclarativeRuntime); go would emit adk_usage_metadata.
check(f"workshop-agent runtime is python (got {runtime!r})", runtime == "python")

print("== guard-proxy meters kagent_usage_metadata, ahead of adk_ ==")
spec = importlib.util.spec_from_file_location("guard_proxy", REPO / "gitops/ai-layer/guard-proxy/proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)  # safe: server only starts under __main__


def usage(pin, pout):
    return {"promptTokenCount": pin, "candidatesTokenCount": pout, "totalTokenCount": pin + pout}


before = proxy._cost["input_tokens"]
proxy.record_usage({"result": {"metadata": {"kagent_usage_metadata": usage(700, 50)}}})
check("record_usage meters a kagent_usage_metadata response", proxy._cost["input_tokens"] - before == 700)

before = proxy._cost["input_tokens"]
proxy.record_usage({"result": {"metadata": {"kagent_usage_metadata": usage(300, 10),
                                            "adk_usage_metadata": usage(9000, 900)}}})
check("record_usage takes kagent_usage_metadata when both keys are present",
      proxy._cost["input_tokens"] - before == 300, f"metered {proxy._cost['input_tokens'] - before}")
check("chat_usage_tokens takes kagent_usage_metadata when both keys are present",
      proxy.chat_usage_tokens({"result": {"metadata": {"kagent_usage_metadata": usage(300, 10),
                                                        "adk_usage_metadata": usage(9000, 900)}}}) == (300, 10))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll A2A usage key checks passed.")
