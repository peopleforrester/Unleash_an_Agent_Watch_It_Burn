# ABOUTME: Runs the terminal's real ttyd with the entrypoint's own flags (#770) and proves a websocket with no, an
# ABOUTME: empty or a wrong credential never starts a shell, while the right one does, so the check can see a shell.
# SUITE: e2e (needs the ttyd binary the web-terminal image ships)
# E2E TIER: tools (no cluster, no AWS: the pinned ttyd from e2e-tools.lock, run on loopback)
"""Why (#770). On 2026-11-01 lab-platform's tls-check on burritobot-private.agenticburn.com, the presenters'
cluster, saw a plain GET /terminal/ answer 401 but a websocket upgrade on /terminal/ with no credential answer 101.
A 101 to anyone would make the terminal a shell for anyone who knows the hostname, so the question was what ttyd
does after the upgrade: is a socket whose first message carries an empty or wrong AuthToken closed before any
shell starts? lab-platform#347 could not send that message to the presenters' cluster, since a broken check would
start a shell there.

This runs the same bytes the pod runs. e2e-tools.lock pins ttyd 1.7.7's ttyd.x86_64 by SHA-256, which is the
binary in the web-terminal image gitops/ai-layer/resources.yaml pins (measured 2026-11-02, decisions.md), and the
flags are read from the credentialed `exec ttyd` line of the entrypoint the pod mounts, so a change to either is
what gets tested. Only three things differ from the pod: the port (a free one), the interface (loopback) and the
command, which is a script that records each start in a file before it runs an interactive shell. ttyd's own log
line "started process" is counted as well, so a start is seen whichever way it shows.

What ttyd 1.7.7 does, and what this holds:

  * The `tty` subprotocol, the one ttyd's page asks for and the only one bound to the shell, checks the Basic
    credential AT THE UPGRADE. With none, or a wrong one, the connection is dropped and no 101 is sent, whatever
    the first message would have said.
  * With the Basic credential right, the first message's AuthToken is checked as well. Empty, wrong, missing, or
    the password unencoded: ttyd closes with 1008 (policy violation) and starts nothing. Keystrokes sent before
    the AuthToken drop the connection.
  * A socket that asks for NO subprotocol, as tls-check's curl probe does, is answered 101 by anyone. libwebsockets
    binds it to ttyd's first protocol, the HTTP handler, which never spawns a command: no AuthToken, not even the
    right one, starts a shell there. That is the 101 #770 saw, and it opens nothing.
  * The positive control: the right Basic credential and the right AuthToken start exactly one shell, whose output
    arrives. Without it, a ttyd that could start no shell at all would pass every case above.

Install: none. verify/fetch-e2e-tools.sh fetches ttyd from e2e-tools.lock, and run-e2e.sh and run-e2e-tools.sh point
$TTYD at it. Run by hand: TTYD=verify/.tools/bin/ttyd python3 verify/test_ttyd_ws_auth.py
"""
from __future__ import annotations

import os
import pathlib
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "verify"))
import ttyd_ws  # noqa: E402

ENTRYPOINT = REPO / "gitops/ai-layer/web-terminal/entrypoint.sh"
LOCK = REPO / "verify/e2e-tools.lock"
CREDENTIAL = "presenter:wib-770-not-a-real-password"
TOKEN = ttyd_ws.auth_token(CREDENTIAL)

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
    print("All ttyd websocket auth checks passed.")


def ttyd_args(entrypoint: str) -> list[str]:
    """The arguments of the entrypoint's credentialed `exec ttyd` line, command included, unexpanded."""
    joined = entrypoint.replace("\\\n", " ")
    lines = [ln.strip() for ln in joined.splitlines() if ln.strip().startswith("exec ttyd ")]
    cred = [ln for ln in lines if '"${TTYD_CREDENTIAL}"' in ln]
    return shlex.split(cred[0])[2:] if len(cred) == 1 else []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


print("== the ttyd under test is the pod's ttyd, with the pod's flags ==")
ttyd = os.environ.get("TTYD", "")
if not ttyd or not os.access(ttyd, os.X_OK):
    check("TTYD names an executable ttyd (run-e2e-tools.sh points it at verify/.tools/bin/ttyd)", False,
          f"TTYD={ttyd!r}: run bash verify/fetch-e2e-tools.sh, then TTYD=verify/.tools/bin/ttyd")
    finish()
pinned = next((ln.split()[1] for ln in LOCK.read_text().splitlines() if ln.startswith("ttyd ")), "")
version = subprocess.run([ttyd, "--version"], capture_output=True, text=True).stdout.strip()
check(f"$TTYD is e2e-tools.lock's ttyd {pinned} ({version!r})",
      bool(pinned) and re.match(rf"ttyd version {re.escape(pinned)}\b", version) is not None)

args = ttyd_args(ENTRYPOINT.read_text())
check(f"the entrypoint has one credentialed `exec ttyd` line ({args})", bool(args))
if not args:
    finish()
check("it passes the credential with -c", "-c" in args and args[args.index("-c") + 1] == "${TTYD_CREDENTIAL}")
check("it serves under /terminal, the path the console proxies", "-b" in args and args[args.index("-b") + 1] == "/terminal")
check("it is writable (-W), so a started shell would take input", "-W" in args)
check("it sets no --auth-header, which would hand the check to a proxy", "-H" not in args and "--auth-header" not in args)
cmd_at = args.index("bash") if "bash" in args else len(args)
flags = args[:cmd_at]
check(f"it runs bash ({args[cmd_at:]})", args[cmd_at:cmd_at + 1] == ["bash"])

