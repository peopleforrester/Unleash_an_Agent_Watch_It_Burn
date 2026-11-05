# ABOUTME: The real workshop-mcp behind the real agentgateway (:3001 as committed) refuses one turn's third identical
# ABOUTME: call and every call past twenty, keyed on the trace id of the traceparent kagent forwards (#885).
# SUITE: e2e (needs uv for the pinned mcp library and the agentgateway binary of the deployed gateway version)
# E2E TIER: tools (no cluster, no AWS: the pinned agentgateway from e2e-tools.lock, run on loopback)
"""Why this exists (#885).

#644's load replay lost 13 turns to guard-proxy's 120 s PROXY_TIMEOUT, each one the agent calling run_shell again and
again inside the turn. tool_audit.py's turn guard now refuses the third identical call in a turn and every call after
the twentieth, and the turn is the trace id of the request's traceparent. verify/test_turn_guard.py holds the rules
offline against a stand-in FastMCP. What only the real pieces can show is the chain the key travels:

  * kagent keeps ONE MCP session for every conversation (five sessions carried the replay's 504 turns), and the
    header it forwards changes per request (allowedHeaders, read per request off the A2A call). So this drives one
    session and changes traceparent per request, the way kagent does, with an httpx request hook.
  * the request goes through agentgateway v1.7.0 on agentgateway-config's committed :3001 bind and its committed
    frontendPolicies.tracing, so the test sees whether the gateway, which starts a span of its own, keeps the trace id
    on its way to workshop-mcp. A gateway that dropped it or started a new trace would leave every call unlimited.
    It does keep it. A request with no traceparent gets a new trace from the gateway, so each such call is a turn of
    its own and is never limited, which is what every call on a cluster is until kagent forwards the header.
  * FastMCP really answers a refusal raised from the call_tool override as an isError result, and the refused
    command really does not run (each run appends a line to a file the test counts).

The :3001 config is taken as committed and changed in three places only: the workshop-mcp target's host becomes the
loopback server this test runs, the bind port becomes a free one, and the collector's host:port becomes a loopback
OTLP receiver. Run by hand: AGENTGATEWAY=verify/.tools/bin/agentgateway python3 verify/test_turn_guard_e2e.py
"""
from __future__ import annotations

import asyncio
import http.server
import json
import os
import pathlib
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
AI = REPO / "gitops/ai-layer"
GATEWAY = AI / "agentgateway.yaml"
LOCK = REPO / "verify/e2e-tools.lock"
COLLECTOR = "otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4318"
WORKSHOP_MCP = "http://workshop-mcp.agent.svc.cluster.local:8000/mcp"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def finish() -> None:
    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nturn guard: agentgateway keeps the turn's trace id, and workshop-mcp refuses the repeats in it.")
    sys.exit(0)


