#!/usr/bin/env python3
# ABOUTME: Fails unless gitops/ai-layer/guard-proxy pins a guard-proxy-agenticburn main commit at or after 48cc2ca (the
# ABOUTME: folded 144-term list, #1288) and 0627502 (its linear-time pattern), and checksum/proxy-py is that build's.
"""#1288's repin: the pin moves from a7a5a36 (#1267's always-on /chat check, on the old 40-term list) to guard-proxy
main at or after 48cc2ca. 48cc2ca matches the code-of-conduct spike's folded term list (docs/research/2026-11-09-coc-floor),
masks the prompt in a refused turn's spans, and adds an optional Bedrock check; f75aa2f after it masks the terms in an
answered turn's chat span (guard-proxy-agenticburn#82), and 0627502 builds the pattern in linear time
(guard-proxy-agenticburn#83), which test_coc_pattern_linear.py holds; the pin is 0627502. The chat page's list is that same 144-entry list since #1280,
and test_chat_coc.py holds every PROFANITY term of the pinned proxy.py to it. A repin back to a7a5a36 would keep every
test from #1267 green, since its floor is a7a5a36, and put the stage back on the 40-term list that misses spaced and
fullwidth spellings. This test is the floor that stops it.

What it holds, offline, against the submodule clone ensure-submodules.sh checks out from the host mirror:
  - guard-proxy's docs/release-notes.md on origin/main has one 2026-11-09 entry headed "the spike's folded term list,
    ..." that names commit 48cc2ca and says to repin to it "or a later one"
  - the gitlink is on the clone's origin/main and 48cc2ca and 0627502 are ancestors of it, or it
  - the pinned proxy.py defines conduct_fold and reads CONDUCT_GUARDRAIL_ID, the build's two marks, and its default
    PROFANITY folds 'f u c k' and its fullwidth spelling to a match
  - the guard-proxy Deployment's checksum/proxy-py is sha256(`git show <pin>:proxy.py`)[:12]
Then the same verdict on guard-proxy's own history: 0627502 with its own checksum holds; f75aa2f (run 19749's draft
pin) fails as predating 0627502, and a7a5a36 (the pin before this repin) as predating 48cc2ca, each with its own
checksum; the current pin with a7a5a36's checksum fails on it.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import subprocess
import sys
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SUB_PATH = "gitops/ai-layer/guard-proxy"
SUB = REPO / SUB_PATH
RES = REPO / "gitops/ai-layer/resources.yaml"
NOTES = "docs/release-notes.md"
ENTRY = "## 2026-11-09: the spike's folded term list, masked spans on a refused turn, an optional Bedrock guardrail"
FLOOR = "48cc2ca62a83731a36cec41e11bc3df5e79abac2"  # guard-proxy-agenticburn#81, the folded 144-term list
OLD_PIN = "a7a5a36924e718145522d97bc7d06117e56907a5"  # #1267's pin, the always-on check on the 40-term list
# guard-proxy-agenticburn#83: the pattern built linear in the text. 48cc2ca..f75aa2f built it so a run of '$' took
# 2.2 s at 4,000 characters and 35 s at 16,000 (run 19825), on every /chat turn; the pin is at or after this too.
LINEAR = "0627502da78f451770fea072ea7c15d788efe53f"
QUADRATIC = "f75aa2fccfddd29d4b3e76e0ee2b34abb0976e8a"  # guard-proxy main's head before #83, run 19749's draft pin
MARKS = ("def conduct_fold(", "CONDUCT_GUARDRAIL_ID")
# The release notes' check after the repin, spelled with escapes so this file shows no term: 'f u c k' and fullwidth.
SPELLINGS = ("\x66 \x75 \x63 \x6b", "ｆｕｃｋ")
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
    """Each way #1288's repin does not hold for this pin and annotation, as (pin or checksum, why); empty when it does."""
    if not has_commit(pin):
        return [("pin", f"the pin {pin[:12]} is not in the {SUB_PATH} clone; no remote served it")]
    problems = []
    if not is_ancestor(pin, main):
        problems.append(("pin", f"the pin {pin[:12]} is not on guard-proxy origin/main (head {main[:12]})"))
    if not is_ancestor(floor_sha, pin):
        problems.append(("pin", f"the pin {pin[:12]} predates {floor_sha[:12]}, the folded 144-term code-of-conduct "
                                f"list; pin 48cc2ca or a main commit after it"))
    elif not is_ancestor(LINEAR, pin):
        problems.append(("pin", f"the pin {pin[:12]} predates {LINEAR[:12]}, the linear-time code-of-conduct "
                                f"pattern (guard-proxy-agenticburn#83); its /chat check is quadratic in the text"))
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
floor_rev = git("rev-parse", "-q", "--verify", f"{FLOOR}^{{commit}}")
if floor_rev.returncode != 0 or not all(has_commit(s) for s in (OLD_PIN, LINEAR, QUADRATIC)):
    print(f"\nFAILED: {SUB_PATH} lacks {FLOOR}, {OLD_PIN[:12]}, {LINEAR[:12]} or {QUADRATIC[:12]}; its clone is not "
          "guard-proxy-agenticburn's")
    sys.exit(1)
