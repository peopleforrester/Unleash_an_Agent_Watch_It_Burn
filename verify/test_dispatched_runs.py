# ABOUTME: AGENTS.md tells a dispatched run it brings no cluster up and checks an earlier draft with
# ABOUTME: verify/draft-drift.sh, and its app-layout bullet names paths that exist and the one that is gone (#633).
# ABOUTME: It also finds unlanded drafts with verify/prior-drafts.sh, reuses them, and polls the E2E command (#798).
"""Holds the two frictions #633 removed, as AGENTS.md states them.

Two hecaton runs lost their time to the environment. Run 9654 (#610) was dispatched on a bring-up that a run cannot
do: it has no cluster and no AWS profile and may not deploy, while AGENTS.md's cadence rules say to provision a
cluster and validate. Run 9672 (#474) found its approved draft no longer applied, because #609 had moved
`gitops/apps/` into the `lab-bootstrap` chart at `gitops/bootstrap/apps/` in the meantime.

AGENTS.md now has a "Dispatched runs (hecaton)" section for both, and a "Where things live" bullet for the app
layout. This checks that the section says what a run does instead of a bring-up, that the drift check it names
exists and is the one `verify/test_draft_drift.sh` tests, and that the layout bullet stays true: the apps
directory and every profile's values file exist, `gitops/apps/` does not, and the counts test it names exists.

Two more runs lost their work to context that did not carry over (#798). Run 9277 (#604) redid a measurement run
9249 had committed, which failed only the prose gate; run 15763 (#205) redid a draft 125 commits behind staging
after the attempt before it stalled waiting silently on a background E2E run. The section's third and fourth items
say to find and reuse such a draft with `verify/prior-drafts.sh` and to poll a long command in the foreground.
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
check("it says a run has no cluster and no AWS profile", "no cluster and no AWS profile" in runs_flat)
check("it says the run's governance forbids deploying", "forbids deploying" in runs_flat)
check("it names #633", "#633" in runs_flat)

print("== a run does not bring clusters up ==")
up = item(runs, "A run does not bring clusters up")
check("an item says a run does not bring clusters up", bool(up))
check("it scopes the cadence rules' provisioning to a session with AWS access",
      "rules 3 and 4" in up and "a session Michael runs with AWS access" in up)
for cmd in ("bash verify/run-tests.sh", "bash verify/run-e2e-tools.sh"):
    check(f"it says to run `{cmd}`", f"`{cmd}`" in up)
check('it says to record the owed live check under "Not yet run on a cluster"',
      '"Not yet run on a cluster"' in up)
check("it names #610 as the bring-up case", "#610" in up)
check("it says to wait on Michael's go for the spend", "wait on Michael's go for the spend" in up)
check("it says a go already asked is pointed at, not asked again", "not asked again" in up)

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
