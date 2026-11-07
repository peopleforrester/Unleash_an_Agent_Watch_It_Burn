# ABOUTME: Holds #1074: CLAUDE.md tells a dispatched run it never writes agent/terminal-auth on the KubeCon pair,
# ABOUTME: whose presenter login was set by hand (#1069), and fleet.sh's guard names exactly those two and runs first.
"""The presenter terminal login on watch-it-burn-private and watch-it-burn-community was set by hand on 2026-11-07
(#1069), to one Michael and Whitney can remember, and Michael asked that hecaton leave it alone (#1074). A run takes
its instructions from this repo, so CLAUDE.md (a link to AGENTS.md) says so in its "Dispatched runs (hecaton)"
section, and `infra/terraform/fleet/fleet.sh`, the one script that wrote the Secret, refuses to on those two.

This holds the two CLAUDE.md sentences the issue asks for, word for word, so a later edit cannot drop them, and holds
fleet.sh's guard: `terminal_login_hand_set` is true for the two names and nothing else (sourced and called), and
both writers ask it before they read a login to write. What each writer then does on the pair, and that it still
writes elsewhere, is held by verify/test_fleet_terminal_harvest.sh (bring-up) and verify/test_admin_actions.sh
(`terminal-password`).
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
CLAUDE = REPO / "CLAUDE.md"
FLEET = REPO / "infra" / "terraform" / "fleet" / "fleet.sh"
PAIR = ("watch-it-burn-community", "watch-it-burn-private")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def item(body: str, label: str) -> str:
    """The numbered item whose bold label starts with `label`, continuation lines included."""
    m = re.search(rf"^\d+\. \*\*{re.escape(label)}.*?(?=^\d+\. |^\S|\Z)", body, re.M | re.S)
    return flat(m.group(0)) if m else ""


def function(src: str, name: str) -> str:
    """The body of the bash function `name() {` up to its closing brace at column 0."""
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}", src, re.M | re.S)
    return m.group(1) if m else ""


print("== CLAUDE.md's Dispatched runs section keeps the rule (#1074) ==")
claude = CLAUDE.read_text(encoding="utf-8")
runs = section(claude, "Dispatched runs (hecaton)")
check("CLAUDE.md has a '## Dispatched runs (hecaton)' section", bool(runs.strip()), str(CLAUDE))
LABEL = "No run touches the presenter terminal login on the two KubeCon clusters"
rule = item(runs, LABEL)
check(f"an item there is labelled {LABEL!r}", bool(rule))
for sentence in (
    "No run creates, rotates, regenerates or restores the `agent/terminal-auth` Secret (`TTYD_CREDENTIAL`) on "
    "watch-it-burn-private or watch-it-burn-community, in converge, reset or bring-up paths included.",
    "A live check reads the login from that Secret, never from an issue, a commit or a transcript, and never prints it.",
):
    check(f"it says: {sentence}", sentence in rule)
check("it names #1069, where the login was set by hand, and #1074", "#1069" in rule and "#1074" in rule)
check("it names the guard in fleet.sh", "`terminal_login_hand_set`" in rule and "`infra/terraform/fleet/fleet.sh`" in rule)

print("== fleet.sh's guard is the KubeCon pair and nothing else ==")
src = FLEET.read_text(encoding="utf-8")
m = re.search(r'^readonly HAND_SET_TERMINAL_LOGINS="([^"]*)"$', src, re.M)
check("fleet.sh declares HAND_SET_TERMINAL_LOGINS", bool(m))
check("it lists exactly the two KubeCon clusters", bool(m) and sorted(m.group(1).split()) == sorted(PAIR),
      m.group(1) if m else "absent")
probe = {**{n: True for n in PAIR},
         "watch-it-burn-community-b01": False, "watch-it-burn-private-b01": False,
         "watch-it-burn-whitney-admin": False, "watch-it-burn-attendee-007": False,
         "watch-it-burn": False, "community": False}
script = f'source "{FLEET}" >/dev/null 2>&1 </dev/null; for n in "$@"; do terminal_login_hand_set "$n" && echo "$n yes" || echo "$n no"; done'
r = subprocess.run(["bash", "-c", script, "_", *probe], cwd=FLEET.parent, capture_output=True, text=True, timeout=60)
got = dict(line.split() for line in r.stdout.splitlines() if len(line.split()) == 2)
check("fleet.sh sources and answers for every probe name", set(got) == set(probe), r.stderr.strip()[-300:])
for name, want in probe.items():
    check(f"terminal_login_hand_set {name} is {'true' if want else 'false'}", got.get(name) == ("yes" if want else "no"))

print("== both writers ask the guard before they read a login to write ==")
for fn, first_write in (("bootstrap_terminal_auth", "terminal_creds_for"), ("terminal_password_one", "terminal_creds_for")):
    body = function(src, fn)
    g, w = body.find('terminal_login_hand_set "${name}"'), body.find(first_write)
    check(f"{fn} exists in fleet.sh", bool(body))
    check(f"{fn} asks terminal_login_hand_set before {first_write}", 0 <= g < w, f"guard at {g}, {first_write} at {w}")

print(f"\n{'FAIL' if failures else 'PASS'}: {len(failures)} failed")
sys.exit(1 if failures else 0)
