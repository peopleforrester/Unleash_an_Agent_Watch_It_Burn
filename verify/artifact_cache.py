# ABOUTME: The host's one content-addressed cache of pinned downloads, <root>/sha256/<hex>, outside any worktree (#1117).
# ABOUTME: get(sha256, url) re-checks every hit, fetches only on a miss, and fails on a mismatch without downloading again.
"""Runs and CI jobs used to download, on every run, artifacts already held as pinned copies on the same host (#1115).
Every pinned fetch goes through get() here instead, which keeps one copy per SHA-256 for the whole host.

The root is the first of these that is set and not empty:
  1. HECATON_TOOLS_CACHE, hecaton's shared tools store on netcup (#1004, hecaton#540);
  2. WIB_ARTIFACT_CACHE, which the self-hosted CI runners set;
  3. ${XDG_CACHE_HOME:-$HOME/.cache}/wib-artifacts, a per-user default.
A root inside a git worktree is refused, naming the path and the worktree: a cache there is one worktree's copy, which
is the per-worktree download this replaces, and the offline tests that scan the tree would read it.

get(sha256, url) returns <root>/sha256/<sha256>:
  - A hit is hashed again and served only when it matches, with no network access. A hit that does not match fails,
    naming the path and both sums, and the file is left where it is for a person to look at: it is never deleted and
    downloaded again, since a cache file that changed under its own sum is something to find out about, not paper over.
  - A miss takes a lock on that sum, so runs side by side fetch it once between them, looks again, and only then goes
    to the network. The download is written to a temp file in the same directory, hashed, and renamed into place only
    when it matches, so no reader ever sees a half-written or unverified file. A download that does not match is
    removed and fails, naming the URL and both sums.
  - A fetch the network broke (a refused or reset connection, a failed name lookup, a timeout, a body cut short, a 429
    or a 5xx) is tried again, up to len(BACKOFF) + 1 times in all, each retry printed to stderr: the curl that
    fetch-e2e-tools.sh used before #1118 retried three times. Any other failure (a 404, say) and a download that does not
    match fail at once.
  - Every network fetch, good or bad, is one line appended to the fetch log: ARTIFACT_FETCH_LOG, or <root>/fetch.log.
    A warm run's log is unchanged, which is how the last child of #1115 shows a warm run made no download.

A hit needs only read access, so a read-only store serves hits; a miss there fails on the write, naming the path.

Command line (verify/artifact-cache.sh runs this):
  artifact-cache.sh root               print the resolved root
  artifact-cache.sh get <sha256> <url> print the path of the verified file, fetching it on a miss
Any failure prints one line starting ARTIFACT CACHE FAILED to stderr and exits 1."""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import http.client
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import BinaryIO

ROOT_VARS = ("HECATON_TOOLS_CACHE", "WIB_ARTIFACT_CACHE")
DEFAULT_SUBDIR = "wib-artifacts"
SHA256 = re.compile(r"[0-9a-f]{64}")
CHUNK = 1 << 20
# Seconds a connect or a read may stall before the fetch fails; a slow but moving download is not cut off.
TIMEOUT = 60
# Seconds before each retry of a fetch the network broke; one more attempt than there are waits.
BACKOFF = (2, 5, 10)

# A fetcher writes the bytes at url to the open file it is given.
Fetcher = Callable[[str, BinaryIO], None]


class ArtifactCacheError(RuntimeError):
    """The cache could not serve the artifact; the message names what and where."""


class RootInWorktree(ArtifactCacheError):
    """The resolved root sits inside a git worktree."""


class ArtifactMismatch(ArtifactCacheError):
    """A cached file, or a fresh download, does not hash to the pinned SHA-256."""


class FetchFailed(ArtifactCacheError):
    """The fetcher raised; transient says whether the network broke it, so another attempt may do better."""

    def __init__(self, message: str, transient: bool):
        super().__init__(message)
        self.transient = transient


