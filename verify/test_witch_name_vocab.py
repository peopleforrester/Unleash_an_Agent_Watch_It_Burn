# ABOUTME: The chat page assigns every visitor a witch name on first visit from the SAME vocabulary the
# ABOUTME: support desk uses, sets the shared cookie, carries the name to the bot, and offers a re-roll (#762).
"""Pins #762: the auto-assigned witch name.

The chat page gives every visitor a name on their first visit, from the desk's vocabulary, so the desk, /me
and the projected wall all find the person's Joker under one name. The JS copy of the vocabulary is mirrored
from ticket_site.py; this test is what keeps the two from drifting, because a name from any other vocabulary
is replaced by the desk and the person's Joker would never show on the wall.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PY = (REPO / "gitops/ai-layer/ticket_site.py").read_text(encoding="utf-8")
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def py_tuple(src: str, name: str) -> list[str]:
    m = re.search(rf"{name}\s*=\s*(\([^)]*\))", src, flags=re.S)
    return list(ast.literal_eval(m.group(1))) if m else []


def js_array(src: str, name: str) -> list[str]:
    m = re.search(rf"{name}\s*=\s*(\[.*?\]);", src, flags=re.S)
    if not m:
        return []
    return ast.literal_eval(m.group(1).replace("\n", " "))


print("== the chat page's vocabulary is exactly the desk's ==")
py_first, py_creatures = py_tuple(PY, "FIRST"), py_tuple(PY, "CREATURES")
js_first, js_creatures = js_array(PAGE, "WITCH_FIRST"), js_array(PAGE, "WITCH_CREATURES")
check("the desk's FIRST parses", len(py_first) > 0)
check("the desk's CREATURES parses", len(py_creatures) > 0)
check("WITCH_FIRST matches the desk's FIRST exactly (order included)", js_first == py_first)
check("WITCH_CREATURES matches the desk's CREATURES exactly (order included)", js_creatures == py_creatures)

print("== a name is assigned on first visit and shares the desk's cookie ==")
check("only a vocabulary name is kept from the cookie (mirrors name_from_slug)",
      "witchFromSlug" in PAGE and "WITCH_FIRST.indexOf" in PAGE and "WITCH_CREATURES.indexOf" in PAGE)
check("a first visit with no valid cookie assigns a name", "name=randWitch(); setWitchCookie(name);" in PAGE)
check("the cookie is set on .burritobot.co so the desk and wall share it",
      "Domain=.burritobot.co" in PAGE and 'document.cookie="wib_witch="' in PAGE)
check("the cookie carries the desk's 48-hour Max-Age", "Max-Age=172800" in PAGE)
check("the name shows as plain text in the header", "el.textContent='\\uD83E\\uDDD9 You are '+name" in PAGE)

print("== the visitor's name reaches the bot without the visitor typing it ==")
check("each /chat call carries the witch name in its body",
      "witch:WITCH_NAME" in PAGE and re.search(r"body:JSON\.stringify\(\{prompt:v,session:getSession\(\),witch:WITCH_NAME\}\)", PAGE) is not None)

print("== the re-roll button is label-only (#762) ==")
m = re.search(r'<button[^>]*id="newwitch"[^>]*>([^<]*)</button>', PAGE)
btn_tag = re.search(r'<button[^>]*id="newwitch"[^>]*>', PAGE)
check("the button exists", m is not None)
check("its label is exactly 'Get a new witch name'", (m.group(1) if m else "") == "Get a new witch name")
check("it has no title attribute (no tooltip or explanation)",
      btn_tag is not None and "title=" not in btn_tag.group(0))
check("it has no aria-label (the label is the only text)",
      btn_tag is not None and "aria-label" not in btn_tag.group(0))
check("clicking it re-rolls and replaces the cookie",
      "WITCH_NAME=randWitch(); setWitchCookie(WITCH_NAME);" in PAGE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All witch-name vocabulary checks passed.")
