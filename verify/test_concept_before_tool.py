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
check("the dependency-of-dependency framing is hers",
      "which in turn each have their own supporting services and dependencies" in C3)
check("the third-party trust question is kept",
      "Do you completely trust another company's security practices?" in C3)
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
check("LSMs and eBPF are both credited", "Linux Security Modules (LSMs)" in C3 and "eBPF" in C3)

print("== the shape is the same on both, since she asked for a pattern ==")
for n, c in ((2, C2), (3, C3)):
    check(f"C{n} opens its teaching with a concept heading", '<h3 class="sub">What is a' in c)
    check(f"C{n} still says where the guardrail runs", "Where this guardrail runs:" in c)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All concept-before-tool checks passed.")
