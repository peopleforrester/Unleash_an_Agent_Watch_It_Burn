# ABOUTME: Holds #1337 and #1343 offline: the pinned proxy.py's own server listens with a backlog of 1024, not the
# ABOUTME: stdlib's 5, the Deployment runs it directly, and its CPU limit stays at 1 CPU or more, so a burst is queued.
"""In run 20287's two 500-phone replays (#1334), eight /chat turns came back 502 or 504 from the console's nginx and
never reached guard-proxy's handler. nginx's error log named the cause of each: seven "recv() failed (104: Connection
reset by peer) while reading response header from upstream" and one "upstream timed out (110) while connecting to
upstream". guard-proxy's pod counted 3,227 ListenOverflows. proxy.py served with http.server's ThreadingHTTPServer,
which listens with a backlog of 5, and the process sat at its 250m CPU limit, throttled every period, while the window
let a burst through.

#1337 set the backlog from the Deployment's command, a `python -c` wrapper that set the class attribute and ran
proxy.py through runpy. guard-proxy-agenticburn#85 (c8599fe) moved it into proxy.py: its __main__ serves through
`Server`, a ThreadingHTTPServer subclass with request_queue_size = 1024. Since #1343 the Deployment runs proxy.py
directly, and this test reads the backlog from the pinned proxy.py, not from command text.

What this holds, offline:
- The Deployment's command is `python /app/proxy.py`, with no wrapper.
- The pinned proxy.py's __main__ builds only `Server`, and `Server` is a ThreadingHTTPServer.
- The pinned proxy.py, imported in a child process, gives a `Server` that listens with 1024 and, never accepting,
  takes 64 loopback connections at once. The stdlib's ThreadingHTTPServer, probed the same way, listens with 5 and
  takes fewer, so the probe tells the two apart.
- The proxy container's CPU limit is 1 CPU or more.

The live half, #644's replay on watch-it-burn-community once this is synced, with 0 turns answered 502 or 504 and no
new ListenOverflows, is #1343's decisions.md entry under "Not yet run on a cluster".
"""
from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
RESOURCES = REPO / "gitops/ai-layer/resources.yaml"
PROXY_PY = REPO / "gitops/ai-layer/guard-proxy/proxy.py"
COMMAND = ["python", "/app/proxy.py"]
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


# argv: the path of proxy.py, then "proxy" to probe its Server or "stdlib" to probe ThreadingHTTPServer. Builds the
# server on a loopback port and never accepts, then opens CONNECTIONS at once, each given 0.5 s to connect.
PROBE = f"""
import importlib.util, socket, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
spec = importlib.util.spec_from_file_location("guard_proxy_backlog", sys.argv[1])
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
cls = proxy.Server if sys.argv[2] == "proxy" else ThreadingHTTPServer
srv = cls(("127.0.0.1", 0), BaseHTTPRequestHandler)
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
print(srv.request_queue_size, int(issubclass(cls, ThreadingHTTPServer)), ok)
"""


def probe(which: str) -> tuple[int, int, int]:
    # proxy.py reads its settings at import; no OTel exporter is configured, so it sends no telemetry anywhere.
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
    out = subprocess.run([sys.executable, "-c", PROBE, str(PROXY_PY), which], capture_output=True, text=True,
                         timeout=120, env=env, cwd=REPO)
    if out.returncode != 0:
        raise SystemExit(f"FAIL: the {which} probe exited {out.returncode}: {out.stderr.strip()[-400:]}")
    size, is_sub, ok = out.stdout.split()[-3:]
    return int(size), int(is_sub), int(ok)


def main() -> int:
    docs = [d for d in yaml.safe_load_all(RESOURCES.read_text()) if d]
    gp = next(d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
    proxy = next(c for c in gp["spec"]["template"]["spec"]["containers"] if c["name"] == "proxy")
    cmd = proxy.get("command") or []

    print("== guard-proxy's Deployment runs proxy.py directly ==")
    check(f"the command is {COMMAND}, with no wrapper setting the backlog", cmd == COMMAND, str(cmd))

    print("== the pinned proxy.py serves through its own Server ==")
    if not PROXY_PY.is_file():
        raise SystemExit(f"FAIL: {PROXY_PY} is missing; run bash verify/ensure-submodules.sh")
    tree = ast.parse(PROXY_PY.read_text())
    mains = [n for n in tree.body if isinstance(n, ast.If) and ast.unparse(n.test) == "__name__ == '__main__'"]
    if len(mains) != 1:
        raise SystemExit(f"FAIL: {PROXY_PY} has {len(mains)} `if __name__ == '__main__'` blocks, not one")
    built = {n.func.id for n in ast.walk(mains[0]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    check("proxy.py's __main__ builds Server and no other server", built == {"Server"}, str(sorted(built)))

    print("== the pinned Server queues a burst the stdlib's backlog drops ==")
    size, is_sub, ok = probe("proxy")
    check("Server is a ThreadingHTTPServer", is_sub == 1)
    check(f"Server listens with {BACKLOG}", size == BACKLOG, str(size))
    check(f"Server takes {CONNECTIONS} connections with none accepted", ok == CONNECTIONS, str(ok))
    size0, _, ok0 = probe("stdlib")
    check("the stdlib's ThreadingHTTPServer listens with 5", size0 == 5, str(size0))
    check(f"it takes fewer than {CONNECTIONS}, so the probe tells the two apart", ok0 < CONNECTIONS, str(ok0))

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
