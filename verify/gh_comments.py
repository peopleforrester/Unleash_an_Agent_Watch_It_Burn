# ABOUTME: Reads an issue's comments with `gh issue view --json comments`, which carries gh's token, never GitHub's
# ABOUTME: anonymous quota (#863). A missing gh or token, a spent rate limit and any other failed read each name themselves.
"""Every comment on one GitHub issue, read with a token.

Why (#863). The cause-comment tests asked api.github.com for an issue's comments anonymously. Every dispatched run on
the host shares one IP, so one quota of 60 anonymous requests an hour, and in run 17065 (#814) the tools tier went
red when other runs had spent it: GitHub answered 403, "0 anonymous requests left this hour", and the test read that
as a missing comment. A test whose result hangs on a quota other runs spend breaks the repo's "Tests own their
inputs" rule. So the read goes through gh, which sends gh's own token (from `gh auth login`, or GH_TOKEN or
GITHUB_TOKEN in the environment) and refuses to read without one. There is no anonymous path to fall back to.

Why `gh issue view` and not `gh api`. On the hecaton host, gh is a wrapper that runs gh as michael, and the read-only
form the promotion gate gets refuses `gh api` while it allows `gh issue view`; dispatched runs get both. `gh issue
view --json comments` reads every comment through GraphQL, so each comes back as {"login", "body", "url"}, and a
GitHub App's bot is named by its slug, without the "[bot]" the REST API adds.

`read(owner_repo, number)` returns a `Read`. When the read failed, exactly one of its `missing`, `rate_limited` and
`error` is set, naming what happened; when it did not, `comments` is every comment. `check_read(read, issue, check)`
turns that into the named checks the tests print, so a spent quota reads as a spent quota and never as "no comment
names the cause".
"""
from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
from typing import Callable

# gh exits 4 when it has no token to send ("To get started with GitHub CLI, please run: gh auth login").
GH_NO_AUTH_EXIT = 4
RATE_LIMIT = re.compile(r"rate limit|HTTP 429", re.I)


@dataclasses.dataclass
class Read:
    comments: list[dict]
    missing: str = ""
    rate_limited: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not (self.missing or self.rate_limited or self.error)


def _last_lines(text: str, n: int = 3) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:])


def _comment(c: object) -> dict | None:
    """One GraphQL comment as {"login", "body", "url"}, or None when it is not one."""
    if not isinstance(c, dict) or not isinstance(c.get("author"), (dict, type(None))):
        return None
    return {"login": (c.get("author") or {}).get("login") or "?", "body": c.get("body") or "",
            "url": c.get("url") or "?"}


def read(owner_repo: str, number: str | int, timeout: int = 90) -> Read:
    """Every comment on owner_repo#number, read with `gh issue view --json comments`, or why not."""
    gh = shutil.which("gh")
    if not gh:
        return Read([], missing="no gh on PATH: the comments are read with gh's token, and an anonymous read would "
                                "share the host's one quota of 60 requests an hour (#863)")
    cmd = [gh, "issue", "view", str(number), "-R", owner_repo, "--json", "comments"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Read([], error=f"`gh issue view` did not answer within {timeout}s")
    said = _last_lines(p.stderr) or _last_lines(p.stdout)
    if p.returncode == GH_NO_AUTH_EXIT:
        return Read([], missing="gh has no token: run `gh auth login`, or set GH_TOKEN or GITHUB_TOKEN"
                                + (f" (gh said: {said})" if said else ""))
    if p.returncode != 0:
        if RATE_LIMIT.search(p.stderr) or RATE_LIMIT.search(p.stdout):
            return Read([], rate_limited=f"gh issue view exit {p.returncode}: {said}")
        return Read([], error=f"gh issue view exit {p.returncode}: {said or 'no output'}")
    try:
        doc = json.loads(p.stdout)
    except ValueError as e:
        return Read([], error=f"gh issue view printed what is not JSON ({e}): {p.stdout[:200]!r}")
    raw = doc.get("comments") if isinstance(doc, dict) else None
    if not isinstance(raw, list):
        return Read([], error=f"gh issue view printed no comments list: {p.stdout[:200]!r}")
    comments = [_comment(c) for c in raw]
    if None in comments:
        return Read([], error=f"gh issue view printed a comment that is not one: {p.stdout[:200]!r}")
    return Read(comments)


def check_read(got: Read, issue: str, check: Callable[[str, bool, str], None]) -> None:
    """The read's named checks, in order, each printed only when the one before it held: a token to read with, a
    quota not spent, an answer, and at least one comment. So the one FAIL names what stopped the read."""
    check("gh is on PATH with a token, so the read does not spend the host's shared anonymous quota (#863)",
          not got.missing, got.missing)
    if got.missing:
        return
    check("GitHub's rate limit on gh's token is not spent", not got.rate_limited, got.rate_limited)
    if got.rate_limited:
        return
    check(f"gh answers the read of {issue}'s comments", not got.error, got.error)
    if got.error:
        return
    check(f"{issue} has at least one comment", bool(got.comments), "none")
