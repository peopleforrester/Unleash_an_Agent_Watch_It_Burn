# ABOUTME: Load test for one public cluster (#644): replays recorded prompts at /chat as N concurrent phones
# ABOUTME: (default 500), each its own session, and reports latency, refusals by limit, errors by status and spend.
"""Replay the last delivery's prompts at one cluster's /chat, the way a ballroom of phones sends them.

    # the plan and the cost estimate only; nothing is sent
    python3 verify/load_replay.py attackme.burritobot.co \\
        --harvest ~/repos/talks/Unleash_an_Agent_Watch_It_Burn/.harvest/devopsdays-portland/prompts

    # the run: add --yes
    python3 verify/load_replay.py attackme.burritobot.co --yes \\
        --harvest ~/repos/talks/Unleash_an_Agent_Watch_It_Burn/.harvest/devopsdays-portland/prompts \\
        --json-out tmp/load-replay-attackme.json

The prompts. `--source harvest` (the default) reads the DevOpsDays Portland 2026 harvest, the per-cluster
`prompts/*.json` files scripts/harvest wrote from Datadog LLM Observability. It is gitignored because it holds
attendee-typed text, so the path is passed with --harvest and a missing directory is an error, not a quiet
switch to other prompts. `--source catalog` replays the stage's own asks instead (the burrito order, the CEO
record, the friendly opener, HC-666, the poisoned weather tool, the off-topic and on-topic asks), from
verify/kubecon_probe.py and verify/topic_cases.py, which hold them equal to what the stage sends.

The pacing. Each user is one phone: its own session, sent in the body and as X-BurritoBot-Session as the
storefront sends it. Users start spread over --ramp seconds and send --turns turns in order, waiting for
each reply and then a think time drawn from --think-min to --think-max seconds. A user replays one recorded
conversation from a random point, so the turns follow each other the way an attendee's did.

The money. Every prompt carries guard-proxy's probe marker, so it is answered but kept off the prompt wall.
Each /chat send counts as one model call, as kubecon_probe.py counts them, and --max-calls is a hard ceiling
on sends: a turn past it is never sent. The estimate is printed before anything is sent, and without --yes
the tool stops there. During the run /cost is read every --progress seconds, and new turns stop once the
cluster's spend has risen by --max-usd or --deadline seconds have passed. The spend lands on the cluster's
own COST_CAP_USD tally, so on attackme this runs before `./fleet.sh reset-bot watch-it-burn-community`.

Results hold no prompt or reply text: outcome, HTTP status, latency, tokens.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import pathlib
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_HARVEST = REPO / ".harvest/devopsdays-portland/prompts"
CONSOLE_CONF = REPO / "gitops/ai-layer/console.conf"
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"

# guard-proxy's PROBE_MARKER: a prompt carrying it is answered normally and never recorded in the feed.
PROBE_MARKER = "[[wib-probe]]"
# The measured price of one expensive lab send on Nova Pro, from proxy.py's BUDGET_CAP_USD comment
# (attendee-001, 2026-09-08: about $0.005 a send). Most recorded prompts are cheaper; it is the estimate's unit.
USD_PER_CALL = 0.005
# Longer than nginx's 285s proxy_read_timeout and Railway's 300s, so a slow turn ends at the server, not here.
TIMEOUT_S = 320.0
# A recorded prompt longer than this is left out; the harvest holds a handful of pasted walls of text.
MAX_PROMPT_CHARS = 8000

# Outcomes, by what the phone would see. The refusal texts are guard-proxy's and the console nginx's own
# (proxy.py _chat_turn and console.conf @chat_slow_down); verify/test_load_replay.py holds them to the source.
EDGE_LIMIT_TEXT = "a minute per conversation. Wait"     # console.conf @chat_slow_down
SESSION_LIMIT_TEXT = "/min per conversation.)"           # proxy.py, RATE_LIMIT_SESSION_RPM
CLUSTER_LIMIT_TEXT = "/min cap on this cluster.)"        # proxy.py, RATE_LIMIT_RPM
BUDGET_TEXT = "The kitchen tab is frozen."               # proxy.py, COST_CAP_USD or the C4 budget guard
OUTCOMES = ("served", "edge_limit", "session_limit", "cluster_limit", "budget", "guarded", "empty",
            "http_502", "http_504", "http_429", "http_other", "timeout", "transport")
LIMIT_OUTCOMES = ("edge_limit", "session_limit", "cluster_limit")
ERROR_OUTCOMES = ("empty", "http_502", "http_504", "http_429", "http_other", "timeout", "transport")


# --- prompts ------------------------------------------------------------------------------------------------
_JSON_USER = re.compile(r'\{"role":"user","parts":\[\{"content":("(?:[^"\\]|\\.)*")')
_TEXT_USER = re.compile(r"(?:^|\n)user: (.*?)(?=\n(?:assistant|user|tool|system): |\Z)", re.S)


def user_turns(field_text: str) -> list[str]:
    """The user turns in one harvested span's input. Datadog stored it two ways: a JSON message array (often
    cut short, so it is read by pattern rather than parsed whole) or a "user: ...\\nassistant: ..." transcript."""
    if field_text.lstrip().startswith("["):
        found = []
        for m in _JSON_USER.finditer(field_text):
            try:
                found.append(json.loads(m.group(1)))
            except json.JSONDecodeError:
                continue
        return found
    return [m.group(1) for m in _TEXT_USER.finditer(field_text)]


def load_harvest(directory: pathlib.Path) -> tuple[list[list[str]], dict]:
    """One conversation per harvested cluster file: its distinct user prompts in the order first seen."""
    files = sorted(glob.glob(str(directory / "*.json")))
    if not files:
        raise SystemExit(f"no recorded prompts: {directory} has no *.json files. The harvest is gitignored; pass "
                         "its prompts/ directory with --harvest, or replay the stage's asks with --source catalog.")
    sequences, too_long, probes = [], 0, 0
    for path in files:
        seen: dict[str, str] = {}
        for rec in json.loads(pathlib.Path(path).read_text()):
            for text in rec.get("user") or []:
                for turn in user_turns(text if isinstance(text, str) else ""):
                    turn = turn.strip()
                    if not turn or turn in seen:
                        continue
                    if PROBE_MARKER in turn:
                        probes += 1
                    elif len(turn) > MAX_PROMPT_CHARS:
                        too_long += 1
                    else:
                        seen[turn] = rec.get("ts") or ""
                        continue
                    seen.setdefault(turn, "")  # counted once, never replayed
        ordered = [t for t, ts in sorted(((t, ts) for t, ts in seen.items() if ts), key=lambda x: x[1])]
        if ordered:
            sequences.append(ordered)
    stats = {"files": len(files), "conversations": len(sequences),
             "prompts": sum(len(s) for s in sequences), "too_long": too_long, "probes_left_out": probes}
    if not sequences:
        raise SystemExit(f"no replayable prompts in {directory} ({len(files)} files)")
    return sequences, stats


def load_catalog() -> tuple[list[list[str]], dict]:
    """The stage's asks, each its own one-turn conversation: the same prompts kubecon_probe.py sends."""
    sys.path.insert(0, str(HERE))
    import kubecon_probe as kp  # noqa: E402  (imported here: only this source needs it)
    import topic_cases as tc  # noqa: E402
    prompts = [kp.ORDER_PROMPT, kp.CEO_PROMPT, kp.FRIENDLY_CEO_PROMPT, kp.ROOM_PROMPT, kp.MCP_PROMPT,
               *tc.OFF_TOPIC, *tc.CANONICAL_ON]
    prompts = list(dict.fromkeys(p for p in prompts if p))
    return [[p] for p in prompts], {"conversations": len(prompts), "prompts": len(prompts)}


