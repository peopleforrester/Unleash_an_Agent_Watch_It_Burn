# ABOUTME: Runs a helm command that fetches a chart from a remote repo, and runs it once more when helm says the repo
# ABOUTME: cannot be reached, so one dropped fetch of a chart index does not turn a 30-minute tools tier red (#989).
"""Why. In run 17888 (#938) test_enforce_floor.py failed one check after 33 minutes of the tools tier:
`helm template --repo https://charts.external-secrets.io` said the repo "is not a valid chart repository or cannot be
reached" on its index.yaml, and a moment later the same URL answered 200 and the test passed on its own.

What is retried. Only a helm error that says the repo cannot be reached, which is how helm reports a failed fetch of
a repo's index.yaml. A bad chart version, a bad values file or a template error fails on the first attempt, because
a second attempt cannot change it. What is not retried. A second unreachable answer: both errors are returned, so a
lasting outage still fails the check and names what helm said each time."""
from __future__ import annotations

import subprocess
import time

UNREACHABLE = "cannot be reached"
ATTEMPTS = 2
PAUSE_SECONDS = 5.0


def last_line(stderr: str) -> str:
    """Helm's own message is the last stderr line; the lines above it are warnings."""
    lines = stderr.strip().splitlines()
    return lines[-1][:200] if lines else "helm failed with no message"


def unreachable(stderr: str) -> bool:
    return UNREACHABLE in stderr


def run_helm(cmd: list[str], pause: float = PAUSE_SECONDS) -> tuple[subprocess.CompletedProcess, str | None]:
    """Run cmd, and once more after `pause` seconds when helm says the repo cannot be reached.

    Returns the last attempt's CompletedProcess and None on success, or it and an error naming each attempt's
    message on failure."""
    errors = []
    for attempt in range(1, ATTEMPTS + 1):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            if errors:
                print(f"  note: {cmd[0]} {cmd[1]} answered on attempt {attempt} after: {errors[0]}")
            return r, None
        errors.append(last_line(r.stderr))
        if not unreachable(r.stderr) or attempt == ATTEMPTS:
            break
        time.sleep(pause)
    if len(errors) == 1:
        return r, errors[0]
    return r, "; ".join(f"attempt {i}: {e}" for i, e in enumerate(errors, 1))
