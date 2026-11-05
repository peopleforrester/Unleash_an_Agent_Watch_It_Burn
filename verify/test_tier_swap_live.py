# ABOUTME: Live check for #793 item 4: swap the workshop-agent from bedrock-nova to bedrock-haiku on a cluster and hold
# ABOUTME: guard-proxy to reading the swap on /cost within its 5-second cache and pricing new spend at Haiku rates.
# SUITE: e2e
"""Needs kubectl and CONTEXT, the kube-context of a cluster running guard-proxy at this repo's pin. Every missing
prerequisite is a failure, never a skip.

guard-proxy-agenticburn#37 has guard-proxy price each request at the tier of the workshop-agent Agent's bound
`bedrock-<tier>` ModelConfig, read at most every 5 seconds, with MODEL_TIER only the start-up default. This is the
live half of #793 and the O2b check of docs/research/2026-11-02-workload-management-exercises.md:

1. the guard-proxy pod template carries git's `checksum/proxy-py`, the sha256 of the pinned proxy.py, and sets no
   COST_PER_1K_IN or COST_PER_1K_OUT, so the cluster prices by the pinned tier table this check reads its rates from;
2. the Agent is bound to bedrock-nova and /cost's `tier` reads nova;
3. the Agent is patched to bedrock-haiku with nothing else changed (MODEL_TIER stays as it is), and a poller inside
   the guard-proxy pod, which reads the Agent and /cost on one clock, sees /cost's `tier` read haiku within 5 seconds
   of the patch, plus one second for its own poll cycle and the API reads;
4. guard-proxy logs one `price_tier` line naming bedrock-haiku;
5. once the agent pod has rolled out on Haiku, one /chat turn answers, its `cost_usd` is its tokens at the Haiku row,
   and /cost's growth across the turn is the tokens it gained at the Haiku row. That holds for any other turn the
   counter took in the same window, since every turn after the swap is priced at Haiku, so a visitor on a public bot
   does not make it fail;
6. the Agent is patched back to bedrock-nova, /cost's `tier` reads nova again and the agent pod rolls out.

The patches go as Argo CD's application controller (`--as`), which Kyverno's block-argocd-drift always admits, so
the check needs no policy flip on an armed cluster and leaves the policy as it found it. The Application ignores
`modelConfig`, so selfHeal does not fight the swap. Step 6 runs whenever step 3's patch was sent, whatever failed.

What it spends. One model call on Haiku, marked [[wib-probe]] so the room's feed skips it: under a cent of Bedrock,
which counts on /cost until the counter is reset. The agent pod restarts twice.

verify/test_tier_swap_live_judges.py runs the judges offline on recorded and failing readings.

Usage: CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] python3 verify/test_tier_swap_live.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from typing import Callable

REPO = pathlib.Path(__file__).resolve().parent.parent
PROXY_PY = REPO / "gitops" / "ai-layer" / "guard-proxy" / "proxy.py"
RESOURCES = REPO / "gitops" / "ai-layer" / "resources.yaml"
NS = "agent"
AGENT = "workshop-agent"
ARGO_CONTROLLER = "system:serviceaccount:argocd:argocd-application-controller"
FROM_CONFIG, FROM_TIER = "bedrock-nova", "nova"
TO_CONFIG, TO_TIER = "bedrock-haiku", "haiku"
# guard-proxy's _BINDING_TTL, and the allowance for the poller's 0.1 s cycle and its two reads per cycle.
CACHE_TTL_S = 5.0
POLL_SLACK_S = 1.0
POLL_LIMIT_S = 30.0
PROBE_MARKER = "[[wib-probe]]"
PROMPT = f"What burritos are on the menu today?\n\n{PROBE_MARKER}"
USD_TOLERANCE = 1e-9

# Runs inside the guard-proxy container. It reads the Agent with guard-proxy's own token, the way bound_tier() does,
# and /cost on loopback, both on the pod's monotonic clock, so the time from the patch to the new tier carries no
# exec or clock-skew overhead. The patch landed after the start of the last read that still showed the old
# ModelConfig, so the time from that start to the /cost answer that reads the new tier bounds the delay from above.
POLLER = r'''
import json, os, ssl, sys, time, urllib.request
mc_target, tier_target, limit = sys.argv[1], sys.argv[2], float(sys.argv[3])
host = os.environ.get("K8S_API_URL") or "https://kubernetes.default.svc"
tok_path = os.environ.get("K8S_TOKEN_PATH") or "/var/run/secrets/kubernetes.io/serviceaccount/token"
ca = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
ctx = ssl.create_default_context(cafile=ca) if os.path.exists(ca) else None
path = "/apis/kagent.dev/v1alpha2/namespaces/agent/agents/workshop-agent"
def model_config():
    tok = open(tok_path).read().strip()
    req = urllib.request.Request(host + path, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
        return json.load(r)["spec"]["declarative"].get("modelConfig")
def tier():
    with urllib.request.urlopen("http://127.0.0.1:8080/cost", timeout=5) as r:
        return json.load(r).get("tier")
def say(**kw):
    print(json.dumps(kw), flush=True)
say(event="ready", model_config=model_config(), tier=tier())
start = time.monotonic(); last_old = None; seen = None; mc = None; tr = None
while time.monotonic() - start < limit:
    t0 = time.monotonic()
    mc = model_config()
    if seen is None:
        if mc == mc_target:
            seen = time.monotonic()
            say(event="bound", model_config=mc)
        else:
            last_old = t0
    if seen is not None:
        tr = tier()
        t1 = time.monotonic()
        if tr == tier_target:
            say(event="priced", tier=tr, after_bound_s=round(t1 - seen, 3),
                after_last_old_s=round(t1 - (last_old if last_old is not None else seen), 3))
            sys.exit(0)
    time.sleep(0.1)
say(event="timeout", model_config=mc, tier=tr, limit_s=limit)
sys.exit(1)
'''

# One /chat turn on loopback with /cost read just before and just after it, in one exec.
CHAT = r'''
import json, sys, urllib.request
def cost():
    with urllib.request.urlopen("http://127.0.0.1:8080/cost", timeout=10) as r:
        return json.load(r)
before = cost()
req = urllib.request.Request("http://127.0.0.1:8080/chat", data=json.dumps({"prompt": sys.argv[1], "session": sys.argv[2]}).encode(),
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=170) as r:
    reply = json.load(r)
after = cost()
print(json.dumps({"before": before, "reply": reply, "after": after}))
'''

Check = tuple[bool, str]


# --- the judges (offline-tested) ----------------------------------------------------------------------------------


def tier_prices(source: str) -> dict:
    """TIER_PRICES_PER_1K as the given proxy.py defines it."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TIER_PRICES_PER_1K" for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit(f"TIER_PRICES_PER_1K is not assigned in {PROXY_PY}: the anchor this check prices by is gone")


