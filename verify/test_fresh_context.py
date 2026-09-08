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

print("== the Reset mechanic is explained in exactly ONE place ==")
# THIS CHECK WAS INVERTED ON PURPOSE. It used to require Challenge 1 to carry its own Reset paragraph,
# placed between the in-chat ask and the exfil attempt (#321). Whitney deleted that paragraph (her doc
# line 909): the mechanic belongs in Section 0's "Remember: You can always clear BurritoBot's context"
# collapsible, which is where she put it, and repeating it inside the attack instructions was part of the
# density she objected to. So the invariant is no longer "C1 repeats it" but "it is said once, in
# Section 0, and does not creep back into a challenge". Do not "fix" a failure here by restoring the C1
# paragraph.
C1 = LAB[LAB.find("Challenge 1: Exfiltrate"):LAB.find("Challenge 2: Deploy")]
check("Section 0 owns the explanation", "Remember: You can always clear BurritoBot's context" in LAB)
check("C1 does not repeat it", "press &#8635; Reset before you go further" not in C1
      and "that no stays in the conversation" not in C1)
# The attack instructions themselves must still be intact after the paragraph was removed from between
# them, so the in-chat ask and the exfil attempt both survive and remain in that order.
_ask, _exfil = C1.find("First, ask it for the demographic info in chat"), C1.find("send the data somewhere instead")
check("the two attack beats survive, in order", _ask != -1 and _exfil != -1 and _ask < _exfil)

print("== the lab explains it before the challenges start ==")
# Whitney's Sept-7 lean pass (#357) retitled this section and cut the measurement paragraph and the
# "real ordering app" aside from Section 0. The measured 83%/0% reason now lives once, in Challenge 1
# where the student is about to need it (asserted above), and in the presenter brief; Section 0 keeps the
# instruction without the justification.
check("the lab has the section", "Remember: You can always clear BurritoBot's context" in LAB)
check("it names the button", "↺ Reset button" in LAB)
check("it says a refresh does not reset", "Refreshing the page does not do this" in LAB)
check("it covers the hard refresh people will try next", "hard refresh" in LAB)
# WHAT THIS CHECK USED TO PIN, AND WHY IT NO LONGER DOES.
# It required three things in the Reset explainer: the word "path-dependent", the instruction to reset
# "at the start of every challenge", and the phrase "identical to a guardrail". Whitney cut all three by
# name (her doc lines 883 and 1085), calling the paragraph too dense, and her wording wins on this page.
# Restoring those strings would be re-applying text she deleted, so do not "fix" this by putting them
# back. What survives is the part a stuck student actually needs: the button, what it forgets, and the
# fact that a refresh is not a substitute.
check("it names the button, not just the idea", "Reset button at the top of the chat" in LAB)
check("it says what BurritoBot forgets",
      "forgets everything you have said" in LAB and "dug its heels in about" in LAB)
# Her capitalised ESPECIALLY is deliberate emphasis and is the whole point of the sentence.
check("it keeps her emphasis on the refusal it forgets",
      "ESPECIALLY whatever it dug its heels in about" in LAB)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All fresh-context checks passed.")
