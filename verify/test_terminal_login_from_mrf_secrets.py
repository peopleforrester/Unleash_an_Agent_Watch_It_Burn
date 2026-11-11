# ABOUTME: Holds #912: CLAUDE.md tells a dispatched run the KubeCon pair's presenter terminal login comes from
# ABOUTME: mrf-secrets by fleet.sh alone, and fleet.sh no longer refuses the pair (#1074's guard is gone).
"""From 2026-11-07 the presenter terminal login on watch-it-burn-private and watch-it-burn-community was set by hand
(#1069), and fleet.sh refused to write it there (#1074). On 2026-11-11 Michael lifted that hold (#912): the login is
in mrf-secrets (`projects/watch-it-burn-terminal.env`, which he committed on 2026-11-09), and it reaches both clusters
by fleet.sh's path, `terminal-password` or a bring-up.

This holds the CLAUDE.md rule that says so, word for word in the sentences that bind a run, and holds that fleet.sh
has no guard left that singles out the pair: `terminal_login_hand_set` and `HAND_SET_TERMINAL_LOGINS` are gone, and
both writers go straight to `terminal_creds_for`, which gives the pair the presenter login from mrf-secrets. What each
writer then does on the pair is held by verify/test_fleet_terminal_harvest.sh (bring-up) and
verify/test_admin_actions.sh (`terminal-password`).
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
CLAUDE = REPO / "CLAUDE.md"
FLEET = REPO / "infra" / "terraform" / "fleet" / "fleet.sh"
PAIR = ("watch-it-burn-community", "watch-it-burn-private")

# fleet.sh is sourced below, so the cloud tools are stubs and the cloud environment is cleared (#859).
sys.path.insert(0, str(REPO / "verify"))
import no_cloud  # noqa: E402
no_cloud.setup()

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


print("== CLAUDE.md's Dispatched runs section keeps the rule (#912) ==")
claude = CLAUDE.read_text(encoding="utf-8")
runs = section(claude, "Dispatched runs (hecaton)")
check("CLAUDE.md has a '## Dispatched runs (hecaton)' section", bool(runs.strip()), str(CLAUDE))
LABEL = "The presenter terminal login on the two KubeCon clusters comes from mrf-secrets, by fleet.sh alone"
rule = item(runs, LABEL)
check(f"an item there is labelled {LABEL!r}", bool(rule))
for sentence in (
    "A run writes the `agent/terminal-auth` Secret (`TTYD_CREDENTIAL`) on watch-it-burn-private or "
    "watch-it-burn-community only through `infra/terraform/fleet/fleet.sh` (its `terminal-password` verb, or a "
    "bring-up that finds no Secret), from that file, and never generates, invents or puts back any other login there.",
    "A live check reads the login from that Secret or that file, never from an issue, a commit or a transcript, and "
    "never prints it.",
):
    check(f"it says: {sentence}", sentence in rule)
check("it names the file and its two keys",
      all(s in rule for s in ("`projects/watch-it-burn-terminal.env`", "`WIB_TERMINAL_USER`", "`WIB_TERMINAL_PASSWORD`")))
check("it names #1069 and #1074, the hold, and #912, which lifted it", all(s in rule for s in ("#1069", "#1074", "#912")))
check("no item still says no run touches the login",
      "No run touches the presenter terminal login" not in claude and "`terminal_login_hand_set`" not in claude)

print("== fleet.sh singles out neither KubeCon cluster ==")
src = FLEET.read_text(encoding="utf-8")
check("fleet.sh has no HAND_SET_TERMINAL_LOGINS", "HAND_SET_TERMINAL_LOGINS" not in src)
check("fleet.sh has no terminal_login_hand_set", "terminal_login_hand_set" not in src)
check("fleet.sh records no terminal-login-by-hand failure", "terminal-login-by-hand" not in src)
for fn in ("bootstrap_terminal_auth", "terminal_password_one"):
    body = function(src, fn)
    check(f"{fn} exists in fleet.sh", bool(body))
    check(f"{fn} takes the login from terminal_creds_for", 'terminal_creds_for "${name}"' in body)
    check(f"{fn} refuses no cluster by name", not re.search(r"watch-it-burn-(community|private)", body))

print("== the pair is handed the presenter login, which is read from mrf-secrets ==")
# Sourced with a test-owned env file, so terminal_creds_for reads the presenter login as fleet.sh reads mrf-secrets.
# The values are placeholders this test owns; it prints only whether each cluster got the presenter one.
script = (
    f'source "{FLEET}" >/dev/null 2>&1 </dev/null; '
    'for n in "$@"; do c="$(terminal_creds_for "$n" 2>/dev/null)" || c=NONE; '
    '[[ "$c" == "placeholder-user:placeholder-pw" ]] && echo "$n presenter" || echo "$n other"; done'
)
probe = {**{n: "presenter" for n in PAIR}, "watch-it-burn-whitney-admin": "presenter",
         "watch-it-burn-attendee-007": "other"}
with tempfile.TemporaryDirectory() as env_dir:
    env_file = pathlib.Path(env_dir) / "watch-it-burn-terminal.env"
    env_file.write_text("WIB_TERMINAL_USER=placeholder-user\nWIB_TERMINAL_PASSWORD=placeholder-pw\n", encoding="utf-8")
    env = {**os.environ, "WIB_TERMINAL_ENV": str(env_file), "WIB_TERMINAL_USER": "", "WIB_TERMINAL_PASSWORD": ""}
    r = subprocess.run(["bash", "-c", script, "_", *probe], cwd=FLEET.parent, capture_output=True, text=True,
                       timeout=60, env=env)
got = dict(line.split() for line in r.stdout.splitlines() if len(line.split()) == 2)
check("fleet.sh sources and answers for every probe name", set(got) == set(probe), r.stderr.strip()[-300:])
for name, want in probe.items():
    check(f"terminal_creds_for {name} is the {want} login", got.get(name) == want)

print("== offline means offline ==")
_calls = no_cloud.calls()
check("no check above called the real aws, kubectl, eksctl, terraform or helm", not _calls)
if _calls:
    print("".join(f"        {line}\n" for line in _calls.splitlines()), end="")

print(f"\n{'FAIL' if failures else 'PASS'}: {len(failures)} failed")
sys.exit(1 if failures else 0)
