# ABOUTME: Runs gitops/ai-layer/egress_proxy.py on localhost (#861) and holds what it decides: a tunnel to an allowed
# ABOUTME: name, 403 for any other name, an address literal, another port or a plain request, and no lookup on refusal.
"""Offline checks for the forced egress proxy, option B of the #724 decision.

The proxy is the one way out of namespace `agent` on 443, so what it opens is the control. This starts the real
script as a subprocess, with an allowlist of `localhost` and the port of a local echo server standing in for an
Open-Meteo host, and speaks CONNECT to it over a socket. Nothing leaves the machine: every name tried is either
localhost or one the proxy must refuse before it resolves it.

"Refused before it resolves" is checked with names under `.invalid`, which RFC 6761 reserves so that no resolver
answers them: an allowed name that cannot resolve gets 502, so a 403 for such a name shows the decision came first.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
PROXY = REPO / "gitops/ai-layer/egress_proxy.py"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def echo_server() -> int:
    """A one-thread-per-connection echo server on localhost, the stand-in for an allowed upstream."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()

    def serve() -> None:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=lambda c=conn: [c.sendall(d) for d in iter(lambda: c.recv(4096), b"")],
                             daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


def ask(port: int, head: str, then: bytes = b"") -> tuple[str, bytes]:
    """Send one request head to the proxy; return its status line and, after a 200, the echo of `then`."""
    with socket.create_connection(("127.0.0.1", port), timeout=15) as s:
        s.sendall(head.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        status, _, rest = buf.partition(b"\r\n")
        body = rest.partition(b"\r\n\r\n")[2]
        if then and status.split()[1:2] == [b"200"]:
            s.sendall(then)
            got = body
            while len(got) < len(then):
                chunk = s.recv(4096)
                if not chunk:
                    break
                got += chunk
            return status.decode(), got
        return status.decode(), body


upstream = echo_server()
proxy_port = free_port()
env = dict(os.environ, ALLOWED_HOSTS="localhost,nowhere.invalid", ALLOWED_PORTS=str(upstream),
           LISTEN_PORT=str(proxy_port))
proc = subprocess.Popen([sys.executable, "-I", str(PROXY)], env=env, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True)
try:
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", proxy_port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        check("the proxy starts and listens", False, "no listener after 10s")

    print("== an allowed name gets a tunnel ==")
    status, echoed = ask(proxy_port, f"CONNECT localhost:{upstream} HTTP/1.1\r\nHost: localhost\r\n\r\n", b"hello")
    check("CONNECT to an allowed host and port answers 200", status.startswith("HTTP/1.1 200"), status)
    check("and the tunnel carries bytes both ways", echoed == b"hello", repr(echoed))
    status, _ = ask(proxy_port, f"CONNECT LOCALHOST.:{upstream} HTTP/1.1\r\n\r\n", b"x")
    check("the name is compared case-blind and without the root dot", status.startswith("HTTP/1.1 200"), status)

    print("== every other request is refused ==")
    for label, head in [
        ("a name not on the list", f"CONNECT agenticburn.com:{upstream} HTTP/1.1\r\n\r\n"),
        ("a subdomain of an allowed name", f"CONNECT x.localhost:{upstream} HTTP/1.1\r\n\r\n"),
        ("an allowed name inside a longer one", f"CONNECT localhost.evil.invalid:{upstream} HTTP/1.1\r\n\r\n"),
        ("an IPv4 address literal", f"CONNECT 127.0.0.1:{upstream} HTTP/1.1\r\n\r\n"),
        ("an IPv6 address literal", f"CONNECT [::1]:{upstream} HTTP/1.1\r\n\r\n"),
        ("an allowed name on another port", f"CONNECT localhost:{proxy_port} HTTP/1.1\r\n\r\n"),
        ("a plain-HTTP request", "GET http://localhost/ HTTP/1.1\r\nHost: localhost\r\n\r\n"),
        ("a POST", "POST /beacon HTTP/1.1\r\nHost: agenticburn.com\r\nContent-Length: 0\r\n\r\n"),
    ]:
        status, _ = ask(proxy_port, head)
        check(f"{label} gets 403", status.startswith("HTTP/1.1 403"), status)

    print("== the decision comes before any lookup ==")
    status, _ = ask(proxy_port, f"CONNECT data-carrying-label.not-listed.invalid:{upstream} HTTP/1.1\r\n\r\n")
    check("an unlisted name that no resolver answers gets 403, not 502", status.startswith("HTTP/1.1 403"), status)
    status, _ = ask(proxy_port, f"CONNECT nowhere.invalid:{upstream} HTTP/1.1\r\n\r\n")
    check("while a listed name that cannot resolve gets 502, so 403 is the allowlist's answer",
          status.startswith("HTTP/1.1 502"), status)

    print("== the probe path ==")
    status, body = ask(proxy_port, "GET /healthz HTTP/1.1\r\n\r\n")
    check("GET /healthz answers 200", status.startswith("HTTP/1.1 200") and body.startswith(b"ok"), status)
finally:
    proc.terminate()
    out, _ = proc.communicate(timeout=10)

print("== it logs each decision as one JSON line ==")
lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
events = [(d.get("event"), d.get("host")) for d in lines]
check("the start line names the allowlist", any(d.get("event") == "egress_proxy_start"
                                                and d.get("hosts") == ["localhost", "nowhere.invalid"] for d in lines))
check("an allowed tunnel is logged egress_allow", ("egress_allow", "localhost") in events)
check("a refused name is logged egress_deny with the name", ("egress_deny", "agenticburn.com") in events)
check("and with its reason", any(d.get("host") == "agenticburn.com" and d.get("reason") == "host not on the allowlist"
                                 for d in lines))

print("== an empty allowlist is a startup error, not a proxy that refuses everything ==")
bad = subprocess.run([sys.executable, "-I", str(PROXY)], env=dict(os.environ, ALLOWED_HOSTS="", LISTEN_PORT="0"),
                     capture_output=True, text=True, timeout=20)
check("it exits 2 and says why", bad.returncode == 2 and "ALLOWED_HOSTS is empty" in bad.stdout + bad.stderr,
      f"exit {bad.returncode}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All egress proxy checks passed.")
