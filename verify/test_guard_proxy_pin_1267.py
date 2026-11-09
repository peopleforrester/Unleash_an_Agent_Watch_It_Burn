#!/usr/bin/env python3
# ABOUTME: Fails unless gitops/ai-layer/guard-proxy pins a guard-proxy-agenticburn main commit at or after a7a5a36, the
# ABOUTME: always-on code-of-conduct check on /chat (#1267, guard-proxy#78), and checksum/proxy-py is that build's.
"""#1267's repin: Michael asked on the issue (2026-11-09) for the `gitops/ai-layer/guard-proxy` submodule at
a7a5a36924e7 and `checksum/proxy-py` at 5caafc6044af. a7a5a36 refuses a `/chat` prompt carrying a code-of-conduct term
before any guard, limit or agent and masks every such term in the reply, whatever `/toggle` says. A repin back to a
commit before it would drop that check from the stage with every other test green, since test_guard_proxy_pin_1225.py's
floor is a637e68, the commit just before it.

What it holds, offline, against the submodule clone ensure-submodules.sh checks out from the host mirror:
  - guard-proxy's docs/release-notes.md on origin/main has one 2026-11-09 entry headed "/chat refuses and masks
    code-of-conduct terms" that names commit a7a5a36 and says to repin to it "or a later one"
  - the gitlink is on the clone's origin/main and a7a5a36 is an ancestor of it, or it
  - the pinned proxy.py defines conduct_matches and answers `always_on` in /controls, the check's two marks
  - the guard-proxy Deployment's checksum/proxy-py is sha256(`git show <pin>:proxy.py`)[:12]
Then the same verdict on guard-proxy's own history: a7a5a36 with its own checksum holds; a637e68 (the pin before
this repin) fails as predating the floor with its own checksum; the current pin with a637e68's checksum fails on it.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SUB_PATH = "gitops/ai-layer/guard-proxy"
SUB = REPO / SUB_PATH
RES = REPO / "gitops/ai-layer/resources.yaml"
NOTES = "docs/release-notes.md"
ENTRY = "## 2026-11-09: /chat refuses and masks code-of-conduct terms"
FLOOR = "a7a5a36924e718145522d97bc7d06117e56907a5"  # guard-proxy-agenticburn#78, the always-on /chat check
OLD_PIN = "a637e68eb76ef255bee951e84735d04f342b77c8"  # the pin before #1267's repin, with no such check
MARKS = ("def conduct_matches(", '"always_on"')
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def git(*args: str, cwd: pathlib.Path = SUB) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def has_commit(sha: str) -> bool:
    return git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def is_ancestor(a: str, b: str) -> bool:
    return git("merge-base", "--is-ancestor", a, b).returncode == 0


def proxy_at(sha: str) -> bytes:
    out = git("show", f"{sha}:proxy.py")
    if out.returncode != 0:
        print(f"\nFAILED: {SUB_PATH} has no proxy.py at {sha[:12]}: {out.stderr.decode().strip()}")
        sys.exit(1)
    return out.stdout


def build_checksum(sha: str) -> str:
    return hashlib.sha256(proxy_at(sha)).hexdigest()[:12]


def verdict(pin: str, annotation: str | None, main: str) -> list[tuple[str, str]]:
    """Each way #1267's repin does not hold for this pin and annotation, as (pin or checksum, why); empty when it does."""
    if not has_commit(pin):
        return [("pin", f"the pin {pin[:12]} is not in the {SUB_PATH} clone; no remote served it")]
    problems = []
    if not is_ancestor(pin, main):
        problems.append(("pin", f"the pin {pin[:12]} is not on guard-proxy origin/main (head {main[:12]})"))
    if not is_ancestor(FLOOR, pin):
        problems.append(("pin", f"the pin {pin[:12]} predates a7a5a36924e7, the always-on code-of-conduct check on "
                                f"/chat; pin a7a5a36 or a main commit after it"))
    want = build_checksum(pin)
    if annotation != want:
        problems.append(("checksum", f"checksum/proxy-py is {annotation!r}, the pinned build's proxy.py hashes to "
                                     f"{want!r}; set it to {want} in gitops/ai-layer/resources.yaml"))
    return problems


