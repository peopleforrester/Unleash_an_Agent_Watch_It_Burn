# ABOUTME: Lists the sister repo's component directories from a shallow, blob-free git clone, never GitHub's REST API,
# ABOUTME: so the read spends no share of the host's anonymous API quota (#1027). A network error is retried, then named.
"""Why git and not api.github.com (#1027).

test_platform_baseline_sister.py listed each layer of the sister's solution/platform with a GET on
api.github.com/repos/<repo>/contents/<path>, anonymously unless GITHUB_TOKEN was set. Every dispatched run on the host
shares one IP, so one quota of 60 anonymous REST requests an hour, and in run 17993 the tools tier failed it with
"cannot list 1-foundation: HTTP Error 403: rate limit exceeded"; run alone a few minutes later it passed. A run holds
no GitHub token to send (`gh auth token` is refused it), and the promotion gate's gh refuses `gh api` (see
verify/gh_comments.py), so there is no token for the tier to supply. A clone over git's smart HTTP is not a REST call
and is not counted against that quota.

read(url, ref, path) clones the one commit at `ref` with `--depth 1 --filter=blob:none --no-checkout`: the commit and
its trees, no file contents, a few hundred kilobytes for the sister. It then lists, with `git ls-tree`, the directories
directly under `path` and the directories directly under each of those. Only tree entries count, as the contents API's
type "dir" did: a file or a submodule under a layer is not a component.

A clone that fails on a network error (a failed name lookup, a refused, reset or timed-out connection, a TLS failure, an
early EOF, a 429 or a 5xx) is tried again, up to ATTEMPTS times in all, and each retry is printed. Any other failure, a
ref or path that is not there included, raises SisterReadError at once with git's own words, and so does the last
network error. Nothing here falls back to the API.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable

# Seconds before each retry; one more attempt than there are waits.
BACKOFF = (2, 5, 10)
ATTEMPTS = len(BACKOFF) + 1
TIMEOUT = 120

# git's and libcurl's words for a clone the network broke.
NETWORK_ERROR = re.compile(
    r"could not resolve host|temporary failure in name resolution|failed to connect|connection refused"
    r"|connection reset|connection timed out|operation timed out|timed out after|network is unreachable"
    r"|early EOF|unexpected disconnect|the remote end hung up unexpectedly|transfer closed|RPC failed"
    r"|gnutls_handshake|SSL_ERROR_SYSCALL|TLS connection was non-properly terminated|OpenSSL SSL_(read|connect)"
    r"|returned error: (429|50[0234])\b|HTTP/2 stream \d+ was not closed cleanly",
    re.I)


class SisterReadError(RuntimeError):
    """The sister's tree could not be read; the message names the command's target and git's last words."""


def is_network_error(stderr: str) -> bool:
    return bool(NETWORK_ERROR.search(stderr))


def _last_lines(text: str, n: int = 3) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:]) or "no output"


def _env() -> dict[str, str]:
    # No prompt for a username: GitHub answers a repo that is not there, or not public, with a request to sign in,
    # and git would wait on a terminal for it.
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def clone(url: str, ref: str, dest: pathlib.Path, run: Callable = subprocess.run,
          sleep: Callable[[float], None] = time.sleep, say: Callable[[str], None] = print) -> None:
    """The commit at `ref` of `url`, with its trees and no blobs, cloned into `dest`, which must not exist.

    Raises:
        SisterReadError: a failure that is not a network error, or a network error on the last attempt.
    """
    cmd = ["git", "-c", "init.defaultBranch=main", "-c", "credential.helper=", "clone", "--quiet", "--depth", "1",
           "--filter=blob:none", "--no-checkout", "--single-branch", "--branch", ref, url, str(dest)]
    for attempt in range(1, ATTEMPTS + 1):
        shutil.rmtree(dest, ignore_errors=True)
        try:
            p = run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=_env())
            code, said = p.returncode, _last_lines(p.stderr or p.stdout or "")
        except subprocess.TimeoutExpired:
            code, said = None, f"git clone did not finish within {TIMEOUT}s (operation timed out)"
        if code == 0:
            return
        where = f"git clone {url} at {ref} failed (attempt {attempt} of {ATTEMPTS})"
        if not is_network_error(said) or attempt == ATTEMPTS:
            raise SisterReadError(f"{where}: {said}")
        wait = BACKOFF[attempt - 1]
        say(f"  RETRY {where} on a network error, again in {wait}s: {said}")
        sleep(wait)


def dirs(checkout: pathlib.Path, path: str, run: Callable = subprocess.run) -> list[str]:
    """The directories directly under `path` in the checkout's HEAD, sorted. Files and submodules are not listed.

    Raises:
        SisterReadError: `path` is not a directory in HEAD, or git failed.
    """
    spec = f"HEAD:{path}" if path else "HEAD"
    p = run(["git", "-C", str(checkout), "ls-tree", "-z", spec], capture_output=True, text=True, timeout=TIMEOUT,
            env=_env())
    if p.returncode != 0:
        raise SisterReadError(f"git ls-tree {spec} failed: {_last_lines(p.stderr or p.stdout or '')}")
    names = []
    for entry in filter(None, p.stdout.split("\0")):
        meta, _, name = entry.partition("\t")
        if meta.split(" ")[1:2] == ["tree"]:
            names.append(name)
    return sorted(names)


def read(url: str, ref: str, path: str, run: Callable = subprocess.run,
         sleep: Callable[[float], None] = time.sleep, say: Callable[[str], None] = print) -> dict[str, list[str]]:
    """{"": the directories under `path`, and, for each of those, its name: the directories under it}, at `ref`.

    Raises:
        SisterReadError: the clone failed (see clone) or `path` is not a directory at `ref`.
    """
    with tempfile.TemporaryDirectory(prefix="sister-tree-") as td:
        checkout = pathlib.Path(td) / "sister"
        clone(url, ref, checkout, run=run, sleep=sleep, say=say)
        top = dirs(checkout, path, run=run)
        tree = {"": top}
        for name in top:
            tree[name] = dirs(checkout, f"{path}/{name}" if path else name, run=run)
        return tree


def github_url(owner_repo: str) -> str:
    return f"https://github.com/{owner_repo}.git"
