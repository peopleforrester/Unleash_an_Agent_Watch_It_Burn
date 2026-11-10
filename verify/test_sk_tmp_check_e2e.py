# ABOUTME: Runs scripts-knowledge's sk-tmp-check from the repo root and holds that it reports no literal system temp
# ABOUTME: path (#1315, #1317), and that each file's `tmp-ok` waiver is what keeps it quiet. Needs scripts-knowledge.
# SUITE: e2e (needs a scripts-knowledge checkout, a private repo that only a machine with Michael's repos has)
"""#1315 gave every line that names a system temp directory as a literal path a `tmp-ok: <reason>` waiver, the one
sk-tmp-check honours, and its done line reads: `sk-tmp-check`, run from the repo root, reports no "a system tempdir
path" (literal) findings. test_no_system_temp_paths.py holds the same paths with its own pattern and its own
EXCEPTIONS list, which never reads a waiver, so a deleted `tmp-ok` passed every test while sk-tmp-check reported
the line again (#1317). This runs sk-tmp-check itself.

  1. The checker is where SCRIPTS_KNOWLEDGE says (default ~/repos/workflow/scripts-knowledge), and its literal
     message and waiver word are still the ones this reads. A reworded message would otherwise read as zero findings.
  2. Run from the repo root with --warn, it reads every tracked .sh, .bash and .py file and reports no line with
     "a system tempdir path". Its other findings, bare mktemp and tempfile calls with no directory, follow TMPDIR,
     which the runners and scripts set to the checkout's tmp/ (#1261), and #1315's done line leaves them out.
  3. A scratch copy of each tracked file that carries a waiver, with the waivers renamed, makes sk-tmp-check report
     on every one of those files, and each literal it then reports sits on a line that carried a waiver. So the zero
     in 2 comes from the waivers, and a checker gone blind would fail here rather than pass.

It is not in the `# E2E TIER: tools` tier: scripts-knowledge is private and the gate host has no ~/repos, so
nothing can fetch it there (test_american_english_published.py is the same case). A missing checker fails with its
path printed, never a skip. The full scan takes about 100 seconds of wall clock on netcup.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SK = pathlib.Path(os.environ.get("SCRIPTS_KNOWLEDGE") or pathlib.Path.home() / "repos/workflow/scripts-knowledge")
CHECKER = SK / "bin/sk-tmp-check"
WRITES = SK / "bin/tmp_writes.py"
LITERAL = "a system tempdir path"
WAIVER = "tmp-ok"
RENAMED = "tmp-xx"
SUFFIXES = (".sh", ".bash", ".py")
FINDING = re.compile(r"^(?P<file>.+?):(?P<line>\d+): (?P<msg>.*)$")
SUMMARY = re.compile(r"^sk-tmp-check: (\d+) findings? in (?:(\d+) of )?(\d+) files$", re.M)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        sys.exit(1)
    print("sk-tmp-check reports no literal system temp path from the repo root, and the waivers are what keep it so.")
    sys.exit(0)


def sk_tmp_check(cwd: pathlib.Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}  # plain lines, not annotations
    return subprocess.run([sys.executable, "-I", str(CHECKER), "--warn"], cwd=cwd, capture_output=True, text=True,
                          env=env, timeout=900)


def tracked(root: pathlib.Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True,
                         check=True).stdout.split("\0")
    return [f for f in out if f.endswith(SUFFIXES) and (root / f).is_file()]


def literals(stdout: str) -> list[tuple[str, int]]:
    return [(m["file"], int(m["line"])) for m in map(FINDING.match, stdout.splitlines())
            if m and m["msg"].startswith(LITERAL)]


print("== sk-tmp-check is there, and says what this reads ==")
check("sk-tmp-check and tmp_writes.py are in the scripts-knowledge checkout (set SCRIPTS_KNOWLEDGE to another)",
      CHECKER.is_file() and WRITES.is_file(), f"{CHECKER}, {WRITES}")
if failures:
    finish()
source = WRITES.read_text()
check(f'tmp_writes.py\'s literal message still starts "{LITERAL}"', f'LITERAL = "{LITERAL};' in source,
      f"no `LITERAL = \"{LITERAL};` in {WRITES}")
check(f'tmp_writes.py\'s waiver word is still "{WAIVER}"', f'WAIVER = "{WAIVER}"' in source,
      f"no `WAIVER = \"{WAIVER}\"` in {WRITES}")
if failures:
    finish()

print("== run from the repo root, it reports no literal system temp path ==")
r = sk_tmp_check(REPO)
summary = SUMMARY.search(r.stderr)
files = tracked(REPO)
check("sk-tmp-check --warn exits 0 and prints its summary", r.returncode == 0 and summary is not None,
      f"rc={r.returncode} {r.stderr.strip()[-400:]}")
check("it read every tracked .sh, .bash and .py file", summary is not None and int(summary[3]) == len(files),
      f"read {summary[3] if summary else '?'}, tracked {len(files)}")
found = [ln for ln in r.stdout.splitlines() if LITERAL in ln]
check(f'no finding reads "{LITERAL}" (give the line a `{WAIVER}: <reason>` comment, or move it to the checkout\'s '
      "tmp/)", not found, "\n    " + "\n    ".join(found))

print("== with the waivers renamed, sk-tmp-check reports each file that carried one ==")
# This file names the waiver word only to rename it, and waives nothing.
SELF = pathlib.Path(__file__).resolve().relative_to(REPO).as_posix()
waived = {f: (REPO / f).read_text(errors="replace") for f in files
          if f != SELF and WAIVER in (REPO / f).read_text(errors="replace")}
check("the tree carries waivers to test", bool(waived), "no tracked .sh, .bash or .py file names " + WAIVER)
with tempfile.TemporaryDirectory(prefix="sk-tmp-check-1317-") as scratch:
    root = pathlib.Path(scratch)
    for rel, text in waived.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text.replace(WAIVER, RENAMED))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    s = sk_tmp_check(root)
reported = {m["file"] for m in map(FINDING.match, s.stdout.splitlines()) if m}
silent = sorted(set(waived) - reported)
check("sk-tmp-check --warn exits 0 on the copy", s.returncode == 0, f"rc={s.returncode} {s.stderr.strip()[-400:]}")
check(f"each of the {len(waived)} files reports a finding once its waivers are renamed, so each waiver is needed",
      not silent, "no finding in: " + ", ".join(silent))
bare = literals(s.stdout)
unwaived = [f"{f}:{n}" for f, n in bare if WAIVER not in (waived.get(f, "").split("\n") + [""])[n - 1]]
check("it reports literal paths there, each on a line that carried a waiver", bool(bare) and not unwaived,
      f"{len(bare)} literal findings; on lines with no waiver: {', '.join(unwaived)}")

finish()
