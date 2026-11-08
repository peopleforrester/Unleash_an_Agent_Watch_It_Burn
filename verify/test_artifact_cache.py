# ABOUTME: Holds verify/artifact_cache.py, the host's content-addressed cache (#1117), offline against a loopback file server:
# ABOUTME: the root's order, a root inside a worktree refused, hit, miss, both kinds of mismatch, and two fetches at once.
"""Every later child of #1115 routes its pinned fetches through artifact_cache.get(), so this holds what get() promises,
with no internet: a ThreadingHTTPServer on 127.0.0.1 serves the artifacts and counts each request, and the fetch log
the helper writes is read back. The two concurrent fetches are two processes of verify/artifact-cache.sh; the server
holds the first one's download half-sent until the second is seen in /proc/locks waiting on the same sum's lock, so
the case is a real overlap every time and not a race the timing happens to win."""
from __future__ import annotations

import hashlib
import http.server
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))
import artifact_cache as ac  # noqa: E402

SH = VERIFY / "artifact-cache.sh"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


GOOD = b"pinned artifact bytes\n" * 4096
HALF = len(GOOD) // 2


class Server:
    """Serves self.files by path and counts requests per path. A path in self.gated sends half its body, then waits on
    self.gate before sending the rest."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.hits: dict[str, int] = {}
        self.gated: set[str] = set()
        # path -> how many more requests for it answer 503 before it is served.
        self.flaky: dict[str, int] = {}
        self.gate = threading.Event()
        self.lock = threading.Lock()
        srv = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                with srv.lock:
                    srv.hits[self.path] = srv.hits.get(self.path, 0) + 1
                    if srv.flaky.get(self.path, 0) > 0:
                        srv.flaky[self.path] -= 1
                        self.send_error(503)
                        return
                body = srv.files.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.path in srv.gated:
                    self.wfile.write(body[:HALF])
                    self.wfile.flush()
                    srv.gate.wait(60)
                    self.wfile.write(body[HALF:])
                else:
                    self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def requests(self) -> int:
        with self.lock:
            return sum(self.hits.values())

    def close(self):
        self.gate.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def scratch_base() -> pathlib.Path:
    """A new temp directory outside every git worktree (artifact_cache.scratch_dir, which says how it picks one); with
    none usable the test fails, naming each candidate and why."""
    try:
        return ac.scratch_dir("artifact-cache-test-")
    except ac.ArtifactCacheError as e:
        raise SystemExit(f"FAIL: {e}")


CLEAN = {k: v for k, v in os.environ.items()
         if k not in (*ac.ROOT_VARS, "ARTIFACT_FETCH_LOG", "XDG_CACHE_HOME")}


def cli(*args: str, root: pathlib.Path, log: pathlib.Path) -> subprocess.CompletedProcess:
    env = {**CLEAN, "WIB_ARTIFACT_CACHE": str(root), "ARTIFACT_FETCH_LOG": str(log)}
    return subprocess.run(["bash", str(SH), *args], env=env, capture_output=True, text=True, timeout=60)


def log_lines(log: pathlib.Path) -> list[list[str]]:
    return [ln.split("\t") for ln in log.read_text().splitlines()] if log.exists() else []


def leftovers(root: pathlib.Path) -> list[str]:
    d = root / "sha256"
    return sorted(p.name for p in d.glob(".*.part")) if d.is_dir() else []


def test_root_order(base: pathlib.Path) -> None:
    print("root resolution")
    h, w, x, home = (base / n for n in ("hecaton", "wib", "xdg", "home"))
    full = {"HECATON_TOOLS_CACHE": str(h), "WIB_ARTIFACT_CACHE": str(w), "XDG_CACHE_HOME": str(x), "HOME": str(home)}
    check("HECATON_TOOLS_CACHE comes first", ac.resolve_root(full) == h.resolve())
    no_h = {**full, "HECATON_TOOLS_CACHE": ""}
    check("an empty HECATON_TOOLS_CACHE is passed over for WIB_ARTIFACT_CACHE", ac.resolve_root(no_h) == w.resolve())
    no_w = {k: v for k, v in full.items() if k not in ac.ROOT_VARS}
    check("then ${XDG_CACHE_HOME}/wib-artifacts", ac.resolve_root(no_w) == (x / "wib-artifacts").resolve())
    check("then $HOME/.cache/wib-artifacts", ac.resolve_root({"HOME": str(home)}) == (home / ".cache/wib-artifacts").resolve())
    try:
        ac.resolve_root({})
        check("with nothing set it fails, naming the variables", False, "resolve_root({}) returned")
    except ac.ArtifactCacheError as e:
        check("with nothing set it fails, naming the variables", "HECATON_TOOLS_CACHE" in str(e) and "HOME" in str(e), str(e))
    r = subprocess.run(["bash", str(SH), "root"], env={**CLEAN, "WIB_ARTIFACT_CACHE": str(w)}, capture_output=True,
                       text=True, timeout=60)
    check("artifact-cache.sh root prints the resolved root", r.returncode == 0 and r.stdout.strip() == str(w.resolve()),
          f"exit {r.returncode}: {r.stdout!r} {r.stderr!r}")


def test_root_in_worktree(base: pathlib.Path, srv: Server) -> None:
    print("a root inside a git worktree")
    repo = base / "a-worktree"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    inside = repo / "deep" / "cache"
    for name, root in (("a fresh repository", inside), ("this repo's own verify/.tools", VERIFY / ".tools" / "cache")):
        try:
            ac.resolve_root({"HECATON_TOOLS_CACHE": str(root)})
            check(f"a root in {name} is refused", False, "resolve_root returned")
        except ac.RootInWorktree as e:
            check(f"a root in {name} is refused, naming the path", str(root.resolve()) in str(e), str(e))
    sub = repo / "sub"
    sub.mkdir()
    (sub / ".git").write_text("gitdir: ../.git/modules/sub\n")
    try:
        ac.resolve_root({"WIB_ARTIFACT_CACHE": str(sub / "c")})
        check("a root in a submodule (a .git file) is refused", False, "resolve_root returned")
    except ac.RootInWorktree as e:
        check("a root in a submodule (a .git file) is refused", str(sub) in str(e), str(e))

    srv.files["/wt.bin"] = GOOD
    before = srv.requests()
    log = base / "wt-fetch.log"
    r = subprocess.run(["bash", str(SH), "get", sha(GOOD), srv.url("/wt.bin")],
                       env={**CLEAN, "HECATON_TOOLS_CACHE": str(inside), "WIB_ARTIFACT_CACHE": str(base / "unused"),
                            "ARTIFACT_FETCH_LOG": str(log)}, capture_output=True, text=True, timeout=60)
    check("artifact-cache.sh get exits non-zero for a root in a worktree", r.returncode == 1, f"exit {r.returncode}")
    check("and names the path and the worktree", str(inside) in r.stderr and str(repo) in r.stderr, r.stderr)
    check("and neither falls back to the next root nor fetches",
          srv.requests() == before and not (base / "unused").exists() and not inside.exists() and not log.exists())


def test_miss_then_hit(base: pathlib.Path, srv: Server) -> None:
    print("a miss, then a hit")
    root, log = base / "cache-miss", base / "miss-fetch.log"
    srv.files["/tool.tar.gz"] = GOOD
    url = srv.url("/tool.tar.gz")
    final = root / "sha256" / sha(GOOD)
    r = cli("get", sha(GOOD), url, root=root, log=log)
    check("a miss prints <root>/sha256/<hex>", r.returncode == 0 and r.stdout.strip() == str(final),
          f"exit {r.returncode}: {r.stdout!r} {r.stderr!r}")
    check("holding the pinned bytes", final.is_file() and final.read_bytes() == GOOD)
    check("after one request", srv.hits.get("/tool.tar.gz") == 1, str(srv.hits))
    lines = log_lines(log)
    check("and one fetch-log line naming the URL, the sum and the bytes",
          len(lines) == 1 and lines[0][1:] == [url, sha(GOOD), str(len(GOOD)), "ok"], str(lines))
    check("with no temp file left", leftovers(root) == [], str(leftovers(root)))

    srv.close()  # nothing answers at url now: a hit that reached the network would fail
    r = cli("get", sha(GOOD), url, root=root, log=log)
    check("a hit is served with the server gone", r.returncode == 0 and r.stdout.strip() == str(final),
          f"exit {r.returncode}: {r.stderr!r}")
    check("and adds nothing to the fetch log", len(log_lines(log)) == 1, str(log_lines(log)))

    def no_network(url: str, out) -> None:
        raise AssertionError(f"fetched {url} on a hit")

    try:
        got = ac.get(sha(GOOD), url, root=root, fetch=no_network, env={"ARTIFACT_FETCH_LOG": str(log)})
        check("get() on a hit returns the file without calling its fetcher", got == final)
    except Exception as e:  # noqa: BLE001
        check("get() on a hit returns the file without calling its fetcher", False, repr(e))

    # The hit is hashed again, every time: one bit flipped after the first serve is caught on the next.
    data = bytearray(final.read_bytes())
    data[0] ^= 1
    final.write_bytes(bytes(data))
    calls: list[str] = []
    try:
        ac.get(sha(GOOD), url, root=root, fetch=lambda u, o: calls.append(u), env={"ARTIFACT_FETCH_LOG": str(log)})
        check("a hit changed after it was first served fails on the next get", False, "get returned")
    except ac.ArtifactMismatch as e:
        check("a hit changed after it was first served fails on the next get", sha(bytes(data)) in str(e), str(e))
    check("without calling the fetcher", calls == [], str(calls))


def test_mismatching_hit(base: pathlib.Path, srv: Server) -> None:
    print("a hit whose bytes do not match the pin")
    root, log = base / "cache-bad", base / "bad-fetch.log"
    srv.files["/good.bin"] = GOOD
    bad = b"not the pinned bytes\n"
    final = root / "sha256" / sha(GOOD)
    final.parent.mkdir(parents=True)
    final.write_bytes(bad)
    before = srv.requests()
    r = cli("get", sha(GOOD), srv.url("/good.bin"), root=root, log=log)
    check("artifact-cache.sh get exits 1", r.returncode == 1, f"exit {r.returncode}: {r.stdout!r}")
    check("naming the path, the pinned sum and the sum found",
          str(final) in r.stderr and sha(GOOD) in r.stderr and sha(bad) in r.stderr, r.stderr)
    check("printing no path on stdout", r.stdout == "", repr(r.stdout))
    check("leaving the file as it was", final.read_bytes() == bad)
    check("and downloading nothing again, though the server holds the right bytes",
          srv.requests() == before and not log.exists(), f"{srv.requests() - before} requests")

    (root / "sha256" / ("0" * 64)).mkdir()
    try:
        ac.get("0" * 64, srv.url("/good.bin"), root=root, env={"ARTIFACT_FETCH_LOG": str(log)})
        check("a cache entry that is not a regular file fails", False, "get returned")
    except ac.ArtifactMismatch as e:
        check("a cache entry that is not a regular file fails, naming it", str(root / "sha256" / ("0" * 64)) in str(e), str(e))


def test_bad_download(base: pathlib.Path, srv: Server) -> None:
    print("a miss whose download does not match, and one that fails")
    root, log = base / "cache-dl", base / "dl-fetch.log"
    served = b"the server changed this artifact\n"
    srv.files["/changed.bin"] = served
    url = srv.url("/changed.bin")
    r = cli("get", sha(GOOD), url, root=root, log=log)
    check("a download that does not match exits 1", r.returncode == 1, f"exit {r.returncode}")
    check("naming the URL and both sums", url in r.stderr and sha(GOOD) in r.stderr and sha(served) in r.stderr, r.stderr)
    check("and nothing is put in the cache", not (root / "sha256" / sha(GOOD)).exists() and leftovers(root) == [],
          str(leftovers(root)))
    lines = log_lines(log)
    check("the fetch is logged as a mismatch",
          len(lines) == 1 and lines[0][1:] == [url, sha(GOOD), str(len(served)), f"mismatch {sha(served)}"], str(lines))

    missing = srv.url("/missing.bin")
    r = cli("get", sha(GOOD), missing, root=root, log=log)
    check("a fetch that fails (a 404) exits 1, naming the URL", r.returncode == 1 and missing in r.stderr, r.stderr)
    lines = log_lines(log)
    check("and is logged too", len(lines) == 2 and lines[1][1] == missing and lines[1][4].startswith("error"), str(lines))
    check("and leaves nothing in the cache", not (root / "sha256" / sha(GOOD)).exists() and leftovers(root) == [])

    for bad_sum in ("ABC", sha(GOOD).upper(), sha(GOOD) + "0"):
        r = cli("get", bad_sum, url, root=root, log=log)
        check(f"a malformed sum ({bad_sum[:8]}..., {len(bad_sum)} chars) is refused", r.returncode == 1
              and "not a SHA-256" in r.stderr, r.stderr)


def test_retry(base: pathlib.Path, srv: Server) -> None:
    print("a miss the network broke is asked again; a 404 and a mismatch are not (#1118)")
    root, log = base / "cache-retry", base / "retry-fetch.log"
    env = {"ARTIFACT_FETCH_LOG": str(log)}
    srv.files["/flaky.bin"] = GOOD
    srv.flaky["/flaky.bin"] = 2
    url, waits = srv.url("/flaky.bin"), []
    before = srv.hits.get("/flaky.bin", 0)
    try:
        got, err = ac.get_retrying(sha(GOOD), url, root=root, env=env, sleep=waits.append), ""
    except ac.ArtifactCacheError as e:
        got, err = None, str(e)
    check(f"two 503s and then the file: it comes back ({err})", got == root / "sha256" / sha(GOOD)
          and got.read_bytes() == GOOD)
    check("after three requests", srv.hits.get("/flaky.bin", 0) - before == 3, str(srv.hits))
    check(f"with the first two waits of BACKOFF between them ({waits})", waits == list(ac.BACKOFF[:2]))
    lines = log_lines(log)
    check("each attempt is its own line in the fetch log", [ln[4].split()[0] for ln in lines] == ["error", "error", "ok"],
          str(lines))

    srv.flaky["/down.bin"], srv.files["/down.bin"] = 99, GOOD
    waits = []
    try:
        ac.get_retrying(sha(GOOD + b"x"), srv.url("/down.bin"), root=root, env=env, sleep=waits.append)
        err = ""
    except ac.ArtifactCacheError as e:
        err = str(e)
    check(f"a 503 on every attempt fails after the last ({err[:80]})", "503" in err and srv.hits.get("/down.bin") == 4
          and waits == list(ac.BACKOFF), f"{srv.hits} {waits}")

    for path, why in (("/nowhere.bin", "a 404"), ("/flaky.bin", "a download that does not match")):
        waits, before = [], srv.hits.get(path, 0)
        try:
            ac.get_retrying(sha(b"other"), srv.url(path), root=root, env=env, sleep=waits.append)
            err = ""
        except ac.ArtifactCacheError as e:
            err = str(e)
        check(f"{why} fails on the first attempt, with no wait", err != "" and waits == []
              and srv.hits.get(path, 0) - before == 1, f"{err} {waits} {srv.hits}")
    check("a 503, a timeout and a reset are transient; a 404 is not",
          ac.transient(ac.urllib.error.HTTPError("u", 503, "x", None, None)) and ac.transient(TimeoutError())
          and ac.transient(ConnectionResetError()) and not ac.transient(ac.urllib.error.HTTPError("u", 404, "x", None, None))
          and not ac.transient(None))


def lock_waiter(pid: int) -> bool:
    """Whether pid is blocked in /proc/locks waiting for an flock, the `->` lines."""
    for ln in pathlib.Path("/proc/locks").read_text().splitlines():
        f = ln.split()
        if len(f) > 5 and f[1] == "->" and f[2] == "FLOCK" and f[5] == str(pid):
            return True
    return False


def test_concurrent(base: pathlib.Path, srv: Server) -> None:
    print("two fetches of the same sum at once")
    root, log = base / "cache-two", base / "two-fetch.log"
    srv.files["/slow.bin"] = GOOD
    srv.gated.add("/slow.bin")
    url = srv.url("/slow.bin")
    final = root / "sha256" / sha(GOOD)
    env = {**CLEAN, "WIB_ARTIFACT_CACHE": str(root), "ARTIFACT_FETCH_LOG": str(log)}
    a = subprocess.Popen(["bash", str(SH), "get", sha(GOOD), url], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 30
    while srv.hits.get("/slow.bin", 0) < 1 and a.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    b = subprocess.Popen(["bash", str(SH), "get", sha(GOOD), url], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    waited = False
    while b.poll() is None and time.monotonic() < deadline:
        if lock_waiter(b.pid):
            waited = True
            break
        time.sleep(0.02)
    check("the first is mid-download while the second waits on the same sum's lock", waited and a.poll() is None,
          f"waited={waited}, first exit={a.poll()}, second exit={b.poll()}")
    check("and no reader can see the half-written file: <root>/sha256/<hex> does not exist yet, a temp file does",
          not final.exists() and len(leftovers(root)) == 1, f"exists={final.exists()}, temp={leftovers(root)}")
    srv.gate.set()
    out_a, err_a = a.communicate(timeout=60)
    out_b, err_b = b.communicate(timeout=60)
    check("both succeed with the same path", a.returncode == 0 and b.returncode == 0
          and out_a.strip() == out_b.strip() == str(final), f"a {a.returncode} {err_a!r}; b {b.returncode} {err_b!r}")
    check("holding the pinned bytes", final.read_bytes() == GOOD)
    check("from one download between them", srv.hits.get("/slow.bin") == 1, str(srv.hits))
    check("logged once", len(log_lines(log)) == 1, str(log_lines(log)))
    check("with no temp file left", leftovers(root) == [], str(leftovers(root)))


def main() -> int:
    base = scratch_base()
    srv = Server()
    try:
        test_root_order(base)
        test_root_in_worktree(base, srv)
        test_mismatching_hit(base, srv)
        test_bad_download(base, srv)
        test_retry(base, srv)
        test_concurrent(base, srv)
        test_miss_then_hit(base, srv)  # last: it shuts the server down to show a hit needs no network
    finally:
        srv.close()
        shutil.rmtree(base, ignore_errors=True)
    if failures:
        print(f"\nFAIL: {len(failures)} artifact-cache checks failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: the artifact cache resolves its root, refuses a worktree, verifies every hit and fetches a miss once")
    return 0


if __name__ == "__main__":
    sys.exit(main())
