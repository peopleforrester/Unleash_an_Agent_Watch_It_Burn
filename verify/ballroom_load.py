# ABOUTME: The phone-scale load test for #450: a ballroom of phones on one network sends real turns to the community
# ABOUTME: bot through the apex for an audience segment, and every phone must read a sentence while the ceiling holds.
"""Run by hand from a session with network access, never from the venue network during the session:

    python3 verify/ballroom_load.py --host attackme.agenticburn.com --max-usd 6

Every phone here leaves through this machine's one public address, which is what the venue Wi-Fi NAT does to the
room. Each phone is one conversation (its own X-BurritoBot-Session) that sends a turn, waits for the reply, reads
it for a think time, and sends again, for --minutes. The defaults, 200 phones thinking about 30 s for 5 minutes,
offer the network well over its ceiling, so the run shows what the room sees when it is saturated.

It fails when any of these do not hold:
- every reply is a sentence in the /chat shape: no connection error, no bare HTML page, no empty reply;
- no turn ends in "kitchen isn't answering", the reply a hop's timeout or a dead upstream gives;
- guard-proxy's cluster window is never reached, so cellular phones and the stage keep their share;
- the turns that get past nginx come to the per-network ceiling, read from console.conf: not over it, so the
  ceiling holds, and not well under it, so nothing lower (Bedrock throttling, a slow pod) binds first;
- the cost cap is not reached, and the measured spend rate leaves --segment-minutes of a saturated room under it.

What it spends. The turns are real, marked [[wib-probe]] so the instructor feed skips them, and at most the
network's ceiling of them reach the model: about 660 turns over 5 minutes, a few dollars of Bedrock. --max-usd is
required; the run stops and fails once /cost has risen by that much. The spend stays on /cost until the counter is
reset, so reset the community bot after it (run-of-show, "Reset the community bot").
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import json
import math
import pathlib
import random
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
CONF_PATH = REPO / "gitops/ai-layer/console.conf"
MARKER = "[[wib-probe]]"
# Asks a ballroom sends: menu questions and the off-topic kind the talk invites. A guard refusing one is a
# readable reply, so it counts like an answer.
ASKS = [
    "what proteins do you have?",
    "is guacamole extra on a burrito bowl?",
    "which salsa is the hottest?",
    "can I get a burrito with no rice and double beans?",
    "what's the best Kubernetes distro for a toaster?",
    "write me a haiku about a pod in CrashLoopBackOff",
]
# Above Railway's 300 s with no data, so the client sees whatever a phone would, Railway's own error included.
CLIENT_TIMEOUT = 310
COST_POLL_S = 15  # how often the spend stop reads /cost


@dataclasses.dataclass
class Result:
    phone: int
    sent_at: float
    status: int
    body: dict
    latency: float
    kind: str


def limits_from_conf(conf: str) -> dict:
    """The per-network zone and the /chat timeout the console's nginx runs, read from console.conf."""
    rate = re.search(r"limit_req_zone \$http_x_forwarded_for zone=wib_chat_address:\S+ rate=(\d+)r/m;", conf)
    burst = re.search(r"limit_req zone=wib_chat_address burst=(\d+)", conf)
    chat = re.search(r"location = /chat \{(.*?)\n  \}", conf, re.S)
    timeout = re.search(r"proxy_read_timeout (\d+)s;", chat.group(1)) if chat else None
    if not (rate and burst and timeout):
        raise ValueError("console.conf no longer has the /chat per-network zone, its burst and its read timeout")
    return {"address_rpm": int(rate.group(1)), "address_burst": int(burst.group(1)),
            "chat_timeout": int(timeout.group(1))}


def classify(status: int, body: dict) -> str:
    """What the phone showed. Everything but 'unreadable' is a sentence on the screen."""
    reply = body.get("reply")
    if status == 0 or not isinstance(reply, str) or not reply.strip():
        return "unreadable"
    if "kitchen isn't answering" in reply:
        return "kitchen_down"
    if "Slow down, hungry traveler." in reply:
        if "from one network" in reply:
            return "nginx_limit"
        if "cap on this cluster" in reply:
            return "cluster_limit"
        return "conversation_limit"
    if "kitchen tab is frozen" in reply:
        return "cost_cap"
    if status != 200:
        return "unreadable"
    return "guarded" if body.get("guarded") is True else "answered"


