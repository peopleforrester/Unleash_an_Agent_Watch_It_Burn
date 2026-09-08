# ABOUTME: The eight challenges are colour-coded ROYGBIV + teal so a stuck student can be found by the
# ABOUTME: colour on their screen and it matches the deck (#340). This pins the hues, the order, and that
# ABOUTME: every challenge carries one and nothing else does.
"""Locks the per-challenge lab colours to the deck's order (#340).

Whitney's deck and this lab colour the challenges the same way on purpose: someone stuck on a challenge is
found by the colour projected on their screen, so challenge 3 must be the colour a student would call
yellow in both places. The deck runs a dark ground and the lab a light one, so the hex values differ by
design (the lab darkens them, yellow most of all) and this test does NOT assert the deck's hex. It asserts
the hue *order* is ROYGBIV then teal, that all eight challenge steps carry a colour class and no other step
does, and that the colour drives the number, the header stripe, the collapse chevron and the disclosure
carets so none stays the default purple.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# The value set per challenge, parsed from `.step.cN{--cc:#hex}`.
CC = {int(n): hexv.lower() for n, hexv in re.findall(r"\.step\.c([1-8])\{--cc:(#[0-9a-fA-F]{6})", LAB)}

print("== every challenge 1-8 defines a colour ==")
check("all eight --cc values are present", sorted(CC) == list(range(1, 9)))

print("== each challenge step carries its class, and only the eight do ==")
for n in range(1, 9):
    check(f"challenge {n} step has class c{n}", f'<div class="step c{n}">' in LAB)
# The numbered challenges are the only coloured steps: Section 0 and the trailing steps stay neutral.
coloured = re.findall(r'<div class="step c(\d)">', LAB)
check("exactly eight coloured steps", len(coloured) == 8)
check("no step beyond c8", all(c in "12345678" for c in coloured))


def hue(hexv: str) -> float:
    """Hue angle in degrees, enough to order the rainbow. 0=red, up through violet, teal near cyan."""
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60


print("== the hues run ROYGBIV, and teal is the eighth ==")
# Red < orange < yellow < green < blue < indigo < violet, as increasing hue angle. Violet wraps past 300,
# so red (near 0) is the smallest and violet the largest of the seven; teal sits in the cyan band (~170-190).
h = {n: hue(CC[n]) for n in range(1, 9)}
roygbiv = [h[n] for n in range(1, 8)]
check(f"1-7 increase in hue angle (ROYGBIV): {[round(x) for x in roygbiv]}",
      all(roygbiv[i] < roygbiv[i + 1] for i in range(len(roygbiv) - 1)))
check(f"challenge 1 is red (hue < 20): {round(h[1])}", h[1] < 20)
check(f"challenge 3 is yellow (hue 45-70): {round(h[3])}", 45 <= h[3] <= 70)
check(f"challenge 8 is teal (hue 160-195): {round(h[8])}", 160 <= h[8] <= 195)

print("== the colour drives every mark, so no caret stays purple ==")
check("the number circle reads --cc", ".step.c1 .num" in LAB and "background:var(--cc)" in LAB)
check("the header stripe reads --cc", "border-left:4px solid var(--cc" in LAB)
check("the collapse chevron reads --cc", "color:var(--cc,var(--mid))" in LAB)
check("the disclosure carets read --cc",
      ".step.c1 .ctl>summary" in LAB and ".step.c1 details.hint>summary" in LAB)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All challenge-colour checks passed.")
