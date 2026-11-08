# ABOUTME: Holds the run-of-show's Night Before stage-switch step (#1184) to verify/stage_switch_run.py: the command and
# ABOUTME: its flags, the switches in talk order, the verdict lines and exit codes it names, and its place in the list.
"""The Night Before step "Every stage switch reaches both clusters" (#1184, the last piece of #1146).

The step tells the presenter which command to run and what its PASS, FAIL and closing lines mean. Each of those is
read from the script here, not typed twice: the flags from its argparse, the switches and their fields from
stage_switch_check.SWITCHES, the closing commands from stage_switch_run.CLOSE, the verdict words from what the script
prints, and the two NOT RUN exit codes from guard_lease.BUSY_EXIT and stage_switch_run.NOT_AT_START_EXIT. The step
sits after the guardrails-switch step (#774), whose guardrails-on and guardrails-off it builds on, and before the
admin probe, which also switches both clusters and holds the same lock.
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import guard_lease  # noqa: E402
import stage_switch_check as ssc  # noqa: E402
import stage_switch_run as ssr  # noqa: E402

ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
ROS = ROS_PATH.read_text(encoding="utf-8")
RUNNER = (HERE / "stage_switch_run.py").read_text(encoding="utf-8")
STEP_TITLE = "**Every stage switch reaches both clusters (#1146)"
GUARDRAILS_TITLE = "**The guardrails switch reaches both clusters (#774).**"
PROBE_TITLE = "**Every shown beat works, on the clusters that will be on stage (#503).**"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def section(text: str, heading: str) -> str:
    """The body under a markdown heading, up to the next heading of the same or a higher level."""
    m = re.search(rf"^(#+) {re.escape(heading)}\s*$", text, re.M)
    if not m:
        return ""
    level = len(m.group(1))
    rest = text[m.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def steps(body: str) -> list[str]:
    """Each top-level checklist item of a section, its continuation lines included."""
    return [s for s in re.split(r"^(?=- \[ \] )", body, flags=re.M) if s.startswith("- [ ] ")]


def unwrap(text: str) -> str:
    """The step's prose with its line breaks and indentation folded to single spaces, so a wrapped phrase matches."""
    return re.sub(r"\s+", " ", text)


night = section(ROS, "Night Before")
items = steps(night)
titles = [i.splitlines()[0] for i in items]

print("== the anchors this test reads ==")
for anchor in (STEP_TITLE, GUARDRAILS_TITLE, PROBE_TITLE):
    found = any(anchor in t for t in titles)
    check(f"the Night Before list has the step {anchor!r} ({ROS_PATH.relative_to(REPO)})", found)
if failures:
    print(f"\n{len(failures)} FAILED: an anchor above is missing from {ROS_PATH.relative_to(REPO)}", file=sys.stderr)
    sys.exit(1)


def index(anchor: str) -> int:
    return next(n for n, t in enumerate(titles) if anchor in t)


step = items[index(STEP_TITLE)]
flat = unwrap(step)
fence = re.search(r"```bash\n(.*?)```", step, re.S)
command = unwrap(fence.group(1).replace("\\\n", " ")).strip() if fence else ""

print("== where the step sits ==")
check("it comes after the guardrails-switch step (#774), whose commands it runs",
      index(GUARDRAILS_TITLE) < index(STEP_TITLE))
check("it comes before the admin probe, which switches both clusters under the same lock",
      index(STEP_TITLE) < index(PROBE_TITLE))
title = flat[: flat.find(".**") + 3]
check(f"its bold title says it runs after #1132's switches are built ({title!r})",
      "after #1132's switches are built" in title)

print("== the command is the script's, with the flags it takes ==")
check("the step has one bash block", bool(fence) and step.count("```bash") == 1)
check("the block runs verify/stage_switch_run.py from the repo root", command.startswith("python3 verify/stage_switch_run.py "))
flags = re.findall(r"(--[a-z-]+)", command)
taken = set(re.findall(r'add_argument\("(--[a-z-]+)"', RUNNER))
check(f"every flag the block passes is one the script takes ({flags} within {sorted(taken)})",
      bool(flags) and set(flags) <= taken)
check("the block names the private cluster's context explicitly (no current-context)", "--context <private-context>" in command)
check("the block passes an isolated kubeconfig and the AWS profile",
      "--kubeconfig /tmp/private.kubeconfig" in command and "--profile accen-dev" in command)

print("== the switches, their fields and the closing pair are the script's ==")
names = [f"`{s}`" for s in ssc.SWITCHES]
talk_order = f"runs {', '.join(names[:-1])} and {names[-1]} in talk order"
check(f"the step says it {talk_order!r}", talk_order in flat)
for switch, fields in ssc.SWITCHES.items():
    if switch == "guardrails-on":
        continue  # the step names its four fields as "the four Kubernetes guardrails"
    for _, key in fields:
        check(f"the PASS bullet names {switch}'s field {key}", f"`{key}`" in flat)
check(f"the step names the closing pair in order ({', '.join(ssr.CLOSE)})",
      0 <= flat.find(f"`{ssr.CLOSE[0]}` and `{ssr.CLOSE[1]}`"))
check("the step names both hosts the script reads",
      all(f"`{h}`" in flat for h in ssc.CLUSTERS.values()))

print("== PASS, FAIL and the verdict lines are what the script prints ==")
check("the step has a PASS bullet and a FAIL bullet", "- **PASS**" in step and "- **FAIL**" in step)
for word in ("start-state", "as-found", "terminal"):
    check(f"the step explains the {word!r} lines", f"`{word}`" in flat)
    check(f"the script prints a {word!r} line", f'"{word}"' in RUNNER)
for verdict in ("STAGE SWITCH CHECK GREEN", "STAGE SWITCH CHECK RED", "STAGE SWITCH CHECK NOT RUN"):
    check(f"the step names {verdict!r}", f"`{verdict}" in flat)
    check(f"the script prints {verdict!r}", verdict in RUNNER)
check("GREEN is exit 0 and RED exit 1 in the step", "`STAGE SWITCH CHECK GREEN` (exit 0)" in flat
      and "`STAGE SWITCH CHECK RED` (exit 1)" in flat)
check(f"the step's busy-lock exit is guard_lease.BUSY_EXIT ({guard_lease.BUSY_EXIT})",
      f"exit {guard_lease.BUSY_EXIT} is another run holding the lock" in flat)
check(f"the step's not-at-start exit is stage_switch_run.NOT_AT_START_EXIT ({ssr.NOT_AT_START_EXIT})",
      f"exit {ssr.NOT_AT_START_EXIT} is a cluster not at the start state" in flat)
check("the step says the summary names the lines that wait on #1132", "wait on #1132" in flat
      and "waiting on #1132" in RUNNER)
check("each -off command the FAIL bullet names is one the terminal has",
      all(f'"$HOME/{c}"' in (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text(encoding="utf-8")
          for c in re.findall(r"`(guard-[a-z]+-off)`", flat)) and bool(re.findall(r"`(guard-[a-z]+-off)`", flat)))

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nALL STAGE-SWITCH NIGHT BEFORE STEP CHECKS PASS")
