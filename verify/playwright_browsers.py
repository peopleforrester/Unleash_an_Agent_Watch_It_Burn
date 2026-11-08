# ABOUTME: Which browsers the pinned Playwright needs, where they go, and installs a missing one from the host artifact
# ABOUTME: cache by the SHA-256 in playwright-browsers.lock (#1120), never by `playwright install` (#658).
"""The browsers the pinned Playwright needs, read from `playwright install --dry-run chromium`.

`playwright install` takes a lock file, `__dirlock`, in the browsers directory before it looks at what is already
there, even when every browser is installed. Where that directory is not writable (a shared PLAYWRIGHT_BROWSERS_PATH
owned by another group), the lock fails with EACCES and Playwright retries it for about 8 minutes before it gives up.
On 2026-10-29 that cost each Playwright test 8 minutes and pushed run-e2e-tools.sh past 10 (#658, from #633).

A browser counts as installed when its install location holds INSTALLATION_COMPLETE, the marker Playwright writes
last and checks before downloading. A missing browser in a directory this user cannot write is reported at once,
naming the directory and what is missing, with the directory's owner, group and mode and whether this user is in that
group: on 2026-10-29 the dispatch host's run users of one pool had been left out of the group that writes the shared
directory (#672).

Since #1120 nothing here runs `playwright install`. Every archive the dry run lists (the browser, its headless shell
and ffmpeg) is pinned in playwright-browsers.lock by its install directory, its download URL and the SHA-256 of the
zip. A missing browser's zip comes from the host artifact cache (artifact_cache.py, #1117), which re-checks the sum on
every hit and goes to the network only on a miss, so a host downloads each archive once whatever browsers directory
asks for it. The zip is unpacked into a temp directory beside the install location, INSTALLATION_COMPLETE is written
last, as Playwright does, and the directory is renamed into place, so no reader sees a half-unpacked browser. A
browser the dry run lists that the lock does not pin, or pins at another URL, is a problem named at once, installed or
not: it means the Playwright pin moved without the lock, which `python3 verify/playwright_browsers.py lock` rewrites.

Run as a script with no argument, it is run-e2e-tools.sh's prerequisite check: it prints one line per problem and
exits 1 when a browser is not pinned, or is missing and cannot be installed. It does not install anything.
`lock` downloads each archive the dry run lists, writes playwright-browsers.lock with their sums, and leaves each
archive in the host cache.
"""
from __future__ import annotations

import fcntl
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from typing import NamedTuple

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402

PLAYWRIGHT = "playwright==1.64.1"
UV = ["uv", "run", "--no-project", "--with", PLAYWRIGHT]
BROWSERS = ["chromium"]
MARKER = "INSTALLATION_COMPLETE"
LOCK = VERIFY / "playwright-browsers.lock"
# The first run brings playwright in through uv, which is a download.
TIMEOUT = 300
LOCK_HEADER = """\
# ABOUTME: The browser archives the pinned Playwright lists for `install chromium` on linux x86_64, each pinned by the
# ABOUTME: SHA-256 of its zip (#1120). playwright_browsers.ensure() unpacks a missing one from the host artifact cache.
#
# The first data line names the Playwright pin the archives belong to. Then one archive a line: the install directory
# Playwright reads under PLAYWRIGHT_BROWSERS_PATH, the SHA-256 of the zip, and the download URL the dry run names.
# Written by `python3 verify/playwright_browsers.py lock`, which downloads each zip and hashes it, since Playwright's
# CDN publishes no sum. A browser the dry run lists that is not here, or is here at another URL, fails the tier's
# prerequisite check by name; nothing falls back to `playwright install`.
"""


class Browser(NamedTuple):
    name: str
    location: pathlib.Path
    url: str


class Pin(NamedTuple):
    directory: str
    sha256: str
    url: str


class LockError(RuntimeError):
    """playwright-browsers.lock is missing, malformed or for another Playwright; the message names which."""


def entries(dry_run: str) -> list[Browser]:
    """Each browser the dry run lists: its name, install location and primary download URL ('' when none is given)."""
    found = []
    for block in re.split(r"\n\s*\n", dry_run):
        m = re.search(r"^(\S[^\n]*)\n[ \t]+Install location:[ \t]+(\S[^\n]*)$", block, re.M)
        if not m:
            continue
        url = re.search(r"^[ \t]+Download url:[ \t]+(\S+)[ \t]*$", block, re.M)
        found.append(Browser(m.group(1).strip(), pathlib.Path(m.group(2).strip()), url.group(1) if url else ""))
    return found


