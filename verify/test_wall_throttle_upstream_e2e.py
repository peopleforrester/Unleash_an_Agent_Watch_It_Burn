# ABOUTME: Reads prompts-agenticburn's templates/wall.html on that repo's main through `gh api` and runs #933's card-rate
# ABOUTME: checks on it; fails when main breaks the one-card-per-1.5-s rule or has moved past the pinned copy.
# SUITE: e2e (needs gh signed in to a login that can read the private peopleforrester/prompts-agenticburn)
"""Why (#933). test_wall_throttle_e2e.py, in the gate's tools tier, runs a pinned copy of the wall's page, because
the wall repo is private and the gate has no GitHub login. This is its live half, run by hand with run-e2e.sh: the
wall the room sees is built from that repo's main, so this runs the same checks on main as it is now, and turns red
when main has a commit past the copy, naming the commit to refresh the copy, its SHA-256 and WALL_COMMIT to. No gh,
no login or an API error is a failure with the reason printed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_wall_throttle_e2e as pinned  # noqa: E402
import wall_throttle  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def gh(path: str) -> dict:
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"`gh api {path}` exited {out.returncode}: {(out.stderr or out.stdout).strip()[:400]}")
    return json.loads(out.stdout)


def main() -> int:
    if shutil.which("gh") is None:
        print("FAIL: gh is not on PATH; this test reads the private wall repo through `gh api`")
        return 1
    try:
        head = gh(f"repos/{pinned.WALL_REPO}/commits/main")["sha"]
        body = gh(f"repos/{pinned.WALL_REPO}/contents/{pinned.WALL_PATH}?ref={head}")
    except (RuntimeError, KeyError, json.JSONDecodeError) as e:
        print(f"FAIL: could not read {pinned.WALL_REPO}'s {pinned.WALL_PATH} on main: {e}")
        return 1
    raw = base64.b64decode(body.get("content", ""))
    digest = hashlib.sha256(raw).hexdigest()
    print(f"== {pinned.WALL_REPO}'s {pinned.WALL_PATH} on main, at {head[:8]} ==")
    check("main's page is the pinned copy", digest == pinned.WALL_SHA256,
          f"main {head} has sha256 {digest}; copy it to {pinned.WALL.relative_to(pinned.REPO)} and set WALL_COMMIT "
          f"and WALL_SHA256 in verify/test_wall_throttle_e2e.py to them")
    with tempfile.TemporaryDirectory() as tmp:
        wall = pathlib.Path(tmp) / "wall.html"
        wall.write_bytes(raw)
        try:
            for name, ok, detail in wall_throttle.criterion_checks(wall):
                check(name, ok, detail)
        except RuntimeError as e:
            print(f"FAIL: {e}")
            return 1
    if failures:
        print(f"\nFAIL: {len(failures)} check(s) failed")
        return 1
    print("\nPASS: the wall repo's main adds at most one card per 1.5 s window, and the pinned copy is main's page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
