# ABOUTME: Fetches peopleforrester/prompts-agenticburn at a branch tip through gh's token and runs that repo's own
# ABOUTME: test command, `uv run ruff check . && uv run pytest`, in a clean environment (#937, from #927).
"""prompts-agenticburn's own suite, run from here.

Why (#937). #927's fifth criterion is "`uv run ruff check . && uv run pytest` passes in prompts-agenticburn", the
prompt wall's repo, where #927's throttle landed as prompts-agenticburn#18 (6601313a). No test here ran that command,
so nothing in this repo failed when it stopped holding. verify/test_prompts_wall_suite_e2e.py now runs it on the tip
of that repo's main and staging, and verify/test_prompts_wall_suite.py runs this module on stubs offline.

How the code is read. prompts-agenticburn is private, so there is no anonymous clone. The tarball comes from
`gh api repos/<repo>/tarball/<sha>`, which carries gh's token. On the hecaton host gh is a wrapper that runs gh as
michael: dispatched runs get `gh api` GETs, and the promotion gate's read-only form refuses `gh api` (decisions.md,
#863). So the live test is in the live suite (`bash verify/run-e2e.sh`), not the tools tier the gate runs, the same
call verify/test_images_saved.py makes for the image archive.

Why a clean environment. The wall's app reads FEED_URL, ROSTER_URL, MAX_ENTRIES and other settings from its
environment, and run-e2e.sh's environment carries CONTEXT, KUBECONFIG and AWS settings that are none of its business.
The suite runs with PATH, HOME, the locale, TMPDIR and uv's own UV_* settings only, so its result is the repo's, not
the caller's ("Tests own their inputs").
"""
from __future__ import annotations

import dataclasses
import io
import os
import pathlib
import re
import shutil
import subprocess
import tarfile

WALL_REPO = "peopleforrester/prompts-agenticburn"
# main is what the wall serves from; staging is where that repo's runs land first.
WALL_REFS = ("main", "staging")
# The command #927's criterion names, as the steps `&&` runs in order: a failed step stops the rest.
STEPS = (("uv", "run", "ruff", "check", "."), ("uv", "run", "pytest"))
COMMAND = " && ".join(" ".join(step) for step in STEPS)
SHA = re.compile(r"^[0-9a-f]{40}$")
# What the suite inherits from the caller; anything else (CONTEXT, KUBECONFIG, AWS_*, FEED_URL...) is dropped.
KEEP_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "XDG_CACHE_HOME")
STEP_TIMEOUT = 900


class WallSuiteError(Exception):
    """A read or step that could not happen, with what it would have needed."""


def _last_lines(text: str, n: int = 3) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:])


def _gh(*args: str, timeout: int = 120) -> bytes:
    gh = shutil.which("gh")
    if not gh:
        raise WallSuiteError(f"no gh on PATH: {WALL_REPO} is private and is read with gh's token")
    try:
        p = subprocess.run([gh, *args], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise WallSuiteError(f"`gh {' '.join(args)}` did not answer within {timeout}s") from e
    if p.returncode != 0:
        said = _last_lines(p.stderr.decode(errors="replace") or p.stdout.decode(errors="replace"))
        raise WallSuiteError(f"`gh {' '.join(args)}` exit {p.returncode}: {said or 'no output'}")
    return p.stdout


def resolve(ref: str) -> str:
    """The commit sha at the tip of `ref` in the wall's repo."""
    sha = _gh("api", f"repos/{WALL_REPO}/commits/{ref}", "--jq", ".sha").decode(errors="replace").strip()
    if not SHA.match(sha):
        raise WallSuiteError(f"gh answered {ref!r} of {WALL_REPO} with {sha[:80]!r}, not a commit sha")
    return sha


def unpack(tarball: bytes, dest: pathlib.Path) -> pathlib.Path:
    """The source tree in `tarball`, unpacked under `dest`. GitHub's tarball holds one top directory."""
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
            tops = {m.name.split("/", 1)[0] for m in tf.getmembers()}
            if len(tops) != 1:
                raise WallSuiteError(f"the tarball has {len(tops)} top directories, not GitHub's one: {sorted(tops)}")
            # The data filter refuses absolute paths, links out of dest, devices and setuid bits.
            tf.extractall(dest, filter="data")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise WallSuiteError(f"the tarball does not unpack: {e}") from e
    src = dest / tops.pop()
    if not (src / "pyproject.toml").is_file():
        raise WallSuiteError(f"the tarball has no pyproject.toml at its top, so it is not {WALL_REPO}")
    return src


def fetch(sha: str, dest: pathlib.Path) -> pathlib.Path:
    """The wall's repo at `sha`, unpacked under `dest` (a new, empty directory)."""
    return unpack(_gh("api", f"repos/{WALL_REPO}/tarball/{sha}", timeout=300), dest)


@dataclasses.dataclass
class Step:
    command: str
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def suite_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in KEEP_ENV or k.startswith("UV_")}


def run_suite(src: pathlib.Path) -> list[Step]:
    """Each step of COMMAND run in `src`, in order, stopping after the first that fails, as `&&` does."""
    uv = shutil.which("uv")
    if not uv:
        raise WallSuiteError(f"no uv on PATH: {WALL_REPO}'s test command is `{COMMAND}`")
    ran: list[Step] = []
    for step in STEPS:
        try:
            p = subprocess.run([uv, *step[1:]], cwd=src, env=suite_env(), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, timeout=STEP_TIMEOUT)
            ran.append(Step(" ".join(step), p.returncode, p.stdout))
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            ran.append(Step(" ".join(step), 124, out + f"\n(timed out after {STEP_TIMEOUT}s)"))
        if not ran[-1].ok:
            break
    return ran


def passed(steps: list[Step]) -> bool:
    """COMMAND passed: every one of its steps ran, and each exited 0."""
    return len(steps) == len(STEPS) and all(s.ok for s in steps)
