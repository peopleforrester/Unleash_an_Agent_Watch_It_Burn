# ABOUTME: On a phone the BurritoBot page is one natural scroll, not a stack of viewport-fraction panes
# ABOUTME: that overlap. The Community cluster is the first thing a room full of phones opens on.
"""Guards the phone layout against the overlap bug (#355).

Measured at 390px before the fix: .chatcol ran 385->945 and .infra ran 445->773, 328px of overlap, which
is the chat text bleeding through the workshop cards in the report. Cause: the desktop layout gives each
pane its own dvh-capped height and internal scroller, and stacked in a column those sum past the screen.

This is a CSS assertion, not a render test, because the render needs a browser. It pins the specific rules
that keep the phone layout flowing: below 760px the document scrolls once, panes are natural height, and no
pane keeps a private viewport-fraction height. A full-page render at 390px is in scratchpad and was checked
by eye; this keeps the rules from being undone.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Isolate the phone block that carries the fix (the one containing order:-1), by brace-matching from its
# @media header, so a dvh height in the desktop rules cannot fail us. A regex over nested CSS braces is not
# worth the cleverness; scan for balance.
start = PAGE.find("@media(max-width:760px)", PAGE.find("order:-1") - 4000)
# find the @media(max-width:760px) whose body contains order:-1
phone = ""
idx = 0
while True:
    h = PAGE.find("@media(max-width:760px){", idx)
    if h == -1:
        break
    i = h + len("@media(max-width:760px){")
    depth = 1
    while depth and i < len(PAGE):
        if PAGE[i] == "{":
            depth += 1
        elif PAGE[i] == "}":
            depth -= 1
        i += 1
    body = PAGE[h:i]
    if "order:-1" in body:
        phone = body
        break
    idx = i
check("there is a phone block that reorders the chat first", bool(phone))

print("== the page scrolls as one on a phone ==")
check("the body stops being a fixed-height clipped box", "html,body{height:auto;overflow:visible}" in phone)
check("the wrap flows instead of clipping", "flex-direction:column;height:auto;overflow:visible" in phone)
check("the three panes are natural height, not dvh-capped",
      ".menu,.chatcol,.infra{width:100%;flex:0 0 auto;height:auto;min-height:0;overflow:visible}" in phone)

print("== no pane keeps a viewport-fraction height that would re-create the overlap ==")
# The bug was dvh/vh heights on stacked panes. The only survivor may be the stream's scroll cap.
caps = re.findall(r"(\d+d?vh)", phone)
check(f"the only viewport unit left is the stream cap ({caps})", caps == ["60vh"])
check("the chat comes first so a phone lands on the conversation", "order:-1" in phone)
check("the composer stays reachable while the stream scrolls", "position:sticky;bottom:0" in phone)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All mobile-layout checks passed.")
