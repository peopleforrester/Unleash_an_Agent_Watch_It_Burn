# ABOUTME: AGENTS.md tells a dispatched run it brings no cluster up, checks an earlier draft with verify/draft-drift.sh,
# ABOUTME: pre-checks its prose and waits on the E2E command by its exit (#633, #796); the layout bullet stays true.
"""Holds the frictions #633 and #796 removed, as AGENTS.md states them.

Two hecaton runs lost their time to the environment. Run 9654 (#610) was dispatched on a bring-up that a run cannot
do: it has no cluster and no AWS profile and may not deploy, while AGENTS.md's cadence rules say to provision a
cluster and validate. Run 9672 (#474) found its approved draft no longer applied, because #609 had moved
`gitops/apps/` into the `lab-bootstrap` chart at `gitops/bootstrap/apps/` in the meantime.

AGENTS.md now has a "Dispatched runs (hecaton)" section for both, and a "Where things live" bullet for the app
layout. This checks that the section says what a run does instead of a bring-up, that the drift check it names
exists and is the one `verify/test_draft_drift.sh` tests, and that the layout bullet stays true: the apps
directory and every profile's values file exist, `gitops/apps/` does not, and the counts test it names exists.

#796 added two more. Run 9604 failed hecaton's ai-isms gate on the repo's nickname, a hype verb to the scanner, in
a file that already read `major`. Run 15816's E2E command outran the 20 minutes it was given in the background, and
`pgrep` by name found other runs' copies of the same scripts. The section's third and fourth items name the words
and the pre-check, `verify/prose_gate.py`, and how the E2E command is waited on; this checks both say so.
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
check("it says to make the design again, not cherry-pick", "rather than cherry-picking it" in draft)
check("it names #474 and #609", "#474" in draft and "#609" in draft)

print("== prose is put through the ai-isms gate before it is committed (#796) ==")
check("the section names runs 9604 and 15816 and #796",
      "Runs 9604 and 15816 lost theirs to the third and the fourth (#796)" in runs_flat)
prose = item(runs, "Prose is put through the ai-isms gate")
check("an item says prose is put through the ai-isms gate", bool(prose))
check("it names the talk's verb and the nickname in backticks", "`Unleash`" in prose and "`Unleashed`" in prose)
check("it names `lets`, read as `let's`", "`lets` is read as `let's`" in prose)
check("it names the records that already read major", all(f in prose for f in ("decisions.md", "PROJECT_STATE.md",
                                                                                  "PROGRESS.md")))
cmd = "python3 verify/prose_gate.py /var/lib/hecaton/app/current/src/hecaton/run/aiisms.py origin/staging"
check(f"it gives the command `{cmd}`", f"`{cmd}`" in prose)
check("verify/prose_gate.py exists", (REPO / "verify" / "prose_gate.py").is_file())
check("verify/test_prose_gate.py tests it",
      "prose_gate.py" in (REPO / "verify" / "test_prose_gate.py").read_text(encoding="utf-8"))

print("== the E2E command runs in the background with an hour's limit (#796) ==")
e2e = item(runs, "The E2E command runs in the background")
check("an item says how the E2E command is waited on", bool(e2e))
check("it gives the limit as 3600000 ms", "3600000 ms" in e2e)
check("it names run 15816 and the 20 minutes", "run 15816" in e2e and "20 minutes" in e2e)
check("it says not to watch it with pgrep", "`pgrep`" in e2e and "other runs on the host" in e2e)
tools = (REPO / "verify" / "run-e2e-tools.sh").read_text(encoding="utf-8")
check("the verdict lines it names are the ones run-e2e-tools.sh prints",
      "checks ran" in tools and "ALL E2E TOOLS TIER CHECKS GREEN" in tools and "`checks ran`" in e2e
      and "`ALL E2E TOOLS TIER CHECKS GREEN`" in e2e)
check("run-e2e-tools.sh prints how long it took", "SECONDS / 60" in tools)

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
