# ABOUTME: Holds that verify/weather_feed_probe.py imports with nothing started (#1019, from #982): no socket, DNS,
# ABOUTME: urlopen, subprocess or thread, and no weather feed, and that its formatter and helper answer offline.
"""Offline check for #982's criterion that the probe's helper and formatter import without the feed or the network.

verify/test_weather_feed_e2e.py imports `request`, `error_field` and `failure_line` from verify/weather_feed_probe.py,
whose ABOUTME says importing it starts nothing. This test holds that:

1. Every top-level statement of the probe is a docstring, an import, a def, a class or an assignment with no call
   in it, so nothing runs when it is imported.
2. The probe is loaded with socket creation, connects, DNS lookups, urlopen, subprocesses and thread starts all
   replaced by guards that record the call and raise. The load must record none of them, and must not import
   gitops/ai-layer/weather_feed.py, http.server or any other file from this repo.
3. With the guards still on, `error_field` and `failure_line` are called on fixed replies, one per branch, and each
   printed line is held to the exact text. They must open nothing.
4. `request` is called with only urlopen stubbed (the socket guards stay on): a 200, an HTTP 502 with the feed's
   JSON error, a non-JSON error body, and a refused connection. Each makes exactly one urlopen call, never raises,
   and returns the status, the body and a non-negative elapsed time.

Every literal this test reads in the probe is checked to be there first.
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import pathlib
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
PROBE_PY = VERIFY / "weather_feed_probe.py"
FEED_PY = REPO / "gitops/ai-layer/weather_feed.py"

ANCHORS = [
    "importing it starts nothing",
    "def request(url: str, timeout: float = 20) -> Reply:",
    "with urllib.request.urlopen(url, timeout=timeout) as r:",
    "def error_field(body: Body, limit: int = 300) -> str:",
    "def failure_line(what: str, reply: Reply, expected: int = 200) -> str:",
    'status = "no HTTP answer" if reply.status is None else f"HTTP {reply.status}"',
    'text = body.strip() or "<empty body>"',
    'text = f"<no error field in {json.dumps(body)}>"',
]
probe_text = PROBE_PY.read_text()
for lit in ANCHORS:
    if lit not in probe_text:
        print(f"FAILED: the literal {lit!r} is not in {PROBE_PY.relative_to(REPO)}; this test reads it, so it "
              "changes with that file")
        sys.exit(1)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# 1. Nothing runs at module level.
print("== the probe's top level only defines ==")


def has_call(node: ast.AST) -> bool:
    return any(isinstance(n, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom)) for n in ast.walk(node))


tree = ast.parse(probe_text, filename=str(PROBE_PY))
runs: list[str] = []
for i, stmt in enumerate(tree.body):
    if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
            and isinstance(stmt.value.value, str):
        continue
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        continue
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        # Decorators, defaults and base classes run at import; bodies do not.
        at_import = [*stmt.decorator_list]
        if isinstance(stmt, ast.ClassDef):
            at_import += [*stmt.bases, *(k.value for k in stmt.keywords)]
            # A class body runs at import: it may hold a docstring, annotations without values and defs only.
            for s in stmt.body:
                if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
                    continue
                if isinstance(s, ast.AnnAssign) and s.value is None:
                    continue
                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    at_import += [*s.decorator_list, *s.args.defaults, *(d for d in s.args.kw_defaults if d)]
                    continue
                runs.append(f"line {s.lineno}: {ast.unparse(s)[:80]}")
        else:
            at_import += [*stmt.args.defaults, *(d for d in stmt.args.kw_defaults if d)]
        runs += [f"line {n.lineno}: {ast.unparse(n)[:80]}" for n in at_import if has_call(n)]
        continue
    if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None and not has_call(stmt.value):
        continue
    runs.append(f"line {stmt.lineno}: {ast.unparse(stmt)[:80]}")
check("every top-level statement is a docstring, import, def, class or call-free assignment", not runs,
      "; ".join(runs))
check("the probe has no `if __name__` entry point to run", "__main__" not in probe_text)


# 2. The import, under guards.
class Opened(Exception):
    """Raised by a guard: the probe reached for the network, a process or a thread."""


opened: list[str] = []


def guard(what: str):
    def refuse(*args, **kwargs):
        opened.append(what)
        raise Opened(what)
    return refuse


class GuardedSocket(socket.socket):
    def __init__(self, *args, **kwargs) -> None:
        opened.append("socket.socket()")
        raise Opened("socket.socket()")


saved = {
    (socket, "socket"): socket.socket,
    (socket, "create_connection"): socket.create_connection,
    (socket, "getaddrinfo"): socket.getaddrinfo,
    (socket, "gethostbyname"): socket.gethostbyname,
    (urllib.request, "urlopen"): urllib.request.urlopen,
    (subprocess, "Popen"): subprocess.Popen,
    (threading.Thread, "start"): threading.Thread.start,
}
guards = {
    (socket, "socket"): GuardedSocket,
    (socket, "create_connection"): guard("socket.create_connection"),
    (socket, "getaddrinfo"): guard("socket.getaddrinfo"),
    (socket, "gethostbyname"): guard("socket.gethostbyname"),
    (urllib.request, "urlopen"): guard("urllib.request.urlopen"),
    (subprocess, "Popen"): guard("subprocess.Popen"),
    (threading.Thread, "start"): guard("threading.Thread.start"),
}


def guards_on() -> None:
    for (owner, name), fn in guards.items():
        setattr(owner, name, fn)


def guards_off() -> None:
    for (owner, name), fn in saved.items():
        setattr(owner, name, fn)


print("== importing the probe opens nothing ==")
modules_before = set(sys.modules)
threads_before = threading.active_count()
guards_on()
try:
    spec = importlib.util.spec_from_file_location("weather_feed_probe_under_test", PROBE_PY)
    probe = importlib.util.module_from_spec(spec)
    load_error = ""
    try:
        spec.loader.exec_module(probe)
    except Exception as e:  # noqa: BLE001 (the error is the check's detail)
        load_error = f"{type(e).__name__}: {e}"
    check("the probe loads with sockets, DNS, urlopen, subprocesses and threads guarded", not load_error, load_error)
    check("and the load opened none of them", not opened, str(opened))
    check("no thread was started", threading.active_count() == threads_before,
          f"{threads_before} -> {threading.active_count()}")
    new = set(sys.modules) - modules_before
    repo_files = sorted(str(pathlib.Path(f).resolve().relative_to(REPO)) for m in new
                        if (f := getattr(sys.modules[m], "__file__", None))
                        and pathlib.Path(f).resolve().is_relative_to(REPO))
    check("the load imported no file from this repo (the weather feed included)", not repo_files, str(repo_files))
    feed_loaded = [m for m, mod in list(sys.modules.items())
                   if getattr(mod, "__file__", None) and pathlib.Path(mod.__file__).resolve() == FEED_PY]
    check("gitops/ai-layer/weather_feed.py is not loaded", not feed_loaded, str(feed_loaded))
    check("http.server, which serves the feed, is not imported", "http.server" not in new)
    if load_error:
        guards_off()
        print(f"\nFAILED: {len(failures)} check(s)")
        sys.exit(1)

    # 3. The formatter, still under guards.
    print("== error_field and failure_line answer offline ==")
    Reply = probe.Reply
    what = "/current for Salt Lake City"
    long_err = "x" * 301
    CASES = [
        ("a 502 with the feed's error field",
         probe.failure_line(what, Reply(502, {"error": "weather service unavailable: <urlopen error timed out>"},
                                        0.031)),
         "/current for Salt Lake City: HTTP 502 (expected 200) after 0.03 s; "
         "error: weather service unavailable: <urlopen error timed out>"),
        ("no HTTP answer at all",
         probe.failure_line(what, Reply(None, "URLError: [Errno 111] Connection refused", 0.0012)),
         "/current for Salt Lake City: no HTTP answer (expected 200) after 0.00 s; "
         "error: URLError: [Errno 111] Connection refused"),
        ("a 200 when a 404 was expected, with no error field",
         probe.failure_line("/current for Nowhere", Reply(200, {"place": "Nowhere", "temp_c": 1}, 1.5), expected=404),
         '/current for Nowhere: HTTP 200 (expected 404) after 1.50 s; '
         'error: <no error field in {"place": "Nowhere", "temp_c": 1}>'),
        ("a list body", probe.error_field([1, 2]), "<no error field in [1, 2]>"),
        ("an empty text body", probe.error_field("  \n"), "<empty body>"),
        ("a text body, stripped", probe.error_field("  Bad Gateway\n"), "Bad Gateway"),
        ("an error field that is not a string", probe.error_field({"error": True}), "True"),
        ("an error of exactly 300 characters, kept whole", probe.error_field({"error": "y" * 300}), "y" * 300),
        ("an error over 300 characters, cut with ...", probe.error_field({"error": long_err}), "x" * 300 + "..."),
        ("a limit passed in", probe.error_field("abcdef", limit=3), "abc..."),
    ]
    for name, got, want in CASES:
        check(f"{name}: {want[:70]!r}", got == want, f"got {got!r}")
    check("the formatter opened nothing", not opened, str(opened))

    # 4. The helper, with urlopen stubbed and the socket guards still on.
    print("== request makes one call and never raises ==")

    class Answer(io.BytesIO):
        def __init__(self, status: int, raw: bytes) -> None:
            super().__init__(raw)
            self.status = status

    def http_error(code: int, raw: bytes) -> urllib.error.HTTPError:
        return urllib.error.HTTPError("http://feed.test/current", code, "err", {}, io.BytesIO(raw))

    feed_error = {"error": "weather service unavailable: HTTP Error 503: Service Unavailable"}
    REQUESTS = [
        ("a 200 with a JSON reading", Answer(200, b'{"place": "Salt Lake City", "temp_c": 4.2}'),
         200, {"place": "Salt Lake City", "temp_c": 4.2}),
        ("a 502 with the feed's JSON error", http_error(502, json.dumps(feed_error).encode()), 502, feed_error),
        ("a 502 whose body is not JSON", http_error(502, b"<html>Bad Gateway</html>"), 502,
         "<html>Bad Gateway</html>"),
        ("a refused connection", urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")), None,
         "URLError: [Errno 111] Connection refused"),
        ("a timeout", TimeoutError("timed out"), None, "TimeoutError: timed out"),
    ]
    for name, answer, status, body in REQUESTS:
        calls: list[tuple[str, float]] = []

        def stub(url, timeout=None, _answer=answer):
            calls.append((url, timeout))
            if isinstance(_answer, BaseException):
                raise _answer
            return _answer

        urllib.request.urlopen = stub
        raised = ""
        try:
            reply = probe.request("http://feed.test/current?city=Salt+Lake+City", timeout=7)
        except BaseException as e:  # noqa: BLE001 (the error is the check's detail)
            raised, reply = f"{type(e).__name__}: {e}", None
        urllib.request.urlopen = guards[(urllib.request, "urlopen")]
        check(f"{name}: request does not raise", not raised, raised)
        if reply is None:
            continue
        check(f"{name}: exactly one urlopen call, with the url and timeout given",
              calls == [("http://feed.test/current?city=Salt+Lake+City", 7)], str(calls))
        check(f"{name}: status {status}", reply.status == status, f"got {reply.status!r}")
        check(f"{name}: the body is kept", reply.body == body, f"got {reply.body!r}")
        check(f"{name}: a non-negative elapsed time", isinstance(reply.elapsed, float) and reply.elapsed >= 0,
              repr(reply.elapsed))
    check("request reached nothing past the stub", not opened, str(opened))
finally:
    guards_off()

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All weather feed probe offline checks passed.")
