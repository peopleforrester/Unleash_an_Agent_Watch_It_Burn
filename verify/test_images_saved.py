# ABOUTME: Save half of #603 (#836): every images.lock row that owes a tarball, laiyer/llm-guard-api:0.3.16 first, is
# ABOUTME: dated and held in the image archive at its current digest by a file that hashes to what save recorded.
# SUITE: e2e (needs the image archive mirror-images.sh save writes, ~/repos/private/image-archive on netcup)
"""Why this exists (#836, from #603).

#603 asks to record the digests of the images this workshop depends on and to save them, starting with
laiyer/llm-guard-api:0.3.16. test_images_lock.py holds the digests and accepts - in the saved column, and
test_images_lock_render.py leaves save to mirror-images.sh, so until this nothing failed when no image had been
saved, or when a digest moved past the copy that was.

This reads images.lock and the archive llm-coding-workflow's scripts/mirror-images.sh `save .` writes (its
MIRROR_IMAGES_DEST, default ~/repos/private/image-archive), and holds each row that save does not skip to
verify/images_saved.py's judge: a date in the saved column, a manifest.tsv line for the ref at the row's current
digest, and that line's file present and hashing to its file_sha256. test_images_saved_judge.py runs the same judge
on fixture archives offline.

It is not in the `# E2E TIER: tools` tier: the archive is on netcup under michael's home, which the gate host cannot
read. A missing archive or manifest is a failure with its path printed, never a skip. To turn it green, as michael
on netcup in this repo: `~/repos/workflow/llm-coding-workflow/scripts/mirror-images.sh save .`, then commit the
saved dates it writes into images.lock.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from images_saved import default_archive, lock_rows, manifest_lines, owes_save, row_save_problems  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
LOCK = REPO / "images.lock"
FIRST = "laiyer/llm-guard-api:0.3.16"

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


archive = default_archive()
manifest_path = archive / "manifest.tsv"

print("== the rows that owe a save ==")
rows = lock_rows(LOCK.read_text(encoding="utf-8"))
owed = [(ref, digest, saved) for ref, digest, source, saved in rows if owes_save(digest, source)]
print(f"        {len(rows)} rows, {len(owed)} owe a saved tarball")
check(f"images.lock declares {FIRST}", any(ref == FIRST for ref, _, _ in owed))

print(f"== the archive at {archive} ==")
check(f"the image archive is a directory ({archive})", archive.is_dir(), "mirror-images.sh save has not written it")
check(f"its manifest.tsv is there ({manifest_path})", manifest_path.is_file())
manifest, bad = manifest_lines(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else ({}, [])
for b in bad:
    print(f"        {b}")
check(f"manifest.tsv has the header save writes and seven columns a line ({len(bad)} problems)", not bad)

print(f"== {FIRST}, the image #603 names first ==")
hashes: dict[pathlib.Path, str] = {}
first = [(digest, saved) for ref, digest, saved in owed if ref == FIRST]
if first:
    problems = row_save_problems(FIRST, first[0][0], first[0][1], archive, manifest, hashes)
    for p in problems:
        print(f"        {p}")
    check(f"{FIRST} is saved at {first[0][0][:19]}...", not problems)

print(f"== every one of the {len(owed)} rows is saved at its current digest ==")
unsaved = []
for ref, digest, saved in owed:
    problems = row_save_problems(ref, digest, saved, archive, manifest, hashes)
    if problems:
        unsaved.append(ref)
        print(f"        {ref}: {'; '.join(problems)}")
check(f"no row left unsaved ({len(unsaved)} of {len(owed)})", not unsaved)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s). As michael on netcup, in this repo: "
          "~/repos/workflow/llm-coding-workflow/scripts/mirror-images.sh save . && commit images.lock")
    sys.exit(1)
print(f"All {len(owed)} images images.lock owes a copy of are saved in {archive}.")
