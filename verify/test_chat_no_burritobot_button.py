# ABOUTME: The BurritoBot chat page carries no BurritoBot button (#bbbtn), which linked to the page it sits on (#1385),
# ABOUTME: while the lab and platform pages keep theirs, since from those pages it goes somewhere.
"""Pins #1385 (Whitney, 2026-11-12: "a button to get to BurritoBot, which is silly").

burritbot.html had the VTT's header buttons, BurritoBot among them, and its BurritoBot button went to `/`, the chat
page itself, with init rewriting that href to carry the cluster and user. #1385 took the button and the init line
off the chat page alone. lab.html and platform.html keep their BurritoBot buttons, which open the chat.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "gitops/ai-layer/web"
CHAT = (WEB / "burritbot.html").read_text(encoding="utf-8")
LAB = (WEB / "lab.html").read_text(encoding="utf-8")
PLATFORM = (WEB / "platform.html").read_text(encoding="utf-8")
# An element whose id attribute is bbbtn, quoted either way, on any tag.
ID_BBBTN = re.compile(r"<[a-zA-Z][^>]*\sid\s*=\s*[\"']bbbtn[\"'][^>]*>")

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


print("== the chat page has no BurritoBot button (#1385) ==")
found = ID_BBBTN.findall(CHAT)
check("burritbot.html carries no element with id bbbtn", not found, f"found {found}")
check("and no script looks one up or sets its href", "bbbtn" not in re.sub(r"<!--.*?-->", "", CHAT, flags=re.S),
      "burritbot.html still names bbbtn outside a comment")
header = CHAT[CHAT.find("<header>"):CHAT.find("</header>")]
check("the chat page's header is found", bool(header) and CHAT.find("<header>") >= 0)
check("no header button is labelled BurritoBot", 'aria-label="BurritoBot"' not in header
      and "> BurritoBot</span></a>" not in header)

print("== the lab and platform pages keep theirs ==")
for name, page in (("lab.html", LAB), ("platform.html", PLATFORM)):
    tags = [t for t in ID_BBBTN.findall(page) if t.startswith('<a class="hb"')]
    check(f"{name} has one BurritoBot header button", len(tags) == 1, f"found {tags}")
    check(f"{name}'s button goes to the chat page", bool(tags) and 'href="/"' in tags[0], f"found {tags}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All BurritoBot-button checks passed: none on the chat page, one each on the lab and platform pages.")