print("== prerequisites ==")
binary = os.environ.get("AGENTGATEWAY", "")
pin = re.search(r"'mcp==([0-9.]+)'", (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8"))
want = pin.group(1) if pin else "?"
# The library comes in through `uv run` at the image's pin on the image's Python, never from the host (#441). The
# marker keeps the re-run from re-running itself.
if os.environ.get("WIB_TURN_GUARD_UV") != want:
    check("AGENTGATEWAY names an executable agentgateway (run-e2e-tools.sh points it at verify/.tools/bin/agentgateway)",
          bool(binary) and os.access(binary, os.X_OK),
          f"AGENTGATEWAY={binary!r}: run bash verify/fetch-e2e-tools.sh, then AGENTGATEWAY=verify/.tools/bin/agentgateway")
    check("uv is on PATH; it runs the pinned mcp library without a global install", shutil.which("uv") is not None)
    check("images/workshop-mcp/Dockerfile pins mcp==<version>", pin is not None)
    if failures:
        finish()
    sys.stdout.flush()
    os.execvpe("uv", ["uv", "run", "--no-project", "--python", "3.12", "--with", f"mcp=={want}", "--with", "pyyaml",
                      "python", "-I", __file__], {**os.environ, "WIB_TURN_GUARD_UV": want})

import yaml  # noqa: E402  (from the uv environment, beside the pinned mcp)

try:
    from importlib.metadata import version

    import httpx  # noqa: F401
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    have = version("mcp")
except ImportError as e:
    have = None
    print(f"        {e}")
check(f"the mcp library is importable (uv run --with 'mcp=={want}')", have is not None)
check(f"it is the version the workshop-mcp image pins ({want}; found {have})", have == want)
docs = [d for d in yaml.safe_load_all(GATEWAY.read_text(encoding="utf-8")) if d]
deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "agentgateway")
tags = {c["image"].split("@", 1)[0].rsplit(":", 1)[-1] for c in deployment["spec"]["template"]["spec"]["containers"]}
try:
    gw_version = json.loads(subprocess.run([binary, "--version"], capture_output=True, text=True,
                                           timeout=30).stdout)["version"]
except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as e:
    gw_version = f"unreadable ({e})"
check(f"$AGENTGATEWAY is the version the gateway Deployment runs ({gw_version!r}, {sorted(tags)})",
      tags == {f"v{gw_version}"})
pinned = next((ln.split()[1] for ln in LOCK.read_text().splitlines() if ln.startswith("agentgateway ")), "")
check(f"and e2e-tools.lock's agentgateway ({pinned!r})", pinned == f"v{gw_version}")
if failures:
    finish()

sys.path.insert(0, str(AI))
import tool_audit  # noqa: E402

MAX_SAME, MAX_CALLS = tool_audit.MAX_SAME_CALLS, tool_audit.MAX_TURN_CALLS


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, proc: subprocess.Popen, seconds: float = 30) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline and proc.poll() is None:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


class Receiver:
    """A loopback OTLP/HTTP receiver, so the committed tracing has a collector to export to."""

    def __init__(self) -> None:
        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("content-length", 0)))
                self.send_response(200)
                self.send_header("content-type", "application/x-protobuf")
                self.send_header("content-length", "0")
                self.end_headers()

            def log_message(self, *a) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def gateway_config(mcp_port: int, bind: int, rx_port: int) -> dict:
    cm = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "agentgateway-config")
    cfg = yaml.safe_load(cm["data"]["config.yaml"])
    bind3001 = next(b for b in cfg["binds"] if b["port"] == 3001)
    text = yaml.safe_dump({**cfg, "binds": [bind3001]})
    check("the :3001 bind fronts workshop-mcp at its Service address", WORKSHOP_MCP in text)
    check("the gateway config sends its spans to the collector", COLLECTOR in text)
    cfg = yaml.safe_load(text.replace(WORKSHOP_MCP, f"http://127.0.0.1:{mcp_port}/mcp")
                         .replace(COLLECTOR, f"127.0.0.1:{rx_port}"))
    cfg["binds"][0]["port"] = bind
    cfg.setdefault("config", {}).update(
        {"adminAddr": "off", "statsAddr": "off", "readinessAddr": f"127.0.0.1:{free_port()}"})
    return cfg


SERVE = f"""
import importlib.util, sys
sys.path.insert(0, {str(AI)!r})
spec = importlib.util.spec_from_file_location("workshop_mcp", {str(AI / "workshop-mcp-server.py")!r})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.mcp.settings.host = "127.0.0.1"
m.mcp.settings.port = int(sys.argv[1])
m.mcp.run(transport="streamable-http")
"""


def text_of(result) -> str:
    return " ".join(getattr(b, "text", "") or "" for b in result.content)


