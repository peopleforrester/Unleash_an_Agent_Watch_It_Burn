# ABOUTME: The `delivered/<event>` tags, pinned: each is an annotated tag object, by id, on the commit the room ran.
# ABOUTME: Shared by test_delivered_tags.py (the local refs) and test_delivered_tags_github_e2e.py (GitHub's refs).
"""A delivered tag records the exact commit an event ran, so it is never moved, deleted or re-made (#954, #971).

An annotated tag's object id is the hash of its whole content: the commit it points at, its type, its name, the
tagger, the date and the message. So a pin on that id fails when the tag is moved, deleted, swapped for a lightweight
tag on the same commit, or deleted and made again with the same name and commit, since the tagger date then differs.
The peeled commit is pinned as well, so a failure names which of the two changed.

The ids below are the ones run 17825 (#954) read off GitHub's `git/refs/tags/delivered/devopsdays-portland-2026` and
the local clone, and that `git ls-remote` on GitHub printed on 2026-11-06 for both tags.
"""
from __future__ import annotations

import subprocess

GITHUB_URL = "https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn.git"

# name: (annotated tag object id, the commit it peels to)
PINS: dict[str, tuple[str, str]] = {
    # DevOpsDays Portland 2026, 2026-09-08, Room 327: 17499c8e is the last commit before the room sat down.
    "delivered/devopsdays-portland-2026": ("0e5ff394c4f6fb92faddebc0de256921bf2c4c0e",
                                           "17499c8e5e52b3bef2d9a9deb9e19ef4f7febbfd"),
    # AI Engineer World's Fair 2026, the same kind of record, tagged the same day.
    "delivered/aiewf-2026": ("0d7bd25d5539667192d4fcd2dbfd0e9264941bf6",
                             "d15031a9e7943299dd75a5c9a8ffdd8017215b65"),
}


def local_refs(repo: str, names) -> dict[str, tuple[str, str, str]]:
    """{name: (object id, object type, peeled commit)} for each tag in `names` the repo has."""
    out = subprocess.run(["git", "-C", str(repo), "for-each-ref",
                          "--format=%(refname)%09%(objectname)%09%(objecttype)%09%(*objectname)",
                          *(f"refs/tags/{n}" for n in names)],
                         capture_output=True, text=True, check=True).stdout
    refs = {}
    for line in out.splitlines():
        ref, obj, typ, peeled = line.split("\t")
        refs[ref.removeprefix("refs/tags/")] = (obj, typ, peeled)
    return refs


def parse_ls_remote(text: str) -> dict[str, tuple[str, str]]:
    """{name: (ref object id, peeled id or "")} from `git ls-remote` output for refs/tags/*.

    ls-remote prints an annotated tag twice: the ref with the tag object, and `<ref>^{}` with the commit it peels to.
    A lightweight tag has only the first line, so its peeled id is left empty.
    """
    refs: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        oid, ref = line.split("\t")
        if not ref.startswith("refs/tags/"):
            continue
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            refs.setdefault(name[:-3], ["", ""])[1] = oid
        else:
            refs.setdefault(name, ["", ""])[0] = oid
    return {n: (v[0], v[1]) for n, v in refs.items()}


def problems_local(refs: dict[str, tuple[str, str, str]], pins=PINS) -> list[str]:
    """Each way the local refs differ from the pins, in words; empty when every pinned tag is as pinned."""
    found = []
    for name, (tag_obj, commit) in pins.items():
        if name not in refs:
            found.append(f"{name} is missing (a clone without tags reads so too: "
                         f"git fetch origin 'refs/tags/delivered/*:refs/tags/delivered/*')")
            continue
        obj, typ, peeled = refs[name]
        if typ != "tag":
            found.append(f"{name} is a {typ}, not an annotated tag object")
        if obj != tag_obj:
            found.append(f"{name} is object {obj}, pinned {tag_obj}")
        if (peeled or obj) != commit:
            found.append(f"{name} is on commit {peeled or obj}, pinned {commit}")
    return found


def problems_remote(refs: dict[str, tuple[str, str]], pins=PINS) -> list[str]:
    """Each way ls-remote's refs differ from the pins, in words; empty when every pinned tag is as pinned."""
    found = []
    for name, (tag_obj, commit) in pins.items():
        if name not in refs:
            found.append(f"{name} is missing on the remote")
            continue
        obj, peeled = refs[name]
        if not peeled:
            found.append(f"{name} has no ^{{}} line, so it is a lightweight tag, not an annotated tag object")
        if obj != tag_obj:
            found.append(f"{name} is object {obj}, pinned {tag_obj}")
        if (peeled or obj) != commit:
            found.append(f"{name} is on commit {peeled or obj}, pinned {commit}")
    return found