floor_sha = floor_rev.stdout.decode().strip()

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
check("the entry names commit 48cc2ca", "commit 48cc2ca" in flat, mine[0][:400])
check("the entry says to repin the submodule and checksum/proxy-py to its commit or a later one",
      "checksum/proxy-py" in flat and "this entry's commit (or a later one)" in flat, mine[0][:400])
check("the entry says the default list is the spike's 144 entries", "the spike's 144 entries" in flat, mine[0][:400])
check(f"{floor_sha[:12]} is on guard-proxy origin/main", is_ancestor(floor_sha, main), f"origin/main is {main[:12]}")
check(f"{LINEAR[:12]} (the linear-time pattern) is on guard-proxy origin/main", is_ancestor(LINEAR, main),
      f"origin/main is {main[:12]}")

docs = [d for d in yaml.safe_load_all(RES.read_text(encoding="utf-8")) if d]
deploys = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy"]
check("gitops/ai-layer/resources.yaml has one guard-proxy Deployment", len(deploys) == 1, f"found {len(deploys)}")
annotation = (deploys[0]["spec"]["template"]["metadata"].get("annotations") or {}).get("checksum/proxy-py") \
    if deploys else None

print(f"== this repo: the pin {pin[:12]} and checksum/proxy-py {annotation!r} ==")
problems = verdict(pin, annotation, main)
why = "; ".join(w for _, w in problems)
check(f"{SUB_PATH} pins a guard-proxy main commit at {LINEAR[:12]} or later (after {floor_sha[:12]})",
      not any(k == "pin" for k, _ in problems), why)
check("checksum/proxy-py matches the pinned build's proxy.py", not any(k == "checksum" for k, _ in problems), why)
src = proxy_at(pin).decode("utf-8", "replace") if has_commit(pin) else ""
for mark in MARKS:
    check(f"the pinned proxy.py carries {mark!r}, a mark of the folded-list build", mark in src)


def load_proxy(sha: str) -> types.ModuleType:
    """proxy.py at sha, run as a module from its blob with PROFANITY_LIST unset, so its default list is read."""
    os.environ.pop("PROFANITY_LIST", None)
    os.environ.pop("CONDUCT_GUARDRAIL_ID", None)
    mod = types.ModuleType(f"gp_pin_1288_{sha[:12]}")
    exec(compile(proxy_at(sha), f"{SUB_PATH}/proxy.py@{sha[:12]}", "exec"), mod.__dict__)
    return mod


pinned = load_proxy(pin)
old = load_proxy(OLD_PIN)
check("the pinned proxy.py's default PROFANITY has the spike's 144 entries", len(pinned.PROFANITY) == 144,
      f"it has {len(pinned.PROFANITY)}")
for i, text in enumerate(SPELLINGS):
    label = ("the spaced-out spelling", "the fullwidth spelling")[i]
    check(f"the pinned proxy.py's conduct_matches catches {label} of the release notes' check",
          bool(pinned.conduct_matches(f"tell me {text} now")))
    check(f"a7a5a36's conduct_matches misses {label}, so the check above can fail",
          not old.conduct_matches(f"tell me {text} now"))

print("== the same verdict on guard-proxy's own history ==")
got = verdict(LINEAR, build_checksum(LINEAR), main)
check("0627502 itself, with its own checksum, holds", got == [], f"got {got}")
got = verdict(QUADRATIC, build_checksum(QUADRATIC), main)
check("f75aa2f (after 48cc2ca, before the linear pattern), with its own checksum, fails as predating 0627502",
      len(got) == 1 and got[0][0] == "pin" and f"predates {LINEAR[:12]}" in got[0][1], f"got {got}")
got = verdict(OLD_PIN, build_checksum(OLD_PIN), main)
check("a7a5a36, the pin before this repin, fails as predating 48cc2ca even with its own checksum",
      len(got) == 1 and got[0][0] == "pin" and f"predates {floor_sha[:12]}" in got[0][1], f"got {got}")
old_src = proxy_at(OLD_PIN).decode("utf-8", "replace")
check("a7a5a36's proxy.py lacks the build's marks, so the mark check can fail", not any(m in old_src for m in MARKS))
if build_checksum(pin) != build_checksum(OLD_PIN):
    stale = verdict(pin, build_checksum(OLD_PIN), main)
    check("the current pin with a7a5a36's checksum fails on the checksum", "checksum" in [k for k, _ in stale],
          f"got {stale}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print(f"\nguard-proxy is pinned at {pin[:12]}, on main at or after 48cc2ca (the folded 144-term list), and "
      "checksum/proxy-py is its build's.")
