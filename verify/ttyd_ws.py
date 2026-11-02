# ABOUTME: A stdlib websocket client that speaks just enough of ttyd's "tty" protocol to test its auth (#770):
# ABOUTME: the upgrade, one first message, and what the server does next (close code, output, or silence).
"""ttyd takes its credential twice. The HTTP pages (/, /token) want Basic auth at the request, so a plain GET
answers 401. The websocket does not: the upgrade answers 101 to anyone, and the credential is the AuthToken in
the socket's first message, a JSON object ttyd compares with base64("user:password") before it spawns the
command. So a 101 on an upgrade proves nothing either way; what matters is what follows that first message.

This client opens the socket, sends one message, and reports what came back: the close code ttyd sent, any
output frames (a shell's prompt arrives as output), or nothing before the deadline. It never sends a second
message, so it never types into a shell that a broken check let it start.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import os
import socket
import ssl
import struct
import time

# ttyd 1.7 server-to-client commands: '0' output, '1' set title, '2' set preferences.
OUTPUT = ord("0")


@dataclasses.dataclass
class Result:
    status: int                 # the upgrade's HTTP status; 101 when the socket opened
    close_code: int | None      # the close frame's code, None when no close frame came
    output: bytes               # every OUTPUT frame's payload, joined
    frames: list[bytes]         # every data frame's payload, command byte included
    eof: bool                   # the server dropped the TCP connection


def auth_token(credential: str) -> str:
    """The token ttyd expects for -c user:password, the base64 its /token endpoint serves."""
    return base64.b64encode(credential.encode()).decode()


def basic(credential: str) -> str:
    return "Basic " + auth_token(credential)


def _frame(payload: bytes, opcode: int) -> bytes:
    mask = os.urandom(4)
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 1 << 16:
        head += bytes([0x80 | 126]) + struct.pack("!H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack("!Q", n)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def _read_frame(sock: socket.socket) -> tuple[int, bytes]:
    b0, b1 = _recv_exact(sock, 2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    mask = _recv_exact(sock, 4) if b1 & 0x80 else b""
    payload = _recv_exact(sock, n)
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return b0 & 0x0F, payload


def connect(host: str, port: int, path: str, *, tls: bool = False, server_name: str | None = None,
            headers: dict[str, str] | None = None, protocol: str | None = "tty",
            timeout: float = 10.0) -> tuple[socket.socket, int, bytes]:
    """Opens the upgrade, asking for `protocol` (none when None). Returns the socket, the HTTP status (0 when the
    server dropped the connection without answering) and any bytes read past the response head."""
    sock = socket.create_connection((host, port), timeout=timeout)
    if tls:
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=server_name or host)
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [f"GET {path} HTTP/1.1", f"Host: {server_name or host}", "Upgrade: websocket", "Connection: Upgrade",
             f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    if protocol is not None:
        lines.append(f"Sec-WebSocket-Protocol: {protocol}")
    lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        try:
            chunk = sock.recv(4096)
        except ConnectionError:
            break
        if not chunk:
            break
        head += chunk
    status_line = head.split(b"\r\n", 1)[0].decode(errors="replace")
    parts = status_line.split()
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    rest = head.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in head else b""
    return sock, status, rest


def first_message(host: str, port: int, path: str, message: bytes | None, *, tls: bool = False,
                  server_name: str | None = None, headers: dict[str, str] | None = None,
                  protocol: str | None = "tty", wait: float = 3.0) -> Result:
    """Opens the socket, sends `message` as its one binary frame (none when None), and listens for `wait`
    seconds. Stops early at a close frame or a dropped connection. Answers a close with a close."""
    sock, status, rest = connect(host, port, path, tls=tls, server_name=server_name, headers=headers,
                                 protocol=protocol)
    res = Result(status=status, close_code=None, output=b"", frames=[], eof=False)
    if status != 101:
        sock.close()
        return res
    if rest:
        # Bytes past the 101 head belong to the first frame; put them back in front of the stream.
        sock = _Prefixed(sock, rest)
    try:
        if message is not None:
            sock.sendall(_frame(message, 0x2))
        deadline = time.monotonic() + wait
        while (left := deadline - time.monotonic()) > 0:
            sock.settimeout(left)
            try:
                opcode, payload = _read_frame(sock)
            except (socket.timeout, TimeoutError):
                break
            except (EOFError, ConnectionError):
                res.eof = True
                break
            if opcode == 0x8:
                res.close_code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
                try:
                    sock.sendall(_frame(payload[:2], 0x8))
                except OSError:
                    pass
                break
            if opcode in (0x1, 0x2):
                res.frames.append(payload)
                if payload[:1] == bytes([OUTPUT]):
                    res.output += payload[1:]
    finally:
        sock.close()
    return res


def hello(token: str | None, columns: int = 80, rows: int = 24) -> bytes:
    """ttyd's first message: the window size and, when token is not None, the AuthToken."""
    body: dict = {"columns": columns, "rows": rows}
    if token is not None:
        body = {"AuthToken": token, **body}
    return json.dumps(body).encode()


class _Prefixed:
    """A socket whose next reads return `prefix` first."""

    def __init__(self, sock: socket.socket, prefix: bytes) -> None:
        self._sock, self._prefix = sock, prefix

    def recv(self, n: int) -> bytes:
        if self._prefix:
            out, self._prefix = self._prefix[:n], self._prefix[n:]
            return out
        return self._sock.recv(n)

    def __getattr__(self, name: str):
        return getattr(self._sock, name)
