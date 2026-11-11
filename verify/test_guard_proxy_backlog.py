# ABOUTME: Holds #1337 offline: guard-proxy's command starts proxy.py with a listen backlog of 1024, not the stdlib's 5,
# ABOUTME: and its CPU limit stays at 1 CPU or more, so a burst at the cluster window's reopening is queued, not reset.
"""In run 20287's two 500-phone replays (#1334), eight /chat turns came back 502 or 504 from the console's nginx and
never reached guard-proxy's handler. nginx's error log named the cause of each: seven "recv() failed (104: Connection
reset by peer) while reading response header from upstream" and one "upstream timed out (110) while connecting to
upstream". guard-proxy's pod counted 3,227 ListenOverflows. proxy.py serves with http.server's ThreadingHTTPServer,
which listens with a backlog of 5, and the process sat at its 250m CPU limit, throttled every period, while the window
let a burst through.

What this holds, offline:
- The Deployment's command is `python -c CODE`, and CODE runs /app/proxy.py as __main__ after setting
  ThreadingHTTPServer.request_queue_size to 1024.
- CODE, run as written with /app/proxy.py pointed at a stand-in that builds its server the way proxy.py does and never
  accepts, takes 64 loopback connections at once. The stand-in run alone, with the stdlib's backlog of 5, does not,
  so the probe tells the two apart.
- The pinned proxy.py still builds its server as `ThreadingHTTPServer(("0.0.0.0", 8080), Handler)`, the class whose
  attribute CODE sets.
- The proxy container's CPU limit is 1 CPU or more.

The live half, #644's replay on watch-it-burn-community once this is synced, with 0 turns answered 502 or 504 and no
new ListenOverflows, is #1337's decisions.md entry under "Not yet run on a cluster".
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
PROXY_PY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
APP_PATH = "/app/proxy.py"
SERVER_LINE = 'ThreadingHTTPServer(("0.0.0.0", 8080), Handler)'
BACKLOG = 1024
CONNECTIONS = 64
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def cpu_millis(v: object) -> int:
    s = str(v)
    return int(s[:-1]) if s.endswith("m") else int(float(s) * 1000)


# Builds its server as proxy.py does and never accepts, then opens CONNECTIONS at once, each given 0.5 s.
STAND_IN = f"""
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
srv = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
port = srv.server_address[1]
held, ok = [], 0
for _ in range({CONNECTIONS}):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        ok += 1
    except OSError:
        break
    held.append(s)
print(srv.request_queue_size, ok)
"""


def run(argv: list[str]) -> tuple[int, int]:
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"FAIL: {argv[:2]} exited {out.returncode}: {out.stderr.strip()[-400:]}")
    size, ok = out.stdout.split()
    return int(size), int(ok)


def main() -> int:
    docs = [d for d in yaml.safe_load_all(RESOURCES.read_text()) if d]
    gp = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
    proxy = next(c for c in gp["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
    cmd = proxy.get("command") or []

    print("== guard-proxy's command sets the listen backlog ==")
    check("the command is python -c CODE", len(cmd) == 3 and cmd[:2] == ["python", "-c"], str(cmd))
    code = cmd[2] if len(cmd) == 3 else ""
    if APP_PATH not in code:
        raise SystemExit(f"FAIL: the anchor {APP_PATH!r} is not in guard-proxy's command in {RESOURCES}: {cmd}")
    check(f"CODE sets ThreadingHTTPServer.request_queue_size to {BACKLOG} and runs {APP_PATH} as __main__",
          f"ThreadingHTTPServer.request_queue_size = {BACKLOG}" in code
          and f"runpy.run_path('{APP_PATH}', run_name='__main__')" in code, code)

    print("== the command, run, queues a burst the stdlib's backlog drops ==")
    with tempfile.TemporaryDirectory(dir=REPO / "tmp" if (REPO / "tmp").is_dir() else None) as d:
        stand_in = pathlib.Path(d) / "proxy.py"
        stand_in.write_text(STAND_IN)
        size, ok = run([sys.executable, "-c", code.replace(APP_PATH, str(stand_in))])
        check(f"under the command, the server listens with {BACKLOG}", size == BACKLOG, str(size))
        check(f"under the command, {CONNECTIONS} connections are taken with none accepted", ok == CONNECTIONS, str(ok))
        size0, ok0 = run([sys.executable, str(stand_in)])
        check("alone, the stand-in listens with the stdlib's 5", size0 == 5, str(size0))
        check(f"alone, it takes fewer than {CONNECTIONS}, so the probe tells the two apart", ok0 < CONNECTIONS,
              str(ok0))

    print("== the pinned proxy.py builds the server the command reaches ==")
    if not PROXY_PY.is_file():
        raise SystemExit(f"FAIL: {PROXY_PY} is missing; run bash verify/ensure-submodules.sh")
    src = PROXY_PY.read_text()
    check(f"proxy.py serves with {SERVER_LINE}", SERVER_LINE in src)
    check("proxy.py imports ThreadingHTTPServer from http.server",
          "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer" in src)

    print("== guard-proxy's CPU limit ==")
    limit = (proxy.get("resources") or {}).get("limits", {}).get("cpu")
    check("the proxy container's CPU limit is 1 CPU or more (it ran pinned at 250m in run 20287's replays)",
          limit is not None and cpu_millis(limit) >= 1000, str(limit))

    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