port = free_port()
flags = [{"${TTYD_CREDENTIAL}": CREDENTIAL}.get(a, a) for a in flags]
flags[flags.index("-p") + 1] = str(port)

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    starts = tmp / "starts"
    spawn = tmp / "spawn.sh"
    spawn.write_text(f'#!/bin/sh\necho "started $$" >> {shlex.quote(str(starts))}\nexec bash --norc --noprofile -i\n')
    spawn.chmod(0o755)
    log = tmp / "ttyd.log"
    with log.open("wb") as lf:
        proc = subprocess.Popen([ttyd, *flags, "-i", "127.0.0.1", str(spawn)], stdout=lf, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

        def started() -> int:
            return len(starts.read_text().splitlines()) if starts.exists() else 0

        def logged() -> int:
            return log.read_text(errors="replace").count("started process")

        def probe(path: str, message: bytes | None, *, auth: str | None, protocol: str | None) -> tuple:
            before = (started(), logged())
            headers = {"Authorization": auth} if auth else None
            r = ttyd_ws.first_message("127.0.0.1", port, path, message, headers=headers, protocol=protocol, wait=2.0)
            time.sleep(0.3)  # a start the socket's close raced is still written by now
            return r, started() - before[0], logged() - before[1]

        def get(path: str, auth: str | None = None) -> int:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
            if auth:
                req.add_header("Authorization", auth)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code

        print("== the HTTP pages want the credential at the request, as tls-check saw ==")
        check("GET /terminal/ with no credential answers 401", get("/terminal/") == 401)
        check("GET /terminal/token with no credential answers 401, so the AuthToken cannot be fetched",
              get("/terminal/token") == 401)
        check("GET /terminal/ with the credential answers 200", get("/terminal/", ttyd_ws.basic(CREDENTIAL)) == 200)

        firsts = {
            "no first message": None,
            "an empty AuthToken": ttyd_ws.hello(""),
            "a wrong AuthToken": ttyd_ws.hello("d3Jvbmc6d3Jvbmc="),
            "no AuthToken at all": ttyd_ws.hello(None),
            "the password unencoded as the AuthToken": ttyd_ws.hello(CREDENTIAL),
            "keystrokes before any AuthToken": b"0id\n",
            "the right AuthToken": ttyd_ws.hello(TOKEN),
        }
        WRONG_BASIC = ttyd_ws.basic("presenter:wrong")

        print("== the tty subprotocol without the Basic credential: refused at the upgrade ==")
        for path in ("/terminal/ws", "/terminal/"):
            for who, auth in (("no Basic credential", None), ("a wrong Basic credential", WRONG_BASIC)):
                for what, msg in firsts.items():
                    r, s, lg = probe(path, msg, auth=auth, protocol="tty")
                    check(f"{path}, tty, {who}, {what}: no 101 and no shell",
                          r.status != 101 and s == 0 and lg == 0, f"status={r.status} starts={s} logged={lg}")

        print("== the tty subprotocol with the Basic credential: the AuthToken is checked too ==")
        for what in ("an empty AuthToken", "a wrong AuthToken", "no AuthToken at all",
                     "the password unencoded as the AuthToken"):
            r, s, lg = probe("/terminal/ws", firsts[what], auth=ttyd_ws.basic(CREDENTIAL), protocol="tty")
            check(f"{what}: 101, then closed 1008 with no output and no shell",
                  r.status == 101 and r.close_code == 1008 and not r.output and s == 0 and lg == 0,
                  f"status={r.status} close={r.close_code} output={r.output[:60]!r} starts={s} logged={lg}")
        r, s, lg = probe("/terminal/ws", firsts["keystrokes before any AuthToken"], auth=ttyd_ws.basic(CREDENTIAL),
                         protocol="tty")
        check("keystrokes before any AuthToken: the connection is dropped, with no shell",
              r.status == 101 and (r.eof or r.close_code is not None) and not r.output and s == 0 and lg == 0,
              f"status={r.status} close={r.close_code} eof={r.eof} starts={s} logged={lg}")

        print("== no subprotocol, as tls-check's probe sends: the 101 #770 saw, bound to no shell ==")
        for path in ("/terminal/ws", "/terminal/"):
            for proto in (None, "", "http-only"):
                for who, auth in (("no Basic credential", None), ("the Basic credential", ttyd_ws.basic(CREDENTIAL))):
                    for what in ("an empty AuthToken", "a wrong AuthToken", "the right AuthToken"):
                        r, s, lg = probe(path, firsts[what], auth=auth, protocol=proto)
                        check(f"{path}, subprotocol {proto!r}, {who}, {what}: no output and no shell",
                              not r.output and s == 0 and lg == 0,
                              f"status={r.status} close={r.close_code} output={r.output[:60]!r} starts={s} logged={lg}")
        r, _, _ = probe("/terminal/", None, auth=None, protocol=None)
        check("an upgrade with no subprotocol and no credential answers 101, as on burritobot-private",
              r.status == 101, f"status={r.status}")
        r, _, _ = probe("/terminal/ws", None, auth=None, protocol="not-tty")
        check("an upgrade asking only for some other subprotocol is refused", r.status != 101, f"status={r.status}")

        print("== the positive control: the right credential and AuthToken start one shell ==")
        r, s, lg = probe("/terminal/ws", firsts["the right AuthToken"], auth=ttyd_ws.basic(CREDENTIAL), protocol="tty")
        check("101, output from the shell, and exactly one start in both the script's record and ttyd's log",
              r.status == 101 and bool(r.output) and s == 1 and lg == 1,
              f"status={r.status} close={r.close_code} output={r.output[:60]!r} starts={s} logged={lg}")
        alive = proc.poll() is None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    check("ttyd ran for the whole test (it did not exit early)", alive,
          f"exit {proc.returncode}: {log.read_text(errors='replace')[-400:]}")

finish()
