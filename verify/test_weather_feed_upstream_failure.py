# ABOUTME: Serves the real weather feed handler on loopback with Open-Meteo failing (#983), and holds that the e2e
# ABOUTME: test's own helper and formatter print the 502, the feed's stated cause and its log line, from one request.
"""Offline half of #964's diagnostics: what verify/test_weather_feed_e2e.py prints when Open-Meteo fails.

Run 17801 saw the e2e test die on a bare `HTTP Error 502` (#982 made it print the cause). This test makes that
failure happen on purpose, without the network, and reads what the e2e test would print:

1. gitops/ai-layer/weather_feed.py is loaded as a module and its own `Handler` served on a free loopback port.
   Its `GEOCODE` and `FORECAST` URLs point at a loopback upstream that fails in one of three ways: it accepts the
   connection and never answers (a timeout, with the feed's `TIMEOUT` cut to 0.4 s), it answers 503 (an upstream
   HTTP error), or nothing listens on its port (refused). The feed's `_get_json` is not patched: its real urlopen
   call is what fails.
2. `request` and `failure_line` from verify/weather_feed_probe.py, the helper and formatter the e2e test imports,
   are called against that feed, and the e2e test's own `check_reading` is run with its stdout captured. Each must
   carry `HTTP 502` and the feed's `error` text, and that text must name the cause: "timed out" for the timeout,
   "HTTP Error 503" for the upstream error, "Connection refused" for the refusal, and no cause's words in another's.
3. The feed's log, captured from its `weather-feed` logger, must hold its `upstream lookup for ... failed` line
   with the same cause, and the feed must have received exactly one request per helper call: no retry.

Every literal this test matches in the feed, the helper or the e2e test is checked to be in that file first.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import logging
import pathlib
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
FEED_PY = REPO / "gitops/ai-layer/weather_feed.py"
PROBE_PY = VERIFY / "weather_feed_probe.py"
E2E_PY = VERIFY / "test_weather_feed_e2e.py"
CITY = "Salt Lake City"
FEED_TIMEOUT = 0.4

# Each literal the checks below read, and the file it must be in. The output literals are the feed's and the
# formatter's own words; the code literals are what this test reaches into (module names it sets or calls).
ANCHORS = {
    FEED_PY: ['log.warning("upstream lookup for %r failed: %s", city, e)',
              'self._send(502, {"error": f"weather service unavailable: {e}"})',
              "except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as e:",
              'GEOCODE = "https://', 'FORECAST = "https://', "TIMEOUT = ", "timeout=TIMEOUT",
              'log = logging.getLogger("weather-feed")', "class Handler(BaseHTTPRequestHandler):"],
    PROBE_PY: ['status = "no HTTP answer" if reply.status is None else f"HTTP {reply.status}"',
               '(expected {expected})', 'error: {error_field(reply.body)}', "def request(url: str, timeout: float = 20)",
               "def failure_line(what: str, reply: Reply, expected: int = 200)"],
    E2E_PY: ["from weather_feed_probe import error_field, failure_line, request",
             'reply = request(current_url(base, LIVE_CITY), timeout=20)',
             'line = failure_line(f"/current for {LIVE_CITY}", reply)', "def check_reading(base: str)",
             'LIVE_CITY = "Salt Lake City"', 'if __name__ == "__main__":'],
}
for path, literals in ANCHORS.items():
    text = path.read_text()
    for lit in literals:
        if lit not in text:
            print(f"FAILED: the literal {lit!r} is not in {path.relative_to(REPO)}; this test reads it, so it "
                  "changes with that file")
            sys.exit(1)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(VERIFY))
feed = load("weather_feed_under_test", FEED_PY)
probe = load("weather_feed_probe", PROBE_PY)
sys.modules["weather_feed_probe"] = probe  # the e2e test's own import then gets this same module
e2e = load("weather_feed_e2e_under_test", E2E_PY)
check("the e2e test uses the probe's helper and formatter, not copies",
      e2e.request is probe.request and e2e.failure_line is probe.failure_line)


class CaptureLog(logging.Handler):
    """The feed's log lines, as `LEVEL message`, cleared before each case."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:  # logging.Handler.handle holds self.lock around this
        self.lines.append(f"{record.levelname} {record.getMessage()}")


feed_log = CaptureLog()
feed.log.addHandler(feed_log)
feed.log.setLevel(logging.DEBUG)
feed.log.propagate = False


class CountingServer(ThreadingHTTPServer):
    """Serves the feed's own Handler unchanged; only counts the requests it is sent."""

    daemon_threads = True

    def __init__(self, addr, handler) -> None:
        super().__init__(addr, handler)
        self.requests = 0
        self.lock = threading.Lock()

    def process_request(self, request, client_address) -> None:
        with self.lock:
            self.requests += 1
        super().process_request(request, client_address)


