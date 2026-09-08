# ABOUTME: The lab's two feedback links point at different surfaces, because a student who taps Feedback
# ABOUTME: mid-challenge must not be handed the long end-of-workshop form (#364).
"""Pins the two feedback links apart.

Whitney caught this by eye during her walkthrough: "The feedback form that appears when you click on the
top right button is still the long one. This should be different than the feedback form linked at the
bottom of the lab." Both hrefs were byte-identical, so the button a student taps at minute five served
the pacing-and-difficulty questionnaire, and the cost of that is measurable rather than cosmetic. The
same button drew zero responses at a previous event.

The top bar goes to /quick, which stays on the page after a send so a thought can be dropped without
losing your place. Challenge 9 keeps the long form. These are offline string checks: no network.
"""
from __future__ import annotations

import pathlib
import re
import sys

LAB = pathlib.Path(__file__).resolve().parent.parent / "gitops/ai-layer/web/lab.html"
SRC = LAB.read_text()

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def href(element_id: str) -> str:
    m = re.search(rf'id="{element_id}"[^>]*href="([^"]+)"', SRC)
    return m.group(1) if m else ""


top, long_form = href("fbbtn"), href("fblink2")

print("== the two surfaces are not the same form ==")
check("the top-bar Feedback button has an href", bool(top))
check("Challenge 9's link has an href", bool(long_form))
check("they are NOT identical (the bug Whitney found)", top != long_form)
check("the top bar goes to the short /quick surface", "/quick" in top)
check("Challenge 9 keeps the long form (no /quick)", "/quick" not in long_form)

print("== the top-bar link carries what segments a note ==")
# The visible context picker is being removed from /quick, so the URL is the only thing that can say
# where in the workshop a note came from.
check("context is carried in the URL", "context=Challenges" in top)
check("source is carried in the URL", "source=lab" in top)

print("== the identity join cannot produce a second ? ==")
# lab.html appends cluster/user to both links. Appending a bare '?' to an href that already has one
# drops the identity silently rather than failing, which is why the join is conditional.
check("the join helper exists", "function addq(el)" in SRC)
check("it chooses & when a query string is already present",
      "indexOf('?')>=0?'&':'?'" in SRC)
check("neither link is joined with a hardcoded '?'",
      "fb.href+'?'" not in SRC and "fb2.href+'?'" not in SRC)

print("== page= tracks the challenge the student is on ==")
check("an IntersectionObserver keeps page= current", "IntersectionObserver" in SRC)
check("the challenge number comes from the step's own cN class",
      r"match(/\bc(\d+)\b/)" in SRC)

print("== Challenge 9 states the thank-you the form actually offers ==")
# The long form's checkbox says two hours, so the lab copy has to say two hours as well.
check("the cluster extension is named as two hours", "two more hours on your cluster" in SRC)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All feedback-link checks passed.")
