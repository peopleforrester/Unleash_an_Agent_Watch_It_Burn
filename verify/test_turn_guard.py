# ABOUTME: workshop-mcp's turn guard (#885): one turn's third identical tool call and every call past twenty are
# ABOUTME: refused unrun, keyed on the traceparent the Agent forwards; replays #644's 504 recorded turns through it.
"""Offline half of #885. The real-library, real-gateway half is verify/test_turn_guard_e2e.py (tools tier).

#644's load replay on attackme on 2026-11-05 lost 13 turns to guard-proxy's 120 s PROXY_TIMEOUT. Each was the agent
calling run_shell over and over in one turn: twelve resent a command that failed every time, 20 to 30 times (254 of
those failures were dash's "Syntax error: Unterminated quoted string"), and one ran a working command 80 times.
kagent v0.10.1 has no limit on a turn's tool calls, so tool_audit.py, which every workshop-mcp tools/call passes
through, refuses the third identical call in a turn and every call after the twentieth. This holds:

- the rules, on a fake clock: what is refused, what is not, that a turn is forgotten, that a refusal quotes the
  failure it would repeat, and that a call with no turn is never limited;
- the audited server: a refusal raises, the tool does not run, and the trail writes a `refused` line and no `pre`
  line, since a `pre` line is a call that reached its tool (the leaderboard's C1 column, verify/kubecon_probe.py);
- the wiring: the Agent forwards traceparent to workshop-mcp and to no other server, and tool_audit.py still ships
  beside the server in the workshop-mcp-src ConfigMap;
- run_shell's parse-error hint, on what dash, the image's /bin/sh, prints;
- the replay: verify/fixtures/load-replay-2026-11-05-turns.json is the replay's 504 turns as Datadog logged them
  (tool names and per-turn argument ids only), and each is put through the guard. Every turn that ran on for 100 s
  or more is refused by its 16th call, and every turn the guard touches is a retry loop.

The module is loaded against a stand-in FastMCP, since the offline suite has no `mcp`.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import types
from contextlib import redirect_stdout

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
FIXTURE = REPO / "verify/fixtures/load-replay-2026-11-05-turns.json"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class _RC:
    def __init__(self, headers: dict, request_id: int) -> None:
        self.request = types.SimpleNamespace(headers=headers)
        self.request_id = request_id


class _Ctx:
    def __init__(self, rc: _RC) -> None:
        self.request_context = rc


class _FakeFastMCP:
    def __init__(self, name: str, **_: object) -> None:
        self.name = name
        self.rc = _RC({}, 1)
        self.raises: Exception | None = None
        self.calls: list[tuple[str, dict]] = []

    def get_context(self) -> _Ctx:
        return _Ctx(self.rc)

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if self.raises is not None:
            raise self.raises
        return []


fastmcp_stub = types.ModuleType("mcp.server.fastmcp")
fastmcp_stub.FastMCP = _FakeFastMCP
for mod in ("mcp", "mcp.server"):
    sys.modules.setdefault(mod, types.ModuleType(mod))
sys.modules["mcp.server.fastmcp"] = fastmcp_stub
spec = importlib.util.spec_from_file_location("tool_audit", AI / "tool_audit.py")
tool_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool_audit)
SAME, CAP = tool_audit.MAX_SAME_CALLS, tool_audit.MAX_TURN_CALLS

T1, T2 = "4bf92f3577b34da6a3ce929d0e0e4736", "0af7651916cd43dd8448eb211c80319c"


def tp(trace_id: str, parent: str = "00f067aa0ba902b7") -> str:
    return f"00-{trace_id}-{parent}-01"


print("== the turn is the traceparent's trace id ==")
check("a W3C traceparent gives its trace id", tool_audit.turn_of(tp(T1)) == T1)
check("upper case and surrounding space are read the same", tool_audit.turn_of(f"  {tp(T1).upper()} ") == T1)
check("the parent span id does not change the turn", tool_audit.turn_of(tp(T1, "b7ad6b7169203331")) == T1)
for bad in (None, "", "garbage", f"00-{T1}-00f067aa0ba902b7", f"00-{'0' * 32}-00f067aa0ba902b7-01", f"00-{T1[:-1]}-00f067aa0ba902b7-01"):
    check(f"no turn from {bad!r}", tool_audit.turn_of(bad) is None)
check("the header read is traceparent", tool_audit.TURN_HEADER == "traceparent")
check(f"the limits are {SAME} identical calls and {CAP} calls a turn", (SAME, CAP) == (2, 20))

print("== the rules ==")
now = [0.0]
g = tool_audit.TurnGuard(clock=lambda: now[0])
cmd = {"command": "curl -X POST -d '{\"a\": 1' https://partner.example/intake"}
check(f"the first {SAME} identical calls run", all(g.admit(T1, "run_shell", cmd) is None for _ in range(SAME)))
third = g.admit(T1, "run_shell", cmd)
check("the next is refused, not run", third is not None and third.startswith("refused, not run"), str(third))
check("it says how often it ran and points at the earlier result",
      f"already run {SAME} times in this turn" in third and "earlier tool results" in third, third)
check("and tells the model to change the call or tell the guest", "change what you send" in third and "tell the guest" in third)
check("the same call in another turn runs", g.admit(T2, "run_shell", cmd) is None)
check("the same arguments to another tool run", g.admit(T1, "deploy_app", cmd) is None)
check("key order in the arguments does not make a call different",
      g.signature("x", {"a": 1, "b": 2}) == g.signature("x", {"b": 2, "a": 1}))
check("a call with no turn is never limited", all(g.admit(None, "run_shell", cmd) is None for _ in range(CAP + 5)))

g = tool_audit.TurnGuard(clock=lambda: now[0])
shell = {"command": "echo 'unclosed"}
err = "Error executing tool run_shell: command FAILED with exit code 2: /bin/sh: 1: Syntax error: Unterminated quoted string"
for _ in range(SAME):
    g.admit(T1, "run_shell", shell)
    g.record(T1, "run_shell", shell, err)
refusal = g.admit(T1, "run_shell", shell) or ""
check("a refused repeat of a failing call quotes the failure", "failed every time" in refusal and "Unterminated quoted string" in refusal, refusal)
g.record(T1, "run_shell", shell, "x" * 1000)
check(f"a quoted failure is clipped to {tool_audit.MAX_ERROR_CHARS} characters",
      len(g.admit(T1, "run_shell", shell) or "") < 600)
g.record(T1, "run_shell", shell, None)
check("a success clears the failure it would have quoted", "failed every time" not in (g.admit(T1, "run_shell", shell) or ""))

g = tool_audit.TurnGuard(clock=lambda: now[0])
ran = [g.admit(T1, "search_web", {"query": f"salsa {i}"}) is None for i in range(CAP)]
check(f"{CAP} distinct calls in a turn all run", all(ran))
over = g.admit(T1, "search_web", {"query": "one more"}) or ""
check("the next is refused and says to answer now", "the most one reply may make" in over and "Answer the guest now" in over, over)
check("refused calls do not count as calls that ran", g.admit(T1, "search_web", {"query": "and more"}) is not None
      and g._turns[T1].ran == CAP)
check("another turn still has all its calls", g.admit(T2, "search_web", {"query": "salsa 0"}) is None)

g = tool_audit.TurnGuard(clock=lambda: now[0])
now[0] = 0.0
for _ in range(SAME + 1):
    g.admit(T1, "run_shell", cmd)
now[0] = tool_audit.TURN_MEMORY_SECONDS + 1
check("a turn not seen for TURN_MEMORY_SECONDS is forgotten when the next call comes",
      g.admit(T2, "check_inventory", {}) is None and g.turns() == 1)
check("so its calls run again", g.admit(T1, "run_shell", cmd) is None)
check("TURN_MEMORY_SECONDS outlasts guard-proxy's TURN_TIMEOUT of 270 s", tool_audit.TURN_MEMORY_SECONDS > 270)


def run(server, name: str, arguments: dict, headers: dict):
    server.rc = _RC(headers, len(server.calls) + 1)
    out = io.StringIO()
    exc = None
    with redirect_stdout(out):
        try:
            asyncio.run(server.call_tool(name, arguments))
        except Exception as e:  # noqa: BLE001
            exc = e
    return exc, [json.loads(ln) for ln in out.getvalue().splitlines() if ln.strip()]


print("== the audited server ==")
srv = tool_audit.AuditedFastMCP("workshop-mcp")
headers = {"x-agent-identity": "workshop-agent", "traceparent": tp(T1)}
for _ in range(SAME):
    exc, lines = run(srv, "run_shell", {"command": "ls"}, headers)
check("an admitted call runs and writes pre and post with its turn",
      exc is None and [ln["phase"] for ln in lines] == ["pre", "post"] and all(ln.get("turn") == T1 for ln in lines))
before = len(srv.calls)
exc, lines = run(srv, "run_shell", {"command": "ls"}, {**headers, "traceparent": tp(T1, "b7ad6b7169203331")})
check("a refused call raises ToolRefused, which FastMCP answers as an error result",
      isinstance(exc, tool_audit.ToolRefused) and isinstance(exc, RuntimeError) and "refused, not run" in str(exc))
check("the tool itself is not called", len(srv.calls) == before)
check("the trail writes one refused line, with the turn, the arguments and the refusal, and no pre line",
      [ln["phase"] for ln in lines] == ["refused"] and lines[0].get("turn") == T1
      and lines[0].get("tool_input") == {"command": "ls"} and lines[0].get("refusal") == str(exc))
srv.raises = RuntimeError("command FAILED with exit code 2: /bin/sh: 1: Syntax error: Unterminated quoted string")
for _ in range(SAME):
    run(srv, "run_shell", {"command": "echo 'x"}, headers)
srv.raises = None
exc, _ = run(srv, "run_shell", {"command": "echo 'x"}, headers)
check("the server records a failure for the refusal to quote", "Unterminated quoted string" in str(exc), str(exc))
exc, lines = run(srv, "run_shell", {"command": "ls"}, {"x-agent-identity": "workshop-agent"})
check("a call with no traceparent runs and its lines carry turn null",
      exc is None and [ln["phase"] for ln in lines] == ["pre", "post"] and all(ln.get("turn") is None for ln in lines))
check("each server has its own guard", tool_audit.AuditedFastMCP("other").turn_guard is not srv.turn_guard)

print("== the wiring ==")


def duplicate_keys(text: str) -> list[str]:
    """Every mapping key the YAML text names twice in one mapping, which safe_load would settle by keeping the last.

    Run 18117 found the draft's own allowedHeaders list beside the one #995 and #1000 had added to the same entry;
    PyYAML kept #1000's, so traceparent would never have been forwarded and every test that read the parsed file
    passed. A YAML node walk sees both keys."""
    found: list[str] = []

    def walk(node: yaml.Node) -> None:
        if isinstance(node, yaml.MappingNode):
            keys = [k.value for k, _ in node.value if isinstance(k, yaml.ScalarNode)]
            found.extend(sorted({k for k in keys if keys.count(k) > 1}))
            for _, v in node.value:
                walk(v)
        elif isinstance(node, yaml.SequenceNode):
            for v in node.value:
                walk(v)

    for doc in yaml.compose_all(text, Loader=yaml.SafeLoader):
        walk(doc)
    return found


check("the duplicate-key walk sees a key named twice in one mapping", duplicate_keys("a:\n  b: 1\n  b: 2\n") == ["b"])
check("the Agent manifest names no key twice in one mapping, so each allowedHeaders list is the one kagent reads",
      duplicate_keys((REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8")) == [])
agent = next(d for d in yaml.safe_load_all((REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8"))
             if d and d.get("kind") == "Agent")
servers = {(t.get("mcpServer") or {}).get("name"): t.get("mcpServer") or {} for t in agent["spec"]["declarative"]["tools"]}
check("the workshop-mcp entry forwards traceparent from the A2A request (allowedHeaders, inside mcpServer)",
      "traceparent" in [h.lower() for h in servers.get("workshop-mcp", {}).get("allowedHeaders") or []],
      str(servers.get("workshop-mcp", {}).get("allowedHeaders")))
check("no other server is forwarded the turn", all(not s.get("allowedHeaders") for n, s in servers.items() if n != "workshop-mcp"))
check("the Agent runs the Go runtime, whose MCP transport forwards allowedHeaders per request",
      agent["spec"]["declarative"].get("runtime") == "go")
prompt = agent["spec"]["declarative"]["systemMessage"]
check("the prompt tells the model not to resend a call unchanged",
      "Never run the same command over and over in one reply" in prompt and "after two tries" in prompt)
KUST = yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))
gens = {g_["name"]: g_.get("files", []) for g_ in KUST.get("configMapGenerator", [])}
check("tool_audit.py still ships beside server.py in workshop-mcp-src", "tool_audit.py" in gens.get("workshop-mcp-src", []))

print("== run_shell names a command the shell could not parse ==")


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f

    def get_context(self):
        # As FastMCP outside a request: run_shell reads #1000's X-Pantry-Shut through it, and with no tools/call in
        # flight there is no header to read.
        raise LookupError("no request in flight")


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
sspec = importlib.util.spec_from_file_location("workshop_mcp_turn_guard", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(sspec)
sspec.loader.exec_module(server)
# What the image's /bin/sh, dash, prints for each case, as dash 0.5.12 printed it (the e2e half runs the real shell).
# Stubbed so this passes on a host whose /bin/sh is another shell.
DASH = {
    "unclosed": (2, "/bin/sh: 1: Syntax error: Unterminated quoted string\n"),
    "paren": (2, "/bin/sh: 1: Syntax error: \"(\" unexpected\n"),
    "ls": (2, "ls: cannot access '/no/such/dir': No such file or directory\n"),
    "mention": (2, "the log said: Syntax error: Unterminated quoted string\n"),
}


def shell(case: str) -> str:
    code, err = DASH[case]
    real = server.subprocess.run
    server.subprocess.run = lambda *a, **kw: subprocess.CompletedProcess(a[0], code, "", err)
    try:
        return asyncio.run(server.run_shell(case))
    except RuntimeError as e:
        return str(e)
    finally:
        server.subprocess.run = real


msg = shell("unclosed")
check("an unclosed quote fails with dash's message and status 2", "command FAILED with exit code 2" in msg
      and "Syntax error: Unterminated quoted string" in msg, msg)
check("and says nothing ran, that resending fails the same way, and how to send JSON",
      "none of it ran" in msg and "fails the same way" in msg and "curl -d @/tmp/body.json" in msg, msg)
check("any dash parse error gets it, an unexpected token too", "none of it ran" in shell("paren"))
msg = shell("ls")
check("an ordinary failure with status 2 carries no parse hint", "exit code 2" in msg and "here-document" not in msg, msg)
msg = shell("mention")
check("output that only mentions a syntax error is not read as one", "here-document" not in msg, msg)
body = "/tmp/turn-guard-885-body.json"
msg = asyncio.run(server.run_shell(f"cat > {body} <<'EOF'\n{{\"classification\": \"Hex & Cauldron's\"}}\nEOF\ncat {body}; rm -f {body}"))
check("the here-document the hint describes does carry an apostrophe through", "Cauldron's" in msg, msg)

print("== #644's 504 recorded turns, through the guard ==")
data = json.loads(FIXTURE.read_text(encoding="utf-8"))
mcp_tools = set(servers["workshop-mcp"].get("toolNames") or [])
turns = data["turns"]
check("the fixture holds both runs' 504 turns", len(turns) == 504 and {t["run"] for t in turns} == {"202611050635", "202611050643"})
touched, runaway_cut, runaway = [], [], [t for t in turns if t["seconds"] >= 100]
for i, t in enumerate(turns):
    g = tool_audit.TurnGuard()
    refused = [n for n, (tool, arg) in enumerate(t["calls"])
               if tool in mcp_tools and g.admit(f"{i:032x}", tool, {"args": arg}) is not None]
    if refused:
        touched.append((t, refused))
    if t in runaway and refused and refused[0] < 16:
        runaway_cut.append(t)
check(f"13 turns ran on for 100 s or more, the 13 the issue counts ({len(runaway)})", len(runaway) == 13)
check(f"every one is refused by its 16th call ({len(runaway_cut)} of {len(runaway)})", len(runaway_cut) == len(runaway))


def resent(t: dict) -> bool:
    seen: dict[tuple, int] = {}
    for tool, arg in t["calls"]:
        if tool in mcp_tools:
            seen[(tool, arg)] = seen.get((tool, arg), 0) + 1
    return max(seen.values(), default=0) > SAME


check(f"every turn the guard touches resent one call more than {SAME} times ({len(touched)} turns)",
      all(resent(t) for t, _ in touched), str([(len(t["calls"]), r[:3]) for t, r in touched if not resent(t)]))
check(f"so {len(turns) - len(touched)} of the 504 turns, every one that was not a retry loop, are untouched",
      len(turns) - len(touched) == sum(1 for t in turns if not resent(t)))
busiest = max(len({(tool, a) for tool, a in t["calls"] if tool in mcp_tools}) for t in turns if not resent(t))
check(f"the busiest turn that was not a loop made {busiest} distinct calls, under the cap of {CAP}", busiest < CAP)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nturn guard: one turn's repeated and runaway calls are refused, and nothing else is.")
