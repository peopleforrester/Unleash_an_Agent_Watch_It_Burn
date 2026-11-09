#!/usr/bin/env python3
# ABOUTME: Fails unless gitops/ai-layer/guard-proxy pins a guard-proxy-agenticburn main commit at or after a637e68, the
# ABOUTME: commit of its 2026-11-08 release-notes entry for #77, and checksum/proxy-py is that pinned build's proxy.py (#1259).
"""#1225's criterion, held by #1259: `gitops/ai-layer/guard-proxy` and `checksum/proxy-py` point at a guard-proxy main
commit at or after the 2026-11-08 release-notes entry for guard-proxy-agenticburn#77 (each `/chat` `tasks/get` poll goes
out unsampled and leaves no span). test_guard_proxy_pin_1048.py holds main ancestry and the checksum but its floor is
dc78f1c (#1048), so a repin back to be88e1f, the pin before #1225, with be88e1f's own checksum passed every test.

What it holds, offline, against the submodule clone ensure-submodules.sh checks out from the host mirror:
  - guard-proxy's docs/release-notes.md on origin/main has the 2026-11-08 entry naming guard-proxy-agenticburn#77, and
    the commit that added that entry's heading is a637e68, the floor below. The entry says "Repin ... to this entry's
    commit (or a later one)", so the floor is read from guard-proxy's own record, not only from this file.
  - the gitlink names a commit the clone has, reachable from the clone's origin/main
  - a637e68 is an ancestor of the pin, or the pin itself
  - the guard-proxy Deployment's checksum/proxy-py is sha256(`git show <pin>:proxy.py`)[:12], the pinned build's bytes
    and not whatever the working tree holds
Then it runs the same verdict on guard-proxy's own history, so each way the criterion can stop holding is seen to fail:
a637e68 with its own checksum passes; be88e1f (the pin #1225 moved off) and 3c68224 (main's commit just before the
entry) each fail as predating a637e68 with their own checksums; the current pin with be88e1f's checksum fails on the
checksum, and so does the current pin with no checksum/proxy-py.
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
ENTRY_DATE = "2026-11-08"
ENTRY_ISSUE = "guard-proxy-agenticburn#77"
FLOOR = "a637e68eb76ef255bee951e84735d04f342b77c8"  # the commit of the 2026-11-08 release-notes entry for #77
OLD_PIN = "be88e1f"  # the pin before #1225's repin, which carries no #77
BEFORE = "3c68224"  # main's commit just before a637e68 (guard-proxy-agenticburn#76), so one short of the entry
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def git(*args: str, cwd: pathlib.Path = SUB) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)


def full(rev: str) -> str:
    out = git("rev-parse", "-q", "--verify", f"{rev}^{{commit}}")
    if out.returncode != 0:
        print(f"\nFAILED: {SUB_PATH} has no commit {rev}; its clone is not guard-proxy-agenticburn's")
        sys.exit(1)
    return out.stdout.decode().strip()


def has_commit(sha: str) -> bool:
    return git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def is_ancestor(a: str, b: str) -> bool:
    return git("merge-base", "--is-ancestor", a, b).returncode == 0


def build_checksum(sha: str) -> str:
    """The checksum/proxy-py value for the build at `sha`: the first 12 hex of the sha256 of its proxy.py."""
    out = git("show", f"{sha}:proxy.py")
    if out.returncode != 0:
        print(f"\nFAILED: {SUB_PATH} has no proxy.py at {sha[:12]}: {out.stderr.decode().strip()}")
        sys.exit(1)
    return hashlib.sha256(out.stdout).hexdigest()[:12]


def verdict(pin: str, annotation: str | None, main: str) -> list[tuple[str, str]]:
    """Each way the #1225 criterion does not hold for this pin and annotation, as (pin or checksum, why), empty when it
    holds."""
    if not has_commit(pin):
        return [("pin", f"the pin {pin[:12]} is not in the {SUB_PATH} clone; no remote served it")]
    problems = []
    if not is_ancestor(pin, main):
        problems.append(("pin", f"the pin {pin[:12]} is not on guard-proxy origin/main (head {main[:12]}); pin a main commit"))
    if not is_ancestor(FLOOR, pin):
        problems.append(("pin", f"the pin {pin[:12]} predates a637e68eb76e, the {ENTRY_DATE} release-notes entry for "
                                f"{ENTRY_ISSUE}; pin a637e68 or a main commit after it"))
    want = build_checksum(pin)
    if annotation != want:
        problems.append(("checksum", f"checksum/proxy-py is {annotation!r}, the pinned build's proxy.py hashes to {want!r}; "
                                     f"set it to {want} in gitops/ai-layer/resources.yaml"))
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
full(FLOOR)
old_pin, before = full(OLD_PIN), full(BEFORE)

print(f"== guard-proxy's {NOTES}: the {ENTRY_DATE} entry for {ENTRY_ISSUE} ==")
notes = git("show", f"{main}:{NOTES}")
if notes.returncode != 0:
    print(f"\nFAILED: guard-proxy origin/main has no {NOTES}: {notes.stderr.decode().strip()}")
    sys.exit(1)
# Each entry is a `## <date>: <title>` heading and the lines down to the next one.
entries = re.split(r"(?m)^(?=## )", notes.stdout.decode())
mine = [e for e in entries if e.startswith(f"## {ENTRY_DATE}:") and ENTRY_ISSUE in e]
if len(mine) != 1:
    print(f"\nFAILED: guard-proxy origin/main's {NOTES} has {len(mine)} entries headed '## {ENTRY_DATE}:' that name "
          f"{ENTRY_ISSUE}, not one; the floor below is read from that entry")
    sys.exit(1)
heading = mine[0].splitlines()[0]
check(f"the entry says to repin the submodule and checksum/proxy-py to its commit or a later one",
      "checksum/proxy-py" in mine[0] and "this entry's commit (or a later one)" in mine[0], mine[0][:400])
# The entry's commit: the first main commit whose release notes gained the heading.
added = git("log", "--reverse", "--format=%H", "-F", f"-S{heading}", main, "--", NOTES).stdout.decode().split()
check(f"the commit that added {heading!r} is a637e68eb76e, the floor this test holds",
      bool(added) and added[0] == FLOOR, f"git log -S found {added}")
check("a637e68eb76e is on guard-proxy origin/main, so a pin at or after it can be", is_ancestor(FLOOR, main),
      f"origin/main is {main[:12]}")

docs = [d for d in yaml.safe_load_all(RES.read_text(encoding="utf-8")) if d]
deploys = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy"]
check("gitops/ai-layer/resources.yaml has one guard-proxy Deployment", len(deploys) == 1, f"found {len(deploys)}")
annotation = (deploys[0]["spec"]["template"]["metadata"].get("annotations") or {}).get("checksum/proxy-py") \
    if deploys else None

print(f"== this repo: the pin {pin[:12]} and checksum/proxy-py {annotation!r} ==")
problems = verdict(pin, annotation, main)
why = "; ".join(w for _, w in problems)
check(f"{SUB_PATH} pins a guard-proxy main commit at a637e68eb76e ({ENTRY_DATE}, {ENTRY_ISSUE}) or later",
      not any(k == "pin" for k, _ in problems), why)
check(f"checksum/proxy-py matches the pinned build's proxy.py ({build_checksum(pin)})",
      not any(k == "checksum" for k, _ in problems), why)

print("== the same verdict on guard-proxy's own history ==")
floor_sum = build_checksum(FLOOR)
check("a637e68 itself, with its own checksum, holds", verdict(FLOOR, floor_sum, main) == [],
      f"got {verdict(FLOOR, floor_sum, main)}")
for sha, what in ((old_pin, "be88e1f, the pin before #1225"), (before, "3c68224, main's commit just before the entry")):
    got = verdict(sha, build_checksum(sha), main)
    check(f"{what}, fails as predating a637e68 even with its own checksum",
          len(got) == 1 and got[0][0] == "pin" and "predates a637e68eb76e" in got[0][1], f"got {got}")
old_sum = build_checksum(old_pin)
if build_checksum(pin) != old_sum:
    stale = verdict(pin, old_sum, main)
    check("the current pin with be88e1f's checksum fails on the checksum",
          "checksum" in [k for k, _ in stale], f"got {stale}")
missing = verdict(pin, None, main)
check("the current pin with no checksum/proxy-py fails on the checksum",
      "checksum" in [k for k, _ in missing], f"got {missing}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print(f"\nguard-proxy is pinned at {pin[:12]}, on main at or after a637e68 ({ENTRY_DATE}, {ENTRY_ISSUE}), and "
      "checksum/proxy-py is its build's.")
