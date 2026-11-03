# ABOUTME: Offline half of #836: verify/images_saved.py's judge, and test_images_saved.py run whole, on fixture image
# ABOUTME: archives, so a save that is missing, stale, unhashed or undated reads as unsaved and a real one as saved.
"""test_images_saved.py needs the archive on netcup and is red until mirror-images.sh save runs there. This holds
its judge to known cases with fixture archives built here, so the e2e test failing reads as "not saved" and not
as a broken check, and its passing means what it says.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from images_saved import (MANIFEST_HEADER, default_archive, lock_rows, manifest_lines, owes_save,  # noqa: E402
                          row_save_problems)

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64
FIRST = "laiyer/llm-guard-api:0.3.16"


def archive_with(root: pathlib.Path, entries: list[tuple[str, str, str, bytes | None, str | None]]) -> pathlib.Path:
    """entries: (saved_at, ref, digest, file bytes or None for no file, recorded sha or None for the true one)."""
    root.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(MANIFEST_HEADER)]
    for i, (saved_at, ref, digest, body, sha) in enumerate(entries):
        rel = f"img{i}/{digest.replace(':', '-')}.tar.gz"
        if body is not None:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(body)
        true_sha = hashlib.sha256(body or b"").hexdigest()
        lines.append("\t".join([saved_at, "git@github.com:o/r.git", ref, digest, "linux/amd64", rel, sha or true_sha]))
    (root / "manifest.tsv").write_text("\n".join(lines) + "\n")
    return root


def problems(archive: pathlib.Path, ref: str, digest: str, saved: str) -> list[str]:
    manifest, bad = manifest_lines((archive / "manifest.tsv").read_text())
    assert not bad, bad
    return row_save_problems(ref, digest, saved, archive, manifest)


tmp = pathlib.Path(tempfile.mkdtemp(prefix="images-saved-"))
try:
    print("== which rows owe a save: mirror-images.sh save's skips ==")
    check("a not-an-image: row owes none", not owes_save("-", "not-an-image:placeholder"))
    check("a build: row with no digest owes none", not owes_save("-", "build:images/tool-pin"))
    check("a build: row with a digest owes one", owes_save(D1, "build:images/tool-pin"))
    check("an upstream:, repo: and none row each owe one",
          all(owes_save(D1, s) for s in ("upstream:https://x", "repo:o/r/images/a", "none")))
    rows = lock_rows((REPO / "images.lock").read_text(encoding="utf-8"))
    owed = {ref for ref, digest, source, _ in rows if owes_save(digest, source)}
    check(f"in images.lock, {FIRST} owes a save", FIRST in owed)
    check("in images.lock, every row with a digest that is an image owes one",
          owed == {ref for ref, digest, source, _ in rows if digest != "-" and not source.startswith("not-an-image:")})
    check("lock_rows reads a three-column row as saved -", lock_rows(f"# c\n{FIRST} {D1} none\n")
          == [(FIRST, D1, "none", "-")])

    print("== a real save reads as saved ==")
    good = archive_with(tmp / "good", [("2026-11-04", FIRST, D1, b"tarball", None)])
    check("dated, a manifest line at the digest, the file hashing to its sha: saved",
          problems(good, FIRST, D1, "2026-11-04") == [])
    named = archive_with(tmp / "named", [("2026-11-04", "llm-guard", D1, b"tarball", None)])
    check("a name@sha256 row is matched by the digest after its @",
          problems(named, "llm-guard", f"ghcr.io/o/llm-guard@{D1}", "2026-11-04") == [])
    two = archive_with(tmp / "two", [("2026-11-01", FIRST, D1, None, None), ("2026-11-04", FIRST, D1, b"t", None)])
    check("one good line among the ref's lines is enough", problems(two, FIRST, D1, "2026-11-04") == [])

    print("== anything less reads as unsaved ==")
    p = problems(good, FIRST, D1, "-")
    check("saved - fails though the archive holds it", any("saved is -" in x for x in p), str(p))
    p = problems(good, FIRST, D2, "2026-11-04")
    check("a digest bumped after the save fails: the old date alone is not a copy",
          any("no line for" in x and D2 in x for x in p), str(p))
    p = problems(good, "other:1", D1, "2026-11-04")
    check("a ref with no manifest line fails", any("no line for other:1" in x for x in p), str(p))
    missing = archive_with(tmp / "missing", [("2026-11-04", FIRST, D1, None, None)])
    p = problems(missing, FIRST, D1, "2026-11-04")
    check("a manifest line whose file is gone fails", any("not in the archive" in x for x in p), str(p))
    empty = archive_with(tmp / "empty", [("2026-11-04", FIRST, D1, b"", None)])
    p = problems(empty, FIRST, D1, "2026-11-04")
    check("an empty file fails", any("not in the archive, or is empty" in x for x in p), str(p))
    swapped = archive_with(tmp / "swapped", [("2026-11-04", FIRST, D1, b"other bytes", "ab" * 32)])
    p = problems(swapped, FIRST, D1, "2026-11-04")
    check("a file that does not hash to the recorded sha fails", any("hashes to" in x for x in p), str(p))
    undated = archive_with(tmp / "undated", [("-", FIRST, D1, b"t", None)])
    p = problems(undated, FIRST, D1, "2026-11-04")
    check("a manifest line with no saved_at date fails", any("saved_at" in x for x in p), str(p))
    m, _ = manifest_lines("\t".join(MANIFEST_HEADER) + "\n" + "\t".join(
        ["2026-11-04", "o", FIRST, D1, "linux/amd64", "../outside.tar.gz", "ab" * 32]) + "\n")
    p = row_save_problems(FIRST, D1, "2026-11-04", tmp / "good", m)
    check("a manifest file outside the archive fails", any("outside the archive" in x for x in p), str(p))
    p = row_save_problems("x", "-", "2026-11-04", good, {})
    check("a row with no sha256 digest fails", any("names no sha256" in x for x in p), str(p))
    _, bad = manifest_lines("ref\tdigest\n")
    check("a manifest without save's header is a shape problem", bool(bad))
    _, bad = manifest_lines("\t".join(MANIFEST_HEADER) + "\na\tb\n")
    check("a manifest line without seven columns is a shape problem", bool(bad))

    print("== the archive is where mirror-images.sh save writes it ==")
    os.environ.pop("MIRROR_IMAGES_DEST", None)
    check("default ~/repos/private/image-archive", default_archive() == pathlib.Path.home() / "repos/private/image-archive")
    os.environ["MIRROR_IMAGES_DEST"] = str(tmp / "dest")
    check("MIRROR_IMAGES_DEST overrides it, as it does for the script", default_archive() == tmp / "dest")
    os.environ.pop("MIRROR_IMAGES_DEST", None)

    print("== test_images_saved.py, run whole ==")
    e2e = (HERE / "test_images_saved.py").read_text()
    check("it is `# SUITE: e2e`, so run-tests.sh hands it to run-e2e.sh", re.search(r"^# SUITE: e2e", e2e, re.M) is not None)
    check("it is not in the tools tier, whose gate host cannot read the archive",
          re.search(r"^# E2E TIER: tools", e2e, re.M) is None)
    env = {k: v for k, v in os.environ.items() if k != "MIRROR_IMAGES_DEST"}
    r = subprocess.run([sys.executable, str(HERE / "test_images_saved.py")], capture_output=True, text=True,
                       env={**env, "MIRROR_IMAGES_DEST": str(tmp / "absent")})
    check("on an archive that does not exist it exits 1 and names the path",
          r.returncode == 1 and f"FAIL  the image archive is a directory ({tmp / 'absent'})" in r.stdout,
          r.stdout[-400:] + r.stderr[-400:])
    check(f"and fails {FIRST} by name", f"FAIL  {FIRST} is saved" in r.stdout, r.stdout[-400:])

    # A copy of the test and its judge in a fixture repo whose images.lock is fully saved: the whole run goes green.
    fake = tmp / "repo"
    (fake / "verify").mkdir(parents=True)
    for name in ("test_images_saved.py", "images_saved.py"):
        shutil.copy(HERE / name, fake / "verify" / name)
    (fake / "images.lock").write_text(
        "# fixture\n"
        f"{FIRST} {D1} upstream:https://github.com/protectai/llm-guard 2026-11-04\n"
        f"llm-guard ghcr.io/o/llm-guard@{D2} repo:o/r/deploy/images 2026-11-04\n"
        "${{parameters.image}} - not-an-image:a-parameter -\n"
        "ghcr.io/o/tool-pin:1 - build:images/tool-pin -\n")
    full = archive_with(tmp / "full", [("2026-11-04", FIRST, D1, b"a", None), ("2026-11-04", "llm-guard", D2, b"b", None)])
    r = subprocess.run([sys.executable, str(fake / "verify/test_images_saved.py")], capture_output=True, text=True,
                       env={**env, "MIRROR_IMAGES_DEST": str(full)})
    check("on a lock and archive where every owed row is saved it exits 0, the two skipped rows owing nothing",
          r.returncode == 0 and "4 rows, 2 owe a saved tarball" in r.stdout, r.stdout[-600:] + r.stderr[-400:])
    (full / "img1" / f"{D2.replace(':', '-')}.tar.gz").write_bytes(b"changed")
    r = subprocess.run([sys.executable, str(fake / "verify/test_images_saved.py")], capture_output=True, text=True,
                       env={**env, "MIRROR_IMAGES_DEST": str(full)})
    check("and exits 1 once one tarball no longer matches what save recorded",
          r.returncode == 1 and "FAIL  no row left unsaved (1 of 2)" in r.stdout, r.stdout[-600:])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The save judge reads saved and unsaved rows as they are.")
