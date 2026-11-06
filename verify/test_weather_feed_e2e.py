# ABOUTME: Runs the real weather feed against Open-Meteo and the deployed get_weather against that feed (#642),
# ABOUTME: so the reading C7's room sees is proven live, not only pattern-matched.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: network to Open-Meteo, uv for mcp 1.29.1 as the image pins it)
"""The executed half of verify/test_weather_feed.py.

1. gitops/ai-layer/weather_feed.py is started on a free loopback port and asked for Salt Lake City. The
   answer must be a real current reading from Open-Meteo: a place, a temperature in both units, conditions.
2. A city that does not exist must come back as a 404 with a reason, not as a reading.
3. The deployed server.py is imported with mcp==1.29.1 and its get_weather called with WEATHER_FEED_URL at
   that feed. The reply must open with the live reading. With the feed stopped it must say the lookup failed.

Needs network and uv. A missing tool or an unreachable Open-Meteo is a failure, not a skip.

A request the feed answers with an error is printed, not raised (#982): its status, the feed's `error` field and
how long it took (verify/weather_feed_probe.py), and the reading checks that need its body are not run. When any
check fails, the feed's own log is printed after it is stopped: it records each upstream failure it answered 502
for. Nothing is retried; one failed request is one failed check and a failed test.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from weather_feed_probe import error_field, failure_line, request  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
LIVE_CITY = "Salt Lake City"
UNKNOWN_CITY = "Qzxqzxqzx Nowhereville"
PROBE = ("import importlib.util,sys;spec=importlib.util.spec_from_file_location('srv',sys.argv[1]);"
         "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);print(m.get_weather('Salt Lake City'))")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def current_url(base: str, city: str) -> str:
    return f"{base}/current?{urllib.parse.urlencode({'city': city})}"


def call_tool(feed_url: str) -> str:
    r = subprocess.run(["uv", "run", "--no-project", "--with", "mcp==1.29.1", "python", "-I", "-c", PROBE,
                        str(AI / "server.py")], capture_output=True, text=True, cwd="/",
                       env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "WEATHER_FEED_URL": feed_url})
    return r.stdout if r.returncode == 0 else f"<failed: {r.stderr.strip()[-300:]}>"


def check_reading(base: str) -> None:
    print("== the feed returns a live reading ==")
    reply = request(current_url(base, LIVE_CITY), timeout=20)
    line = failure_line(f"/current for {LIVE_CITY}", reply)
    ok = reply.status == 200 and isinstance(reply.body, dict)
    if not ok:
        print(f"  {line}")
    check("the feed answers 200 with a JSON reading", ok, line)
    if not ok:
        print("  (the reading checks need that body, so they are not run)")
        return
    body = reply.body
    check("it names the place", str(body.get("place", "")).startswith(LIVE_CITY), str(body))
    units = isinstance(body.get("temp_f"), (int, float)) and isinstance(body.get("temp_c"), (int, float))
    check("it gives Fahrenheit and Celsius", units, str(body))
    check("the two units agree", units and abs((body["temp_f"] - 32) * 5 / 9 - body["temp_c"]) < 0.2, str(body))
    check("it describes the conditions in words", isinstance(body.get("conditions"), str) and bool(body["conditions"])
          and not body["conditions"].startswith("WMO"), str(body))
    check("the reading is current (Open-Meteo's observation time is given)", bool(body.get("observed")), str(body))


def check_unknown_city(base: str) -> None:
    print("== an unknown city is an error, not a reading ==")
    reply = request(current_url(base, UNKNOWN_CITY), timeout=20)
    line = failure_line(f"/current for {UNKNOWN_CITY}", reply, expected=404)
    if reply.status != 404:
        print(f"  {line}")
    check("an unknown city returns 404", reply.status == 404, line)
    if reply.status == 404:
        check("with a reason", "no place" in error_field(reply.body).lower(), error_field(reply.body))


def main() -> int:
    if shutil.which("uv") is None:
        print("FAILED: uv not on PATH; this E2E check cannot run, which is a failure, not a skip")
        return 1

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    feed = subprocess.Popen([sys.executable, "-I", str(AI / "weather_feed.py")],
                            env={"FEED_LISTEN_PORT": str(port), "FEED_LISTEN_HOST": "127.0.0.1"},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            if request(f"{base}/healthz", timeout=1).status == 200:
                break
            time.sleep(0.1)

        check_reading(base)
        check_unknown_city(base)

        print("== the deployed get_weather reads it ==")
        out = call_tool(base)
        check("get_weather opens with the live reading for the city", out.startswith(LIVE_CITY) and "°F" in out,
              out[:200])
    finally:
        feed.terminate()
        try:
            feed_log, _ = feed.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            feed.kill()
            feed_log, _ = feed.communicate()

    out = call_tool(base)
    check("with the feed down, get_weather says the lookup failed", out.startswith("Weather lookup failed"), out[:200])

    print()
    if failures:
        print("== the feed's log (its stdout and stderr) ==")
        print(feed_log.rstrip() or "<the feed printed nothing>")
        print()
        print(f"FAILED: {len(failures)} check(s)")
        return 1
    print("All weather feed E2E checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
