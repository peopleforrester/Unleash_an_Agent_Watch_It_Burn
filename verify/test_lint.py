# ABOUTME: Repo-wide lint gate: every tracked shell script parses (bash -n) and has no shellcheck errors,
# ABOUTME: and every tracked Python file compiles. Submodules lint in their own repos.
#
# Why. test_verify_harness.py runs bash -n over verify/ only, but most of the platform's behaviour lives in
# scripts outside it (infra/terraform/fleet/fleet.sh, scripts/, teardown/, the demo toggles). A syntax
# error in one of those is found by the first person to run it, usually on the day. Shellcheck runs at
# error severity only: warnings are style, errors are scripts that cannot do what they say.
import pathlib, shutil, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
failures = []


def check(n, c):
    print(f"  {'PASS' if c else 'FAIL'}  {n}")
    if not c:
        failures.append(n)


def tracked(pattern):
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", pattern],
                         capture_output=True, text=True, check=True).stdout
    return [REPO / p for p in out.split("\0") if p and (REPO / p).is_file()]


shell = tracked("*.sh")
python = tracked("*.py")
check(f"found tracked shell scripts to lint ({len(shell)})", len(shell) > 0)
check(f"found tracked Python files to lint ({len(python)})", len(python) > 0)

print("== every shell script parses ==")
bad = [str(p.relative_to(REPO)) for p in shell
       if subprocess.run(["bash", "-n", str(p)], capture_output=True).returncode != 0]
check(f"bash -n clean ({', '.join(bad) or 'all'})", not bad)

print("== every Python file compiles ==")
bad = []
for p in python:
    try:
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
    except SyntaxError as e:
        bad.append(f"{p.relative_to(REPO)}:{e.lineno}")
check(f"compiles ({', '.join(bad) or 'all'})", not bad)

print("== shellcheck finds no errors ==")
have_shellcheck = bool(shutil.which("shellcheck"))
if have_shellcheck:
    r = subprocess.run(["shellcheck", "-S", "error", *map(str, shell)], capture_output=True, text=True)
    check("shellcheck -S error clean", r.returncode == 0)
    if r.returncode != 0:
        print(r.stdout[-4000:])
else:
    print("  SKIP  shellcheck not on PATH")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
if not have_shellcheck:
    # Exit 2, the repo's SKIP code: the parse and compile checks passed, shellcheck did not run.
    print("Parse and compile checks passed; shellcheck was skipped (not installed).", file=sys.stderr)
    sys.exit(2)
print("All lint checks passed.")
