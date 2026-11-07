# ABOUTME: Holds verify/fetch_meter.py, the proxy #1116's cold baseline counted downloads with, offline: a plain-HTTP
# ABOUTME: request and a CONNECT tunnel to a local server are logged with their bytes, a refused tunnel with its error.
"""#1115's last child compares its warm run against #1116's cold baseline, so both must count downloads the same way:
through verify/fetch_meter.py, a proxy that logs each connection's host and bytes. This holds what it logs, against a
server on 127.0.0.1 the test starts, with no network: the command it runs sees the proxy variables and NO_PROXY, its
exit code is the meter's, a plain-HTTP fetch is logged with its URL, a CONNECT tunnel with its bytes, and a tunnel to
a closed port with a 502 and the error. summary() adds the rows up by host."""
from __future__ import annotations

import http.server
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))
import fetch_meter  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


BODY = b"x" * 50_000


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]
closed = socket.socket()
closed.bind(("127.0.0.1", 0))
CLOSED = closed.getsockname()[1]
closed.close()

# The client the meter runs. It drops no_proxy, which names 127.0.0.1, so its local fetches go through the proxy.
CLIENT = f"""
import os, socket, sys, urllib.request
print("ENV", os.environ["HTTPS_PROXY"] == os.environ["HTTP_PROXY"], os.environ["NO_PROXY"])
proxy = os.environ.pop("HTTP_PROXY"); os.environ.pop("no_proxy"); os.environ.pop("NO_PROXY")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({{"http": proxy}}))
print("HTTP", len(opener.open("http://127.0.0.1:{PORT}/plain", timeout=10).read()))
host, port = proxy.rsplit(":", 1)
def tunnel(target):
    s = socket.create_connection((host.removeprefix("http://"), int(port)), timeout=10)
    s.sendall(f"CONNECT {{target}} HTTP/1.1\\r\\nHost: {{target}}\\r\\n\\r\\n".encode())
    status = s.recv(4096).split(b"\\r\\n")[0].decode()
    return s, status
s, status = tunnel("127.0.0.1:{PORT}")
s.sendall(b"GET /tunnel HTTP/1.0\\r\\n\\r\\n")
got = b""
while chunk := s.recv(65536):
    got += chunk
s.close()
print("TUNNEL", status, len(got))
s, status = tunnel("127.0.0.1:{CLOSED}")
s.close()
print("REFUSED", status)
sys.exit(3)
"""

with tempfile.TemporaryDirectory() as tmp:
    log = pathlib.Path(tmp) / "fetches.jsonl"
    r = subprocess.run([sys.executable, "-I", str(VERIFY / "fetch_meter.py"), "run", str(log), "--",
                        sys.executable, "-I", "-c", CLIENT], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=60)
    out = r.stdout
    check("the meter exits with its command's exit code", r.returncode == 3, f"rc {r.returncode}: {r.stderr[-400:]}")
    check("the command sees one proxy for HTTP and HTTPS, and NO_PROXY naming localhost",
          "ENV True localhost,127.0.0.1,::1" in out, out)
    check("a plain-HTTP fetch through the proxy reads the whole body", f"HTTP {len(BODY)}" in out, out)
    check("a CONNECT tunnel is established and carries the response", "TUNNEL HTTP/1.1 200 Connection established" in out
          and any(line.startswith("TUNNEL") and int(line.split()[-1]) > len(BODY) for line in out.splitlines()), out)
    check("a tunnel to a closed port is answered 502", "REFUSED HTTP/1.1 502 Bad Gateway" in out, out)
    rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    check("one log row per connection, three in all", len(rows) == 3, f"{rows}")
    plain = [x for x in rows if x["url"] == f"http://127.0.0.1:{PORT}/plain"]
    check("the plain-HTTP row has its URL and at least the body's bytes down",
          len(plain) == 1 and plain[0]["down"] >= len(BODY) and not plain[0]["error"], f"{plain}")
    tun = [x for x in rows if not x["url"] and x["port"] == PORT]
    check("the tunnel row has its host and port, no URL, and at least the body's bytes down",
          len(tun) == 1 and tun[0]["host"] == "127.0.0.1" and tun[0]["down"] >= len(BODY) and tun[0]["up"] > 0, f"{tun}")
    bad = [x for x in rows if x["port"] == CLOSED]
    check("the refused tunnel's row names the error and has no bytes down",
          len(bad) == 1 and bad[0]["error"] and bad[0]["down"] == 0, f"{bad}")
    if log.exists():
        s = fetch_meter.summary(str(log))
        check("summary() adds the rows up by host", s["connections"] == 3 and s["hosts"]["127.0.0.1"]["connections"] == 3
              and s["down"] == sum(x["down"] for x in rows) and s["hosts"]["127.0.0.1"]["errors"] == 1, f"{s}")

server.shutdown()
if failures:
    print(f"FAILED: {len(failures)} fetch meter check(s): {'; '.join(failures)}")
    sys.exit(1)
print("All fetch meter checks passed.")
