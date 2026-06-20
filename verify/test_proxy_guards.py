# ABOUTME: Render-gate check for the two-stage progressive input guard + demo rate-limit/cost-cap.
# ABOUTME: Imports the canonical guard-proxy and asserts the guard/limit logic without a cluster.
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard_proxy_g", REPO / "gitops" / "ai-layer" / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Two-stage progressive input guard: independent block-list and classifier toggles.
check("GUARDS has two independent input stages + output",
      set(proxy.GUARDS) == {"input_blocklist", "input_classifier", "output"})

# Rate limit: a sliding 60s window capped at RATE_LIMIT_RPM.
proxy.RATE_LIMIT_RPM = 2
proxy._req_times.clear()
check("rate limit allows up to the cap", (not proxy.rate_limited()) and (not proxy.rate_limited()))
check("rate limit blocks the request over the cap", proxy.rate_limited())
proxy.RATE_LIMIT_RPM = 0
check("rate limit disabled when 0", not proxy.rate_limited())

# Cost cap: freeze spend once the cluster's metered tally hits the cap.
proxy.COST_CAP_USD = 0
check("cost cap disabled when 0", not proxy.cost_capped())
proxy.record_usage({"result": {"metadata": {"adk_usage_metadata": {
    "promptTokenCount": 100000, "candidatesTokenCount": 100000, "totalTokenCount": 200000}}}})
proxy.COST_CAP_USD = 0.0001
check("cost cap trips once spend exceeds the cap", proxy.cost_capped())
proxy.COST_CAP_USD = 1e9
check("cost cap not tripped under a high cap", not proxy.cost_capped())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll proxy-guard checks passed.")
