# ABOUTME: Tests the root .gitattributes (#958): two branches that each append an entry to decisions.md, or to PROGRESS.md,
# ABOUTME: rebase cleanly with both entries kept, and no tracked file but those two merges with the union driver.
#
# Why. Concurrent dispatched runs each add an entry to the end of decisions.md, and a rebase of one onto the other
# conflicted there: nineteen runs ended `failed (rebase-conflict)` from 2026-11-05 (hecaton#532). The union driver
# turns that into a clean merge. It also merges two edits to the same lines without a conflict, keeping both, so
# the file is held to the two append-only files and every other tracked path is checked to stay on the normal merge.
#
# Each scratch repo is built in pytest's tmp_path (or a temp directory when run as `python3 <this file>`, as
# verify/run-tests.sh does), with hooks off, no user or system git config and a fixed identity. The attribute
# file the scratch repos merge with is a copy of this repo's own .gitattributes, so the test reads the real file.
#
# Union does not keep a line both sides add at the same place twice. Entries that each open with a blank line
# merge with one blank line before the first and none between the two; both headings still start their own line.
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
ATTRS = REPO / ".gitattributes"
UNION = ("PROGRESS.md", "decisions.md")


def git_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return env


def git(cwd, *args, home, check=True, stdin=None):
    """Run git in `cwd` with hooks off and no user config; returns the CompletedProcess."""
    r = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "init.defaultBranch=staging",
                        "-c", "rerere.enabled=false", *args],
                       cwd=cwd, env=git_env(home), input=stdin, capture_output=True, text=True, check=False)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} exited {r.returncode}:\n{r.stdout}{r.stderr}")
    return r


def scratch(tmp_path, attrs, path, base, entry_a, entry_b):
    """A repo whose staging holds `base` at `path`, branch a adding `entry_a` and branch b adding `entry_b` the
    same way. Rebases b onto a and returns (rebase result, the file after it, the repo)."""
    repo = tmp_path / "r"
    home = tmp_path
    repo.mkdir()
    git(repo, "init", "-q", home=home)
    if attrs is not None:
        (repo / ".gitattributes").write_text(attrs)
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(base)
    git(repo, "add", "-A", home=home)
    git(repo, "commit", "-q", "-m", "base", home=home)
    for branch, entry in (("a", entry_a), ("b", entry_b)):
        git(repo, "checkout", "-q", "-b", branch, "staging", home=home)
        f.write_text(entry(base))
        git(repo, "commit", "-q", "-am", f"entry on {branch}", home=home)
    r = git(repo, "rebase", "a", home=home, check=False)
    return r, f.read_text(), repo


def appended(entry):
    return lambda base: base + entry


ENTRY_A = "\n## 2026-11-06: run A's entry (#901, run 1)\n\nA's body, two lines\nof prose.\n"
ENTRY_B = "\n## 2026-11-06: run B's entry (#902, run 2)\n\nB's body.\n"
DECISIONS = "# Decisions\n\n## 2026-11-05: the last entry on staging\n\nIts body.\n"


def lines_in_order(text, *blocks):
    """Each block's non-blank lines appear in `text`, whole, in the order given."""
    lines = text.splitlines()
    at = 0
    for block in blocks:
        for want in (ln for ln in block.splitlines() if ln):
            try:
                at = lines.index(want, at) + 1
            except ValueError:
                return False
    return True


