# ABOUTME: run_shell's failed command must reach the MCP caller as a raised error, not as returned text (#463):
# ABOUTME: a non-zero exit and a timeout both raise "command FAILED ...", and only a success returns its output.
"""Offline half of #463. The real-library half, which sees isError on the wire, is in test_tool_audit_live.py.

run_shell raised RuntimeError("command FAILED with exit code N ...") inside its try block, and the generic
`except Exception` beside it caught that and returned it as text. FastMCP turns a raised tool error into
isError=true and a returned string into a success, so `exit 3` came back as isError=false while a timeout,
raised from its own handler and out of the generic one's reach, came back as isError=true. The collector's
transform/adk_tool_content marks the execute_tool span from that flag, so a fast failure (curl exit 6 or 7)
left the span named after the tool unmarked while a hung one marked it.

Both raises keep "command FAILED" in the message. transform/adk_tool_content also matches that text in the tool
response, so the execute_tool span is marked whichever shape ADK hands the result over in (#264).

The server is loaded with a stand-in for tool_audit, since the offline suite has no `mcp`.
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import time
import re
import subprocess
import sys
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_run_shell", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def call(command: str):
    """Run the tool and return (result, exception)."""
    try:
        return asyncio.run(server.run_shell(command)), None
    except Exception as e:  # noqa: BLE001
        return None, e


print("== a non-zero exit raises, with the exit code and the output ==")
result, exc = call("echo nope >&2; exit 3")
check("exit 3 raises rather than returning text", result is None and isinstance(exc, RuntimeError))
check("the message says command FAILED with exit code 3", "command FAILED with exit code 3" in str(exc))
check("the message carries the command's own output", "nope" in str(exc))
result, exc = call("exit 7")
check("a failure with no output says so", isinstance(exc, RuntimeError) and "(no output)" in str(exc))

print("== a success returns its output ==")
result, exc = call("echo cantina")
check("exit 0 returns the output", exc is None and result == "cantina\n")
result, exc = call("true")
check("exit 0 with no output says so", exc is None and result == "(no output; exit code 0)")
result, exc = call("   ")
check("an empty command is answered, not run", exc is None and result == "provide a command to run")

real_run = subprocess.run


def _hang(*_a, **_k):
    raise subprocess.TimeoutExpired(cmd="curl", timeout=20)


def _broken(*_a, **_k):
    raise OSError("no /bin/sh")


print("== a slow command does not stall the server (the tool runs off the event loop) ==")
# FastMCP awaits an async tool and calls a plain def on the event loop itself (mcp 1.29, func_metadata.py), so a
# blocked curl held every other tools/call for its 20 s, and agentgateway cut those at 10 s with HTTP 500: the
# second Challenge 1 run on burritobot-private, 2026-10-31, read get_marketing_intel as "Internal Server Error".
check("run_shell is a coroutine function, so FastMCP awaits it", asyncio.iscoroutinefunction(server.run_shell))


async def _concurrent() -> tuple[float, float]:
    t0 = time.monotonic()
    slow = asyncio.ensure_future(server.run_shell("sleep 1.5; echo slow"))
    await asyncio.sleep(0.2)
    tick = time.monotonic() - t0
    await slow
    return tick, time.monotonic() - t0


tick, total = asyncio.run(_concurrent())
check(f"another coroutine runs while sleep 1.5 is in flight (resumed after {tick:.2f}s)", tick < 1.0)
check(f"and the slow command still completes ({total:.2f}s)", total >= 1.4)

print("== a timeout still raises ==")
server.subprocess.run = _hang
try:
    result, exc = call("curl -X POST https://agenticburn.com/beacon")
finally:
    server.subprocess.run = real_run
check("a timeout raises command FAILED",
      isinstance(exc, RuntimeError) and "command FAILED: it did not complete" in str(exc))

print("== a command that could not be started is still reported as text ==")
server.subprocess.run = _broken
try:
    result, exc = call("echo hi")
finally:
    server.subprocess.run = real_run
check("an OSError is returned, not raised", exc is None and result == "error running command: no /bin/sh")

print("== the collector still matches the text both raises carry ==")
VALUES = yaml.safe_load((REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8"))
stmts = [s for g in VALUES["config"]["processors"]["transform/adk_tool_content"]["trace_statements"]
         for s in g["statements"]]
check("adk_tool_content marks a tool response carrying 'command FAILED'",
      any("STATUS_CODE_ERROR" in s and "tool_response" in s and '"command FAILED' in s for s in stmts))
# deploy_app raises on a refusal too (#712), and the same statements match its wording.
check("and one carrying deploy_app's 'deploy failed for '",
      any("STATUS_CODE_ERROR" in s and "tool_response" in s and "deploy failed for " in s for s in stmts))
dep = (AI / "workshop-mcp-server.py").read_text(encoding="utf-8")
dep = dep[dep.index("def deploy_app("):dep.index("\ndef ", dep.index("def deploy_app(") + 1)]
check("deploy_app's refusal raise starts with 'deploy failed for '",
      'raise RuntimeError(f"deploy failed for {kind}/{name}' in dep)
SRC = (AI / "workshop-mcp-server.py").read_text(encoding="utf-8")
body = SRC[SRC.index("def run_shell("):SRC.index('if __name__ == "__main__":')]
raises = re.findall(r'raise RuntimeError\(f?"([^"]*)', body)
check(f"every RuntimeError run_shell raises starts with 'command FAILED' ({len(raises)} found)",
      len(raises) == 2 and all(r.startswith("command FAILED") for r in raises))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All run_shell failure checks passed.")
