# ABOUTME: Render-gate check for the P1 cost counter: real token metering climbs; a blocked request flatlines.
# ABOUTME: Imports the canonical guard-proxy and asserts the §2 cost before/after at the logic level.
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PROXY = REPO / "gitops" / "ai-layer" / "guard-proxy" / "proxy.py"

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
sample = {"result": {"metadata": {"kagent_usage_metadata": {
    "promptTokenCount": pin, "candidatesTokenCount": pout, "totalTokenCount": pin + pout}}}}
before = dict(proxy._cost)
proxy.record_usage(sample)
after = dict(proxy._cost)
# Off a cluster the Agent cannot be read, so the price is the MODEL_TIER row on every build: the start-up default
# of one that prices at the bound model (guard-proxy-agenticburn#37), the only price of one before it.
row = proxy.TIER_PRICES_PER_1K.get(proxy.MODEL_TIER, proxy.TIER_PRICES_PER_1K["haiku"])
expected_usd = (pin / 1000.0) * row["in"] + (pout / 1000.0) * row["out"]
check("request count increments", after["requests"] == before["requests"] + 1)
check("input tokens metered from response", after["input_tokens"] == before["input_tokens"] + pin)
check("output tokens metered from response", after["output_tokens"] == before["output_tokens"] + pout)
check(f"cost climbs by tokens x {proxy.MODEL_TIER} price",
      abs(after["usd"] - (before["usd"] + expected_usd)) < 1e-9)
check("cost is non-zero after a real response", after["usd"] > 0)

# 1b. A live tier swap (#793). A build that carries guard-proxy-agenticburn#37 prices each request at the tier of
# the workshop-agent Agent's bound ModelConfig, re-read after the 5 s cache, with MODEL_TIER untouched; a build
# before it prices at MODEL_TIER whatever the Agent is bound to, so its swap has to move MODEL_TIER too. Whichever
# build is pinned is held to its own pricing. The Agent read is stubbed.
BOUND = callable(getattr(proxy, "_tier_of", None)) and callable(getattr(proxy, "bound_tier", None))
print(f"  (the pinned proxy.py prices at {'the bound ModelConfig' if BOUND else 'MODEL_TIER alone'})")
bound = {"modelConfig": "bedrock-nova"}
proxy._k8s_get = lambda path: ({"spec": {"declarative": dict(bound)}}
                               if path.endswith("/agents/workshop-agent") else None)


def priced_after_swap(model_config):
    """The USD one sample request adds after the Agent is patched to model_config and the cache has expired."""
    bound["modelConfig"] = model_config
    if BOUND:
        proxy._binding["at"] = None  # past the 5 s cache, as the room's next turn after a swap would be
    was = proxy._cost["usd"]
    proxy.record_usage(sample)
    return proxy._cost["usd"] - was


def at(tier):
    r = proxy.TIER_PRICES_PER_1K[tier]
    return (pin / 1000.0) * r["in"] + (pout / 1000.0) * r["out"]


mt = proxy.MODEL_TIER
if BOUND:
    usd = priced_after_swap("bedrock-nova")
    check("bound to bedrock-nova, a request is priced at Nova rates",
          proxy.bound_tier() == "nova" and abs(usd - at("nova")) < 1e-12)
    usd = priced_after_swap("bedrock-haiku")
    check("after a live swap to bedrock-haiku, with MODEL_TIER unchanged, it is priced at Haiku rates",
          proxy.bound_tier() == "haiku" and abs(usd - at("haiku")) < 1e-12 and proxy.MODEL_TIER == mt)
    usd = priced_after_swap("bedrock-opus")
    check("and a swap to bedrock-opus at Opus rates", proxy.bound_tier() == "opus" and abs(usd - at("opus")) < 1e-12)
    usd = priced_after_swap("gateway-local-qwen3")
    check("a ModelConfig with no bedrock-<tier> name is priced at MODEL_TIER",
          proxy.bound_tier() == mt and abs(usd - at(mt)) < 1e-12)
    bound["modelConfig"] = "bedrock-sonnet"
    check("within the 5 s cache a swap is not yet read", proxy.bound_tier() == mt)
else:
    usd = priced_after_swap("bedrock-haiku")
    check(f"this build prices a swap to bedrock-haiku at the MODEL_TIER row ({mt}), so its swap moves MODEL_TIER too",
          abs(usd - at(mt)) < 1e-12 and proxy.MODEL_TIER == mt)

# 2. Block-list flatlines: destructive intent is matched pre-LLM, so that path never calls record_usage.
check("block-list catches 'delete' intent", proxy.blocklisted("please delete the payments deployment") is not None)
check("block-list catches 'kubectl delete'", proxy.blocklisted("run kubectl delete ns prod") is not None)
check("benign request is allowed through", proxy.blocklisted("list the pods in the apps namespace") is None)
flat_before = dict(proxy._cost)
proxy.record_usage({"result": {}})  # a response with no usage must not move the counter
check("counter flatlines when no token usage is present", proxy._cost["usd"] == flat_before["usd"])

# 3. Per-tier price table is real and ordered (escalation drives the closing-demo cost contrast).
# Superset, not equality: the table gained "nova" on 2026-08-30 when the workshop default moved to
# Nova Pro (the agent's bound ModelConfig). Pinning the exact set made adding the model the fleet actually
# runs a test failure, which is backwards. The three Claude tiers must stay for the cost-race demo.
check("tier table has the haiku/sonnet/opus cost-race tiers",
      {"haiku", "sonnet", "opus"} <= set(proxy.TIER_PRICES_PER_1K))
check("every priced tier has both an input and an output rate",
      all({"in", "out"} <= set(v) for v in proxy.TIER_PRICES_PER_1K.values()))
check("opus output price > sonnet > haiku",
      proxy.TIER_PRICES_PER_1K["opus"]["out"] > proxy.TIER_PRICES_PER_1K["sonnet"]["out"]
      > proxy.TIER_PRICES_PER_1K["haiku"]["out"])

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll cost-counter checks passed.")
