# ABOUTME: The per-agent tool audit trail (#190): every workshop-mcp tool call writes pre and post JSON lines
# ABOUTME: tagged with the agent's identity, and the Agent CR, the toggle and the bundle all carry that identity.
"""Offline half of the #190 audit-trail checks. The real-library and live-Datadog-Logs half is test_tool_audit_live.py.

The workshop is about attributing damage to an agent, and before #190 nothing recorded which agent called
which tool in what order. tool_audit.py is that record. What breaks it is mostly not the module but the
wiring around it, each of which fails silently:

- the server builds a plain FastMCP again, so nothing is written;
- tool_audit.py drops out of the ConfigMap, so the import fails and workshop-mcp CrashLoops;
- the Agent's workshop-mcp entry loses its X-Agent-Identity header, so every line says `unattributed`;
- Challenge 7's toggle, which replaces the whole tools array, writes the entry back without the header;
- the Datadog Agent stops collecting every container's logs, so the lines are written and read by nobody.
  Datadog is the only log store since #474 removed Loki and Alloy.

The module itself is exercised here against a stand-in FastMCP, since the offline suite has no `mcp`.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import pathlib
import re
import sys
import types
from contextlib import redirect_stdout

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# ----- a stand-in for mcp.server.fastmcp, shaped like mcp 1.29.1 where the module touches it -------------
class _Block:
    def __init__(self, text: str) -> None:
        self.text = text


class _RC:
    def __init__(self, headers: dict | None, request_id: int) -> None:
        self.request = None if headers is None else types.SimpleNamespace(headers=headers)
        self.request_id = request_id


class _Ctx:
    def __init__(self, rc: _RC | None) -> None:
        self._rc = rc

    @property
    def request_context(self) -> _RC:
        if self._rc is None:
            raise ValueError("Context is not available outside of a request")
        return self._rc


class _FakeFastMCP:
    def __init__(self, name: str, **_: object) -> None:
        self.name = name
        self.rc: _RC | None = None
        self.result: object = None
        self.raises: Exception | None = None
        self.calls: list[tuple[str, dict]] = []

    def get_context(self) -> _Ctx:
        return _Ctx(self.rc)

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if self.raises is not None:
            raise self.raises
        return self.result


fastmcp_stub = types.ModuleType("mcp.server.fastmcp")
fastmcp_stub.FastMCP = _FakeFastMCP
for mod in ("mcp", "mcp.server"):
    sys.modules.setdefault(mod, types.ModuleType(mod))
sys.modules["mcp.server.fastmcp"] = fastmcp_stub

spec = importlib.util.spec_from_file_location("tool_audit", AI / "tool_audit.py")
tool_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool_audit)


def run(server, name: str, arguments: dict):
    """Call the audited tool and return (result, exception, parsed audit lines)."""
    out = io.StringIO()
    result = exc = None
    with redirect_stdout(out):
        try:
            result = asyncio.run(server.call_tool(name, arguments))
        except Exception as e:  # noqa: BLE001
            exc = e
    lines = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    return result, exc, lines


print("== a successful call writes a pre line, then a post line, both attributed ==")
srv = tool_audit.AuditedFastMCP("workshop-mcp")
srv.rc = _RC({"x-agent-identity": "workshop-agent", "mcp-session-id": "sess-1"}, 7)
SECRET = "WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7"
srv.result = ([_Block(SECRET)], {"result": SECRET})
result, exc, lines = run(srv, "get_vault_entry", {"name": "bat-spit-amazing-awesome-sauce"})
check("the tool's own result is returned unchanged", result == srv.result and exc is None)
check("the underlying tool ran exactly once", srv.calls == [("get_vault_entry", {"name": "bat-spit-amazing-awesome-sauce"})])
check("two audit lines, pre then post", [ln.get("phase") for ln in lines] == ["pre", "post"])
pre, post = (lines + [{}, {}])[:2]
for field, want in (("event", "tool_invocation"), ("agent_identity", "workshop-agent"), ("mcp_server", "workshop-mcp"),
                    ("tool_name", "get_vault_entry"), ("mcp_session_id", "sess-1"), ("request_id", "7")):
    check(f"both lines carry {field}={want}", pre.get(field) == want and post.get(field) == want)
check("pre and post share one call number, so they pair", pre.get("call") == post.get("call") and isinstance(pre.get("call"), int))
check("pre records the arguments, which are the attack", pre.get("tool_input") == {"name": "bat-spit-amazing-awesome-sauce"})
check("post records the outcome and how long it took", post.get("outcome") == "ok" and isinstance(post.get("duration_ms"), int))
check("post records the result's size", post.get("result_chars") == len(SECRET))
check("the result itself is never logged (it is the leaked value)",
      all(SECRET not in json.dumps(ln) for ln in lines))
check("every line carries a UTC timestamp", all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", ln.get("ts", "")) for ln in lines))

print("== calls are numbered in order ==")
_, _, again = run(srv, "list_services", {})
check("the next call gets the next number", again and again[0].get("call") == pre.get("call", 0) + 1)

print("== a failing call is recorded as an error and still fails ==")
srv.raises = RuntimeError("command FAILED with exit code 7: curl: (7) Failed to connect")
_, exc, lines = run(srv, "run_shell", {"command": "curl -X POST https://partner.example/intake"})
check("the exception reaches the caller", isinstance(exc, RuntimeError))
check("pre was written before the tool ran", lines and lines[0].get("phase") == "pre"
      and lines[0].get("tool_input") == {"command": "curl -X POST https://partner.example/intake"})
check("post says error and why", len(lines) == 2 and lines[1].get("outcome") == "error" and "exit code 7" in lines[1].get("error", ""))
srv.raises = None

print("== a caller that is not the agent is marked, not guessed ==")
srv.rc = _RC({}, 9)
_, _, lines = run(srv, "check_inventory", {})
check("no identity header -> unattributed", lines and all(ln.get("agent_identity") == "unattributed" for ln in lines))
srv.rc = _RC({"x-agent-identity": "   "}, 10)
_, _, lines = run(srv, "check_inventory", {})
check("a blank identity header -> unattributed", lines and lines[0].get("agent_identity") == "unattributed")
srv.rc = None
_, _, lines = run(srv, "check_inventory", {})
check("no request in flight -> unattributed, no request id",
      lines and lines[0].get("agent_identity") == "unattributed" and lines[0].get("request_id") is None)

print("== arguments are bounded ==")
big = "x" * (tool_audit.MAX_ARG_CHARS + 500)
clipped = tool_audit.clip({"manifest": big, "nested": [big], "n": 3})
check("a long string is clipped and says by how much",
      clipped["manifest"].endswith("...[+500 chars]") and len(clipped["manifest"]) < len(big))
check("clipping keeps the structure and leaves non-strings alone",
      clipped["nested"][0] == clipped["manifest"] and clipped["n"] == 3)

print("== workshop-mcp is built on the audited server ==")
WMCP = (AI / "workshop-mcp-server.py").read_text(encoding="utf-8")
check("workshop-mcp imports AuditedFastMCP", "from tool_audit import AuditedFastMCP" in WMCP)
check("workshop-mcp constructs AuditedFastMCP, not a bare FastMCP",
      re.search(r"^mcp = AuditedFastMCP\(", WMCP, re.M) is not None and "FastMCP(" not in WMCP.replace("AuditedFastMCP(", ""))
EVIL = (AI / "server.py").read_text(encoding="utf-8")
check("evil-mcp-shim stays dark (#18): it does not audit itself", "tool_audit" not in EVIL)

print("== the module ships in workshop-mcp's ConfigMap ==")
KUST = yaml.safe_load((AI / "kustomization.yaml").read_text(encoding="utf-8"))
gens = {g["name"]: g.get("files", []) for g in KUST.get("configMapGenerator", [])}
check("workshop-mcp-src mounts tool_audit.py beside server.py",
      "tool_audit.py" in gens.get("workshop-mcp-src", []) and "server.py=workshop-mcp-server.py" in gens.get("workshop-mcp-src", []))

print("== the agent declares who it is to workshop-mcp ==")
RES = [d for d in yaml.safe_load_all((AI / "resources.yaml").read_text(encoding="utf-8")) if d]
agent = next(d for d in RES if d.get("kind") == "Agent")
entries = {(e.get("mcpServer") or {}).get("name"): e for e in agent["spec"]["declarative"]["tools"]}
good = entries.get("workshop-mcp", {})
ident = [h for h in good.get("headersFrom") or [] if h.get("name", "").lower() == tool_audit.IDENTITY_HEADER]
check("the workshop-mcp entry sets X-Agent-Identity exactly once", len(ident) == 1)
check("the identity is the Agent's own name", ident[:1] and ident[0].get("value") == agent["metadata"]["name"])
check("headersFrom sits on the tool entry, where kagent 0.9.9 reads it, not inside mcpServer",
      "headersFrom" not in (good.get("mcpServer") or {}))
check("the rogue server is not handed the agent's identity",
      not (entries.get("evil-mcp") or {}).get("headersFrom"))

print("== Challenge 7's toggle writes the same workshop-mcp entry back ==")
TOGGLE = (REPO / "challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh").read_text(encoding="utf-8")
m = re.search(r"^readonly GOOD_TOOL='(.*)'$", TOGGLE, re.M)
check("the toggle defines GOOD_TOOL", m is not None)
toggle_good = json.loads(m.group(1)) if m else {}
check("the toggle's workshop-mcp entry is identical to the committed one, header included", toggle_good == good)

print("== the trail reaches Datadog Logs, the only log store ==")
DDA = yaml.safe_load((REPO / "gitops/manifests/datadog/datadog-agent.yaml").read_text(encoding="utf-8"))
logs = DDA["spec"]["features"].get("logCollection") or {}
check("the Datadog Agent collects every container's logs (logCollection, containerCollectAll)",
      logs.get("enabled") is True and logs.get("containerCollectAll") is True)
env = [e.get("name") for c in DDA["spec"].get("override", {}).values() for e in c.get("env") or []]
check("no DD_CONTAINER_EXCLUDE* setting can drop workshop-mcp's logs",
      not [n for n in env if n.startswith("DD_CONTAINER_EXCLUDE")])
mcp_dep = next((d for d in RES if d.get("kind") == "Deployment" and d["metadata"]["name"] == "workshop-mcp"), {})
annotations = (mcp_dep.get("spec", {}).get("template", {}).get("metadata", {}).get("annotations") or {})
check("workshop-mcp's pod carries no Datadog annotation that excludes or reroutes its logs",
      bool(mcp_dep) and not [k for k in annotations if k.startswith("ad.datadoghq.com/") and k.endswith((".logs", "exclude"))])
APPS = REPO / "gitops/bootstrap/apps"
check("no Loki or Alloy app is left to read the trail from (#474)",
      APPS.is_dir() and not (APPS / "loki.yaml").exists() and not (APPS / "alloy.yaml").exists())

print("== the live check's call is sent from a pod the armed admin profile admits (#555) ==")
LIVE = (REPO / "verify/test_tool_audit_live.py").read_text(encoding="utf-8")
check("it builds its probe pod with verify/probe_pod.py, which test_probe_pod_admission.py judges",
      "probe_pod.shell_pod(" in LIVE)
check("it runs the shim image the workshop-mcp Deployment names, read off the cluster",
      re.search(r'get", "deployment", "workshop-mcp".*\n.*containers\[\?\(@\.name=="shim"\)\]\.image', LIVE) is not None)
check("it no longer uses kubectl run or curlimages/curl, which Deny refuses on that profile",
      re.search(r'kubectl\(\s*"run"', LIVE) is None and "curlimages" not in LIVE)

print("== the live check runs on the image's mcp pin through uv, never a global install (#441) ==")
py = re.search(r"^FROM python:(\d+\.\d+)", (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8"), re.M)
check("it re-runs itself under uv run --with mcp==<the Dockerfile pin>",
      'os.execvpe("uv", ["uv", "run", "--no-project"' in LIVE and '"--with", f"mcp=={want}"' in LIVE)
check(f"on the workshop-mcp image's Python ({py.group(1) if py else '?'})",
      bool(py) and f'"--python", "{py.group(1)}"' in LIVE)
check("the re-run is marked so it does not re-run itself", 'WIB_TOOL_AUDIT_UV' in LIVE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All tool-audit checks passed.")
