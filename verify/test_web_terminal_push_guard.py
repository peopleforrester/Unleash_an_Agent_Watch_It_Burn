# ABOUTME: Runs build-web-terminal.yml's push step against a stub crane and docker (#815): a tag that exists is never
# ABOUTME: pushed over, a tag moved off its images.lock pin is put back on it, and only a missing tag is pushed.
"""Why (#815). The workflow rebuilt the web terminal on every push that touched it and pushed the build under the
same web-terminal-ttyd-<v> tag. The build is not reproducible, so each run moved the tag to a new, unsigned digest:
after #714's edit to the workflow, ghcr.io served d6acd503 under the tag gitops/ai-layer/resources.yaml pins at
68004fb5, and test_image_version_tags.py went red. The push step now reads the tag before it pushes:

  tag missing                     push the build (the only case that pushes)
  tag serves its images.lock pin  push nothing
  tag serves another digest       push nothing; crane re-points the tag at the pinned digest, then reads it back
  tag exists, images.lock pins
    nothing for it                fail: nothing says which digest is right
  registry gives another error    fail: an outage or a lost login is not "no such tag"

This runs the step's own script, taken out of the workflow file, with crane and docker replaced by stubs that log
each call, so what is held is what GitHub runs. test_web_terminal_push_guard_registry.py runs the same script with
the real pinned crane against a registry on loopback. The crane the workflow installs is held to e2e-tools.lock's.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((REPO / ".github/workflows/build-web-terminal.yml").read_text(encoding="utf-8"))
LOCK = (REPO / "images.lock").read_text(encoding="utf-8")
TOOLS = (REPO / "verify/e2e-tools.lock").read_text(encoding="utf-8")
TAG = "ghcr.io/peopleforrester/watch-it-burn:web-terminal-ttyd-1.7.7"
UNPINNED = "ghcr.io/peopleforrester/watch-it-burn:web-terminal-ttyd-9.9.9"
OTHER = "sha256:" + "d" * 64
BUILT = "sha256:" + "b" * 64
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


steps = {s.get("name", ""): s for s in WORKFLOW["jobs"]["build"]["steps"]}
push = steps.get("Push, never over a tag that exists", {})
install = steps.get("Install crane", {})
SCRIPT = push.get("run", "")

print("== the workflow's push step ==")
check("build-web-terminal.yml has a 'Push, never over a tag that exists' step", bool(SCRIPT))
check("no other step pushes", [n for n, s in steps.items() if "docker push" in s.get("run", "")]
      == ["Push, never over a tag that exists"])
check("the push step reads the tag from the version step through env, not an expression in the script",
      push.get("env", {}).get("TAG") == "${{ steps.version.outputs.tag }}" and "${{" not in SCRIPT)
check("crane is installed before the push step", list(steps).index("Install crane") < list(steps).index(
    "Push, never over a tag that exists") if install and push else False)

print("== the crane the workflow installs is e2e-tools.lock's ==")
row = re.search(r"^crane\s+(\S+)\s+([0-9a-f]{64})\s+(\S+)\s+crane$", TOOLS, re.M)
check("e2e-tools.lock has a crane row", row is not None)
if row and install:
    env = install.get("env", {})
    check(f"the workflow downloads crane {row.group(1)} from the lock's URL", env.get("CRANE_URL") == row.group(3),
          str(env.get("CRANE_URL")))
    check("and checks the lock's SHA-256 before extracting it", env.get("CRANE_SHA256") == row.group(2)
          and "sha256sum -c" in install.get("run", ""))

pin_m = re.search(rf"^{re.escape(TAG)}@(sha256:[0-9a-f]{{64}}) (sha256:[0-9a-f]{{64}}) ", LOCK, re.M)
check(f"images.lock pins {TAG}", pin_m is not None)
PIN = pin_m.group(2) if pin_m else ""

CRANE = """#!/usr/bin/env bash
echo "crane $*" >>"${CALLS}"
case "$1" in
  digest)
    if [ -n "${CRANE_ERROR:-}" ]; then echo "${CRANE_ERROR}" >&2; exit 1; fi
    if [ -s "${STATE}" ]; then cat "${STATE}"; exit 0; fi
    echo "Error: GET https://ghcr.io/v2/x/manifests/y: MANIFEST_UNKNOWN: manifest unknown" >&2; exit 1 ;;
  tag) echo "${2##*@}" >"${STATE}" ;;
  *) echo "unexpected crane call: $*" >&2; exit 3 ;;
