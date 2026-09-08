# ABOUTME: Every fix card teaches the concept before it names the tool, in the same shape, using Whitney's
# ABOUTME: own published writing verbatim where she supplied it rather than paraphrasing it into our voice.
"""Pins the concept-first pattern and Whitney's text (#322).

Her instruction was structural, not stylistic: *"first thing we do is teach high-level concepts about what
exactly is happening here. Then we can drill into the specific technology."* A student who has never met an
admission controller met Kyverno first and had to reverse-engineer the idea from the implementation.

She then supplied several thousand words of her own published writing and asked for it verbatim where it
fits. That instruction is easy to honour on the day and easy to erode later, one tidy-up at a time, which
is what this test is for. The strings below are hers; if a rewrite changes them it should be because she
changed them.

It also asserts the SHAPE, because she asked for the pattern to apply to every challenge: a concept
heading before the tool is named, and the tool named after it.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB = (REPO / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
FLAT = " ".join(LAB.split())

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def card(n: int, nxt: str) -> str:
    i = LAB.index(f"Challenge {n}:")
    return " ".join(LAB[i:LAB.index(nxt, i)].split())


C2 = card(2, "Challenge 3:")
C3 = card(3, "Challenge 4:")

print("== Challenge 2 teaches cluster-level policy before it names Kyverno ==")
check("it defines a policy in her words",
      "A policy is an organization-specific rule about what actions" in C2)
check("and an admission controller policy specifically",
      "a rule specifically about what you are allowing into your Kubernetes cluster" in C2)
for reason in ("Security", "Governance", "Automation", "Cost Optimization"):
    check(f"the {reason} example survives", f"<b>{reason}</b>" in LAB)
check("the two-step webhook mechanism is explained",
      "teaches the kube-API server" in C2 and "configuration for the kube-API server" in C2)
check("her aside about the confusing name is kept",
      "does not run as a reconciliation loop" in C2)
check("validating and mutating are distinguished", "validating" in C2 and "mutating" in C2)
# She asked for the alternatives named without dwelling on the differences, and for native Kubernetes.
check("the alternatives are named", "OPA Gatekeeper" in C2 and "Kubewarden" in C2)
check("native Kubernetes is named too", "ValidatingAdmissionPolicy" in C2)
check("Kyverno comes AFTER the concept",
      C2.index("A policy is an organization-specific rule") < C2.index("This cluster runs"))

print("== Challenge 3 teaches runtime policy before it names KubeArmor ==")
# Both of the supply-chain paragraphs that used to be pinned here (the dependency-of-dependency framing
# and the "Do you completely trust another company's security practices?" question) were removed at her
# instruction: she wanted the section to start on "What is a runtime policy?" and answer it directly,
# rather than argue its way there. The definition below is her sentence from doc line 630. Do not
# restore the removed paragraphs.
check("the section opens by defining a runtime policy",
      "protect a system from security vulnerabilities and threats" in C3)
check("unknown unknowns, which is the phrase that lands",
      "unknown unknowns" in C3)
check("the scale question is asked before it is answered",
      "How can a runtime security tool even begin to monitor them all?" in C3)
check("the kernel-level answer is hers",
      "monitoring is done at the <b>kernel level</b>" in LAB and "not application-specific" in C3)
check("the kinds of kernel event are listed",
      "a process being executed, a file being opened" in C3)
check("what a runtime policy does is left to the tool",
      "What that something is depends on the tool" in C3)

print("== the tools are described in her words too ==")
check("Falco is a cloud native threat detector", "cloud native <b>threat detector</b>" in LAB)
check("a threat is defined", "an event that could endanger the system" in C3)
check("a Falco Rule is defined", "a YAML file that defines the conditions under which an alert" in C3)
# Her example of what Talon does is exactly what this cluster does, which is why it is worth using.
check("Talon is introduced as she introduces it",
      "which can take action on alerts. For example, when an alert happens then kill a container" in C3)
check("KubeArmor's definition is hers",
      "cloud native runtime security engine that helps you monitor your system at the kernel level" in C3)
check("the line that carries this whole challenge is kept",
      "By the time you see an alert, an attack may have already happened" in C3)
check("inline enforcement is named", "inline enforcement" in C3)
# Whitney asked for the mechanism explained rather than named: "If you're going to explain the
# mechanism, take time and really explain the mechanism to someone who's technical but doesn't know
# anything about this particular field." LSM and eBPF were acronyms doing the work of an explanation.
# What is pinned now is that the explanation says WHERE the decision is made and WHY that matters.
check("the mechanism is explained, not just named",
      "from inside the Linux kernel itself" in C3
      and "before the read returns any bytes" in C3)

print("== the shape is the same on both, since she asked for a pattern ==")
for n, c in ((2, C2), (3, C3)):
    check(f"C{n} opens its teaching with a concept heading", '<h3 class="sub">What is a' in c)
# The "Where this guardrail runs" blocks were cut from every challenge at Whitney's request (#357); the
# layer mapping moved to docs/CHALLENGE-ASSETS.md. See test_enforcement_points.py. What this file guards
# is the concept-before-tool ORDER, which is unaffected by that cut.
check("the cut blocks did not come back", "Where this guardrail runs" not in LAB)

# ---------------------------------------------------------------------------
print("== EVERY fix section teaches the concept before it names the tool (#380) ==")
# Whitney: "The fix section first goes over the idea behind the fix at a high level: What is
# Cluster-Level Policy? How does it work? Why do you need it? ... We're going to use Kyverno. Here is
# what Kyverno is." followed by "That's the pattern. Please take this pattern and apply it to every
# challenge."
#
# Measured 2026-09-08: five of eight opened their fix card by naming the tool. This check is the
# structural version of her rule, so a new challenge cannot ship without one and an edit cannot quietly
# reorder an existing one. It asserts a <h3 class="sub"> heading appears inside the "How to..." fix card
# BEFORE the first named tool.
import re as _re
_TOOLS = ["Kyverno", "KubeArmor", "Falco", "LLM Guard", "guard-proxy", "kagent", "KMCP",
          "NetworkPolic", "RBAC"]
_src = (pathlib.Path(__file__).resolve().parent.parent
        / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
_bounds = [(m.group(1), m.start()) for m in _re.finditer(r'class="step c(\d)"', _src)]
_bounds.append(("end", len(_src)))
_seen = 0
for _i, (_n, _st) in enumerate(_bounds[:-1]):
    _seg = _src[_st:_bounds[_i + 1][1]]
    _m = _re.search(r"<summary>(How to[^<]*)</summary>(.*?)</details>", _seg, _re.S)
    if not _m:
        continue
    _seen += 1
    _body = _m.group(2)
    _sub = _re.search(r'<h3 class="sub">([^<]+)</h3>', _body)
    _first = min([_body.find(t) for t in _TOOLS if _body.find(t) >= 0] or [10 ** 9])
    check(f"C{_n}'s fix card opens on a concept, not a tool",
          _sub is not None and _sub.start() < _first)
check("all eight challenges have a fix card to check", _seen == 8)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All concept-before-tool checks passed.")
