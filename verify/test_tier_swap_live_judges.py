# ABOUTME: Offline checks for verify/test_tier_swap_live.py (#793): its judges pass the readings run 17416 recorded on
# ABOUTME: watch-it-burn-community and fail each way the live tier swap can stop being priced at the bound model.
#
# test_tier_swap_live.py patches the workshop-agent from bedrock-nova to bedrock-haiku on a cluster and holds
# guard-proxy to reading the swap on /cost within its 5-second cache and pricing new spend at Haiku rates. It can
# only run with a cluster. This runs its judges on the readings it took live in run 17416, and on each reading that
# should fail: a slow flip, a turn or counter priced at Nova rates, a guarded turn, a stale build, a price override.
# It also holds the in-pod scripts to compiling and the poller to reading the Agent path the pinned proxy.py reads.
import ast
import contextlib
import importlib.util
import io
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
LIVE = REPO / "verify" / "test_tier_swap_live.py"
PROXY_PY = REPO / "gitops" / "ai-layer" / "guard-proxy" / "proxy.py"

failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


if not PROXY_PY.is_file():
    print(f"FAILED: {PROXY_PY} is missing; run bash verify/ensure-submodules.sh")
    sys.exit(1)

spec = importlib.util.spec_from_file_location("tier_swap_live", LIVE)
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
PROXY_SOURCE = PROXY_PY.read_text()
PRICES = live.tier_prices(PROXY_SOURCE)


def ok_all(checks):
    return all(ok for ok, _ in checks)


# --- the readings run 17416 took on watch-it-burn-community (2026-11-05) --------------------------------------------
# The poller's events, the log line and the turn's reply are as the live check printed them. /cost before and after is
# as read just before and just after the whole check: 773 to 774 requests, so the counter took this turn alone, and its
# token and usd growth are exactly the reply's. The `tier` fields are what the in-exec reads report after the swap.

READY = {"event": "ready", "model_config": "bedrock-nova", "tier": "nova"}
FLIP = [{"event": "bound", "model_config": "bedrock-haiku"},
        {"event": "priced", "tier": "haiku", "after_bound_s": 3.63, "after_last_old_s": 3.77}]
LOG = "\n".join([
    "not json at all",
    '{"level": "INFO", "logger": "guard-proxy", '
    '"message": "pricing at haiku: workshop-agent is bound to bedrock-haiku", "event": "price_tier"}',
])
TURN = {
    "before": {"requests": 773, "input_tokens": 4631033, "output_tokens": 148801, "usd": 4.1809895999999975,
               "tier": "haiku"},
    "reply": {"reply": "Welcome to Hex & Cauldron, friend!", "guarded": False, "input_tokens": 5889,
              "output_tokens": 400, "cost_usd": 0.007889},
    "after": {"requests": 774, "input_tokens": 4636922, "output_tokens": 149201, "usd": 4.1888785999999975,
              "tier": "haiku"},
}


def with_turn(**parts):
    turn = {k: dict(v) for k, v in TURN.items()}
    for key, fields in parts.items():
        turn[key].update(fields)
    return turn


print("the prices it judges by")
check("the pinned proxy.py has a nova and a haiku row, and they differ",
      {"nova", "haiku"} <= set(PRICES) and PRICES["nova"] != PRICES["haiku"], str(PRICES))
try:
    with contextlib.redirect_stdout(io.StringIO()):
        live.tier_prices("X = 1\n")
    check("a proxy.py without TIER_PRICES_PER_1K stops the check, naming the anchor", False, "no SystemExit")
except SystemExit as e:
    check("a proxy.py without TIER_PRICES_PER_1K stops the check, naming the anchor",
          "TIER_PRICES_PER_1K" in str(e), str(e))

print("the in-pod scripts")
for name in ("POLLER", "CHAT"):
    try:
        compile(getattr(live, name), name, "exec")
        check(f"{name} compiles", True)
    except SyntaxError as e:
        check(f"{name} compiles", False, str(e))
