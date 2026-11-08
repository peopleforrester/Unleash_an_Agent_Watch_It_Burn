# ABOUTME: Holds verify/git_mirror.py (#1122) on local repositories: a miss clones the mirror once, a hit fetches nothing,
# ABOUTME: a changed object or a checkout off the pin fails naming both hashes and is never fetched again. Offline.
"""Each case builds its own source repository and cache root outside every worktree (artifact_cache.scratch_dir), so
nothing here reads the network or the host's own cache. A hit is proved to fetch nothing by moving the source away
before it: a fetch would then fail, and the fetch log would grow."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import zlib

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache as ac  # noqa: E402
import git_mirror as gm  # noqa: E402

os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                  GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_COUNT="1",
                  GIT_CONFIG_KEY_0="protocol.file.allow", GIT_CONFIG_VALUE_0="always")
for var in ("ARTIFACT_FETCH_LOG", "HECATON_TOOLS_CACHE", "WIB_ARTIFACT_CACHE"):
    os.environ.pop(var, None)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def sh(*args: str, cwd: pathlib.Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"setup failed: git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def commit(repo: pathlib.Path, text: str) -> str:
    (repo / "proxy.py").write_text(text)
    sh("-C", str(repo), "add", "proxy.py")
    sh("-C", str(repo), "commit", "-qm", text)
    return sh("-C", str(repo), "rev-parse", "HEAD")


def log_lines(root: pathlib.Path) -> list[str]:
    p = root / "fetch.log"
    return p.read_text().splitlines() if p.exists() else []


def raises(fn, kind: type) -> str:
    try:
        fn()
    except kind as e:
        return str(e)
    except Exception as e:  # noqa: BLE001 - the case reports what came instead
        return f"WRONG {type(e).__name__}: {e}"
    return "NO ERROR"


base = ac.scratch_dir("git-mirror-test-")
try:
    root = base / "cache"
    src = base / "src" / "guard-proxy"
    src.parent.mkdir()
    sh("init", "-q", "-b", "main", str(src))
    old = commit(src, "old")
    new = commit(src, "new")
    url = str(src)

    print("== a miss clones a bare mirror once, into the host cache ==")
    m = gm.ensure(url, new, root=root)
    check("the mirror is <root>/git/<key>.git", m.parent == root / "git" and m.name.endswith("-guard-proxy.git"), str(m))
    check("it is bare", sh("--git-dir", str(m), "rev-parse", "--is-bare-repository") == "true")
    check("it holds the pin and the branch", sh("--git-dir", str(m), "rev-parse", "refs/heads/main") == new)
    lines = log_lines(root)
    check("the clone is one fetch-log line naming the URL, the commit and ok",
          len(lines) == 1 and lines[0].split("\t")[1:3] == [url, new] and lines[0].endswith("\tok"), str(lines))
    check("no temp clone is left beside it", not [p for p in m.parent.iterdir() if p.name.endswith(".part")])

    print("== a hit fetches nothing: the source is gone and the mirror still serves it ==")
    away = base / "src-away"
    src.rename(away)
    check("an older pin of the same URL is a hit too", gm.ensure(url, old, root=root) == m)
    check("the pin is a hit", gm.ensure(url, new, root=root) == m)
    check("the fetch log is unchanged", log_lines(root) == lines, str(log_lines(root)))
    away.rename(src)

    print("== a miss on an existing mirror fetches its branches once ==")
    newer = commit(src, "newer")
    check("a new pin is served", gm.ensure(url, newer, root=root) == m)
    lines = log_lines(root)
    check("one more fetch-log line, ok", len(lines) == 2 and lines[1].split("\t")[2] == newer and lines[1].endswith("\tok"),
          str(lines))

    print("== a commit no branch holds fails by name, and nothing is kept ==")
    sh("-C", str(src), "checkout", "-q", "--detach")
    loose = commit(src, "on no branch")
    sh("-C", str(src), "checkout", "-q", "main")
    msg = raises(lambda: gm.ensure(url, loose, root=root), gm.GitMirrorError)
    check("it fails naming the URL and the commit", url in msg and loose in msg and "no branch or tag" in msg, msg)
    fresh_root = base / "cache-2"
    msg = raises(lambda: gm.ensure(url, loose, root=fresh_root), gm.GitMirrorError)
    check("with no mirror yet, the clone is not kept", "no branch or tag" in msg
          and not (fresh_root / "git" / m.name).exists(), msg)

    print("== a mirror object that does not hash to the pin fails, naming both hashes, and is not fetched again ==")
    bad_root = base / "cache-bad"
    bm = gm.ensure(url, old, root=bad_root)
    # The clone left every object in a pack; unpack them loose, then write new's commit under old's name.
    pack_dir = bm / "objects" / "pack"
    for pack in list(pack_dir.glob("*.pack")):
        data = pack.read_bytes()
        for f in pack_dir.glob(pack.stem + ".*"):
            f.unlink()
        subprocess.run(["git", "--git-dir", str(bm), "unpack-objects", "-q"], input=data, check=True)
    body = subprocess.run(["git", "--git-dir", str(bm), "cat-file", "commit", new], capture_output=True).stdout
    obj = bm / "objects" / old[:2] / old[2:]
    obj.chmod(0o644)
    obj.write_bytes(zlib.compress(b"commit %d\0" % len(body) + body))
    before = log_lines(bad_root)
    msg = raises(lambda: gm.ensure(url, old, root=bad_root), gm.CommitMismatch)
    check("it fails naming the mirror, the pin and the hash it read", str(bm) in msg and old in msg and new in msg, msg)
    check("the fetch log is unchanged: no fresh fetch on a mismatch", log_lines(bad_root) == before)
    check("the mirror is left in place, still wrong", obj.exists() and gm.object_hash(bm, old) == new)

    print("== a pin that is not a commit hash is refused before anything is read ==")
    check("a short hash is refused", "40 lowercase hex" in raises(lambda: gm.ensure(url, new[:12], root=root),
                                                                   gm.GitMirrorError))

    print("== submodules(): a fresh clone checks out its submodule from the mirror, with the source gone ==")
    sh("init", "-q", "-b", "main", str(base / "super"))
    sup = base / "super"
    sh("-C", str(sup), "submodule", "add", "-q", url, "guard-proxy")
    sh("-C", str(sup), "-C", "guard-proxy", "checkout", "-q", new)
    sh("-C", str(sup), "add", "guard-proxy")
    sh("-C", str(sup), "commit", "-qm", "pin")
    sh("clone", "-q", str(sup), str(base / "fresh"))
    fresh = base / "fresh"
    lines = log_lines(root)
    src.rename(away)
    said: list[str] = []
    moved = gm.submodules(fresh, root=root, say=said.append)
    check("the submodule is checked out at the pin", gm.checked_out(fresh / "guard-proxy") == new)
    check("it names the path it moved and says where from", moved == ["guard-proxy"] and "mirror" in "".join(said),
          str(said))
    check("its origin is the URL .gitmodules names, not the mirror",
          sh("-C", str(fresh / "guard-proxy"), "remote", "get-url", "origin") == url)
    check("its remote-tracking main is the mirror's", sh("-C", str(fresh / "guard-proxy"), "rev-parse", "origin/main")
          == newer)
    status = subprocess.run(["git", "-C", str(fresh), "submodule", "status"], capture_output=True, text=True).stdout
    check("git submodule status reads it as initialised and at its pin", status.startswith(" " + new), status)
    check("the fetch log is unchanged", log_lines(root) == lines)

    print("== a submodule checked out elsewhere is moved back; one at its pin is left alone ==")
    sh("-C", str(fresh / "guard-proxy"), "checkout", "-q", old)
    check("moved back to the pin", gm.submodules(fresh, root=root, say=said.append) == ["guard-proxy"]
          and gm.checked_out(fresh / "guard-proxy") == new)
    said.clear()
    check("at its pin: nothing moved, nothing said", gm.submodules(fresh, root=root, say=said.append) == [] and not said)
    sh("-C", str(fresh), "submodule", "deinit", "-q", "-f", "guard-proxy")
    check("a deinitialised one is checked out again from its old git dir", gm.submodules(fresh, root=root, say=said.append)
          == ["guard-proxy"] and gm.checked_out(fresh / "guard-proxy") == new)
    check("still no fetch", log_lines(root) == lines)

    print("== a checkout that does not land on the pin fails, naming both hashes ==")
    sh("-C", str(fresh / "guard-proxy"), "checkout", "-q", old)
    sh("-C", str(fresh), "config", "submodule.guard-proxy.update", "none")
    msg = raises(lambda: gm.submodules(fresh, root=root, say=said.append), gm.CommitMismatch)
    check("it fails naming the path, the commit it is at and the pin", "guard-proxy" in msg and old in msg and new in msg,
          msg)
    check("no fetch was made for it", log_lines(root) == lines)
    away.rename(src)

    print("== the command line ==")
    r = subprocess.run([sys.executable, str(VERIFY / "git_mirror.py"), "ensure", url, "0" * 40],
                       capture_output=True, text=True, env={**os.environ, "WIB_ARTIFACT_CACHE": str(root)})
    check("a failure exits 1 with one GIT MIRROR FAILED line", r.returncode == 1
          and r.stderr.startswith("GIT MIRROR FAILED:") and r.stderr.count("\n") == 1, r.stderr)
    r = subprocess.run([sys.executable, str(VERIFY / "git_mirror.py"), "ensure", url, new],
                       capture_output=True, text=True, env={**os.environ, "WIB_ARTIFACT_CACHE": str(root)})
    check("ensure prints the mirror's path", r.returncode == 0 and r.stdout.strip() == str(m), r.stdout + r.stderr)
finally:
    shutil.rmtree(base, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("All git mirror checks passed.")
