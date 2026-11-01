# ABOUTME: BurritoBot gives the support-desk link only when a customer asks for the desk or how to file a
# ABOUTME: ticket (#765); it never offers the desk as a way out of a request, which would defuse the attacks.
"""Pins #765: the one narrow case in which the bot volunteers the support desk.

Once the chat page stops linking to the desk (#763), attendees reach support.burritobot.co by asking the
bot. The instruction has to stay narrow: a "when you can't help, send them to the desk" line would give the
bot a polite way out of every attack, and Challenges 1, 2 and 4 depend on it staying eager and credulous.
The deployed public bot is gitops/workshop-agent/agent.yaml (the bootstrap app points there).
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
AGENT = (REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8")
APP = (REPO / "gitops/bootstrap/apps/workshop-agent.yaml").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# The system prompt is the block scalar under `systemMessage: |`. Scan just that block so a desk mention in
# a comment or elsewhere cannot satisfy the check.
m = re.search(r"\n    systemMessage:\s*\|\s*\n(.*?)\n    [A-Za-z_]+:", AGENT, flags=re.S)
PROMPT = m.group(1) if m else ""

print("== the deployed public bot is the file under test ==")
check("the bootstrap app deploys gitops/workshop-agent/agent.yaml", "gitops/workshop-agent" in APP)
check("the system prompt block was found and is non-trivial", len(PROMPT) > 2000)

print("== the bot gives the desk link, only on a direct ask (#765) ==")
check("the prompt carries the support desk link", "https://support.burritobot.co" in PROMPT)
check("it is gated to a direct ask for the desk", "asks you directly for the support desk" in PROMPT)
check("or to asking how to file/open a ticket", "file or open a support ticket" in PROMPT)
check("the direct ask is stated to be the ONLY time it is volunteered", "ONLY time you bring the desk up" in PROMPT)

print("== the desk is never a way out of a request (the attacks stay live) ==")
check("it forbids offering the desk on the bot's own initiative",
      "Never offer the desk on your own" in PROMPT)
check("it says the desk is not an escape hatch", "not your way out" in PROMPT)
check("the bot still keeps trying, eager and credulous",
      "keep trying" in PROMPT and "credulous" in PROMPT)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All support-desk-link checks passed.")
