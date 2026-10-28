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
"""
from __future__ import annotations

import json
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("uv") is None:
    print("FAILED: uv not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
feed = subprocess.Popen([sys.executable, "-I", str(AI / "weather_feed.py")],
                        env={"FEED_LISTEN_PORT": str(port), "FEED_LISTEN_HOST": "127.0.0.1"},
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
base = f"http://127.0.0.1:{port}"
try:
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{base}/healthz", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)

    print("== the feed returns a live reading ==")
    body = json.loads(urllib.request.urlopen(f"{base}/current?city=Salt+Lake+City", timeout=20).read())
    check("it names the place", body.get("place", "").startswith("Salt Lake City"), str(body))
    check("it gives Fahrenheit and Celsius", isinstance(body.get("temp_f"), (int, float))
          and isinstance(body.get("temp_c"), (int, float)), str(body))
    check("the two units agree", abs((body["temp_f"] - 32) * 5 / 9 - body["temp_c"]) < 0.2, str(body))
    check("it describes the conditions in words", isinstance(body.get("conditions"), str) and body["conditions"]
          and not body["conditions"].startswith("WMO"), str(body))
    check("the reading is current (Open-Meteo's observation time is given)", bool(body.get("observed")), str(body))

    print("== an unknown city is an error, not a reading ==")
    try:
        urllib.request.urlopen(f"{base}/current?city=Qzxqzxqzx+Nowhereville", timeout=20)
        check("an unknown city returns 404", False, "got 200")
    except urllib.error.HTTPError as e:
        check("an unknown city returns 404", e.code == 404, str(e.code))
        check("with a reason", b"no place" in e.read().lower())

    print("== the deployed get_weather reads it ==")
    probe = ("import importlib.util,sys;spec=importlib.util.spec_from_file_location('srv',sys.argv[1]);"
             "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);print(m.get_weather('Salt Lake City'))")

    def call_tool(feed_url: str) -> str:
        r = subprocess.run(["uv", "run", "--no-project", "--with", "mcp==1.29.1", "python", "-I", "-c", probe,
                            str(AI / "server.py")], capture_output=True, text=True, cwd="/",
                           env={"PATH": __import__("os").environ["PATH"], "HOME": __import__("os").environ["HOME"],
                                "WEATHER_FEED_URL": feed_url})
        return r.stdout if r.returncode == 0 else f"<failed: {r.stderr.strip()[-300:]}>"

    out = call_tool(base)
    check("get_weather opens with the live reading for the city", out.startswith("Salt Lake City") and "°F" in out, out[:200])
finally:
    feed.terminate()
    feed.wait(timeout=5)

out = call_tool(base)
check("with the feed down, get_weather says the lookup failed", out.startswith("Weather lookup failed"), out[:200])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All weather feed E2E checks passed.")
