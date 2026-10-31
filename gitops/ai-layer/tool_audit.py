# ABOUTME: Per-agent tool-invocation audit trail for workshop-mcp: one JSON line on stdout per tool call
# ABOUTME: phase, tagged with the calling agent's identity. The Datadog Agent ships it with the pod logs.
"""Who called which tool, with what, in what order (#190).

Ported from the sister repo's Claude Code audit hook (packt-agentic-devops `.claude/hooks/audit.sh`), which
writes one JSON line per PreToolUse/PostToolUse event tagged `agent_identity`. Here the agent is the kagent
`workshop-agent` and kagent has no tool hook, so the hook lives in the server that does the damage:
workshop-mcp builds `AuditedFastMCP` instead of `FastMCP`, and every `tools/call` writes a `pre` line before
the tool runs and a `post` line after. Only the hook is ported. The sister's permission block, which set
`bypassPermissions` and so made its own deny lists decorative, is deliberately not.

evil-mcp-shim does NOT use this, on purpose. It stays dark for the reason recorded on #18 (PROGRESS.md,
2026-06-24): a rogue server that helpfully audits itself undermines the lesson. Its calls are attributed
from the caller's side, by the agent's own execute_tool spans.

The `pre` line is written first and flushed on its own because the tools that matter most are the ones that
may never return: a `run_shell` fork bomb (C4) can take the pod down before any `post` line exists, and the
attribution question is exactly "which agent started that".

Identity comes from the `X-Agent-Identity` request header. The Agent CR sets it on its workshop-mcp tool
entry with `headersFrom` (gitops/workshop-agent/agent.yaml); kagent sends it on every MCP request, and
agentgateway, which workshop-mcp is reached through, forwards request headers to MCP targets. It is DECLARED, not authenticated: it says which agent config made the call,
which is the attribution question, and a caller without it is logged as `unattributed` rather than guessed.
That is itself a finding, since the only callers without it are things that are not the agent, such as a
student or a challenge script dialling the MCP server directly.

Tool RESULTS are deliberately not logged, only their size. The results are the leaked values themselves
(the recipe, the CEO's record, the FAKE-...-sentinel strings), and every container log here also goes to
Datadog, which would put them outside the span redaction the observability act teaches. Arguments are
logged, clipped, because the arguments are the attack: the shell command, the manifest, the vault entry.

Query, in Datadog Log Explorer (the Agent collects every container's logs and tags them with namespace,
deployment, pod and container; Datadog parses the JSON line into attributes; #474):
    kube_namespace:agent kube_deployment:workshop-mcp @event:tool_invocation
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

EVENT = "tool_invocation"
IDENTITY_HEADER = "x-agent-identity"
UNATTRIBUTED = "unattributed"
# Long enough for a whole curl command or a one-object manifest, short enough that a pasted blob cannot
# turn one audit line into megabytes.
MAX_ARG_CHARS = 2000

# Per-process call counter. Pairs a call's pre and post lines, and orders calls that share a millisecond.
_calls = itertools.count(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clip(value: Any) -> Any:
    """Bound every string in a tool's arguments to MAX_ARG_CHARS, keeping the structure."""
    if isinstance(value, str):
        if len(value) <= MAX_ARG_CHARS:
            return value
        return f"{value[:MAX_ARG_CHARS]}...[+{len(value) - MAX_ARG_CHARS} chars]"
    if isinstance(value, dict):
        return {str(k): clip(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v) for v in value]
    return value


def caller(ctx: Any) -> dict[str, Any]:
    """Identity, MCP session and JSON-RPC id of the request a tool call arrived on."""
    try:
        rc = ctx.request_context
    except ValueError:  # no request in flight: called outside the transport, e.g. from a test harness
        rc = None
    request = getattr(rc, "request", None)
    headers = getattr(request, "headers", None) or {}
    identity = (headers.get(IDENTITY_HEADER) or "").strip()
    return {
        "agent_identity": identity or UNATTRIBUTED,
        "mcp_session_id": headers.get("mcp-session-id"),
        "request_id": None if rc is None else str(rc.request_id),
    }


def emit(record: dict[str, Any]) -> None:
    """One compact JSON line on stdout, flushed now: stdout is block-buffered in a container, and a line
    still in the buffer when the pod dies is a line Datadog never gets."""
    sys.stdout.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
    sys.stdout.flush()


def _result_chars(result: Any) -> int:
    """Size of a tool's text output. FastMCP returns a list of content blocks, a (blocks, structured)
    tuple when the tool has an output schema, which every `-> str` tool does, or a CallToolResult."""
    if isinstance(result, tuple):
        result = result[0]
    result = getattr(result, "content", result)
    if isinstance(result, dict):
        return len(json.dumps(result, default=str))
    return sum(len(getattr(block, "text", "") or "") for block in result or [])


class AuditedFastMCP(FastMCP):
    """FastMCP that writes the audit trail for every tool call. FastMCP registers `self.call_tool` as the
    `tools/call` handler in its constructor, so overriding it here covers every tool on the server."""

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        call = next(_calls)
        base = {"event": EVENT, "mcp_server": self.name, "call": call, "tool_name": name,
                **caller(self.get_context())}
        emit({"ts": _now(), **base, "phase": "pre", "tool_input": clip(arguments or {})})
        started = time.monotonic()
        try:
            result = await super().call_tool(name, arguments)
        except Exception as e:
            emit({"ts": _now(), **base, "phase": "post", "outcome": "error",
                  "duration_ms": round((time.monotonic() - started) * 1000), "error": clip(str(e))})
            raise
        emit({"ts": _now(), **base, "phase": "post", "outcome": "ok",
              "duration_ms": round((time.monotonic() - started) * 1000),
              "result_chars": _result_chars(result)})
        return result
