# ABOUTME: Runs the weather feed through egress-proxy with the allowlist resources.yaml deploys (#861), against the real
# ABOUTME: Open-Meteo: C7's reading still arrives, both hosts are tunnelled, and the beacon host is refused.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: network to Open-Meteo)
"""The executed half of #861's build item 2.

verify/test_egress_lock.py holds that ALLOWED_HOSTS names exactly the hosts in weather_feed.py. This runs both
programs as the cluster runs them: egress_proxy.py with the Deployment's own ALLOWED_HOSTS and ALLOWED_PORTS on a
free loopback port, and weather_feed.py with HTTPS_PROXY pointed at it, the way its pod is configured. A reading for
Salt Lake City has to come back, the proxy has to log a tunnel to each Open-Meteo host, and a CONNECT to the beacon's
host has to be refused. Needs network; an unreachable Open-Meteo is a failure, not a skip.
"""
from __future__ import annotations

import json
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text()) if isinstance(d, dict)]
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(port: int) -> None:
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.1)


dep = next(d for d in RES if d.get("kind") == "Deployment" and d["metadata"]["name"] == "egress-proxy")
env = {e["name"]: e["value"] for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
proxy_port, feed_port = free_port(), free_port()
proxy = subprocess.Popen([sys.executable, "-I", str(AI / "egress_proxy.py")],
                         env={"ALLOWED_HOSTS": env["ALLOWED_HOSTS"], "ALLOWED_PORTS": env["ALLOWED_PORTS"],
                              "LISTEN_PORT": str(proxy_port)},
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
feed = subprocess.Popen([sys.executable, "-I", str(AI / "weather_feed.py")],
                        env={"FEED_LISTEN_PORT": str(feed_port), "FEED_LISTEN_HOST": "127.0.0.1",
                             "HTTPS_PROXY": f"http://127.0.0.1:{proxy_port}"},
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    wait(proxy_port)
    wait(feed_port)
    print("== the feed's reading arrives through the proxy ==")
    body = {}
    try:
        body = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{feed_port}/current?city=Salt+Lake+City",
                                                 timeout=40).read())
    except OSError as e:
        check("the feed answers through the proxy", False, repr(e))
    check("it names the place", str(body.get("place", "")).startswith("Salt Lake City"), str(body))
    check("it gives a temperature", isinstance(body.get("temp_c"), (int, float)), str(body))

    print("== the beacon's host is refused ==")
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=10) as s:
        s.sendall(b"CONNECT agenticburn.com:443 HTTP/1.1\r\nHost: agenticburn.com\r\n\r\n")
        status = s.recv(4096).split(b"\r\n", 1)[0].decode()
    check("CONNECT agenticburn.com:443 gets 403", status.startswith("HTTP/1.1 403"), status)
finally:
    feed.terminate()
    proxy.terminate()
    out, _ = proxy.communicate(timeout=10)
    feed.communicate(timeout=10)

lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
allowed = {d["host"] for d in lines if d.get("event") == "egress_allow"}
check("the proxy tunnelled to both Open-Meteo hosts", allowed == {"geocoding-api.open-meteo.com", "api.open-meteo.com"},
      repr(allowed))
check("and logged the refusal", any(d.get("event") == "egress_deny" and d.get("host") == "agenticburn.com"
                                    for d in lines))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All egress proxy E2E checks passed.")
