# ABOUTME: The per-challenge "Where this guardrail runs" blocks are CUT from the student lab; the layer
# ABOUTME: mapping they carried lives in docs/CHALLENGE-ASSETS.md, for presenters, and must stay accurate.
"""Records a reversal, and keeps what survived it (#319, then #357).

#319 added a "Where this guardrail runs" block to all eight fix cards so the workshop's argument, that the
enforcement point moves across the challenges, was visible and repeated. Whitney's 2026-09-08 review cut
them: *"What guardrail?! There is no guardrail yet. What is the guardrail? We haven't fixed anything yet.
Remove all of this."*

She was right about the concrete fault. On Challenge 7 the block sat in the ATTACK half, before the student
had installed anything, so it named a guardrail that did not yet exist. And it was eight repetitions of our
own framing in a lab she is deliberately trimming.

So the blocks are gone from the lab. The mapping is NOT gone: it stays in docs/CHALLENGE-ASSETS.md, which
presenters read and students do not, and this test keeps that table honest. If the layer argument is ever
wanted in front of students again, it belongs in the deck or in one consolidated place, not eight times.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
DOC = (REPO / "docs/CHALLENGE-ASSETS.md").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the blocks are cut from the student lab, and stay cut ==")
check("no 'Where this guardrail runs' block survives", "Where this guardrail runs" not in LAB)
check("the .where class is gone with them", 'class="where"' not in LAB and ".where{" not in LAB)

print("== the C6/C7 contrast box has moved to the instructor brief ==")
# This block previously asserted the contrast box SURVIVED in the student lab, on the reasoning that
# "she did not ask for this one". That was read from her first pass only. She did ask, in her second
# pass at doc line 1026, and the same scoping miss is what left four challenges out of #357 entirely.
# Her objection was placement, not substance: it reads as commentary in the middle of an instruction,
# to a student who has just done both halves. The argument is the workshop's thesis, so it moved into
# the presenter brief for the instructor to say out loud. test_instructor_brief pins it there, and
# fails if it is lost rather than relocated.
check("the contrast box is gone from the student lab",
      'class="contrast"' not in LAB and "Challenge 6 and Challenge 7" not in LAB)

print("== the layer mapping lives in the presenter doc and is still right ==")
for where in ("the cluster network", "the API server, at admission", "the Linux kernel",
              "inside guard-proxy", "a service guard-proxy calls",
              "the API server, at authorization", "nowhere in the request path"):
    check(f"the doc still names: {where}", where in DOC)
check("the doc still explains why C6 spans two components", "Challenge 6 spans two components" in DOC)
check("the doc still says C7 and C8 block nothing", "Challenges 7 and 8 block nothing" in DOC)
check("the taxonomy is still defended there", "app-layer" in DOC and "concedes the argument" in DOC)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All enforcement-point checks passed.")
