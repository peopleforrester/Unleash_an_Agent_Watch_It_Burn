# ABOUTME: Offline check of test_public_images_served.py's retries: its opened() helper is lifted out of the file and
# ABOUTME: run against a stubbed urlopen and sleep: a 429 or no answer is retried, boundedly, and other errors are not.
# ABOUTME: A resolver failure is a network failure: a temporary one is retried, any other raises Unreachable (#1029).
"""The tools-tier test reads public.ecr.aws anonymously, whose budget is about one request a second per source
address. This host runs other runs' suites from the same address, so run 16863 met a 429 on busybox's first manifest
and went green on a rerun (#844). Run 17813 met one TLS handshake to the token endpoint that timed out, and went green
on a rerun (#976). Run 17937 met one temporary failure in name resolution, read as an image that does not pull,
and passed alone twice (#1029). The fix retries a 429, and a timeout or dropped connection, each a bounded number of times; when no
try gets an answer it raises Unreachable, naming the registry. This holds that without the network: the helpers are
taken from the file by name, so what runs here is the code the tier test runs.
"""
from __future__ import annotations

import ast
import email.message
import http.client
import pathlib
import socket
import ssl
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC_PATH = REPO / "verify/test_public_images_served.py"
SRC = SRC_PATH.read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


# The names this lifts out of the file are checked first, so a rename reads as that and not as a broken check.
LIFTED = ("REGISTRY", "RETRIES_ON_429", "RETRIES_ON_NO_ANSWER", "NO_ANSWER_WAIT", "Unreachable", "reason_of",
          "unresolved", "no_answer", "opened", "token")
tree = ast.parse(SRC)
nodes = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
nodes.update({t.id: n for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)})
missing = [name for name in (*LIFTED, "unreachable") if name not in nodes]
if missing:
    print(f"FAILED: {SRC_PATH.relative_to(REPO)} has no top-level {', '.join(missing)} to lift out")
    sys.exit(1)
check("the tier test's token, fetch and blob all read through opened(), its one urlopen",
      "raw = opened(req)" in SRC and "return json.loads(opened(req))" in SRC
      and "opened(" in ast.get_source_segment(SRC, nodes["token"])
      and "urllib.request.urlopen(req" in ast.get_source_segment(SRC, nodes["opened"])
      and SRC.count("urlopen(") == 1)
check("an Unreachable fails the tier test on its own, naming the registry, from the token and from the image loop",
      SRC.count("except Unreachable as e:\n    unreachable(e)") == 2
      and "is unreachable from this host" in ast.get_source_segment(SRC, nodes["unreachable"]))


class _Resp:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:
        return self.body


