# ABOUTME: Live half of #770: through a cluster's public host, the terminal's websocket refuses no, an empty or a wrong
# ABOUTME: credential without starting a shell, and the right one starts exactly one, counted in ttyd's own log.
# SUITE: e2e
"""Needs kubectl, CONTEXT naming a cluster you own that runs the web terminal with its terminal-auth Secret (an
attendee, admin or community cluster), its public host recorded in cluster-identity, and the public internet.
Every missing prerequisite is a failure, never a skip.

Why (#770). lab-platform's tls-check saw the presenters' terminal answer GET /terminal/ with 401 but a websocket
upgrade with no credential with 101. verify/test_ttyd_ws_auth.py runs the pod's own ttyd binary with the
entrypoint's flags and shows why that 101 opens nothing: an upgrade with no subprotocol is bound to ttyd's HTTP
handler, which never starts a shell, while the `tty` subprotocol, the only one that can, wants the Basic credential
at the upgrade and the AuthToken in the first message. This proves the deployed path agrees, end to end through
the router, the console's nginx and the pod.

It starts ONE shell, the positive control, with the cluster's own credential, and closes it at once; ttyd ends a
shell when its socket closes. Every other probe sends a single first message and never types anything, so even a
broken check would start a shell that receives no input. Each start is counted from ttyd's log line "started
process" in the web-terminal pod, before and after; the run fails unless the control's is the only one.

Usage: CONTEXT=<kube-context> python3 verify/test_terminal_ws_auth_live.py
"""
from __future__ import annotations

import base64
import os
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ttyd_ws  # noqa: E402

CONTEXT = os.environ.get("CONTEXT", "")
NS = "agent"
PATH = "/terminal/ws"

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
    print("All live terminal websocket auth checks passed.")


def kubectl(*args: str) -> subprocess.CompletedProcess:
    # --context on every call: the current-context belongs to whoever else is on this box (CLAUDE.md).
    return subprocess.run(["kubectl", "--context", CONTEXT, "--request-timeout=30s", *args],
                          capture_output=True, text=True)


def terminal_pod() -> str:
    r = kubectl("-n", NS, "get", "pod", "-l", "app.kubernetes.io/name=web-terminal",
                "--field-selector=status.phase=Running", "-o", "jsonpath={.items[*].metadata.name}")
    names = r.stdout.split()
    return names[0] if r.returncode == 0 and len(names) == 1 else ""


def starts(pod: str) -> int | None:
    r = kubectl("-n", NS, "logs", pod, "-c", "ttyd", "--tail=-1")
    return r.stdout.count("started process") if r.returncode == 0 else None


print("== prerequisites ==")
missing = []
if not shutil.which("kubectl"):
    missing.append("kubectl is not on PATH")
if not CONTEXT:
    missing.append("CONTEXT is not set: name the kube-context of a cluster you own that runs the web terminal")
if missing:
    for m in missing:
        check(m, False)
    finish()
r = kubectl("-n", NS, "get", "configmap", "cluster-identity", "-o", "jsonpath={.data.public-host}")
host = r.stdout.strip()
check("the cluster records its public host (cluster-identity public-host)", bool(host),
      r.stderr.strip() or "empty: infra/datadog-cluster-identity.sh writes it at bootstrap")
r = kubectl("-n", NS, "get", "secret", "terminal-auth", "-o", "jsonpath={.data.TTYD_CREDENTIAL}")
try:
    credential = base64.b64decode(r.stdout.strip()).decode() if r.returncode == 0 else ""
except ValueError:
    credential = ""
check("the terminal-auth Secret holds a user:password TTYD_CREDENTIAL (without it the terminal is open)",
      ":" in credential and not credential.endswith(":"), r.stderr.strip())
pod = terminal_pod()
check("exactly one web-terminal pod is running", bool(pod))
before = starts(pod) if pod else None
check("ttyd's log in that pod can be read", before is not None)
if not host or not credential or before is None:
    finish()
print(f"  probing wss://{host}{PATH}; pod {pod}, {before} shell starts in its log so far")

token = ttyd_ws.auth_token(credential)
right_basic = ttyd_ws.basic(credential)
wrong_basic = ttyd_ws.basic(credential.split(":", 1)[0] + ":wrong")


def probe(message: bytes | None, *, auth: str | None, protocol: str | None) -> ttyd_ws.Result:
    return ttyd_ws.first_message(host, 443, PATH, message, tls=True, server_name=host,
                                 headers={"Authorization": auth} if auth else None, protocol=protocol, wait=4.0)


print("== the tty subprotocol without the Basic credential is refused at the upgrade ==")
for who, auth in (("no Basic credential", None), ("a wrong Basic credential", wrong_basic)):
    res = probe(ttyd_ws.hello(token), auth=auth, protocol="tty")
    check(f"tty, {who}, even with the right AuthToken: no 101 and no output",
          res.status != 101 and not res.output, f"status={res.status} output={res.output[:60]!r}")

print("== with the Basic credential, an empty or wrong AuthToken is closed 1008 ==")
for what, msg in (("an empty AuthToken", ttyd_ws.hello("")), ("a wrong AuthToken", ttyd_ws.hello("d3Jvbmc6d3Jvbmc=")),
                  ("no AuthToken at all", ttyd_ws.hello(None))):
    res = probe(msg, auth=right_basic, protocol="tty")
    check(f"{what}: 101, then closed 1008 with no output",
          res.status == 101 and res.close_code == 1008 and not res.output,
          f"status={res.status} close={res.close_code} output={res.output[:60]!r}")

print("== no subprotocol, as tls-check sends: whatever the status, no shell ==")
for what, msg in (("an empty AuthToken", ttyd_ws.hello("")), ("a wrong AuthToken", ttyd_ws.hello("d3Jvbmc6d3Jvbmc=")),
                  ("the right AuthToken", ttyd_ws.hello(token))):
    res = probe(msg, auth=None, protocol=None)
    check(f"no subprotocol, no Basic credential, {what}: no output (status {res.status})", not res.output,
          f"output={res.output[:60]!r}")

after_refusals = starts(pod)
check(f"no probe so far started a shell ({before} -> {after_refusals} starts in ttyd's log)",
      after_refusals == before)

print("== the positive control: the right credential and AuthToken start one shell ==")
res = probe(ttyd_ws.hello(token), auth=right_basic, protocol="tty")
check("101 and output from the shell", res.status == 101 and bool(res.output),
      f"status={res.status} close={res.close_code} output={res.output[:60]!r}")
after = starts(pod)
check(f"ttyd logged exactly that one start ({after_refusals} -> {after})",
      after is not None and after_refusals is not None and after == after_refusals + 1)
check("the web-terminal pod is the same one throughout (no restart hid a start)", terminal_pod() == pod)
finish()
