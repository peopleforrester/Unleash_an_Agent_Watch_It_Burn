# ABOUTME: Runs the real agentgateway on each MCP bind of both gateway ConfigMaps (#1303) and holds that it answers the
# ABOUTME: standalone GET /mcp with 405 while the MCP POSTs (initialize, tools/list) still reach the MCP server behind it.
# SUITE: e2e (needs the agentgateway binary of the deployed gateway version)
# E2E TIER: tools (no cluster, no AWS: the pinned agentgateway from e2e-tools.lock, run on loopback)
"""Why this exists (#1303).

The agent's MCP client (go-sdk v1.6.1 in kagent 0.10.1) held a GET /mcp stream per session, its RemoteMCPServer timeout
cut it every 30 seconds, and the sixth empty cut failed the session with any tool call in flight: the admin probe's
Challenge 4 miss on watch-it-burn-private. test_mcp_standalone_stream.py holds the config that stops it, a route on each
MCP bind that answers GET /mcp with 405, which go-sdk reads as no standalone stream. That the binary routes it so is
what this checks, on agentgateway-config's 3001 bind and agentgateway-c7-config's 3003 bind as committed:

  * GET /mcp in a live session, with Accept: text/event-stream as go-sdk sends it, is answered 405 by the gateway's
    no-standalone-sse route, and the MCP server behind it never sees a GET;
  * initialize, notifications/initialized and tools/list, which are POSTs, still go through the MCP route to the
    server and come back, so the route that refuses the GET took nothing else.

Each config is taken as committed and changed in three places only: the bind's port is a free loopback port, its MCP
target is a loopback MCP server this test runs, and the tracing policy and the static listeners are off (no collector
here; test_agentgateway_tracing_e2e.py runs the tracing). The routes are not touched.

A negative control runs agentgateway-c7-config with the 405 route taken out and requires the GET to be answered with an
event stream, the one go-sdk held and the timeout cut, so a 405 this test sees is the route's and not the binary's.

The binary is the release's agentgateway-linux-amd64 for the image tag the Deployment runs, pinned in e2e-tools.lock.
Run by hand: AGENTGATEWAY=verify/.tools/bin/agentgateway python3 verify/test_agentgateway_mcp_get_e2e.py
"""
from __future__ import annotations

import copy
import http.client
import http.server
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = REPO / "gitops/ai-layer/agentgateway.yaml"
LOCK = REPO / "verify/e2e-tools.lock"
MCP_BINDS = {"agentgateway-config": (3001, "workshop-mcp"), "agentgateway-c7-config": (3003, "evil-mcp")}
REFUSING_ROUTE = "no-standalone-sse"
IN_USE = "Address in use"
ATTEMPTS = 5
POLL = 0.3
START_POLLS = 600  # 180 s of polls at least, against a start that takes under one on an idle host
REQUEST_TIMEOUT = 30
PROTOCOL = "2025-06-18"

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
    print("\nagentgateway MCP binds: the standalone GET is refused with 405, and MCP POSTs still go through.")
    sys.exit(0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def clean(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class McpServer:
    """A loopback streamable-HTTP MCP server with one tool: JSON replies to POSTs, a session id at initialize, and an
    event stream for a GET, as evil-mcp-shim and workshop-mcp serve one, which it counts. A 405 a client sees can then
    only be the gateway's own."""

    def __init__(self, tool: str) -> None:
        self.gets = 0
        self.methods: list[str] = []
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def reply(self, status: int, body: dict | None, extra: dict[str, str] | None = None) -> None:
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                if body is not None:
                    self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                me.gets += 1
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("connection", "close")
                self.end_headers()
                self.wfile.flush()
                time.sleep(1)

            def do_DELETE(self) -> None:  # noqa: N802
                self.reply(200, None)

            def do_POST(self) -> None:  # noqa: N802
                msg = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                method = msg.get("method", "")
                me.methods.append(method)
                if "id" not in msg:
                    self.reply(202, None)
                elif method == "initialize":
                    self.reply(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {
                        "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                        "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}},
                        {"mcp-session-id": "upstream-session"})
                elif method == "tools/list":
                    self.reply(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [
                        {"name": tool, "description": "a tool", "inputSchema": {"type": "object"}}]}})
                else:
                    self.reply(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {}})

            def log_message(self, *a) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def rpc_result(resp: http.client.HTTPResponse, want_id: int) -> dict | None:
    """The JSON-RPC message with want_id from a reply in either form the transport allows: JSON, or an SSE stream."""
    body = resp.read().decode(errors="replace")
    if resp.getheader("content-type", "").startswith("text/event-stream"):
        msgs = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
    else:
        msgs = [body]
    for m in msgs:
        try:
            j = json.loads(m)
        except ValueError:
            continue
        if isinstance(j, dict) and j.get("id") == want_id:
            return j
    return None


