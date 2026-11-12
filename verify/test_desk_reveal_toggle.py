# ABOUTME: Holds #1402: every support desk page carries a "Show hidden text" toggle that turns the page mid-grey, where
# ABOUTME: white and black ink both read, so white text written in a ticket can be seen; it changes no stored text.
"""Offline checks for the desk's "Show hidden text" toggle (#1402).

Michael, 2026-11-12: the room should be able to make its own white hidden text on support.burritobot.co and see it.
The form already writes white text; the page and the editor are white, so it was invisible. The real ticket_site.py
runs here, its pages are rendered as the server renders them, and the toggle's colours are checked by contrast ratio.
No cluster, no network.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ticket_site_reveal", REPO / "gitops/ai-layer/ticket_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(label)


def luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


BUTTON = 'id="reveal"'
print("== every desk page carries the toggle, off at load ==")
hc666 = site.find("HC-666")
pages = {"the ticket form": site.desk(), "HC-666's page": site.render([hc666], "HC-666"),
         "the private desk": site.desk(site.desk_banner("support-burritobot-private.burritobot.co"))}
for name, page in pages.items():
    check(f"{name} has one Show hidden text button", page.count(BUTTON) == 1 and ">Show hidden text</button>" in page)
    check(f"{name} starts with the toggle off", "<html class=" not in page and 'aria-pressed="false"' in page)
check("HC-666's page still carries its white paragraph", 'color:#ffffff' in pages["HC-666's page"])

print("== on, the page turns mid-grey, where white and black ink both read ==")
m = re.search(r"html\.reveal,html\.reveal body,html\.reveal \.ed,html\.reveal article,html\.reveal \.you"
              r"\{background:(#[0-9a-f]{6})\}", site._STYLE)
check("one rule turns the page, the editor, each ticket and the visitor box the same colour", m is not None,
      site._STYLE[-400:])
if m:
    grey = m.group(1)
    check(f"white text on {grey} reads at 4.5:1 or better", contrast("#ffffff", grey) >= 4.5,
          f"{contrast('#ffffff', grey):.2f}")
    check(f"black text on {grey} reads at 4.5:1 or better", contrast("#000000", grey) >= 4.5,
          f"{contrast('#000000', grey):.2f}")
check("off, white text on the white page stays hidden", contrast("#ffffff", "#ffffff") == 1.0)
check("the toggle flips only the page's class and its own label",
      "document.documentElement.classList.toggle('reveal')" in site.REVEAL_BUTTON
      and "fetch(" not in site.REVEAL_BUTTON and "innerHTML" not in site.REVEAL_BUTTON)

print("== BurritoBot reads the same ticket ==")
check("HC-666's stored text still holds the hidden instruction", site.ROOM_PAYLOAD in hc666.get("body", "")
      or site.ROOM_PAYLOAD in hc666.get("html", ""))

if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All desk reveal-toggle checks passed.")
