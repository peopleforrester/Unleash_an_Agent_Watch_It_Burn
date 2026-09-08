# ABOUTME: The student's shell opens on a prompt and nothing else; the only thing it may print is the
# ABOUTME: warning that fires when kubectl was NOT configured, because a broken terminal must say so.
"""Keeps the terminal banner gone (#342).

The shell used to greet a student with seven lines: a welcome, what kubectl and aws were wired to, two
commands to flip guardrails, one to list every service and password, and a list of five AI CLIs. Michael
asked for all of it removed.

Two of those lines were doing active harm. `guards-on`/`guards-off` is our abstraction, not anything
Kubernetes has, and Whitney's ruling is that a student never meets it: they install each control themselves
and know it by its real name. `platform` is the command she asked to remove outright. A banner is also the
easiest place for orientation to drift out of step with the lab page that owns it.

The failure path stays. When there is no ServiceAccount token, kubectl is genuinely not configured, and a
terminal that is broken and silent is worse than one that is chatty.

Both copies of the entrypoint are checked. They are byte-identical by design and a fix applied to one is
the oldest way for them to drift.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
COPIES = {
    "images/web-terminal/entrypoint.sh": (REPO / "images/web-terminal/entrypoint.sh").read_text(encoding="utf-8"),
    "gitops/ai-layer/web-terminal/entrypoint.sh": (REPO / "gitops/ai-layer/web-terminal/entrypoint.sh").read_text(encoding="utf-8"),
}

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the two copies have not drifted ==")
vals = list(COPIES.values())
check("both entrypoints are identical", vals[0] == vals[1])

BANNED = [
    ("Welcome to your Watch It Burn cluster shell", "the greeting"),
    ("kubectl is wired to your cluster", "orientation the lab page already gives"),
    ("aws is ready with your keys", "same"),
    ("guards-on   guards-off", "our guardrail abstraction, which a student never meets"),
    ("see which guards are on", "same"),
    ("every service, URL and password", "the platform command Whitney asked to remove"),
    ("AI coding CLIs are installed", "a menu nobody asked for"),
    ("kubectl is configured for THIS cluster", "a success message"),
    ("aws is configured with your keys", "a success message"),
    ("This terminal requires the username and password", "said after they have already logged in"),
]
print("== nothing is printed on a working shell ==")
for phrase, why in BANNED:
    hit = [n for n, t in COPIES.items() if phrase in t]
    check(f"{phrase!r} is gone ({why})", not hit)

print("== what the .bashrc still does ==")
for name, t in COPIES.items():
    m = re.search(r"cat > \"\$HOME/\.bashrc\" <<'BRC'\n(.*?)\nBRC", t, re.S)
    check(f"{name}: the bashrc block exists", m is not None)
    if not m:
        continue
    body = m.group(1)
    echoes = [l for l in body.splitlines() if l.strip().startswith("echo ")]
    check(f"{name}: it echoes nothing ({len(echoes)} echo lines)", not echoes)
    check(f"{name}: it still shows .motd, which is where a failure lands", "cat ~/.motd" in body)
    check(f"{name}: it still sets the prompt and PATH", "PS1=" in body and "PATH=" in body)

print("== a broken terminal still says so ==")
for name, t in COPIES.items():
    check(f"{name}: the no-token warning survives",
          "WARNING: no in-cluster ServiceAccount token found" in t)
    # The file must start empty, or a stale motd from a previous layer would print on a healthy shell.
    check(f"{name}: motd starts empty on the success path", ': > "$HOME/.motd"' in t)

print("== the coding CLIs are not installed in the image (#350) ==")
# Whitney: "coding CLIs, uninstall." The banner no longer names them (above); the image no longer ships
# them. Assert the Dockerfile installs none, so a well-meaning re-add is caught.
DOCKER = (REPO / "images/web-terminal/Dockerfile").read_text(encoding="utf-8")
check("no coding-agent CLI is installed",
      not __import__("re").search(r"(claude-code|gemini-cli|@openai/codex|opencode-ai|aider-chat)", DOCKER))
check("the removal is explained", "No AI coding CLIs" in DOCKER)

print("== the guard toggles still EXIST, they are just not advertised ==")
# Removing the banner must not remove the commands: the lab's fix cards invoke them by name.
for name, t in COPIES.items():
    check(f"{name}: guards-status is still installed", '"$HOME/guards-status"' in t)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All terminal-quiet checks passed.")
