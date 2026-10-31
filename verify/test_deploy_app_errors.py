# ABOUTME: deploy_app's refusals of a manifest it cannot use must raise "deploy failed for ...", not return text, so
# ABOUTME: the agent gets an MCP error and the trace a red span, as a refused apply already does (#463, #712).
"""On 2026-10-30 the public bot's Challenge 3 run sent deploy_app a manifest missing its closing braces. deploy_app
returned "could not parse manifest as JSON or YAML: ..." as text, FastMCP answered that as a success, and the model
told the room joker-agatha-the-banshee was deployed when nothing was (the probe's "narrated, not obeyed" FAIL,
LLM Observability trace 3d0ef331ad7f). Measured from the public cluster's deploy_app spans: two of the four calls
that day were truncated manifests; the model retried after neither.

Every refusal before the apply now raises with "deploy failed for ", the text the collector's
transform/adk_tool_content already marks a tool span ERROR on, and says nothing was deployed. The server is loaded
with a stand-in for tool_audit, as test_run_shell_failure.py loads it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

REPO = pathlib.Path(__file__).resolve().parent.parent
AI = REPO / "gitops/ai-layer"
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class _StandInMCP:
    def __init__(self, *a, **kw):
        pass

    def tool(self, *a, **kw):
        return lambda f: f


sys.modules["tool_audit"] = types.SimpleNamespace(AuditedFastMCP=_StandInMCP)
spec = importlib.util.spec_from_file_location("workshop_mcp_deploy_errors", AI / "workshop-mcp-server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
applied: list = []
server._req = lambda *a, **k: applied.append(a) or (500, "should not be called")  # noqa: E731


def call(manifest: str):
    try:
        return server.deploy_app(manifest), None
    except Exception as e:  # noqa: BLE001
        return None, e


# The manifest the model sent on 2026-10-30, three closing braces short.
TRUNCATED = ('{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"joker-agatha-the-banshee"},"spec":'
             '{"replicas":1,"selector":{"matchLabels":{"app":"joker-agatha-the-banshee"}},"template":{"metadata":'
             '{"labels":{"app":"joker-agatha-the-banshee"}},"spec":{"containers":[{"name":"joker","image":'
             '"ghcr.io/peopleforrester/joker:v1"}]}')
COLLECTOR = (REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8")

for label, manifest, why in (
        ("a truncated manifest (2026-10-30)", TRUNCATED, "could not parse"),
        ("an empty manifest", "   ", "empty"),
        ("a list, not one object", '[{"kind": "Deployment"}]', "apiVersion and kind"),
        ("no metadata.name", '{"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {}}', "metadata.name"),
        ("an unknown kind", '{"apiVersion": "x/v1", "kind": "Gizmo", "metadata": {"name": "g"}}', "unknown resource")):
    print(f"== {label} ==")
    result, exc = call(manifest)
    check(f"{label} raises rather than returning text", result is None and isinstance(exc, RuntimeError),
          f"returned {result!r}")
    msg = str(exc)
    check(f"{label}: the message starts 'deploy failed for ', which the collector marks ERROR",
          msg.startswith("deploy failed for ") and "deploy failed for " in COLLECTOR, msg[:120])
    check(f"{label}: the message says why ({why}) and that nothing was deployed",
          why in msg and "Nothing was deployed." in msg, msg[:200])
check("no refused manifest was applied (no PATCH reached the API server)",
      not [a for a in applied if a and a[0] == "PATCH"], str(applied))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("Every refused manifest reaches the agent as an error.")
