# ABOUTME: On a phone the BurritoBot title bar is one row, brand and buttons, and the chat card's header is one compact
# ABOUTME: row (avatar, title, ⓘ, Reset) over a short witch-name line, with the tagline folded behind ⓘ (#1214, after #387).
"""Pins the phone title layout #1214 asked for, which replaces #387's.

#387 fixed a ragged flex-wrap by giving the title its own row and the buttons an even row under it, and by putting
the chat card's tagline the full width under its title. On a 412px Pixel that made the purple bar about 170px tall
and the card header about 220px, and Michael asked on 2026-11-08 that the conversation get the screen (#1214):
below 760px the bar is one row, the card header one compact row, the tagline folded.

This is the CSS and markup half, which runs anywhere. The rendered halves, which measure the boxes in Chromium, are
verify/test_mobile_titles_e2e.py (the title bars at phone widths, with a wide-font copy) and
verify/test_chat_phone_screen_e2e.py (the whole phone screen with a long reply) in the E2E tools tier, and
verify/test_chat_wide_font_e2e.py runs both, with the chat-pane overlap test, on DejaVu fonts alone (#1253). The lab is not
a phone surface (decisions.md, #387) and nothing here touches lab.html.
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


print("== the title bar on a phone is one row (#1214) ==")
bar = media_block("@media(max-width:760px)", "header.hbicons")
check("below 760px a block sets the bar's phone rules", bool(bar))
check("#387's two-row grid is gone", "header{display:grid" not in PAGE and "@media(max-width:680px)" not in PAGE
      and "@media(max-width:359px)" not in PAGE)
check("the header never flex-wraps", "header{flex-wrap:wrap" not in PAGE)
check("the brand drops its domain on a phone", "header .brand .dom{display:none}" in bar)
check("the markup marks the domain", '<small class="dom"' in PAGE)
check("the title never wraps or shrinks",
      "header .brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;"
      "flex-shrink:0;white-space:nowrap}" in PAGE)
check("in icon mode a button's label is hidden", "header.hbicons a.hb .hbl{display:none}" in bar)
buttons = re.findall(r'<a class="hb" id="(\w+)"[^>]*>(.*?)</a>', PAGE)
# The VTT's four, plus the room's Deployments, Support and Beacon before Feedback (#1347), which ship hidden and show
# only with an event's URLs (verify/test_audience_page_e2e.py runs that).
check("the header buttons are in the markup, in order",
      [b[0] for b in buttons] == ["vttbtn", "bbbtn", "ddbtn", "depbtn", "supbtn", "bcnbtn", "fbbtn"])
check("the room's three ship hidden",
      all(" hidden" in re.search(rf'<a class="hb" id="{b}"[^>]*>', PAGE).group(0) for b in ("depbtn", "supbtn", "bcnbtn")))
for bid, inner in buttons:
    tag = re.search(rf'<a class="hb" id="{bid}"[^>]*>', PAGE).group(0)
    label = re.search(r'<span class="hbl"> ([^<]+)</span>', inner)
    check(f"#{bid}: an aria-hidden icon span, then a label span",
          bool(re.fullmatch(r'<span class="hbi" aria-hidden="true">&#\d+;</span><span class="hbl"> [^<]+</span>', inner)))
    check(f"#{bid}: its aria-label and title name the label, so the icon alone is still named",
          bool(label) and f'aria-label="{label.group(1)}"' in tag and f'title="{label.group(1)}"' in tag)

print("== the header buttons fit whatever fonts the phone has (#1047, #1214) ==")
fit_at = PAGE.find('<script id="hbfit">')
fit = PAGE[fit_at:PAGE.find("</script>", fit_at)] if fit_at >= 0 else ""
check("the page carries its own fit script for the header buttons", bool(fit))
check("it sits right after the header, before event.js and the page's main script",
      0 <= PAGE.find("</header>") < fit_at < PAGE.find('<script src="event.js"></script>'))
check("it measures the header buttons", "document.querySelectorAll('body>header a.hb')" in fit)
check("at any width the bar counts as overflowing when it is wider than its box (#1253)",
      "window.matchMedia('(max-width:760px)')" in fit and "return bar.scrollWidth>bar.clientWidth ||" in fit)
check("a button counts as overflowing when its label is wider than its box", "a.scrollWidth>a.clientWidth" in fit)
check("or when it ends past the bar's right padding edge, which the bar's scrollWidth does not count (#1361)",
      "var edge=bar.getBoundingClientRect().right-parseFloat(getComputedStyle(bar).paddingRight)+0.5;" in fit
      and "a.getBoundingClientRect().right>edge" in fit)
steps = ["if(over()) bar.classList.add('hbnodom');", "if(phone.matches && over()) bar.classList.add('hbicons');",
         "if(over()) bar.classList.add('hbtight');",
         "while(px>8 && over()){ px-=0.5; hb.forEach(function(a){ a.style.fontSize=px+'px'; }); }",
         "bar.classList.add('hbmin');"]
at = [fit.find(s) for s in steps]
check("while it overflows the bar drops its domain, then on a phone switches to icons, then closes its gaps, then "
      "all the buttons step down together, half a pixel at a time, never below 8px, then halve their padding, in that "
      "order (#1253, #1347)",
      -1 not in at and at == sorted(at))
check("those classes drop the domain and close the bar's padding and gaps",
      "header.hbnodom .brand .dom{display:none}" in PAGE
      and "header.hbtight{padding-left:8px;padding-right:8px;gap:4px}" in PAGE
      and "header.hbtight a.hb{margin-left:2px;padding-left:6px;padding-right:6px}" in PAGE)
check("the last step halves the buttons' padding, and only a bar still over at 8px takes it (#1347)",
      "header.hbmin a.hb{margin-left:1px;padding-left:3px;padding-right:3px}" in PAGE
      and "if(!over()) return;\n        // Halved padding" in fit)
check("after it the buttons step back up, never past the CSS size, to the largest that fits",
      "while(px<css){ px+=0.5;" in fit and "if(over()){ px-=0.5;" in fit)
check("each fit starts again from the labels and the CSS size",
      "bar.classList.remove('hbnodom','hbicons','hbtight','hbmin');" in fit
      and "hb.forEach(function(a){ a.style.fontSize=''; });" in fit)
check("it fits again on a resize", "window.addEventListener('resize', fitAll);" in fit)
check("and once the main script has hidden the public bot's buttons and shown the witch name",
      "document.addEventListener('DOMContentLoaded', fitAll);" in fit and "function fitAll(){ fit(); fitWitchLine(); }" in fit)

print("== the witch line stays one line on a wide font where it can (#1253) ==")
check("on a phone a wrapped witch line steps the name and its button down together, never below 9px",
      "if(!phone.matches || name.hidden || roll.hidden) return;" in fit
      and "while(px>9 && wraps()){ px-=0.5; name.style.fontSize=px+'px'; roll.style.fontSize=(px-gap)+'px'; }" in fit)
check("a line that still wraps at 9px goes back to the CSS size", "if(wraps()){ name.style.fontSize=''; "
      "roll.style.fontSize=''; }" in fit)
check("it fits again after a re-roll", "e.target.closest('.chathead .newwitch')) fitWitchLine();" in fit)
check("it sets only the size on the re-roll button, never its text, title or label (#762)",
      set(re.findall(r"\broll\.(\w+(?:\.\w+)?)", fit)) == {"style.fontSize", "hidden", "getBoundingClientRect"})

print("== the chat card's header on a phone is one compact row (#1214) ==")
card = media_block("@media(max-width:760px)", ".chathead{display:grid")
check("below 760px the chat head is a grid", bool(card))
check("the title wrapper steps aside so its children join the grid", ".chathead .ctitle{display:contents}" in card)
check("the markup carries that wrapper", '<div class="ctitle"><h2>BurritoBot</h2>' in PAGE)
check("avatar, title, ⓘ and Reset share row 1",
      all(r in card for r in (".chathead .avatar{grid-column:1;grid-row:1;",
                              ".chathead h2{grid-column:2;grid-row:1}",
                              ".chathead .about{grid-column:3;grid-row:1;",
                              ".chathead .reset{grid-column:4;grid-row:1;")))
check("the witch line is row 2, the card's full width", ".chathead .wline{grid-column:1/-1;grid-row:2;" in card)
check("the markup wraps the witch name, its re-roll button and the deployments link in that line",
      re.search(r'<span class="wline"><a class="witch" id="witch"[^>]*></a><button[^>]*id="newwitch"[^>]*>[^<]*</button>'
                r'<a class="mydeploys" id="mydeploys"[^>]*>[^<]*</a></span>', PAGE) is not None)
check("the tagline is folded on a phone", ".chathead .sub{display:none}" in card)
check("and shows, under the witch line, once ⓘ opens it", ".chathead.open .sub{grid-column:1/-1;grid-row:3;display:block" in card)
about = re.search(r'<button type="button" class="about" id="aboutbtn"[^>]*>', PAGE)
about = about.group(0) if about else ""
check("the ⓘ toggle is a button that controls the tagline and says whether it is open",
      'aria-expanded="false"' in about and 'aria-controls="chatsub"' in about and '<div class="sub" id="chatsub">' in PAGE)
check("tapping it toggles .open on the card header and sets aria-expanded to match",
      "this.setAttribute('aria-expanded',String(this.parentNode.classList.toggle('open')))" in about)
check("above 760px there is no ⓘ toggle, since the tagline always shows",
      re.search(r"\n  \.chathead \.about\{display:none;", PAGE) is not None)
check("Reset never breaks onto two lines", "cursor:pointer;white-space:nowrap}" in PAGE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All mobile-title checks passed.")
