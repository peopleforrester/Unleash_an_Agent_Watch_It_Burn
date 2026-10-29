# ABOUTME: verify/playwright_browsers.py runs `playwright install` only when a browser is missing, and reports a missing
# ABOUTME: browser in a directory it cannot write at once, naming both, instead of an 8-minute lock retry (#658).
"""Offline: `uv` is stubbed to answer the dry run with a fixture listing and to log every call.

`playwright install` takes `__dirlock` in the browsers directory before it looks at anything, so on a host whose
shared PLAYWRIGHT_BROWSERS_PATH is not writable it spent about 8 minutes per test failing with EACCES (#658). These
hold that the install is never run when every install location holds INSTALLATION_COMPLETE, that a missing browser
in a directory this user cannot write is a problem named at once with no install run, and that the Playwright tier
tests go through the module rather than running `playwright install` themselves.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import playwright_browsers as pb  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


LISTED = (("Chrome for Testing 1 (playwright chromium v9)", "chromium-9"), ("FFmpeg (playwright ffmpeg v9)", "ffmpeg-9"))


def stub_uv(bindir: pathlib.Path, log: pathlib.Path, browsers: pathlib.Path, dry_rc: int = 0, install_rc: int = 0,
            listing: str | None = None) -> None:
    """A uv that logs its arguments, answers the dry run with LISTED under browsers, and exits install_rc on install."""
    if listing is None:
        listing = "".join(f"{name}\n  Install location:    {browsers / d}\n  Download url:        https://x.invalid/{d}\n\n"
                          for name, d in LISTED)
    bindir.mkdir(parents=True, exist_ok=True)
    uv = bindir / "uv"
    uv.write_text(f"""#!/bin/sh
echo "$*" >>'{log}'
case "$*" in
  *--dry-run*) cat <<'EOF'
{listing}EOF
     exit {dry_rc} ;;
  *"playwright install"*) exit {install_rc} ;;
esac
""")
    uv.chmod(0o755)


def install(browsers: pathlib.Path, *dirs: str) -> None:
    for d in dirs:
        (browsers / d).mkdir(parents=True, exist_ok=True)
        (browsers / d / pb.MARKER).touch()


def calls(log: pathlib.Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def installs(log: pathlib.Path) -> list[str]:
    return [c for c in calls(log) if "playwright install" in c and "--dry-run" not in c]


PATH = os.environ["PATH"]


def scenario(t: str, browsers_mode: int, installed: tuple[str, ...], **kw) -> tuple[pathlib.Path, pathlib.Path]:
    tmp = pathlib.Path(t)
    browsers, log = tmp / "ms-playwright", tmp / "uv.log"
    browsers.mkdir()
    install(browsers, *installed)
    stub_uv(tmp / "bin", log, browsers, **kw)
    browsers.chmod(browsers_mode)
    os.environ["PATH"] = f"{tmp / 'bin'}:{PATH}"
    return browsers, log


print("== the dry run is read for each browser and its install location ==")
sample = """Chrome for Testing 156.0.8078.4 (playwright chromium v1248)
  Install location:    /var/lib/hecaton/ms-playwright/chromium-1248
  Download url:        https://cdn.playwright.dev/builds/cft/156.0.8078.4/linux64/chrome-linux64.zip

FFmpeg (playwright ffmpeg v1013)
  Install location:    /var/lib/hecaton/ms-playwright/ffmpeg-1013
  Download url:        https://cdn.playwright.dev/dbazure/download/playwright/builds/ffmpeg/1013/ffmpeg-linux.zip
  Download fallback 1: https://playwright.download.prss.microsoft.com/dbazure/download/playwright/builds/ffmpeg/1013/ffmpeg-linux.zip
