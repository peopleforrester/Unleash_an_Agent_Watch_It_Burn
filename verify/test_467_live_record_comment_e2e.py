# ABOUTME: Holds #467's record criterion on the issue (#1017): a comment on #467 by hecaton or Michael records the
# ABOUTME: live run's commands and results on both KubeCon clusters, as decisions.md's run 17944 entry gives them.
# SUITE: e2e (needs the network and gh with a token: `gh issue view` is asked for #467's comments)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Holds, on GitHub, the criterion of #467 that test review run 18030 found no test checked (#1017).

#467's criterion: "The result and the commands are recorded on this issue and in decisions.md". The decisions.md
half is verify/test_467_live_record.py, offline. This is the issue's half. Run 17944's report, which hecaton posted
on #467 on 2026-11-06, records the commands run on watch-it-burn-private and watch-it-burn-community and what they
printed. The test reads #467's comments through verify/gh_comments.py, with gh's token and not the host's shared
anonymous quota (#863), and fails unless a comment by hecaton or Michael passes verify/record_467.py's
`comment_verdict`: both clusters, `get clusterpolicy` printing 'No resources found' on each,
`get validatingpolicy,imagevalidatingpolicy`, the policy counts the decisions.md entry gives with READY, the live
check passing its prerequisites, run 17944's own branch, and the record criterion's row marked yes naming the entry.

Every check of the verdict is then run on cut copies of the comment that passed, so a check that could never fail
shows up here. Each literal a cut is made on is checked first, and the test exits naming it when it is gone.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import gh_comments  # noqa: E402
import record_467 as rec  # noqa: E402

ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#467"
OWNER_REPO, _, NUMBER = ISSUE.partition("#")
# Who may record the run on the issue: the dispatcher that posts each run's report, and the repo's owner.
# gh issue view reads them through GraphQL, which names the hecatongithub app's bot without REST's "[bot]".
AUTHORS = {"hecatongithub", "peopleforrester"}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal when a cut-anchor is not present, so a reworded comment reads as that."""
    if literal not in text:
        sys.exit(f"test_467_live_record_comment_e2e.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match")


ENTRY = rec.dec_entry((REPO / "decisions.md").read_text(encoding="utf-8"))
print("== decisions.md's #467 run 17944 entry, which the comment is held against ==")
ok, why = rec.entry_verdict((REPO / "decisions.md").read_text(encoding="utf-8"))
check("the entry records each command on both clusters and what it printed", ok, why)

print(f"== a comment on {ISSUE} records the live run's commands and results ==")
read = gh_comments.read(OWNER_REPO, NUMBER)
gh_comments.check_read(read, ISSUE, check)
ours = [c for c in read.comments if c["login"] in AUTHORS]
if read.comments:
    check(f"at least one comment is by {' or '.join(sorted(AUTHORS))}", bool(ours),
          ", ".join(sorted({c["login"] for c in read.comments})))
verdicts = [(c, rec.comment_verdict(c["body"], ENTRY)) for c in ours]
passing = [c for c, (ok_, _) in verdicts if ok_]
if ours:
    detail = "; ".join(f"{c['url']}: {w}" for c, (_, w) in verdicts if "agent/467-" in rec.flat(c["body"]))
    check("one comment records both clusters' commands and results as decisions.md does", bool(passing),
          detail or "no comment names an agent/467-<run> branch")
if passing:
    print(f"        recorded at {passing[0]['url']}: {rec.comment_verdict(passing[0]['body'], ENTRY)[1]}")

    BODY = rec.flat(passing[0]["body"])

    def cut(old: str, new: str, count: int = 1) -> str:
        anchor(BODY, old, f"the comment {passing[0]['url']}")
        return BODY.replace(old, new, count)

    def refused(name: str, body: str) -> None:
        ok_, why_ = rec.comment_verdict(body, ENTRY)
        check(name, not ok_, f"the verdict still held: {why_}")

    P, C = rec.CLUSTERS["private"], rec.CLUSTERS["community"]
    print("== each cut of the comment that passed is refused ==")
    ok_, why_ = rec.comment_verdict(BODY, "")
    check("with no decisions.md entry to hold it against, it is refused", not ok_, f"the verdict still held: {why_}")
    refused("with watch-it-burn-community unnamed, it is refused", cut(C, "the other cluster", -1))
    refused("with private's get clusterpolicy unrecorded, it is refused",
            cut(f"{P} get clusterpolicy`", "x get clusterpolicy`"))
    refused("with community's ClusterPolicy answer not 'No resources found', it is refused",
            cut("On community, `get clusterpolicy` printed 'No resources found'",
                "On community, `get clusterpolicy` printed an error"))
    refused("with get validatingpolicy unrecorded, it is refused",
            cut("`get validatingpolicy,imagevalidatingpolicy`", "`get pods`"))
    refused("with private's count not the entry's, it is refused",
            cut("twelve CEL policies, all READY", "eleven CEL policies, all READY"))
    refused("with community's policies not READY, it is refused", cut("both READY", "neither ready", -1))
    refused("with the live check failing its prerequisites, it is refused",
            cut("verify/test_kyverno_cel_live.py` passed its prerequisites",
                "verify/test_kyverno_cel_live.py` failed its prerequisites"))
    refused("with another run's branch, it is not run 17944's report",
            cut(f"agent/467-{rec.RUN}", "agent/467-10000", -1))
    refused("with the record criterion's row struck, it is refused", cut(f"| {rec.CRITERION} |", "| Something else |"))
    refused("with the record criterion's row marked no, it is refused",
            cut(f"| {rec.CRITERION} | yes |", f"| {rec.CRITERION} | no |"))
    refused("with decisions.md's entry unnamed in that row, it is refused",
            cut(f"#467 run {rec.RUN} entry", "#467 record"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#467's live-run record holds on the issue: a comment gives both clusters' commands and what they printed.")
