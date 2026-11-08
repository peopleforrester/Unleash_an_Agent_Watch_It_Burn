# ABOUTME: Holds the KubeCon run-of-show's segment 4 (Challenge 3) and its segments-table row to the 2026-11-07 deck
# ABOUTME: (#1098): the slides in order, each cited, no Joker and no desk wall, and the facts that still hold.
"""Segment 4 of `facilitation/kubecon-na-2026-run-of-show.md` follows the 2026-11-07 deck's Challenge 3 (#1098).

rounds-agenticburn#82 replaced the old seven Challenge 3 slides with slides `#/43` to `#/63` by the deck's URL hash,
which the run-of-show counts from 1 as slides 44 to 64; rounds-agenticburn#93 drew the architecture diagram on the
last six. This test holds:

  1. Segment 4's steps, its `- **...**` bullets, cite slides 44 to 64, each slide once, in ascending order.
  2. The beats come in the deck's order: the desk, its QR code, filing a ticket and the admin bot reading it back,
     the challenge, the HC-666 hint, the white text, the deployment, the trace after the attack, LLM01,
     `guard-agency-on` then `guard-input-on` from `/lab`, the retry, least privilege, the input guard, the diagram.
  3. No "Joker" and no desk wall; the deployments page and the prompt wall are the optional views during play; the
     desk is #1077's, filed and looked up by number and never browsed.
  4. The facts that still hold are still stated: Kyverno trusts the internal registry, the room's deployments run
     tiny and scale to zero, the three saved Datadog views, the two fixes and what each does, the double duty.
  5. The segments table's row 4 names the same beats with the same slides, in the same order, and no Joker.

The desk hosts and the `/support` 404 are verify/test_support_desk_named.py's, and segment 3's hand-off is
verify/test_instructor_brief.py's. Each cut on repo text checks its literal first and exits naming it when it is gone
("Tests own their inputs"), and each check is run again on a copy with one beat moved or the old wording put back, so
a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
SEG4 = "### Segment 4:"
SEG5 = "### Segment 5:"
ROW4 = "| 4 | 7 |"
FIRST, LAST = 44, 64

# Each beat of the deck's Challenge 3, as segment 4 words it, in the deck's order (whitespace flattened).
BEATS = [
    ("the desk (slide 44)", "**BurritoBot has a support desk.**"),
    ("its QR code (slide 45)", "\"People can use the support desk too.\" over the desk's QR code"),
    ("filing a ticket (slide 46)", "**\"Let's file a ticket.\" (slide 46).**"),
    ("the admin bot reads it back", "BurritoBot reads the ticket back"),
    ("the challenge (slide 47)", "**Use the support ticket system to get BurritoBot to deploy something.**"),
    ("the HC-666 hint (slide 48)", "Hint: Look up ticket HC-666 on the support desk."),
    ("the white text", "shows the instructions hidden in white text"),
    ("the deployment landing", "show it landing"),
    ("the trace after the attack (slide 49)", "**The trace, after the attack (slide 49).**"),
    ("LLM01 (slide 50)", "**LLM01 (slide 50).**"),
    ("the switch from /lab (slide 51)", "`https://burritobot-private.burritobot.co/lab`"),
    ("guard-agency-on", "The presenter types `guard-agency-on`, then `guard-input-on`"),
    ("the retry (slide 52)", "\"Try your attack again.\""),
    ("least privilege (slides 53 to 56)", "\"This attack was prevented with least privilege.\""),
    ("the input guard (slides 57 and 58)", "\"This attack was prevented with an input guard.\""),
    ("the diagram (slides 59 to 64)", "**The architecture diagram (slides 59 to 64).**"),
]
KEPT = [
    ("Kyverno at Deny admits HC-666's image: it trusts the internal registry",
     "Kyverno is at Deny on both clusters by now and admits it: the policy trusts the internal registry."),
    ("room deployments run tiny and scale to zero", "Room deployments run tiny and scale to zero after five minutes"),
    ("the attack's saved view", "`c3-attack`"),
    ("the fixed saved view", "`c3-fixed`"),
    ("the PII saved view", "`c3-pii` in Trace Explorer"),
    ("least privilege takes create and patch on Deployments and Pods",
     "loses create and patch on Deployments and Pods"),
    ("the input guard withholds a flagged ticket", "which withholds a flagged ticket"),
    ("the double duty", "**The input guard's double duty:**"),
    ("the number-only desk (#1077)", "Nobody can browse tickets"),
    ("the deployments page, optional during play", "Optional during play: the deployments page,"),
    ("the prompt wall, optional during play", "and the prompt wall, `https://prompts.burritobot.co`,"),
]
# The row's beats, each with the slides it cites, in order.
ROW_BEATS = [
    ("the desk", "support desk (44)"), ("its QR code", "the room's first look at it (45)"),
    ("filing a ticket", "\"Let's file a ticket.\" (46)"), ("the challenge", "the challenge sentence (47)"),
    ("optional views", "the deployments page and the prompt wall optional during play"),
    ("the hint", "the hint, HC-666 (48)"), ("the white text", "white text"), ("the trace", "Challenge 3 tab (49)"),
    ("LLM01", "LLM01, Prompt Injection (50)"), ("the switch", "\"Let's turn on least privilege and an input guard.\" (51)"),
    ("the retry", "\"Try your attack again.\" (52)"), ("least privilege", "(53 to 56)"),
    ("the input guard", "(57 and 58)"), ("the diagram", "(59 to 63) and where the input guard is added (64)"),
]
SLIDE_REF = re.compile(r"\(slides? (\d+)(?: (?:to|and) (\d+))?\b")

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def need(text: str, literal: str) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {ROS_PATH}; the segment 4 checks cut on it")


def flat(text: str) -> str:
    return " ".join(text.split())


def parts(ros: str) -> tuple[str, str]:
    """Segment 4's section and the segments table's row 4, each whitespace flattened."""
    for lit in (SEG4, SEG5, "\n" + ROW4):
        need(ros, lit)
    seg = ros.split(SEG4, 1)[1].split(SEG5, 1)[0]
    row = next(ln for ln in ros.splitlines() if ln.startswith(ROW4))
    return flat(seg), flat(row)


def cited_slides(seg: str) -> list[int]:
    """The slides each step cites in its bold lead, `- **... (slide N)` or `(slides N to M)`, expanded, in order."""
    out: list[int] = []
    for lead in re.findall(r"(?:^| )- \*\*(.*?)\*\*", seg):
        m = SLIDE_REF.search(lead)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            out.extend(range(lo, hi + 1))
    return out


def in_order(text: str, phrases: list[tuple[str, str]]) -> list[str]:
    """What is missing or out of order, by label."""
    bad, at = [], -1
    for label, phrase in phrases:
        i = text.find(phrase, at + 1)
        if i < 0:
            bad.append(f"{label}: {phrase!r} missing or before the beat ahead of it")
        else:
            at = i
    return bad


def problems(ros: str) -> dict[str, list[str]]:
    seg, row = parts(ros)
    out: dict[str, list[str]] = {}
    slides = cited_slides(seg)
    out[f"segment 4's steps cite slides {FIRST} to {LAST}, each once, in order"] = (
        [] if slides == list(range(FIRST, LAST + 1)) else [f"cited {slides}"])
    out["segment 4's beats come in the deck's order"] = in_order(seg, BEATS)
    out["segment 4 says no Joker and puts no desk wall on screen"] = [w for w in ("Joker", "joker", "/wall") if w in seg]
    out["segment 4 still states the facts that hold"] = [f"{label}: {p!r}" for label, p in KEPT if p not in seg]
    out["the segments table's row 4 names the same beats and slides, in order, and no Joker"] = (
        in_order(row, ROW_BEATS) + [w for w in ("Joker", "joker", "wall,") if w in row.split("|")[4]])
    return out


ros = ROS_PATH.read_text(encoding="utf-8")
for name, errs in problems(ros).items():
    for e in errs:
        print("  " + e)
    check(name, not errs)

# Each check can fail.
seg_raw = ros.split(SEG4, 1)[1].split(SEG5, 1)[0]
need(seg_raw, "**LLM01 (slide 50).**")
moved = ros.replace("**LLM01 (slide 50).**", "**LLM01 (slide 49).**", 1)
check("a step citing a slide out of order fails the citation check",
      bool(problems(moved)[f"segment 4's steps cite slides {FIRST} to {LAST}, each once, in order"]))
need(seg_raw, "Hint: Look up ticket HC-666 on the support desk.")
swapped = ros.replace(seg_raw, seg_raw.replace("Hint: Look up ticket HC-666 on the support desk.", "", 1)
                      .replace("**LLM01 (slide 50).**", "Hint: Look up ticket HC-666 on the support desk. "
                               "**LLM01 (slide 50).**", 1), 1)
check("the hint moved after LLM01 fails the order check", bool(problems(swapped)["segment 4's beats come in the deck's order"]))
need(seg_raw, "show it landing.")
joker = ros.replace("show it landing.", "show the Joker landing on `https://support.burritobot.co/wall`.", 1)
check("the old Joker wall put back fails the no-Joker check",
      bool(problems(joker)["segment 4 says no Joker and puts no desk wall on screen"]))
need(seg_raw, "the policy trusts the internal registry.")
dropped = ros.replace("the policy trusts the internal registry.", "the policy admits it.", 1)
check("dropping the internal-registry fact fails the kept-facts check",
      bool(problems(dropped)["segment 4 still states the facts that hold"]))
old_row = ("| 4 | 7 | W+M | Challenge 3: the support desk and its Joker wall, the prompt wall optional during play | "
           "Asks BurritoBot about HC-666 | 4, 5, 6, 7 |")
need(ros, "\n" + ROW4)
with_old_row = "\n".join(old_row if ln.startswith(ROW4) else ln for ln in ros.splitlines())
check("the 2026-11-06 row put back fails the row check",
      bool(problems(with_old_row)["the segments table's row 4 names the same beats and slides, in order, and no Joker"]))

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nsegment 4 and its row follow the 2026-11-07 deck's Challenge 3")
