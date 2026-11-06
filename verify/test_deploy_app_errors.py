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

Since #856 deploy_app closes a manifest that is only short of its closing braces, so the 2026-10-30 manifest is now
applied; verify/test_deploy_app_manifest_shapes.py holds that. The parse refusal here is a manifest nothing can read.
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

    def get_context(self):
        # No request in flight, as the real FastMCP has none outside its transport; deploy_app reads the
        # request's X-Witch-Name through it (#995) and so finds no name here.
        raise LookupError("a stand-in FastMCP: no MCP request in flight")

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


# Two keys with no comma between them: neither JSON, YAML, nor a JSON object short of its braces reads it.
UNREADABLE = '{"apiVersion": "apps/v1" "kind": "Deployment", "metadata": {"name": "joker-agatha-the-banshee"}}'
COLLECTOR = (REPO / "gitops/otel-collector/values.yaml").read_text(encoding="utf-8")

for label, manifest, why in (
        ("a manifest nothing can read", UNREADABLE, "could not parse"),
        ("an empty manifest", "   ", "empty"),
        ("a list of two objects, not one", '[{"kind": "Deployment"}, {"kind": "Service"}]', "apiVersion and kind"),
        ("no kind", '{"apiVersion": "apps/v1", "metadata": {"name": "x"}}', "apiVersion and kind"),
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