"""
check("1.64.1's listing reads as two browsers with their install locations",
      pb.listing(sample) == [("Chrome for Testing 156.0.8078.4 (playwright chromium v1248)",
                              pathlib.Path("/var/lib/hecaton/ms-playwright/chromium-1248")),
                             ("FFmpeg (playwright ffmpeg v1013)", pathlib.Path("/var/lib/hecaton/ms-playwright/ffmpeg-1013"))],
      str(pb.listing(sample)))

print("== every browser installed: no install is run, writable or not ==")
for mode, how in ((0o555, "not writable"), (0o755, "writable")):
    with tempfile.TemporaryDirectory() as t:
        browsers, log = scenario(t, mode, ("chromium-9", "ffmpeg-9"))
        try:
            problems = pb.ensure()
        finally:
            browsers.chmod(0o755)
        check(f"a {how} directory holding every browser is ready ({problems})", problems == [])
        check(f"a {how} directory holding every browser runs no `playwright install`", installs(log) == [], str(calls(log)))

print("== a browser missing from a directory this user cannot write is named at once ==")
with tempfile.TemporaryDirectory() as t:
    browsers, log = scenario(t, 0o555, ("chromium-9",))
    try:
        problems = pb.ensure()
        script = pb.check()[0]
    finally:
        browsers.chmod(0o755)
    check("it is one problem", len(problems) == 1, str(problems))
    check("it names the directory, says it is not writable, and names the missing browser at its location",
          bool(problems) and f"browsers directory {browsers} is not writable" in problems[0]
          and f"FFmpeg (playwright ffmpeg v9) at {browsers / 'ffmpeg-9'}" in problems[0]
          and "chromium" not in problems[0], str(problems))
    check("no `playwright install` is run, so there is no lock to wait on", installs(log) == [], str(calls(log)))
    check("check() reports the same problem", script == problems, str(script))
    group = pb.ownership(browsers).rsplit(" ", 1)[-1]
    check("it names the directory's owner, group and mode, and whether this user is in that group (#672)",
          bool(problems) and f"({browsers} is owner " in problems[0] and ", mode 555, and " in problems[0]
          and f"{pb._user()} is in group {group})" in problems[0], str(problems))

print("== the ownership says when this user is not in the directory's group (#672) ==")
with tempfile.TemporaryDirectory() as t:
    d = pathlib.Path(t)
    group = pb.ownership(d).rsplit(" ", 1)[-1]
    check("this user's own directory: it is in the directory's group",
          pb.ownership(d).endswith(f"and {pb._user()} is in group {group}"), pb.ownership(d))
    check("a directory that does not exist yet is described by the nearest one above it",
          pb.ownership(d / "a" / "b") == pb.ownership(d), pb.ownership(d / "a" / "b"))
    real = (os.getgid, os.getgroups)
    # A user whose groups hold nothing of the directory's, as a run user outside hecaton-tools.
    os.getgid, os.getgroups = (lambda: -1), (lambda: [])
    try:
        outside = pb.ownership(d)
    finally:
        os.getgid, os.getgroups = real
    check("a user outside the directory's group is told so, with the group named",
          outside.endswith(f"and {pb._user()} is not in group {group}"), outside)

print("== a browser missing from a writable directory is installed ==")
with tempfile.TemporaryDirectory() as t:
    browsers, log = scenario(t, 0o755, ("chromium-9",))
    problems = pb.ensure()
    check(f"it is ready ({problems})", problems == [])
    check("`playwright install chromium` ran once, through the pinned playwright",
          installs(log) == [f"run --no-project --with {pb.PLAYWRIGHT} playwright install chromium"], str(calls(log)))
with tempfile.TemporaryDirectory() as t:
    browsers, log = scenario(t, 0o755, (), install_rc=1)
    problems = pb.ensure()
    check("an install that fails is a problem naming its exit code",
          len(problems) == 1 and "`playwright install chromium` exited 1" in problems[0], str(problems))
with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    browsers, log = scenario(t, 0o755, ())
    stub_uv(tmp / "bin", log, tmp / "not-yet" / "ms-playwright")
    check(f"a browsers directory that does not exist yet, under a writable one, is installable ({pb.check()[0]})",
          pb.check()[0] == [])

print("== a dry run that fails or lists nothing is a problem, not a pass ==")
with tempfile.TemporaryDirectory() as t:
    browsers, log = scenario(t, 0o755, ("chromium-9", "ffmpeg-9"), dry_rc=3)
    problems = pb.ensure()
    check("a dry run that exits non-zero is named with its exit code",
          len(problems) == 1 and "--dry-run chromium` (playwright==" in problems[0] and "exited 3" in problems[0],
          str(problems))
    check("and nothing is installed", installs(log) == [], str(calls(log)))
with tempfile.TemporaryDirectory() as t:
    browsers, log = scenario(t, 0o755, (), listing="nothing to see\n")
    problems = pb.ensure()
    check("a dry run that lists no install location is a problem",
          len(problems) == 1 and "listed no install location" in problems[0], str(problems))
os.environ["PATH"] = PATH

print("== the Playwright tier tests install through the module ==")
for t in sorted(VERIFY.glob("test_*.py")):
    text = t.read_text()
    if t.name == pathlib.Path(__file__).name or not re.search(r"^# E2E TIER: tools", text, re.M):
        continue
    if "playwright" not in text.lower():
        continue
    check(f"{t.name} gets its browsers from playwright_browsers.ensure()",
          "from playwright_browsers import" in text and "ensure()" in text)
    check(f"{t.name} runs no `playwright install` of its own",
          not re.search(r'"install",\s*"chromium"', text) and "playwright install chromium\"" not in text)
check("test_mobile_titles_e2e.py is one of them",
      "from playwright_browsers import" in (VERIFY / "test_mobile_titles_e2e.py").read_text())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll Playwright browser checks passed.")
