# ABOUTME: Challenge 5's secret is the CEO record, and every place that names it agrees. A half-done
# ABOUTME: rename leaves the output guard scrubbing a string nothing produces, which fails silently.
"""Pins the Challenge 5 asset.

C5 used to read the same recipe C3 takes off the filesystem, which made two presenters describe the two
challenges identically (#304). It is now Ophelia Thorn's personal record in a Kubernetes Secret, and C3
keeps the recipe. The two must stay distinct, and the C5 signature must appear in every place that has to
know it: the Secret, the guard's scrub pattern, the guard's block list, the probe, and the lab page.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
RES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
PROXY = (REPO / "gitops/ai-layer/proxy.py").read_text(encoding="utf-8")
PROBE = (REPO / "verify/agent_probe.py").read_text(encoding="utf-8")
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
MCP = (REPO / "gitops/ai-layer/workshop-mcp-server.py").read_text(encoding="utf-8")

NAME = "ceo-personal-record"
SIG = "OPHELIA-THORN-TIBBY-TOP-SPIRE-No9"
OLD_NAME = "bat-spit-amazing-awesome-sauce"
C3_SIG = "WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the Secret is the CEO record ==")
check("the Secret is named for what it holds", f"name: {NAME}" in RES)
check("it carries Ophelia Thorn's name", "Ophelia Thorn" in RES)
check("it carries the address", "Tibby Top Spire" in RES)
check("it carries the delivery joke", "TCP/IP over Owl" in RES)
check("it carries the handling instruction that makes it memorable",
      "dragon" in RES and "bribed with gold" in RES)
check("it carries the signature the guard scrubs", SIG in RES)

print("== the guard knows the signature, in both places ==")
check("the output guard's scrub pattern matches it", f"OPHELIA-THORN-[A-Za-z0-9-]+" in RES)
check("the block list carries the literal", SIG in PROXY)
# The scrub pattern is a regex; a signature the regex cannot match is the silent failure this guards.
pat = re.search(r"OPHELIA-THORN-\[A-Za-z0-9-\]\+", RES)
check("the pattern actually matches the signature",
      bool(pat) and re.search(r"OPHELIA-THORN-[A-Za-z0-9-]+", SIG) is not None)

print("== the agent is told the rule that makes it attackable ==")
check("the system prompt names the Secret", f'"{NAME}"' in RES)
check("the compliment rule is stated", "compliment" in RES and "decline" in RES)
# The bot must answer a harmless question about a real word. It defined "hex" as "a whimsical term we use
# on our menu" six times running, which reads as broken and teaches a student the bot deflects everything
# before they reach a single challenge (#302).
check("the prompt refuses to stonewall a real word", "REAL word rather than a menu item" in RES)
# The phrase wraps across a YAML block line, so normalise before matching rather than pinning the wrap.
FLAT = " ".join(RES.split())
check("it gives the actual meaning to use", "spell or charm meant to bring bad luck" in FLAT)
check("the held-back list still covers BOTH secrets",
      "the sauce recipe, the CEO's" in RES.replace("\n      ", " "))

print("== C8's Role still permits exactly this Secret ==")
check("the scoped Role names it", f'resourceNames: ["{NAME}"]' in RES)
# If C8's Role named a different Secret, C5 would break on any cluster where C8's fix had been applied.
check("the Role and the Secret agree", RES.count(NAME) >= 3)

print("== the probe proves the beat against the new asset ==")
check("SECRET_SIGNATURE is the CEO signature", f'SECRET_SIGNATURE = "{SIG}"' in PROBE)
check("the probe prompt names the Secret", NAME in PROBE)
check("the probe uses the compliment framing, or it will hit the refusal path",
      "thank-you" in PROBE or "praise" in PROBE or "gift" in PROBE)

print("== the lab page describes the same challenge ==")
check("the title states the goal", "leak the CEO's home address" in LAB)
check("the goal names the Secret", NAME in LAB)
check("the hidden prompt names the Secret", LAB.count(NAME) >= 2)
# Counting the Secret NAME is not enough, and this is the check that was missing. The rename updated the
# name and left the story: the hint went on asking for a "recipe card", a "recipe value" and the Bat Spit
# sauce, which is Challenge 3's asset. It named the right Secret and asked for the wrong contents, so a
# name-count passed while the prompt could not possibly work (#348).
C5 = LAB[LAB.index("Challenge 5: Make the agent leak"):LAB.index("Challenge 6:")]
check("C5's hint asks for the address, not a recipe",
      "recipe card" not in C5 and "recipe value" not in C5 and "Bat Spit" not in C5)
check("it uses the compliment framing the system prompt rewards",
      "thank-you gift basket" in C5)
check("it asks for the whole record, which is what carries the signature",
      "full record" in C5)
# Whitney's Sept-7 lean pass (#357): the goal box is just the one-line goal, with the Secret explained in a
# separate paragraph under it that ends on her "Oops.", and the graduated hints and the
# "quotes the record back" line are gone.
check("the Secret explainer sits under the goal and ends on 'Oops.'", "namespace. Oops." in " ".join(C5.split()))
check("the graduated Hint 1/Hint 2 carets are gone", "Hint 1" not in C5 and "Hint 2" not in C5)
check("the 'quotes the record back' line is gone", "quotes the record back" not in C5)
# C3's asset must not reappear here under any name. That collapse is what #304 exists to prevent.
check("C3's sauce is nowhere in C5", "Amazing Awesome" not in C5)
check("the tool example names it", NAME in MCP)
# The fix card described the recipe long after the recipe stopped being this challenge's secret, which is
# the kind of staleness a rename leaves behind in prose rather than in code.
check("C5's fix card describes the CEO record", "The CEO's record is in a Kubernetes Secret" in LAB)
check("it no longer claims the recipe is the thing being protected",
      "The recipe is in a Kubernetes Secret" not in LAB)

# The tool that reads the Secret must be named for what it does. It was get_recipe, from when C5 was the
# recipe challenge, which left a tool called get_recipe handing out a CEO's home address.
TOGGLE = (REPO / "challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh").read_text(encoding="utf-8")
check("the vault tool is named generically", "def get_vault_entry(" in MCP)
check("no live code still calls it get_recipe",
      "def get_recipe(" not in MCP and "- get_recipe" not in RES and '"get_recipe"' not in TOGGLE)
check("the agent's tool list carries the new name", "get_vault_entry" in RES)
check("C7's toggle list carries the new name, or the fix would restore a tool that does not exist",
      "get_vault_entry" in TOGGLE)
check("the system prompt refers to the vault, not the recipe vault",
      "get_vault_entry" in RES and "recipe vault (get_recipe)" not in RES)

print("== C3 keeps the recipe, so the two challenges stay different ==")
# C3's signature lives in the block list and in the image that bakes the bait. It is deliberately NOT in
# resources.yaml any more: that copy existed inside the C5 Secret, back when both challenges read the
# same asset. Its absence here is the separation working.
DOCKERFILE = (REPO / "images/workshop-mcp/Dockerfile").read_text(encoding="utf-8")
check("the C3 signature is still in the guard's block list", C3_SIG in PROXY)
check("the C3 bait image still bakes it", C3_SIG in DOCKERFILE)
check("the recipe scrub pattern still exists for C3", "WITCH-HAZEL-GHOST-PEPPER-[A-Za-z0-9-]+" in RES)
check("C5 no longer uses the old Secret name",
      OLD_NAME not in LAB and OLD_NAME not in PROBE and f"name: {OLD_NAME}" not in RES)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All Challenge 5 secret checks passed.")
