#!/usr/bin/env python3
# ABOUTME: #1316's repin: guard-proxy is pinned on its main at or after 0a3ca16 (guard-proxy-agenticburn#84, the
# ABOUTME: 1,253-term code-of-conduct list), checksum/proxy-py is that build's, and its list is the spike's list.
"""#1316's repin: the pin moves from 0627502 (#1288, the spike's folded 144-term list in linear time) to guard-proxy
main at or after 0a3ca16, which grows the default code-of-conduct list to 1,253 terms: Urban Dictionary-style slang,
its alphanumeric spellings, coded hate and regional slang (guard-proxy-agenticburn#84). The matching rules are
unchanged. A repin back to 0627502 would keep every earlier pin test green and put /chat back on 144 terms while the
chat page, the desk, the collector and the admission policy read 1,253; this test is the floor that stops it.

What it holds, offline, against the submodule clone ensure-submodules.sh checks out from the host mirror:
  - guard-proxy's docs/release-notes.md on origin/main has one entry headed "2026-11-10: Urban Dictionary-style slang
    on the code-of-conduct list" that says the list grows to 1,253 and to repin to the commit that promotes it
  - the gitlink is on the clone's origin/main and 0a3ca16 is an ancestor of it, or it
  - the guard-proxy Deployment's checksum/proxy-py is sha256(`git show <pin>:proxy.py`)[:12]
  - the pinned proxy.py's default PROFANITY is 1,253 entries, the spike's terms-proposed.rot13 entry for entry and
    in order, and carries conformance/coc_floor/slang-set.rot13.tsv, which test_desk_coc.py and test_chat_coc_e2e.py
    read
Then the same verdict on guard-proxy's own history: 0a3ca16 with its own checksum holds, and 0627502 (the pin before
this repin) fails as predating it even with its own checksum.
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
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
NOTES = "docs/release-notes.md"
FIXTURE = "conformance/coc_floor/slang-set.rot13.tsv"
ENTRY = "## 2026-11-10: Urban Dictionary-style slang on the code-of-conduct list"
SLANG = "0a3ca16078a2e079f086ce1dc7e6319a1957695a"  # guard-proxy-agenticburn#84, the 1,253-term list
OLD_PIN = "0627502da78f451770fea072ea7c15d788efe53f"  # #1288's pin, the 144-term list in linear time
TERMS = 1253
failures: list[str] = []

sys.path.insert(0, str(SPIKE))
import corpus  # noqa: E402


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


def blob(sha: str, path: str) -> bytes:
    out = git("show", f"{sha}:{path}")
    if out.returncode != 0:
        print(f"\nFAILED: {SUB_PATH} has no {path} at {sha[:12]}: {out.stderr.decode().strip()}")
        sys.exit(1)
    return out.stdout


def build_checksum(sha: str) -> str:
    return hashlib.sha256(blob(sha, "proxy.py")).hexdigest()[:12]


def verdict(pin: str, annotation: str | None, main: str) -> list[tuple[str, str]]:
    """Each way #1316's repin does not hold for this pin and annotation, as (pin or checksum, why); empty when it does."""
    if not has_commit(pin):
        return [("pin", f"the pin {pin[:12]} is not in the {SUB_PATH} clone; no remote served it")]
    problems = []
    if not is_ancestor(pin, main):
        problems.append(("pin", f"the pin {pin[:12]} is not on guard-proxy origin/main (head {main[:12]})"))
    if not is_ancestor(SLANG, pin):
        problems.append(("pin", f"the pin {pin[:12]} predates {SLANG[:12]}, the 1,253-term code-of-conduct list "
                                f"(guard-proxy-agenticburn#84); pin it or a main commit after it"))
    want = build_checksum(pin)
    if annotation != want:
        problems.append(("checksum", f"checksum/proxy-py is {annotation!r}, the pinned build's proxy.py hashes to "
                                     f"{want!r}; set it to {want} in gitops/ai-layer/resources.yaml"))
    return problems


