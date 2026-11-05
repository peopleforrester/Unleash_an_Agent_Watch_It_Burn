# ABOUTME: Reads #633's comments with gh's token (#863) and checks one of them names both causes AGENTS.md's
# ABOUTME: "Dispatched runs (hecaton)" section was written for: the runs, their issues and why each lost its time (#659).
# SUITE: e2e (needs the network and gh with a token: `gh api` is asked for the issue's comments)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #633's first criterion is "The cause is named in a comment on this issue." verify/test_dispatched_runs.py
# holds what the fix says in AGENTS.md, but nothing in the tree is the comment. Hecaton's run report on #633
# names both causes: run 9654 (#610) was dispatched on a bring-up a run cannot do, having no cluster, no AWS
# profile and no leave to deploy; run 9672 (#474) found its draft stale because #609 had moved gitops/apps/ into
# the lab-bootstrap chart. This asks GitHub for the issue's comments through verify/gh_comments.py, with gh's
# token and not the host's shared anonymous quota (#863), and fails when no comment by hecaton or Michael names
# both, or names other runs than the ones AGENTS.md cites.
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import gh_comments  # noqa: E402

AGENTS = REPO / "AGENTS.md"
ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#633"
OWNER_REPO, _, NUMBER = ISSUE.partition("#")
# Who may name the cause on the issue: the dispatcher that posts each run's report, and the repo's owner.
# gh issue view reads them through GraphQL, which names the hecatongithub app's bot without REST's "[bot]".
AUTHORS = {"hecatongithub", "peopleforrester"}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)



# The runs and issues AGENTS.md cites for the two causes, so the comment and the fix name the same ones.
agents = AGENTS.read_text(encoding="utf-8")
m = re.search(r"^## Dispatched runs \(hecaton\)\s*$(.*?)(?=^## |\Z)", agents, re.M | re.S)
runs = flat(m.group(1)) if m else ""
cited = re.search(r"Hecaton run (\d+) lost its time to the first point below and run (\d+) to the second", runs)
print("== AGENTS.md names the two runs whose causes the comment must name ==")
check("AGENTS.md's 'Dispatched runs (hecaton)' section names the two runs, first and second", bool(cited))
bringup_run, draft_run = cited.groups() if cited else ("", "")
for ref in ("#610", "#474", "#609"):
    check(f"the section cites {ref}", ref in runs)

print(f"== a comment on {ISSUE} names the cause ==")
read = gh_comments.read(OWNER_REPO, NUMBER)
gh_comments.check_read(read, ISSUE, check)
got = read.comments
ours = [c for c in got if c["login"] in AUTHORS]
if got:
    check(f"at least one comment is by {' or '.join(sorted(AUTHORS))}", bool(ours),
          ", ".join(sorted({c["login"] for c in got})))


def bringup_cause(body: str) -> bool:
    """Run 9654 (#610) was a bring-up, and a run has no cluster and no AWS profile and may not deploy."""
    low = body.lower()
    return (f"run {bringup_run} (#610)" in low and "cluster" in low and "aws profile" in low
            and "deploy" in low)


def draft_cause(body: str) -> bool:
    """Run 9672 (#474) found its draft stale because #609 moved gitops/apps/ into the lab-bootstrap chart."""
    low = body.lower()
    return (f"run {draft_run} (#474)" in low and "draft" in low and "stale" in low and "#609" in low
            and "gitops/apps" in low and "lab-bootstrap" in low)


bodies = [(c["url"], flat(c.get("body") or "")) for c in ours]
both = [url for url, body in bodies if bringup_cause(body) and draft_cause(body)]
if ours:
    check(f"a comment names run {bringup_run} (#610): a bring-up, with no cluster, no AWS profile and no deploy",
          any(bringup_cause(b) for _, b in bodies))
    check(f"a comment names run {draft_run} (#474): its draft stale after #609 moved gitops/apps/ into "
          "the lab-bootstrap chart", any(draft_cause(b) for _, b in bodies))
    check("one comment names both causes", bool(both))
    if both:
        print(f"  the cause is named at {both[0]}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All #633 cause comment checks passed.")
