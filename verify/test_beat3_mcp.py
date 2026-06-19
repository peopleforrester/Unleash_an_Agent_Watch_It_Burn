# ABOUTME: Render-gate check for Beat 3 (bad MCP + clown-file): rogue tools exist (BEFORE leaks/drops),
# ABOUTME: the gateway allowlist denies them (AFTER), and the clown-file is non-compliant so Kyverno rejects it.
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
BEAT = REPO / "beats" / "03-bad-mcp-excessive-agency"
SERVER = (BEAT / "evil-mcp-shim" / "server.py").read_text()
AUTHZ_ON_TEXT = (REPO / "agent" / "gateway" / "mcp-authz-on.yaml").read_text()
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

# AFTER: parse the ACTIVE gateway allowlist rules (FORM A) and assert neither rogue tool is permitted.
cm = next(d for d in yaml.safe_load_all(AUTHZ_ON_TEXT) if d and d.get("kind") == "ConfigMap")
rules = yaml.safe_load(cm["data"]["config.yaml"])["policies"]["mcpAuthorization"]["rules"]
rules_text = " ".join(rules)
check("active allowlist does NOT permit read_internal_config", "read_internal_config" not in rules_text)
check("active allowlist does NOT permit apply_optimization", "apply_optimization" not in rules_text)

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
