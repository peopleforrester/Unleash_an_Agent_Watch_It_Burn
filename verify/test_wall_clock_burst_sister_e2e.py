# ABOUTME: Holds #927's criterion on prompts-agenticburn itself: its main has an offline fake-clock test that feeds the wall a
# ABOUTME: burst and asserts card count, shown prompt and "+N more" after each tick, and that test passes and catches a bad page.
# SUITE: e2e (needs the network and gh with a token: prompts-agenticburn is private, and uv fetches its test pins)
"""Why (#936). #927's criterion reads: "An offline test in prompts-agenticburn with a controlled clock (no real timers,
no network) feeds a burst of prompts and checks the card count, which prompt was shown, and the counter value after
each tick." The fake-clock test #927 added here drives this repo's display.js, not the wall, so test review run 17682
found nothing that fails when the criterion stops holding. prompts-agenticburn#18 then landed the wall's throttle with
that test (`6601313a`, test_wall_page.py). A run here cannot change that repo, so this reads it.

What it does, on prompts-agenticburn's `main` as it is when it runs:

1. Reads the head commit and its tarball through `gh api`, with gh's token. The repo is private, so there is no
   anonymous path, and a missing gh or a failed read is a failure with gh's reason.
2. Holds test_wall_page.py and conftest.py to the criterion with verify/wall_clock_burst.py: MiniRacer with fake
   timers, performance.now(), fetch and EventSource on one virtual clock, the page served at /, the fleet poller off,
   and at least one test that feeds a burst and asserts on the page after every tick, reading the card count, the
   shown prompt and "+N more".
3. Runs that repo's test_wall_page.py under its own lock (`uv run --frozen pytest`) and checks each burst test passed.
4. Sets the page's `CARD_INTERVAL_MS` to 1 ms and runs the burst tests again: one card per prompt arrival is what the
   criterion's test exists to catch, so at least one of them must fail on an assert. The anchor is checked first.

Not in the tools tier: the promotion gate's gh refuses `gh api` (verify/gh_comments.py says why), so run-e2e.sh runs
this by hand, and a dispatched run, whose gh allows `gh api`, runs it directly.
"""
from __future__ import annotations

import io
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import package_cache  # noqa: E402
import wall_clock_burst  # noqa: E402

SISTER = "peopleforrester/prompts-agenticburn"
BRANCH = "main"
PAGE_TEST = "test_wall_page.py"
WALL = "templates/wall.html"
INTERVAL_ANCHOR = "const CARD_INTERVAL_MS = 1500;"
failures: list[str] = []
passed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    (passed if ok else failures).append(name)


def finish() -> None:
    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"\n{len(passed)}/{len(passed)} checks passed: {SISTER}'s fake-clock burst test holds #927's criterion")


def gh(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=not binary, timeout=120)


