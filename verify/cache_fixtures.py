# ABOUTME: What the host artifact cache's offline tests share (#1117, #1118): a loopback file server that counts requests,
# ABOUTME: and a scratch directory outside every git worktree, where a cache root may sit.
"""test_artifact_cache.py, test_e2e_tools_tier.py and test_chart_fetch.py each need a cache root the helper accepts and
something to fetch from with no internet. A root inside a worktree is refused (artifact_cache.resolve_root), and hecaton
points TMPDIR inside the run's worktree, so scratch_base() looks further. Server() serves bytes by path on 127.0.0.1 and
counts each request, which is how a test tells a cache hit (no request) from a miss (one)."""
from __future__ import annotations

import http.server
import pathlib
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import artifact_cache as ac  # noqa: E402

HALF_OF = 2  # a gated path sends len(body) // HALF_OF bytes, then waits on the gate


class Server:
    """Serves self.files by path and counts requests per path. A path in self.gated sends half its body, then waits on
    self.gate before sending the rest. A path in self.failing answers its next N requests with the status it is given
    (self.failing[path] = [N, status]) before serving the file."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.hits: dict[str, int] = {}
        self.gated: set[str] = set()
        self.failing: dict[str, list[int]] = {}
        self.gate = threading.Event()
        self.lock = threading.Lock()
        srv = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                with srv.lock:
                    srv.hits[self.path] = srv.hits.get(self.path, 0) + 1
                    fail = srv.failing.get(self.path)
                    status = 0
                    if fail and fail[0] > 0:
                        fail[0] -= 1
                        status = fail[1]
                if status:
                    self.send_error(status)
                    return
                body = srv.files.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.path in srv.gated:
                    half = len(body) // HALF_OF
                    self.wfile.write(body[:half])
                    self.wfile.flush()
                    srv.gate.wait(60)
                    self.wfile.write(body[half:])
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


def scratch_base(prefix: str = "artifact-cache-test-") -> pathlib.Path:
    """A new temp directory outside every git worktree: the first of TMPDIR, /tmp, /var/tmp and /dev/shm that is outside
    one and takes a new directory. Hecaton points TMPDIR inside the run's worktree, where the helper rightly refuses a
    root. In run 18422 the dispatcher's private /tmp and /var/tmp were deleted while the run was going (findmnt read
    both as `//deleted`), so a mkdir there failed with ENOENT though the path was still a directory. With none usable
    the test fails, naming each one and why."""
    why = []
    for cand in dict.fromkeys(map(pathlib.Path, (tempfile.gettempdir(), "/tmp", "/var/tmp", "/dev/shm"))):
        tree = ac.worktree_of(cand)
        if tree is not None:
            why.append(f"{cand} is inside the git worktree {tree}")
            continue
        try:
            return pathlib.Path(tempfile.mkdtemp(prefix=prefix, dir=cand))
        except OSError as e:
            why.append(f"{cand}: {e}")
    raise SystemExit("FAIL: no temp directory outside a git worktree takes a new directory:\n  " + "\n  ".join(why))
