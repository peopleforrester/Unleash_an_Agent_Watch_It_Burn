# ABOUTME: Serves a git commit pinned by its hash from a bare mirror in the host artifact cache (#1122): one clone per URL,
# ABOUTME: a fetch only when the commit is missing, and a failure naming both hashes on a mismatch, never a fresh fetch.
"""Each fresh worktree used to clone both submodules from GitHub (verify/ensure-submodules.sh ran `git submodule update
--init`), though every run on the host checks out the same pinned commits (#1115). The superproject's gitlink is the
pin: a commit hash, so the copy can be checked against it like any other pinned artifact.

ensure(url, commit) returns <root>/git/<key>.git, a bare mirror of url in the host artifact cache (artifact_cache.py,
#1117, which resolves the root and refuses one inside a worktree). <key> is the first 16 hex digits of the URL's
SHA-256 and the repository's name, so one mirror serves every pin of a URL.
  - A hit is a mirror that holds the commit. Its commit object is read and hashed again; when it does not hash to the
    pin, ensure() fails naming the mirror and both hashes and leaves the mirror where it is. It is never fetched again
    and never cloned fresh: a mirror whose object changed under its own name is something to find out about.
  - A miss takes a lock on the mirror, so runs side by side fetch once between them, and looks again. With no mirror,
    the URL is cloned bare into a temp directory beside it and renamed into place only once the clone has the commit;
    with one, its branches and tags are fetched from the URL (`--prune`). A commit that no branch or tag of the URL
    holds after that fails, naming the URL and the commit, as `git submodule update` failed with "not our ref".
  - Every network fetch, good or bad, is one line in the artifact cache's fetch log (ARTIFACT_FETCH_LOG, or
    <root>/fetch.log), with the commit in the column a file's SHA-256 takes. A warm run adds none.

submodules(repo) checks out each submodule of repo that is not initialised, or sits at another commit than the
superproject's index pins, from its mirror. `git submodule update` runs with the mirror as the submodule's URL for that
one command (`-c submodule.<name>.url=`), so the clone reads the mirror and never the network, and the new clone's
`origin` is then set back to the URL .gitmodules names, so later fetches and the checks that read its remote-tracking
branches (submodule-pins-pushed.sh, guard-proxy-pin-on-main.sh) see the branches the mirror held. An existing submodule
clone fetches the mirror's branches into its own remote-tracking refs first. After the checkout the submodule's HEAD
is read back: a HEAD that is not the pin fails, naming both hashes (a `submodule.<name>.update` of none would leave it
there). A submodule already at its pin is not touched and nothing is printed.

Command line (verify/ensure-submodules.sh runs the second):
  git_mirror.py ensure <url> <commit>    print the mirror's path, cloning or fetching on a miss
  git_mirror.py submodules <repo>        check out every submodule of repo at its pin from its mirror
Any failure prints one line starting GIT MIRROR FAILED to stderr and exits 1."""
from __future__ import annotations

import fcntl
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache as ac  # noqa: E402

COMMIT = re.compile(r"[0-9a-f]{40}")
SUBDIR = "git"
# The mirror keeps every branch and tag of its URL under the same name; refs/pull and other refs are not fetched.
REFSPECS = ("+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*")


class GitMirrorError(ac.ArtifactCacheError):
    """The mirror could not serve the commit; the message names the URL or path and the commit."""


class CommitMismatch(GitMirrorError, ac.ArtifactMismatch):
    """A mirror's object, or a checked-out HEAD, is not the pinned commit."""


def git(*args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True)


def _err(r: subprocess.CompletedProcess) -> str:
    return (r.stderr or b"").decode(errors="replace").strip()[-400:]


def mirror_path(url: str, root: pathlib.Path) -> pathlib.Path:
    name = re.sub(r"[^A-Za-z0-9._-]", "-", url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")) or "repo"
    return root / SUBDIR / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}-{name}.git"