def is_transient(e: BaseException) -> bool:
    """Whether a fetcher's exception is the network's doing: a 429 or a 5xx, or any connection, name lookup, timeout or
    short-body error. An HTTP status other than those (a 404 or a 403) is the server's answer and is not retried."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or e.code >= 500
    if isinstance(e, urllib.error.URLError):
        return not isinstance(e.reason, (FileNotFoundError, PermissionError, IsADirectoryError))
    return isinstance(e, (TimeoutError, ConnectionError, http.client.HTTPException))


def worktree_of(path: pathlib.Path) -> pathlib.Path | None:
    """The git worktree (or submodule) that holds path, found by a .git entry on it or any parent; None when none does.
    The path need not exist yet."""
    p = path.expanduser().resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d
    return None


def resolve_root(env: Mapping[str, str] | None = None) -> pathlib.Path:
    """The cache root, by the order in the module docstring; RootInWorktree when it is inside a git worktree."""
    env = os.environ if env is None else env
    source = ""
    for var in ROOT_VARS:
        if env.get(var):
            root, source = pathlib.Path(env[var]), var
            break
    else:
        if env.get("XDG_CACHE_HOME"):
            root, source = pathlib.Path(env["XDG_CACHE_HOME"]) / DEFAULT_SUBDIR, "XDG_CACHE_HOME"
        elif env.get("HOME"):
            root, source = pathlib.Path(env["HOME"]) / ".cache" / DEFAULT_SUBDIR, "HOME"
        else:
            raise ArtifactCacheError(f"no cache root: none of {', '.join(ROOT_VARS)}, XDG_CACHE_HOME or HOME is set")
    root = root.expanduser().resolve()
    tree = worktree_of(root)
    if tree is not None:
        raise RootInWorktree(f"the cache root {root} (from {source}) is inside the git worktree {tree}; "
                             "the host cache must sit outside every worktree")
    return root


def path_for(sha256: str, root: pathlib.Path) -> pathlib.Path:
    return root / "sha256" / sha256


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def url_fetch(url: str, out: BinaryIO) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "wib-artifact-cache"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        while chunk := r.read(CHUNK):
            out.write(chunk)


def fetch_log_path(root: pathlib.Path, env: Mapping[str, str] | None = None) -> pathlib.Path:
    env = os.environ if env is None else env
    return pathlib.Path(env["ARTIFACT_FETCH_LOG"]) if env.get("ARTIFACT_FETCH_LOG") else root / "fetch.log"


def log_fetch(log: pathlib.Path, url: str, sha256: str, size: int, result: str) -> None:
    """One line per network fetch: time, URL, pinned sum, bytes received, result. Tab-separated, and written with one
    O_APPEND write so lines from runs side by side never interleave."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{stamp}\t{url}\t{sha256}\t{size}\t{result}\n".encode()
    log.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def _check_hit(path: pathlib.Path, sha256: str) -> pathlib.Path:
    if not path.is_file():
        raise ArtifactMismatch(f"cache entry {path} is not a regular file; expected the file with SHA-256 {sha256}")
    got = sha256_of(path)
    if got != sha256:
        raise ArtifactMismatch(f"cache hit {path} does not match its pin: expected SHA-256 {sha256}, got {got}; "
                               "the file is left in place and not downloaded again")
    return path


def _fetch_once(final: pathlib.Path, sha256: str, url: str, fetch: Fetcher, log: pathlib.Path) -> None:
    """One network fetch of a miss into a temp file beside final, hashed and renamed into place only when it matches.
    The caller holds the sum's lock."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{sha256}.", suffix=".part", dir=final.parent)
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                fetch(url, out)
            except Exception as e:
                out.flush()
                log_fetch(log, url, sha256, tmp.stat().st_size, f"error {type(e).__name__}")
                raise FetchFailed(f"fetch of {url} for SHA-256 {sha256} failed: {e}", is_transient(e)) from e
            out.flush()
            os.fsync(out.fileno())
        size = tmp.stat().st_size
        got = sha256_of(tmp)
        log_fetch(log, url, sha256, size, "ok" if got == sha256 else f"mismatch {got}")
        if got != sha256:
            raise ArtifactMismatch(f"download of {url} does not match its pin: expected SHA-256 {sha256}, "
                                   f"got {got} ({size} bytes); nothing was written to {final}")
        os.chmod(tmp, 0o644)
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)


def get(sha256: str, url: str, *, root: pathlib.Path | None = None, fetch: Fetcher = url_fetch,
        env: Mapping[str, str] | None = None, backoff: Sequence[float] = BACKOFF,
        sleep: Callable[[float], None] = time.sleep) -> pathlib.Path:
    """The verified file for sha256: a hit re-checked, or a miss fetched from url once (a fetch the network broke tried
    again after each wait in backoff) and checked before the rename."""
    if not SHA256.fullmatch(sha256):
        raise ArtifactCacheError(f"{sha256!r} is not a SHA-256: want 64 lowercase hex digits (for {url})")
    root = resolve_root(env) if root is None else root
    final = path_for(sha256, root)
    if final.exists():
        return _check_hit(final, sha256)

    d = final.parent
    try:
        d.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(d / f".{sha256}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as e:
        raise ArtifactCacheError(f"cache miss for {sha256} and {d} is not writable: {e}") from e
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Another run may have fetched it while this one waited for the lock.
        if final.exists():
            return _check_hit(final, sha256)
        log = fetch_log_path(root, env)
        attempts = len(backoff) + 1
        for attempt in range(1, attempts + 1):
            try:
                _fetch_once(final, sha256, url, fetch, log)
                return final
            except FetchFailed as e:
                if not e.transient:
                    raise
                if attempt == attempts:
                    raise FetchFailed(f"{e} (a network error on each of {attempts} attempts)", True) from e
                wait = backoff[attempt - 1]
                print(f"  RETRY {e} (attempt {attempt} of {attempts}; again in {wait:g}s)", file=sys.stderr, flush=True)
                sleep(wait)
        raise AssertionError("unreachable")
    finally:
        os.close(lock_fd)


def main(argv: list[str]) -> int:
    try:
        if argv == ["root"]:
            print(resolve_root())
            return 0
        if len(argv) == 3 and argv[0] == "get":
            print(get(argv[1], argv[2]))
            return 0
        raise ArtifactCacheError("usage: artifact-cache.sh root | artifact-cache.sh get <sha256> <url>")
    except ArtifactCacheError as e:
        print(f"ARTIFACT CACHE FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
