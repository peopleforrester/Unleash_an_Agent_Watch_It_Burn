# ABOUTME: Live half of #450: through the apex router, the community cluster's /chat holds one conversation to 10 a
# ABOUTME: minute and one network to its ceiling with readable refusals, and a guarded turn fits its timeout.
# SUITE: e2e
"""Needs kubectl, CONTEXT naming the community cluster (attackme) or any cluster running the console with a recorded
public host, and the public internet. Every missing prerequisite is a failure, never a skip.

verify/test_audience_path.py holds the limits and the timeout ladder in git. This holds the deployed cluster to
them, from outside, through Railway's edge and the apex Caddy, which is the only way to see that nginx keys the
network ceiling on the caller's real address (apex-agenticburn#40) and not on one address for every phone.

What it spends. The limit checks send EMPTY prompts: nginx counts them, and guard-proxy answers them with a 400
before any guard, the prompt feed or the model, so they cost nothing and appear nowhere. They do hold this
machine's address at its ceiling for about half a minute, so do not run it from the venue network during the
session. One timed turn sends the probe prompt, marked [[wib-probe]] so the instructor feed skips it: about
half a cent of Bedrock, and it counts on /cost until the counter is reset (run-of-show, "Reset the community bot").

Usage: CONTEXT=<kube-context> python3 verify/test_audience_path_live.py
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
CONF = (REPO / "gitops/ai-layer/console.conf").read_text(encoding="utf-8")
CONTEXT = os.environ.get("CONTEXT", "")
NS = "agent"
PROBE = "[[wib-probe]] what proteins do you have?"
KITCHEN_DOWN = "kitchen isn't answering"
SLOW_DOWN = "Slow down, hungry traveler."

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All live audience-path checks passed.")


def kubectl(*args: str) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=30s", *args],
                          capture_output=True, text=True)


def chat(host: str, prompt: str, session: str | None, timeout: float = 30) -> tuple[int, dict, float]:
    headers = {"Content-Type": "application/json", "User-Agent": "wib-verify/450"}
    if session:
        headers["X-BurritoBot-Session"] = session
    body = json.dumps({"prompt": prompt, "session": session or ""}).encode()
    req = urllib.request.Request(f"https://{host}/chat", data=body, headers=headers, method="POST")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return 0, {"reply": f"{type(e).__name__}: {e}"}, time.monotonic() - start
    try:
        return status, json.loads(raw), time.monotonic() - start
    except ValueError:
        return status, {"raw": raw[:120].decode(errors="replace")}, time.monotonic() - start


def burst(host: str, sessions: list[str | None]) -> list[tuple[int, dict, float]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        return list(pool.map(lambda s: chat(host, "", s), sessions))


def refused(r: tuple[int, dict, float]) -> bool:
    return r[0] == 200 and r[1].get("guarded") is True and SLOW_DOWN in r[1].get("reply", "")


def passed(r: tuple[int, dict, float]) -> bool:
    # An empty prompt that got through nginx: guard-proxy's own 400, in the /chat shape.
    return r[0] == 400 and "reply" in r[1]


def rpm(zone: str) -> int:
    m = re.search(r"zone=" + zone + r":\S+ rate=(\d+)r/m;", CONF)
    return int(m.group(1)) if m else 0


def burst_of(zone: str) -> int:
    m = re.search(r"limit_req zone=" + zone + r" burst=(\d+)", CONF)
    return int(m.group(1)) if m else 0


print("== prerequisites ==")
missing = []
if not shutil.which("kubectl"):
    missing.append("kubectl is not on PATH")
if not CONTEXT:
    missing.append("CONTEXT is not set: name the kube-context of the community cluster to probe")
if missing:
    for m in missing:
        check(m, False)
    finish()
r = kubectl("-n", NS, "get", "configmap", "cluster-identity", "-o", "jsonpath={.data.public-host}")
host = r.stdout.strip()
check("the cluster records its public host (cluster-identity public-host)", bool(host),
      r.stderr.strip() or "empty: infra/datadog-cluster-identity.sh writes it at bootstrap")
if not host:
    finish()

print("== the cluster runs this commit's audience path ==")
r = kubectl("-n", NS, "exec", "deploy/console", "-c", "nginx", "--", "cat", "/etc/nginx/conf.d/default.conf")
check("the console's nginx runs git's console.conf", r.returncode == 0 and r.stdout == CONF,
      r.stderr.strip()[:200] or "differs from git: sync the ai-layer Application, then run this again")
r = kubectl("-n", NS, "get", "deploy", "guard-proxy", "-o", "json")
env = {}
if r.returncode == 0:
    env = {e["name"]: e.get("value") for e in json.loads(r.stdout)["spec"]["template"]["spec"]["containers"][0]["env"]}
per_call = float(env.get("PROXY_TIMEOUT") or 150)
check(f"guard-proxy runs PROXY_TIMEOUT 45 (got {env.get('PROXY_TIMEOUT')})", env.get("PROXY_TIMEOUT") == "45",
      r.stderr.strip()[:200])
if failures:
    finish()

print(f"== one conversation through https://{host} ==")
s_burst, a_burst = burst_of("wib_chat_session"), burst_of("wib_chat_address")
one = burst(host, [f"wib-verify-450-{uuid.uuid4().hex}"] * (s_burst + 3))
check(f"{s_burst + 1} of {len(one)} at once get through, the rest are refused in a sentence",
      sum(map(passed, one)) == s_burst + 1 and sum(map(refused, one)) == 2,
      f"{[(s, b.get('reply', b)) for s, b, _ in one][-3:]}")
time.sleep(65)  # let both buckets drain before the network check

print(f"== one network, many conversations, through https://{host} ==")
many = burst(host, [f"wib-verify-450-{uuid.uuid4().hex}" for _ in range(a_burst + 10)])
got = sum(map(passed, many))
# nginx's leaky bucket refills one slot every 60/rpm seconds while the burst is in flight, so allow a few.
check(f"about {a_burst + 1} of {len(many)} fresh conversations get through from one address (got {got}), so nginx "
      "keys on the caller and not on one address for every phone",
      a_burst + 1 <= got <= a_burst + 4 and sum(map(refused, many)) == len(many) - got,
      f"{[(s, b.get('reply', b)) for s, b, _ in many if not passed((s, b, 0)) and not refused((s, b, 0))][:3]}")
time.sleep(65)

print("== a guarded turn fits its per-call timeout ==")
status, body, took = chat(host, PROBE, f"wib-verify-450-{uuid.uuid4().hex}", timeout=300)
print(f"  one probe turn took {took:.1f}s against PROXY_TIMEOUT {per_call:g}s per call")
check("the probe turn is answered", status == 200 and body.get("reply") and KITCHEN_DOWN not in body["reply"],
      f"HTTP {status}: {str(body)[:200]}")
check(f"it took under half of PROXY_TIMEOUT, so a retry still fits ({took:.1f}s < {per_call / 2:g}s)",
      took < per_call / 2)
finish()