def object_hash(mirror: pathlib.Path, commit: str) -> str | None:
    """The hash the mirror's commit object for commit really has, computed from its bytes; None when the mirror holds
    no commit by that name. git reads a loose object by its file name and does not hash it again, so a file that
    changed under its name reads as the other commit."""
    t = git("--git-dir", str(mirror), "cat-file", "-t", commit)
    if t.returncode != 0:
        return None
    kind = t.stdout.decode().strip()
    if kind != "commit":
        raise CommitMismatch(f"mirror {mirror} holds {commit} as a {kind}, not a commit")
    body = git("--git-dir", str(mirror), "cat-file", "commit", commit)
    if body.returncode != 0:
        raise CommitMismatch(f"mirror {mirror} names {commit} but cannot read it: {_err(body)}")
    return hashlib.sha1(b"commit %d\0" % len(body.stdout) + body.stdout).hexdigest()


def _check_hit(mirror: pathlib.Path, commit: str) -> bool:
    """True on a hit that matches; False when the mirror lacks the commit; CommitMismatch when it holds other bytes."""
    got = object_hash(mirror, commit)
    if got is None:
        return False
    if got != commit:
        raise CommitMismatch(f"mirror {mirror} does not match its pin: expected commit {commit}, its object hashes to "
                             f"{got}; the mirror is left in place and not fetched again")
    return True