def _err(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://public.ecr.aws/v2/x/manifests/y", code, "stub", h, None)


def run(script: list, call: str = "opened") -> tuple[object, list[float], int]:
    """Run opened(), or token(), against a urlopen that answers each item of script in turn: bytes, or an error to
    raise. What it returns, or the exception it raises, comes back with the sleeps and the number of urlopen calls."""
    calls = {"n": 0}
    sleeps: list[float] = []

    def urlopen(req, timeout=None):
        item = script[calls["n"]]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return _Resp(item)

    fake_urllib = type("U", (), {})()
    fake_urllib.request = type("R", (), {"urlopen": staticmethod(urlopen), "Request": urllib.request.Request})
    fake_urllib.error = urllib.error
    ns = {"urllib": fake_urllib, "json": __import__("json"), "socket": socket,
          "time": type("T", (), {"sleep": staticmethod(sleeps.append)})}
    for name in LIFTED:
        exec(compile(ast.Module(body=[nodes[name]], type_ignores=[]), str(SRC_PATH), "exec"), ns)
    try:
        if call == "token":
            out: object = ns["token"]()
        else:
            out = ns["opened"](urllib.request.Request("https://public.ecr.aws/v2/x/manifests/y"))
    except Exception as e:  # noqa: BLE001  every error comes back to be checked by type
        out = e
    return out, sleeps, calls["n"]


def handshake_timeout() -> urllib.error.URLError:
    """What run 17813 met: urlopen wraps the handshake's TimeoutError in a URLError."""
    return urllib.error.URLError(TimeoutError("_ssl.c:1012: The handshake operation timed out"))


print("== a rate-limited anonymous pull is retried; a 404 is not (#844, run 16863) ==")
out, sleeps, n = run([_err(429), _err(429), b"manifest"])
check("two 429s then an answer returns the answer", out == b"manifest" and n == 3, f"{out!r} after {n} calls")
check("and waits 2 s then 4 s between them, with no Retry-After", sleeps == [2, 4], str(sleeps))

out, sleeps, n = run([_err(429, "3"), b"manifest"])
check("a Retry-After is honoured", out == b"manifest" and sleeps == [3], str(sleeps))
out, sleeps, n = run([_err(429, "3600"), b"manifest"])
check("and capped at 30 s, so a long one cannot stall the tier", sleeps == [30], str(sleeps))

out, sleeps, n = run([_err(429)] * 5 + [b"never read"])
check("five 429s in a row still fail, after four waits", isinstance(out, urllib.error.HTTPError) and out.code == 429
      and n == 5 and sleeps == [2, 4, 8, 16], f"{out!r}, {n} calls, {sleeps}")

out, sleeps, n = run([_err(404), b"never read"])
check("a 404 fails at once, with no retry and no wait",
      isinstance(out, urllib.error.HTTPError) and out.code == 404 and n == 1 and sleeps == [], f"{n} calls, {sleeps}")

print("\n== no answer at all is retried, boundedly, and then fails naming the registry (#976, run 17813) ==")
out, sleeps, n = run([handshake_timeout(), b'{"token": "t"}'], call="token")
check("one handshake timeout on the token, then an answer, returns the token",
      out == "t" and n == 2 and sleeps == [5], f"{out!r} after {n} calls, {sleeps}")
out, sleeps, n = run([TimeoutError("The read operation timed out"), b"manifest"])
check("a bare read timeout is retried", out == b"manifest" and n == 2 and sleeps == [5], f"{out!r}, {sleeps}")
out, sleeps, n = run([ConnectionResetError(104, "reset"), http.client.RemoteDisconnected("closed"), b"manifest"])
check("a reset and a dropped connection are retried", out == b"manifest" and n == 3 and sleeps == [5, 5],
      f"{out!r}, {sleeps}")
out, sleeps, n = run([urllib.error.URLError(ConnectionRefusedError(111, "refused")), b"manifest"])
check("a refused connect is retried", out == b"manifest" and n == 2, f"{out!r}, {n} calls")

out, sleeps, n = run([handshake_timeout()] * 3 + [b"never read"], call="token")
check("three handshake timeouts in a row raise Unreachable, after two waits",
      type(out).__name__ == "Unreachable" and n == 3 and sleeps == [5, 5], f"{out!r}, {n} calls, {sleeps}")
check("and it names the registry, the URL, the tries and the last error",
      all(w in str(out) for w in ("public.ecr.aws gave no answer to https://public.ecr.aws/token/", "on 3 tries",
                                   "The handshake operation timed out")), str(out))
check("Unreachable is no URLError, so the per-image checks do not catch it as an image that is not served",
      not isinstance(out, OSError))

out, sleeps, n = run([TimeoutError("t"), _err(429), TimeoutError("t"), _err(429), b"manifest"])
check("timeouts and 429s each keep their own budget", out == b"manifest" and n == 5 and sleeps == [5, 2, 5, 4],
      f"{out!r}, {n} calls, {sleeps}")

def resolver(code: int, text: str) -> urllib.error.URLError:
    """What urlopen raises when getaddrinfo fails: the socket.gaierror as a URLError's reason."""
    return urllib.error.URLError(socket.gaierror(code, text))


print("\n== a resolver failure is a network failure, never an image that is not served (#1029, run 17937) ==")
blip = resolver(socket.EAI_AGAIN, "Temporary failure in name resolution")
out, sleeps, n = run([blip, b"manifest"])
check("one temporary failure in name resolution, then an answer, returns the answer",
      out == b"manifest" and n == 2 and sleeps == [5], f"{out!r} after {n} calls, {sleeps}")
out, sleeps, n = run([blip, b'{"token": "t"}'], call="token")
check("and on the token as well", out == "t" and n == 2 and sleeps == [5], f"{out!r} after {n} calls, {sleeps}")
out, sleeps, n = run([socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution"), b"manifest"])
check("a bare temporary resolver failure is retried", out == b"manifest" and n == 2, f"{out!r}, {n} calls")
out, sleeps, n = run([blip] * 3 + [b"never read"])
check("three in a row raise Unreachable, after two waits, naming the resolver's error",
      type(out).__name__ == "Unreachable" and n == 3 and sleeps == [5, 5]
      and all(w in str(out) for w in ("public.ecr.aws gave no answer to", "on 3 tries",
                                       "Temporary failure in name resolution")), f"{out!r}, {n} calls, {sleeps}")
for code, text in ((socket.EAI_NONAME, "Name or service not known"), (socket.EAI_FAIL, "Non-recoverable failure")):
    no_name = resolver(code, text)
    out, sleeps, n = run([no_name, b"never read"])
    check(f"a resolver's {text!r} raises Unreachable at once, with no retry and no wait",
          type(out).__name__ == "Unreachable" and out.__cause__ is no_name and n == 1 and sleeps == []
          and all(w in str(out) for w in ("public.ecr.aws's name did not resolve on this host",
                                           "https://public.ecr.aws/v2/x/manifests/y", text)),
          f"{out!r}, {n} calls, {sleeps}")
check("so the per-image checks, which catch URLError, never see a resolver failure",
      type(out).__name__ == "Unreachable" and not isinstance(out, OSError))

print("\n== what the registry did answer, or the host refused, is not retried ==")
bad_cert = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))
out, sleeps, n = run([bad_cert, b"never read"])
check("a certificate the host cannot verify fails at once", out is bad_cert and n == 1 and sleeps == [],
      f"{out!r}, {n} calls")
refused_tls = urllib.error.URLError(ssl.SSLError(1, "wrong version number"))
out, sleeps, n = run([refused_tls, b"never read"])
check("a TLS error that is no timeout fails at once", out is refused_tls and n == 1 and sleeps == [],
      f"{out!r}, {n} calls")
out, sleeps, n = run([_err(404), b"never read"], call="token")
check("a 404 on the token fails at once", isinstance(out, urllib.error.HTTPError) and n == 1 and sleeps == [],
      f"{out!r}, {n} calls")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("A 429, no answer or a temporary resolver failure from public.ecr.aws is retried, boundedly; an unreachable "
      "or unresolved registry fails naming it.")
