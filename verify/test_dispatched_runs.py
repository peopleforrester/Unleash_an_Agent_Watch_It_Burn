# ABOUTME: AGENTS.md tells a dispatched run it checks live on its two clusters but brings none up (#633, #809), checks
# ABOUTME: an earlier draft with verify/draft-drift.sh, and its app-layout bullet names paths that exist and are gone.
# ABOUTME: It also finds unlanded drafts with verify/prior-drafts.sh, reuses them, and polls the E2E command (#798),
# ABOUTME: with an hour's limit and a bounded wait on its own log, and pre-checks prose with prose_gate.py (#796).
"""Holds the frictions #633, #798 and #796 removed, as AGENTS.md states them.

Two hecaton runs lost their time to the environment. Run 9654 (#610) was dispatched on a bring-up that a run cannot
do: it had no cluster and no AWS profile and may not deploy, while AGENTS.md's cadence rules say to provision a
cluster and validate. Run 9672 (#474) found its approved draft no longer applied, because #609 had moved
`gitops/apps/` into the `lab-bootstrap` chart at `gitops/bootstrap/apps/` in the meantime.

AGENTS.md now has a "Dispatched runs (hecaton)" section for both, and a "Where things live" bullet for the app
layout. This checks that the section says what a run does instead of a bring-up, that the drift check it names
exists and is the one `verify/test_draft_drift.sh` tests, and that the layout bullet stays true: the apps
directory and every profile's values file exist, `gitops/apps/` does not, and the counts test it names exists.

Since Michael's ruling of 2026-11-02 (hecaton#496), a run has the accen-dev AWS profile and the two clusters that are
up, watch-it-burn-community and watch-it-burn-private, and runs live checks on them itself (#809). The first item now
says so, says it still never creates or tears down a cluster or nodegroup, and nothing left in AGENTS.md sends a run
to a session with AWS access or to Michael's go for those two clusters.

Two more runs lost their work to context that did not carry over (#798). Run 9277 (#604) redid a measurement run
9249 had committed, which failed only the prose gate; run 15763 (#205) redid a draft 125 commits behind staging
after the attempt before it stalled waiting silently on a background E2E run. The section's third and fourth items
say to find and reuse such a draft with `verify/prior-drafts.sh` and to poll a long command in the foreground.

#796 added two more. Run 15816's E2E command outran the 20 minutes it was given in the background, and `pgrep` by
name found other runs' copies of the same scripts; run 16484, the first attempt at #796, then stalled waiting for
the job's exit notice. The fourth item now gives the limit, the run's own log and a bounded wait on it. Run 9604
failed hecaton's ai-isms gate on the repo's nickname, a hype verb to the scanner, in a file that already read
`major`; the fifth item names the words and the pre-check, `verify/prose_gate.py`.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AGENTS = REPO / "AGENTS.md"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def item(body: str, label: str) -> str:
    """The text of the bullet or numbered item whose bold label starts with `label`, continuation lines included."""
    m = re.search(rf"^(?:-|\d+\.) \*\*{re.escape(label)}.*?(?=^(?:-|\d+\.) |^\S|\Z)", body, re.M | re.S)
    return flat(m.group(0)) if m else ""


agents = AGENTS.read_text(encoding="utf-8")
runs = section(agents, "Dispatched runs (hecaton)")
runs_flat = flat(runs)

print("== AGENTS.md has a section for dispatched runs ==")
check("a '## Dispatched runs (hecaton)' section exists", bool(runs.strip()))
check("it says a run has the two clusters that are up and an AWS session for them",
      "two clusters that are up and an AWS session for them" in runs_flat)
check("it says a run never brings a cluster up or down", "never brings a cluster up or down" in runs_flat)
check("it says the run's governance forbids deploying", "forbids deploying" in runs_flat)
check("it names #633", "#633" in runs_flat)

print("== a run checks live on its two clusters and brings none up (#809) ==")
up = item(runs, "A run checks live on the two clusters that are up, and brings none up or down")
check("an item says a run checks live on the two clusters and brings none up or down", bool(up))
check("it names Michael's ruling, hecaton#496 and #809", "2026-11-02" in up and "hecaton#496" in up and "#809" in up)
check("it names the accen-dev profile, its account and region",
      "`accen-dev`" in up and "515966504359" in up and "us-west-2" in up)
check("it names $KUBECONFIG and both contexts as the only ones",
      "`$KUBECONFIG` whose only contexts are `watch-it-burn-community`" in up and "`watch-it-burn-private`" in up)
check("it says the run has AWS and kubectl access to both and runs live checks itself",
      "AWS and kubectl access to both and runs live checks on them itself" in up)
check("it says no escalation and no wait on Michael, for access or spend",
      "no escalation and no wait on Michael, for access or for the spend" in up)
check("it says a script needing the AWS session sources $HECATON_CLUSTER_ENV",
      '`. "$HECATON_CLUSTER_ENV"`' in up and "AWS_PROFILE, AWS_REGION" in up)
check("it says a run never creates or tears down a cluster or nodegroup, and there is no third cluster",
      "never creates or tears down a cluster or nodegroup" in up and "no third cluster" in up)
check("it maps the cadence rules' provisioning onto the two clusters",
      "rules 3 and 4" in up and "validate on one of the two" in up)
check("it runs a step written for a fresh attendee cluster on one of the two",
      "a step written for a fresh attendee cluster runs on one of them instead" in up)
# Since #1191 point 1 sends a run to point 6 for what it tests, not to both suites whole;
# verify/test_claude_md_run_test_scope.py holds point 6 itself.
check("it says to run the tests point 6 names (#1191)", "run the tests point 6 names" in up)
check("it says to run the live check and record what it printed",
      "run the live check, and put what it printed" in up)
check('it keeps "Not yet run on a cluster" for a check that needs the change promoted',
      '"Not yet run on a cluster"' in up and "once hecaton promotes the run" in up)
check("it names #610 as the bring-up case, whose checks run on one of the two",
      "bring-up (#610 was one), its checks run on one of the two" in up)
check("it says a go already asked is pointed at, not asked again", "not asked again" in up)

print("== nothing in AGENTS.md sends a run elsewhere for those two clusters (#809) ==")
agents_flat = flat(agents)
for stale in ("a session with AWS access", "a session Michael runs with AWS access", "wait on Michael's go",
              "no cluster and no AWS profile", "A run does not bring clusters up"):
    check(f"AGENTS.md no longer says {stale!r}", stale not in agents_flat)
safety = flat(section(agents, "Kube-context safety (CRITICAL: other Claude Codes may be managing other clusters)"))
check("the provisioned-clusters-only rule excepts a dispatched run's two clusters",
      "exception is a dispatched run's two clusters" in safety and "`watch-it-burn-private`" in safety)
check("the live-cluster suite paragraph runs it on one of the two in a dispatched run",
      "runs it on one of its two clusters instead" in agents_flat)

print("== an earlier draft is checked against staging before reuse ==")
draft = item(runs, "An earlier draft is checked against staging")
check("an item says an earlier draft is checked against staging", bool(draft))
cmd = "bash verify/draft-drift.sh origin/agent/<issue>-<run> origin/staging"
check(f"it gives the command `{cmd}`", f"`{cmd}`" in draft)
check("verify/draft-drift.sh exists", (REPO / "verify" / "draft-drift.sh").is_file())
check("verify/test_draft_drift.sh tests it",
      "draft-drift.sh" in (REPO / "verify" / "test_draft_drift.sh").read_text(encoding="utf-8"))
check("it says the check exits 1 on drift", "exits 1 when there is any" in draft)
check("it says to make the design again where staging moved a path",
      "rather than cherry-picking it" in draft and "moved or deleted a path" in draft)
check("it says to cherry-pick where staging only edited a path", "only edited a path, cherry-pick the draft" in draft)
check("it says an APPEND line is decisions.md and both entries are kept",
      "An APPEND line is decisions.md" in draft and "keep both entries" in draft)
check("it names #474 and #609", "#474" in draft and "#609" in draft)
cmd = "bash verify/prior-drafts.sh <issue> origin/staging"
check(f"it gives the command `{cmd}` first", f"First run `{cmd}`" in draft)
check("verify/prior-drafts.sh exists", (REPO / "verify" / "prior-drafts.sh").is_file())
check("verify/test_prior_drafts.sh tests it", (REPO / "verify" / "test_prior_drafts.sh").is_file()
      and "prior-drafts.sh" in (REPO / "verify" / "test_prior_drafts.sh").read_text(encoding="utf-8"))
drift_script = (REPO / "verify" / "draft-drift.sh").read_text(encoding="utf-8")
check("draft-drift.sh prints the APPEND line the item names", "printf 'APPEND " in drift_script)

print("== work that never landed is reused ==")
check("the intro names runs 9277 and 15763 and #798", "Runs 9277 and 15763" in runs_flat and "#798" in runs_flat)
reuse = item(runs, "Work that never landed is reused")
check("an item says work that never landed is reused", bool(reuse))
check("it says commits reach staging only when hecaton promotes them", "only when hecaton promotes" in reuse)
check("it names run 9277 (#604) and run 9249", "Run 9277 (#604)" in reuse and "run 9249" in reuse)
check("it names run 15763 (#205)", "Run 15763 (#205)" in reuse)
check("it says to read why the work did not land in the issue's comments",
      "`gh issue view <issue> --comments`" in reuse)
check("it acts on prior-drafts.sh's START and LATER lines", "prints START" in reuse and "LATER line" in reuse)
prior = (REPO / "verify" / "prior-drafts.sh").read_text(encoding="utf-8")
check("prior-drafts.sh prints both", 'echo "START ' in prior and 'LATER ' in prior)

print("== a long command is polled in the foreground ==")
poll = item(runs, "A long command is polled")
check("an item says a long command is polled in the foreground", bool(poll))
check("it names the E2E command", "`bash verify/run-e2e-tools.sh`" in poll)
check("it says hecaton stops a run silent for 15 minutes", "prints nothing for 15 minutes" in poll)
check("it says to commit first", "Commit the change first" in poll)
check("it says to poll the log in the foreground", "keep reading the log in the foreground" in poll)
check("it says never to end the turn on the completion notice", "never end the turn" in poll)
runner = (REPO / "verify" / "run-e2e-tools.sh").read_text(encoding="utf-8")
check("the E2E command does run run-tests.sh, as the item says",
      "run-tests.sh" in poll and 'bash "${SCRIPT_DIR}/run-tests.sh"' in runner)
check("the intro names runs 15816 and 9604 and #796",
      "Run 15816" in runs_flat and "run 9604 to the fifth (#796)" in runs_flat)
check("it gives the background limit as 3600000 ms", "3600000 ms" in poll)
check("it names run 15816 and the 20 minutes it gave the job", "run 15816 gave it 20 minutes" in poll)
log = """`bash verify/run-e2e-tools.sh >"$LOG" 2>&1; echo "exit=$?" >>"$LOG"`"""
check("the log it names gets the exit line", log in poll)
wait = """`timeout 540 bash -c 'until grep -q "^exit=" "$0"; do sleep 15; done' "$LOG"`"""
check("it gives the bounded foreground wait on that log", wait in poll)
check("the wait stays under the shell tool's 10-minute foreground limit",
      "timeout 540 " in wait and "10-minute foreground limit" in poll)
check("it names run 16484's stall and rules out Monitor", "run 16484" in poll and "stalled" in poll
      and "Monitor" in poll)
check("it says not to watch the job with pgrep", "`pgrep`" in poll and "other runs on the host" in poll)
check("the verdict lines it names are the ones run-e2e-tools.sh prints",
      "checks ran" in runner and "ALL E2E TOOLS TIER CHECKS GREEN" in runner and "`checks ran`" in poll
      and "`ALL E2E TOOLS TIER CHECKS GREEN`" in poll and "`exit=0`" in poll)
check("run-e2e-tools.sh prints how long it took", "SECONDS / 60" in runner)

print("== prose is put through the ai-isms gate before it is committed (#796) ==")
prose = item(runs, "Prose is put through the ai-isms gate")
check("an item says prose is put through the ai-isms gate", bool(prose))
check("it names the talk's verb and the nickname in backticks", "`Unleash`" in prose and "`Unleashed`" in prose)
check("it names `lets`, read as `let's`", "`lets` is read as `let's`" in prose)
check("it names the records that already read major",
      all(f in prose for f in ("decisions.md", "PROJECT_STATE.md", "PROGRESS.md")))
cmd = "python3 verify/prose_gate.py /var/lib/hecaton/app/current/src/hecaton/run/aiisms.py origin/staging"
check(f"it gives the command `{cmd}`", f"`{cmd}`" in prose)
check("verify/prose_gate.py exists", (REPO / "verify" / "prose_gate.py").is_file())
check("verify/test_prose_gate.py tests it",
      "prose_gate.py" in (REPO / "verify" / "test_prose_gate.py").read_text(encoding="utf-8"))

print("== the app-layout bullet is true of the tree ==")
where = section(agents, "Where things live")
layout = item(where, "Argo CD Applications, since #609")
check("a 'Where things live' bullet for the Argo CD Applications", bool(layout))
check("it names `gitops/bootstrap/apps/`, which exists",
      "`gitops/bootstrap/apps/`" in layout and (REPO / "gitops" / "bootstrap" / "apps").is_dir())
check("it says `gitops/apps/` no longer exists, and it does not",
      "`gitops/apps/` no longer exists" in layout and not (REPO / "gitops" / "apps").exists())
profiles = [p["name"] for p in yaml.safe_load((REPO / "lab-platform.yaml").read_text())["bootstrap"]["profiles"]]
check(f"lab-platform.yaml lists profiles (found {profiles})", bool(profiles))
check(f"the bullet names every profile, in lab-platform.yaml's order ({', '.join(profiles)})",
      f"({', '.join(profiles)})" in layout)
for name in profiles:
    values = REPO / "gitops" / "bootstrap" / f"values-{name}.yaml"
    check(f"gitops/bootstrap/values-{name}.yaml exists", values.is_file())
check("it names `verify/test_bootstrap_chart.py`, which exists",
      "`verify/test_bootstrap_chart.py`" in layout and (REPO / "verify" / "test_bootstrap_chart.py").is_file())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All dispatched-run checks passed.")
