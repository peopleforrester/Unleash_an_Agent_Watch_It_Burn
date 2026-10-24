# ABOUTME: Live half of #481: from outside the cluster, the console refuses /a2a/toggle and /toggle, while the
# ABOUTME: terminal's own guard helpers still reach guard-proxy's /toggle over kubectl exec + localhost.
# SUITE: e2e
"""Needs kubectl, CONTEXT naming an admin or community cluster (any cluster running the console works) whose
public host is recorded, and the public internet. Every missing prerequisite is a failure, never a skip.

Why (#481). The console's /a2a/ route stripped its prefix into guard-proxy's whole path space, so anyone who
could open the cluster's URL could GET /a2a/toggle?output=off. verify/test_console_no_toggle.py proves the
rendered config forwards no such path; this proves the deployed console agrees, through the real apex
router, and that closing it cost the students nothing: the helpers they run in the terminal still work.

Changes no guard state. The public probes send /toggle with NO query, which flips nothing even on a cluster
still running the old route, and the helper call sets output to the value it already has. The guards are
read before and after over kubectl exec, and the run fails if they moved.

Usage: CONTEXT=<kube-context> python3 verify/test_console_no_toggle_live.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

CONTEXT = os.environ.get("CONTEXT", "")
NS = "agent"
TIMEOUT_S = 20
# Paths that reached guard-proxy through the old /a2a/ route, or would if a bare route came back.
REFUSED = ("/a2a/toggle", "/a2a/guards", "/a2a/", "/toggle")
GUARD_KEYS = ("input_blocklist", "input_classifier", "output")
READ_GUARDS = ("import urllib.request;"
               "print(urllib.request.urlopen('http://localhost:8080/guards',timeout=10).read().decode())")

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
    print("All live /toggle exposure checks passed.")


def kubectl(*args: str) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=30s", *args],
                          capture_output=True, text=True)


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "wib-verify/481"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"


def guards_in_pod() -> dict:
    r = kubectl("-n", NS, "exec", "deploy/guard-proxy", "-c", "proxy", "--", "python3", "-c", READ_GUARDS)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {}
    except ValueError:
        return {}


print("== prerequisites ==")
missing = []
if not shutil.which("kubectl"):
    missing.append("kubectl is not on PATH")
if not CONTEXT:
    missing.append("CONTEXT is not set: name the kube-context of the admin or community cluster to probe")
if missing:
    for m in missing:
        check(m, False)
    finish()
r = kubectl("-n", NS, "get", "configmap", "cluster-identity", "-o", "jsonpath={.data.public-host}")
host = r.stdout.strip()
check("the cluster records its public host (cluster-identity public-host)", bool(host),
      r.stderr.strip() or "empty: infra/datadog-cluster-identity.sh writes it at bootstrap")
before = guards_in_pod()
check("guard-proxy answers /guards over kubectl exec + localhost", all(k in before for k in GUARD_KEYS),
      f"{before}")
if not host or not before:
    finish()
print(f"  probing https://{host} through the router; guards before: {before}")

print("== the console still serves guard-proxy's read-only state ==")
status, body = fetch(f"https://{host}/guards")
check(f"https://{host}/guards answers the guard state (so a 404 below is the console's, not a dead hop)",
      status == 200 and all(k in body for k in GUARD_KEYS), f"HTTP {status}: {body.strip()[:160]}")

print("== the console refuses every path into /toggle from outside ==")
for path in REFUSED:
    status, body = fetch(f"https://{host}{path}")
    check(f"https://{host}{path} is refused (404, nothing from guard-proxy)",
          status == 404 and not any(k in body for k in GUARD_KEYS), f"HTTP {status}: {body.strip()[:160]}")

print("== the terminal's helpers still flip the guards ==")
cur = "on" if before.get("output") else "off"
helper = ('source "$HOME/.guardlib" && _px "output=' + cur + '" && echo PX_OK && bash "$HOME/guards-status"')
r = kubectl("-n", NS, "exec", "deploy/web-terminal", "-c", "ttyd", "--",
            "env", "HOME=/home/student", "bash", "-c", helper)
check(f"the terminal's _px helper sets output={cur} through kubectl exec + localhost",
      r.returncode == 0 and "PX_OK" in r.stdout, f"rc={r.returncode}: {(r.stderr or r.stdout).strip()[:240]}")
check("guards-status reads the guards from the terminal", "Your AI guardrails right now:" in r.stdout,
      r.stdout.strip()[-240:])

after = guards_in_pod()
check("no probe changed the guard state", after == before, f"before={before} after={after}")
finish()