esac
"""
DOCKER = """#!/usr/bin/env bash
echo "docker $*" >>"${CALLS}"
case "$1" in
  tag) ;;
  push) echo "${BUILT}" >"${STATE}" ;;
  *) echo "unexpected docker call: $*" >&2; exit 3 ;;
esac
"""


def run(tag: str, served: str | None, error: str = "") -> tuple[int, str, list[str], str]:
    """Run the step's script for tag, with ghcr.io serving served under it (None: no such tag). Returns the exit
    code, the output, every crane and docker call, and the digest the tag serves afterwards."""
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        for name, body in (("crane", CRANE), ("docker", DOCKER)):
            (tmp / name).write_text(body)
            (tmp / name).chmod(0o755)
        state, calls = tmp / "state", tmp / "calls"
        state.write_text(served or "")
        calls.write_text("")
        env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "TAG": tag, "STATE": str(state),
               "CALLS": str(calls), "BUILT": BUILT, "CRANE_ERROR": error}
        p = subprocess.run(["bash", "-e", "-c", SCRIPT], cwd=REPO, env=env, capture_output=True, text=True,
                           timeout=60)
        return p.returncode, p.stdout + p.stderr, calls.read_text().splitlines(), state.read_text().strip()


if SCRIPT and PIN:
    print("== no such tag: the build is pushed ==")
    rc, out, calls, after = run(TAG, None)
    check("exit 0", rc == 0, out)
    check("docker pushes the tag", f"docker push {TAG}" in calls, str(calls))
    check("and the job names the digest it pushed, to pin and sign", BUILT in out and "sign" in out, out)

    print("== the tag serves its pin: nothing is pushed ==")
    rc, out, calls, after = run(TAG, PIN)
    check("exit 0", rc == 0, out)
    check("no docker push and no crane tag", not [c for c in calls if c.startswith(("docker push", "crane tag"))],
          str(calls))
    check("the tag still serves the pin", after == PIN, after)
    check("the job warns that this build was not pushed", "::warning::" in out and "not pushed" in out, out)

    print("== the tag moved off its pin (#815): it is put back, and the build is not pushed ==")
    rc, out, calls, after = run(TAG, OTHER)
    check("exit 0", rc == 0, out)
    check("no docker push", not [c for c in calls if c.startswith("docker push")], str(calls))
    check("crane re-points the tag at the pinned digest",
          f"crane tag {TAG.rsplit(':', 1)[0]}@{PIN} {TAG.rsplit(':', 1)[1]}" in calls, str(calls))
    check("and reads the tag back", calls[-1:] == [f"crane digest {TAG}"], str(calls))
    check("the tag serves the pin again", after == PIN, after)

    print("== the tag exists and images.lock pins nothing for it: fail, push nothing ==")
    rc, out, calls, after = run(UNPINNED, OTHER)
    check("exit non-zero", rc != 0, out)
    check("no docker push and no crane tag", not [c for c in calls if c.startswith(("docker push", "crane tag"))],
          str(calls))
    check("the tag is left as it was", after == OTHER, after)
    check("the error says it refused to overwrite", "::error::" in out and "refusing to overwrite" in out, out)

    print("== the registry gives an error that is not 'no such tag': fail, push nothing ==")
    rc, out, calls, after = run(TAG, None, error="Error: GET https://ghcr.io/token: UNAUTHORIZED: authentication required")
    check("exit non-zero", rc != 0, out)
    check("no docker push", not [c for c in calls if c.startswith("docker push")], str(calls))
    check("the error carries the registry's answer", "::error::" in out and "UNAUTHORIZED" in out, out)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    raise SystemExit(1)
print("build-web-terminal.yml pushes only a tag that does not exist, and puts a moved pinned tag back on its pin.")
