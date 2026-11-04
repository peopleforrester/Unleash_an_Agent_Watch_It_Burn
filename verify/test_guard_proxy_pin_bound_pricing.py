# ABOUTME: Fails when the pinned guard-proxy stops pricing at the Agent's bound ModelConfig (guard-proxy-agenticburn#37),
# ABOUTME: or when verify/model_pin_check.py, on that pin, stops accepting a live tier swap with MODEL_TIER left alone (#841).
#
# #793 asked for two things: repin gitops/ai-layer/guard-proxy to a build that carries #37, and have
# model_pin_check.py accept a live `kubectl patch agent workshop-agent` to bedrock-<tier> on that build. The tests
# #793 changed (test_model_pin_check.py, test_cost_counter.py, test_recreation_spec_tier_swap.py) hold for either
# build on purpose, so a pin before #37 passed them all. This one holds only for a pin that carries #37.
#
# Everything here reads proxy.py as the committed gitlink records it (`git show <gitlink>:proxy.py` in the
# submodule), not the checked-out file, so a local edit in the submodule neither passes nor fails it. It needs the
# submodule's history, which verify/ensure-submodules.sh clones in full; a missing object fails, it does not skip.
import contextlib
import importlib.util
import io
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SUB = "gitops/ai-layer/guard-proxy"
# guard-proxy-agenticburn#37: "Price each request at the model the workshop-agent is bound to".
PR37 = "c8ac56e1271ee16e71872f1cba8e53680a7f94f5"

failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -> ' + detail) if (detail and not cond) else ''}")
    if not cond:
        failures.append(name)


def git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def die(msg):
    print(f"FAILED: {msg}")
    sys.exit(1)


print("== the gitlink carries guard-proxy-agenticburn#37 ==")
# The index, not HEAD: it is what the next commit records, so a staged move back before #37 fails here too.
staged = git("ls-files", "-s", "--", SUB).stdout.split()
if len(staged) < 2 or staged[0] != "160000":
    die(f"{SUB} is not a gitlink in the index: {staged!r}")
GITLINK = staged[1]
print(f"  ({SUB} is pinned at {GITLINK[:12]})")
sub_dir = REPO / SUB
for sha, what in ((GITLINK, "the pinned commit"), (PR37, "#37's commit")):
    if git("cat-file", "-e", f"{sha}^{{commit}}", cwd=sub_dir).returncode != 0:
        die(f"{what} {sha} is not in {SUB}'s clone; run `git -C {SUB} fetch origin` (verify/ensure-submodules.sh "
            f"clones it in full)")
anc = git("merge-base", "--is-ancestor", PR37, GITLINK, cwd=sub_dir)
check(f"the pinned guard-proxy {GITLINK[:12]} descends from #37 ({PR37[:7]})", anc.returncode == 0,
      f"exit {anc.returncode}: the pin is before #37, so a live tier swap is priced at MODEL_TIER")

shown = git("show", f"{GITLINK}:proxy.py", cwd=sub_dir)
if shown.returncode != 0:
    die(f"cannot read proxy.py at {GITLINK}: {shown.stderr.strip()}")
PINNED_SOURCE = shown.stdout

tmp = tempfile.TemporaryDirectory()
PINNED_PROXY = pathlib.Path(tmp.name) / "proxy.py"
PINNED_PROXY.write_text(PINNED_SOURCE)

spec = importlib.util.spec_from_file_location("model_pin_check", REPO / "verify" / "model_pin_check.py")
mpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mpc)
mpc.PROXY = PINNED_PROXY  # main() and load_tier_map() read the pinned build, whatever is checked out

check("model_pin_check reads the pinned proxy.py as pricing at the bound model",
      mpc.prices_bound_model(PINNED_SOURCE))

print("== the pinned proxy.py prices a live swap at the bound tier ==")
# The proxy reads its env once at import. Give it the committed guard-proxy Deployment's MODEL_TIER (nova), as the
# cluster does, and no price override, so a swap to another tier has a different price to be told apart by.
os.environ["MODEL_TIER"] = mpc.pinned(mpc.committed_manifests())["model_tier"]
for var in ("COST_PER_1K_IN", "COST_PER_1K_OUT", "MODEL_NAME"):
    os.environ.pop(var, None)
pspec = importlib.util.spec_from_file_location("guard_proxy_pinned", PINNED_PROXY)
proxy = importlib.util.module_from_spec(pspec)
pspec.loader.exec_module(proxy)  # safe: the server only starts under __main__
HAS_37 = callable(getattr(proxy, "_tier_of", None)) and callable(getattr(proxy, "bound_tier", None))
check("it defines _tier_of and bound_tier", HAS_37)
if not HAS_37:
    die(f"{len(failures)} check(s): proxy.py at {GITLINK[:12]} has no bound pricing to swap; repin {SUB} to a "
        f"build that carries guard-proxy-agenticburn#37 ({PR37[:7]})")

