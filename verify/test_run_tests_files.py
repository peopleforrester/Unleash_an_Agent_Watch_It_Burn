#!/usr/bin/env python3
# ABOUTME: Holds the offline suite to HECATON_TEST_FILES (#1319): set, offline-suite.sh and run-tests.sh run exactly the
# ABOUTME: files listed, setting e2e ones aside, under no_cloud_run; unset, every offline test. AGENTS.md declares it.
"""Offline. Hecaton's tests gate works out which of the offline suite's files read a change and passes them to the
declared Test command in HECATON_TEST_FILES, one repo path per line (hecaton#623). That command is offline-suite.sh,
the suite's core; run-tests.sh, the command people and CI run, scopes the suite and hands its run to it. The real
run-tests.sh, offline-suite.sh, no-cloud.sh and ensure-submodules.sh are copied into a fixture repo with four tests:
two offline Python tests, one offline shell test and one marked `# SUITE: e2e`. Each offline test prints where `aws`
resolves and whether any scoping variable reached it. Each case runs through both scripts.

1. AGENTS.md declares `Test command: `bash verify/offline-suite.sh`` and, beside it, `Test files: `verify/test_*.py
   verify/test_*.sh``, as the gate reads them.
2. offline-suite.sh's code spells no repo path but no-cloud.sh and ensure-submodules.sh, read as hecaton's gate reads
   it: whole-line comments dropped, then every name a run of path characters spells. The gate runs the full suite for
   a change that reaches the command's own script through named paths, and run-tests.sh, through scope_tests.py and
   its map, is reached from 1,274 of the repo's 1,476 paths (hecaton release 0219092fddb2).
3. Unset, and set to blank lines alone, both run every offline test and set the e2e one aside.
4. Set, both run exactly the files listed, once each however often listed, with HECATON_BASE_SHA ignored even when it
   names no commit; a listed e2e file is set aside, and a list of e2e files alone runs nothing and passes, where an
   empty suite with the variable unset fails NO TESTS FOUND.
5. Each listed test runs under no_cloud_run (aws is the no-cloud stub) and sees no scoping variable; a failing listed
   test fails the run; a listed path that is not a test file of the suite fails the run naming it, and runs nothing.
6. OFFLINE_SUITE_SCOPE, how run-tests.sh hands offline-suite.sh its own scoping, runs the tests it names, and none when
   it is set to nothing; a list from the gate wins over it.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
VERIFY = REPO / "verify"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail[-3000:]}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def declared(text: str, label: str) -> str | None:
    """The value of a `<label>: `value`` line, as hecaton's gate reads it (validate.command_line); the first wins."""
    m = re.search(rf"^[ \t]*(?:[-*+][ \t]+)?(?:\*\*)?{re.escape(label)}:(?:\*\*)?[ \t]*`([^`\n]+)`", text, re.M | re.I)
    return (m.group(1).strip() or None) if m else None


print("== AGENTS.md declares the suite's core as the Test command, and its test files beside it ==")
agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
command_line = declared(agents, "Test command")
check(f"AGENTS.md declares `Test command: `bash verify/offline-suite.sh`` (got {command_line!r})",
      command_line == "bash verify/offline-suite.sh")
files_line = declared(agents, "Test files")
check(f"AGENTS.md declares `Test files: `verify/test_*.py verify/test_*.sh`` (got {files_line!r})",
      files_line == "verify/test_*.py verify/test_*.sh")
lines = agents.splitlines()
at = next((i for i, ln in enumerate(lines) if ln.startswith("Test command:")), -1)
check("the Test files line sits beside the Test command line",
      at >= 0 and any(ln.startswith("Test files:") for ln in lines[max(at - 2, 0):at + 3]))
core = (VERIFY / "offline-suite.sh").read_text(encoding="utf-8")
check("the globs are the ones offline-suite.sh discovers by",
      '"${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh' in core)

print("== offline-suite.sh spells no repo file but the two it needs ==")
NEEDED = {"verify/no-cloud.sh", "verify/ensure-submodules.sh"}


def path_names(path: str) -> list[str]:
    """The names that point at a file in code: its path from the root and from each directory below, down to its
    file name, longer than three characters (hecaton testscope._path_names)."""
    parts = path.split("/")
    return [n for n in ("/".join(parts[i:]) for i in range(len(parts))) if len(n) > 3]


def spelled(code: str) -> set[str]:
    """Every name a text spells: in each run of path characters, each piece that starts at its start or after a `/`
    and ends at its end or before a `/`, `.` or `-` (hecaton testscope._spelled)."""
    out: set[str] = set()
    for token in re.findall(r"[\w./-]+", code):
        if len(token) <= 3 or len(token) > 300:
            continue
        starts = [0, *(i + 1 for i, ch in enumerate(token) if ch == "/")]
        ends = [len(token), *(i for i, ch in enumerate(token) if ch in "/.-")]
        out.update(token[a:b] for a in starts for b in ends if b - a > 3)
    return out


