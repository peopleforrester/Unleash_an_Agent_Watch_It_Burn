# ABOUTME: The agent namespace's forced egress proxy (#861, option B of #724): an HTTPS CONNECT proxy that opens a
# ABOUTME: tunnel only to a named hostname on its allowlist, and refuses every other host before it resolves a name.
"""egress-proxy: the one way out of namespace `agent` on 443.

Challenge 1's egress policy drops every direct path to the internet from `agent`. What still has to leave, C7's
weather feed reaching Open-Meteo, leaves through this proxy, and the proxy decides on the hostname the client asks
for. A NetworkPolicy matches addresses and ports and cannot read a name, which is the gap the beat shows; this is
the half of the fix that reads names for HTTPS.

What it does, and nothing more:
- `CONNECT host:port` opens a TCP tunnel when `host` is exactly a name on ALLOWED_HOSTS and `port` is on
  ALLOWED_PORTS. The check runs on the name the client sent, before any lookup, so a refused name is never
  resolved and never reaches a DNS server through this pod. An address literal is refused: the allowlist is names.
- `GET /healthz` answers 200, for the kubelet's probes.
- Anything else is refused with 403. Plain-HTTP forwarding is not offered, so there is no second path to reason
  about.

Each decision is logged as one JSON line (event egress_allow or egress_deny, host, port, reason), so the room can
watch the agent's refused attempts in the pod's log and in Datadog.

Settings, read once at start: ALLOWED_HOSTS (comma-separated names, required), ALLOWED_PORTS (comma-separated,
default 443), LISTEN_PORT (default 3128). None is named EGRESS_PROXY_*, which the Service's injected links would set.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import sys

HEAD_LIMIT = 8192
HEAD_TIMEOUT = 10
CONNECT_TIMEOUT = 10

log = logging.getLogger("egress-proxy")


def parse_set(raw: str) -> frozenset[str]:
    return frozenset(p.strip().lower().rstrip(".") for p in raw.split(",") if p.strip())


def normalize(host: str) -> str:
    """The name as the allowlist compares it: lower case, no trailing root dot, no IPv6 brackets."""
    return host.strip().lower().rstrip(".").removeprefix("[").removesuffix("]")


def is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def decide(host: str, port: str, hosts: frozenset[str], ports: frozenset[str]) -> str:
    """The reason a CONNECT is refused, or "" when it is allowed. Exact names only: no suffix or wildcard match."""
    if not host:
        return "no host"
    if is_address(host):
        return "address literal"
    if host not in hosts:
        return "host not on the allowlist"
    if port not in ports:
        return "port not allowed"
    return ""


def record(event: str, host: str, port: str, reason: str = "") -> None:
    line = {"event": event, "host": host, "port": port}
    if reason:
        line["reason"] = reason
    log.info(json.dumps(line, sort_keys=True))


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001 - the socket may already be gone; closing is best effort here
            pass


async def reply(writer: asyncio.StreamWriter, status: str, body: str = "") -> None:
    payload = body.encode()
    writer.write(f"HTTP/1.1 {status}\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode() + payload)
    await writer.drain()
    writer.close()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 hosts: frozenset[str], ports: frozenset[str]) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
        writer.close()
        return
    parts = head.split(b"\r\n", 1)[0].decode("latin-1").split()
    method, target = (parts[0].upper(), parts[1]) if len(parts) >= 2 else ("", "")
    if method == "GET" and target == "/healthz":
        await reply(writer, "200 OK", "ok\n")
        return
    if method != "CONNECT":
        record("egress_deny", target[:200], "", "only CONNECT is proxied")
        await reply(writer, "403 Forbidden", "egress-proxy: only CONNECT to an allowed host\n")
        return
    raw_host, _, port = target.rpartition(":")
    host = normalize(raw_host)
    reason = decide(host, port, hosts, ports)
    if reason:
        record("egress_deny", host[:253], port, reason)
        await reply(writer, "403 Forbidden", f"egress-proxy: {reason}\n")
        return
    try:
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), CONNECT_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as e:
        record("egress_deny", host, port, f"upstream unreachable: {type(e).__name__}")
        await reply(writer, "502 Bad Gateway", "egress-proxy: upstream unreachable\n")
        return
    record("egress_allow", host, port)
    writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await writer.drain()
    await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


async def serve(hosts: frozenset[str], ports: frozenset[str], listen_port: int) -> None:
    server = await asyncio.start_server(lambda r, w: handle(r, w, hosts, ports), "0.0.0.0", listen_port,
                                        limit=HEAD_LIMIT)
    log.info(json.dumps({"event": "egress_proxy_start", "hosts": sorted(hosts), "ports": sorted(ports),
                         "listen": listen_port}))
    async with server:
        await server.serve_forever()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    hosts = parse_set(os.environ.get("ALLOWED_HOSTS", ""))
    if not hosts:
        log.error("ALLOWED_HOSTS is empty: the proxy would refuse everything, which is a misconfiguration")
        return 2
    ports = parse_set(os.environ.get("ALLOWED_PORTS", "443"))
    asyncio.run(serve(hosts, ports, int(os.environ.get("LISTEN_PORT", "3128"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