def listing(dry_run: str) -> list[tuple[str, pathlib.Path]]:
    """(browser, install location) for each browser the dry run lists."""
    return [(b.name, b.location) for b in entries(dry_run)]


def read_lock(path: pathlib.Path = LOCK) -> dict[str, Pin]:
    """The lock's pins by install directory; LockError when it is missing, malformed or pins another Playwright."""
    if not path.is_file():
        raise LockError(f"{path} is missing; `python3 verify/playwright_browsers.py lock` writes it")
    lines = [ln.split() for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines or lines[0] != ["playwright", PLAYWRIGHT.split("==", 1)[1]]:
        raise LockError(f"{path} pins archives for {' '.join(lines[0]) if lines else 'nothing'}, not {PLAYWRIGHT}; "
                        "`python3 verify/playwright_browsers.py lock` rewrites it")
    pins: dict[str, Pin] = {}
    for fields in lines[1:]:
        if len(fields) != 3 or not artifact_cache.SHA256.fullmatch(fields[1]) or fields[0] in pins:
            raise LockError(f"{path} has a malformed or repeated line {' '.join(fields)!r}: "
                            "want install directory, SHA-256, URL")
        pins[fields[0]] = Pin(*fields)
    if not pins:
        raise LockError(f"{path} pins no archive")
    return pins


def unpinned(listed: list[Browser], pins: dict[str, Pin]) -> list[str]:
    """One problem for each listed browser the lock does not pin at the URL the dry run names."""
    problems = []
    for b in listed:
        pin = pins.get(b.location.name)
        if pin is None:
            problems.append(f"{PLAYWRIGHT} lists {b.name} at {b.location}, and {LOCK.name} pins no "
                            f"{b.location.name}; `python3 verify/playwright_browsers.py lock` rewrites the lock")
        elif pin.url != b.url:
            problems.append(f"{PLAYWRIGHT} downloads {b.name} from {b.url or 'no URL'}, and {LOCK.name} pins "
                            f"{b.location.name} at {pin.url}; `python3 verify/playwright_browsers.py lock` rewrites it")
    return problems


def existing(path: pathlib.Path) -> pathlib.Path:
    """path, or the nearest directory above it that exists."""
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def writable(path: pathlib.Path) -> bool:
    """Whether this user can create entries in path, or in the nearest directory above it that exists."""
    return os.access(existing(path), os.W_OK | os.X_OK)


def ownership(path: pathlib.Path) -> str:
    """Who may write path: its owner, group and mode, and whether this user is in that group (#672).

    A shared browsers directory is written through its group, so a user left out of the group is what to fix.
    """
    st = existing(path).stat()
    try:
        import grp
        import pwd
        owner, group = pwd.getpwuid(st.st_uid).pw_name, grp.getgrgid(st.st_gid).gr_name
    except (ImportError, KeyError):
        owner, group = f"uid {st.st_uid}", f"gid {st.st_gid}"
    member = st.st_gid == os.getgid() or st.st_gid in os.getgroups()
    return (f"{existing(path)} is owner {owner}, group {group}, mode {st.st_mode & 0o7777:o}, "
            f"and {_user()} is {'' if member else 'not '}in group {group}")


def dry_run() -> tuple[str, list[Browser]]:
    """(problem, listed browsers): the problem is '' when the dry run listed at least one install location."""
    what = f"`playwright install --dry-run {' '.join(BROWSERS)}` ({PLAYWRIGHT})"
    try:
        r = subprocess.run([*UV, "playwright", "install", "--dry-run", *BROWSERS],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"{what} did not finish in {TIMEOUT}s", []
    if r.returncode != 0:
        return f"{what} exited {r.returncode}: {' '.join((r.stdout + r.stderr).split())}", []
    listed = entries(r.stdout)
    if not listed:
        return f"{what} listed no install location: {' '.join(r.stdout.split())}", []
    return "", listed


def check(lock: pathlib.Path = LOCK) -> tuple[list[str], list[Browser]]:
    """(problems, missing browsers). No problems means every browser is pinned, and installed or installable."""
    problem, listed = dry_run()
    if problem:
        return [problem], []
    try:
        problems = unpinned(listed, read_lock(lock))
    except LockError as e:
        problems = [str(e)]
    missing = [b for b in listed if not (b.location / MARKER).is_file()]
    for root in sorted({b.location.parent for b in missing}):
        if writable(root):
            continue
        absent = "; ".join(f"{b.name} at {b.location}" for b in missing if b.location.parent == root)
        problems.append(f"Playwright's browsers directory {root} is not writable by this user "
                        f"({_user()}), so a missing browser cannot be unpacked there: {absent} "
                        f"({ownership(root)})")
    return problems, missing


def safe_members(zf: zipfile.ZipFile, archive: pathlib.Path) -> list[zipfile.ZipInfo]:
    """The zip's members, each a relative path that stays inside the directory it is unpacked into."""
    for info in zf.infolist():
        parts = pathlib.PurePosixPath(info.filename).parts
        if not parts or info.filename.startswith("/") or ".." in parts:
            raise artifact_cache.ArtifactCacheError(f"{archive} holds {info.filename!r}, which would unpack outside "
                                                    "its install location")
    return zf.infolist()


def unzip(archive: pathlib.Path, dest: pathlib.Path) -> None:
    """Unpacks archive into dest with each member's mode, and its symlinks as symlinks, as Playwright's extract does."""
    umask = os.umask(0)
    os.umask(umask)
    with zipfile.ZipFile(archive) as zf:
        for info in safe_members(zf, archive):
            mode = info.external_attr >> 16
            target = dest / info.filename
            if stat.S_ISLNK(mode):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(zf.read(info).decode())
            elif info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                os.chmod(target, (mode & 0o777 or 0o755) & ~umask)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(target, (mode & 0o777 or 0o644) & ~umask)


def install(browser: Browser, pin: Pin, **cache_kw) -> None:
    """Puts the pinned archive, from the host cache, at the browser's install location; INSTALLATION_COMPLETE last."""
    archive = artifact_cache.get_retrying(pin.sha256, pin.url, **cache_kw)
    root, loc = browser.location.parent, browser.location
    root.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(root / ".wib-unpack.lock", os.O_RDWR | os.O_CREAT, 0o664)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Another run may have unpacked it while this one waited for the lock.
        if (loc / MARKER).is_file():
            return
        stage = pathlib.Path(tempfile.mkdtemp(prefix=f".{loc.name}.", suffix=".partial", dir=root))
        try:
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(stage, 0o777 & ~umask)
            unzip(archive, stage)
            (stage / MARKER).write_bytes(b"")
            # A location without the marker is an unpack that never finished; Playwright's own install replaces it too.
            if loc.is_symlink() or loc.is_file():
                loc.unlink()
            elif loc.exists():
                shutil.rmtree(loc)
            os.rename(stage, loc)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    finally:
        os.close(lock_fd)


def ensure(lock: pathlib.Path = LOCK, **cache_kw) -> list[str]:
    """Installs the missing browsers from the host cache, if any. Returns the problems; none means they are ready."""
    problems, missing = check(lock)
    if problems or not missing:
        return problems
    pins = read_lock(lock)
    for b in missing:
        try:
            install(b, pins[b.location.name], **cache_kw)
        except (artifact_cache.ArtifactCacheError, OSError, zipfile.BadZipFile) as e:
            problems.append(f"{b.name} could not be unpacked at {b.location} from {pins[b.location.name].url}: {e}")
    return problems


def write_lock(path: pathlib.Path = LOCK) -> int:
    """Downloads every archive the dry run lists, writes the lock with their sums, and leaves each in the host cache."""
    problem, listed = dry_run()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    lines = [f"playwright {PLAYWRIGHT.split('==', 1)[1]}"]
    scratch = artifact_cache.scratch_dir("playwright-lock-")
    try:
        for b in listed:
            if not b.url:
                print(f"the dry run names no download URL for {b.name}", file=sys.stderr)
                return 1
            part = scratch / b.location.name
            with open(part, "wb") as out:
                artifact_cache.url_fetch(b.url, out)
            sha = artifact_cache.sha256_of(part)

            def copy(_url: str, out, part=part) -> None:
                with open(part, "rb") as src:
                    shutil.copyfileobj(src, out)
            print(f"  {b.location.name} {sha} {artifact_cache.get(sha, b.url, fetch=copy)}")
            lines.append(f"{b.location.name} {sha} {b.url}")
    finally:
        shutil.rmtree(scratch)
    path.write_text(LOCK_HEADER + "".join(f"{ln}\n" for ln in lines))
    print(f"wrote {path}: {len(lines) - 1} archives for {PLAYWRIGHT}")
    return 0


def _user() -> str:
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError):
        return f"uid {os.getuid()}"


if __name__ == "__main__":
    if sys.argv[1:] == ["lock"]:
        sys.exit(write_lock())
    if sys.argv[1:]:
        print("usage: playwright_browsers.py [lock]", file=sys.stderr)
        sys.exit(2)
    found, _ = check()
    for p in found:
        print(p)
    sys.exit(1 if found else 0)