def load_proxy(sha: str) -> types.ModuleType:
    """proxy.py at sha, run as a module from its blob with PROFANITY_LIST unset, so its default list is read."""
    os.environ.pop("PROFANITY_LIST", None)
    os.environ.pop("CONDUCT_GUARDRAIL_ID", None)
    mod = types.ModuleType(f"gp_pin_1316_{sha[:12]}")
    exec(compile(blob(sha, "proxy.py"), f"{SUB_PATH}/proxy.py@{sha[:12]}", "exec"), mod.__dict__)
    return mod


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
if not all(has_commit(s) for s in (SLANG, OLD_PIN)):
    print(f"\nFAILED: {SUB_PATH} lacks {SLANG[:12]} or {OLD_PIN[:12]}; its clone is not guard-proxy-agenticburn's, or "
          "it predates #84's promotion; run bash verify/ensure-submodules.sh")
    sys.exit(1)

print(f"== guard-proxy's {NOTES}: {ENTRY!r} ==")
entries = re.split(r"(?m)^(?=## )", blob(main, NOTES).decode())
mine = [e for e in entries if e.startswith(ENTRY)]
if len(mine) != 1:
    print(f"\nFAILED: guard-proxy origin/main's {NOTES} has {len(mine)} entries headed {ENTRY!r}, not one; "
          "the floor below is read from that entry")
    sys.exit(1)
flat = " ".join(mine[0].split())  # the notes wrap their lines, so a phrase can cross a line break
check("the entry says the default list grows from the spike's 144 entries to 1,253",
      "from the spike's 144 entries to 1,253" in flat, mine[0][:400])
check("the entry says to repin the submodule and checksum/proxy-py to the commit that promotes it",
      "checksum/proxy-py" in flat and "the commit that promotes it (or a later one)" in flat, mine[0][:400])
check(f"{SLANG[:12]} is on guard-proxy origin/main", is_ancestor(SLANG, main), f"origin/main is {main[:12]}")

docs = [d for d in yaml.safe_load_all(RES.read_text(encoding="utf-8")) if d]
deploys = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy"]
check("gitops/ai-layer/resources.yaml has one guard-proxy Deployment", len(deploys) == 1, f"found {len(deploys)}")
annotation = (deploys[0]["spec"]["template"]["metadata"].get("annotations") or {}).get("checksum/proxy-py") \
    if deploys else None

print(f"== this repo: the pin {pin[:12]} and checksum/proxy-py {annotation!r} ==")
problems = verdict(pin, annotation, main)
why = "; ".join(w for _, w in problems)
check(f"{SUB_PATH} pins a guard-proxy main commit at {SLANG[:12]} or later",
      not any(k == "pin" for k, _ in problems), why)
check("checksum/proxy-py matches the pinned build's proxy.py", not any(k == "checksum" for k, _ in problems), why)
pinned = load_proxy(pin)
spike = corpus.terms("proposed")
check(f"the pinned proxy.py's default PROFANITY has {TERMS:,} entries", len(pinned.PROFANITY) == TERMS,
      f"it has {len(pinned.PROFANITY)}")
check("the pinned proxy.py's default PROFANITY is terms-proposed.rot13, entry for entry and in order",
      pinned.PROFANITY == spike,
      f"proxy only: {len(set(pinned.PROFANITY) - set(spike))}, spike only: {len(set(spike) - set(pinned.PROFANITY))}")
check(f"the pinned build carries {FIXTURE}, which the desk's and the chat page's tests read",
      (SUB / FIXTURE).is_file() and (SUB / FIXTURE).read_bytes() == blob(pin, FIXTURE))

print("== the same verdict on guard-proxy's own history ==")
got = verdict(SLANG, build_checksum(SLANG), main)
check("0a3ca16 itself, with its own checksum, holds", got == [], f"got {got}")
got = verdict(OLD_PIN, build_checksum(OLD_PIN), main)
check("0627502, the pin before this repin, fails as predating 0a3ca16 even with its own checksum",
      len(got) == 1 and got[0][0] == "pin" and f"predates {SLANG[:12]}" in got[0][1], f"got {got}")
check("0627502's default list is the 144 entries, so the list checks above can fail",
      len(load_proxy(OLD_PIN).PROFANITY) == 144)
if build_checksum(pin) != build_checksum(OLD_PIN):
    stale = verdict(pin, build_checksum(OLD_PIN), main)
    check("the current pin with 0627502's checksum fails on the checksum", "checksum" in [k for k, _ in stale],
          f"got {stale}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print(f"\nguard-proxy is pinned at {pin[:12]}, on main at or after 0a3ca16 (the 1,253-term list), checksum/proxy-py is "
      "its build's, and its list is the spike's.")