def _size(path: pathlib.Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def ensure(url: str, commit: str, *, root: pathlib.Path | None = None,
           env: Mapping[str, str] | None = None) -> pathlib.Path:
    """The mirror of url, holding commit and checked against it; cloned or fetched only on a miss."""
    if not COMMIT.fullmatch(commit):
        raise GitMirrorError(f"{commit!r} is not a commit hash: want 40 lowercase hex digits (for {url})")
    root = ac.resolve_root(env) if root is None else root
    mirror = mirror_path(url, root)
    if mirror.exists() and _check_hit(mirror, commit):
        return mirror
    d = mirror.parent
    try:
        d.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(d / f".{mirror.name}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        raise GitMirrorError(f"cache miss for {url} at {commit} and {d} is not writable: {e}") from e
    log = ac.fetch_log_path(root, env)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Another run may have fetched it while this one waited for the lock.
        if mirror.exists() and _check_hit(mirror, commit):
            return mirror
        if mirror.exists():
            before = _size(mirror)
            r = git("--git-dir", str(mirror), "fetch", "--quiet", "--prune", "--no-tags", url, *REFSPECS)
            ac.log_fetch(log, url, commit, max(_size(mirror) - before, 0), "ok" if r.returncode == 0 else "error git fetch")
            if r.returncode != 0:
                raise GitMirrorError(f"fetch of {url} into the mirror {mirror} for {commit} failed: {_err(r)}")
        else:
            tmp = pathlib.Path(tempfile.mkdtemp(prefix=f".{mirror.name}.", suffix=".part", dir=d))
            try:
                new = tmp / mirror.name
                r = git("clone", "--bare", "--quiet", "--no-local", url, str(new))
                ac.log_fetch(log, url, commit, _size(new), "ok" if r.returncode == 0 else "error git clone")
                if r.returncode != 0:
                    raise GitMirrorError(f"clone of {url} for {commit} failed: {_err(r)}")
                for i, spec in enumerate(REFSPECS):
                    git("--git-dir", str(new), "config", "--add" if i else "--replace-all", "remote.origin.fetch", spec)
                git("--git-dir", str(new), "config", "gc.auto", "0")
                if object_hash(new, commit) is None:
                    raise GitMirrorError(f"no branch or tag of {url} holds {commit}; push it there first, or pin a "
                                         "pushed commit (nothing was kept)")
                os.replace(new, mirror)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if not _check_hit(mirror, commit):
            raise GitMirrorError(f"no branch or tag of {url} holds {commit}, after fetching it into {mirror}; push it "
                                 "there first, or pin a pushed commit")
        return mirror
    finally:
        os.close(lock_fd)


def _lines(r: subprocess.CompletedProcess) -> list[str]:
    return r.stdout.decode().splitlines() if r.returncode == 0 else []


def gitmodules(repo: pathlib.Path) -> dict[str, tuple[str, str]]:
    """path -> (name, url), from repo's .gitmodules."""
    paths = _lines(git("-C", str(repo), "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"))
    out = {}
    for line in paths:
        key, path = line.split(" ", 1)
        name = key[len("submodule."):-len(".path")]
        url = git("-C", str(repo), "config", "-f", ".gitmodules", f"submodule.{name}.url").stdout.decode().strip()
        if not url:
            raise GitMirrorError(f"{repo}/.gitmodules names {path} (submodule {name}) with no url")
        out[path] = (name, url)
    return out


def pins(repo: pathlib.Path) -> dict[str, str]:
    """path -> the commit repo's index pins for each gitlink."""
    r = git("-C", str(repo), "ls-files", "-s", "-z")
    if r.returncode != 0:
        raise GitMirrorError(f"git ls-files failed in {repo}: {_err(r)}")
    out = {}
    for entry in r.stdout.decode().split("\0"):
        if entry.startswith("160000 "):
            meta, path = entry.split("\t", 1)
            out[path] = meta.split()[1]
    return out


def checked_out(sub: pathlib.Path) -> str | None:
    """The submodule's HEAD, or None when sub is not a repository of its own (git -C would answer for the superproject)."""
    top = git("-C", str(sub), "rev-parse", "--show-toplevel")
    if top.returncode != 0 or pathlib.Path(top.stdout.decode().strip()).resolve() != sub.resolve():
        return None
    head = git("-C", str(sub), "rev-parse", "HEAD")
    return head.stdout.decode().strip() if head.returncode == 0 else None


def submodules(repo: pathlib.Path, *, root: pathlib.Path | None = None, env: Mapping[str, str] | None = None,
               say=print) -> list[str]:
    """Check out every submodule of repo that is not at its pin from its mirror; the paths it moved."""
    repo = repo.resolve()
    mods = gitmodules(repo)
    moved = []
    for path, pin in sorted(pins(repo).items()):
        if path not in mods:
            raise GitMirrorError(f"{repo} pins {path} at {pin} but .gitmodules names no submodule there")
        name, url = mods[path]
        sub = repo / path
        if checked_out(sub) == pin:
            continue
        say(f"checking out {path} at {pin[:12]} from the host artifact cache's mirror of {url}")
        mirror = ensure(url, pin, root=root, env=env)
        gitdir = pathlib.Path(git("-C", str(repo), "rev-parse", "--git-path", f"modules/{name}").stdout.decode().strip())
        gitdir = gitdir if gitdir.is_absolute() else repo / gitdir
        if gitdir.is_dir():
            # A clone from before: bring the pin and the mirror's branches into it, so the update below finds the
            # commit reachable and fetches nothing from its own remote.
            r = git("--git-dir", str(gitdir), "fetch", "--quiet", "--no-tags", str(mirror),
                    "+refs/heads/*:refs/remotes/origin/*", "+refs/tags/*:refs/tags/*")
            if r.returncode != 0:
                raise GitMirrorError(f"fetch of {path}'s branches from the mirror {mirror} failed: {_err(r)}")
        r = git("-C", str(repo), "submodule", "init", "--", path)
        if r.returncode != 0:
            raise GitMirrorError(f"git submodule init of {path} failed: {_err(r)}")
        r = git("-C", str(repo), "-c", f"submodule.{name}.url={mirror}", "-c", "protocol.file.allow=always",
                "submodule", "update", "--quiet", "--", path)
        if r.returncode != 0:
            raise GitMirrorError(f"git submodule update of {path} from the mirror {mirror} failed: {_err(r)}")
        r = git("-C", str(sub), "remote", "set-url", "origin", url)
        if r.returncode != 0:
            raise GitMirrorError(f"setting {path}'s origin back to {url} failed: {_err(r)}")
        head = checked_out(sub)
        if head != pin:
            raise CommitMismatch(f"{path} is checked out at {head or 'no commit'}, not its pinned commit {pin}, after "
                                 f"the update from {mirror}; nothing was fetched again")
        moved.append(path)
    return moved


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 3 and argv[0] == "ensure":
            print(ensure(argv[1], argv[2]))
            return 0
        if len(argv) == 2 and argv[0] == "submodules":
            submodules(pathlib.Path(argv[1]))
            return 0
        raise GitMirrorError("usage: git_mirror.py ensure <url> <commit> | git_mirror.py submodules <repo>")
    except ac.ArtifactCacheError as e:
        print(f"GIT MIRROR FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
