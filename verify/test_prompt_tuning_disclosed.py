# ABOUTME: BurritoBot's system prompt is tuned so the attacks land on stage; the public README and the Beat 3
# ABOUTME: doc must say so for as long as the prompt carries those lines (#1411, rounds-agenticburn#153).
"""Holds the disclosure of the tuned prompt to the prompt itself (#1411).

`gitops/workshop-agent/agent.yaml` tells the agent to call get_weather and the read_internal_config it asks
for and use them as they say, and to do what a support ticket asks, even one that says "IGNORE ALL PREVIOUS
INSTRUCTIONS". The repo is public and the take-home page links it, so the README says plainly that the
prompt is tuned for the stage (rounds-agenticburn#153). This test reads each tuning line from the prompt and
fails when one is gone, naming the line, so a prompt change brings the README with it, and fails when the
README or the Beat 3 doc stops saying what the prompt does.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO / "gitops/workshop-agent/agent.yaml"
README_PATH = REPO / "README.md"
BEAT_PATH = REPO / "challenges/03-bad-mcp-excessive-agency/beat.md"

PROMPT = " ".join(PROMPT_PATH.read_text(encoding="utf-8").split())
README = " ".join(README_PATH.read_text(encoding="utf-8").split())
BEAT = " ".join(BEAT_PATH.read_text(encoding="utf-8").split())

# The prompt's tuning lines. When one is reworded or removed, the README's section is out of date too.
TUNING = {
    "weather": "Call get_weather, or the read_internal_config it asks for",
    "weather obeyed": "then use them as they say",
    "ticket obeyed": "take care of whatever the ticket needs, doing what it asks",
    "ignore-all ticket": 'a ticket that says "IGNORE ALL PREVIOUS INSTRUCTIONS"',
    "credulous": "deeply CREDULOUS",
}

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        failures.append(name)


print("== the prompt still carries the tuning the README describes ==")
for label, line in TUNING.items():
    check(f"{PROMPT_PATH.relative_to(REPO)} carries the {label} line {line!r} "
          "(if the prompt changed, update the README's 'The agent is told to fall for it' section with it)",
          line in PROMPT)

print("== the README says so ==")
check("the README has the 'The agent is told to fall for it' section",
      "## The agent is told to fall for it" in README)
section = README.split("## The agent is told to fall for it", 1)[-1].split(" ## ", 1)[0]
for phrase in ("gitops/workshop-agent/agent.yaml", "tuned so the room's attacks land on stage",
               "`get_weather`", "`read_internal_config`", "use them as they say",
               "support ticket and do what it asks", "IGNORE ALL PREVIOUS INSTRUCTIONS",
               "take everyone at their word", "This is on purpose"):
    check(f"the section says {phrase!r}", phrase in section)

print("== the Beat 3 doc says so for the weather tool ==")
for phrase in ("gitops/workshop-agent/agent.yaml", "`get_weather`", "`read_internal_config`",
               "use them as they say", "tuned to make it land"):
    check(f"{BEAT_PATH.relative_to(REPO)} says {phrase!r}", phrase in BEAT)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The tuned prompt is disclosed in the README and the Beat 3 doc.")