def test_attribute_is_read_from_this_repos_gitattributes(tmp_path):
    text = ATTRS.read_text()
    assert text.startswith("# ABOUTME: "), "the root .gitattributes opens on an ABOUTME comment"
    rules = [ln.split() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert rules == [["decisions.md", "merge=union"], ["PROGRESS.md", "merge=union"]], rules
    # In this repo, as the issue asks: `git check-attr merge decisions.md` prints union.
    for path in UNION:
        out = git(REPO, "check-attr", "merge", path, home=tmp_path).stdout
        assert out == f"{path}: merge: union\n", out
    # And from the file alone: a fresh repo with only a copy of it, so no info/attributes in this checkout's git dir
    # (hecaton's promoter writes one) can be what answers.
    repo = tmp_path / "attrs"
    repo.mkdir()
    git(repo, "init", "-q", home=tmp_path)
    (repo / ".gitattributes").write_text(text)
    for path in UNION:
        out = git(repo, "check-attr", "merge", path, home=tmp_path).stdout
        assert out == f"{path}: merge: union\n", out


def test_no_other_tracked_file_merges_as_union(tmp_path):
    files = git(REPO, "ls-files", "-z", home=tmp_path).stdout
    out = git(REPO, "check-attr", "--stdin", "-z", "merge", home=tmp_path, stdin=files).stdout.split("\0")
    union = sorted(out[i] for i in range(0, len(out) - 2, 3) if out[i + 2] == "union")
    assert union == sorted(UNION), union
    nested = [p for p in files.split("\0") if p.endswith(".gitattributes") and p != ".gitattributes"]
    assert nested == [], nested


def test_two_appends_to_decisions_rebase_with_both_entries(tmp_path):
    r, text, repo = scratch(tmp_path, ATTRS.read_text(), "decisions.md", DECISIONS, appended(ENTRY_A), appended(ENTRY_B))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "<<<<<<<" not in text and ">>>>>>>" not in text, text
    # The upstream entry first, then the replayed one, each whole, after what staging already held.
    assert lines_in_order(text, DECISIONS, ENTRY_A, ENTRY_B), text
    log = git(repo, "log", "--format=%s", home=tmp_path).stdout.split("\n")
    assert log[:3] == ["entry on b", "entry on a", "base"], log
    assert git(repo, "status", "--porcelain", home=tmp_path).stdout == ""


def test_without_the_attribute_the_same_rebase_conflicts(tmp_path):
    # The control: this is the conflict the runs ended on, so the clean rebase above is the attribute's doing.
    r, text, _ = scratch(tmp_path, None, "decisions.md", DECISIONS, appended(ENTRY_A), appended(ENTRY_B))
    assert r.returncode != 0 and "CONFLICT" in r.stdout + r.stderr, r.stdout + r.stderr
    assert "<<<<<<<" in text, text


def test_two_entries_added_under_progress_heading_rebase_with_both(tmp_path):
    # PROGRESS.md takes its entries at the top of "### Added", so two runs insert at the same line.
    base = "# Changelog\n\n## [Unreleased]\n\n### Added\n- (2026-11-05) #900: the last entry.\n"
    head = "### Added\n"

    def under(entry):
        return lambda b: b.replace(head, head + entry, 1)

    a, b = "- (2026-11-06) #901: run A's entry.\n", "- (2026-11-06) #902: run B's entry.\n"
    r, text, _ = scratch(tmp_path, ATTRS.read_text(), "PROGRESS.md", base, under(a), under(b))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "<<<<<<<" not in text, text
    assert text.count(a) == 1 and text.count(b) == 1 and "#900: the last entry." in text, text


def test_a_verify_test_edited_on_both_sides_still_conflicts(tmp_path):
    # A shared verify/ test is edited in place, not appended to: the real .gitattributes leaves it on the normal
    # merge, so two edits of the same line stop the rebase instead of keeping both.
    base = "EXPECTED = 3\n"
    r, text, _ = scratch(tmp_path, ATTRS.read_text(), "verify/test_count.py", base,
                         lambda s: "EXPECTED = 4\n", lambda s: "EXPECTED = 5\n")
    assert r.returncode != 0 and "CONFLICT" in r.stdout + r.stderr, r.stdout + r.stderr
    assert "<<<<<<<" in text, text


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        with tempfile.TemporaryDirectory() as d:
            try:
                t(pathlib.Path(d))
                print(f"  PASS  {t.__name__}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {t.__name__}: {exc}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} gitattributes union checks passed")
    sys.exit(1 if failed or not TESTS else 0)