class Client:
    """One MCP client session through the gateway, as go-sdk opens it: initialize, initialized, then calls."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.session = ""

    def request(self, method: str, body: dict | None = None, accept: str = "application/json, text/event-stream"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=REQUEST_TIMEOUT)
        headers = {"accept": accept, "content-type": "application/json", "mcp-protocol-version": PROTOCOL}
        if self.session:
            headers["mcp-session-id"] = self.session
        conn.request(method, "/mcp", body=json.dumps(body) if body is not None else None, headers=headers)
        return conn, conn.getresponse()

    def call(self, rid: int, method: str, params: dict | None = None) -> tuple[int, dict | None]:
        conn, resp = self.request("POST", {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        try:
            if method == "initialize" and resp.getheader("mcp-session-id"):
                self.session = resp.getheader("mcp-session-id")
            return resp.status, rpc_result(resp, rid)
        finally:
            conn.close()

    def notify(self, method: str) -> int:
        conn, resp = self.request("POST", {"jsonrpc": "2.0", "method": method})
        try:
            resp.read()
            return resp.status
        finally:
            conn.close()

    def standalone_get(self) -> tuple[int, str]:
        """The GET go-sdk opens once initialized: its status and content type, read without waiting on a stream."""
        conn, resp = self.request("GET", accept="text/event-stream")
        try:
            return resp.status, resp.getheader("content-type", "")
        finally:
            conn.close()


def initialize(c: Client) -> tuple[int, dict | None]:
    return c.call(1, "initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "test", "version": "1"}})


def run(binary: str, cfg: dict, port: int, tool: str, tmp: pathlib.Path, label: str) -> dict:
    """Start the gateway on cfg's bind `port`, re-pointed at a loopback MCP server, open a session, list its tools and
    send the standalone GET. Retries the start on fresh ports while the one it was given is taken."""
    up = McpServer(tool)
    out: dict = {"started": False, "attempts": [], "log": ""}
    proc = None
    try:
        for attempt in range(ATTEMPTS):
            bind, ready = free_port(), free_port()
            while ready == bind:
                ready = free_port()
            run_cfg = copy.deepcopy(cfg)
            run_cfg.pop("frontendPolicies", None)
            run_cfg.setdefault("config", {}).update(
                {"adminAddr": "off", "statsAddr": "off", "readinessAddr": f"127.0.0.1:{ready}"})
            run_cfg["binds"] = [b for b in run_cfg.get("binds", []) if b.get("port") == port]
            for b in run_cfg["binds"]:
                b["port"] = bind
                for li in b["listeners"]:
                    for r in li["routes"]:
                        for be in r.get("backends", []):
                            for t in (be.get("mcp") or {}).get("targets", []):
                                t["mcp"]["host"] = f"http://127.0.0.1:{up.port}/mcp"
            path = tmp / f"{label}-{attempt}.yaml"
            path.write_text(yaml.safe_dump(run_cfg))
            log = tmp / f"{label}-{attempt}.log"
            with log.open("w") as fh:
                proc = subprocess.Popen([binary, "-f", str(path)], stdout=fh, stderr=subprocess.STDOUT,
                                        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp)})
            out["log_file"], out["config"] = log, run_cfg
            client = Client(bind)
            polls = 0
            while polls < START_POLLS and proc.poll() is None:
                polls += 1
                try:
                    out["init"] = initialize(client)
                    if out["init"][0] == 200 and "initialize" in up.methods:
                        out["started"] = True
                        break
                except OSError:
                    pass
                time.sleep(POLL)
            logged = clean(log.read_text(errors="replace"))
            out["attempts"].append({"bind": bind, "polls": polls, "exit": proc.poll(), "log": logged})
            if out["started"] or proc.poll() is None or IN_USE not in logged:
                break
        if out["started"]:
            try:
                out["initialized"] = client.notify("notifications/initialized")
                out["tools"] = client.call(2, "tools/list")
                out["get"] = client.standalone_get()
                out["session"] = client.session
            except OSError as e:
                out["error"] = f"{type(e).__name__}: {e}"
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if "log_file" in out:
            out["log"] = clean(out["log_file"].read_text(errors="replace"))
        up.server.shutdown()
    out["upstream_gets"], out["upstream_methods"] = up.gets, list(up.methods)
    out["detail"] = (f"{len(out['attempts'])} start(s), exits {[a['exit'] for a in out['attempts']]}; "
                     f"upstream saw {out['upstream_methods']} and {out['upstream_gets']} GET(s); "
                     f"{out.get('error', '')}\n        gateway log:\n{out['log'][-2000:] or '(empty)'}")
    return out


def tool_names(result: tuple[int, dict | None] | None) -> list[str]:
    msg = (result or (0, None))[1] or {}
    return [t.get("name") for t in (msg.get("result") or {}).get("tools", [])]


binary = os.environ.get("AGENTGATEWAY", "")
print("== the agentgateway under test is the deployed version ==")
if not binary or not os.access(binary, os.X_OK):
    check("AGENTGATEWAY names an executable agentgateway (run-e2e-tools.sh points it at verify/.tools/bin/agentgateway)",
          False, f"AGENTGATEWAY={binary!r}: run it through bash verify/run-e2e-tools.sh, or copy the image's tools out (the e2e-image tools verb), then AGENTGATEWAY=verify/.tools/bin/agentgateway")
    finish()
docs = [d for d in yaml.safe_load_all(GATEWAY.read_text(encoding="utf-8")) if d]
deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "agentgateway")
tags = {c["image"].split("@", 1)[0].rsplit(":", 1)[-1] for c in deployment["spec"]["template"]["spec"]["containers"]}
try:
    version = json.loads(subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30).stdout)["version"]
except (ValueError, KeyError, subprocess.TimeoutExpired) as e:
    version = f"unreadable ({e})"
check(f"$AGENTGATEWAY is the version every gateway container runs ({version!r}, {sorted(tags)})", tags == {f"v{version}"})
pinned = next((ln.split()[1] for ln in LOCK.read_text().splitlines() if ln.startswith("agentgateway ")), "")
check(f"and e2e-tools.lock's agentgateway ({pinned!r})", pinned == f"v{version}")

configmaps = {d["metadata"]["name"]: yaml.safe_load(d["data"]["config.yaml"])
              for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] in MCP_BINDS}
check(f"both gateway ConfigMaps are there ({sorted(configmaps)})", set(configmaps) == set(MCP_BINDS))
if failures:
    finish()

with tempfile.TemporaryDirectory() as t:
    tmp = pathlib.Path(t)
    for name, (port, tool) in sorted(MCP_BINDS.items()):
        print(f"== {name} :{port}, its routes as committed ==")
        r = run(binary, configmaps[name], port, tool, tmp, name)
        routes = [x for b in r.get("config", {}).get("binds", []) for li in b["listeners"] for x in li["routes"]]
        check(f"{name}: the bind has the {REFUSING_ROUTE} route ({[x.get('name') for x in routes]})",
              REFUSING_ROUTE in [x.get("name") for x in routes])
        check(f"{name}: the gateway started and initialize reached the MCP server through it", r["started"], r["detail"])
        check(f"{name}: notifications/initialized went through ({r.get('initialized')})",
              r.get("initialized") in (200, 202), r["detail"])
        check(f"{name}: tools/list came back with {tool}'s tool ({tool_names(r.get('tools'))})",
              tool_names(r.get("tools")) == [tool], r["detail"])
        check(f"{name}: the standalone GET /mcp in that session is answered 405 ({r.get('get')})",
              (r.get("get") or (0,))[0] == 405, r["detail"])
        refused = [ln for ln in r["log"].splitlines() if "http.method=GET" in ln and f"route=default/{REFUSING_ROUTE}"
                   in ln and "http.status=405" in ln]
        check(f"{name}: by the {REFUSING_ROUTE} route, as the gateway's log says ({len(refused)} line(s))",
              len(refused) == 1, r["detail"])
        check(f"{name}: and the MCP server behind it saw no GET ({r['upstream_gets']})",
              r["started"] and r["upstream_gets"] == 0, r["detail"])

    print("== the negative control: agentgateway-c7-config without the 405 route ==")
    cfg = copy.deepcopy(configmaps["agentgateway-c7-config"])
    for b in cfg["binds"]:
        for li in b["listeners"]:
            li["routes"] = [x for x in li["routes"] if x.get("name") != REFUSING_ROUTE]
    r = run(binary, cfg, 3003, "evil-mcp", tmp, "control")
    status, ctype = r.get("get") or (0, "")
    check("the gateway started and listed the tool", r["started"] and tool_names(r.get("tools")) == ["evil-mcp"],
          r["detail"])
    check(f"the standalone GET is answered with an event stream, the one go-sdk held ({status}, {ctype!r})",
          status == 200 and ctype.startswith("text/event-stream"), r["detail"])
    check(f"forwarded to the MCP server ({r['upstream_gets']} GET)", r["upstream_gets"] == 1, r["detail"])
finish()
