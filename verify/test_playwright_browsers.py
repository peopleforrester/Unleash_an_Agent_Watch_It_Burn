# ABOUTME: verify/playwright_browsers.py unpacks a missing browser from the host artifact cache by its pinned SHA-256
# ABOUTME: (#1120), never runs `playwright install`, and names a browser it cannot write or the lock does not pin (#658).
"""Offline: `uv` is stubbed to answer the dry run with a fixture listing and to log every call, and a
ThreadingHTTPServer on 127.0.0.1 serves the fixture zips and counts each request.

`playwright install` takes `__dirlock` in the browsers directory before it looks at anything, so on a host whose
shared PLAYWRIGHT_BROWSERS_PATH is not writable it spent about 8 minutes per test failing with EACCES (#658). Since
#1120 the module never runs it: each archive is pinned in a lock and comes from the host artifact cache. These hold
that nothing is fetched or unpacked when every install location holds INSTALLATION_COMPLETE; that a missing browser in
a directory this user cannot write is named at once with no fetch; that a cache miss fetches each zip once, logs it
and unpacks it with its modes and symlinks; that a hit in a fresh browsers directory makes no request; that a cached
zip that no longer matches, or a download that does not, fails by name and leaves no browser; that a browser the lock
does not pin, or pins at another URL, fails; and that the Playwright tier tests go through the module.
"""
from __future__ import annotations

import hashlib
import http.server
import io
import os
import pathlib
import re
import shutil
import stat
import sys
import tempfile
import threading
import zipfile

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import artifact_cache  # noqa: E402
import playwright_browsers as pb  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fixture_zip(top: str) -> bytes:
    """A zip as Playwright's are laid out: a top directory, an executable, a plain file and a symlink, at fixed times
    so its sum is the same on every run."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        def add(name: str, data: bytes, mode: int) -> None:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = mode << 16
            zf.writestr(info, data)
        add(f"{top}/", b"", stat.S_IFDIR | 0o755)
        add(f"{top}/bin", f"#!/bin/sh\necho {top}\n".encode(), stat.S_IFREG | 0o755)
        add(f"{top}/ABOUT", b"about\n", stat.S_IFREG | 0o644)
        add(f"{top}/link", b"bin", stat.S_IFLNK | 0o777)
    return buf.getvalue()


ZIPS = {"chromium-9": fixture_zip("chrome-linux64"), "ffmpeg-9": fixture_zip("ffmpeg")}
NAMES = {"chromium-9": "Chrome for Testing 1 (playwright chromium v9)", "ffmpeg-9": "FFmpeg (playwright ffmpeg v9)"}
VERSION = pb.PLAYWRIGHT.split("==", 1)[1]


class Server:
    """Serves self.files by path and counts requests per path."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.hits: dict[str, int] = {}
        self.lock = threading.Lock()
        srv = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                with srv.lock:
                    srv.hits[self.path] = srv.hits.get(self.path, 0) + 1
                body = srv.files.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def requests(self) -> int:
        with self.lock:
            return sum(self.hits.values())

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


SERVER = Server()
for d, body in ZIPS.items():
    SERVER.files[f"/{d}.zip"] = body
URLS = {d: SERVER.url(f"/{d}.zip") for d in ZIPS}


def write_lock(path: pathlib.Path, version: str = VERSION, sums: dict[str, str] | None = None,
               urls: dict[str, str] | None = None, dirs: tuple[str, ...] = tuple(ZIPS)) -> pathlib.Path:
    sums = {d: sha(ZIPS[d]) for d in ZIPS} | (sums or {})
    urls = URLS | (urls or {})
    path.write_text("# a test lock\nplaywright " + version + "\n" + "".join(f"{d} {sums[d]} {urls[d]}\n" for d in dirs))
    return path


def stub_uv(bindir: pathlib.Path, log: pathlib.Path, browsers: pathlib.Path, dry_rc: int = 0,
            listing: str | None = None, urls: dict[str, str] | None = None) -> None:
    """A uv that logs its arguments and answers the dry run with the fixture browsers under browsers."""
    urls = URLS | (urls or {})
    if listing is None:
        listing = "".join(f"{NAMES[d]}\n  Install location:    {browsers / d}\n  Download url:        {urls[d]}\n"
                          f"  Download fallback 1: https://fallback.invalid/{d}.zip\n\n" for d in ZIPS)
    bindir.mkdir(parents=True, exist_ok=True)
    uv = bindir / "uv"
    uv.write_text(f"""#!/bin/sh
echo "$*" >>'{log}'
case "$*" in
  *--dry-run*) cat <<'EOF'
{listing}EOF
     exit {dry_rc} ;;
esac
exit 97
""")
    uv.chmod(0o755)