# Hecaton drops only whole-line comments from a shell script; an inline comment is read as code.
code_names = spelled(re.sub(r"(?m)^\s*#.*$", "", core))
tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, text=True,
                         check=True).stdout.split("\0")
named = sorted(p for p in tracked if p and code_names & set(path_names(p)))
check(f"its code names exactly {sorted(NEEDED)} (names {named})", set(named) == NEEDED)
for gone in ("run-tests.sh", "scope_tests.py", "run-e2e.sh"):
    check(f"its code does not spell {gone}", gone not in code_names)

PY_TEST = '''import os, shutil, sys
print("RAN {name}")
print("aws at", shutil.which("aws"))
print("TEST_FILES seen" if "HECATON_TEST_FILES" in os.environ else "TEST_FILES unset")
print("BASE seen" if "HECATON_BASE_SHA" in os.environ else "BASE unset")
print("SCOPE seen" if "OFFLINE_SUITE_SCOPE" in os.environ else "SCOPE unset")
sys.exit({rc})
'''
SH_TEST = '''echo "RAN {name}"
echo "aws at $(command -v aws)"
[[ -n "${{HECATON_TEST_FILES+x}}" ]] && echo "TEST_FILES seen" || echo "TEST_FILES unset"
[[ -n "${{HECATON_BASE_SHA+x}}" ]] && echo "BASE seen" || echo "BASE unset"
[[ -n "${{OFFLINE_SUITE_SCOPE+x}}" ]] && echo "SCOPE seen" || echo "SCOPE unset"
exit {rc}
'''
E2E_TEST = '# SUITE: e2e\nprint("RAN test_live.py")\n'


RUNNER_FILES = ("run-tests.sh", "offline-suite.sh", "no-cloud.sh", "ensure-submodules.sh")
# The gate's declared command, and the one people, CI and the E2E command run.
SCRIPTS = ("offline-suite.sh", "run-tests.sh")
SCRIPT_VARS = ("HECATON_TEST_FILES", "HECATON_BASE_SHA", "OFFLINE_SUITE_SCOPE")


def fixture(root: pathlib.Path, failing: str = "") -> None:
    v = root / "verify"
    v.mkdir(parents=True)
    for name in RUNNER_FILES:
        shutil.copy2(VERIFY / name, v / name)
    for name in ("test_alpha.py", "test_beta.py"):
        (v / name).write_text(PY_TEST.format(name=name, rc=1 if name == failing else 0))
    (v / "test_gamma.sh").write_text(SH_TEST.format(name="test_gamma.sh", rc=0))
    (v / "test_live.py").write_text(E2E_TEST)
    (root / "notes.txt").write_text("not a test\n")


def run(root: pathlib.Path, files: str | None, base: str | None = None, script: str = "offline-suite.sh",
        scope: str | None = None) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k not in SCRIPT_VARS}
    env["TMPDIR"] = str(root.parent)
    if files is not None:
        env["HECATON_TEST_FILES"] = files
    if base is not None:
        env["HECATON_BASE_SHA"] = base
    if scope is not None:
        env["OFFLINE_SUITE_SCOPE"] = scope
    r = subprocess.run(["bash", str(root / "verify" / script)], capture_output=True, text=True, env=env, timeout=120)
    return r.returncode, r.stdout + r.stderr


def ran(out: str) -> list[str]:
    return re.findall(r"^RAN (\S+)$", out, re.M)


