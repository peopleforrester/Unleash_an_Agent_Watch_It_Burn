# ABOUTME: AGENTS.md (which CLAUDE.md links to) must say who this repo is and point at talks-knowledge for the
# ABOUTME: talk record and conference-knowledge for event state: the fleet standard for a talk repo (#422, #522).
"""Holds the identity statement and the "Where things live" pointers in AGENTS.md (#422, #522).

talks-knowledge asked every talk repo to know who it is and where its record lives (audit 2026-10-14). #422
answered with a "Where things live" section in `AGENTS.md`: the workshop this repo builds, who presents it,
that it holds the build and not the record of the talk, then talks-knowledge for the register, abstracts and
talk scripts, conference-knowledge for event state, the submodule repos and this repo's own state files. A
session that reads `CLAUDE.md` first lands on that section, so `CLAUDE.md` must stay a symlink to it.

The title is checked against the README's heading rather than written down twice here, so a rename of the
workshop has to move both files together. The submodule pointers are checked against `.gitmodules`, so a
moved or added submodule cannot leave the section naming the wrong path.

#625 named the third repo, llm-guard-upstream-mirror, outside decisions.md: a bullet in the section and a
paragraph in the README, each saying it is private and not a submodule. Both are checked here, and so is
`.gitmodules`, so the mirror cannot be added as a submodule while the two still say it is not one (#657).
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
AGENTS = REPO / "AGENTS.md"
CLAUDE = REPO / "CLAUDE.md"
README = REPO / "README.md"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def flat(text: str) -> str:
    """Collapse the wrapped lines of a paragraph so a phrase split across a line break still matches."""
    return re.sub(r"\s+", " ", text)


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def bullet(body: str, label: str) -> str:
    """The text of the `- **<label>...**` bullet, continuation lines included."""
    m = re.search(rf"^- \*\*{re.escape(label)}.*?(?=^- |^\S|\Z)", body, re.M | re.S)
    return flat(m.group(0)) if m else ""


agents = AGENTS.read_text(encoding="utf-8")
where = section(agents, "Where things live")
where_flat = flat(where)

print("== CLAUDE.md is the same file as AGENTS.md ==")
check("CLAUDE.md is a symlink", CLAUDE.is_symlink())
check("CLAUDE.md points at AGENTS.md", CLAUDE.is_symlink() and os.readlink(CLAUDE) == "AGENTS.md")

print("== AGENTS.md says who this repo is ==")
check("a '## Where things live' section exists", bool(where.strip()))
readme_h1 = re.search(r"^# (.+)$", README.read_text(encoding="utf-8"), re.M)
# The README heading ends in a fire emoji; the title is everything before it.
title = re.sub(r"[^\w!.?]+$", "", readme_h1.group(1)).strip() if readme_h1 else ""
check("the README heading gives a title", bool(title))
check(f'it is the platform and content of the workshop "{title}"',
      bool(title) and f'This repo is the platform and content of the workshop "{title}"' in where_flat)
check("it names the presenters, Michael Forrester with Whitney Lee",
      "Michael Forrester with Whitney Lee" in where_flat)
check("it holds the build, not the record of the talk",
      "It holds the build, not the record of the talk." in where_flat)

print("== it points at talks-knowledge for the talk record ==")
talks = bullet(where, "The talk register")
check("a bullet for the talk register, abstracts and talk scripts", bool(talks))
for needle in ("talks-knowledge", "`~/repos/talks/talks-knowledge`", "`peopleforrester/talks-knowledge`",
               "`talks/register.md`", "abstracts", "talk scripts"):
    check(f"the talk-record bullet names {needle}", needle in talks)

print("== it points at conference-knowledge for event state ==")
events = bullet(where, "Event state")
check("a bullet for event state", bool(events))
for needle in ("`~/repos/conferences/conference-knowledge`", "`events/registry.yaml`"):
    check(f"the event-state bullet names {needle}", needle in events)

print("== the submodule pointers match .gitmodules ==")
modules = bullet(where, "Components built from their own repos")
check("a bullet for the submodule repos", bool(modules))
gitmodules = (REPO / ".gitmodules").read_text(encoding="utf-8")
paths = re.findall(r"^\s*path = (\S+)", gitmodules, re.M)
urls = re.findall(r"^\s*url = \S+/([^/\s]+?)(?:\.git)?$", gitmodules, re.M)
check(".gitmodules lists submodules", bool(paths) and len(paths) == len(urls))
for path, repo in zip(paths, urls):
    check(f"the section names submodule {repo} at `{path}`", repo in modules and f"`{path}`" in modules)

print("== it names the upstream mirror, which is not a submodule ==")
MIRROR = "peopleforrester/llm-guard-upstream-mirror"
mirror = bullet(where, "Upstream backup, not a submodule")
check("a bullet for the upstream backup", bool(mirror))
for needle in ("llm-guard-upstream-mirror", f"`{MIRROR}`", "private", "`protectai/llm-guard`"):
    check(f"the upstream-backup bullet names {needle}", needle in mirror)
check("the mirror is not in the submodule bullet", "upstream-mirror" not in modules)
check(".gitmodules does not list the mirror", "llm-guard-upstream-mirror" not in gitmodules)
readme_flat = flat(README.read_text(encoding="utf-8"))
check(f"the README names `{MIRROR}` (private)", f"`{MIRROR}` (private)" in readme_flat)
check("the README says the mirror is not a submodule and nothing builds from it",
      "It is not a submodule and nothing here builds from it." in readme_flat)

print("== it names this repo's own state files ==")
state = bullet(where, "This repo's own state")
for name in ("PROJECT_STATE.md", "decisions.md"):
    check(f"the own-state bullet names {name}, which exists", f"`{name}`" in state and (REPO / name).is_file())

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All repo identity checks passed.")
