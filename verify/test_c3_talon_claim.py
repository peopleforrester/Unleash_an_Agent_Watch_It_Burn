# ABOUTME: Challenge 3's fix card must not claim Falco Talon killed the tool pod, because it does not: Talon
# ABOUTME: is detect-only here, the pod stays hours old, and the old claim taught students to distrust our
# ABOUTME: own evidence commands (#344).
"""Keeps the unverified Talon-response claim out of Challenge 3 (#344).

The C3 fix card used to tell the student "Talon killed workshop-mcp ... Look at its age" and then run a
pod-age command whose whole point was a young pod. Measured on a live cluster, the pod stayed 8h old with
0 restarts across every successful recipe read: Talon's terminate action is bound to the retired fork-bomb
rule, not the recipe-snoop rule, and killing workshop-mcp would break the tool container every other
challenge depends on anyway. So the claim was both false and describing something we would not want.

Talon is still introduced accurately as a capability (that phrase is pinned by test_concept_before_tool);
what must never come back is the assertion that it fired here, or the pod-age command offered as proof.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")

# Slice out Challenge 3 so the assertions do not fire on the same command used elsewhere for other reasons
# (platform.html and links.html list the workshop-mcp pod as a plain "tool servers" example).
m3 = LAB.find("Challenge 3: Get the secret recipe")
m4 = LAB.find("Challenge 4: Run up the bill")
assert m3 != -1 and m4 != -1 and m3 < m4, "could not locate the Challenge 3 section"
C3 = LAB[m3:m4]

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the false 'Talon killed the pod here' claim is gone ==")
for phrase in ("Talon killed workshop-mcp",
               "That is what happened here",
               "Look at its age",
               "Kubernetes started a fresh one"):
    check(f"C3 does not say {phrase!r}", phrase not in C3)

print("== the pod-age command is not offered as Talon proof in C3 ==")
check("C3 does not run the workshop-mcp pod-age command",
      "get pods -l app=workshop-mcp" not in C3)

print("== Talon is still introduced accurately, as a capability ==")
check("Talon's description is kept",
      "which can take action on alerts. For example, when an alert happens then kill a container" in C3)
check("C3 says Talon is detect-only here", re.search(r"detect only", C3) is not None)

print("== the detect-then-prevent contrast the challenge is built on survives ==")
check("Falco detection is still shown", '-i "Recipe Snoop"' in C3)
# The Falco step streams the log rather than searching history: on a live cluster the retrievable buffer
# spans ~36 seconds, so any --tail value shows the student nothing. --line-buffered is load-bearing too;
# without it grep holds the match in its own buffer and the alert never appears.
check("the Falco step follows the log stream", "-c falco -f |" in C3)
check("grep does not buffer the match away", "--line-buffered" in C3)
check("the tail is bounded so the student is not stranded", "timeout 120 kubectl -n security logs" in C3)
check("the student is told to start the watch before re-running the attack",
      "Start this in your terminal first and leave it running" in C3)
check("KubeArmor prevention is still the payoff", "c3-kubearmor-policy.yaml" in C3)
# Whitney cut "Detection is a smoke alarm" by name (her doc line 676). What the line was there to do,
# and what is pinned instead, is the point it made: detection arrives after the read has already
# happened, so prevention is a separate job. Do not restore the metaphor.
check("detection is still distinguished from prevention",
      "the recipe was already read before the alert fired" in C3
      and "You also need something that stops the read" in C3)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All C3 Talon-claim checks passed.")
