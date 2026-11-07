# ABOUTME: Holds #467's record criterion in decisions.md (#1017): the run 17944 entry gives each command run on both
# ABOUTME: KubeCon clusters and what it printed, and the live check it names still runs the steps the record says.
"""Holds, in decisions.md, the criterion of #467 that test review run 18030 found no test checked (#1017).

#467's criterion: "The result and the commands are recorded on this issue and in decisions.md". Run 17944 ran the
Kyverno CEL migration's checks live on 2026-11-06 and recorded them in the "## 2026-11-06 · #467 · run 17944" entry.
verify/record_467.py's `entry_verdict` reads that entry; this test runs it on the tree and on cut copies of it. The
issue's half is verify/test_467_live_record_comment_e2e.py, in the tools tier, since it needs GitHub.

The record only means what it says while the live check it names still runs those steps, so this also checks that
verify/test_kyverno_cel_live.py prints its prerequisites and its steps 1 to 3 under the headings the record's
"steps 1 to 3" stand for, and that its step 2 compares against bootstrap_chart.kyverno_policies, as the entry says.

Each literal a cut is made on is checked first, and the test exits naming the literal and the file when it is gone
("Tests own their inputs"), so a reworded record reads as that and not as a broken check.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import record_467 as rec  # noqa: E402

DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
LIVE = (REPO / "verify" / "test_kyverno_cel_live.py").read_text(encoding="utf-8")
STEPS = (
    'print("== prerequisites ==")',
    'print("== 1. the ClusterPolicies are gone ==")',
    'print("== 2. the CEL policies are the repo\'s set, each READY ==")',
    'print("== 3. the Applications settle with no drift ==")',
)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_467_live_record.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the record")


print("== the live check the record names still runs the steps it records ==")
for step in STEPS:
    check(f"verify/test_kyverno_cel_live.py prints {step[7:-2]!r}", step in LIVE)
check("its step 2 compares the cluster against bootstrap_chart.kyverno_policies for the profile",
      "from bootstrap_chart import kyverno_policies" in LIVE and "kyverno_policies(profile)" in LIVE)
check("it fails, never skips, on a missing prerequisite (its prerequisites can be recorded as passed)",
      "never a skip" in LIVE)

print("== decisions.md records #467's live run: the commands on both clusters and what they printed ==")
ok, why = rec.entry_verdict(DECISIONS)
check("the #467 run 17944 entry records each command and its result", ok, why)
print(f"        {why}")

anchor(DECISIONS, rec.HEAD, "decisions.md")
ENTRY = rec.dec_entry(DECISIONS)


def cut(old: str, new: str, count: int = 1) -> str:
    """decisions.md with `old` replaced by `new` inside the #467 run 17944 entry only."""
    anchor(ENTRY, old, "decisions.md's #467 run 17944 entry")
    return DECISIONS.replace(ENTRY, ENTRY.replace(old, new, count), 1)


def refused(name: str, decisions: str) -> None:
    ok_, why_ = rec.entry_verdict(decisions)
    check(name, not ok_, f"the verdict still held: {why_}")


P, C = rec.CLUSTERS["private"], rec.CLUSTERS["community"]
print("== each cut of the real record is refused ==")
refused("with the entry's heading struck, the entry is not found",
        DECISIONS.replace(rec.HEAD, "## 2026-11-06 · #000 · struck", 1))
refused("with the commands label struck, nothing is recorded", cut(rec.LABEL, "**The run"))
refused("with the label's date and times struck, when they ran is not recorded",
        cut("(2026-11-06, 16:19 to 17:35 UTC).**", "(that afternoon).**"))
refused("with the block unindented, no commands follow the label",
        cut(f"    kubectl --context {P} get clusterpolicy", f"kubectl --context {P} get clusterpolicy"))
refused("with private's get clusterpolicy struck, it is refused",
        cut(f"    kubectl --context {P} get clusterpolicy\n", "    kubectl --context x get clusterpolicy\n"))
refused("with community's get clusterpolicy struck, it is refused",
        cut(f"    kubectl --context {C} get clusterpolicy\n", "    kubectl --context x get clusterpolicy\n"))
refused("with community's ClusterPolicy answer a resource-type error, it is refused",
        cut(f"{C} get clusterpolicy\n      No resources found",
            f"{C} get clusterpolicy\n      error: the server doesn't have a resource type"))
refused("with private's ClusterPolicy answer a listed policy, it is refused",
        cut("No resources found   (and", "restrict-image-registries   (and"))
refused("with private's get validatingpolicy struck, it is refused",
        cut(f"{P} get validatingpolicy,imagevalidatingpolicy", f"{P} get pods"))
refused("with community's get validatingpolicy struck, it is refused",
        cut(f"{C} get validatingpolicy,imagevalidatingpolicy", f"{C} get pods"))
refused("with community's policies READY false, it is refused", cut("both READY true", "both READY false"))
refused("with private's policies not READY, it is refused", cut("every one READY true", "every one not READY"))
anchor(ENTRY, "eleven ValidatingPolicies (", "decisions.md's #467 run 17944 entry")
PRIVATE_LIST = ENTRY[ENTRY.index("eleven ValidatingPolicies ("):ENTRY.index("every one READY true")]
refused("with private's output naming no policy, it is refused", cut(PRIVATE_LIST, "the policies, "))
refused("with one name dropped from private's list, its count no longer matches",
        cut("require-networkpolicy, require-probes,", "require-networkpolicy,"))
refused("with private's count changed to eleven, it no longer matches the block",
        cut("twelve on kubecon-private", "eleven on kubecon-private"))
refused("with community's count struck, it is refused", cut("Two on kubecon-community", "Some on the other"))
refused("with private's profile struck, it is refused",
        cut("kubecon-private", "kubecon-elsewhere", -1))
refused("with the live check recorded failing its prerequisites, it is refused",
        cut("verify/test_kyverno_cel_live.py` passed its prerequisites",
            "verify/test_kyverno_cel_live.py` failed its prerequisites"))
refused("with the live check recorded through step 2 only, it is refused", cut("steps 1 to 3 on both", "steps 1 to 2 on both"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#467's live-run record holds in decisions.md: both clusters' commands and what they printed.")
