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
from html.parser import HTMLParser

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

print("== the re-roll button is label-only, anywhere on the page (#762, #802) ==")


class Markup(HTMLParser):
    """Every start tag's attributes, and the text and child tags inside the id="newwitch" element."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.inside, self.text, self.children = False, "", []

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        self.tags.append((tag, a))
        if self.inside:
            self.children.append(tag)
        if a.get("id") == "newwitch":
            self.inside = True

    def handle_endtag(self, tag):
        if self.inside and tag == "button":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.text += data


mk = Markup()
mk.feed(PAGE)
buttons = [(t, a) for t, a in mk.tags if a.get("id") == "newwitch"]
check("the page has exactly one id=\"newwitch\" element, a button", [t for t, _ in buttons] == ["button"])
check("its attributes are only type, class, id and hidden: no title, aria-label, aria-description or data-tip",
      bool(buttons) and set(buttons[0][1]) == {"type", "class", "id", "hidden"})
check("its only text is exactly 'Get a new witch name', with nothing nested in it",
      mk.text == "Get a new witch name" and mk.children == [])
pointers = [(t, a) for t, a in mk.tags for k, v in a.items()
            if (k in ("for", "list", "popovertarget", "interestfor", "commandfor") or k.startswith("aria-"))
            and "newwitch" in v.split()]
check("no label, aria-describedby, aria-labelledby, aria-details or popover points at it", pointers == [])
css_rules = re.findall(r"([^{}]*newwitch[^{}]*)\{([^}]*)\}", PAGE.split("<script", 1)[0])
check("its CSS adds no text: no ::before, ::after or content", bool(css_rules) and all(
      "::" not in sel and ":before" not in sel and ":after" not in sel and "content" not in body
      for sel, body in css_rules))
script = PAGE[PAGE.find("(function witchName(){"):]
uses = set(re.findall(r"\bbtn\.(\w+)", script))
check("the script only shows it and listens for its click: no title, label or text set on it",
      uses == {"hidden", "addEventListener"} and PAGE.count("'newwitch'") == 1)
check("clicking it re-rolls to another name and replaces the cookie",
      "WITCH_NAME=otherWitch(WITCH_NAME); setWitchCookie(WITCH_NAME);" in PAGE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All witch-name vocabulary checks passed.")