def install(browsers: pathlib.Path, *dirs: str) -> None:
    for d in dirs:
        (browsers / d).mkdir(parents=True, exist_ok=True)
        (browsers / d / pb.MARKER).touch()


def calls(log: pathlib.Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def installs(log: pathlib.Path) -> list[str]:
    return [c for c in calls(log) if "--dry-run" not in c]


def fetches(log: pathlib.Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


PATH = os.environ["PATH"]


class Case:
    """A browsers directory, a stubbed uv, a lock, and a cache root outside every worktree with its own fetch log."""

    def __init__(self, t: str, mode: int = 0o755, installed: tuple[str, ...] = (), cache: pathlib.Path | None = None,
                 **kw):
        tmp = pathlib.Path(t)
        self.browsers, self.uvlog = tmp / "ms-playwright", tmp / "uv.log"
        self.browsers.mkdir()
        install(self.browsers, *installed)
        stub_uv(tmp / "bin", self.uvlog, self.browsers, **{k: v for k, v in kw.items() if k != "lock_kw"})
        self.lock = write_lock(tmp / "playwright-browsers.lock", **kw.get("lock_kw", {}))
        self.cache = cache or artifact_cache.scratch_dir("pwb-cache-")
        self.fetchlog = self.cache / "fetch.log"
        self.browsers.chmod(mode)
        os.environ["PATH"] = f"{tmp / 'bin'}:{PATH}"

    def ensure(self) -> list[str]:
        before = SERVER.requests()
        try:
            return pb.ensure(self.lock, root=self.cache, env={}, backoff=())
        finally:
            self.requests = SERVER.requests() - before
            self.browsers.chmod(0o755)


scratch_caches: list[pathlib.Path] = []

print("== the dry run is read for each browser, its install location and its download URL ==")
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
check("each browser's primary download URL is read, not a fallback",
      [b.url for b in pb.entries(sample)] == [
          "https://cdn.playwright.dev/builds/cft/156.0.8078.4/linux64/chrome-linux64.zip",
          "https://cdn.playwright.dev/dbazure/download/playwright/builds/ffmpeg/1013/ffmpeg-linux.zip"],
      str(pb.entries(sample)))

print("== the checked-in lock ==")
try:
    real, why = pb.read_lock(), ""
except pb.LockError as e:
    real, why = {}, str(e)
check(f"playwright-browsers.lock reads, and is for {pb.PLAYWRIGHT}, the pin uv runs", not why, why)
check("it pins the three archives `install chromium` lists on linux x86_64: the browser, its headless shell, ffmpeg",
      sorted(real) == ["chromium-1248", "chromium_headless_shell-1248", "ffmpeg-1013"], str(sorted(real)))
check("each pin is Playwright's CDN zip for that directory",
      all(p.url.startswith("https://cdn.playwright.dev/") and p.url.endswith(".zip") for p in real.values()),
      str(real))
check("the lock's header is the one `lock` writes", pb.LOCK.read_text().startswith(pb.LOCK_HEADER))

print("== every browser installed: nothing fetched or unpacked, writable or not ==")
for mode, how in ((0o555, "not writable"), (0o755, "writable")):
    with tempfile.TemporaryDirectory() as t:
        c = Case(t, mode, tuple(ZIPS))
        scratch_caches.append(c.cache)
        problems = c.ensure()
        check(f"a {how} directory holding every browser is ready ({problems})", problems == [])
        check(f"a {how} directory holding every browser fetches nothing and runs no install",
              c.requests == 0 and fetches(c.fetchlog) == [] and installs(c.uvlog) == [], str(calls(c.uvlog)))

print("== a browser missing from a directory this user cannot write is named at once ==")
with tempfile.TemporaryDirectory() as t:
    c = Case(t, 0o555, ("chromium-9",))
    scratch_caches.append(c.cache)
    problems = c.ensure()
    c.browsers.chmod(0o555)
    try:
        script = pb.check(c.lock)[0]
    finally:
        c.browsers.chmod(0o755)
    check("it is one problem", len(problems) == 1, str(problems))
    check("it names the directory, says it is not writable, and names the missing browser at its location",
          bool(problems) and f"browsers directory {c.browsers} is not writable" in problems[0]
          and f"FFmpeg (playwright ffmpeg v9) at {c.browsers / 'ffmpeg-9'}" in problems[0]
          and "chromium" not in problems[0], str(problems))
    check("nothing is fetched and no install is run, so there is no lock to wait on",
          c.requests == 0 and fetches(c.fetchlog) == [] and installs(c.uvlog) == [], str(calls(c.uvlog)))
    check("check() reports the same problem", script == problems, str(script))
    group = pb.ownership(c.browsers).rsplit(" ", 1)[-1]
    check("it names the directory's owner, group and mode, and whether this user is in that group (#672)",
          bool(problems) and f"({c.browsers} is owner " in problems[0] and ", mode 555, and " in problems[0]
          and f"{pb._user()} is in group {group})" in problems[0], str(problems))

print("== the ownership says when this user is not in the directory's group (#672) ==")
with tempfile.TemporaryDirectory() as t:
    d = pathlib.Path(t)
    group = pb.ownership(d).rsplit(" ", 1)[-1]
    check("this user's own directory: it is in the directory's group",
          pb.ownership(d).endswith(f"and {pb._user()} is in group {group}"), pb.ownership(d))
    check("a directory that does not exist yet is described by the nearest one above it",
          pb.ownership(d / "a" / "b") == pb.ownership(d), pb.ownership(d / "a" / "b"))
    saved = (os.getgid, os.getgroups)
    # A user whose groups hold nothing of the directory's, as a run user outside hecaton-tools.
    os.getgid, os.getgroups = (lambda: -1), (lambda: [])
    try:
        outside = pb.ownership(d)
    finally:
        os.getgid, os.getgroups = saved
    check("a user outside the directory's group is told so, with the group named",
          outside.endswith(f"and {pb._user()} is not in group {group}"), outside)

print("== a cache miss: each zip fetched once, logged, verified and unpacked ==")
shared = artifact_cache.scratch_dir("pwb-shared-")
scratch_caches.append(shared)
with tempfile.TemporaryDirectory() as t:
    c = Case(t, cache=shared)
    problems = c.ensure()
    check(f"it is ready ({problems})", problems == [])
    check("each missing zip was asked for once", c.requests == 2 and SERVER.hits.get("/chromium-9.zip") == 1
          and SERVER.hits.get("/ffmpeg-9.zip") == 1, str(SERVER.hits))
    log = fetches(c.fetchlog)
    check("each fetch is one `ok` line in the fetch log, naming the URL and the pinned sum",
          len(log) == 2 and all(ln.endswith("\tok") for ln in log)
          and {ln.split("\t")[1] for ln in log} == set(URLS.values())
          and {ln.split("\t")[2] for ln in log} == {sha(z) for z in ZIPS.values()}, str(log))
    check("no `playwright install` ran", installs(c.uvlog) == [], str(calls(c.uvlog)))
    loc = c.browsers / "chromium-9"
    check("INSTALLATION_COMPLETE is written in each install location",
          all((c.browsers / d / pb.MARKER).is_file() for d in ZIPS))
    check("the zip is unpacked in the location as Playwright lays it out",
          (loc / "chrome-linux64" / "ABOUT").read_text() == "about\n")
    check("an executable keeps its execute bit", os.access(loc / "chrome-linux64" / "bin", os.X_OK))
    check("a plain file is not made executable", not os.access(loc / "chrome-linux64" / "ABOUT", os.X_OK))
    check("a symlink stays a symlink", (loc / "chrome-linux64" / "link").is_symlink()
          and os.readlink(loc / "chrome-linux64" / "link") == "bin")
    check("no temp directory is left beside the locations",
          sorted(p.name for p in c.browsers.iterdir() if not p.name.startswith(".wib-")) == sorted(ZIPS),
          str(sorted(p.name for p in c.browsers.iterdir())))
    check("each zip is in the cache under its sum",
          all(artifact_cache.path_for(sha(z), shared).is_file()
              and artifact_cache.path_for(sha(z), shared).read_bytes() == z for z in ZIPS.values()))

print("== a cache hit: a fresh browsers directory on the same cache makes no request ==")
with tempfile.TemporaryDirectory() as t:
    c = Case(t, cache=shared)
    before = fetches(c.fetchlog)
    SERVER.httpd.shutdown()
    try:
        problems = c.ensure()
    finally:
        threading.Thread(target=SERVER.httpd.serve_forever, daemon=True).start()
    check(f"it is ready with the server stopped ({problems})", problems == [])
    check("no request was made and the fetch log is unchanged", c.requests == 0 and fetches(c.fetchlog) == before,
          str(fetches(c.fetchlog)))
    check("the browsers are unpacked from the cached zips",
          all((c.browsers / d / pb.MARKER).is_file() for d in ZIPS)
          and os.access(c.browsers / "ffmpeg-9" / "ffmpeg" / "bin", os.X_OK))

print("== an install location without its marker is an unfinished unpack and is replaced ==")
with tempfile.TemporaryDirectory() as t:
    c = Case(t, cache=shared, installed=("ffmpeg-9",))
    (c.browsers / "chromium-9" / "chrome-linux64").mkdir(parents=True)
    (c.browsers / "chromium-9" / "chrome-linux64" / "stale").write_text("half")
    problems = c.ensure()
    check(f"it is ready ({problems})", problems == [])
    check("the stale file is gone and the browser is whole",
          not (c.browsers / "chromium-9" / "chrome-linux64" / "stale").exists()
          and (c.browsers / "chromium-9" / pb.MARKER).is_file()
          and (c.browsers / "chromium-9" / "chrome-linux64" / "bin").is_file())
    check("the installed browser beside it was left alone", c.requests == 0
          and sorted(p.name for p in (c.browsers / "ffmpeg-9").iterdir()) == [pb.MARKER])

print("== a cached zip that no longer matches its sum fails by name, with no request and no browser ==")
tampered = artifact_cache.scratch_dir("pwb-tampered-")
scratch_caches.append(tampered)
entry = artifact_cache.path_for(sha(ZIPS["chromium-9"]), tampered)
entry.parent.mkdir(parents=True)
entry.write_bytes(ZIPS["chromium-9"] + b"x")
with tempfile.TemporaryDirectory() as t:
    c = Case(t, cache=tampered, installed=("ffmpeg-9",))
    problems = c.ensure()
    check("it is one problem naming the browser, the cached path and both sums",
          len(problems) == 1 and NAMES["chromium-9"] in problems[0] and str(entry) in problems[0]
          and sha(ZIPS["chromium-9"]) in problems[0] and sha(ZIPS["chromium-9"] + b"x") in problems[0], str(problems))
    check("nothing was fetched over it", c.requests == 0 and fetches(c.fetchlog) == [], str(fetches(c.fetchlog)))
    check("the cached file is left as it was", entry.read_bytes() == ZIPS["chromium-9"] + b"x")
    check("no browser was put at the location", not (c.browsers / "chromium-9").exists())

print("== a download that does not match its pin fails, caching nothing and leaving no browser ==")
with tempfile.TemporaryDirectory() as t:
    c = Case(t, installed=("ffmpeg-9",), lock_kw={"sums": {"chromium-9": sha(b"other bytes")}})
    scratch_caches.append(c.cache)
    problems = c.ensure()
    check("it is one problem naming the URL and both sums",
          len(problems) == 1 and URLS["chromium-9"] in problems[0] and sha(b"other bytes") in problems[0]
          and sha(ZIPS["chromium-9"]) in problems[0], str(problems))
    check("it was fetched once and logged as a mismatch", c.requests == 1
          and len(fetches(c.fetchlog)) == 1 and "\tmismatch " in fetches(c.fetchlog)[0], str(fetches(c.fetchlog)))
    check("nothing is cached under the pin", not artifact_cache.path_for(sha(b"other bytes"), c.cache).exists())
    check("no browser was put at the location", not (c.browsers / "chromium-9").exists())

print("== a browser the lock does not pin, or pins at another URL, is a problem, installed or not ==")
with tempfile.TemporaryDirectory() as t:
    c = Case(t, installed=tuple(ZIPS), urls={"ffmpeg-9": "https://cdn.invalid/moved/ffmpeg-9.zip"})
    scratch_caches.append(c.cache)
    problems = c.ensure()
    check("a URL the dry run names that the lock does not is one problem naming both URLs",
          len(problems) == 1 and "https://cdn.invalid/moved/ffmpeg-9.zip" in problems[0]
          and URLS["ffmpeg-9"] in problems[0] and "playwright_browsers.py lock" in problems[0], str(problems))
with tempfile.TemporaryDirectory() as t:
    c = Case(t, lock_kw={"dirs": ("ffmpeg-9",)})
    scratch_caches.append(c.cache)
    problems = c.ensure()
    check("a listed directory the lock does not pin is a problem naming it, and nothing is fetched",
          len(problems) == 1 and "pins no chromium-9" in problems[0] and c.requests == 0, str(problems))
with tempfile.TemporaryDirectory() as t:
    c = Case(t, installed=tuple(ZIPS), lock_kw={"version": "1.0.0"})
    scratch_caches.append(c.cache)
    problems = c.ensure()
    check(f"a lock for another Playwright is a problem naming both pins",
          len(problems) == 1 and "playwright 1.0.0" in problems[0] and pb.PLAYWRIGHT in problems[0], str(problems))
with tempfile.TemporaryDirectory() as t:
    c = Case(t)
    scratch_caches.append(c.cache)
    c.lock.write_text("playwright " + VERSION + "\nchromium-9 nothex " + URLS["chromium-9"] + "\n")
    problems = c.ensure()
    check("a malformed lock line is a problem naming it", len(problems) == 1 and "nothex" in problems[0]
          and c.requests == 0, str(problems))
    c.lock.unlink()
    problems = c.ensure()
    check("a missing lock is a problem naming it", len(problems) == 1 and str(c.lock) in problems[0], str(problems))

print("== a zip member that would land outside its location is refused ==")
with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    evil = tmp / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escaped", b"x")
    try:
        pb.unzip(evil, tmp / "dest")
        check("a member with `..` is refused", False, "no error raised")
    except artifact_cache.ArtifactCacheError as e:
        check("a member with `..` is refused, naming it", "../escaped" in str(e), str(e))
    check("and nothing was written outside", not (tmp / "escaped").exists())

print("== a dry run that fails or lists nothing is a problem, not a pass ==")
with tempfile.TemporaryDirectory() as t:
    c = Case(t, installed=tuple(ZIPS), dry_rc=3)
    scratch_caches.append(c.cache)
    problems = c.ensure()
    check("a dry run that exits non-zero is named with its exit code",
          len(problems) == 1 and "--dry-run chromium` (playwright==" in problems[0] and "exited 3" in problems[0],
          str(problems))
    check("and nothing is fetched", c.requests == 0, str(SERVER.hits))
with tempfile.TemporaryDirectory() as t:
    c = Case(t, listing="nothing to see\n")
    scratch_caches.append(c.cache)
    problems = c.ensure()
    check("a dry run that lists no install location is a problem",
          len(problems) == 1 and "listed no install location" in problems[0], str(problems))
os.environ["PATH"] = PATH
SERVER.close()
for d in scratch_caches:
    shutil.rmtree(d, ignore_errors=True)

print("== nothing runs `playwright install` but the module's dry run, and the tier tests install through it ==")


def runs_install(text: str) -> bool:
    """Whether a line of code (not a comment) runs `playwright install` for anything but a dry run."""
    for line in text.splitlines():
        code = line.strip()
        if code.startswith("#") or "--dry-run" in code:
            continue
        if re.search(r'"playwright",\s*"install"', code) or re.search(r"(^|run:\s*|[;&|]\s*)(uv run \S.*\s)?playwright install\b", code):
            return True
    return False


check("runs_install() sees a list-form and a shell-form call, and not a dry run or a comment",
      runs_install('subprocess.run([*UV, "playwright", "install", *BROWSERS])')
      and runs_install("uv run --no-project --with playwright==1 playwright install chromium")
      and not runs_install('[*UV, "playwright", "install", "--dry-run", *BROWSERS]')
      and not runs_install("# `playwright install` takes a lock"))
callers = [f.name for f in sorted({*VERIFY.glob("*.py"), *VERIFY.glob("*.sh"), *(VERIFY.parent / "scripts").glob("*"),
                                   *(VERIFY.parent / ".github" / "workflows").glob("*.yml")})
           if f.is_file() and f.name != pathlib.Path(__file__).name and runs_install(f.read_text(errors="replace"))]
check("no script, test or workflow runs `playwright install` to download a browser", callers == [], str(callers))
for t in sorted(VERIFY.glob("test_*.py")):
    text = t.read_text()
    if t.name == pathlib.Path(__file__).name or not re.search(r"^# E2E TIER: tools", text, re.M):
        continue
    if "playwright" not in text.lower():
        continue
    check(f"{t.name} gets its browsers from playwright_browsers.ensure()",
          "from playwright_browsers import" in text and "ensure()" in text)
check("test_mobile_titles_e2e.py is one of them",
      "from playwright_browsers import" in (VERIFY / "test_mobile_titles_e2e.py").read_text())

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll Playwright browser checks passed.")
