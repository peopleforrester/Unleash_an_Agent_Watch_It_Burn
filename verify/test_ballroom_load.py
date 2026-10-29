# ABOUTME: Offline half of the #450 ballroom load test: verify/ballroom_load.py reads nginx's and guard-proxy's real
# ABOUTME: replies right, and its verdict fails a room that breaks the ceiling, starves, times out or nears the cap.
"""verify/ballroom_load.py spends real Bedrock on attackme, so it runs by hand. This holds what it decides: the
reply kinds against the bodies console.conf and proxy.py actually send, the verdict against made-up rooms, and the
whole run loop in-process against a fake front door that limits like nginx's leaky bucket.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import re
import sys
import threading
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
PROXY_SRC = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
if not PROXY_SRC.exists():
    print(f"FAILED: {PROXY_SRC} is missing; run bash verify/ensure-submodules.sh")
    sys.exit(1)
PROXY = PROXY_SRC.read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("ballroom_load", REPO / "verify/ballroom_load.py")
bl = importlib.util.module_from_spec(spec)
sys.modules["ballroom_load"] = bl  # dataclasses look their module up here
spec.loader.exec_module(bl)

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def returned(loc: str) -> tuple[int, dict]:
    """(status, JSON body) a named location in console.conf returns."""
    m = re.search(r"location " + re.escape(loc) + r" \{.*?return (\d+) '((?:[^'\\]|\\.)*)';", CONF, re.S)
    return int(m.group(1)), json.loads(m.group(2).replace("\\'", "'"))


print("== what it reads from console.conf ==")
limits = bl.limits_from_conf(CONF)
_, slow = returned("@chat_slow_down")
check(f"the per-network rate it reads ({limits['address_rpm']}) is the one the refusal names",
      f"{limits['address_rpm']} a minute from one network" in slow["reply"])
check(f"its client waits longer than nginx's /chat ({limits['chat_timeout']}s) and Railway's 300s",
      bl.CLIENT_TIMEOUT > max(limits["chat_timeout"], 300))

print("== the reply kinds, on the bodies the platform sends ==")
check("nginx's limit is nginx_limit", bl.classify(*returned("@chat_slow_down")) == "nginx_limit")
check("nginx's 502 and 504 are kitchen_down",
      bl.classify(*returned("@chat_kitchen_down")) == bl.classify(*returned("@chat_kitchen_slow")) == "kitchen_down")
check("guard-proxy's texts are still the ones it matches",
      all(t in PROXY for t in ("Slow down, hungry traveler. ({RATE_LIMIT_SESSION_RPM}/min per conversation.)",
                               "({RATE_LIMIT_RPM}/min cap on this cluster.)", "The kitchen tab is frozen",
                               "BurritoBot's kitchen isn't answering")))
check("guard-proxy's per-conversation and cluster limits are told apart",
      bl.classify(200, {"reply": "Slow down, hungry traveler. (10/min per conversation.)", "guarded": True})
      == "conversation_limit"
      and bl.classify(200, {"reply": "Slow down, hungry traveler. (150/min cap on this cluster.)", "guarded": True})
      == "cluster_limit")
check("the cost cap is cost_cap", bl.classify(200, {"reply": "The kitchen tab is frozen. This conversation hit",
                                                    "guarded": True}) == "cost_cap")
check("an answer and a guard's refusal are both sentences",
      bl.classify(200, {"reply": "Carnitas, chicken and sofritas.", "guarded": False}) == "answered"
      and bl.classify(200, {"reply": "BurritoBot can't help with that.", "guarded": True}) == "guarded")
check("a bare HTML 504, a connection error, an empty reply and an unknown error are unreadable",
      all(bl.classify(s, b) == "unreadable" for s, b in (
          (504, {"raw": "<html><body>504 Gateway Time-out</body></html>"}),
          (0, {"error": "TimeoutError: timed out"}), (200, {"reply": "  "}),
          (502, {"error": "agent forward failed"}), (403, {"reply": "Forbidden"}))))

print("== the verdict on made-up rooms ==")
L = {"address_rpm": 120, "address_burst": 60, "chat_timeout": 285}


def room(n_past: int, n_limited: int, minutes: float = 5, extra: tuple = ()) -> list:
    out = [bl.Result(i, minutes * 60 * i / max(1, n_past - 1), 200, {}, 4.0, "answered") for i in range(n_past)]
    out += [bl.Result(i, 1.0, 200, {}, 0.1, "nginx_limit") for i in range(n_limited)]
    return out + [bl.Result(0, 2.0, s, b, 1.0, bl.classify(s, b)) for s, b in extra]


ok = room(650, 900)
check("a room at the ceiling, cheap, passes", bl.verdict(ok, L, 0.0, 4.0, 25, 5) == [])
check("a room under the ceiling that offered less than it passes", bl.verdict(room(300, 0), L, 0.0, 2.0, 25, 5) == [])
check("one bare 504 fails", any("not a sentence" in f for f in
                                bl.verdict(room(650, 900, extra=((504, {"raw": "<html>"}),)), L, 0, 4, 25, 5)))
check("one kitchen_down fails", any("kitchen" in f for f in bl.verdict(
    room(650, 900, extra=((504, returned("@chat_kitchen_slow")[1]),)), L, 0, 4, 25, 5)))
check("reaching guard-proxy's cluster window fails", any("cluster window" in f for f in bl.verdict(
    room(650, 900, extra=((200, {"reply": "Slow down, hungry traveler. (150/min cap on this cluster.)"}),)),
    L, 0, 4, 25, 5)))
check("more past nginx than the ceiling allows fails (nginx keyed on something other than the network)",
      any("over the ceiling" in f for f in bl.verdict(room(1400, 100), L, 0, 4, 25, 5)))
check("well under the ceiling while the room offered more fails (something lower bound first)",
      any("held the room back" in f for f in bl.verdict(room(300, 1200), L, 0, 2, 25, 5)))
check("a spend rate that would reach the cap within the segment fails",
      any("at or over" in f for f in bl.verdict(ok, L, 10.0, 23.0, 25, 10)))
check("reaching the cap fails", any("reached" in f for f in bl.verdict(ok, L, 0.0, 25.0, 25, 5)))
check("no cap fails", any("no cap" in f for f in bl.verdict(ok, L, 0.0, 4.0, 0, 5)))
check("no turns fails", bl.verdict([], L, 0, 0, 25, 5) != [])

print("== the run loop, in-process, behind a fake nginx ==")


class Front:
    """nginx's leaky bucket for one zone: burst + 1 at once, then one every 60/rate seconds."""

    def __init__(self, rate: float, burst: int, keyed_per_request: bool = False, reply=None):
        self.rate, self.burst, self.per_request = rate / 60, burst, keyed_per_request
        self.excess, self.last, self.lock, self.cost = -1.0, time.monotonic(), threading.Lock(), 0.0
        self.reply = reply or (lambda n: (200, {"reply": "Carnitas, chicken and sofritas.", "guarded": False}))
        self.n = 0

    def chat(self, host, prompt, session):
        assert prompt.startswith(bl.MARKER) and session.startswith("wib-load-450-")
        with self.lock:
            now = time.monotonic()
            excess = max(-1.0, self.excess - self.rate * (now - self.last)) + 1
            if excess > self.burst and not self.per_request:
                return 200, {"reply": returned("@chat_slow_down")[1]["reply"], "guarded": True}, 0.001
            self.excess, self.last = excess, now
            self.n += 1
            self.cost += 0.006
            n = self.n
        time.sleep(0.005)
        status, body = self.reply(n)
        return status, body, 0.005

    def read_cost(self, host):
        with self.lock:
            return self.cost, 25.0