MT = proxy.MODEL_TIER
bound = {"modelConfig": "bedrock-nova"}
proxy._k8s_get = lambda path: ({"spec": {"declarative": dict(bound)}}
                               if path.endswith("/agents/workshop-agent") else None)
SAMPLE_IN, SAMPLE_OUT = 1000, 200
SAMPLE = {"result": {"metadata": {"kagent_usage_metadata": {
    "promptTokenCount": SAMPLE_IN, "candidatesTokenCount": SAMPLE_OUT, "totalTokenCount": SAMPLE_IN + SAMPLE_OUT}}}}


def usd_at(tier):
    r = proxy.TIER_PRICES_PER_1K[tier]
    return SAMPLE_IN / 1000.0 * r["in"] + SAMPLE_OUT / 1000.0 * r["out"]


def priced_after_swap(model_config):
    bound["modelConfig"] = model_config
    proxy._binding["at"] = None  # past the 5 s cache, as the room's next turn after a swap is
    was = proxy._cost["usd"]
    proxy.record_usage(SAMPLE)
    return proxy._cost["usd"] - was


for tier in ("haiku", "sonnet", "opus"):
    usd = priced_after_swap(f"bedrock-{tier}")
    check(f"after a swap to bedrock-{tier}, with MODEL_TIER still {MT}, a request is priced at {tier} rates",
          proxy.bound_tier() == tier and abs(usd - usd_at(tier)) < 1e-12 and proxy.MODEL_TIER == MT,
          f"bound_tier {proxy.bound_tier()!r}, priced {usd} vs {usd_at(tier)}")
check(f"the swap's price differs from the MODEL_TIER ({MT}) row, so the test can tell the two builds apart",
      abs(usd_at("haiku") - usd_at(MT)) > 1e-9)

print("== model_pin_check accepts a live swap on the pinned build ==")
COMMITTED = mpc.committed_manifests()
ANCHOR = "modelConfig: bedrock-nova"
if ANCHOR not in COMMITTED:
    die(f"the anchor {ANCHOR!r} is not in {mpc.AGENT_MANIFEST.relative_to(REPO)}; the swap cannot be built")
TIERS = mpc.load_tier_map()


def swapped_manifests(model_config):
    """The manifests as a live `kubectl patch agent workshop-agent` to model_config leaves the cluster: the Agent's
    modelConfig moves, guard-proxy's MODEL_TIER does not."""
    return COMMITTED.replace(ANCHOR, f"modelConfig: {model_config}", 1)


def run_offline_half(manifests):
    """model_pin_check.main() on these manifests with no aws on PATH: it judges the pin and its pricing, prints
    that, then stops with exit 2 before the first Bedrock call. The stdout is the offline verdict."""
    out, err = io.StringIO(), io.StringIO()
    saved_cm, saved_path = mpc.committed_manifests, os.environ.get("PATH", "")
    with tempfile.TemporaryDirectory() as empty:
        mpc.committed_manifests = lambda: manifests
        os.environ["PATH"] = empty
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = mpc.main(["--profile", "delivery", "--region", "us-west-2"])
        finally:
            mpc.committed_manifests, os.environ["PATH"] = saved_cm, saved_path
    return rc, out.getvalue(), err.getvalue()


for tier in ("haiku", "sonnet", "opus"):
    manifests = swapped_manifests(f"bedrock-{tier}")
    pin = mpc.pinned(manifests)
    check(f"the swap to bedrock-{tier} leaves MODEL_TIER at nova",
          pin["model_config"] == f"bedrock-{tier}" and pin["model_tier"] == "nova", str(pin))
    rc, out, err = run_offline_half(manifests)
    lines = out.splitlines()
    check(f"model_pin_check says the pinned proxy.py prices at the bound ModelConfig (swap to {tier})",
          any("pricing: the pinned proxy.py prices at the bound bedrock-<tier> ModelConfig" in ln for ln in lines),
          out)
    check(f"it prices the swap at {tier}, bound to bedrock-{tier}",
          any(f"at tier '{tier}' (bound to bedrock-{tier})" in ln and ln.strip().startswith("PASS") for ln in lines),
          out)
    check(f"and fails and warns on nothing in the offline half (swap to {tier})",
          not any(ln.strip().startswith(("FAIL", "WARN")) for ln in lines), out)
    check(f"it stops at the missing aws CLI, past the offline half (swap to {tier})",
          rc == 2 and "aws CLI is not on PATH" in err, f"exit {rc}: {err}")
    check(f"priced_tier on the pinned build is {tier}",
          mpc.priced_tier(pin, TIERS, mpc.prices_bound_model(PINNED_SOURCE)) == tier)

# The same swap judged as a build before #37 prices it fails: this is what the pin moving past #37 bought.
check("judged as a build before #37, the same swap to bedrock-haiku is mispriced and fails",
      not all(ok for _, ok, _ in mpc.judge_pin(mpc.pinned(swapped_manifests("bedrock-haiku")), "us-west-2", TIERS,
                                               False)))

tmp.cleanup()
if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll guard-proxy bound-pricing pin checks passed.")