agent_path = next((ast.literal_eval(n.value) for n in ast.parse(PROXY_SOURCE).body if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", None) == "_AGENT_PATH" for t in n.targets)), None)
check("the poller reads the Agent path the pinned proxy.py prices from",
      agent_path is not None and f'"{agent_path}"' in live.POLLER, f"_AGENT_PATH {agent_path!r}")
check("the live check is in the e2e suite, not the offline one",
      any(line == "# SUITE: e2e" for line in LIVE.read_text().splitlines()))

print("judge_build")
check("the recorded build passes", ok_all(live.judge_build("dfca2b1fe758", "dfca2b1fe758", "dfca2b1fe758", ["MODEL_TIER"])))
check("a pod template on another proxy.py fails",
      not ok_all(live.judge_build("ba8d8e2b789f", "dfca2b1fe758", "dfca2b1fe758", ["MODEL_TIER"])))
check("a committed checksum that is not the pinned proxy.py's fails",
      not ok_all(live.judge_build("dfca2b1fe758", "dfca2b1fe758", "19fbbe48283e", ["MODEL_TIER"])))
for var in ("COST_PER_1K_IN", "COST_PER_1K_OUT"):
    check(f"{var} set on the proxy fails",
          not ok_all(live.judge_build("dfca2b1fe758", "dfca2b1fe758", "dfca2b1fe758", ["MODEL_TIER", var])))

print("judge_start")
check("the recorded start passes", ok_all(live.judge_start(READY)))
check("an Agent already on bedrock-haiku fails", not ok_all(live.judge_start(dict(READY, model_config="bedrock-haiku"))))
check("/cost reading sonnet before the swap fails", not ok_all(live.judge_start(dict(READY, tier="sonnet"))))

print("judge_flip")
ok, msg = live.judge_flip(FLIP, "haiku")
check("the recorded flip, 3.77s after the patch, passes", ok, msg)
check("a flip 6.5s after the patch fails",
      not live.judge_flip([FLIP[0], dict(FLIP[1], after_bound_s=6.4, after_last_old_s=6.5)], "haiku")[0])
check("a flip at exactly the 5s cache plus 1s allowance passes",
      live.judge_flip([FLIP[0], dict(FLIP[1], after_last_old_s=6.0)], "haiku")[0])
check("a poller that timed out with /cost still on nova fails",
      not live.judge_flip([FLIP[0], {"event": "timeout", "model_config": "bedrock-haiku", "tier": "nova"}], "haiku")[0])
check("no events fails", not live.judge_flip([], "haiku")[0])
check("a priced event on the wrong tier fails", not live.judge_flip([FLIP[0], dict(FLIP[1], tier="nova")], "haiku")[0])

print("judge_log")
check("the recorded price_tier line passes", live.judge_log(LOG, "bedrock-haiku")[0])
check("a price_tier line naming another ModelConfig does not count", not live.judge_log(LOG, "bedrock-opus")[0])
unknown = ('{"message": "workshop-agent is bound to \'bedrock-haiku-x\', which names no price tier; pricing at '
           'MODEL_TIER nova", "event": "price_tier_unknown"}')
check("a price_tier_unknown line does not count", not live.judge_log(unknown, "bedrock-haiku")[0])
check("no price_tier line fails", not live.judge_log("plain text\n{}\n[1, 2]", "bedrock-haiku")[0])

print("judge_spend")
spend = live.judge_spend(TURN, PRICES, "haiku", "nova")
check("the recorded turn passes", ok_all(spend), "; ".join(m for ok, m in spend if not ok))
nova_cost = live.priced(5889, 400, PRICES["nova"])
check("a turn whose cost_usd is at the Nova row fails",
      not ok_all(live.judge_spend(with_turn(reply={"cost_usd": nova_cost}), PRICES, "haiku", "nova")))
check("a counter that grew at the Nova row fails",
      not ok_all(live.judge_spend(with_turn(after={"usd": TURN["before"]["usd"] + nova_cost}), PRICES, "haiku", "nova")))
visitor_in, visitor_out = 1200, 90
busy = with_turn(after={"requests": 775, "input_tokens": TURN["after"]["input_tokens"] + visitor_in,
                        "output_tokens": TURN["after"]["output_tokens"] + visitor_out,
                        "usd": TURN["after"]["usd"] + live.priced(visitor_in, visitor_out, PRICES["haiku"])})
check("a visitor's turn in the same window, also at Haiku, passes", ok_all(live.judge_spend(busy, PRICES, "haiku", "nova")))
check("a guarded turn with no tokens fails",
      not ok_all(live.judge_spend(with_turn(reply={"guarded": True, "input_tokens": 0, "output_tokens": 0,
                                                   "cost_usd": 0.0}), PRICES, "haiku", "nova")))
check("/cost reading nova after the turn fails",
      not ok_all(live.judge_spend(with_turn(after={"tier": "nova"}), PRICES, "haiku", "nova")))
check("a counter that did not count the turn fails",
      not ok_all(live.judge_spend(with_turn(after=dict(TURN["before"])), PRICES, "haiku", "nova")))
check("a counter reset in the window fails",
      not ok_all(live.judge_spend(with_turn(after={"requests": 1, "input_tokens": 5889, "output_tokens": 400,
                                                   "usd": 0.007889}), PRICES, "haiku", "nova")))

print("main without a cluster")
env = dict(os.environ)
os.environ.pop("CONTEXT", None)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = live.main()
os.environ.clear()
os.environ.update(env)
check("no CONTEXT fails loudly, it does not skip", rc == 1 and "FAIL CONTEXT is not set" in out.getvalue(),
      out.getvalue())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll tier-swap live judge checks passed.")