def priced(tokens_in: int, tokens_out: int, row: dict) -> float:
    return tokens_in / 1000.0 * row["in"] + tokens_out / 1000.0 * row["out"]


def judge_build(annotation: str, committed: str, proxy_sha12: str, env_names: list[str]) -> list[Check]:
    out = [(annotation == committed == proxy_sha12,
            f"guard-proxy runs the pinned proxy.py: pod template checksum/proxy-py {annotation!r}, "
            f"resources.yaml {committed!r}, sha256 of the pinned proxy.py {proxy_sha12!r}")]
    overrides = sorted(n for n in env_names if n in ("COST_PER_1K_IN", "COST_PER_1K_OUT"))
    out.append((not overrides, "guard-proxy prices by the tier table (no COST_PER_1K_IN/OUT override)" if not overrides
                else f"guard-proxy sets {', '.join(overrides)}, which fixes the price whatever the Agent is bound to"))
    return out


def judge_start(ready: dict) -> list[Check]:
    return [(ready.get("model_config") == FROM_CONFIG,
             f"before the swap the Agent is bound to {ready.get('model_config')!r} (want {FROM_CONFIG})"),
            (ready.get("tier") == FROM_TIER, f"before the swap /cost's tier reads {ready.get('tier')!r} (want {FROM_TIER})")]


