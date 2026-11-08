# ABOUTME: Holds #1010 offline: BurritoBot confirms a completed five-step order with "Your order is now complete.",
# ABOUTME: never "Free burritos for life" or "You did it", and the chat page's ring-me-up check reads the new sentence.
"""The order-complete sentence, offline.

The persona (gitops/workshop-agent/agent.yaml) used to congratulate a finished order with "You did it. Free burritos
for life!", and the chat page (gitops/ai-layer/web/burritbot.html) showed the ring-me-up button when a reply held
"free burritos for life". Now the persona says exactly "Your order is now complete." and the page tests each reply
with a case-insensitive regex that allows any whitespace between the words. What this holds:

- the persona asks for "Your order is now complete." word for word and says neither old phrase;
- send() tests the reply with that regex and no longer looks for "free burritos for life";
- the celebration popup keeps its own "Free burritos for life!" heading and the button keeps its label;
- the regex, run here with Python's re (its \\s and the i flag read the same as JavaScript's for these replies),
  matches the three spellings the issue names and a line-broken one, and misses replies without the sentence.

The page's own JavaScript runs in node in verify/test_order_complete_button_e2e.py, which proves the button itself.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AGENT = REPO / "gitops/workshop-agent/agent.yaml"
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
PAGE = PAGE_PATH.read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def cut(text: str, start: str, end: str, where: str) -> str:
    """The text from one anchor to the next, or exit naming the anchor that is missing (#797)."""
    i = text.find(start)
    j = text.find(end, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        print(f"FAIL  anchor {(start if i < 0 else end)!r} is not in {where}", file=sys.stderr)
        sys.exit(1)
    return text[i:j]


docs = [d for d in yaml.safe_load_all(AGENT.read_text(encoding="utf-8")) if d]
agents = [d for d in docs if d.get("kind") == "Agent"]
if len(agents) != 1:
    print(f"FAIL  {AGENT} holds {len(agents)} Agent documents, not one", file=sys.stderr)
    sys.exit(1)
prompt = agents[0]["spec"]["declarative"]["systemMessage"]
flat = " ".join(prompt.split())

check('the persona confirms a completed order with exactly "Your order is now complete."',
      'confirm it with exactly: "Your order is now complete."' in flat)
check("the persona ties the sentence to the five-step order",
      'When they complete the full five-step order, confirm it with exactly: "Your order is now complete."' in flat)
check('the persona no longer says "Free burritos for life"', "free burritos" not in flat.lower())
check('the persona no longer says "You did it"', "you did it" not in flat.lower())

send = cut(PAGE, "  async function send(){", "  // The left menu is a static reference", str(PAGE_PATH))
# Since #1214 the button takes the reply botReply returned, so it can show that reply from its first line again.
TRIGGER = r"if(/your\s+order\s+is\s+now\s+complete/i.test(data.reply||'')) winBubble(reply);"
check("send() shows the ring-me-up button when the reply holds the order-complete sentence", TRIGGER in send)
check('send() no longer looks for "free burritos for life"', "free burritos" not in send.lower())
check("send() calls winBubble(reply) once, from that check", send.count("winBubble(") == 1)
check("send() keeps the reply bubble botReply returns, for the button (#1214)", "const reply=botReply(data.reply);" in send)

check('the celebration popup keeps its "Free burritos for life!" heading',
      '<div id="celebrate"><div class="winmsg"><h2>🌯 Free burritos for life! 🌯</h2>' in PAGE)
win = cut(PAGE, "  function winBubble(reply){", "  function celebrate(){", str(PAGE_PATH))
check("the button keeps its label and still sets off the celebration",
      "b.textContent=\"🔔 That's my order, ring me up!\"; b.onclick=celebrate;" in win)

literal = re.search(r"if\(/(.+?)/i\.test\(data\.reply", send)
pattern = re.compile(literal.group(1), re.I) if literal else None
check("the trigger's regex can be read out of send()", pattern is not None)
if pattern is not None:
    for reply in ("Pixie-o de Gallo it is. Your order is now complete.", "your order is now complete",
                  "YOUR ORDER IS NOW COMPLETE!", "Your  order is\nnow\tcomplete...", "(Your order is now complete!)"):
        check(f"the regex matches {reply!r}", pattern.search(reply) is not None)
    for reply in ("You did it. Free burritos for life!", "Your order is almost complete. Pick a salsa.",
                  "Your order is complete.", "", "What base would you like?"):
        check(f"the regex misses {reply!r}", pattern.search(reply) is None)

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("\nPASS: the order-complete sentence holds in the persona and the chat page (#1010)")
