# ABOUTME: Re-runs the fetch call-site scan of #1116 and holds every site under verify/, .github/workflows/ and
# ABOUTME: scripts/ to a classified entry in verify/fetch-inventory.yaml, naming the file and line of each that is not.
"""#1115 is Michael's ruling of 2026-11-07 that no run or CI job downloads an artifact we already hold a pinned copy
of. Its first child (#1116) is the inventory: every fetch call site the scan finds, classified as a pinned artifact
(with its kind and the file holding its pin), an unpinned one, a live check (with what it reaches), or a line that
names a fetch tool and fetches nothing. This test re-runs the scan (verify/fetch_inventory.py) on the checkout and
fails, naming file:line, on a site the inventory misses or an entry left without a classification.

It first holds the check itself on a small git repository it writes, so a check that stopped failing reads as that:
a new curl line no entry matches, an entry with no class, a pinned entry with no pin or a pin that is no file, an
entry that matches nothing, and a comment line, which is not a site."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_inventory as fi  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fixture(root: pathlib.Path) -> pathlib.Path:
    """A repository with one fetch script, one workflow, one comment-only mention and one file out of scope."""
    repo = root / "repo"
    (repo / "verify").mkdir(parents=True)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "verify" / "fetch.sh").write_text(
        "#!/usr/bin/env bash\n"
        "# curl in a comment is not a site\n"
        "curl -fsSL -o tool.tgz https://example.invalid/tool-1.0.tgz\n"
        "curl -fsS https://api.example.invalid/healthz\n")
    (repo / ".github" / "workflows" / "ci.yml").write_text("steps:\n  - uses: actions/checkout@v4\n")
    (repo / "docs" / "notes.sh").write_text("curl https://example.invalid/\n")
    (repo / "tool.lock").write_text("tool 1.0 sha256\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    return repo


GOOD = {
    "verify/fetch.sh": [
        {"match": r"tool-1\.0\.tgz", "class": "pinned", "kind": "tool-binary", "pin": "tool.lock"},
        {"match": "healthz", "class": "live", "service": "the API's health endpoint"},
    ],
    ".github/workflows/ci.yml": [
        {"match": "checkout@v4", "class": "unpinned", "kind": "github-action", "why": "a major tag, not a SHA"},
    ],
}


def problems_with(repo: pathlib.Path, files: dict) -> list[str]:
    return fi.check(fi.sites(repo), files, repo)


with tempfile.TemporaryDirectory() as tmp:
    repo = fixture(pathlib.Path(tmp))
    found = fi.sites(repo)
    check("the fixture's scan finds its two curl lines and its uses: line, not the comment or docs/",
          [s.where() for s in found] == [".github/workflows/ci.yml:2", "verify/fetch.sh:3", "verify/fetch.sh:4"],
          f"found {[s.where() for s in found]}")
    check("a fully classified fixture passes", problems_with(repo, GOOD) == [], f"{problems_with(repo, GOOD)}")

    missing = {k: v for k, v in GOOD.items() if k != ".github/workflows/ci.yml"}
    p = problems_with(repo, missing)
    check("a file missing from the inventory fails naming its file and line",
          len(p) == 1 and p[0].startswith(".github/workflows/ci.yml:2: action site is missing from"), f"{p}")

    one = {**GOOD, "verify/fetch.sh": GOOD["verify/fetch.sh"][:1]}
    p = problems_with(repo, one)
    check("a site no entry of its file matches fails naming its file and line",
          len(p) == 1 and p[0].startswith("verify/fetch.sh:4: curl site matches no entry"), f"{p}")

    noclass = {**GOOD, "verify/fetch.sh": [GOOD["verify/fetch.sh"][0], {"match": "healthz"}]}
    p = problems_with(repo, noclass)
    check("an entry with no class fails as having no classification",
          len(p) == 1 and "verify/fetch.sh entry 2 ('healthz') has no classification" in p[0], f"{p}")

    nopin = {**GOOD, "verify/fetch.sh": [{"match": "tool", "class": "pinned", "kind": "tool-binary"},
                                         GOOD["verify/fetch.sh"][1]]}
    p = problems_with(repo, nopin)
    check("a pinned entry with no pin fails", len(p) == 1 and "is pinned but has no `pin`" in p[0], f"{p}")

    badpin = {**GOOD, "verify/fetch.sh": [{**GOOD["verify/fetch.sh"][0], "pin": "no/such.lock"},
                                          GOOD["verify/fetch.sh"][1]]}
    p = problems_with(repo, badpin)
    check("a pin that is no file in the repo fails", len(p) == 1 and "pin 'no/such.lock' is not a file" in p[0], f"{p}")

    badkind = {**GOOD, "verify/fetch.sh": [{**GOOD["verify/fetch.sh"][0], "kind": "tarball"},
                                           GOOD["verify/fetch.sh"][1]]}
    p = problems_with(repo, badkind)
    check("a kind outside KINDS fails", len(p) == 1 and "kind 'tarball' is not one of" in p[0], f"{p}")

    stale = {**GOOD, "verify/fetch.sh": [*GOOD["verify/fetch.sh"],
                                         {"match": "wget", "class": "none", "why": "gone"}]}
    p = problems_with(repo, stale)
    check("an entry that matches no site fails", len(p) == 1 and "entry 3 ('wget') matches no fetch site" in p[0],
          f"{p}")

# The checkout itself.
found = fi.sites()
try:
    files = fi.load()
except (OSError, ValueError) as e:
    print(f"FAILED: {fi.INVENTORY.relative_to(fi.REPO)} cannot be read: {e}")
    sys.exit(1)
problems = fi.check(found, files)
for problem in problems:
    print(f"  FAIL  {problem}")
check(f"each of the {len(found)} fetch call sites under {', '.join(fi.SCOPE)} has a classified entry in "
      f"{fi.INVENTORY.name}, and every entry matches a site", not problems, f"{len(problems)} problems above")
classified = fi.classify(found, files)
check("every site the scan finds takes its class from an entry", len(classified) == len(found),
      f"{len(found) - len(classified)} sites have none")
check("the scan finds sites at all (an empty scan would pass vacuously)", len(found) > 100, f"{len(found)} found")

if failures:
    print(f"FAILED: {len(failures)} fetch inventory check(s): {'; '.join(failures)}")
    sys.exit(1)
print(f"All fetch inventory checks passed: {len(found)} sites, each classified.")
