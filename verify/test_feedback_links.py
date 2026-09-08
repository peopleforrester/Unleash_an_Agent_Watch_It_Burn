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

# Every surface, not just the guide. The first pass at #364 fixed lab.html and left BurritoBot pointing
# at the long form, which is the tab a student actually sits in for the whole workshop.
WEB = LAB.parent
print("== every student-facing Feedback button goes to /quick ==")
for name, ctx in (("burritbot.html", "Challenges"), ("platform.html", "Tour")):
    src = (WEB / name).read_text()
    m = re.search(r'id="fbbtn"[^>]*href="([^"]+)"', src)
    h = m.group(1) if m else ""
    check(f"{name}: has a Feedback button", bool(h))
    check(f"{name}: goes to /quick, not the long form", "/quick" in h)
    check(f"{name}: carries context={ctx}", f"context={ctx}" in h)
    check(f"{name}: carries a source label", "source=" in h)
    # The same second-? bug lived here too.
    check(f"{name}: identity join is conditional",
          "fb.href+'?'" not in src.replace(" ", ""))

print("== the cluster identity on the links is the friendly name, not the slot id (#383) ==")
# The provisioning app puts cluster=watch-it-burn-attendee-NNN (a slot id) on the lab link. The student
# never sees that string: their address bar and claim page show the friendly name. The lab computes the
# friendly name for its crumb (pretty), and the outbound links must carry THAT, or a feedback note comes
# back tagged with a value a facilitator cannot match to the student in front of them.
check("the outbound identity is the friendly name (pretty), via ident",
      "var ident=(pretty" in SRC)
check("no link param encodes the raw slot-id cluster value",
      "encodeURIComponent(cluster)" not in SRC)
check("the slot id is kept in the crumb tooltip for debugging",
      "clEl.title=cluster" in SRC)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All feedback-link checks passed (all surfaces).")
