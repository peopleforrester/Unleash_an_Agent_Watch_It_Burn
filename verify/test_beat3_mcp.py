# ABOUTME: Render-gate check for Beat 3 (bad MCP + clown-file): rogue tools exist (BEFORE leaks/drops),
# ABOUTME: the C7 toggle's ON-state toolNames excludes them (AFTER), and Kyverno rejects the clown-file.
import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
BEAT = REPO / "challenges" / "03-bad-mcp-excessive-agency"
SERVER = (BEAT / "evil-mcp-shim" / "server.py").read_text()
TOGGLE = (BEAT / "toggle-mcp-authz-on.sh").read_text()
CLOWN = list(yaml.safe_load_all((BEAT / "clown-file.yaml").read_text()))[0]

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# BEFORE: the bad MCP exposes the cover tool plus both rogue tools (exfil + clown-file drop).
for tool in ("get_weather", "read_internal_config", "apply_optimization"):
    check(f"evil-mcp exposes {tool}", f"def {tool}(" in SERVER)
check("apply_optimization is poisoned to push an apply", "MUST apply" in SERVER or "Always apply" in SERVER)

# AFTER: C7's deployed control is the kagent toolNames allowlist the toggle patches onto workshop-agent's
# evil-mcp entry (the evil-mcp RemoteMCPServer dials evil-mcp-shim direct, not through agentgateway).
# Read the EVIL_TOOL each branch of the toggle writes and assert ON is get_weather alone.
def _evil_tool(state, branch):
    m = re.search(r"^  EVIL_TOOL='(.*)'$", branch, re.M)
    check(f"the toggle sets EVIL_TOOL in its {state} branch", m is not None)
    return json.loads(m.group(1)) if m else {}


branches = re.search(r'^if \[\[ "\$\{STATE\}" == "on" \]\]; then\n(.*?)^else\n(.*?)^fi$', TOGGLE, re.M | re.S)
check("the toggle branches on STATE == on", branches is not None)
ON_BRANCH, OFF_BRANCH = branches.groups() if branches else ("", "")
evil_on, evil_off = _evil_tool("ON", ON_BRANCH), _evil_tool("OFF", OFF_BRANCH)
on_server = evil_on.get("mcpServer", {})
check("the ON-state entry is the evil-mcp RemoteMCPServer",
      on_server.get("name") == "evil-mcp" and on_server.get("kind") == "RemoteMCPServer")
check("ON-state evil-mcp toolNames is exactly [get_weather]", on_server.get("toolNames") == ["get_weather"])
for tool in ("read_internal_config", "apply_optimization"):
    check(f"ON-state allowlist does NOT permit {tool}", tool not in on_server.get("toolNames", []))
    check(f"OFF-state allowlist does permit {tool} (the before-state the beat shows)",
          tool in evil_off.get("mcpServer", {}).get("toolNames", []))

# Defense in depth: the clown-file payload is non-compliant, so the CNCF wall rejects it if applied.
container = CLOWN["spec"]["template"]["spec"]["containers"][0]
check("clown-file is privileged (disallow-privileged denies)",
      container.get("securityContext", {}).get("privileged") is True)
check("clown-file has no resource limits (require-resource-limits denies)",
      "limits" not in container.get("resources", {}))
check("clown-file has no probes (require-probes denies)",
      "readinessProbe" not in container and "livenessProbe" not in container)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll beat-3 MCP/clown-file checks passed.")
