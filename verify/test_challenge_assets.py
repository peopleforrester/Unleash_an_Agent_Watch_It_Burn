# ABOUTME: docs/CHALLENGE-ASSETS.md names the asset and control for every challenge; this asserts each
# ABOUTME: name still matches the code, so a rename that misses the doc fails here instead of on stage.
"""Keeps the challenge mapping honest.

The table exists because two presenters described the same challenge differently in a recorded session
(#304). A table that drifts from the code is worse than no table: it is confidently wrong, and it is read
by someone about to say it out loud to a room.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DOC = (REPO / "docs/CHALLENGE-ASSETS.md").read_text(encoding="utf-8")
RES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
PROXY = (REPO / "gitops/ai-layer/proxy.py").read_text(encoding="utf-8")
DOCKERFILE = (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8")
KUBEARMOR = (REPO / "policies/kubearmor/block-recipe-snoop.yaml").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


# Each row: a fact the doc states, and the code that has to agree with it.
FACTS = [
    ("C1 names the egress policy", "agent-egress-allowlist", RES),
    ("C2 names the Kyverno policy", "restrict-image-registries", RES),
    ("C3 names the bait path", "/tmp/burrito-data/config/legacy", DOCKERFILE),
    ("C3 names the KubeArmor policy", "block-recipe-snoop", KUBEARMOR),
    ("C5 names the Secret", "ceo-personal-record", RES),
    ("C5 names the scrub signature", "OPHELIA-THORN-", RES),
    ("C7 names the first rogue tool", "read_internal_config", RES),
    ("C7 names the second rogue tool", "apply_optimization", RES),
    ("C8 names the scoped Role manifest", "c8-scoped-role.yaml", RES),
]

print("== every name in the table still exists in the code ==")
for label, needle, source in FACTS:
    check(f"{label} ({needle})", needle in DOC and needle in source)

print("== the two caps are stated correctly ==")
# 3 cents, and PER CONVERSATION. Both halves matter: the number was measured (10 cents was ~20 sends of
# the expensive prompt, #345) and the scope is what stops Challenge 4 killing the rest of the lab (#346).
check("the demo cap is 3 cents in the doc and the proxy",
      "BUDGET_CAP_USD" in DOC and '"0.03"' in PROXY and "0.03" in DOC)
check("the doc says the demo cap is per conversation", "per conversation" in DOC)
check("the proxy measures it per session, not cluster-wide",
      "def cost_capped(session=" in PROXY and "_session_cost" in PROXY)
check("the cluster-wide backstop is still cluster-wide",
      "spend >= COST_CAP_USD" in PROXY)
check("the safety cap is 25 dollars in the doc and the manifest",
      "COST_CAP_USD" in DOC and 'COST_CAP_USD, value: "25"' in RES and "25 dollars" in DOC)

print("== C3 and C5 are still different assets ==")
# The whole point of the table. If these ever read the same object again, the confusion returns.
check("C3's asset is a file on disk", "file baked into the workshop-mcp image" in DOC)
check("C5's asset is a Kubernetes Secret", "Kubernetes Secret **`ceo-personal-record`**" in DOC)
check("the doc says why they differ", "two different layers" in DOC)
check("the C5 Secret is not the recipe", "bat-spit-amazing-awesome-sauce" not in DOC)

print("== every challenge has a row ==")
for n in range(1, 9):
    check(f"challenge {n} is in the table", f"| {n} |" in DOC)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All challenge-asset checks passed.")
