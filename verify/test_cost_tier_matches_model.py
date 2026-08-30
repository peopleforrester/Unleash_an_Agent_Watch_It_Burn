# ABOUTME: Contract test — the proxy's MODEL_TIER must match the kagent ModelConfig the agent is bound to,
# ABOUTME: and that tier must be priced, or the on-screen cost counter shows the wrong model's money.
import importlib.util
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
RESOURCES = (REPO / "gitops" / "ai-layer" / "resources.yaml").read_text()

spec = importlib.util.spec_from_file_location("guard_proxy_tier", REPO / "gitops" / "ai-layer" / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


# What the agent is actually bound to, e.g. "modelConfig: bedrock-nova".
m = re.search(r"^\s*modelConfig:\s*([A-Za-z0-9._-]+)", RESOURCES, re.M)
check("resources.yaml declares the agent's modelConfig", m is not None)
bound = m.group(1) if m else ""

# What the proxy is told to price, e.g. '- { name: MODEL_TIER, value: "nova" }'.
t = re.search(r'name:\s*MODEL_TIER,\s*value:\s*"([^"]+)"', RESOURCES)
check("resources.yaml sets MODEL_TIER for the guard-proxy", t is not None)
tier = (t.group(1) if t else "").lower()

# The bound ModelConfig is named bedrock-<tier>, so the tier must be its suffix. This is the check that
# would have caught MODEL_TIER=sonnet while the agent ran bedrock-nova (found live 2026-08-30, ~4x
# overstatement on the C4 cost counter).
check("MODEL_TIER matches the bound kagent ModelConfig",
      bool(tier) and bool(bound) and bound.endswith(tier),
      f"modelConfig={bound!r} but MODEL_TIER={tier!r}")

# A tier with no price silently falls back to another model's rates.
check("the configured tier is present in the price table",
      tier in proxy.TIER_PRICES_PER_1K,
      f"{tier!r} not in {sorted(proxy.TIER_PRICES_PER_1K)}")

check("the configured tier maps to a full Bedrock model ID",
      tier in proxy._TIER_TO_MODEL_ID,
      f"{tier!r} not in {sorted(proxy._TIER_TO_MODEL_ID)}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll cost-tier checks passed.")
