# ABOUTME: Render-gate check for P8 takeaway artifacts: governance map carries the cost ladder in
# ABOUTME: cost order, and the self-assessment exists. Content assertions, no cluster needed.
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
gov = (REPO / "facilitation" / "governance-map.md").read_text()
selfassess = REPO / "facilitation" / "self-assessment.md"

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


check("governance map has the cost ladder section", "cost ladder" in gov.lower())
# Cost order: input block-list (cheapest) appears before Kyverno admission (most expensive).
low = gov.lower()
check("ladder orders input block-list before Kyverno admission",
      low.find("input block-list") != -1 and low.find("input block-list") < low.rfind("kyverno admission"))
check("ladder states the input block-list flatlines the counter (zero tokens)",
      "flatline" in low and "zero" in low)
check("ladder names Kyverno as last and most expensive", "most expensive mile" in low)
check("self-assessment artifact exists and is non-trivial",
      selfassess.exists() and len(selfassess.read_text().split()) > 50)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll takeaway (P8) checks passed.")
