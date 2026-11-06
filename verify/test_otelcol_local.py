# ABOUTME: Holds verify/otelcol_local.py's collector start to its three promises with a stand-in collector (#969): it
# ABOUTME: waits for the ready line before the send clock, survives a port taken before the bind, and says why it failed.
"""Offline: no otelcol-contrib, no network beyond loopback. The stand-in is a small Python server the test writes
itself. It binds 127.0.0.1:<port> the way the collector's OTLP/HTTP receiver does, logs the collector's own lines
("bind: address already in use" and exit 1 when the port is taken, "Everything is ready" once bound), and answers a
POST with its pid, so the test can tell which process took a turn. Each failure #969 named is forced, not waited for:
the taken port is held by this test, the slow start is a sleep before the bind, the silent collector never logs.
"""
from __future__ import annotations

import http.server
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import otelcol_local  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


STAND_IN = r'''
import errno, http.server, os, sys, time
port, mode, delay = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
time.sleep(delay)
if mode == "silent":
    time.sleep(3600)
if mode == "crash":
    print("Error: boom", flush=True)
    sys.exit(3)
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = f"stand-in pid={os.getpid()}".encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
try:
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
except OSError as e:
    if e.errno != errno.EADDRINUSE:
        raise
    print(f"Error: cannot start pipelines: listen tcp 127.0.0.1:{port}: bind: address already in use", flush=True)
    sys.exit(1)
print("info service.go:284 Everything is ready. Begin running and processing data.", flush=True)
srv.serve_forever()
'''


class Holder:
    """Another process's server on the port: it answers 200 too, so a turn sent to it would read as taken."""

    def __init__(self) -> None:
        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Length", "6")
                self.end_headers()
                self.wfile.write(b"holder")

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def post(port: int) -> str:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/traces", data=b"{}",
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=5).read().decode()


with tempfile.TemporaryDirectory() as d:
    script = pathlib.Path(d) / "stand_in.py"
    script.write_text(STAND_IN)
    log = pathlib.Path(d) / "collector.log"

    def argv(mode: str, delay: float = 0.0):
        return lambda port: [sys.executable, "-I", str(script), str(port), mode, str(delay)]

    print("== a port another process took between free_port() and the bind ==")
    holder = Holder()
    c = otelcol_local.start(argv("serve"), log, ports=iter([holder.port, otelcol_local.free_port()]))
    try:
        check("the start comes up on a fresh port", c.ready and c.port != holder.port, c.detail())
        check("it took two starts, the first one's log saying the address was in use",
              len(c.logs) == 1 and c.logs[0][0] == holder.port and otelcol_local.IN_USE in c.logs[0][1], c.detail())
        got = post(c.port) if c.ready else ""
        check("a turn sent to the port reaches this collector and not the holder",
              got == f"stand-in pid={c.proc.pid}", got)
        check("and the holder still has its own port", post(holder.port) == "holder")
    finally:
        c.stop()
        holder.close()

    print("== a port taken on every start ==")
    holders = [Holder() for _ in range(3)]
    c = otelcol_local.start(argv("serve"), log, ports=iter([h.port for h in holders]), attempts=3)
    try:
        detail = c.detail()
        check("the start fails after its attempts, not before", not c.ready and len(c.logs) == 2, detail)
        check("the detail carries proc.poll() and every attempt's log",
              "proc.poll() = 1" in detail and detail.count(otelcol_local.IN_USE) == 3, detail)
    finally:
        c.stop()
        for h in holders:
            h.close()

    print("== a slow start: nothing logged and nothing bound for 2 s ==")
    t0 = time.monotonic()
    c = otelcol_local.start(argv("serve", 2.0), log)
    try:
        check("start() returns only once the collector says it is ready", c.ready and time.monotonic() - t0 >= 2.0,
              c.detail())
        sent_at = time.monotonic()
        got = post(c.port) if c.ready else ""
        check("so the first POST after it is taken, the send clock not spent on the start",
              got == f"stand-in pid={c.proc.pid}" and time.monotonic() - sent_at < 5, got)
    finally:
        c.stop()

    print("== a collector that never says it is ready ==")
    c = otelcol_local.start(argv("silent"), log, ready_polls=10)
    try:
        detail = c.detail()
        check("the start fails once its polls run out, without a retry", not c.ready and not c.logs, detail)
        check("the detail says the collector is still running and that its log is empty",
              "proc.poll() = None (still running)" in detail and "(empty)" in detail and "waited 10 polls" in detail,
              detail)
    finally:
        c.stop()
    check("stop() ends it", c.proc.poll() is not None)

    print("== a collector that exits on something else ==")
    c = otelcol_local.start(argv("crash"), log)
    try:
        detail = c.detail()
        check("the start fails at once, without a retry", not c.ready and not c.logs and c.polls < 50, detail)
        check("the detail carries the exit code and the log", "proc.poll() = 3" in detail and "boom" in detail, detail)
    finally:
        c.stop()

print("== the tier tests start their collectors this way ==")
VERIFY = pathlib.Path(__file__).resolve().parent
for name in ("test_collector_act2_redaction_e2e.py",):
    src = (VERIFY / name).read_text()
    check(f"{name} starts its collector with otelcol_local.start and keeps no free_port() or Popen of its own",
          "otelcol_local" in src and "def free_port" not in src and "Popen" not in src)
    check(f"{name} prints the start's detail when the collector does not take the turn",
          "took the turn" in src and ".detail()" in src)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All otelcol_local start checks passed.")
