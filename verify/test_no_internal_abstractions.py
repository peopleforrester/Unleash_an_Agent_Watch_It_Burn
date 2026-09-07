# ABOUTME: Nothing a student reads may name an abstraction that belongs to us: rounds, the guardrail
# ABOUTME: on/off model, spend caps they cannot act on, or the terminal as a "source of truth".
"""Keeps our mental model out of the student's pane (#298).

Whitney opened BurritoBot as a first-time student and found three of our own inventions staring back at
her: a round selector offering "Round set to no guardrails for reference", a banner asserting that all
guardrails were on with no way to tell whether that was her cluster or a default, and a line telling her
the terminal was the source of truth. Her verdict was flat: *"They don't know about 'Rounds' and they
don't know about our 'guardrails' abstraction."*

All of it is gone. This exists so it cannot come back, and rounds especially: the nomenclature was retired
across the fleet (#290, #291) and any student-facing text that resurrects it would be not merely confusing
but wrong. The vocabulary is cheap to reintroduce by accident, in a stray label or a placeholder, which is
exactly what a text assertion is good at catching.

Comments are stripped first. A comment explaining why a phrase was removed is documentation, not something
a student sees, and a check that could not tell the two apart would fail on its own rationale.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "gitops/ai-layer/web"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def visible(path: pathlib.Path) -> str:
    """What a student can actually read: markup minus every kind of comment.

    Three comment styles hide in these files and all three are documentation, not content. HTML comments
    carry the design rationale. The pages also embed <script> and <style>, so `//` and `/* */` comments
    live in the same file. A first version of this check stripped only HTML comments and reported three
    pages as naming a round, when every hit was a JS comment explaining why the round handling exists.
    """
    t = path.read_text(encoding="utf-8")
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
    t = re.sub(r"^\s*//.*$", "", t, flags=re.M)
    return t


# Only the two pages a STUDENT opens. brief.html is the presenter's, and diagram/links/platform are
# instructor and reference surfaces. They are not exempt from being stale, but they are a different
# audience and a different issue: the presenter is allowed to know how the machine works.
STUDENT_PAGES = ("lab.html", "burritbot.html")
PAGES = {n: visible(WEB / n) for n in STUDENT_PAGES}

# Each entry: the phrase, and why a student must never meet it.
BANNED = [
    ("Round set to", "a round selector; rounds are ours and are retired"),
    ("Choose Round", "same"),
    ("no guardrails for reference", "describes a round, not their cluster"),
    ("Installed guardrails are lit", "explains our badge model instead of showing state"),
    ("source of truth", "the terminal is not where a student is working"),
    ("Lost?", "points at one recovery for a hundred ways to be lost"),
]

print("== no student-facing page names an internal abstraction ==")
for phrase, why in BANNED:
    hit = [name for name, text in PAGES.items() if phrase in text]
    check(f"{phrase!r} appears nowhere ({why})", not hit)

# "Round" as a bare word is too common to ban outright (rounded corners, a round trip), so target the
# shapes that would actually reach a student.
print("== the round vocabulary is gone in every shape ==")
ROUND_SHAPES = re.compile(r"\b(round\s*[123]\b|round-[123]\b|Round\s+(set|selector|[123])\b)", re.I)
for name, text in PAGES.items():
    m = ROUND_SHAPES.search(text)
    check(f"{name} names no numbered round" + (f" (found {m.group(0)!r})" if m else ""), m is None)

print("== the guardrail panel states the student's own cluster, and starts empty ==")
bot = PAGES.get("burritbot.html", "")
check("the panel is labelled as the workshop's, not the shop's", "Workshop Panel" in bot)
check("it says guardrails appear once installed", "Guardrails will appear here when you install them" in bot)
# Grayed-out placeholders give away the punchline: a student would see the whole list before earning any.
check("it does not preannounce the controls they have not installed",
      "Installed guardrails are lit" not in bot)

print("== the spend cap a student cannot act on is gone ==")
# Whitney: "what the hell is the spend cap? It's even more confusing when it says infra backstop, not a
# guardrail." The cluster backstop still exists; it just stopped being shown to someone who cannot change it.
for phrase in ("Spend cap", "spend cap", "infra backstop"):
    hit = [n for n, t in PAGES.items() if phrase.lower() in t.lower()]
    check(f"{phrase!r} is not in the student pane", not hit)
check("tokens and cost, which are legible, are still shown", "Tokens" in bot and "Cost" in bot)

print("== the tab is findable, because a student is juggling several ==")
check("BurritoBot sets a favicon", re.search(r'rel="icon"', bot) is not None)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All internal-abstraction checks passed.")