def judge_flip(events: list[dict], tier: str) -> Check:
    """The poller's events after a patch: /cost reads `tier` within the cache TTL plus the poll allowance."""
    got = next((e for e in events if e.get("event") == "priced"), None)
    if got is None:
        last = events[-1] if events else {}
        return False, (f"/cost's tier never read {tier} within {POLL_LIMIT_S:.0f}s of the patch "
                       f"(last reading: Agent {last.get('model_config')!r}, tier {last.get('tier')!r})")
    if got.get("tier") != tier:
        return False, f"the poller stopped on tier {got.get('tier')!r}, not {tier!r}"
    bound = float(got["after_last_old_s"])
    limit = CACHE_TTL_S + POLL_SLACK_S
    return bound <= limit, (f"/cost's tier read {tier} at most {bound:.2f}s after the patch "
                            f"({float(got['after_bound_s']):.2f}s after the poller saw it; limit {CACHE_TTL_S:.0f}s "
                            f"cache + {POLL_SLACK_S:.0f}s poll allowance)")


def judge_log(log: str, model_config: str) -> Check:
    lines = []
    for line in log.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("event") == "price_tier" and model_config in str(rec.get("message", "")):
            lines.append(rec)
    return (len(lines) >= 1, f"guard-proxy logged {len(lines)} price_tier line(s) naming {model_config}"
            + (f": {lines[0].get('message')!r}" if lines else ""))


def judge_spend(turn: dict, prices: dict, tier: str, other: str) -> list[Check]:
    """The /chat turn and /cost's growth across it are priced at `tier`'s row, not `other`'s."""
    row, other_row = prices[tier], prices[other]
    before, reply, after = turn.get("before") or {}, turn.get("reply") or {}, turn.get("after") or {}
    pin, pout = int(reply.get("input_tokens") or 0), int(reply.get("output_tokens") or 0)
    out: list[Check] = []
    answered = not reply.get("guarded") and pin > 0 and pout > 0
    out.append((answered, f"the /chat turn answered: guarded={reply.get('guarded')!r}, {pin} in / {pout} out tokens, "
                          f"reply {str(reply.get('reply', ''))[:80]!r}"))
    if not answered:
        return out
    want = priced(pin, pout, row)
    nope = priced(pin, pout, other_row)
    cost = reply.get("cost_usd")
    out.append((isinstance(cost, (int, float)) and math.isclose(cost, want, rel_tol=0, abs_tol=USD_TOLERANCE),
                f"the turn's cost_usd {cost!r} is its tokens at the {tier} row, ${want:.6f} "
                f"(the {other} row would be ${nope:.6f})"))
    out.append((after.get("tier") == tier, f"/cost's tier after the turn reads {after.get('tier')!r} (want {tier})"))
    d_req = int(after.get("requests", 0)) - int(before.get("requests", 0))
    d_in = int(after.get("input_tokens", 0)) - int(before.get("input_tokens", 0))
    d_out = int(after.get("output_tokens", 0)) - int(before.get("output_tokens", 0))
    d_usd = float(after.get("usd", 0.0)) - float(before.get("usd", 0.0))
    counted = d_req >= 1 and d_in >= pin and d_out >= pout
    out.append((counted, f"/cost counted the turn: +{d_req} request(s), +{d_in} in / +{d_out} out tokens"))
    grown = priced(d_in, d_out, row)
    out.append((counted and math.isclose(d_usd, grown, rel_tol=0, abs_tol=USD_TOLERANCE * max(d_req, 1)),
                f"/cost's usd grew ${d_usd:.6f}, its token growth at the {tier} row is ${grown:.6f} "
                f"(the {other} row would be ${priced(d_in, d_out, other_row):.6f})"))
    return out


# --- the cluster ------------------------------------------------------------------------------------------------


