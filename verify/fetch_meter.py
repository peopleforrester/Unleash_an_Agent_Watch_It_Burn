#!/usr/bin/env python3
# ABOUTME: A logging HTTP(S) proxy that meters what a command downloads (#1116): one JSON line per connection with
# ABOUTME: the host, the bytes each way and the seconds, so a run's fetches can be counted and summed by host.
"""Meter the network fetches of a command.

    python3 verify/fetch_meter.py run LOG -- CMD...   start the proxy, run CMD with HTTP(S)_PROXY set to it, stop it
    python3 verify/fetch_meter.py summary LOG          the connections and bytes in LOG, by host

`run` listens on 127.0.0.1 on a free port and exports HTTPS_PROXY, HTTP_PROXY (both cases) and NO_PROXY for
localhost to CMD, so curl, terraform, helm, uv, pip, git, Playwright and anything else that honors the proxy
variables reach the network through it. A CONNECT is tunnelled as is: the proxy sees the host and the byte counts,
never the URL or the payload, and terminates no TLS. A plain-HTTP request is forwarded with its URL logged. Each
connection, when it closes, appends {"start", "end", "host", "port", "url", "up", "down", "error"} to LOG.

A process that clears its environment, or a client that ignores the proxy variables (Node's fetch without
NODE_USE_ENV_PROXY), is not metered: the count is a floor, and `summary` says so.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

BUF = 1 << 16


class Meter:
    def __init__(self, log_path: str):
        self.log = open(log_path, "a", encoding="utf-8", buffering=1)

    def record(self, **row) -> None:
        self.log.write(json.dumps(row, sort_keys=True) + "\n")

    async def pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, counter: list[int]) -> None:
        try:
            while True:
                chunk = await reader.read(BUF)
                if not chunk:
                    break
                counter[0] += len(chunk)
                writer.write(chunk)
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except (ConnectionError, OSError):
                pass

    async def handle(self, creader: asyncio.StreamReader, cwriter: asyncio.StreamWriter) -> None:
        start = time.time()
        host, port, url, error = "", 0, "", ""
        up, down = [0], [0]
        try:
            head = await creader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            cwriter.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        method, target, version = (lines[0].split(" ") + ["", "", ""])[:3]
        try:
            if method == "CONNECT":
                host, _, p = target.rpartition(":")
                host, port = host.strip("[]"), int(p or 443)
                sreader, swriter = await asyncio.open_connection(host, port)
                cwriter.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await cwriter.drain()
                await asyncio.gather(self.pipe(creader, swriter, up), self.pipe(sreader, cwriter, down))
            elif target.startswith("http://"):
                url = target
                rest = target[len("http://"):]
                hostport, _, path = rest.partition("/")
                host, _, p = hostport.rpartition(":") if ":" in hostport else (hostport, "", "80")
                port = int(p or 80)
                sreader, swriter = await asyncio.open_connection(host, port)
                first = f"{method} /{path} {version}\r\n".encode("latin-1")
                swriter.write(first + "\r\n".join(lines[1:]).encode("latin-1"))
                up[0] += len(head)
                await swriter.drain()
                await asyncio.gather(self.pipe(creader, swriter, up), self.pipe(sreader, cwriter, down))
            else:
                error = f"not a proxy request: {lines[0][:120]}"
                cwriter.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                await cwriter.drain()
                cwriter.close()
        except (OSError, ValueError) as e:
            error = f"{type(e).__name__}: {e}"
            try:
                cwriter.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                await cwriter.drain()
                cwriter.close()
            except (ConnectionError, OSError):
                pass
        self.record(start=round(start, 3), end=round(time.time(), 3), host=host, port=port, url=url,
                    up=up[0], down=down[0], error=error)


async def serve(log_path: str, ready: asyncio.Future) -> None:
    meter = Meter(log_path)
    server = await asyncio.start_server(meter.handle, "127.0.0.1", 0, limit=1 << 20)
    ready.set_result(server.sockets[0].getsockname()[1])
    async with server:
        await server.serve_forever()


def proxy_env(port: int, base: dict[str, str]) -> dict[str, str]:
    env = dict(base)
    url = f"http://127.0.0.1:{port}"
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        env[k] = url
    no = "localhost,127.0.0.1,::1"
    env["NO_PROXY"] = env["no_proxy"] = no
    return env


async def run(log_path: str, cmd: list[str]) -> int:
    loop = asyncio.get_running_loop()
    ready: asyncio.Future = loop.create_future()
    task = asyncio.create_task(serve(log_path, ready))
    port = await ready
    print(f"fetch_meter: proxy on 127.0.0.1:{port}, logging to {log_path}", file=sys.stderr, flush=True)
    proc = await asyncio.create_subprocess_exec(*cmd, env=proxy_env(port, dict(os.environ)))
    rc = await proc.wait()
    task.cancel()
    return rc


def summary(log_path: str) -> dict:
    rows = [json.loads(line) for line in open(log_path, encoding="utf-8") if line.strip()]
    by_host: dict[str, dict] = {}
    for r in rows:
        h = by_host.setdefault(r["host"] or "(none)", {"connections": 0, "down": 0, "up": 0, "errors": 0})
        h["connections"] += 1
        h["down"] += r["down"]
        h["up"] += r["up"]
        h["errors"] += bool(r["error"])
    return {"connections": len(rows), "down": sum(r["down"] for r in rows), "hosts": by_host}


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[1] == "run" and argv[3] == "--":
        return asyncio.run(run(argv[2], argv[4:]))
    if len(argv) == 3 and argv[1] == "summary":
        s = summary(argv[2])
        for host, h in sorted(s["hosts"].items(), key=lambda kv: -kv[1]["down"]):
            print(f"{h['down']:>14,d} B  {h['connections']:>5d} conn  {h['errors']:>3d} err  {host}")
        print(f"{s['down']:>14,d} B  {s['connections']:>5d} conn  in all (a floor: unmetered clients are not here)")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