# Kinds that got past nginx: guard-proxy wrote the reply.
PAST_NGINX = ("answered", "guarded", "conversation_limit", "cluster_limit", "cost_cap", "kitchen_down")


def verdict(results: list[Result], limits: dict, cost_before: float, cost_after: float, cap: float,
            segment_minutes: float) -> list[str]:
    """The failures of one run, empty when the room held."""
    failures = []
    if not results:
        return ["no turn was sent"]
    kinds = [r.kind for r in results]
    bad = [r for r in results if r.kind == "unreadable"]
    if bad:
        sample = "; ".join(f"HTTP {r.status} {str(r.body)[:80]}" for r in bad[:3])
        failures.append(f"{len(bad)} replies were not a sentence a phone can read: {sample}")
    if kinds.count("kitchen_down"):
        failures.append(f"{kinds.count('kitchen_down')} turns ended in 'kitchen isn't answering'")
    if kinds.count("cluster_limit"):
        failures.append(f"{kinds.count('cluster_limit')} turns reached guard-proxy's cluster window from one "
                        "network, so the per-network ceiling did not hold the room under it")
    if kinds.count("cost_cap"):
        failures.append(f"{kinds.count('cost_cap')} turns hit the cost cap")

    span_min = (max(r.sent_at for r in results) - min(r.sent_at for r in results)) / 60
    rate, burst = limits["address_rpm"], limits["address_burst"]
    past = sum(kinds.count(k) for k in PAST_NGINX)
    # nginx's leaky bucket passes its burst plus one, then one every 60/rate seconds; 2 more for clock edges.
    most = burst + 1 + rate * span_min + 2
    least = 0.9 * min(len(results), burst + rate * span_min)
    if past > most:
        failures.append(f"{past} turns got past nginx in {span_min:.1f} min, over the ceiling's {most:.0f}: "
                        "nginx is not keying on the caller's network")
    if past < least:
        failures.append(f"only {past} turns got past nginx in {span_min:.1f} min, under {least:.0f}: something "
                        "below the per-network ceiling held the room back")

    spent = cost_after - cost_before
    if cap <= 0:
        failures.append("/cost reports no cap, so nothing stops a runaway room")
    elif cost_after >= cap:
        failures.append(f"the room reached the ${cap:.2f} cap (${cost_after:.4f})")
    elif span_min > 0:
        projected = cost_before + spent / span_min * segment_minutes
        if projected >= cap:
            failures.append(f"at ${spent / span_min:.4f} a minute, {segment_minutes:g} minutes of this room comes to "
                            f"${projected:.2f}, at or over the ${cap:.2f} cap")
    return failures


def chat(host: str, prompt: str, session: str) -> tuple[int, dict, float]:
    headers = {"Content-Type": "application/json", "User-Agent": "wib-verify/450-ballroom",
               "X-BurritoBot-Session": session}
    req = urllib.request.Request(f"https://{host}/chat", data=json.dumps({"prompt": prompt, "session": session}).encode(),
                                 headers=headers, method="POST")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=CLIENT_TIMEOUT) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}, time.monotonic() - start
    try:
        body = json.loads(raw)
    except ValueError:
        body = {"raw": raw[:120].decode(errors="replace")}
    return status, body if isinstance(body, dict) else {"raw": str(body)[:120]}, time.monotonic() - start


def read_cost(host: str) -> tuple[float, float]:
    with urllib.request.urlopen(f"https://{host}/cost", timeout=30) as r:
        payload = json.loads(r.read())
    return float(payload["usd"]), float(payload.get("cap_usd") or 0)


