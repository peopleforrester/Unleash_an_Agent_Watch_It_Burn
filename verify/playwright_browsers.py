# ABOUTME: Which browsers the pinned Playwright needs, where they go, and whether `playwright install` can put them
# ABOUTME: there. run-e2e-tools.sh checks it once before any test (#658); the Playwright tier tests install through it.
"""The browsers the pinned Playwright needs, read from `playwright install --dry-run chromium`.

`playwright install` takes a lock file, `__dirlock`, in the browsers directory before it looks at what is already
there, even when every browser is installed. Where that directory is not writable (a shared PLAYWRIGHT_BROWSERS_PATH
owned by another group), the lock fails with EACCES and Playwright retries it for about 8 minutes before it gives up.
On 2026-10-29 that cost each Playwright test 8 minutes and pushed run-e2e-tools.sh past 10 (#658, from #633).

So nothing here runs `playwright install` unless a browser is missing, and a missing browser in a directory this user
cannot write is reported at once, naming the directory and what is missing. A browser counts as installed when its
install location holds INSTALLATION_COMPLETE, the marker Playwright writes last and checks before downloading.

Run as a script, it is run-e2e-tools.sh's prerequisite check: it prints one line per problem and exits 1 when the
browsers are missing and cannot be installed. It does not install anything.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

PLAYWRIGHT = "playwright==1.64.1"
UV = ["uv", "run", "--no-project", "--with", PLAYWRIGHT]
BROWSERS = ["chromium"]
MARKER = "INSTALLATION_COMPLETE"
# The first run brings playwright in through uv, which is a download.
TIMEOUT = 300


def listing(dry_run: str) -> list[tuple[str, pathlib.Path]]:
    """(browser, install location) for each browser the dry run lists."""
    return [(name.strip(), pathlib.Path(loc.strip()))
            for name, loc in re.findall(r"^(\S[^\n]*)\n[ \t]+Install location:[ \t]+(\S[^\n]*)$", dry_run, re.M)]


def writable(path: pathlib.Path) -> bool:
    """Whether this user can create entries in path, or in the nearest directory above it that exists."""
    while not path.exists() and path != path.parent:
        path = path.parent
    return os.access(path, os.W_OK | os.X_OK)


def check() -> tuple[list[str], list[tuple[str, pathlib.Path]]]:
    """(problems, missing browsers). No problems means every browser is installed or can be."""
    try:
        r = subprocess.run([*UV, "playwright", "install", "--dry-run", *BROWSERS],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return [f"`playwright install --dry-run {' '.join(BROWSERS)}` ({PLAYWRIGHT}) did not finish in {TIMEOUT}s"], []
    if r.returncode != 0:
        out = " ".join((r.stdout + r.stderr).split())
        return [f"`playwright install --dry-run {' '.join(BROWSERS)}` ({PLAYWRIGHT}) exited {r.returncode}: {out}"], []
    listed = listing(r.stdout)
    if not listed:
        return [f"`playwright install --dry-run {' '.join(BROWSERS)}` ({PLAYWRIGHT}) listed no install location: "
                f"{' '.join(r.stdout.split())}"], []
    missing = [(name, loc) for name, loc in listed if not (loc / MARKER).is_file()]
    problems = []
    for root in sorted({loc.parent for _, loc in missing}):
        if writable(root):
            continue
        absent = "; ".join(f"{name} at {loc}" for name, loc in missing if loc.parent == root)
        problems.append(f"Playwright's browsers directory {root} is not writable by this user "
                        f"({_user()}), so `playwright install` cannot add what is missing there: {absent}")
    return problems, missing


def ensure() -> list[str]:
    """Installs the missing browsers, if any. Returns the problems; none means the browsers are ready."""
    problems, missing = check()
    if problems or not missing:
        return problems
    r = subprocess.run([*UV, "playwright", "install", *BROWSERS], capture_output=True, text=True)
    if r.returncode != 0:
        return [f"`playwright install {' '.join(BROWSERS)}` exited {r.returncode}:\n{r.stdout}{r.stderr}"]
    return []


def _user() -> str:
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError):
        return f"uid {os.getuid()}"


if __name__ == "__main__":
    found, _ = check()
    for p in found:
        print(p)
    sys.exit(1 if found else 0)
