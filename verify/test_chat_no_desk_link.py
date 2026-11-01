# ABOUTME: The BurritoBot chat page shows the witch name as plain text and links to the support desk from
# ABOUTME: nowhere (#763): a header link gave away Challenge 3, and "see your Jokers" named a Joker too early.
"""Pins #763: no support-desk link on the chat page, in either cookie state.

The header used to link to the desk's `/` when there was no `wib_witch` cookie and to the desk's `/me`
("see your Jokers") when there was one. Both reached Challenge 3's surface before the presenters introduced
it. The name now shows as plain text only. People reach the desk by asking the bot or from the slide.
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


# Comments record WHY the links were removed (they name the old desk URL and link text), so strip HTML
# comments, CSS/JS block comments and full-line JS comments before scanning for a live link. A `https://`
# inside a code string is never a full-line comment, so it is left in scope.
VISIBLE = re.sub(r"<!--.*?-->", "", PAGE, flags=re.S)
VISIBLE = re.sub(r"/\*.*?\*/", "", VISIBLE, flags=re.S)
VISIBLE = re.sub(r"(?m)^\s*//.*$", "", VISIBLE)

print("== the chat page links to the support desk from nowhere ==")
check("no link to any support*.burritobot.co host", not re.search(r"support[\w-]*\.burritobot\.co", VISIBLE))
check("nothing builds a support-<cluster> desk URL", "support-" not in VISIBLE)
check("no '/me' deployments link", "'/me'" not in VISIBLE and '"/me"' not in VISIBLE and "+'/me'" not in VISIBLE)
check("the old 'see your Jokers' link text is gone", "see your Jokers" not in VISIBLE)
check("the old 'Get your witch name at the support desk' link text is gone",
      "Get your witch name at the support desk" not in VISIBLE)

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
print("All chat-page no-desk-link checks passed.")
