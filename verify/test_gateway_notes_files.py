# ABOUTME: Render gate for agent/GATEWAY-NOTES.md (#546): every repo path it names exists, agent/gateway/ holds no
# ABOUTME: pre-gitops overlay again, and the guard objects and /toggle keys the notes name are the deployed ones.
"""Why this exists (#546, after #479).

agent/gateway/ held agentgateway overlays (agentgateway.yaml, mcp-authz-*, input-guard-*, output-guard-*,
llm-guard-*) written for the pre-gitops v1.2 config shape. Nothing applied them, yet GATEWAY-NOTES.md named
them as each guard's "Files", so a reader chasing a guard landed on YAML that was not running. The guards run
in guard-proxy and LLM Guard under gitops/ai-layer/, toggled at runtime through guard-proxy's /toggle.
"""
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
NOTES = (REPO / "agent" / "GATEWAY-NOTES.md").read_text(encoding="utf-8")
BEAT2 = REPO / "challenges" / "02-sanitization"

failures = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


print("== every repo path the notes name exists ==")
paths = sorted(set(re.findall(r"`((?:gitops|challenges|verify|docs|infra)/[^`\s{}]+)`", NOTES)))
check("the notes name repo paths at all", bool(paths))
for rel in paths:
    check(f"{rel} exists", (REPO / rel).exists())

print("== agent/gateway/ holds no pre-gitops overlay ==")
overlays = sorted(str(p.relative_to(REPO)) for p in (REPO / "agent" / "gateway").glob("*.yaml"))
check(f"agent/gateway/ has no top-level YAML overlay (found {overlays})", not overlays)

print("== the guard objects the notes name are deployed ==")
docs = [d for d in yaml.safe_load_all((REPO / "gitops" / "ai-layer" / "resources.yaml").read_text()) if d]
names = {(d.get("kind"), d.get("metadata", {}).get("name")) for d in docs}
for kind, name in (("Deployment", "guard-proxy"), ("Deployment", "llm-guard"), ("ConfigMap", "llm-guard-scanners")):
    check(f"GATEWAY-NOTES names {kind} {name}", name in NOTES)
    check(f"gitops/ai-layer/resources.yaml deploys {kind} {name}", (kind, name) in names)

print("== each toggle the notes name flips guard-proxy's /toggle ==")
for script, key in (("toggle-input-guard-on.sh", "input_blocklist"),
                    ("toggle-input-classifier-on.sh", "input_classifier"),
                    ("toggle-output-guard-on.sh", "output")):
    check(f"GATEWAY-NOTES names {script}", script in NOTES)
    text = (BEAT2 / script).read_text(encoding="utf-8")
    check(f"{script} hits /toggle?{key}=", f"/toggle?{key}=" in text)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nOK")
