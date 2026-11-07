# ABOUTME: Per-agent tool-invocation audit trail for workshop-mcp: one JSON line on stdout per tool call
# ABOUTME: phase, tagged with the calling agent's identity and turn; it also refuses one turn's repeated calls (#885).
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

The turn guard (#885). The same override is where every tools/call passes, so it also bounds one turn's calls.
#644's load replay on 2026-11-05 lost 13 of 1,950 turns to guard-proxy's 120 s PROXY_TIMEOUT, and every one was the
agent calling run_shell again and again in one turn: the same failing command 20 to 30 times, or a working one 80
times. kagent v0.10.1 has no limit on tool calls in a turn (the Agent CRD has none, and ADK-go v2.1.0's RunConfig
holds only StreamingMode and SaveInputBlobsAsArtifacts), so the limit lives here. In one turn:

- the third call of a tool with the same arguments is refused, and not run (MAX_SAME_CALLS 2);
- once 20 calls have run, every further call is refused (MAX_TURN_CALLS). The busiest real turns in the replay made
  14 distinct reorder_supply calls and 12 distinct deploy_app calls, in two seconds each.

A refusal is raised, so FastMCP answers it as an error result, and its text tells the model to change the call or
answer the guest. It writes a `refused` line and no `pre` line: a `pre` line is a call that reached its tool, which
the leaderboard's C1 column and verify/kubecon_probe.py count.

The turn is the W3C trace id of the call's `traceparent` header. workshop-mcp's MCP session cannot be the key: kagent
keeps one session for every conversation (five sessions carried that replay's 504 turns). guard-proxy injects its
/chat span's traceparent on each A2A message/send and tasks/get of a turn, kagent forwards it on the turn's MCP
requests because the Agent lists it in allowedHeaders (gitops/workshop-agent/agent.yaml), and agentgateway keeps the
trace id on its way to this server. A call with no valid traceparent has no turn and is not limited. Behind
agentgateway there is always one: a request that brings none gets a new trace there, so it is a turn of one call,
and is never limited either (verify/test_turn_guard_e2e.py runs the pinned gateway and sees both).
"""
from __future__ import annotations

import itertools
import json
import re
import sys
import threading
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

TURN_HEADER = "traceparent"
MAX_SAME_CALLS = 2
MAX_TURN_CALLS = 20
# A turn is forgotten this long after its last call. guard-proxy's TURN_TIMEOUT (270 s) bounds a turn, so this only
# keeps the table small; a conversation's next turn arrives under a new trace id either way.
TURN_MEMORY_SECONDS = 900
# The failure a refusal quotes back, clipped: enough for the shell's or the API server's reason.
MAX_ERROR_CHARS = 300
# version-traceid-parentid-flags, as W3C Trace Context writes it. An all-zero trace id is invalid there.
_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


def turn_of(traceparent: Any) -> str | None:
    """The trace id a traceparent header names, which is the turn; None when there is no valid one."""
    m = _TRACEPARENT.match(str(traceparent or "").strip().lower())
    if not m or m.group(1) == "0" * 32:
        return None
    return m.group(1)


class ToolRefused(RuntimeError):
    """A tool call the turn guard did not run."""


class _Turn:
    def __init__(self, now: float) -> None:
        self.last = now
        self.ran = 0
        self.same: dict[str, int] = {}
        self.failed: dict[str, str] = {}


class TurnGuard:
    """Per-turn counts of tool calls. admit() says whether a call may run; record() keeps how it ended."""

    def __init__(self, max_same: int = MAX_SAME_CALLS, max_calls: int = MAX_TURN_CALLS,
                 memory_seconds: float = TURN_MEMORY_SECONDS, clock=time.monotonic) -> None:
        self.max_same = max_same
        self.max_calls = max_calls
        self.memory_seconds = memory_seconds
        self.clock = clock
        self._turns: dict[str, _Turn] = {}
        self._lock = threading.Lock()

    @staticmethod
    def signature(name: str, arguments: dict[str, Any] | None) -> str:
        return json.dumps([name, arguments or {}], sort_keys=True, default=str)

    def turns(self) -> int:
        return len(self._turns)

    def admit(self, turn: str | None, name: str, arguments: dict[str, Any] | None) -> str | None:
        """None when the call may run, or the refusal to answer with instead of running it."""
        if turn is None:
            return None
        now = self.clock()
        sig = self.signature(name, arguments)
        with self._lock:
            for key in [k for k, t in self._turns.items() if now - t.last > self.memory_seconds]:
                del self._turns[key]
            t = self._turns.setdefault(turn, _Turn(now))
            t.last = now
            same = t.same.get(sig, 0)
            t.same[sig] = same + 1
            if t.ran >= self.max_calls:
                return (f"refused, not run: this turn has already made {t.ran} tool calls, the most one reply may "
                        f"make. Do not call any more tools. Answer the guest now with what the earlier calls returned.")
            if same >= self.max_same:
                failed = t.failed.get(sig)
                if failed:
                    happened = f"and failed every time, last with: {failed}"
                else:
                    happened = "and its result is in your earlier tool results"
                return (f"refused, not run: this exact {name} call has already run {same} times in this turn {happened}. "
                        f"Sending it again unchanged gets the same answer. Do not send it again: change what you send, "
                        f"or stop and tell the guest plainly what happened.")
            t.ran += 1
            return None

    def record(self, turn: str | None, name: str, arguments: dict[str, Any] | None, error: str | None) -> None:
        """Keep a call's failure, clipped, so a refusal of the same call can say what it was; a success clears it."""
        if turn is None:
            return
        sig = self.signature(name, arguments)
        with self._lock:
            t = self._turns.get(turn)
            if t is None:
                return
            if error:
                t.failed[sig] = error if len(error) <= MAX_ERROR_CHARS else error[:MAX_ERROR_CHARS] + "..."
            else:
                t.failed.pop(sig, None)


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
        # The turn's trace id, the same id as the turn's spans in Datadog APM; null when the call carried none.
        "turn": turn_of(headers.get(TURN_HEADER)),
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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.turn_guard = TurnGuard()

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        call = next(_calls)
        base = {"event": EVENT, "mcp_server": self.name, "call": call, "tool_name": name,
                **caller(self.get_context())}
        refusal = self.turn_guard.admit(base["turn"], name, arguments)
        if refusal is not None:
            emit({"ts": _now(), **base, "phase": "refused", "tool_input": clip(arguments or {}), "refusal": refusal})
            raise ToolRefused(refusal)
        emit({"ts": _now(), **base, "phase": "pre", "tool_input": clip(arguments or {})})
        started = time.monotonic()
        try:
            result = await super().call_tool(name, arguments)
        except Exception as e:
            self.turn_guard.record(base["turn"], name, arguments, str(e) or type(e).__name__)
            emit({"ts": _now(), **base, "phase": "post", "outcome": "error",
                  "duration_ms": round((time.monotonic() - started) * 1000), "error": clip(str(e))})
            raise
        self.turn_guard.record(base["turn"], name, arguments, None)
        emit({"ts": _now(), **base, "phase": "post", "outcome": "ok",
              "duration_ms": round((time.monotonic() - started) * 1000),
              "result_chars": _result_chars(result)})
        return result
