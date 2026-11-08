# ABOUTME: The private (administrator) terminal page /lab carries a red banner on burritobot-private. only, in the
# ABOUTME: chat page's .combanner look, outside every ttyd iframe, with the terminal still filling its pane (#1180).
"""Pins the /lab private banner's markup, look and placement (#1180).

The same lab.html ships to every cluster, so the host decides at load time, as the chat page's private banner
does (#761). This offline check reads the page: the banner element, its text, that it starts hidden, its style
against the chat page's .combanner, and where it sits (a flex row of the terminal column, never inside a ttyd
iframe or the panes the iframes fill). What the page's script does with a given hostname is run under node in
test_lab_private_banner_e2e.py, in the tools tier.
"""
from __future__ import annotations

import html.parser
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB_PATH = REPO / "gitops/ai-layer/web/lab.html"
BB_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
LAB = LAB_PATH.read_text(encoding="utf-8")
BB = BB_PATH.read_text(encoding="utf-8")
TEXT = "This is the private (administrator) terminal page."

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def rule(page: str, path: pathlib.Path, selector: str) -> dict[str, str]:
    """The declarations of every CSS rule whose selector is exactly `selector`, later rules winning as in the
    cascade, or exit naming the selector and the file when there is none."""
    found = re.findall(r"(?m)^\s*" + re.escape(selector) + r"\{([^}]*)\}", page)
    if not found:
        print(f"FAILED: no CSS rule '{selector}{{' in {path.relative_to(REPO)}")
        sys.exit(1)
    out: dict[str, str] = {}
    for body in found:
        for decl in body.split(";"):
            if ":" in decl:
                k, v = decl.split(":", 1)
                out[k.strip()] = v.strip()
    return out


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Walk(html.parser.HTMLParser):
    """Records the open-element path at the banner, and the order of the terminal column's direct children."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict]] = []
        self.banner_path: list[tuple[str, dict]] | None = None
        self.banner_attrs: dict | None = None
        self.banner_text = ""
        self.in_banner = False
        self.termcol_children: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.stack and "termcol" in (self.stack[-1][1].get("class") or "").split():
            self.termcol_children.append(a.get("id") or a.get("class") or tag)
        if a.get("id") == "privatebanner":
            self.banner_path = list(self.stack)
            self.banner_attrs = a
            self.in_banner = True
        if tag not in VOID:
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            if self.stack[-1][1].get("id") == "privatebanner":
                self.in_banner = False
            self.stack.pop()

    def handle_data(self, data):
        if self.in_banner:
            self.banner_text += data


w = Walk()
w.feed(LAB)

print("== the banner is on /lab, hidden until the host says otherwise ==")
check("lab.html has exactly one #privatebanner", LAB.count('id="privatebanner"') == 1)
check("it is a .combanner", w.banner_attrs is not None and "combanner" in (w.banner_attrs.get("class") or "").split())
check("it starts hidden, so nothing flashes on a host that should not show it",
      w.banner_attrs is not None and "hidden" in w.banner_attrs)
check(f"it reads exactly '{TEXT}'", w.banner_text.strip() == TEXT, repr(w.banner_text.strip()))

print("== it wears the chat page's .combanner look ==")
lab_css = rule(LAB, LAB_PATH, ".combanner")
bb_css = rule(BB, BB_PATH, ".combanner")
check("bold white on #C62222", lab_css.get("color") == "#fff" and lab_css.get("background") == "#C62222"
      and lab_css.get("font-weight") == "800", str(lab_css))
check("with the #8E1414 border and rounded corners",
      lab_css.get("border") == "1px solid #8E1414" and lab_css.get("border-radius") == "10px", str(lab_css))
for k in ("font-weight", "font-size", "line-height", "color", "background", "border", "border-radius", "padding"):
    check(f"{k} matches the chat page's .combanner", lab_css.get(k) == bb_css.get(k),
          f"lab {lab_css.get(k)!r}, chat {bb_css.get(k)!r}")
check("it sets no display, so the hidden attribute still hides it", "display" not in lab_css, str(lab_css))

print("== it sits around the terminal, never inside it ==")
path = w.banner_path or []
classes = [set((a.get("class") or "").split()) for _, a in path]
check("it is a direct child of the terminal column (.termcol)", bool(classes) and "termcol" in classes[-1],
      str([t for t, _ in path]))
check("no iframe encloses it", all(t != "iframe" for t, _ in path))
check("it is not inside .termpanes, where the ttyd iframes fill the pane",
      all("termpanes" not in c for c in classes))
check("it comes before the terminal tabs, at the top of the column",
      w.termcol_children[:1] == ["privatebanner"] and "termtabs" in w.termcol_children, str(w.termcol_children))

print("== the layout gives it room, so the terminal still fills its pane ==")
check("the terminal column is a flex column", rule(LAB, LAB_PATH, ".termcol").get("flex-direction") == "column")
check("the banner takes only its own height (flex:0 0 auto)", lab_css.get("flex") == "0 0 auto", str(lab_css))
panes = rule(LAB, LAB_PATH, ".termpanes")
check("the panes take the rest (flex:1, min-height:0)", panes.get("flex") == "1" and panes.get("min-height") == "0",
      str(panes))

print("== the host decides, and the community marking is untouched ==")
check("markPrivate runs on the address-bar hostname", "markPrivate(location.hostname||'');" in LAB)
check("the trigger is the burritobot-private. host",
      re.search(r"/\^burritobot-private\\\.\/i\.test\(host\)", LAB) is not None)
check("markCommunity still marks attackme. as the burn profile",
      "if(typeof host==='string' && /^attackme\\./i.test(host)) "
      "document.documentElement.setAttribute('data-profile','burn');" in LAB)
check("the page hardcodes no cluster name for the banner",
      "watch-it-burn-private" not in LAB[LAB.index('id="privatebanner"'):LAB.index("markPrivate(location")])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The /lab private banner is in place, in the right look, outside the terminal.")
