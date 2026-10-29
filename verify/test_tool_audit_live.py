# ABOUTME: E2E half of the #190 audit trail: the real workshop-mcp on the pinned mcp library writes attributed
# ABOUTME: lines, and on a cluster the identity survives kagent, agentgateway and the Datadog Agent into Datadog Logs.
# SUITE: e2e
"""Needs uv, which runs this file on the `mcp` library at the version images/workshop-mcp pins and on the
image's Python 3.12 without a global install (#441), kubectl, CONTEXT naming a cluster that
runs the ai-layer and the Datadog Agent, and the public internet to reach the Datadog API. Every missing
prerequisite is a failure with the reason, never a skip.

Library half: runs gitops/ai-layer/workshop-mcp-server.py as it runs in the pod (tool_audit.py beside it on
sys.path), drives it with the real MCP client over streamable HTTP, and reads the audit lines off its stdout.
This is the part the offline test can only fake: that FastMCP really routes tools/call through the override,
and that the identity header really is on the request context the override reads.

Live half, one link of the chain per check:
1. the Agent CR on the cluster carries X-Agent-Identity on its workshop-mcp entry;
2. kagent rendered it into the agent's config Secret, which is what the ADK runtime sends on every MCP request;
3. a tools/call sent through agentgateway with a unique identity, from a one-shot pod in the agent namespace
   that the admin profile's armed Kyverno admits (verify/probe_pod.py), comes out of Datadog Logs with that
   identity, which proves agentgateway forwards the header, workshop-mcp audits it and the Datadog Agent
   (containerCollectAll, gitops/manifests/datadog/datadog-agent.yaml) ships it tagged with its namespace,
   deployment, pod and container. The search runs against the cluster's own org, with the keys the Agent
   itself uses (datadog-secret), on the site its DatadogAgent CR names. Loki and Alloy carried this before
   #474 removed them; Datadog was already receiving the same lines.
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
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import probe_pod  # noqa: E402

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
# The library comes in through `uv run` at the image's pin on the image's Python, never from whatever the host
# has installed (#441). The marker keeps the re-run from re-running itself.
if os.environ.get("WIB_TOOL_AUDIT_UV") != want:
    check("uv is on PATH; it runs the pinned mcp library without a global install", shutil.which("uv") is not None)
    check("images/workshop-mcp/Dockerfile pins mcp==<version>", pin is not None)
    if failures:
        finish()
    sys.stdout.flush()
    os.execvpe("uv", ["uv", "run", "--no-project", "--python", "3.12", "--with", f"mcp=={want}",
                      "python", "-I", __file__], {**os.environ, "WIB_TOOL_AUDIT_UV": want})
try:
    import mcp  # noqa: F401
    from importlib.metadata import version

    have = version("mcp")
except ImportError:
    have = None
check(f"the mcp library is importable (uv run --with 'mcp=={want}')", have is not None)
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
            # A tool's own failure: run_shell raises on a non-zero exit, and FastMCP must turn that into
            # isError. It used to be caught inside the tool and returned as a success holding text (#463).
            results.append(await s.call_tool("run_shell", {"command": "exit 3"}))
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

check("four calls answered, the unknown tool and the failed command as errors",
      len(results) == 4 and not results[0].isError and results[1].isError and results[2].isError
      and not results[3].isError)
# transform/mark_tool_failure matches this text in the next model call's input, so the error result has to
# keep carrying it.
check("the failed command's error result says command FAILED with exit code 3",
      len(results) == 4
      and "command FAILED with exit code 3" in " ".join(getattr(b, "text", "") for b in results[2].content))
check("eight audit lines, a pre and a post per call", len(lines) == 8)
by_call: dict[int, list] = {}
for rec in lines:
    by_call.setdefault(rec.get("call"), []).append(rec)
calls = [by_call[k] for k in sorted(by_call)]
check("each call's pre comes before its post", all([r.get("phase") for r in c] == ["pre", "post"] for c in calls))
check("the calls are numbered in the order they were made",
      [c[0].get("tool_name") for c in calls] == ["check_inventory", "no_such_tool", "run_shell", "check_inventory"])
if len(calls) == 4:
    check("the header reaches the request context: the first three are the agent's",
          all(r.get("agent_identity") == AGENT for c in calls[:3] for r in c))
    check("the call without the header is unattributed", all(r.get("agent_identity") == "unattributed" for r in calls[3]))
    check("the failed call is recorded as an error, with its arguments and the reason",
          calls[1][1].get("outcome") == "error" and calls[1][0].get("tool_input") == {"why": "probe"}
          and "no_such_tool" in calls[1][1].get("error", ""))
    check("the failed command is recorded as an error with its exit code",
          calls[2][1].get("outcome") == "error" and "exit code 3" in calls[2][1].get("error", ""))
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


def kubectl(*args: str, timeout: int = 60, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", CONTEXT, *args], capture_output=True, text=True, timeout=timeout,
                          input=stdin)


def run_pod(pod: dict, timeout: int = 300) -> tuple[str, str]:
    """Create the pod, wait for it to stop, and return its phase and its stdout (or why it never ran). The pod
    is deleted whatever happened."""
    name = pod["metadata"]["name"]
    made = kubectl("create", "-f", "-", stdin=json.dumps(pod))
    if made.returncode != 0:
        return "Refused", made.stderr.strip()
    try:
        phase, deadline = "", time.time() + timeout
        while time.time() < deadline and phase not in ("Succeeded", "Failed"):
            time.sleep(3)
            phase = kubectl("-n", NS, "get", "pod", name, "-o", "jsonpath={.status.phase}").stdout.strip()
        return phase or "Unknown", kubectl("-n", NS, "logs", name).stdout
    finally:
        kubectl("-n", NS, "delete", "pod", name, "--ignore-not-found", "--wait=false")


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

print("== a call through agentgateway lands in Datadog Logs with its identity ==")
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
# The probe runs workshop-mcp's own image, so the armed admin profile admits it (verify/probe_pod.py, #555).
img = kubectl("-n", NS, "get", "deployment", "workshop-mcp", "-o",
              'jsonpath={.spec.template.spec.containers[?(@.name=="shim")].image}')
image = img.stdout.strip() if img.returncode == 0 else ""
check("the workshop-mcp Deployment names the shim image the probe pod runs", bool(image))
if failures:
    finish()
# Searched from a minute before the call: the probe pod can take minutes to schedule, and a window that
# opened after it ran would miss the lines it made.
sent_at = time.time()
phase, answer = run_pod(probe_pod.shell_pod(f"toolaudit-{uuid.uuid4().hex[:6]}", NS, image, script))
if phase != "Succeeded":
    print(f"        the probe pod ended {phase}: {answer.strip()[:300]}")
check("the tools/call through agentgateway was answered", phase == "Succeeded" and "NO_SESSION" not in answer
      and '"result"' in answer)

print("== the Datadog org this cluster ships to ==")
dda = kubectl("-n", "datadog", "get", "datadogagent", "datadog", "-o", "json")
check("the DatadogAgent CR datadog/datadog is readable", dda.returncode == 0)
# The Agent's own default when the CR names no site; the CR here names none (datadog-agent.yaml).
site = (json.loads(dda.stdout).get("spec", {}).get("global", {}).get("site") if dda.returncode == 0 else None) \
    or "datadoghq.com"


def secret_key(key: str) -> str:
    got = kubectl("-n", "datadog", "get", "secret", "datadog-secret", "-o", "jsonpath={.data.%s}" % key)
    return base64.b64decode(got.stdout).decode() if got.returncode == 0 and got.stdout.strip() else ""


api_key, app_key = secret_key("api-key"), secret_key("app-key")
check("datadog-secret holds the api-key and app-key the Agent ships with", bool(api_key and app_key))
if failures:
    finish()


def search(query: str, since: str, cursor: str | None) -> dict:
    """One page of POST /api/v2/logs/events/search. Raises on a non-2xx answer, with Datadog's reason."""
    body = {"filter": {"query": query, "from": since, "to": "now"}, "sort": "timestamp", "page": {"limit": 1000}}
    if cursor:
        body["page"]["cursor"] = cursor
    req = urllib.request.Request(f"https://api.{site}/api/v2/logs/events/search", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json", "DD-API-KEY": api_key,
                                                         "DD-APPLICATION-KEY": app_key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from api.{site}: {e.read()[:200]!r}") from e


def audit_record(log: dict) -> dict:
    """The audit line as workshop-mcp wrote it. Datadog parses a JSON log into the log's attributes; the
    message is read as well, since a line Datadog did not parse keeps its JSON there."""
    rec = dict(log.get("attributes") or {})
    try:
        msg = json.loads(log.get("message") or "")
    except ValueError:
        msg = None
    if isinstance(msg, dict):
        rec.update(msg)
    return rec


# Selected by tag, not by free text over every log in the org: the Agent tags each container's logs with
# its namespace, deployment, pod and container. The identity is matched here rather than in the query, so
# the check does not depend on agent_identity being a facet in a fresh trial org.
query = f"kube_namespace:{NS} kube_deployment:workshop-mcp"
since = str(int((sent_at - 60) * 1000))
found: list[dict] = []
tags: list[list[str]] = []
error = ""
deadline = time.time() + 300
while time.time() < deadline and len(found) < 2:
    found, tags, cursor = [], [], None
    try:
        for _ in range(10):
            page = search(query, since, cursor)
            for log in page.get("data", []):
                a = log.get("attributes", {})
                rec = audit_record(a)
                if rec.get("event") == "tool_invocation" and rec.get("agent_identity") == ident:
                    found.append(rec)
                    tags.append(a.get("tags") or [])
            cursor = page.get("meta", {}).get("page", {}).get("after")
            if not cursor:
                break
        error = ""
    except (RuntimeError, OSError, ValueError) as e:
        error = str(e)
    if len(found) < 2:
        time.sleep(15)
if error:
    print(f"        last Datadog search failed: {error}")
by_phase = {r.get("phase"): r for r in found}
check("Datadog Logs has the call's pre and post lines, once each",
      sorted(r.get("phase") for r in found) == ["post", "pre"])
check("the pre line was written before the post line",
      len(by_phase) == 2 and str(by_phase["pre"].get("ts")) <= str(by_phase["post"].get("ts")))
check("both carry the identity the caller declared, through agentgateway",
      bool(found) and all(r.get("agent_identity") == ident for r in found))
check("both name the tool and the server", bool(found) and all(
    r.get("tool_name") == "check_inventory" and r.get("mcp_server") == "workshop-mcp" for r in found))
check("both are tagged with the pod and container that wrote them", bool(tags) and all(
    any(t.startswith("pod_name:workshop-mcp-") for t in tg) and "kube_container_name:shim" in tg for tg in tags))

finish()
