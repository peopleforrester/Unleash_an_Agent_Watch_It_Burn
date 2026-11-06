# ABOUTME: Runs prompts-agenticburn's own test command, `uv run ruff check . && uv run pytest`, on the tip of its main
# ABOUTME: and staging, fetched through gh's token, and fails when it does not pass on either (#937, from #927).
# SUITE: e2e (needs the network, uv, and gh with a token that reads the private peopleforrester/prompts-agenticburn)
#
# Why. #927's fifth criterion is "`uv run ruff check . && uv run pytest` passes in prompts-agenticburn", and no test
# here ran it (#937). This fetches that repo at each branch tip with `gh api .../tarball/<sha>`, unpacks it into a new
# temporary directory, and runs the command there through verify/prompts_wall_suite.py, with only PATH, HOME, the
# locale, TMPDIR and UV_* passed down. A lint error or a failing test on either branch turns this red.
#
# Not in the `# E2E TIER: tools` tier: the promotion gate's gh refuses `gh api` (decisions.md, #863), and the repo is
# private, so the gate has no way to read it. `bash verify/run-e2e.sh` runs this; so does a dispatched run, whose gh
# allows `gh api` GETs. No gh, no token, a refused read or no uv is a failure with the reason printed, never a skip.
from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import prompts_wall_suite as wall  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n{detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


shas: dict[str, str] = {}
for ref in wall.WALL_REFS:
    try:
        shas[ref] = wall.resolve(ref)
    except wall.WallSuiteError as e:
        print(f"FAIL: cannot read the tip of {wall.WALL_REPO}@{ref}: {e}", file=sys.stderr)
        sys.exit(1)

done: dict[str, str] = {}
for ref, sha in shas.items():
    print(f"== {wall.WALL_REPO}@{ref} ({sha[:12]}) ==")
    if sha in done:
        print(f"  same commit as {done[sha]}, which ran above")
        continue
    done[sha] = ref
    with tempfile.TemporaryDirectory(prefix="prompts-wall-") as td:
        try:
            src = wall.fetch(sha, pathlib.Path(td))
            steps = wall.run_suite(src)
        except wall.WallSuiteError as e:
            check(f"{ref}: `{wall.COMMAND}` runs", False, f"    {e}")
            continue
    for step in steps:
        tail = step.output.strip().splitlines()[-1:] or ["(no output)"]
        check(f"{ref}: `{step.command}` exits 0 (exit {step.returncode}; last line: {tail[0].strip()})", step.ok,
              "" if step.ok else "\n".join("    " + ln for ln in step.output.strip().splitlines()[-40:]))
    if not wall.passed(steps):
        skipped = [" ".join(s) for s in wall.STEPS[len(steps):]]
        if skipped:
            print(f"  not run, since `&&` stops at the first failure: {', '.join(skipped)}")
        failures.append(f"{ref}: `{wall.COMMAND}`")

if failures:
    print(f"\nFAILED: `{wall.COMMAND}` does not pass in {wall.WALL_REPO}: {'; '.join(failures)}", file=sys.stderr)
    sys.exit(1)
print(f"\n`{wall.COMMAND}` passes in {wall.WALL_REPO} on " +
      ", ".join(f"{r} ({s[:12]})" for r, s in shas.items()) + ".")
