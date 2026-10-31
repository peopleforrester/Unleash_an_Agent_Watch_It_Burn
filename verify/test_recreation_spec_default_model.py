# ABOUTME: docs/MASTER-RECREATION-SPEC.md names as the workshop default model the ModelConfig the Agent in
# ABOUTME: gitops/workshop-agent/agent.yaml binds, and no line of it calls another tier the default.
#
# Why (#573). eac3dbc (2026-07-05) moved the workshop-agent from bedrock-sonnet to bedrock-nova, and the
# 2026-07-25 correction fixed the spec's ModelConfig paragraph and recreation step 5. Part VII's request-chain
# diagram still ended at "sonnet[default]" and its Key Decisions bullet still opened "Workshop default model is
# Sonnet 4.6", so a rebuild reading either would have bound the tier that refuses the exfil beats.
import pathlib, re, sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SPEC = "docs/MASTER-RECREATION-SPEC.md"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


docs = [d for d in yaml.safe_load_all((REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")) if d]
# The Agent is the workshop-agent Application's since #707; the ModelConfigs it names stay in ai-layer.
agents = [d for d in yaml.safe_load_all((REPO / "gitops/workshop-agent/agent.yaml").read_text(encoding="utf-8"))
          if d and d.get("kind") == "Agent" and d["metadata"]["name"] == "workshop-agent"]
check("gitops/workshop-agent/agent.yaml has one workshop-agent Agent", len(agents) == 1, f"found {len(agents)}")
bound = agents[0]["spec"]["declarative"]["modelConfig"] if agents else ""
configs = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "ModelConfig"}
check(f"the bound ModelConfig {bound} is defined in resources.yaml", bound in configs)
# bedrock-nova -> nova: the tier word the spec and guard-proxy's MODEL_TIER use for it.
tier = bound.removeprefix("bedrock-")
TIERS = ("nova", "haiku", "sonnet", "opus")
check(f"the bound ModelConfig {bound} is one of the Bedrock tiers {TIERS}", tier in TIERS)

lines = (REPO / SPEC).read_text(encoding="utf-8").splitlines()

print(f"== {SPEC} names {bound} the default ==")
check(f"{SPEC} has a line naming `{bound}` and calling it the default",
      any(f"`{bound}`" in l and re.search(r"(?i)\bdefault", l) for l in lines))

print(f"== {SPEC} calls no other tier the default ==")
others = [t for t in TIERS if t != tier]
# "sonnet[default]" in a diagram, "default model is Sonnet 4.6" in prose, "defaults to `bedrock-sonnet`" in a step.
patterns = [
    re.compile(rf"(?i)\b({'|'.join(others)})\w*\s*\[default\]"),
    re.compile(rf"(?i)\bdefault model is\s+\W*({'|'.join(others)})"),
    re.compile(rf"(?i)\bdefaults? to\s+\W*(bedrock-)?({'|'.join(others)})"),
]
# The dated correction note at the top records the old default as history; it is not a claim about the build.
bad = [(i, l.strip()) for i, l in enumerate(lines, 1)
       if not l.startswith(">") and any(p.search(l) for p in patterns)]
check(f"{SPEC} calls only {bound} the default (lines {[i for i, _ in bad]})", not bad,
      "; ".join(f"{i}: {l[:120]}" for i, l in bad))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll recreation-spec default model checks passed.")