def run(front: Front, *argv: str) -> tuple[int, str]:
    bl.chat, bl.read_cost, bl.COST_POLL_S = front.chat, front.read_cost, 0.2
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = bl.main(["--host", "fake.invalid", "--phones", "30", "--minutes", "0.05", "--think", "0.05",
                      "--segment-minutes", "0.5", *argv])
    return rc, out.getvalue()


rc, out = run(Front(L["address_rpm"], L["address_burst"]), "--max-usd", "5")
check("a room behind a front door that holds the ceiling passes", rc == 0 and "The room held" in out)
rc, out = run(Front(L["address_rpm"], L["address_burst"], keyed_per_request=True), "--max-usd", "50")
check("a front door that does not limit the network fails on the ceiling", rc == 1 and "over the ceiling" in out)
rc, out = run(Front(L["address_rpm"], L["address_burst"],
                    reply=lambda n: (502, {"raw": "<html>502</html>"}) if n % 7 == 0
                    else (200, {"reply": "Sofritas.", "guarded": False})), "--max-usd", "5")
check("a front door that answers some turns with a bare 502 fails on the words", rc == 1 and "not a sentence" in out)
rc, out = run(Front(L["address_rpm"], L["address_burst"]), "--max-usd", "0.05", "--segment-minutes", "0.001")
check("the run stops and fails once /cost rises by --max-usd", rc == 1 and "at or over --max-usd 0.05; stopped" in out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All ballroom load-test checks passed.")
