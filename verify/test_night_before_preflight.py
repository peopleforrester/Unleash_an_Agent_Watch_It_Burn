# ABOUTME: Holds the KubeCon Night Before preflight (#534): it runs before the roster bring-up, scoped to the
# ABOUTME: account the roster lives in, with a count that covers every roster cluster.
"""The KubeCon Night Before runs `fleet.sh preflight` before `instructors up` (#534).

preflight.sh is the read-only gate that exists to fail BEFORE money is committed. The run-of-show listed it
after "Platform up on AWS", so it ran once the roster was already billing. It also ran unscoped, and the
default WIB_ATTENDEE_ACCOUNTS names the four student accounts, which have no lab VPC for KubeCon, so it
failed on them however ready accen-dev was.

The account and the count are derived, not typed twice: every roster cluster lives in WIB_DEFAULT_ACCOUNT
(roster.tsv), and the preflight count is clusters per account, so it has to equal the roster's row count.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")
FLEET = (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8")
PREFLIGHT = (REPO / "infra/terraform/fleet/preflight.sh").read_text(encoding="utf-8")
ROSTER = (REPO / "infra/terraform/fleet/roster.tsv").read_text(encoding="utf-8")

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


night = section(ROS, "Night Before")
roster_rows = [ln for ln in ROSTER.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
default_account = re.search(r'^WIB_DEFAULT_ACCOUNT="\$\{WIB_DEFAULT_ACCOUNT:-([^}]+)\}"', FLEET, re.M)
attendee_default = re.search(r'^WIB_ATTENDEE_ACCOUNTS="\$\{WIB_ATTENDEE_ACCOUNTS:-([^}]+)\}"', PREFLIGHT, re.M)

print("== the inputs this test derives from ==")
check("the run-of-show has a Night Before section", bool(night))
check("roster.tsv has rows", bool(roster_rows))
check("fleet.sh sets a default account", bool(default_account))
check("preflight.sh sets a default attendee account list", bool(attendee_default))
if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
acct = default_account.group(1)

print("== the preflight is scoped and sized for the roster ==")
runs = re.findall(r"`([^`]*\./fleet\.sh preflight[^`]*)`", night)
check("Night Before runs fleet.sh preflight exactly once", len(runs) == 1)
cmd = runs[0] if runs else ""
check(f"the preflight is scoped to the roster's account: WIB_ATTENDEE_ACCOUNTS={acct}",
      cmd.startswith(f"WIB_ATTENDEE_ACCOUNTS={acct} "))
check("the default attendee list is wider than the roster's account, so the scope is needed",
      attendee_default.group(1).split(",") != [acct])
count = re.search(r"preflight (\d+)$", cmd)
check(f"the preflight count is the roster's {len(roster_rows)} clusters per account",
      bool(count) and int(count.group(1)) == len(roster_rows))
check("every roster cluster lives in the default account (roster.tsv says so)",
      "Every roster cluster lives in WIB_DEFAULT_ACCOUNT" in ROSTER)

print("== the preflight runs before anything is brought up ==")
pre_at = night.find(f"`{cmd}`") if cmd else -1
up_at = night.find("./fleet.sh instructors up")
check("Night Before brings the roster up with instructors up", up_at != -1)
check("the preflight comes before instructors up", -1 < pre_at < up_at)
check("the step says it must end PREFLIGHT GREEN", "PREFLIGHT GREEN" in night[:up_at])
check("preflight.sh prints PREFLIGHT GREEN on success", "PREFLIGHT GREEN" in PREFLIGHT)
check("the boundary step points at the preflight step, not a stale command",
      "./fleet.sh preflight 1" not in night)

if failures:
    print(f"\n{len(failures)} FAILED", file=sys.stderr)
    sys.exit(1)
print("\nNIGHT BEFORE PREFLIGHT GREEN")