ALL = ["test_alpha.py", "test_beta.py", "test_gamma.sh"]
E2E_LINE = "in the E2E suite instead, run by hand on a cluster: test_live.py"

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    root = tmp / "repo"
    fixture(root)

    for script in SCRIPTS:
        print(f"== {script}: unset or blank, every offline test runs ==")
        rc, out = run(root, script=script, files=None)
        check(f"{script}: unset: the three offline tests run, the e2e one is set aside (exit {rc})",
              rc == 0 and ran(out) == ALL and E2E_LINE in out, out)
        rc, out = run(root, script=script, files="\n  \n")
        check(f"{script}: set to blank lines: as unset (exit {rc})", rc == 0 and ran(out) == ALL, out)

        print(f"== {script}: set, exactly the files listed run ==")
        rc, out = run(root, script=script, files="verify/test_gamma.sh\nverify/test_alpha.py\n")
        check(f"{script}: two listed: those two run, in the order listed, and no other (exit {rc})",
              rc == 0 and ran(out) == ["test_gamma.sh", "test_alpha.py"] and "2 tests ran" in out
              and "2 listed, 2 of them offline tests" in out, out)
        rc, out = run(root, script=script, files="verify/test_beta.py\nverify/test_beta.py\n  verify/test_beta.py  ")
        check(f"{script}: one listed three times, padded: it runs once (exit {rc})",
              rc == 0 and ran(out) == ["test_beta.py"], out)
        rc, out = run(root, script=script, files="verify/test_alpha.py", base="0000000000000000000000000000000000000000")
        check(f"{script}: with HECATON_BASE_SHA naming no commit: the list runs and no scoping is asked for (exit {rc})",
              rc == 0 and ran(out) == ["test_alpha.py"] and "SCOPE FAILED" not in out, out)
        rc, out = run(root, script=script, files="verify/test_live.py\nverify/test_beta.py")
        check(f"{script}: an e2e file listed is set aside, the rest run (exit {rc})",
              rc == 0 and ran(out) == ["test_beta.py"] and E2E_LINE in out, out)
        rc, out = run(root, script=script, files="verify/test_live.py")
        check(f"{script}: e2e files alone: nothing runs and the run passes, with no NO TESTS FOUND (exit {rc})",
              rc == 0 and ran(out) == [] and "0 tests ran" in out and "NO TESTS FOUND" not in out, out)

        print(f"== {script}: each listed test runs under no_cloud_run and sees no scoping variable ==")
        rc, out = run(root, script=script, files="verify/test_alpha.py\nverify/test_gamma.sh", base="0" * 40)
        aws = re.findall(r"^aws at (.*)$", out, re.M)
        check(f"{script}: aws resolves to the no-cloud stub in each ({aws})",
              len(aws) == 2 and all(a.startswith(str(tmp)) and a.endswith("/bin/aws") for a in aws), out)
        check(f"{script}: no test sees HECATON_TEST_FILES, HECATON_BASE_SHA or OFFLINE_SUITE_SCOPE",
              out.count("TEST_FILES unset") == 2 and out.count("BASE unset") == 2 and out.count("SCOPE unset") == 2, out)

        print(f"== {script}: a wrong name or a failing test fails the run ==")
        for bad in ("verify/test_missing.py", "notes.txt", "verify/no-cloud.sh", "../repo/verify/test_alpha.py"):
            rc, out = run(root, script=script, files=f"verify/test_alpha.py\n{bad}")
            check(f"{script}: {bad} listed: the run fails naming it and runs nothing (exit {rc})",
                  rc == 1 and ran(out) == [] and "not test files of this suite" in out and bad in out, out)

    failing = tmp / "failing"
    fixture(failing, failing="test_beta.py")
    for script in SCRIPTS:
        rc, out = run(failing, "verify/test_beta.py", script=script)
        check(f"{script}: a failing listed test fails the run (exit {rc})",
              rc == 1 and ran(out) == ["test_beta.py"] and "SOME TESTS FAILED" in out and "test_beta.py (exit 1)" in out,
              out)
        rc, out = run(failing, "verify/test_alpha.py", script=script)
        check(f"{script}: the failing test not listed: it does not run and the run passes (exit {rc})",
              rc == 0 and ran(out) == ["test_alpha.py"], out)

    print("== OFFLINE_SUITE_SCOPE: run-tests.sh's own scoping, as offline-suite.sh reads it ==")
    rc, out = run(root, None, base="b" * 40, scope="test_gamma.sh\n")
    check(f"one name: that test alone runs, counted against the whole suite (exit {rc})",
          rc == 0 and ran(out) == ["test_gamma.sh"]
          and f"scoped to the change since HECATON_BASE_SHA={'b' * 40}: 1 of the 3 offline tests" in out, out)
    rc, out = run(root, None, base="b" * 40, scope="")
    check(f"set to nothing: no test runs and the run passes (exit {rc})",
          rc == 0 and ran(out) == [] and "0 of the 3 offline tests; the other 3 read nothing it touched" in out, out)
    rc, out = run(root, "verify/test_alpha.py", scope="test_gamma.sh\n")
    check(f"with a list from the gate as well: the list wins (exit {rc})",
          rc == 0 and ran(out) == ["test_alpha.py"] and "scoped to the change" not in out, out)
    rc, out = run(root, None, script="run-tests.sh", scope="test_gamma.sh\n")
    check(f"run-tests.sh does not pass on a scope it did not decide itself (exit {rc})",
          rc == 0 and ran(out) == ALL and "scoped to the change" not in out, out)

    empty = tmp / "empty"
    (empty / "verify").mkdir(parents=True)
    for name in RUNNER_FILES:
        shutil.copy2(VERIFY / name, empty / "verify" / name)
    for script in SCRIPTS:
        rc, out = run(empty, None, script=script)
        check(f"{script}: an empty suite with the variable unset fails NO TESTS FOUND (exit {rc})",
              rc == 1 and "NO TESTS FOUND" in out, out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("offline-suite.sh and run-tests.sh run exactly HECATON_TEST_FILES when set, and every offline test when not.")