async def drive(url: str, ran: pathlib.Path, turns: dict[str, str]) -> dict[str, list]:
    """One MCP session for every turn, as kagent keeps; each request carries the traceparent of the turn it is in."""
    current = {"traceparent": None}

    async def stamp(request) -> None:
        if current["traceparent"]:
            request.headers["traceparent"] = current["traceparent"]
        else:
            request.headers.pop("traceparent", None)

    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, follow_redirects=True,
                                 event_hooks={"request": [stamp]})

    def turn(name: str | None) -> None:
        # A new parent span id on every request, as each hop does; the trace id is what stays.
        current["traceparent"] = None if name is None else f"00-{turns[name]}-{secrets.token_hex(8)}-01"

    counted = f"echo run >> {ran}; echo counted"
    out: dict[str, list] = {}
    async with streamablehttp_client(url, headers={"X-Agent-Identity": "workshop-agent"},
                                     httpx_client_factory=factory) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            turn("a")
            out["a"] = [await s.call_tool("run_shell", {"command": counted}) for _ in range(MAX_SAME + 2)]
            turn("b")
            out["b"] = [await s.call_tool("run_shell", {"command": "echo 'unclosed"}) for _ in range(MAX_SAME + 1)]
            # An earlier turn's calls do not count against a later one in the same session.
            turn("c")
            out["c"] = [await s.call_tool("run_shell", {"command": counted})]
            turn("d")
            out["d"] = [await s.call_tool("search_web", {"query": f"salsa {i}"}) for i in range(MAX_CALLS)]
            out["d"].append(await s.call_tool("run_shell", {"command": counted}))
            # Two turns interleaved on the one session, as two phones' turns are: each keeps its own count.
            first = []
            for _ in range(MAX_SAME + 1):
                turn("e")
                first.append(await s.call_tool("check_inventory", {}))
                turn("f")
                first.append(await s.call_tool("get_order_history", {}))
            out["ef"] = first
            turn(None)
            out["none"] = [await s.call_tool("run_shell", {"command": counted}) for _ in range(MAX_SAME + 2)]
    return out


