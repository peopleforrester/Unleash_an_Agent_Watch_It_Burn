# ABOUTME: The `delivered/<event>` tags in this clone are the pinned annotated tag objects on the pinned commits (#971),
# ABOUTME: and the check is held, in a scratch repo, to fail on a moved, deleted, lightweight or re-made tag.
"""Offline: reads this clone's refs with git, and makes a scratch repo. No network.

Why (#971). #954's criterion "the `delivered/devopsdays-portland-2026` tag is confirmed untouched" was checked by hand
and written in decisions.md; no test read the tag. The pins and the reasons a pin on the tag object's id is enough
are in verify/delivered_tags.py. This test reads the clone's own refs, which a `git clone` fetches with the commits,
as hecaton's gate clone does. verify/test_delivered_tags_github_e2e.py reads GitHub's refs, in the tools tier.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import delivered_tags as dt  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== this clone's delivered tags ==")
check("the Portland tag is one of the pins", "delivered/devopsdays-portland-2026" in dt.PINS)
refs = dt.local_refs(str(REPO), dt.PINS)
for name, (tag_obj, commit) in dt.PINS.items():
    found = dt.problems_local({name: refs[name]} if name in refs else {}, {name: (tag_obj, commit)})
    check(f"{name} is annotated tag object {tag_obj[:8]} on commit {commit[:8]}", not found, "; ".join(found))

print("== the check, held to each way a tag can change, in a scratch repo ==")
with tempfile.TemporaryDirectory() as d:
    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                              capture_output=True, text=True, check=True,
                              env={**os.environ, "GIT_COMMITTER_DATE": "2026-09-21T12:56:20Z", "HOME": d,
                                   "GIT_CONFIG_NOSYSTEM": "1"}).stdout.strip()
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "the room")
    ran = git("rev-parse", "HEAD")
    git("commit", "-q", "--allow-empty", "-m", "teardown")
    git("tag", "-a", "delivered/x", ran, "-m", "Delivered: x")
    pin = {"delivered/x": (git("rev-parse", "delivered/x"), ran)}
    read = lambda: dt.problems_local(dt.local_refs(d, pin), pin)  # noqa: E731

    check("the tag as made passes", read() == [], "; ".join(read()))
    git("tag", "-f", "-a", "delivered/x", "HEAD", "-m", "Delivered: x")
    moved = read()
    check("moved to another commit, it fails naming the commit",
          any("is on commit" in p for p in moved) and any("is object" in p for p in moved), "; ".join(moved))
    git("tag", "-d", "delivered/x")
    check("deleted, it fails naming it missing", any("is missing" in p for p in read()), "; ".join(read()))
    git("tag", "delivered/x", ran)
    light = read()
    check("a lightweight tag on the same commit fails as not annotated",
          any("not an annotated tag object" in p for p in light), "; ".join(light))
    git("tag", "-d", "delivered/x")
    git("tag", "-a", "delivered/x", ran, "-m", "Delivered: x, again")
    remade = read()
    check("re-made on the same commit with another message, it fails on the object id",
          len(remade) == 1 and "is object" in remade[0], "; ".join(remade))

print("== ls-remote output is read as the remote check reads it ==")
portland, (p_obj, p_commit) = "delivered/devopsdays-portland-2026", dt.PINS["delivered/devopsdays-portland-2026"]
good = "".join(f"{o}\trefs/tags/{n}\n{c}\trefs/tags/{n}^{{}}\n" for n, (o, c) in dt.PINS.items())
check("GitHub's output as pinned passes", dt.problems_remote(dt.parse_ls_remote(good)) == [])
other = "1" * 40
moved = good.replace(f"{p_commit}\trefs/tags/{portland}^{{}}", f"{other}\trefs/tags/{portland}^{{}}")
check("a moved Portland tag fails on its commit", moved != good
      and any("is on commit" in p for p in dt.problems_remote(dt.parse_ls_remote(moved))))
light = "\n".join(line for line in good.splitlines() if not line.endswith(f"{portland}^{{}}")).replace(
    f"{p_obj}\trefs/tags/{portland}", f"{p_commit}\trefs/tags/{portland}")
check("a lightweight Portland tag fails as not annotated", light != good
      and any("lightweight" in p for p in dt.problems_remote(dt.parse_ls_remote(light))))
gone = "\n".join(line for line in good.splitlines() if portland not in line)
check("a deleted Portland tag fails as missing",
      any(portland in p and "missing" in p for p in dt.problems_remote(dt.parse_ls_remote(gone))))

if failures:
    print(f"\nFAILED: {len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nALL DELIVERED TAG CHECKS PASS")
