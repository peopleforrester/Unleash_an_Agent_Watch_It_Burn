# ABOUTME: Fails if the old presenter terminal login comes back in any tracked file (#911, part of #908).
# ABOUTME: Matches tokens by SHA-256, so this file never carries the value it guards against.
"""No tracked file carries the old private-cluster terminal login (#908, #910, #911).

The presenter login every roster cluster gets as its `terminal-auth` Secret (`TTYD_CREDENTIAL`) was a literal
default in fleet.sh for months, in a public repo, and the pages, run-of-shows, PROJECT_STATE.md and decisions.md
wrote it out too. #910 moved it to mrf-secrets (`projects/watch-it-burn-terminal.env`, keys `WIB_TERMINAL_USER`
and `WIB_TERMINAL_PASSWORD`) and #911 took the value out of every tracked file. This test keeps it out.

It cannot name the value without putting it back, so it holds SHA-256 digests instead: of the old word (it was
both the user and the password) and of the base64 the Secret held for the pair. Every tracked file in the working
tree is split into alphanumeric tokens, each token is hashed as written and lowercased, and a hit names the file
and line, never the token. A run of the scanner on a test-owned placeholder first proves it finds a planted value,
so a scanner that matched nothing would fail here rather than pass.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent

# sha256 of the old presenter login word, and of base64("<word>:<word>") as `TTYD_CREDENTIAL` held it.
OLD_LOGIN_SHA256 = frozenset({
    "b86ed20f4e99fefb9e3a0b4e5fbbbe692903b109197c7943be07494af87bf537",
    "88812ff87e3e37ced3a70bf48c173e931a07567eca8a1806ed8a0935f14715be",
})

TOKEN = re.compile(r"[A-Za-z0-9]+")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hits(text: str, digests: frozenset[str]) -> list[int]:
    """Line numbers (1-based) holding a token whose digest, as written or lowercased, is in `digests`."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        if any(digest(t) in digests or digest(t.lower()) in digests for t in TOKEN.findall(line)):
            found.append(n)
    return found


def tracked_files(repo: pathlib.Path) -> list[pathlib.Path]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], check=True, capture_output=True).stdout
    return [repo / p for p in out.decode("utf-8").split("\0") if p]


def scan(repo: pathlib.Path, digests: frozenset[str]) -> tuple[int, list[str]]:
    """(files read, "path:line" for each hit). A tracked path absent from the tree, a submodule or a
    binary file carries no text to scan."""
    read, found = 0, []
    for path in tracked_files(repo):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        read += 1
        rel = path.relative_to(repo)
        found += [f"{rel}:{n}" for n in hits(data.decode("utf-8", "replace"), digests)]
    return read, found


print("== the scanner finds a planted login and only that (self-test) ==")
_placeholder = "placeholderPresenterLogin911"
_planted = frozenset({digest(_placeholder.lower())})
check("a token is found as written, upper-cased, and inside a user:password pair",
      hits(f"a\nlogin {_placeholder}\nb {_placeholder.upper()}\nTTYD_CREDENTIAL={_placeholder}:{_placeholder}\n",
           _planted) == [2, 3, 4])
check("a longer word that only contains it is not a hit", hits(f"x{_placeholder}y", _planted) == [])
with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    subprocess.run(["git", "init", "-q", str(t)], check=True)
    (t / "clean.md").write_text("the presenter login lives in mrf-secrets\n", encoding="utf-8")
    (t / "leak.html").write_text(f"<p>\nTerminal login: <code>{_placeholder}</code>\n</p>\n", encoding="utf-8")
    (t / "untracked.md").write_text(f"{_placeholder}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(t), "add", "clean.md", "leak.html"], check=True)
    check("a tracked file holding it is named by path and line, and an untracked one is not read",
          scan(t, _planted) == (2, ["leak.html:2"]))

print("== the old presenter terminal login is in no tracked file (#911) ==")
check("the guard holds the old login only as digests", all(re.fullmatch(r"[0-9a-f]{64}", d)
                                                          for d in OLD_LOGIN_SHA256))
_read, _found = scan(REPO, OLD_LOGIN_SHA256)
check(f"the scan read the repo's tracked text files ({_read} of them)", _read > 500)
check("no tracked file carries the old login" + (": " + ", ".join(_found) if _found else ""), not _found)

if failures:
    print(f"\n{len(failures)} check(s) failed")
    print("A tracked file carries the old presenter terminal login. It lives in mrf-secrets "
          "(projects/watch-it-burn-terminal.env, keys WIB_TERMINAL_USER and WIB_TERMINAL_PASSWORD); "
          "point at it there and do not write the value (#908, #911).")
    sys.exit(1)
print("\nNo tracked file carries the old presenter terminal login.")
