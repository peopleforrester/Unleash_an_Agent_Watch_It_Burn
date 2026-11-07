# ABOUTME: On a phone the BurritoBot title bar is one title row over even button rows, and the chat card's
# ABOUTME: title shares a row with Reset while its tagline takes the full width below (#387).
"""Pins the phone title layout that #387 asked for ("the stacking of the title").

Measured at 390px before the fix: the header was flex-wrap, so Terminal rode up beside "BurritoBot" and the
other three buttons wrapped under it; at 360px Feedback sat alone on a third row. In the chat card the
tagline was squeezed between the avatar and Reset into three or four lines, and Reset broke into "↺" over
"Reset".

This is the CSS half, which runs anywhere. The rendered half, which measures the boxes in Chromium at phone
widths, is verify/test_mobile_titles_e2e.py in the E2E suite. The lab is not a phone surface (decisions.md,
#387) and nothing here touches lab.html.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def media_block(header: str, needle: str) -> str:
    """The body of the `header` media block that contains `needle`, found by brace-matching."""
    idx = 0
    while True:
        h = PAGE.find(header + "{", idx)
        if h == -1:
            return ""
        i = h + len(header) + 1
        depth = 1
        while depth and i < len(PAGE):
            if PAGE[i] == "{":
                depth += 1
            elif PAGE[i] == "}":
                depth -= 1
            i += 1
        body = PAGE[h:i]
        if needle in body:
            return body
        idx = i


print("== the title bar on a phone ==")
bar = media_block("@media(max-width:680px)", "header{display:grid")
check("below 680px the header is a grid, not a wrapping flex row", bool(bar))
check("four even button columns", "grid-template-columns:repeat(4,minmax(0,1fr))" in bar)
check("the title takes the whole first row", "header .brand{grid-column:1/-1}" in bar)
check("the spacer that pushed buttons right is gone on a phone", "header .spacer{display:none}" in bar)
check("buttons drop their left margin so the columns are even", "margin:0" in bar)
check("the narrowest phones get two rows of two",
      "@media(max-width:359px){header{grid-template-columns:repeat(2,minmax(0,1fr))}}" in PAGE)
check("the title never wraps or shrinks",
      "header .brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;"
      "flex-shrink:0;white-space:nowrap}" in PAGE)
check("the header no longer flex-wraps anywhere", "header{flex-wrap:wrap" not in PAGE)

print("== the chat card's title on a phone ==")
card = media_block("@media(max-width:760px)", ".chathead{display:grid")
check("below 760px the chat head is a grid", bool(card))
check("the title wrapper steps aside so its children join the grid", ".chathead .ctitle{display:contents}" in card)
check('the markup carries that wrapper', '<div class="ctitle"><h2>BurritoBot</h2>' in PAGE)
check("avatar, title and Reset share row 1",
      all(r in card for r in (".chathead .avatar{grid-column:1;grid-row:1}",
                              ".chathead h2{grid-column:2;grid-row:1;",
                              ".chathead .reset{grid-column:3;grid-row:1}")))
check("the tagline spans the full width in row 2", ".chathead .sub{grid-column:1/-1;grid-row:2}" in card)
check("Reset never breaks onto two lines", "cursor:pointer;white-space:nowrap}" in PAGE)

print("== the header buttons fit whatever fonts the phone has (#1047) ==")
fit_at = PAGE.find('<script id="hbfit">')
fit = PAGE[fit_at:PAGE.find("</script>", fit_at)] if fit_at >= 0 else ""
check("the page carries its own fit script for the header buttons", bool(fit))
check("it sits right after the header, before event.js and the page's main script",
      0 <= PAGE.find("</header>") < fit_at < PAGE.find('<script src="event.js"></script>'))
check("it measures the four header buttons", "document.querySelectorAll('body>header a.hb')" in fit)
check("a button counts as overflowing when its label is wider than its box",
      "a.scrollWidth>a.clientWidth" in fit)
check("all four step down together, half a pixel at a time, never below 8px",
      "while(px>8 && over()){ px-=0.5; hb.forEach(function(a){ a.style.fontSize=px+'px'; }); }" in fit)
check("each fit starts again from the CSS size", "hb.forEach(function(a){ a.style.fontSize=''; });" in fit)
check("it fits again on a resize", "window.addEventListener('resize', fit);" in fit)
check("the clipped label still ellipsizes rather than spilling, if it ever cannot fit",
      "overflow:hidden;text-overflow:ellipsis}" in bar)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All mobile-title checks passed.")
