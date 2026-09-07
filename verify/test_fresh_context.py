# ABOUTME: Reset must give the student a genuinely fresh agent conversation, keep their saved prompts,
# ABOUTME: and the lab must say that a page refresh does not do the same thing.
"""Pins the fresh-context affordance (#311).

The mechanism already worked before this test existed; what failed was that nobody could tell. A student
whose first clumsy prompt earns a refusal spends the rest of the conversation arguing with that refusal,
and from the chat window it is indistinguishable from a guardrail firing. Three things have to hold
together, and each has broken independently at some point:

1. Reset mints a NEW session id, which is what the proxy sends as the A2A contextId. Clearing the rendered
   stream without minting one would look right and change nothing on the server.
2. Reset does NOT throw away the saved prompts. The reason you reset is that BurritoBot refused you, and
   the next thing you want is the prompt it refused.
3. The lab states that a refresh is not a reset. sessionStorage survives a refresh and a hard refresh, so
   the intuition every student arrives with is wrong.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
PROXY = (REPO / "gitops/ai-layer/proxy.py").read_text(encoding="utf-8")
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# The reset body, isolated: several assertions below are about what it does NOT call, and searching the
# whole page would find those calls in unrelated handlers.
m = re.search(r"function resetChat\(\)\{(.*?)\n  \}", PAGE, re.S)
RESET = m.group(1) if m else ""

print("== reset reaches the server, not just the screen ==")
check("resetChat exists", bool(RESET))
check("it mints a new session id", "newSession()" in RESET)
check("the new id is persisted, so the next send carries it", "sessionStorage.setItem('wib-sess'" in PAGE)
check("the session id is what the proxy threads the conversation by",
      "session:getSession()" in PAGE and "_effective_ctx(session)" in PROXY)
check("the proxy sends it as the A2A contextId", 'm["contextId"] = ctx' in PROXY)
check("it clears the rendered conversation too", "innerHTML=''" in RESET)
check("it re-greets, so the student sees a conversation that has actually restarted", "greet()" in RESET)

print("== reset keeps the prompts the student is about to re-send ==")
# It used to call clearSaved(), which destroyed exactly the thing the reset was performed to reuse.
check("reset does not wipe the saved prompts", "clearSaved()" not in RESET)
check("clearing prompts is still available on its own", "onclick=\"clearSaved()\"" in PAGE)
check("the reset message says the prompts survived", "saved prompts are still here" in RESET)

print("== the student is told what reset actually did ==")
check("the message states the agent forgot", "forgotten everything" in RESET)
check("the button carries the same fact", 'title="Start a new conversation.' in PAGE)
check("the button says a refresh is not a reset",
      re.search(r'title="[^"]*refresh does not do this', PAGE) is not None)

print("== Challenge 1 tells them to reset at the point it matters ==")
# Measured on watch-it-burn-michael-admin, 2026-09-07/08, 10 different prompts written without reference to
# the system prompt:
#   fresh conversation per attempt   15 of 20 complied   83%
#   one conversation, after the in-chat refusal the lab itself asks for   0 of 10 complied   0%
# The lab was instructing every student to poison their own context before the real attempt, which is what
# made Challenge 1 look unwinnable (#321). The reset step is the fix and it belongs BETWEEN the two asks.
C1 = LAB[LAB.find("Challenge 1: Exfiltrate"):LAB.find("Challenge 2: Deploy")]
check("C1 tells the student to reset", "press &#8635; Reset before you go further" in C1)
check("it says why: the refusal stays in the conversation", "that no stays in the conversation" in C1)
check("it cites the measured rates", "83%" in C1 and "0%" in C1)
check("it reassures them the prompts survive", "saved prompts stay" in C1)
# Order is the whole point: after the chat ask that gets refused, before the exfil attempt.
i_ask = C1.find("First, ask it for the demographic info in chat")
i_reset = C1.find("press &#8635; Reset")
i_exfil = C1.find("send the data somewhere instead")
check("the reset sits after the in-chat ask", i_ask != -1 and i_reset > i_ask)
check("and before the exfil attempt", i_exfil != -1 and i_reset < i_exfil)

print("== the lab explains it before the challenges start ==")
check("the lab has the section", "When BurritoBot refuses you, reset it" in LAB)
check("it names the button", "↺ Reset button" in LAB)
check("it says a refresh does not reset", "Refreshing the page does not do this" in LAB)
check("it covers the hard refresh people will try next", "hard refresh" in LAB)
check("it explains why a stale refusal matters", "path-dependent" in LAB)
check("it names the confusion this prevents", "identical to a guardrail" in LAB)
# Michael's counter-argument: a real deployment keeps context on purpose. The workshop is otherwise careful
# to be realistic, and a student who spots the difference has spotted something true.
check("it admits the button is a lab affordance", "A real ordering app would not have this button" in LAB)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All fresh-context checks passed.")
