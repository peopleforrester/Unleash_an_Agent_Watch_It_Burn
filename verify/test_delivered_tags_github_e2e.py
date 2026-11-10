# SUITE: e2e
# E2E TIER: tools
# ABOUTME: GitHub's `delivered/<event>` tags are the pinned annotated tag objects on the pinned commits (#971).
# ABOUTME: Needs network: one `git ls-remote` on the public repo, no credentials. Fails when GitHub cannot be read.
"""#954 checked by hand that GitHub's `delivered/devopsdays-portland-2026` ref and the local clone named the same
object. verify/test_delivered_tags.py holds the clone's refs offline; this holds GitHub's, which a force-push or a
delete in the web UI changes without touching any clone. The pins are in verify/delivered_tags.py.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import delivered_tags as dt  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# A read that hangs is asked again, up to TRIES times of TIMEOUT seconds each, as ghcr_pull.py asks a dropped
# connection again (#1047): in CI run 42866956234 one `git ls-remote` from Tanjiro hung for its whole 120 s, with no
# answer from GitHub, and the tier went red on it (#1314). An answer, a refusal or a non-zero exit, is never asked
# again: only the hang is.
TRIES, TIMEOUT = 3, 60
print(f"== GitHub's delivered tags ({dt.GITHUB_URL}) ==")
for attempt in range(1, TRIES + 1):
    try:
        res = subprocess.run(["git", "ls-remote", "--tags", dt.GITHUB_URL, "refs/tags/delivered/*"],
                             capture_output=True, text=True, timeout=TIMEOUT,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        out, err, rc = res.stdout, res.stderr, res.returncode
        break
    except subprocess.TimeoutExpired:
        out, err, rc = "", f"git ls-remote timed out after {TIMEOUT} s, {attempt} of {TRIES} tries", 124
        print(f"  {err}")
check("git ls-remote read GitHub's tags", rc == 0, f"exit {rc}: {err.strip()}")
if rc == 0:
    refs = dt.parse_ls_remote(out)
    for name, (tag_obj, commit) in dt.PINS.items():
        found = dt.problems_remote({name: refs[name]} if name in refs else {}, {name: (tag_obj, commit)})
        check(f"{name} on GitHub is annotated tag object {tag_obj[:8]} on commit {commit[:8]}", not found,
              "; ".join(found))

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nALL GITHUB DELIVERED TAG CHECKS PASS")
