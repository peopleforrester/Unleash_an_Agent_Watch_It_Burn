#!/usr/bin/env python3
# ABOUTME: Fails unless gitops/ai-layer/guard-proxy pins a guard-proxy-agenticburn main commit at dc78f1c80896 or later
# ABOUTME: (#1048's repin, #1046), and checksum/proxy-py is the sha256 prefix of the pinned commit's own proxy.py (#1066).
"""#1046's criterion, the #1048 step: `gitops/ai-layer/guard-proxy` is pinned to guard-proxy main at dc78f1c80896 or
later, and `checksum/proxy-py` matches the pinned build. dc78f1c is the build that sends X-Pantry-Shut
(guard-proxy-agenticburn#65), the header Challenge 2's recipe card is kept shut on. The tests that read the pinned
proxy.py (test_pantry_header_pin.py, test_chat_witch_name.py) hold whichever build is pinned on purpose, so a repin
back to 0f0c809 passes them; test_proxy_checksum.py reads the checked-out proxy.py, not the pinned commit's. This test
is the one that fails on either (#1066).

What it holds, offline, against the submodule clone ensure-submodules.sh checks out from the host mirror:
  - the gitlink names a commit the clone has, reachable from the clone's origin/main
  - dc78f1c is an ancestor of the pin, or the pin itself
  - the guard-proxy Deployment's checksum/proxy-py is sha256(`git show <pin>:proxy.py`)[:12], the pinned build's bytes
    and not whatever the working tree holds
Then it runs the same verdict on guard-proxy's own history, so each way the criterion can stop holding is seen to fail:
dc78f1c with its own checksum passes; 0f0c809 (the pin #1048 moved off) with its own checksum fails as predating
dc78f1c; the current pin with dc78f1c's checksum fails on the checksum.
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SUB_PATH = "gitops/ai-layer/guard-proxy"
SUB = REPO / SUB_PATH
RES = REPO / "gitops/ai-layer/resources.yaml"
FLOOR = "dc78f1c80896f15acd8f5458261b46c1d7f12557"  # #1048's repin: sends X-Pantry-Shut (guard-proxy-agenticburn#65)
OLD_PIN = "0f0c809d3bb080493a541f4a6748947846a6fa97"  # the pin before #1048, from before guard-proxy-agenticburn#65
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


def build_checksum(sha: str) -> str:
    """The checksum/proxy-py value for the build at `sha`: the first 12 hex of the sha256 of its proxy.py."""
    out = git("show", f"{sha}:proxy.py")
    if out.returncode != 0:
        sys.exit(f"FAILED: {SUB_PATH} has no proxy.py at {sha[:12]}: {out.stderr.decode().strip()}")
    return hashlib.sha256(out.stdout).hexdigest()[:12]


def verdict(pin: str, annotation: str | None, main: str) -> list[tuple[str, str]]:
    """Each way the #1048 criterion does not hold for this pin and annotation, as (pin or checksum, why), empty when it
    holds."""
    if not has_commit(pin):
        return [("pin", f"the pin {pin[:12]} is not in the {SUB_PATH} clone; no remote served it")]
    problems = []
    if not is_ancestor(pin, main):
        problems.append(("pin", f"the pin {pin[:12]} is not on guard-proxy origin/main (head {main[:12]}); pin a main commit"))
    if not is_ancestor(FLOOR, pin):
        problems.append(("pin", f"the pin {pin[:12]} predates dc78f1c80896 (#1048); pin dc78f1c or a main commit after it"))
    want = build_checksum(pin)
    if annotation != want:
        problems.append(("checksum", f"checksum/proxy-py is {annotation!r}, the pinned build's proxy.py hashes to {want!r}; set it "
                        f"to {want} in gitops/ai-layer/resources.yaml"))
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
for sha, what in ((FLOOR, "dc78f1c, #1048's repin"), (OLD_PIN, "0f0c809, the pin before #1048")):
    if not has_commit(sha):
        print(f"\nFAILED: {SUB_PATH} has no commit {sha[:12]} ({what}); its clone is not guard-proxy-agenticburn's")
        sys.exit(1)
check("dc78f1c80896 is on guard-proxy origin/main, so a pin at or after it can be", is_ancestor(FLOOR, main),
      f"origin/main is {main[:12]}")

docs = [d for d in yaml.safe_load_all(RES.read_text(encoding="utf-8")) if d]
deploys = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy"]
check("gitops/ai-layer/resources.yaml has one guard-proxy Deployment", len(deploys) == 1, f"found {len(deploys)}")
annotation = (deploys[0]["spec"]["template"]["metadata"].get("annotations") or {}).get("checksum/proxy-py") \
    if deploys else None

print(f"== this repo: the pin {pin[:12]} and checksum/proxy-py {annotation!r} ==")
problems = verdict(pin, annotation, main)
why = "; ".join(w for _, w in problems)
check(f"{SUB_PATH} pins a guard-proxy main commit at dc78f1c80896 or later",
      not any(k == "pin" for k, _ in problems), why)
check(f"checksum/proxy-py matches the pinned build's proxy.py ({build_checksum(pin)})",
      not any(k == "checksum" for k, _ in problems), why)

print("== the same verdict on guard-proxy's own history ==")
floor_sum, old_sum = build_checksum(FLOOR), build_checksum(OLD_PIN)
check("dc78f1c itself, with its own checksum, holds", verdict(FLOOR, floor_sum, main) == [],
      f"got {verdict(FLOOR, floor_sum, main)}")
old = verdict(OLD_PIN, old_sum, main)
check("0f0c809, the pin before #1048, fails as predating dc78f1c even with its own checksum",
      len(old) == 1 and old[0][0] == "pin" and "predates dc78f1c80896" in old[0][1], f"got {old}")
if build_checksum(pin) != floor_sum:
    stale = verdict(pin, floor_sum, main)
    check("the current pin with dc78f1c's checksum fails on the checksum",
          "checksum" in [k for k, _ in stale], f"got {stale}")
missing = verdict(pin, None, main)
check("the current pin with no checksum/proxy-py fails on the checksum",
      "checksum" in [k for k, _ in missing], f"got {missing}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print(f"\nguard-proxy is pinned at {pin[:12]}, on main at or after dc78f1c, and checksum/proxy-py is its build's.")
