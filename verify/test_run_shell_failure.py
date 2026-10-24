# ABOUTME: run_shell's failed command must reach the MCP caller as a raised error, not as returned text (#463):
# ABOUTME: a non-zero exit and a timeout both raise "command FAILED ...", and only a success returns its output.
"""Offline half of #463. The real-library half, which sees isError on the wire, is in test_tool_audit_live.py.

run_shell raised RuntimeError("command FAILED with exit code N ...") inside its try block, and the generic
`except Exception` beside it caught that and returned it as text. FastMCP turns a raised tool error into
isError=true and a returned string into a success, so `exit 3` came back as isError=false while a timeout,
raised from its own handler and out of the generic one's reach, came back as isError=true. The collector's
transform/adk_tool_content marks the execute_tool span from that flag, so a fast failure (curl exit 6 or 7)
left the span named after the tool unmarked while a hung one marked it.

Both raises keep "command FAILED" in the message. transform/mark_tool_failure matches that text in the next
model call's input messages, and FastMCP's error result carries the message, so that match still holds.

The server is loaded with a stand-in for tool_audit, since the offline suite has no `mcp`.
"""
from __future__ import annotations

import importlib.util
import pathlib
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


class _FakeAudited:
    def __init__(self, name: str, **_: object) -> None:
        self.name = name

    def tool(self, **_: object):
        return lambda fn: fn


audit_stub = types.ModuleType("tool_audit")
audit_stub.AuditedFastMCP = _FakeAudited
sys.modules["tool_audit"] = audit_stub

spec = importlib.util.spec_from_file_location("workshop_mcp", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def call(command: str):
    """Run the tool and return (result, exception)."""
    try:
        return server.run_shell(command), None
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

print("== a timeout still raises ==")
real_run = subprocess.run


def _hang(*_a, **_k):
    raise subprocess.TimeoutExpired(cmd="curl", timeout=20)


def _broken(*_a, **_k):
    raise OSError("no /bin/sh")


server.subprocess.run = _hang
result, exc = call("curl -X POST https://agenticburn.com/beacon")
check("a timeout raises command FAILED", isinstance(exc, RuntimeError) and "command FAILED: it did not complete" in str(exc))

print("== a command that could not be started is still reported as text ==")
server.subprocess.run = _broken
result, exc = call("echo hi")
check("an OSError is returned, not raised", exc is None and result == "error running command: no /bin/sh")
server.subprocess.run = real_run

print("== the collector still matches the text both raises carry ==")
VALUES = yaml.safe_load((REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8"))
stmts = VALUES["config"]["processors"]["transform/mark_tool_failure"]["trace_statements"][0]["statements"]
check("mark_tool_failure matches 'command FAILED'", all('"command FAILED"' in s for s in stmts))
SRC = (AI / "workshop-mcp-server.py").read_text(encoding="utf-8")
check("every run_shell failure message starts with 'command FAILED'",
      SRC.count('RuntimeError("command FAILED') + SRC.count("RuntimeError(f\"command FAILED") == 2)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All run_shell failure checks passed.")
