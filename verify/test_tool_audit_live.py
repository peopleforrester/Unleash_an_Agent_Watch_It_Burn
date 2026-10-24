# ABOUTME: E2E half of the #190 audit trail: the real workshop-mcp on the pinned mcp library writes attributed
# ABOUTME: lines, and on a cluster the identity survives kagent, agentgateway and Alloy all the way into Loki.
# SUITE: e2e
"""Needs the `mcp` library at the version images/workshop-mcp pins, kubectl, and CONTEXT naming a cluster
that runs the ai-layer and Loki. Every missing prerequisite is a failure with the reason, never a skip.

Library half: runs gitops/ai-layer/workshop-mcp-server.py as it runs in the pod (tool_audit.py beside it on
sys.path), drives it with the real MCP client over streamable HTTP, and reads the audit lines off its stdout.
This is the part the offline test can only fake: that FastMCP really routes tools/call through the override,
and that the identity header really is on the request context the override reads.

Live half, one link of the chain per check:
1. the Agent CR on the cluster carries X-Agent-Identity on its workshop-mcp entry;
2. kagent rendered it into the agent's config Secret, which is what the ADK runtime sends on every MCP request;
3. a tools/call sent through agentgateway with a unique identity comes out of Loki with that identity, which
   proves agentgateway forwards the header, workshop-mcp audits it and Alloy ships it on a stream labelled
   with its namespace, app, pod and container.
The model is not asked to call a tool: whether it does is up to the model, and a check that depends on it
would be measuring the model, not the trail.

Usage: CONTEXT=<kube-context> [NAMESPACE=agent] python3 verify/test_tool_audit_live.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
CONTEXT = os.environ.get("CONTEXT", "")
NS = os.environ.get("NAMESPACE", "agent")
AGENT = "workshop-agent"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def finish() -> None:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All live tool-audit checks passed.")


print("== library prerequisites ==")
pin = re.search(r"'mcp==([0-9.]+)'", (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8"))
want = pin.group(1) if pin else "?"
try:
    import mcp  # noqa: F401
    from importlib.metadata import version

    have = version("mcp")
except ImportError:
    have = None
check(f"the mcp library is importable (pip install 'mcp=={want}')", have is not None)
check(f"it is the version the workshop-mcp image pins ({want}; found {have})", have == want)
if failures:
    finish()


# ----- library half ------------------------------------------------------------------------------------
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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def drive(url: str) -> list:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    results = []
    async with streamablehttp_client(url, headers={"X-Agent-Identity": AGENT}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            results.append(await s.call_tool("check_inventory", {}))
            # An unknown tool is the one call FastMCP itself fails, so it exercises the error path without
            # depending on any tool's own error handling.
            results.append(await s.call_tool("no_such_tool", {"why": "probe"}))
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            results.append(await s.call_tool("check_inventory", {}))
    return results


print("== the real workshop-mcp writes the trail ==")
with tempfile.TemporaryDirectory() as tmp:
    port = free_port()
    out_path = pathlib.Path(tmp) / "stdout.log"
    with open(out_path, "w") as out:
        proc = subprocess.Popen([sys.executable, "-c", SERVE, str(port)], stdout=out, stderr=subprocess.DEVNULL,
                                env={**os.environ, "WORKSHOP_DATA_DIR": f"{tmp}/data"})
    try:
        deadline = time.time() + 30
        while time.time() < deadline and proc.poll() is None:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
        check("workshop-mcp starts with tool_audit.py beside it", proc.poll() is None)
        results = asyncio.run(drive(f"http://127.0.0.1:{port}/mcp")) if proc.poll() is None else []
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    lines = []
    for raw in out_path.read_text().splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("event") == "tool_invocation":
            lines.append(rec)

check("three calls answered, the unknown tool as an error",
      len(results) == 3 and not results[0].isError and results[1].isError and not results[2].isError)
check("six audit lines, a pre and a post per call", len(lines) == 6)
by_call: dict[int, list] = {}
for rec in lines:
    by_call.setdefault(rec.get("call"), []).append(rec)
calls = [by_call[k] for k in sorted(by_call)]
check("each call's pre comes before its post", all([r.get("phase") for r in c] == ["pre", "post"] for c in calls))
check("the calls are numbered in the order they were made",
      [c[0].get("tool_name") for c in calls] == ["check_inventory", "no_such_tool", "check_inventory"])
if len(calls) == 3:
    check("the header reaches the request context: the first two are the agent's",
          all(r.get("agent_identity") == AGENT for c in calls[:2] for r in c))
    check("the call without the header is unattributed", all(r.get("agent_identity") == "unattributed" for r in calls[2]))
    check("the failed call is recorded as an error, with its arguments and the reason",
          calls[1][1].get("outcome") == "error" and calls[1][0].get("tool_input") == {"why": "probe"}
          and "no_such_tool" in calls[1][1].get("error", ""))
    check("a successful call is recorded as ok with its result size",
          calls[0][1].get("outcome") == "ok" and calls[0][1].get("result_chars", 0) > 0)
    check("every line names the server as workshop-mcp", all(r.get("mcp_server") == "workshop-mcp" for r in lines))
    check("every line carries the MCP session and request id",
          all(r.get("mcp_session_id") and r.get("request_id") for c in calls for r in c))
    check("the inventory itself is not in the trail", all("ghost_pepper" not in json.dumps(r) for r in lines))


# ----- live half ---------------------------------------------------------------------------------------
print("== cluster prerequisites ==")
check("kubectl is on PATH", shutil.which("kubectl") is not None)
check("CONTEXT names the cluster to check (it is never guessed)", bool(CONTEXT))
if failures:
    finish()


def kubectl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", CONTEXT, *args], capture_output=True, text=True, timeout=timeout)


def find_headers(node, url_part: str):
    """Every `headers` map in the rendered config that sits beside a url containing url_part."""
    if isinstance(node, dict):
        if isinstance(node.get("headers"), dict) and url_part in str(node.get("url", "")):
            yield node["headers"]
        for v in node.values():
            yield from find_headers(v, url_part)
    elif isinstance(node, list):
        for v in node:
            yield from find_headers(v, url_part)


print(f"== on {CONTEXT}: the Agent CR declares its identity ==")
got = kubectl("-n", NS, "get", "agent", AGENT, "-o", "json")
check(f"the {AGENT} Agent is readable", got.returncode == 0)
agent = json.loads(got.stdout) if got.returncode == 0 else {}
tools = {(t.get("mcpServer") or {}).get("name"): t for t in agent.get("spec", {}).get("declarative", {}).get("tools", [])}
check("its workshop-mcp entry carries X-Agent-Identity: workshop-agent",
      {"name": "X-Agent-Identity", "value": AGENT} in (tools.get("workshop-mcp") or {}).get("headersFrom", []))

print("== kagent rendered it into the config the agent runtime sends ==")
rms = kubectl("-n", NS, "get", "remotemcpserver", "workshop-mcp", "-o", "jsonpath={.spec.url}")
check("the workshop-mcp RemoteMCPServer is readable", rms.returncode == 0 and rms.stdout.strip() != "")
host = urllib.parse.urlparse(rms.stdout.strip()).netloc.split(".")[0] if rms.returncode == 0 else "?"
sec = kubectl("-n", NS, "get", "secret", AGENT, "-o", "jsonpath={.data.config\\.json}")
check(f"kagent's config Secret {AGENT} has config.json", sec.returncode == 0 and sec.stdout.strip() != "")
cfg = json.loads(base64.b64decode(sec.stdout)) if sec.returncode == 0 and sec.stdout.strip() else {}
rendered = list(find_headers(cfg, host))
check(f"the connection to {host} sends X-Agent-Identity: {AGENT}",
      any(h.get("X-Agent-Identity") == AGENT for h in rendered))

print("== a call through agentgateway lands in Loki with its identity ==")
ident = f"verify-tool-audit-{uuid.uuid4().hex[:10]}"
init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "verify-tool-audit", "version": "1"}}})
call = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "check_inventory", "arguments": {}}})
script = f"""
U={rms.stdout.strip()!r}
set -- -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -H 'X-Agent-Identity: {ident}'
SID=$(curl -s -D - -o /dev/null -X POST "$U" "$@" -d '{init}' | tr -d '\\r' | awk -F': ' 'tolower($1)=="mcp-session-id"{{print $2}}')
[ -n "$SID" ] || {{ echo NO_SESSION; exit 1; }}
curl -s -o /dev/null -X POST "$U" "$@" -H "mcp-session-id: $SID" -d '{{"jsonrpc":"2.0","method":"notifications/initialized"}}'
curl -s -X POST "$U" "$@" -H "mcp-session-id: $SID" -d '{call}'
"""
sent = kubectl("run", f"toolaudit-{uuid.uuid4().hex[:6]}", "--rm", "-i", "--restart=Never", "-n", NS,
               "--pod-running-timeout=180s", "--image=curlimages/curl:8.10.1", "--command", "--", "sh", "-c", script,
               timeout=300)
check("the tools/call through agentgateway was answered", sent.returncode == 0 and "NO_SESSION" not in sent.stdout
      and '"result"' in sent.stdout)

# Selected by stream, not by line-filtering every stream: Alloy's discovery.relabel puts namespace and app on
# each stream (#464). A config that loses the relabel finds nothing here, since every stream is then only job.
query = '{namespace="%s", app="workshop-mcp"} |= "%s" | json' % (NS, ident)
found: list[dict] = []
labels: list[dict] = []
deadline = time.time() + 120
while time.time() < deadline and len(found) < 2:
    start = str(int((time.time() - 900) * 1e9))
    path = ("/api/v1/namespaces/monitoring/services/loki:3100/proxy/loki/api/v1/query_range?"
            + urllib.parse.urlencode({"query": query, "start": start, "limit": "50", "direction": "forward"}))
    got = kubectl("get", "--raw", path)
    if got.returncode == 0:
        streams = json.loads(got.stdout).get("data", {}).get("result", [])
        found = [json.loads(v[1]) for s in streams for v in s.get("values", [])]
        labels = [s.get("stream", {}) for s in streams]
    if len(found) < 2:
        time.sleep(10)
check("Loki has the call's pre and post lines", [r.get("phase") for r in found] == ["pre", "post"])
check("both carry the identity the caller declared, through agentgateway",
      bool(found) and all(r.get("agent_identity") == ident for r in found))
check("both name the tool and the server", bool(found) and all(
    r.get("tool_name") == "check_inventory" and r.get("mcp_server") == "workshop-mcp" for r in found))
check("their stream is labelled with the pod and container that wrote them", bool(labels) and all(
    lb.get("pod", "").startswith("workshop-mcp-") and lb.get("container") == "shim" for lb in labels))

finish()
