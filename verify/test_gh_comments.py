# ABOUTME: verify/gh_comments.py reads an issue's comments with gh's token and names a missing token, a spent rate
# ABOUTME: limit and any other failed read apart from a missing comment (#863). Offline: gh is a stub on PATH.
"""Offline. The real reads are the three cause-comment tests in the tools tier, which call verify/gh_comments.py.

#863: in run 17065 (#814) GitHub answered test_dispatched_runs_cause_comment.py's anonymous read of #633's comments
with 403, "0 anonymous requests left this hour", because every run on the host shares one IP and one quota, and the
test read that as no comment at all. The read now goes through `gh issue view --json comments`, which carries gh's
token. Each case here puts a stub gh alone on PATH that answers as gh does (exit 4 when it has no token, exit 1 and
"API rate limit exceeded" when the quota is spent, {"comments": [...]} with GraphQL's author.login, body and url when
it answers) and checks what the helper says.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gh_comments  # noqa: E402

# The stub runs with only its own directory on PATH, so it names cat by its full path.
CAT = shutil.which("cat") or "/bin/cat"

CAUSE_TESTS = ["test_dispatched_runs_cause_comment.py", "test_agent_obs_cause_comment.py",
               "test_prose_gate_e2e_wait_cause_comment.py"]

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def stub_gh(bindir: pathlib.Path, exit_code: int, stdout: str = "", stderr: str = "") -> pathlib.Path:
    """A gh that records its arguments, prints what it is given and exits as told."""
    (bindir / "out").write_text(stdout)
    (bindir / "err").write_text(stderr)
    gh = bindir / "gh"
    gh.write_text("#!/bin/sh\n"
                  f'printf "%s\\n" "$@" > "{bindir}/args"\n'
                  f'{CAT} "{bindir}/out"\n{CAT} "{bindir}/err" >&2\nexit {exit_code}\n')
    gh.chmod(0o755)
    return gh


def run_case(exit_code: int, stdout: str = "", stderr: str = "", with_gh: bool = True, what: str = "comments"):
    """The helper's Read and the checks check_read printed, with only the stub's directory on PATH. what="body"
    reads with read_body instead of read, and what="title" with read_body(with_title=True)."""
    with tempfile.TemporaryDirectory() as td:
        bindir = pathlib.Path(td)
        if with_gh:
            stub_gh(bindir, exit_code, stdout, stderr)
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = str(bindir)
        try:
            if what == "title":
                got = gh_comments.read_body("owner/repo", 7, with_title=True)
            else:
                got = (gh_comments.read_body if what == "body" else gh_comments.read)("owner/repo", 7)
        finally:
            os.environ["PATH"] = old
        args = (bindir / "args").read_text().split("\n") if (bindir / "args").exists() else []
    seen: list[tuple[str, bool, str]] = []
    gh_comments.check_read(got, "owner/repo#7", lambda n, ok, d="": seen.append((n, ok, d)),
                           "body" if what == "title" else what)
    return got, seen, args


def only_failure(seen: list[tuple[str, bool, str]]) -> str:
    bad = [n for n, ok, _ in seen if not ok]
    return bad[0] if len(bad) == 1 and not seen[-1][1] else f"not one last failure: {seen}"


print("== every comment comes back as login, body and url ==")
answer = {"comments": [
    {"id": "IC_1", "author": {"login": "hecatongithub"}, "body": "one", "url": "https://x/7#issuecomment-1"},
    {"id": "IC_2", "author": {"login": "peopleforrester"}, "body": "two", "url": "https://x/7#issuecomment-2"},
    {"id": "IC_3", "author": None, "body": None, "url": "https://x/7#issuecomment-3"},
]}
got, seen, args = run_case(0, json.dumps(answer))
check("a read gh answers holds every comment, in order, as login, body and url", got.comments == [
    {"login": "hecatongithub", "body": "one", "url": "https://x/7#issuecomment-1"},
    {"login": "peopleforrester", "body": "two", "url": "https://x/7#issuecomment-2"},
    {"login": "?", "body": "", "url": "https://x/7#issuecomment-3"},
], str(got))
check("the read is ok and names no failure", got.ok and not (got.missing or got.rate_limited or got.error), str(got))
check("gh is asked with `issue view 7 -R owner/repo --json comments`, the read the gate's gh wrapper allows",
      args[:7] == ["issue", "view", "7", "-R", "owner/repo", "--json", "comments"], str(args))
check("check_read passes all four checks on it", [ok for _, ok, _ in seen] == [True] * 4, str(seen))

print("== no comment at all is its own failure ==")
got, seen, _ = run_case(0, '{"comments": []}')
check("an empty issue reads ok with no comments", got.ok and got.comments == [], str(got))
check("check_read fails 'has at least one comment', and only that",
      only_failure(seen) == "owner/repo#7 has at least one comment", str(seen))

print("== no gh on PATH names the token, and never reads anonymously ==")
got, seen, args = run_case(0, with_gh=False)
check("the read names the missing gh", "no gh on PATH" in got.missing and "anonymous" in got.missing, got.missing)
check("check_read fails the token check and prints nothing after it",
      len(seen) == 1 and not seen[0][1] and "token" in seen[0][0], str(seen))

print("== gh with no token names how to give it one ==")
got, seen, _ = run_case(4, stderr="To get started with GitHub CLI, please run:  gh auth login\n"
                                  "Alternatively, populate the GH_TOKEN environment variable with a GitHub API "
                                  "authentication token.\n")
check("exit 4 is a missing token, naming gh auth login and GH_TOKEN",
      "gh auth login" in got.missing and "GH_TOKEN" in got.missing and not got.error, str(got))
check("check_read fails the token check alone", len(seen) == 1 and not seen[0][1], str(seen))

print("== a spent rate limit is its own named failure, not a missing comment ==")
for label, out, err in [
    ("primary", '{"message":"API rate limit exceeded for user ID 1."}',
     "gh: API rate limit exceeded for user ID 1. (HTTP 403)\n"),
    ("secondary", '{"message":"You have exceeded a secondary rate limit."}',
     "gh: You have exceeded a secondary rate limit. (HTTP 403)\n"),
    ("429", "", "gh: Too Many Requests (HTTP 429)\n"),
]:
    got, seen, _ = run_case(1, out, err)
    check(f"a {label} rate limit is read as rate_limited, with what gh said", bool(got.rate_limited)
          and "HTTP" in got.rate_limited and not got.error and not got.missing, str(got))
    check(f"check_read fails the rate-limit check on a {label} limit after a passing token check, and stops there",
          [ok for _, ok, _ in seen] == [True, False] and "rate limit" in seen[1][0], str(seen))

print("== any other failed read names gh's exit and words ==")
got, seen, _ = run_case(1, '{"message":"Not Found"}', "gh: Not Found (HTTP 404)\n")
check("a 404 is an error naming the exit and HTTP 404", "exit 1" in got.error and "HTTP 404" in got.error, str(got))
check("check_read fails the answer check, after two passes", [ok for _, ok, _ in seen] == [True, True, False], str(seen))
got, _, _ = run_case(0, "<html>not json</html>")
check("output that is not JSON is an error", "not JSON" in got.error, str(got))
got, _, _ = run_case(0, json.dumps([{"id": 1}]))
check("JSON with no comments list is an error", "no comments list" in got.error, str(got))
got, _, _ = run_case(0, json.dumps({"comments": ["text"]}))
check("a comments list holding what is not a comment is an error", "not one" in got.error, str(got))

print("== read_body reads the issue's body the same way (#946) ==")
got, seen, args = run_case(0, json.dumps({"body": "The desk answers 200."}), what="body")
check("read_body holds the body gh answers, and no comments", got.ok and got.body == "The desk answers 200."
      and got.comments == [], str(got))
check("gh is asked with `issue view 7 -R owner/repo --json body`, the read the gate's gh wrapper allows",
      args[:7] == ["issue", "view", "7", "-R", "owner/repo", "--json", "body"], str(args))
check("check_read(what='body') passes all four checks on it, the last naming the body",
      [ok for _, ok, _ in seen] == [True] * 4 and seen[-1][0] == "owner/repo#7 has a body", str(seen))
got, seen, _ = run_case(0, '{"body": "  "}', what="body")
check("a blank body fails 'has a body', and only that", only_failure(seen) == "owner/repo#7 has a body", str(seen))
got, seen, _ = run_case(4, stderr="To get started with GitHub CLI, please run:  gh auth login\n", what="body")
check("read_body names a missing token as read does", "gh auth login" in got.missing and len(seen) == 1, str(got))
got, seen, _ = run_case(1, stderr="gh: API rate limit exceeded for user ID 1. (HTTP 403)\n", what="body")
check("read_body names a spent rate limit as read does, and check_read stops there",
      bool(got.rate_limited) and [ok for _, ok, _ in seen] == [True, False], str(seen))
for label, out in [("a list", "[]"), ("no body field", '{"title": "x"}'), ("a null body", '{"body": null}')]:
    got, seen, _ = run_case(0, out, what="body")
    check(f"output with {label} is an error naming the missing body",
          "no body" in got.error and only_failure(seen) == "gh answers the read of owner/repo#7's body", str(got))

print("== read_body(with_title=True) reads the title in the same read (#1012) ==")
got, seen, args = run_case(0, json.dumps({"title": "Add the note", "body": "The note."}), what="title")
check("it holds the title and the body gh answers", got.ok and got.title == "Add the note" and got.body == "The note.",
      str(got))
check("gh is asked with `issue view 7 -R owner/repo --json title,body`",
      args[:7] == ["issue", "view", "7", "-R", "owner/repo", "--json", "title,body"], str(args))
check("check_read(what='body') passes all four checks on it", [ok for _, ok, _ in seen] == [True] * 4, str(seen))
got, seen, _ = run_case(0, '{"body": "The note."}', what="title")
check("output with no title field is an error naming the missing title",
      "no title" in got.error and only_failure(seen) == "gh answers the read of owner/repo#7's body", str(got))
got, _, _ = run_case(0, json.dumps({"body": "x"}), what="body")
check("read_body without with_title leaves the title empty and asks for the body alone", got.ok and got.title == "",
      str(got))

print("== the three cause-comment tests read through the helper, and nothing reads anonymously ==")
for name in CAUSE_TESTS:
    src = (HERE / name).read_text(encoding="utf-8")
    check(f"{name} reads with gh_comments.read and checks it with check_read",
          "gh_comments.read(OWNER_REPO, NUMBER)" in src and "gh_comments.check_read(" in src)
    check(f"{name} has no urllib read of api.github.com of its own",
          "urllib" not in src and "urlopen" not in src and not re.search(r"https://api\.github\.com", src))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All gh_comments checks passed.")
