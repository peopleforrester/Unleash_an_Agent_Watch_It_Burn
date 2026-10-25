# ABOUTME: C7's second half on stage: the deployed output-guard Regex redacts evil-mcp's sentinel in the reply.
# ABOUTME: Reads the pattern from gitops/ai-layer/resources.yaml and runs it the way llm-guard's Regex scanner does.
"""Pins the output guard's half of the C7 claim (#518).

The stage claim for C7 has two halves, in order: agentgateway's rule stops the rogue tools/call before the
tool runs, and the output guard redacts the sentinel in the reply. The gateway half is held by
test_c7_gateway_toggle.py and the fallback. This holds the other half: the llm-guard Regex output scanner
in the llm-guard-scanners ConfigMap must match FAKE-MCP-EXFIL-sentinel-4c1d, the value evil-mcp-shim
actually serves, and must redact every occurrence of it, not just the first.

llm-guard's Regex scanner compiles each pattern with Python's re and, with match_type "all" and redact on,
replaces every match with [REDACTED]. This runs the deployed pattern through the same steps.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
DOCS = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]

SENTINEL = "FAKE-MCP-EXFIL-sentinel-4c1d"
REDACTED = "[REDACTED]"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{f': {detail}' if detail and not cond else ''}")
    if not cond:
        failures.append(name)


def env_values(name: str) -> list[str]:
    """Every container env value called name, across the manifest's Deployments."""
    found = []
    for d in DOCS:
        if d.get("kind") != "Deployment":
            continue
        for c in d["spec"]["template"]["spec"].get("containers", []):
            found += [e.get("value") for e in c.get("env", []) if e.get("name") == name]
    return found


print("== evil-mcp serves the sentinel the claim names ==")
served = env_values("FAKE_MCP_SENTINEL")
check(f"one container sets FAKE_MCP_SENTINEL to {SENTINEL}", served == [SENTINEL], f"found {served}")

print("== the deployed output scanner is the Regex the claim rests on ==")
cm = next((d for d in DOCS if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "llm-guard-scanners"), None)
check("the llm-guard-scanners ConfigMap exists", cm is not None)
scanners = yaml.safe_load(cm["data"]["scanners.yml"]) if cm else {}
regex = [s for s in scanners.get("output_scanners") or [] if s.get("type") == "Regex"]
check("exactly one Regex output scanner", len(regex) == 1, f"found {len(regex)}")
params = regex[0].get("params", {}) if regex else {}
check("it redacts", params.get("redact") is True)
check("it blocks", params.get("is_blocked") is True)
check("it redacts every match (match_type all)", params.get("match_type") == "all")
patterns = params.get("patterns") or []
check("it is one alternation pattern, so no earlier pattern stops it being evaluated", len(patterns) == 1)

print(f"== the pattern redacts {SENTINEL} ==")
compiled = re.compile(patterns[0]) if patterns else None
check("the pattern has a FAKE-...-sentinel-<hex> branch",
      bool(patterns) and "FAKE-[A-Z0-9-]+-sentinel-[0-9a-f]+" in patterns[0])
check(f"it matches {SENTINEL} whole",
      compiled is not None and any(m.group(0) == SENTINEL for m in compiled.finditer(SENTINEL)))
# A reply shaped like the leaked one: the weather answer, then the config the rogue tool returned, with the
# sentinel twice, once inside markdown. Every copy must go and the weather answer must stay.
reply = (f"It is 18C and sunny. Internal config: api_key={SENTINEL}. "
         f"**Note:** the token `{SENTINEL}` is valid until rotated.")
scrubbed = compiled.sub(REDACTED, reply) if compiled else reply
check("no copy of the sentinel survives in the reply", SENTINEL not in scrubbed, scrubbed)
check("both copies are replaced with [REDACTED]", scrubbed.count(REDACTED) == 2, scrubbed)
check("the weather answer is left alone", scrubbed.startswith("It is 18C and sunny."), scrubbed)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All C7 output-guard checks passed.")