class Cluster:
    def __init__(self, context: str, runner: Callable = subprocess.run) -> None:
        self.context = context
        self.runner = runner
        # Set once a patch to the Agent has been sent, so the swap back runs whatever fails after it.
        self.patched = False

    def kubectl(self, *args: str, timeout: float = 90, stdin: str | None = None) -> tuple[int, str, str]:
        p = self.runner(["kubectl", "--context", self.context, *args], capture_output=True, text=True,
                        timeout=timeout, input=stdin)
        return p.returncode, p.stdout or "", p.stderr or ""

    def out(self, *args: str, timeout: float = 90, stdin: str | None = None) -> str:
        rc, out, err = self.kubectl(*args, timeout=timeout, stdin=stdin)
        if rc != 0:
            raise RuntimeError(f"kubectl {' '.join(args[:4])} ... exited {rc}: {err.strip()[:300]}")
        return out

    def exec_py(self, script: str, *argv: str, timeout: float = 90) -> str:
        return self.out("-n", NS, "exec", "-i", "deploy/guard-proxy", "-c", "proxy", "--", "python3", "-", *argv,
                        timeout=timeout, stdin=script)

    def patch_model(self, model_config: str) -> None:
        body = json.dumps({"spec": {"declarative": {"modelConfig": model_config}}})
        self.patched = True
        self.out("-n", NS, "patch", "agent", AGENT, "--type", "merge", "-p", body, "--as", ARGO_CONTROLLER)

    def config_hash(self) -> str:
        return self.out("-n", NS, "get", "deploy", AGENT, "-o",
                        "jsonpath={.spec.template.metadata.annotations.kagent\\.dev/config-hash}")

    def await_agent_rollout(self, old_hash: str) -> Check:
        """kagent rewrites the agent Deployment's config-hash for a new ModelConfig; wait for that, then the rollout."""
        deadline = time.monotonic() + 120
        new = old_hash
        while time.monotonic() < deadline:
            new = self.config_hash()
            if new != old_hash:
                break
            time.sleep(2)
        if new == old_hash:
            return False, f"kagent did not change {AGENT}'s config-hash within 120s of the patch"
        rc, out, err = self.kubectl("-n", NS, "rollout", "status", f"deploy/{AGENT}", "--timeout=240s", timeout=260)
        return rc == 0, f"{AGENT} rolled out on its new config-hash: {(out or err).strip().splitlines()[-1:]}"

    def swap_and_watch(self, model_config: str, tier: str, start_from: str | None) -> tuple[list[dict], str]:
        """Start the in-pod poller and, once it is reading, patch the Agent to model_config. With start_from set,
        patch only when the poller's first reading shows the Agent bound to it. Returns the events and stderr."""
        cmd = ["kubectl", "--context", self.context, "-n", NS, "exec", "-i", "deploy/guard-proxy", "-c", "proxy",
               "--", "python3", "-", model_config, tier, str(POLL_LIMIT_S)]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert p.stdin is not None and p.stdout is not None
        p.stdin.write(POLLER)
        p.stdin.close()
        events = []
        try:
            first = p.stdout.readline()
            if first:
                events.append(json.loads(first))
                if start_from is not None and events[0].get("model_config") != start_from:
                    p.kill()
                    p.wait(timeout=30)
                    return events, ""
                self.patch_model(model_config)
            for line in p.stdout:
                if line.strip():
                    events.append(json.loads(line))
            p.wait(timeout=POLL_LIMIT_S + 30)
        finally:
            if p.poll() is None:
                p.kill()
        return events, (p.stderr.read() if p.stderr else "")