def pytest_run(src: pathlib.Path, junit: pathlib.Path, *targets: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"}}
    env["UV_LINK_MODE"] = "copy"
    # uv's cache is the host artifact cache's (#1121); `--frozen` installs what the sister repo's uv.lock pins, and uv
    # checks each package against the hash the lock records.
    env["UV_CACHE_DIR"] = package_cache.installer_env()["UV_CACHE_DIR"]
    return subprocess.run(["uv", "run", "--frozen", "--directory", str(src), "pytest", "-q", "-p", "no:cacheprovider",
                           f"--junitxml={junit}", *targets], capture_output=True, text=True, timeout=900, env=env)


def outcomes(junit: pathlib.Path) -> dict[str, str]:
    """test name -> passed, failed (an assert), error or skipped, from pytest's JUnit XML."""
    out: dict[str, str] = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        kind = "passed"
        for child in case:
            if child.tag in {"failure", "error", "skipped"}:
                kind = {"failure": "failed"}.get(child.tag, child.tag)
        out[case.get("name", "?")] = kind
    return out


def tail(text: str, n: int = 15) -> str:
    return "\n        ".join(text.strip().splitlines()[-n:])


missing = [tool for tool in ("gh", "uv") if shutil.which(tool) is None]
if missing:
    print(f"FAIL: {', '.join(missing)} not on PATH; this check reads {SISTER} with gh and runs its tests with uv",
          file=sys.stderr)
    sys.exit(1)

head = gh("api", f"repos/{SISTER}/commits/{BRANCH}", "--jq", ".sha")
sha = head.stdout.strip()
if head.returncode != 0 or len(sha) != 40:
    print(f"FAIL: cannot read {SISTER}'s {BRANCH} through gh api (exit {head.returncode}): "
          f"{tail(head.stderr or head.stdout, 3)}", file=sys.stderr)
    sys.exit(1)
print(f"{SISTER} {BRANCH} is {sha}")

tarball = gh("api", f"repos/{SISTER}/tarball/{sha}", binary=True)
if tarball.returncode != 0 or not tarball.stdout:
    print(f"FAIL: cannot download {SISTER} at {sha} (exit {tarball.returncode}): "
          f"{tarball.stderr.decode(errors='replace')[-400:]}", file=sys.stderr)
    sys.exit(1)

with tempfile.TemporaryDirectory(prefix="wall-clock-burst-") as tmp:
    src = pathlib.Path(tmp) / "src"
    src.mkdir()
    with tarfile.open(fileobj=io.BytesIO(tarball.stdout), mode="r:gz") as tar:
        members = []
        for m in tar.getmembers():
            parts = pathlib.PurePosixPath(m.name).parts
            if len(parts) < 2:
                continue
            m.name = str(pathlib.PurePosixPath(*parts[1:]))
            members.append(m)
        tar.extractall(src, members=members, filter="data")

    for rel in (PAGE_TEST, "conftest.py", WALL, "uv.lock"):
        check(f"{SISTER} at {sha[:8]} has {rel}", (src / rel).is_file())
    if failures:
        finish()

    result = wall_clock_burst.analyse((src / PAGE_TEST).read_text(), (src / "conftest.py").read_text())
    for name, ok, detail in result.checks:
        check(f"{PAGE_TEST}: {name}", ok, detail)
    if result.burst_tests:
        print(f"  burst tests: {', '.join(result.burst_tests)}")
    if failures:
        finish()

    junit = pathlib.Path(tmp) / "page.xml"
    run = pytest_run(src, junit, PAGE_TEST)
    check(f"{SISTER}'s {PAGE_TEST} passes under its own lock (exit {run.returncode})", run.returncode == 0,
          tail(run.stdout + run.stderr))
    seen = outcomes(junit) if junit.is_file() else {}
    for name in result.burst_tests:
        check(f"{name} ran and passed", seen.get(name) == "passed", f"outcome: {seen.get(name, 'did not run')}")

    wall = src / WALL
    html = wall.read_text()
    if html.count(INTERVAL_ANCHOR) != 1:
        check(f"{WALL} has the anchor {INTERVAL_ANCHOR!r} exactly once, for the 1 ms page", False,
              f"found {html.count(INTERVAL_ANCHOR)} times in {SISTER}'s {WALL} at {sha[:8]}")
        finish()
    wall.write_text(html.replace(INTERVAL_ANCHOR, "const CARD_INTERVAL_MS = 1;"))
    bad_junit = pathlib.Path(tmp) / "bad.xml"
    bad = pytest_run(src, bad_junit, *(f"{PAGE_TEST}::{name}" for name in result.burst_tests))
    bad_seen = outcomes(bad_junit) if bad_junit.is_file() else {}
    caught = [n for n in result.burst_tests if bad_seen.get(n) == "failed"]
    check("on a page whose CARD_INTERVAL_MS is 1 ms, a burst test fails on an assert",
          bad.returncode != 0 and bool(caught), f"exit {bad.returncode}, outcomes {bad_seen}")
    if caught:
        print(f"  the 1 ms page fails: {', '.join(caught)}")

finish()
