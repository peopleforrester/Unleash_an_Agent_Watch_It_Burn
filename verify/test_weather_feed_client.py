# ABOUTME: Serves the real weather feed handler on loopback with Open-Meteo made to fail, and holds that the 502 and
# ABOUTME: its error text reach what test_weather_feed_e2e.py prints, with no retry (#964). No network needed.
"""Offline half of #964.

Run 17801 on #882 saw test_weather_feed_e2e.py die on an HTTPError 502 from the local feed, and the body that names
the upstream cause was never read. The e2e test now asks the feed through verify/weather_feed_client.py, which
returns the status, the JSON body and the time taken for error statuses as well. Here the feed's own Handler from
gitops/ai-layer/weather_feed.py is served on a loopback port, its Open-Meteo call is replaced by one that fails the
ways a live call can, and the client must report each failure by name.
"""
from __future__ import annotations

import importlib.util
import logging
import pathlib
import re
import socket
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import weather_feed_client  # noqa: E402

E2E = (REPO / "verify/test_weather_feed_e2e.py").read_text()

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


spec = importlib.util.spec_from_file_location("weather_feed", REPO / "gitops/ai-layer/weather_feed.py")
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)
feed.log.setLevel(logging.CRITICAL)  # its 502 warning is what is under test, not output for this run


def serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def upstream(behaviour):
    """Replace the feed's Open-Meteo call; return how many times it was called, so a retry would show."""
    calls = {"n": 0}

    def fake(url: str, params: dict) -> dict:
        calls["n"] += 1
        return behaviour(url, params)
    feed._get_json = fake
    return calls


srv, base = serve(feed.Handler)
city = f"{base}/current?city=Salt+Lake+City"
try:
    print("== an Open-Meteo timeout comes back as a 502 that names it ==")

    def timed_out(url, params):
        raise urllib.error.URLError(TimeoutError("timed out"))
    calls = upstream(timed_out)
    a = weather_feed_client.get(city)
    check("the client returns the 502 instead of raising", a.status == 502, a.describe())
    check("with the feed's error text", "timed out" in a.body.get("error", ""), a.describe())
    check("and its description names status, cause and time",
          re.fullmatch(r"HTTP 502 after \d+\.\ds, error: '.*timed out.*'", a.describe()) is not None, a.describe())
    check("one request is one upstream call: nothing retried", calls["n"] == 1, str(calls["n"]))

    print("== an Open-Meteo error status comes back as a 502 that names it ==")

    def limited(url, params):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
    upstream(limited)
    a = weather_feed_client.get(city)
    check("the 429 is in the 502's error text", a.status == 502 and "429" in a.body.get("error", ""), a.describe())

    print("== a read timeout and a malformed answer are 502s too ==")

    def read_timeout(url, params):
        raise TimeoutError("The read operation timed out")
    upstream(read_timeout)
    a = weather_feed_client.get(city)
    check("a read timeout is named", a.status == 502 and "read operation timed out" in a.body.get("error", ""),
          a.describe())
    upstream(lambda url, params: {"results": [{"name": "X", "latitude": 1, "longitude": 2}]} if "geocoding" in url
             else {"unexpected": True})
    a = weather_feed_client.get(city)
    check("a forecast without its current block is named", a.status == 502 and "current" in a.body.get("error", ""),
          a.describe())

    print("== a reading and an unknown city still read as before ==")
    upstream(lambda url, params: {"results": [{"name": "Salt Lake City", "admin1": "Utah", "country": "United States",
                                               "latitude": 40.76, "longitude": -111.89}]} if "geocoding" in url
             else {"current": {"temperature_2m": 50.0, "weather_code": 0, "time": "2026-11-06T06:00"}})
    a = weather_feed_client.get(city)
    check("a 200 returns the reading", a.status == 200 and a.body.get("place", "").startswith("Salt Lake City")
          and a.body.get("temp_c") == 10.0, a.describe())
    upstream(lambda url, params: {})
    a = weather_feed_client.get(f"{base}/current?city=Qzxqzxqzx+Nowhereville")
    check("an unknown city returns 404 with its reason", a.status == 404 and "no place" in a.body.get("error", ""),
          a.describe())
finally:
    srv.shutdown()
    srv.server_close()

print("== a body that is not JSON is still shown ==")


class Html502(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        data = b"<html>Bad Gateway</html>"
        self.send_response(502)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        pass


srv, other = serve(Html502)
try:
    a = weather_feed_client.get(f"{other}/current?city=x")
    check("the status and the raw body are reported", a.status == 502 and "Bad Gateway" in a.describe(), a.describe())
finally:
    srv.shutdown()
    srv.server_close()

print("== a connection that fails outright still raises ==")
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    closed = s.getsockname()[1]
try:
    weather_feed_client.get(f"http://127.0.0.1:{closed}/current?city=x", timeout=2)
    check("a refused connection raises", False, "returned an answer")
except urllib.error.URLError as e:
    check("a refused connection raises", not isinstance(e, urllib.error.HTTPError), repr(e))

print("== the e2e test asks through the client and fails on what it prints ==")
check("both /current requests go through weather_feed_client.get",
      len(re.findall(r"weather_feed_client\.get\(f\"\{base\}/current\?", E2E)) == 2
      and "urlopen(f\"{base}/current" not in E2E)
check("a non-200 live reading is a failed check carrying the description",
      'check("the feed answers 200 for Salt Lake City", live.status == 200, live.describe())' in E2E)
check("a failed run prints the feed's own log", "== the feed's own log ==" in E2E and "feed.stdout.read()" in E2E)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All weather feed client checks passed.")
