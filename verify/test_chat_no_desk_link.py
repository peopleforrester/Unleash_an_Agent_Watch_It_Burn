# ABOUTME: The BurritoBot chat page shows the witch name as plain text (#763) and links to the support desk from one
# ABOUTME: place alone, the header's Support button, whose URL is event.js's supportUrl (#1347).
"""Pins #763's plain witch name, and #1347's one way to the desk from the chat page.

The header used to link to the desk's `/` when there was no `wib_witch` cookie and to the desk's `/me`
("see your Jokers") when there was one. Both reached Challenge 3's surface before the presenters introduced
it, so #763 took every desk link off the page and the name shows as plain text only.

#1347 (Michael, 2026-11-11: "Why wouldn't we have buttons for that at the upper right-hand side so they can do it
themselves?") puts the desk back as one header button, Support, beside Deployments and Beacon. The page names no
desk host of its own: the button ships hidden with no href, and the page's init shows it with event.js's supportUrl,
so an event that sets none, the 2-hour workshop, still has no desk link. The witch name stays plain text, and the
old links (the name as a link, "see your Jokers", /me) stay gone.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
EVENT = (REPO / "gitops/ai-layer/web/event.js").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Comments record WHY the links were removed (they name the old desk URL and link text), so strip HTML
# comments, CSS/JS block comments and full-line JS comments before scanning for a live link. A `https://`
# inside a code string is never a full-line comment, so it is left in scope.
VISIBLE = re.sub(r"<!--.*?-->", "", PAGE, flags=re.S)
VISIBLE = re.sub(r"/\*.*?\*/", "", VISIBLE, flags=re.S)
VISIBLE = re.sub(r"(?m)^\s*//.*$", "", VISIBLE)

print("== the chat page names no desk host of its own ==")
check("no link to any support*.burritobot.co host in the page", not re.search(r"support[\w-]*\.burritobot\.co", VISIBLE))
check("nothing builds a support-<cluster> desk URL", "support-" not in VISIBLE)
check("no '/me' deployments link", "'/me'" not in VISIBLE and '"/me"' not in VISIBLE and "+'/me'" not in VISIBLE)
check("the old 'see your Jokers' link text is gone", "see your Jokers" not in VISIBLE)
check("the old 'Get your witch name at the support desk' link text is gone",
      "Get your witch name at the support desk" not in VISIBLE)

print("== the desk is one header button, Support, shown only with the event's supportUrl (#1347) ==")
tag = re.search(r'<a class="hb" id="supbtn"[^>]*>', PAGE)
check("the header has a Support button", tag is not None and 'aria-label="Support"' in tag.group(0)
      and PAGE.find('id="supbtn"') < PAGE.find("</header>"))
check("it ships hidden, with no href of its own", tag is not None and " hidden" in tag.group(0)
      and "href=" not in tag.group(0))
check("it is the only element that names the support desk: the init's loop key and its three reads of the event",
      len(re.findall(r'id="supbtn"', PAGE)) == 1 and VISIBLE.count("supportUrl") == 4
      and VISIBLE.count("['supbtn','supportUrl']") == 1 and VISIBLE.count("ev.supportUrl") == 3)
init = PAGE[PAGE.find("(function init(){"):PAGE.find("loadSaved();", PAGE.find("(function init(){"))]
check("the page's init reads the event's supportUrl, and only an https one",
      "['supbtn','supportUrl']" in init and r"/^https:\/\//.test(u)" in init
      and r"/^https:\/\//.test(ev.supportUrl)" in init)
m = re.search(r'^\s*supportUrl:\s*"([^"]*)"', EVENT, re.M)
check("event.js sends it to the one desk both bots read (#1145)", m is not None
      and m.group(1) == "https://support.burritobot.co/")
print("== Support waits for guardrails-k8s-on (#1384, #1386; Whitney 2026-11-12: the desk is a reveal) ==")
check("the init gives Support only the event's desk link and never shows it",
      "p[0]!=='supbtn'" in init and "window.wibSupportUrl" in init)
ac = PAGE[PAGE.find("function applyControls(c){"):PAGE.find("// Back-compat alias")]
check("applyControls shows it only while /controls measures infra.kyverno on, with the event's link",
      "c.infra && c.infra.kyverno === true" in ac and "window.wibSupportUrl &&" in ac)
check("it hides with the hidden attribute, never visibility or opacity, so it leaves no gap (#1389)",
      "sup.hidden = !showSup" in ac and "visibility" not in ac and "opacity" not in ac)
check("the header fit re-runs on the page's own event, fired only when Support changes (#1389)",
      "if(sup.hidden === showSup)" in ac and "new Event('wib-header-buttons')" in ac
      and "document.addEventListener('wib-header-buttons', fitAll);" in PAGE)

print("== no header button leads back to the chat page itself (#1385) ==")
# The BurritoBot button went to `/`, this page, and init rewrote it to `/?cluster=..`; Whitney had it taken off on
# 2026-11-12. verify/test_chat_no_burritobot_button.py holds the button by its id; this holds any button by its href.
hrefs = re.findall(r'<a class="hb" id="(\w+)"[^>]*\shref="([^"]*)"', PAGE[:PAGE.find("</header>")])
check("no header button's href is the chat page's own '/' or '/?..'",
      bool(hrefs) and not [h for h in hrefs if h[1] == "/" or h[1].startswith("/?")])
check("and init builds no '/?' link", "'/?'" not in VISIBLE)

print("== the witch name is plain text, set by neither cookie state to a link ==")
m = re.search(r"function witchName\(\)\{.*?\n  \}\)\(\);", PAGE, flags=re.S)
block = m.group(0) if m else ""
check("the witchName block is found", bool(block))
check("witchName assigns no href", ".href=" not in block and "setAttribute('href'" not in block)
check("witchName names no desk host", "burritobot.co" not in block or "support" not in block)
check("witchName shows the name via textContent", "el.textContent" in block and "You are" in block)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All chat-page desk-link checks passed: a plain witch name, and the desk only from the Support button.")