def phone(i: int, host: str, deadline: float, think: float, stop: threading.Event, out: list, lock) -> None:
    rnd = random.Random(i)
    session = f"wib-load-450-{uuid.uuid4().hex}"
    # The room does not press send in the same second; the first turns spread over one think time.
    if stop.wait(rnd.uniform(0, think)):
        return
    while time.monotonic() < deadline and not stop.is_set():
        sent = time.monotonic()
        status, body, took = chat(host, f"{MARKER} {rnd.choice(ASKS)}", session)
        with lock:
            out.append(Result(i, sent, status, body, took, classify(status, body)))
        stop.wait(rnd.uniform(0.5 * think, 1.5 * think))


def report(results: list[Result], limits: dict, cost_before: float, cost_after: float, cap: float) -> None:
    kinds = [r.kind for r in results]
    span_min = (max(r.sent_at for r in results) - min(r.sent_at for r in results)) / 60 if results else 0
    print(f"  {len(results)} turns sent in {span_min:.1f} min by {len({r.phone for r in results})} phones")
    for k in ("answered", "guarded", "nginx_limit", "conversation_limit", "cluster_limit", "cost_cap",
              "kitchen_down", "unreadable"):
        print(f"    {k:<19} {kinds.count(k)}")
    lat = sorted(r.latency for r in results if r.kind in ("answered", "guarded"))
    if lat:
        p95 = lat[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)]
        print(f"  answered latency: median {statistics.median(lat):.1f}s, p95 {p95:.1f}s, max {lat[-1]:.1f}s "
              f"(nginx /chat gives up at {limits['chat_timeout']}s)")
    answered = {r.phone for r in results if r.kind in ("answered", "guarded")}
    phones = {r.phone for r in results}
    print(f"  phones that got at least one answer: {len(answered)} of {len(phones)}")
    print(f"  /cost: ${cost_before:.4f} -> ${cost_after:.4f} of a ${cap:.2f} cap")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", required=True, help="the community bot's public host, e.g. attackme.agenticburn.com")
    ap.add_argument("--max-usd", type=float, required=True, help="stop and fail once /cost has risen by this much")
    ap.add_argument("--phones", type=int, default=200)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--think", type=float, default=30, help="mean seconds a phone reads a reply before sending again")
    ap.add_argument("--segment-minutes", type=float, default=5,
                    help="how long a saturated room must fit under the cost cap")
    args = ap.parse_args(argv)
    limits = limits_from_conf(CONF_PATH.read_text(encoding="utf-8"))

    try:
        cost_before, cap = read_cost(args.host)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"FAILED: https://{args.host}/cost is not readable: {e}")
        return 1
    most = limits["address_burst"] + 1 + limits["address_rpm"] * args.minutes
    print(f"== {args.phones} phones on one network, {args.minutes:g} min, through https://{args.host} ==")
    print(f"  at most about {most:.0f} turns reach the model; stopping if /cost rises ${args.max_usd:g}")

    results: list[Result] = []
    lock, stop = threading.Lock(), threading.Event()
    over = []
    deadline = time.monotonic() + args.minutes * 60
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.phones) as pool:
        for i in range(args.phones):
            pool.submit(phone, i, args.host, deadline, args.think, stop, results, lock)
        while time.monotonic() < deadline and not stop.is_set():
            stop.wait(min(COST_POLL_S, max(0.0, deadline - time.monotonic())))
            try:
                now, _ = read_cost(args.host)
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                # The spend stop is blind without /cost, so the room stops with it.
                over.append(f"/cost stopped answering mid-run ({e}); stopped")
                stop.set()
                break
            if now - cost_before >= args.max_usd:
                over.append(f"/cost rose ${now - cost_before:.4f}, at or over --max-usd {args.max_usd:g}; stopped")
                stop.set()
        # Phones mid-turn finish it; nobody sends a new one.
        stop.set()
    try:
        cost_after, cap = read_cost(args.host)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"FAILED: https://{args.host}/cost is not readable after the run: {e}")
        return 1

    report(results, limits, cost_before, cost_after, cap)
    failures = over + verdict(results, limits, cost_before, cost_after, cap, args.segment_minutes)
    print()
    print("Reset the community bot now: ./fleet.sh reset-bot watch-it-burn-community (run-of-show).")
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("The room held: every phone read a sentence, and the per-network ceiling bound first.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
