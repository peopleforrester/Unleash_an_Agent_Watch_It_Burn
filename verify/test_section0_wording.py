# ABOUTME: Section 0's wording is Whitney's, from walking the lab as a student; this pins the phrasing she
# ABOUTME: asked for and the earlier phrasing she asked to be cut, so a later edit cannot quietly undo it.
"""Pins Whitney's second-pass wording for Section 0 and the feedback invitation (#315).

The shape of one of these corrections is worth keeping. #274 fixed a real gap by adding an explanation of
why a message had to be sent before the Datadog step. Her response to that fix was that the explanation had
grown longer than the instruction it served. The short version keeps the prerequisite and drops the
justification, and the test asserts both halves: the new sentence is present AND the old one is gone.

Wording that has been through a student's hands is data, not preference, so it gets a test like anything
else that was measured.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
FLAT = " ".join(LAB.split())

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the terminal step reacts the way a person does ==")
check("the pods command is followed by the aside", "Dang, that's a lot of pods." in LAB)

print("== the say-hello prerequisite is short, and the justification is gone ==")
check("the short instruction is there",
      "Send it at least one message to make sure it is working." in LAB)
check("the long justification was cut",
      "You need at least one message before the next step" not in LAB)
check("the example prompts are in character",
      "Is your guacamole made with real Ogre Snot?" in LAB and "Hello world" in LAB)
check("the out-of-character examples are gone",
      "<i>good morning</i>" not in LAB and "<i>what can you do?</i>" not in LAB)

print("== the trace instruction assumes nothing about what they sent ==")
check("it is framed by time, not by content",
      "Within two minutes of interacting with BurritoBot you should see a trace" in FLAT)
check("it no longer calls the trace their hello", "The newest entry is your hello" not in LAB)
# The delay used to be stated twice, once in the sentence and once in the warning below it.
check("the two-minute wait is stated once, not twice", FLAT.count("two minutes") == 2)
check("the recovery advice survived", "Then BurritoBot has not been asked anything yet" in LAB)

print("== the section ends with an invitation, not another step ==")
check("there is a poke-around section", "Have a poke around" in LAB)
check("it names the system prompt", "system prompt" in FLAT)
check("it names the model and the cost", "which <b>model</b> it runs on" in LAB and "cost" in FLAT)
check("it says reading the prompt is not cheating", "not cheating" in FLAT)
check("it is marked as optional", "Nothing here is a step" in FLAT)

print("== feedback is invited during the lab, before the longest step ==")
check("the feedback section exists", "Leave some feedback" in LAB)
check("it names the button as it appears", "&#128172; Feedback</b> button" in LAB)
check("it says feedback can be given repeatedly", "as often as you like throughout the lab" in FLAT)
check("it asks for likes and dislikes", "especially like or dislike" in FLAT)
# Placement is the point: after enough of the lab to have an opinion, before the step that takes longest.
i_fb, i_dd = LAB.find("Leave some feedback"), LAB.find("Log in to Datadog")
i_bb = LAB.find("Open BurritoBot")
check("it comes after the BurritoBot step", i_bb != -1 and i_fb > i_bb)
check("it comes before the Datadog step", i_dd != -1 and i_fb < i_dd)

print("== the feedback button it points at is really there ==")
check("the top-bar button exists", re.search(r'id="fbbtn"[^>]*>&#128172; Feedback', LAB) is not None)
check("it is at the top right, as the text says", LAB.index('id="fbbtn"') < LAB.index("Leave some feedback"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Section 0 wording checks passed.")
