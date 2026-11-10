#!/usr/bin/env python3
# ABOUTME: Holds run-tests.sh to HECATON_TEST_FILES (#1319): set, it runs exactly the files listed, still setting e2e
# ABOUTME: files aside and under no_cloud_run; unset or blank, it runs every offline test as before. AGENTS.md declares it.
"""Offline. Hecaton's tests gate works out which of the offline suite's files read a change and passes them to
run-tests.sh in HECATON_TEST_FILES, one repo path per line (hecaton#623). The real run-tests.sh, no-cloud.sh and
ensure-submodules.sh are copied into a fixture repo with four tests: two offline Python tests, one offline shell test
and one marked `# SUITE: e2e`. Each offline test prints where `aws` resolves and whether either scoping variable
reached it.

1. AGENTS.md declares `Test files: `verify/test_*.py verify/test_*.sh`` beside its Test command, as the gate reads it.
2. Unset, and set to blank lines alone, run-tests.sh runs every offline test and sets the e2e one aside.
3. Set, it runs exactly the files listed, once each however often listed, with HECATON_BASE_SHA ignored even when it
   names no commit; a listed e2e file is set aside, and a list of e2e files alone runs nothing and passes, where an
   empty suite with the variable unset fails NO TESTS FOUND.
4. Each listed test runs under no_cloud_run (aws is the no-cloud stub) and sees neither variable; a failing listed test
   fails the run; a listed path that is not a test file of the suite fails the run naming it, and runs nothing.
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


print("== AGENTS.md declares the suite's test files beside its Test command ==")
agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
files_line = declared(agents, "Test files")
check(f"AGENTS.md declares `Test files: `verify/test_*.py verify/test_*.sh`` (got {files_line!r})",
      files_line == "verify/test_*.py verify/test_*.sh")
lines = agents.splitlines()
at = next((i for i, ln in enumerate(lines) if ln.startswith("Test command:")), -1)
check("the Test files line sits beside the Test command line",
      at >= 0 and any(ln.startswith("Test files:") for ln in lines[max(at - 2, 0):at + 3]))
runner = (VERIFY / "run-tests.sh").read_text(encoding="utf-8")
check("the globs are the ones run-tests.sh discovers by",
      '"${SCRIPT_DIR}"/test_*.py "${SCRIPT_DIR}"/test_*.sh' in runner)

PY_TEST = '''import os, shutil, sys
print("RAN {name}")
print("aws at", shutil.which("aws"))
print("TEST_FILES seen" if "HECATON_TEST_FILES" in os.environ else "TEST_FILES unset")
print("BASE seen" if "HECATON_BASE_SHA" in os.environ else "BASE unset")
sys.exit({rc})
'''
SH_TEST = '''echo "RAN {name}"
echo "aws at $(command -v aws)"
[[ -n "${{HECATON_TEST_FILES+x}}" ]] && echo "TEST_FILES seen" || echo "TEST_FILES unset"
[[ -n "${{HECATON_BASE_SHA+x}}" ]] && echo "BASE seen" || echo "BASE unset"
exit {rc}
'''
E2E_TEST = '# SUITE: e2e\nprint("RAN test_live.py")\n'


def fixture(root: pathlib.Path, failing: str = "") -> None:
    v = root / "verify"
    v.mkdir(parents=True)
    for name in ("run-tests.sh", "no-cloud.sh", "ensure-submodules.sh"):
        shutil.copy2(VERIFY / name, v / name)
    for name in ("test_alpha.py", "test_beta.py"):
        (v / name).write_text(PY_TEST.format(name=name, rc=1 if name == failing else 0))
    (v / "test_gamma.sh").write_text(SH_TEST.format(name="test_gamma.sh", rc=0))
    (v / "test_live.py").write_text(E2E_TEST)
    (root / "notes.txt").write_text("not a test\n")


def run(root: pathlib.Path, files: str | None, base: str | None = None) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("HECATON_TEST_FILES", "HECATON_BASE_SHA")}
    env["TMPDIR"] = str(root.parent)
    if files is not None:
        env["HECATON_TEST_FILES"] = files
    if base is not None:
        env["HECATON_BASE_SHA"] = base
    r = subprocess.run(["bash", str(root / "verify" / "run-tests.sh")], capture_output=True, text=True, env=env,
                       timeout=120)
    return r.returncode, r.stdout + r.stderr


def ran(out: str) -> list[str]:
    return re.findall(r"^RAN (\S+)$", out, re.M)


ALL = ["test_alpha.py", "test_beta.py", "test_gamma.sh"]

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    root = tmp / "repo"
    fixture(root)

    print("== unset or blank, every offline test runs ==")
    rc, out = run(root, None)
    check(f"unset: the three offline tests run, the e2e one is set aside (exit {rc})",
          rc == 0 and ran(out) == ALL and "in the E2E suite instead (bash verify/run-e2e.sh): test_live.py" in out, out)
    rc, out = run(root, "\n  \n")
    check(f"set to blank lines: as unset (exit {rc})", rc == 0 and ran(out) == ALL, out)

    print("== set, exactly the files listed run ==")
    rc, out = run(root, "verify/test_gamma.sh\nverify/test_alpha.py\n")
    check(f"two listed: those two run, in the order listed, and no other (exit {rc})",
          rc == 0 and ran(out) == ["test_gamma.sh", "test_alpha.py"] and "2 tests ran" in out
          and "2 listed, 2 of them offline tests" in out, out)
    rc, out = run(root, "verify/test_beta.py\nverify/test_beta.py\n  verify/test_beta.py  ")
    check(f"one listed three times, padded: it runs once (exit {rc})", rc == 0 and ran(out) == ["test_beta.py"], out)
    rc, out = run(root, "verify/test_alpha.py", base="0000000000000000000000000000000000000000")
    check(f"with HECATON_BASE_SHA naming no commit: the list runs and no scoping is asked for (exit {rc})",
          rc == 0 and ran(out) == ["test_alpha.py"] and "SCOPE FAILED" not in out, out)
    rc, out = run(root, "verify/test_live.py\nverify/test_beta.py")
    check(f"an e2e file listed is set aside, the rest run (exit {rc})",
          rc == 0 and ran(out) == ["test_beta.py"] and "instead (bash verify/run-e2e.sh): test_live.py" in out, out)
    rc, out = run(root, "verify/test_live.py")
    check(f"e2e files alone: nothing runs and the run passes, with no NO TESTS FOUND (exit {rc})",
          rc == 0 and ran(out) == [] and "0 tests ran" in out and "NO TESTS FOUND" not in out, out)

    print("== each listed test runs under no_cloud_run and sees neither variable ==")
    rc, out = run(root, "verify/test_alpha.py\nverify/test_gamma.sh", base="0" * 40)
    aws = re.findall(r"^aws at (.*)$", out, re.M)
    check(f"aws resolves to the no-cloud stub in each ({aws})",
          len(aws) == 2 and all(a.startswith(str(tmp)) and a.endswith("/bin/aws") for a in aws), out)
    check("neither test sees HECATON_TEST_FILES or HECATON_BASE_SHA",
          out.count("TEST_FILES unset") == 2 and out.count("BASE unset") == 2, out)

    print("== a wrong name or a failing test fails the run ==")
    for bad in ("verify/test_missing.py", "notes.txt", "verify/no-cloud.sh", "../repo/verify/test_alpha.py"):
        rc, out = run(root, f"verify/test_alpha.py\n{bad}")
        check(f"{bad} listed: the run fails naming it and runs nothing (exit {rc})",
              rc == 1 and ran(out) == [] and "not test files of this suite" in out and bad in out, out)

    failing = tmp / "failing"
    fixture(failing, failing="test_beta.py")
    rc, out = run(failing, "verify/test_beta.py")
    check(f"a failing listed test fails the run (exit {rc})",
          rc == 1 and ran(out) == ["test_beta.py"] and "SOME TESTS FAILED" in out and "test_beta.py (exit 1)" in out, out)
    rc, out = run(failing, "verify/test_alpha.py")
    check(f"the failing test not listed: it does not run and the run passes (exit {rc})",
          rc == 0 and ran(out) == ["test_alpha.py"], out)

    empty = tmp / "empty"
    (empty / "verify").mkdir(parents=True)
    for name in ("run-tests.sh", "no-cloud.sh", "ensure-submodules.sh"):
        shutil.copy2(VERIFY / name, empty / "verify" / name)
    rc, out = run(empty, None)
    check(f"an empty suite with the variable unset fails NO TESTS FOUND (exit {rc})", rc == 1 and "NO TESTS FOUND" in out,
          out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("run-tests.sh runs exactly HECATON_TEST_FILES when set, and every offline test when not.")