with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    mcp_port, bind, rx = free_port(), free_port(), Receiver()
    cfg_path = tmp / "agentgateway.yaml"
    cfg_path.write_text(yaml.safe_dump(gateway_config(mcp_port, bind, rx.port)))
    ran = tmp / "ran.txt"
    turns = {k: secrets.token_hex(16) for k in "abcdef"}
    mcp_log, gw_log = tmp / "mcp.log", tmp / "gw.log"
    print("== workshop-mcp behind agentgateway on loopback ==")
    with mcp_log.open("w") as mout, gw_log.open("w") as gout:
        mcp_proc = subprocess.Popen([sys.executable, "-c", SERVE, str(mcp_port)], stdout=mout, stderr=subprocess.STDOUT,
                                    env={**os.environ, "WORKSHOP_DATA_DIR": f"{tmp}/data", "KUBE_API": "http://127.0.0.1:9"})
        gw_proc = subprocess.Popen([binary, "-f", str(cfg_path)], stdout=gout, stderr=subprocess.STDOUT,
                                   env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp),
                                        "OTEL_SERVICE_NAME": "burritobot-gateway"})
        results: dict[str, list] = {}
        try:
            up = wait_port(mcp_port, mcp_proc) and wait_port(bind, gw_proc)
            check("workshop-mcp and the gateway both start", up,
                  mcp_log.read_text(errors="replace")[-1500:] + gw_log.read_text(errors="replace")[-1500:])
            if up:
                results = asyncio.run(drive(f"http://127.0.0.1:{bind}/mcp", ran, turns))
        finally:
            for p in (gw_proc, mcp_proc):
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
    rx.server.shutdown()
    lines = []
    for raw in mcp_log.read_text(errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("event") == "tool_invocation":
            lines.append(rec)
    runs = len(ran.read_text().splitlines()) if ran.exists() else 0

if not results:
    finish()

print("== agentgateway keeps the turn's trace id on its way to workshop-mcp ==")
seen = {rec.get("turn") for rec in lines}
check("every turn's trace id reaches workshop-mcp's audit lines through the gateway",
      set(turns.values()) <= seen, f"turns seen: {sorted(str(s) for s in seen)}")
# A request that brings no traceparent gets a new trace from the gateway (randomSampling true), so each untraced call
# reaches workshop-mcp as a turn of one call. That is every call on a cluster before kagent forwards the header, and
# it is why such a call is never limited: no two of them share a turn.
untraced = [rec.get("turn") for rec in lines if rec.get("phase") == "pre" and rec.get("turn") not in turns.values()]
check(f"each untraced call arrives under a trace id of its own that the gateway started ({len(untraced)} calls)",
      len(untraced) == MAX_SAME + 2 and len(set(untraced)) == len(untraced)
      and all(tool_audit.turn_of(f"00-{u}-{'1' * 16}-01") == u for u in untraced), str(untraced))

print(f"== one turn: the same call runs {MAX_SAME} times, then is refused without running ==")
a = results["a"]
check(f"the first {MAX_SAME} identical run_shell calls run and succeed", all(not r.isError for r in a[:MAX_SAME]))
check("the next ones are error results saying they were refused and not run",
      all(r.isError and "refused, not run" in text_of(r) for r in a[MAX_SAME:]), text_of(a[-1]))
check("the refusal says it ran before and tells the model to change it or answer",
      f"already run {MAX_SAME} times in this turn" in text_of(a[MAX_SAME]) and "tell the guest" in text_of(a[MAX_SAME]),
      text_of(a[MAX_SAME]))

print("== a command the shell cannot parse says why, and its repeat quotes that failure ==")
b = results["b"]
check("the unparsable command fails as an error result with dash's message and the hint",
      all(r.isError for r in b) and "Syntax error: Unterminated quoted string" in text_of(b[0])
      and "here-document" in text_of(b[0]), text_of(b[0]))
check("the third send is refused and quotes the failure it would repeat",
      "refused, not run" in text_of(b[-1]) and "failed every time" in text_of(b[-1])
      and "Unterminated quoted string" in text_of(b[-1]), text_of(b[-1]))

print("== another turn on the same session starts its own count ==")
check("the next turn runs the command turn a stopped", not results["c"][0].isError, text_of(results["c"][0]))

print(f"== a turn runs at most {MAX_CALLS} calls ==")
d = results["d"]
check(f"{MAX_CALLS} distinct calls in one turn all run", all(not r.isError for r in d[:MAX_CALLS]))
check("the next call is refused, telling the model to answer now",
      d[MAX_CALLS].isError and "the most one reply may make" in text_of(d[MAX_CALLS]), text_of(d[MAX_CALLS]))

print("== two turns interleaved on one session keep separate counts ==")
ef = results["ef"]
check("each turn's first two calls run although the other turn's calls fall between them",
      all(not r.isError for r in ef[:2 * MAX_SAME]))
check("and each turn's third is refused", all(r.isError and "refused, not run" in text_of(r) for r in ef[2 * MAX_SAME:]))

print("== a call with no traceparent is not limited ==")
check("every one of the untraced repeats runs", all(not r.isError for r in results["none"]))

print("== a refused call never runs, and the trail says so ==")
expected = MAX_SAME + 1 + (MAX_SAME + 2)
check(f"the counted command ran {expected} times: twice in turn a, once in turn c, four times untraced ({runs})",
      runs == expected)
refused = [rec for rec in lines if rec.get("phase") == "refused"]
pres = [rec for rec in lines if rec.get("phase") == "pre"]
want_refused = (MAX_SAME + 2 - MAX_SAME) + 1 + 1 + 2
check(f"{want_refused} calls are logged as refused ({len(refused)})", len(refused) == want_refused)
check("a refused call writes no pre line, so nothing that counts pre lines counts it",
      not ({r.get("call") for r in refused} & {p.get("call") for p in pres}))
check("a refused line carries its turn, its arguments and the refusal",
      all(r.get("turn") in turns.values() and "tool_input" in r and "refused, not run" in r.get("refusal", "")
          for r in refused))
finish()