class Upstream503(BaseHTTPRequestHandler):
    """Open-Meteo answering 503 on every path, counting what it was asked."""

    asked: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 (http.server's name)
        Upstream503.asked.append(self.path.split("?")[0])
        body = json.dumps({"error": True, "reason": "upstream down for the test"}).encode()
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        pass


def point_upstream(port: int) -> None:
    feed.GEOCODE = f"http://127.0.0.1:{port}/v1/search"
    feed.FORECAST = f"http://127.0.0.1:{port}/v1/forecast"


feed.TIMEOUT = FEED_TIMEOUT
server = CountingServer(("127.0.0.1", 0), feed.Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"
current = f"{base}/current?city=Salt+Lake+City"

# The three upstreams. Silent: listens, so the connection is made, and never accepts or answers. Refusing: bound
# but not listening, so a connect is refused at once and no other process can take the port meanwhile.
silent = socket.socket()
silent.bind(("127.0.0.1", 0))
silent.listen(16)
refusing = socket.socket()
refusing.bind(("127.0.0.1", 0))
http503 = ThreadingHTTPServer(("127.0.0.1", 0), Upstream503)
http503.daemon_threads = True
threading.Thread(target=http503.serve_forever, daemon=True).start()

CASES = [
    # name, upstream port, the words in the feed's error that name the cause
    ("an upstream timeout", silent.getsockname()[1], "timed out"),
    ("an upstream HTTP error", http503.server_address[1], "HTTP Error 503"),
    ("a refused upstream connection", refusing.getsockname()[1], "Connection refused"),
]
CAUSES = [c[2] for c in CASES]


def run_case(name: str, port: int, cause: str) -> None:
    print(f"== {name}: the feed answers 502 and says why ==")
    point_upstream(port)
    Upstream503.asked.clear()

    # The helper and formatter, called as the e2e test calls them.
    feed_log.lines.clear()
    server.requests = 0
    reply = probe.request(current, timeout=20)
    line = probe.failure_line(f"/current for {CITY}", reply)
    print(f"  printed: {line}")
    check("the helper sent exactly one request (no retry)", server.requests == 1, f"{server.requests} requests")
    check("the feed answered 502", reply.status == 502, f"status {reply.status}")
    err = reply.body.get("error", "") if isinstance(reply.body, dict) else ""
    check("its JSON body has an `error` field", bool(err), repr(reply.body))
    check(f"the error names the cause ({cause!r})",
          err.startswith("weather service unavailable: ") and cause in err, err)
    others = [c for c in CAUSES if c != cause and c in err]
    check("and no other cause's words, so the causes read apart", not others, f"{others} in {err!r}")
    check("the printed line carries HTTP 502", "HTTP 502 (expected 200)" in line, line)
    check("the printed line carries the feed's error text", bool(err) and f"error: {err}" in line, line)
    if name == "an upstream timeout":
        check(f"the feed waited out its own {FEED_TIMEOUT} s timeout, not the helper's 20 s",
              FEED_TIMEOUT <= reply.elapsed < 20, f"{reply.elapsed:.2f} s")
    if name == "an upstream HTTP error":
        check("the feed asked Open-Meteo's geocoder once and stopped there", Upstream503.asked == ["/v1/search"],
              str(Upstream503.asked))

    failed = [x for x in feed_log.lines if x.startswith("WARNING upstream lookup for ")]
    print(f"  feed log: {failed}")
    check("the feed's log holds one `upstream lookup ... failed` line for the request", len(failed) == 1,
          str(feed_log.lines))
    check("that line names the city and the same cause",
          bool(failed) and failed[0].startswith(f"WARNING upstream lookup for {CITY!r} failed: ") and cause in failed[0],
          str(failed))
    access = [x for x in feed_log.lines if x.startswith("INFO ") and "GET /current?" in x]
    check("and one access line, a 502", len(access) == 1 and '" 502 ' in access[0], str(access))

    # The e2e test's own reading check, with what it prints captured.
    print(f"== {name}: what verify/test_weather_feed_e2e.py prints ==")
    feed_log.lines.clear()
    server.requests = 0
    e2e.failures.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        e2e.check_reading(base)
    printed = out.getvalue()
    for x in printed.rstrip().splitlines():
        print(f"  | {x}")
    check("it sent exactly one request (no retry)", server.requests == 1, f"{server.requests} requests")
    check("it prints HTTP 502", f"/current for {CITY}: HTTP 502 (expected 200)" in printed, printed)
    check("it prints the feed's error text naming the cause",
          "error: weather service unavailable: " in printed and cause in printed, printed)
    check("it fails its 200 check and runs none of the reading checks",
          e2e.failures == ["the feed answers 200 with a JSON reading"] and "PASS" not in printed, str(e2e.failures))
    check("the feed's log for that request holds its upstream-failure line",
          sum(x.startswith(f"WARNING upstream lookup for {CITY!r} failed: ") and cause in x
              for x in feed_log.lines) == 1, str(feed_log.lines))


try:
    for case in CASES:
        run_case(*case)
finally:
    server.shutdown()
    http503.shutdown()
    silent.close()
    refusing.close()

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All weather feed upstream-failure checks passed.")