# --- the deployed limits, read from git -------------------------------------------------------------------
def deployed_limits() -> dict:
    """The limits in front of the model as git ships them: the console nginx's /chat zones and guard-proxy's env."""
    conf = CONSOLE_CONF.read_text()
    zone = {m.group(1): int(m.group(2)) for m in
            re.finditer(r"limit_req_zone \S+ zone=(\w+):\S+ rate=(\d+)r/m;", conf)}
    burst = {m.group(1): int(m.group(2)) for m in
             re.finditer(r"limit_req zone=(\w+) burst=(\d+) nodelay;", conf)}
    env = {}
    for doc in yaml.safe_load_all(RESOURCES.read_text()):
        if doc and doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "guard-proxy":
            proxy = next(c for c in doc["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
            env = {e["name"]: e.get("value") or "" for e in proxy["env"]}
    return {
        "edge_session_rpm": zone["wib_chat_session"], "edge_session_burst": burst["wib_chat_session"],
        "proxy_session_rpm": int(env["RATE_LIMIT_SESSION_RPM"]), "proxy_cluster_rpm": int(env["RATE_LIMIT_RPM"]),
        "cost_cap_usd": float(env["COST_CAP_USD"]), "model_tier": env.get("MODEL_TIER", ""),
    }


# --- the plan and the estimate ------------------------------------------------------------------------------
@dataclass
class Plan:
    users: int
    turns: int
    max_calls: int
    ramp: float
    think_min: float
    think_max: float
    usd_per_call: float

    @property
    def planned(self) -> int:
        return self.users * self.turns

    @property
    def sends(self) -> int:
        return min(self.planned, self.max_calls)

    def minutes(self, latency_s: float = 10.0) -> float:
        """A rough run length: the ramp, then each turn's reply and think time."""
        think = (self.think_min + self.think_max) / 2
        return (self.ramp + self.turns * latency_s + (self.turns - 1) * think) / 60.0

    def predicted_served(self, limits: dict) -> int:
        """Turns the limits let through. nginx's per-conversation zone allows each phone its burst then its rate,
        and guard-proxy's cluster window its rate. Nothing keys on the address (#450), so one machine sending as
        every phone is held the way a venue NAT is."""
        m = self.minutes()
        edge = self.users * (limits["edge_session_burst"] + 1 + limits["edge_session_rpm"] * m)
        cluster = limits["proxy_cluster_rpm"] * max(m, 1.0)
        return int(min(self.sends, edge, cluster))


def plan_lines(plan: Plan, limits: dict, source: str, stats: dict, target: str) -> list[str]:
    served = plan.predicted_served(limits)
    return [
        f"target {target}, {plan.users} users x {plan.turns} turns = {plan.planned} turns, "
        f"ramp {plan.ramp:g}s, think {plan.think_min:g} to {plan.think_max:g}s",
        f"prompts: {source}, {stats.get('prompts')} prompts in {stats.get('conversations')} conversations"
        + (f" ({stats['too_long']} over {MAX_PROMPT_CHARS} chars and {stats['probes_left_out']} probes left out)"
           if "too_long" in stats else ""),
        f"model-call ceiling (--max-calls): {plan.max_calls}; sends at most {plan.sends}",
        f"limits in git: nginx {limits['edge_session_rpm']}/min per conversation "
        f"(burst {limits['edge_session_burst']}); guard-proxy {limits['proxy_cluster_rpm']}/min per "
        f"cluster, {limits['proxy_session_rpm']}/min per session, COST_CAP_USD ${limits['cost_cap_usd']:g}",
        f"estimated cost: worst case ${plan.sends * plan.usd_per_call:.2f} (every send reaches the model at "
        f"${plan.usd_per_call:g} a call); predicted ${served * plan.usd_per_call:.2f} for about {served} served "
        f"turns over about {plan.minutes():.1f} min",
    ]


# --- one request ----------------------------------------------------------------------------------------------
def classify(status: int | None, body: dict | None, error: str = "") -> str:
    if error:
        return error
    if status == 200:
        reply = str((body or {}).get("reply") or "")
        if not reply.strip():
            return "empty"
        if EDGE_LIMIT_TEXT in reply:
            return "edge_limit"
        if SESSION_LIMIT_TEXT in reply:
            return "session_limit"
        if CLUSTER_LIMIT_TEXT in reply:
            return "cluster_limit"
        if BUDGET_TEXT in reply:
            return "budget"
        if (body or {}).get("guarded"):
            return "guarded"
        return "served"
    if status in (502, 504, 429):
        return f"http_{status}"
    return "http_other"


@dataclass
class Result:
    outcome: str
    status: int | None
    latency: float
    input_tokens: int = 0
    output_tokens: int = 0


def send_chat(base: str, prompt: str, session: str, timeout: float) -> Result:
    data = json.dumps({"prompt": f"{prompt} {PROBE_MARKER}", "session": session}).encode()
    req = urllib.request.Request(f"{base}/chat", data=data, method="POST", headers={
        "Content-Type": "application/json", "X-BurritoBot-Session": session})
    t0 = time.monotonic()
    status, body, error = None, None, ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            raw = r.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except TimeoutError:
        raw, error = b"", "timeout"
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raw, error = b"", "timeout" if isinstance(reason, TimeoutError) or "timed out" in str(reason) else "transport"
    latency = time.monotonic() - t0
    if not error:
        try:
            body = json.loads(raw or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
    body = body if isinstance(body, dict) else {}
    return Result(classify(status, body, error), status, latency,
                  int(body.get("input_tokens") or 0), int(body.get("output_tokens") or 0))


def get_cost(base: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base}/cost", timeout=20) as r:
            d = json.load(r)
            return d if isinstance(d, dict) else None
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


# --- the run -----------------------------------------------------------------------------------------------
@dataclass
class Run:
    base: str
    plan: Plan
    sequences: list[list[str]]
    timeout: float
    max_usd: float
    deadline: float
    seed: int
    run_id: str
    results: list[Result] = field(default_factory=list)
    sessions: set = field(default_factory=set)
    sent: int = 0
    in_flight: int = 0
    not_sent_ceiling: int = 0
    not_sent_stopped: int = 0
    stop_reason: str = ""

    def __post_init__(self):
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def _take_slot(self) -> bool:
        with self.lock:
            if self.stop.is_set():
                self.not_sent_stopped += 1
                return False
            if self.sent >= self.plan.max_calls:
                self.not_sent_ceiling += 1
                return False
            self.sent += 1
            self.in_flight += 1
            return True

    def _prompts_for(self, rng: random.Random) -> list[str]:
        """One recorded conversation from a random point, continued into another when it runs out."""
        out: list[str] = []
        seq = rng.choice(self.sequences)
        i = rng.randrange(len(seq))
        while len(out) < self.plan.turns:
            if i >= len(seq):
                seq, i = rng.choice(self.sequences), 0
            out.append(seq[i])
            i += 1
        return out

    def user(self, n: int, start_at: float) -> None:
        rng = random.Random(f"{self.seed}-{n}")
        prompts = self._prompts_for(rng)
        session = f"wib-load-{self.run_id}-{n:04d}"
        with self.lock:
            self.sessions.add(session)
        delay = start_at - time.monotonic()
        if delay > 0:
            self.stop.wait(delay)  # a stop during the ramp is caught by _take_slot below
        for t, prompt in enumerate(prompts):
            if not self._take_slot():
                with self.lock:  # this turn and every later one of this user are not sent
                    if self.stop.is_set():
                        self.not_sent_stopped += len(prompts) - t - 1
                    else:
                        self.not_sent_ceiling += len(prompts) - t - 1
                return
            res = send_chat(self.base, prompt, session, self.timeout)
            with self.lock:
                self.results.append(res)
                self.in_flight -= 1
            if t < len(prompts) - 1:
                self.stop.wait(rng.uniform(self.plan.think_min, self.plan.think_max))

    def snapshot(self) -> dict:
        with self.lock:
            res = list(self.results)
            sent, in_flight = self.sent, self.in_flight
        counts = {o: 0 for o in OUTCOMES}
        for r in res:
            counts[r.outcome] += 1
        lat = sorted(r.latency for r in res)
        return {"sent": sent, "in_flight": in_flight, "done": len(res), "counts": counts,
                "p50": percentile(lat, 50)}

    def execute(self, progress_every: float, cost_before: dict | None, out=sys.stdout) -> float:
        rng = random.Random(self.seed)
        t0 = time.monotonic()
        threads = []
        for n in range(self.plan.users):
            th = threading.Thread(target=self.user, args=(n, t0 + rng.uniform(0, self.plan.ramp)), daemon=True)
            th.start()
            threads.append(th)
        usd0 = float((cost_before or {}).get("usd") or 0)
        spend = 0.0
        while any(th.is_alive() for th in threads):
            time.sleep(progress_every)
            elapsed = time.monotonic() - t0
            cost = get_cost(self.base)
            if cost is not None:
                spend = float(cost.get("usd") or 0) - usd0
            if not self.stop.is_set():
                if self.max_usd > 0 and spend >= self.max_usd:
                    self.stop_reason = f"spend rose ${spend:.4f}, at or over --max-usd ${self.max_usd:g}"
                    self.stop.set()
                elif self.deadline > 0 and elapsed >= self.deadline:
                    self.stop_reason = f"--deadline {self.deadline:g}s passed"
                    self.stop.set()
            s = self.snapshot()
            c = s["counts"]
            limited = sum(c[o] for o in LIMIT_OUTCOMES)
            errors = sum(c[o] for o in ERROR_OUTCOMES)
            eta = ""
            if s["sent"] and s["sent"] < self.plan.sends and not self.stop.is_set():
                eta = f" eta {max(0.0, elapsed / s['sent'] * (self.plan.sends - s['sent'])):.0f}s"
            print(f"[load] {elapsed:6.1f}s sent {s['sent']}/{self.plan.sends} "
                  f"({100.0 * s['sent'] / max(1, self.plan.sends):.0f}%){eta} in-flight {s['in_flight']} "
                  f"served {c['served']} limited {limited} errors {errors} "
                  f"p50 {s['p50']:.2f}s spend +${spend:.4f}" + (" STOPPING" if self.stop.is_set() else ""),
                  file=out, flush=True)
        return time.monotonic() - t0


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile of an already sorted list; 0 for an empty one."""
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, math.ceil(p / 100.0 * len(sorted_values)) - 1))
    return sorted_values[k]


def latency_block(values: list[float]) -> dict:
    v = sorted(values)
    return {"n": len(v), "p50": percentile(v, 50), "p90": percentile(v, 90), "p95": percentile(v, 95),
            "p99": percentile(v, 99), "max": v[-1] if v else 0.0}


def summarize(run: Run, elapsed: float, cost_before: dict | None, cost_after: dict | None) -> dict:
    counts = {o: 0 for o in OUTCOMES}
    statuses: dict[str, int] = {}
    tin = tout = 0
    for r in run.results:
        counts[r.outcome] += 1
        key = str(r.status) if r.status is not None else r.outcome
        statuses[key] = statuses.get(key, 0) + 1
        tin += r.input_tokens
        tout += r.output_tokens
    usd_before = float(cost_before["usd"]) if cost_before and "usd" in cost_before else None
    usd_after = float(cost_after["usd"]) if cost_after and "usd" in cost_after else None
    spend = usd_after - usd_before if usd_before is not None and usd_after is not None else None
    return {
        "target": run.base, "run_id": run.run_id, "elapsed_s": round(elapsed, 1),
        "users": run.plan.users, "turns": run.plan.turns, "planned": run.plan.planned,
        "max_calls": run.plan.max_calls, "sent": run.sent, "answered": len(run.results),
        "not_sent_ceiling": run.not_sent_ceiling, "not_sent_stopped": run.not_sent_stopped,
        "stop_reason": run.stop_reason, "sessions": len(run.sessions),
        "outcomes": counts, "statuses": dict(sorted(statuses.items())),
        "rate_limit_refusals": sum(counts[o] for o in LIMIT_OUTCOMES),
        "latency_s": {"all": latency_block([r.latency for r in run.results]),
                      "served": latency_block([r.latency for r in run.results if r.outcome == "served"])},
        "tokens": {"input": tin, "output": tout},
        "cost_before": cost_before, "cost_after": cost_after,
        "spend_usd": spend,
        "usd_per_served": (spend / counts["served"]) if spend is not None and counts["served"] else None,
    }


def report_lines(s: dict) -> list[str]:
    o = s["outcomes"]
    lines = [
        "",
        f"== load replay report: {s['target']} (run {s['run_id']}, {s['elapsed_s']}s) ==",
        f"sent {s['sent']} of {s['planned']} planned turns over {s['sessions']} sessions; ceiling held back "
        f"{s['not_sent_ceiling']}, stopping held back {s['not_sent_stopped']}"
        + (f" ({s['stop_reason']})" if s["stop_reason"] else ""),
        "outcomes: " + ", ".join(f"{k} {v}" for k, v in o.items() if v),
        f"rate-limit refusals {s['rate_limit_refusals']}: nginx per conversation {o['edge_limit']}, "
        f"guard-proxy per session {o['session_limit']}, guard-proxy per cluster {o['cluster_limit']}; "
        f"cost cap {o['budget']}",
        "HTTP status: " + ", ".join(f"{k} {v}" for k, v in s["statuses"].items()),
        f"errors: 502 {o['http_502']}, 504 {o['http_504']}, 429 {o['http_429']}, other HTTP {o['http_other']}, "
        f"timeout {o['timeout']}, transport {o['transport']}, empty reply {o['empty']}",
    ]
    for name in ("all", "served"):
        b = s["latency_s"][name]
        lines.append(f"latency {name} (n={b['n']}): p50 {b['p50']:.2f}s p90 {b['p90']:.2f}s p95 {b['p95']:.2f}s "
                     f"p99 {b['p99']:.2f}s max {b['max']:.2f}s")
    lines.append(f"tokens: {s['tokens']['input']} in, {s['tokens']['output']} out")
    cb, ca = s["cost_before"], s["cost_after"]
    lines.append(
        "/cost before: " + (f"${float(cb.get('usd') or 0):.4f} over {cb.get('requests')} requests, cap "
                            f"${float(cb.get('cap_usd') or 0):g}" if cb else "not read")
        + "; after: " + (f"${float(ca.get('usd') or 0):.4f} over {ca.get('requests')} requests" if ca else "not read")
        + (f"; this run ${s['spend_usd']:.4f}" if s["spend_usd"] is not None else "")
        + (f", ${s['usd_per_served']:.5f} a served turn" if s["usd_per_served"] is not None else ""))
    return lines


def self_check(s: dict, max_usd: float) -> list[tuple[bool, str]]:
    o = s["outcomes"]
    unreadable = sum(o[k] for k in ERROR_OUTCOMES)
    return [
        (s["sent"] <= s["max_calls"], f"the model-call ceiling held ({s['sent']} sent, ceiling {s['max_calls']})"),
        (s["answered"] == s["sent"], f"every sent turn came back ({s['answered']} of {s['sent']})"),
        (unreadable == 0, f"every turn got a sentence a phone can read ({unreadable} errors, timeouts or empty "
                          "replies)"),
        (s["cost_before"] is not None and s["cost_after"] is not None, "/cost read before and after"),
        (s["spend_usd"] is None or max_usd <= 0 or s["spend_usd"] <= max_usd * 1.5,
         f"spend stayed near --max-usd (${s['spend_usd'] or 0:.4f} against ${max_usd:g}; in-flight turns finish "
         "after the stop)"),
    ]


def base_url(target: str) -> str:
    t = target.rstrip("/")
    return t if re.match(r"^https?://", t) else f"https://{t}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="the public host (https assumed), or a full http(s):// URL")
    ap.add_argument("--yes", action="store_true", help="send; without it the plan and estimate print and nothing is sent")
    ap.add_argument("--source", choices=("harvest", "catalog"), default="harvest")
    ap.add_argument("--harvest", type=pathlib.Path, default=DEFAULT_HARVEST,
                    help=f"the harvest's prompts/ directory (default {DEFAULT_HARVEST})")
    ap.add_argument("--users", type=int, default=500)
    ap.add_argument("--turns", type=int, default=3, help="turns each user sends (default 3)")
    ap.add_argument("--max-calls", type=int, default=1500, help="hard ceiling on /chat sends (default 1500)")
    ap.add_argument("--max-usd", type=float, default=10.0,
                    help="stop new turns once /cost has risen this much (default 10; 0 turns it off)")
    ap.add_argument("--deadline", type=float, default=900.0, help="stop new turns after this many seconds (default 900)")
    ap.add_argument("--ramp", type=float, default=60.0, help="users start spread over this many seconds (default 60)")
    ap.add_argument("--think-min", type=float, default=15.0)
    ap.add_argument("--think-max", type=float, default=45.0)
    ap.add_argument("--timeout", type=float, default=TIMEOUT_S, help=f"per-turn client timeout (default {TIMEOUT_S:g})")
    ap.add_argument("--usd-per-call", type=float, default=USD_PER_CALL)
    ap.add_argument("--progress", type=float, default=5.0, help="seconds between progress lines (default 5)")
    ap.add_argument("--seed", type=int, default=644)
    ap.add_argument("--json-out", type=pathlib.Path, help="write the report as JSON (no prompt or reply text)")
    args = ap.parse_args(argv)

    if args.users < 1 or args.turns < 1 or args.max_calls < 1 or args.think_max < args.think_min:
        ap.error("--users, --turns and --max-calls must be at least 1, and --think-max at least --think-min")
    if args.source == "harvest":
        sequences, stats = load_harvest(args.harvest.expanduser())
        source = f"harvest {args.harvest}"
    else:
        sequences, stats = load_catalog()
        source = "catalog (the stage's asks)"
    plan = Plan(args.users, args.turns, args.max_calls, args.ramp, args.think_min, args.think_max,
                args.usd_per_call)
    limits = deployed_limits()
    base = base_url(args.target)
    for line in plan_lines(plan, limits, source, stats, base):
        print(line, flush=True)
    if not args.yes:
        print("plan only: nothing sent. Add --yes to run it.", flush=True)
        return 0

    cost_before = get_cost(base)
    if cost_before is None:
        print(f"FAIL  {base}/cost did not answer; not sending anything", flush=True)
        return 1
    cap = float(cost_before.get("cap_usd") or 0)
    if cap and float(cost_before.get("usd") or 0) + plan.sends * plan.usd_per_call >= cap:
        print(f"note: worst case would reach the cluster's ${cap:g} cap from ${float(cost_before['usd']):.4f}; "
              "turns past it come back as cost-cap refusals", flush=True)
    run = Run(base, plan, sequences, args.timeout, args.max_usd, args.deadline, args.seed,
              time.strftime("%Y%m%d%H%M", time.gmtime()))
    elapsed = run.execute(args.progress, cost_before)
    cost_after = get_cost(base)
    summary = summarize(run, elapsed, cost_before, cost_after)
    for line in report_lines(summary):
        print(line)
    checks = self_check(summary, args.max_usd)
    print()
    for ok, text in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {text}")
    green = all(ok for ok, _ in checks)
    summary["self_check"] = [{"pass": ok, "check": text} for ok, text in checks]
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"report written to {args.json_out}")
    print("LOAD REPLAY GREEN" if green else "LOAD REPLAY RED", flush=True)
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