print("== the guard-proxy pin and its clone ==")
tree = git("ls-tree", "HEAD", "--", SUB_PATH, cwd=REPO).stdout.decode().split()
pin = tree[2] if len(tree) >= 3 and tree[0] == "160000" else ""
check(f"{SUB_PATH} is a submodule gitlink", bool(pin), f"ls-tree said {tree}")
# An uninitialised submodule directory is not a repo, and git -C would answer from the superproject's own refs.
top = git("rev-parse", "--show-toplevel").stdout.decode().strip()
if not pin or pathlib.Path(top or "/nonexistent").resolve() != SUB.resolve():
    print(f"\nFAILED: {SUB_PATH} is not initialised; run bash verify/ensure-submodules.sh")
    sys.exit(1)
main_rev = git("rev-parse", "-q", "--verify", "refs/remotes/origin/main^{commit}")
if main_rev.returncode != 0:
    print(f"\nFAILED: {SUB_PATH} has no origin/main ref; run bash verify/ensure-submodules.sh, which reads the mirror")
    sys.exit(1)
main = main_rev.stdout.decode().strip()
for sha in (FLOOR, OLD_PIN):
    if not has_commit(sha):
        print(f"\nFAILED: {SUB_PATH} has no commit {sha[:12]}; its clone is not guard-proxy-agenticburn's")
        sys.exit(1)

print(f"== guard-proxy's {NOTES}: {ENTRY!r} ==")
notes = git("show", f"{main}:{NOTES}")
if notes.returncode != 0:
    print(f"\nFAILED: guard-proxy origin/main has no {NOTES}: {notes.stderr.decode().strip()}")
    sys.exit(1)
entries = re.split(r"(?m)^(?=## )", notes.stdout.decode())
mine = [e for e in entries if e.startswith(ENTRY)]
if len(mine) != 1:
    print(f"\nFAILED: guard-proxy origin/main's {NOTES} has {len(mine)} entries headed {ENTRY!r}, not one; "
          "the floor below is read from that entry")
    sys.exit(1)
flat = " ".join(mine[0].split())  # the notes wrap their lines, so a phrase can cross a line break
check("the entry names commit a7a5a36", "commit a7a5a36" in flat, mine[0][:400])
check("the entry says to repin the submodule and checksum/proxy-py to its commit or a later one",
      "checksum/proxy-py" in flat and "this entry's commit (or a later one)" in flat, mine[0][:400])
check("a7a5a36924e7 is on guard-proxy origin/main", is_ancestor(FLOOR, main), f"origin/main is {main[:12]}")

docs = [d for d in yaml.safe_load_all(RES.read_text(encoding="utf-8")) if d]
deploys = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy"]
check("gitops/ai-layer/resources.yaml has one guard-proxy Deployment", len(deploys) == 1, f"found {len(deploys)}")
annotation = (deploys[0]["spec"]["template"]["metadata"].get("annotations") or {}).get("checksum/proxy-py") \
    if deploys else None

print(f"== this repo: the pin {pin[:12]} and checksum/proxy-py {annotation!r} ==")
problems = verdict(pin, annotation, main)
why = "; ".join(w for _, w in problems)
check(f"{SUB_PATH} pins a guard-proxy main commit at a7a5a36924e7 or later", not any(k == "pin" for k, _ in problems), why)
check(f"checksum/proxy-py matches the pinned build's proxy.py", not any(k == "checksum" for k, _ in problems), why)
src = proxy_at(pin).decode("utf-8", "replace") if has_commit(pin) else ""
for mark in MARKS:
    check(f"the pinned proxy.py carries {mark!r}, a mark of the always-on check", mark in src)

print("== the same verdict on guard-proxy's own history ==")
got = verdict(FLOOR, build_checksum(FLOOR), main)
check("a7a5a36 itself, with its own checksum, holds", got == [], f"got {got}")
got = verdict(OLD_PIN, build_checksum(OLD_PIN), main)
check("a637e68, the pin before this repin, fails as predating a7a5a36 even with its own checksum",
      len(got) == 1 and got[0][0] == "pin" and "predates a7a5a36924e7" in got[0][1], f"got {got}")
old_src = proxy_at(OLD_PIN).decode("utf-8", "replace")
check("a637e68's proxy.py lacks the check's marks, so the mark check can fail", not any(m in old_src for m in MARKS))
if build_checksum(pin) != build_checksum(OLD_PIN):
    stale = verdict(pin, build_checksum(OLD_PIN), main)
    check("the current pin with a637e68's checksum fails on the checksum", "checksum" in [k for k, _ in stale],
          f"got {stale}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print(f"\nguard-proxy is pinned at {pin[:12]}, on main at or after a7a5a36 (the always-on code-of-conduct check), and "
      "checksum/proxy-py is its build's.")
