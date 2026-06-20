# ABOUTME: Render-gate check for the P1 cost counter: real token metering climbs; a blocked request flatlines.
# ABOUTME: Imports the canonical guard-proxy and asserts the §2 cost before/after at the logic level.
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PROXY = REPO / "gitops" / "ai-layer" / "proxy.py"

spec = importlib.util.spec_from_file_location("guard_proxy", PROXY)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)  # safe: server only starts under __main__

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# 1. Real metering climbs by (tokens x tier price). The counter is computed, never hardcoded.
pin, pout = 1000, 200
sample = {"result": {"metadata": {"adk_usage_metadata": {
    "promptTokenCount": pin, "candidatesTokenCount": pout, "totalTokenCount": pin + pout}}}}
before = dict(proxy._cost)
proxy.record_usage(sample)
after = dict(proxy._cost)
expected_usd = (pin / 1000.0) * proxy.COST_PER_1K_IN + (pout / 1000.0) * proxy.COST_PER_1K_OUT
check("request count increments", after["requests"] == before["requests"] + 1)
check("input tokens metered from response", after["input_tokens"] == before["input_tokens"] + pin)
check("output tokens metered from response", after["output_tokens"] == before["output_tokens"] + pout)
check(f"cost climbs by tokens x {proxy.MODEL_TIER} price",
      abs(after["usd"] - (before["usd"] + expected_usd)) < 1e-9)
check("cost is non-zero after a real response", after["usd"] > 0)

# 2. Block-list flatlines: destructive intent is matched pre-LLM, so that path never calls record_usage.
check("block-list catches 'delete' intent", proxy.blocklisted("please delete the payments deployment") is not None)
check("block-list catches 'kubectl delete'", proxy.blocklisted("run kubectl delete ns prod") is not None)
check("benign request is allowed through", proxy.blocklisted("list the pods in the apps namespace") is None)
flat_before = dict(proxy._cost)
proxy.record_usage({"result": {}})  # a response with no usage must not move the counter
check("counter flatlines when no token usage is present", proxy._cost["usd"] == flat_before["usd"])

# 3. Per-tier price table is real and ordered (escalation drives the closing-demo cost contrast).
check("tier table has haiku/sonnet/opus", set(proxy.TIER_PRICES_PER_1K) == {"haiku", "sonnet", "opus"})
check("opus output price > sonnet > haiku",
      proxy.TIER_PRICES_PER_1K["opus"]["out"] > proxy.TIER_PRICES_PER_1K["sonnet"]["out"]
      > proxy.TIER_PRICES_PER_1K["haiku"]["out"])

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll cost-counter checks passed.")
