# ABOUTME: Every fix card states where its guardrail actually runs, in the same shape, and each statement
# ABOUTME: is checked against the code so the lab cannot drift from where enforcement really happens.
"""Pins the enforcement-point statements (#319).

The argument of the workshop is that the enforcement point moves: the kernel, then admission, then a
platform component in front of the model, then the agent's own capabilities. A student who finishes eight
challenges having learned eight tricks, without noticing they were installed in five different places, has
missed the thing the workshop exists to say.

Two failure modes this guards, and both have happened in this repo:

- **The layer claim drifts from the code.** Saying guard-proxy classifies prompts would be wrong: LLM Guard
  is a separate Deployment with its own pod, called over HTTP. That was Michael's question, and it is the
  one distinction a student is most likely to get wrong.
- **The taxonomy slips.** Calling a guard-proxy control "app-layer" concedes the thesis. Every control here
  is platform-owned; the developer shipped none of them.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
PROXY = (REPO / "gitops/ai-layer/proxy.py").read_text(encoding="utf-8")
RES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
DOC = (REPO / "docs/CHALLENGE-ASSETS.md").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


BLOCKS = re.findall(r'<div class="where">(.*?)</div>', LAB, re.S)

print("== every challenge says where its guardrail runs, in the same shape ==")
check(f"there are eight statements, one per challenge (found {len(BLOCKS)})", len(BLOCKS) == 8)
check("each opens with the same label", all("<b>Where this guardrail runs:</b>" in b for b in BLOCKS))
check("each names a place in the highlighted span", all('<span class="wpt">' in b for b in BLOCKS))
# The repeated closing clause is what makes the thesis land by repetition rather than by assertion.
check("each states what did NOT change", all('<span class="wnot">' in b for b in BLOCKS))
check("each closing clause says the agent's code is untouched",
      all("code" in b.split('class="wnot"')[1] and "unchanged" in b.split('class="wnot"')[1]
          for b in BLOCKS))
check("each names the owner as the platform, never the developer",
      all("platform" in b for b in BLOCKS))

print("== the five distinct places are all present, and named consistently ==")
PLACES = [
    ("the cluster network", "C1, the CNI"),
    ("the API server, at admission", "C2, Kyverno webhook"),
    ("the Linux kernel", "C3, KubeArmor via an LSM"),
    ("inside guard-proxy", "C4 and C5, the proxy's own code"),
    ("the API server, at authorization", "C8, RBAC"),
]
for phrase, why in PLACES:
    check(f"{why}: '{phrase}'", f'<span class="wpt">{phrase}</span>' in LAB)
check("C4 and C5 share the guard-proxy phrasing, because they are the same component",
      LAB.count('<span class="wpt">inside guard-proxy</span>') == 2)

print("== C6: the classifier is a SEPARATE service, not part of guard-proxy ==")
# The exact question that produced this issue. The code is the authority: llm-guard is its own Deployment
# and its own Service, reached over HTTP from the proxy.
check("the code really does call it over the network", "LLM_GUARD_URL" in PROXY and "http://llm-guard" in PROXY)
check("it really is its own Deployment", re.search(r"kind: Deployment\s+metadata:\s+name: llm-guard", RES) is not None)
c6 = next((b for b in BLOCKS if "LLM Guard" in b), "")
check("C6's statement exists", bool(c6))
check("it says the block list is inside the proxy", "block list is inside guard-proxy" in c6)
check("it says the classifier is NOT", "is <b>not</b>" in c6)
check("it names the separate deployment", "separate deployment" in c6)
check("it tells the student how to see both", "get pods" in c6)

print("== C7 and C8 block nothing, and say so ==")
c7 = next((b for b in BLOCKS if "nowhere in the request path" in b), "")
check("C7 states there is no check to evade", "no check to evade" in c7)
check("C8 distinguishes authorization from admission", "Not admission" in LAB)
check("C8 says the capability is gone rather than inspected", "cannot reach what it used to reach" in LAB)

print("== the taxonomy is not conceded ==")
# Calling a platform-injected control "app-layer" gives away the argument. It must appear nowhere.
check("no fix card calls anything app-layer", "app-layer" not in LAB.lower())
check("guard-proxy is described as a platform component the developer never shipped",
      LAB.count("the developer never shipped") >= 3)

print("== the doc and the lab agree about the layers ==")
# CHALLENGE-ASSETS.md used to group C7 and C8 as changing "the agent itself", which reads as developer-
# owned and contradicts the taxonomy. Both files now say platform.
check("the doc names the same five places", all(p in DOC for p, _ in PLACES))
check("the doc does not imply C7/C8 are the developer's", "change the **agent itself**" not in DOC)

print("== C8's fix card no longer contradicts itself about which Secret survives ==")
# The Role names ceo-personal-record since #306. Two lines in this card still said "the recipe".
check("the card says the agent needs the CEO record", "the CEO record, for Challenge 5" in LAB)
check("the after-check names the Secret the Role actually permits",
      "still fetch <code class=\"inl\">ceo-personal-record</code> by name" in LAB)
check("no line in C8 still calls the surviving Secret the recipe",
      "still fetch the recipe by name" not in LAB and "only needs one (the recipe)" not in LAB)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All enforcement-point checks passed.")