def run_checks(cluster: Cluster) -> list[Check]:
    checks: list[Check] = []
    if not PROXY_PY.is_file():
        return [(False, f"{PROXY_PY} is missing: run git submodule update --init gitops/ai-layer/guard-proxy")]
    source = PROXY_PY.read_text()
    prices = tier_prices(source)
    sha12 = hashlib.sha256(source.encode()).hexdigest()[:12]
    m = re.search(r'checksum/proxy-py:\s*"([0-9a-f]+)"', RESOURCES.read_text())
    if m is None:
        return [(False, f"no checksum/proxy-py annotation in {RESOURCES}: the anchor this check reads is gone")]
    dep = json.loads(cluster.out("-n", NS, "get", "deploy", "guard-proxy", "-o", "json"))
    annotation = (dep["spec"]["template"]["metadata"].get("annotations") or {}).get("checksum/proxy-py", "")
    env_names = [e.get("name") for c in dep["spec"]["template"]["spec"]["containers"] if c.get("name") == "proxy"
                 for e in c.get("env") or []]
    checks += judge_build(annotation, m.group(1), sha12, env_names)
    tier_env = next((e.get("value") for c in dep["spec"]["template"]["spec"]["containers"] if c.get("name") == "proxy"
                     for e in c.get("env") or [] if e.get("name") == "MODEL_TIER"), None)
    if not all(ok for ok, _ in checks):
        return checks

    old_hash = cluster.config_hash()
    try:
        swap_started = time.time()
        events, err = cluster.swap_and_watch(TO_CONFIG, TO_TIER, start_from=FROM_CONFIG)
        if not events:
            return checks + [(False, f"the in-pod poller printed nothing: {err.strip()[:300]}")]
        checks += judge_start(events[0])
        if not cluster.patched:
            return checks
        checks.append(judge_flip(events[1:], TO_TIER))
        since = max(60, int(time.time() - swap_started) + 30)
        checks.append(judge_log(cluster.out("-n", NS, "logs", "deploy/guard-proxy", "-c", "proxy",
                                            f"--since={since}s"), TO_CONFIG))
        after_env = json.loads(cluster.out("-n", NS, "get", "deploy", "guard-proxy", "-o", "json"))
        tier_after = next((e.get("value") for c in after_env["spec"]["template"]["spec"]["containers"]
                           if c.get("name") == "proxy" for e in c.get("env") or [] if e.get("name") == "MODEL_TIER"),
                          None)
        checks.append((tier_after == tier_env, f"guard-proxy's MODEL_TIER was left at {tier_after!r} (was {tier_env!r})"))
        rolled = cluster.await_agent_rollout(old_hash)
        checks.append(rolled)
        if rolled[0]:
            turn = json.loads(cluster.exec_py(CHAT, PROMPT, f"tier-swap-check-{os.getpid()}", timeout=200))
            reply = dict(turn.get("reply") or {}, reply=str((turn.get("reply") or {}).get("reply", ""))[:80])
            print("turn " + json.dumps(dict(turn, reply=reply)))
            checks += judge_spend(turn, prices, TO_TIER, FROM_TIER)
    finally:
        if cluster.patched:
            back_hash = cluster.config_hash()
            events, err = cluster.swap_and_watch(FROM_CONFIG, FROM_TIER, start_from=None)
            if not events:
                # The poller never started, so it sent no patch: put the Agent back without it.
                cluster.patch_model(FROM_CONFIG)
            ok, msg = judge_flip(events[1:], FROM_TIER) if events else (False, f"poller printed nothing: {err[:300]}")
            checks.append((ok, f"swapped back to {FROM_CONFIG}: {msg}"))
            ok, msg = cluster.await_agent_rollout(back_hash)
            checks.append((ok, f"after the swap back, {msg}"))
    return checks


def main() -> int:
    context = os.environ.get("CONTEXT", "")
    missing = []
    if not context:
        missing.append("CONTEXT is not set: name the kube-context of the cluster to swap the agent's model on")
    if shutil.which("kubectl") is None:
        missing.append("kubectl is not on PATH")
    if missing:
        for m in missing:
            print(f"FAIL {m}")
        return 1
    checks = run_checks(Cluster(context))
    for ok, msg in checks:
        print(f"{'PASS' if ok else 'FAIL'} {msg}")
    failed = sum(1 for ok, _ in checks if not ok)
    print(f"{len(checks) - failed}/{len(checks)} tier-swap checks passed on {context}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
