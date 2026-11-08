# ABOUTME: On a phone the BurritoBot page is one natural scroll, not a stack of viewport-fraction panes
# ABOUTME: that overlap. The Community cluster is the first thing a room full of phones opens on.
"""Guards the phone layout against the overlap bug (#355).

Measured at 390px before the fix: .chatcol ran 385->945 and .infra ran 445->773, 328px of overlap, which
is the chat text bleeding through the workshop cards in the report. Cause: the desktop layout gives each
pane its own dvh-capped height and internal scroller, and stacked in a column those sum past the screen.

This is a CSS assertion; the render is verify/test_chat_pane_overlap_e2e.py in the E2E tools tier (#1213).
It pins the specific rules that keep the stacked layout flowing: at 980px and under (760px until #1213) the
document scrolls once, panes are natural height, and no pane keeps a private viewport-fraction height; this
keeps the rules from being undone.
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


# Isolate the block that carries the fix (the one containing order:-1), by brace-matching from its @media
# header, so a dvh height in the desktop rules cannot fail us. A regex over nested CSS braces is not worth the
# cleverness; scan for balance. It starts at 980px since #1213, where the panes first stack: from 761 to 980px
# they used to keep their desktop dvh heights and overlap on a Pixel Fold.
STACKED = "@media(max-width:980px){"


def blocks(header: str) -> list[str]:
    """Every @media block whose header is exactly `header`, brace-matched."""
    out, idx = [], 0
    while (h := PAGE.find(header, idx)) != -1:
        i, depth = h + len(header), 1
        while depth and i < len(PAGE):
            depth += {"{": 1, "}": -1}.get(PAGE[i], 0)
            i += 1
        out.append(PAGE[h:i])
        idx = i
    return out


phone = next((b for b in blocks(STACKED) if "order:-1" in b), "")
check(f"there is a {STACKED} block that reorders the chat first", bool(phone))

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

print("== no other block at 980px or under gives a stacked pane a viewport height (#1213) ==")
# The 761-980px band failed because a second 980px block set .menu{max-height:34dvh} and
# .chatcol{height:min(66dvh,620px)}. Any narrow block may size the stream or a strip, but not a pane.
narrow = [b for hdr in ("@media(max-width:980px){", "@media(max-width:760px){", "@media(max-width:640px){")
          for b in blocks(hdr) if b != phone]
pane_vh = [rule for b in narrow for rule in re.findall(r"\.(?:menu|chatcol|infra|wrap|store)\{[^}]*\d+d?vh[^}]*\}", b)]
check(f"no narrow block sizes .menu, .chatcol, .infra, .wrap or .store to the viewport ({pane_vh})", not pane_vh)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All mobile-layout checks passed.")
