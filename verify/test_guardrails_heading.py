# ABOUTME: The chat page's guardrails heading reads "No guardrails installed" until the first badge appears, and
# ABOUTME: "Guardrails installed" from then on, set by the same count that lights the badges, never by the hostname (#923).
"""Pins #923, the markup and the rule. verify/test_guardrails_heading_e2e.py renders both states in Chromium.

Seen on the public bot on 2026-11-05: the Backend Insights card's heading read "GUARDRAILS INSTALLED" over an empty
badge strip, which reads as a claim that guardrails are on. The heading now starts as "No guardrails installed" and
applyControls() sets it from `shown`, the count of badges it just rendered from /controls (or /guards). The text is
the only thing that changes: the element is the same `.card h3`, uppercased by CSS, in both states. The italic note
under it keeps its text and is still hidden only once a badge shows.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
PAGE = PAGE_PATH.read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(literal: str, after: int = 0) -> int:
    """The index of a literal this test cuts the page on, or exit naming it and the file."""
    i = PAGE.find(literal, after)
    if i < 0:
        print(f"FAILED: the anchor {literal!r} is not in {PAGE_PATH.relative_to(REPO)}")
        sys.exit(1)
    return i


start = anchor("  function applyControls(c){")
end = anchor("  // Back-compat alias", start)
FN = PAGE[start:end]

print("== the heading starts as the empty state ==")
heads = re.findall(r"<h3[^>]*\bid=\"badgeshead\"[^>]*>([^<]*)</h3>", PAGE)
check("there is exactly one #badgeshead heading", len(heads) == 1, str(heads))
check("it starts as 'No guardrails installed'", heads == ["No guardrails installed"], str(heads))
tag = re.search(r"<h3[^>]*\bid=\"badgeshead\"[^>]*>", PAGE)
check("it carries no class or inline style of its own, so it is the same .card h3 as before",
      tag is not None and tag.group(0) == '<h3 id="badgeshead">', tag.group(0) if tag else "")
card = PAGE[PAGE.find('<h3 id="badgeshead">'):PAGE.find('<h3 id="badgeshead">') + 400]
check("the badge strip and the note follow it in the same card",
      card.find('id="badges"') > 0 and card.find('id="badgesnote"') > card.find('id="badges"'))
check("the .card h3 rule uppercases it, so the room reads NO GUARDRAILS INSTALLED",
      re.search(r"\.card h3\{[^}]*text-transform:uppercase", PAGE) is not None)
check("no fixed 'Guardrails installed' heading is left in the markup", "<h3>Guardrails installed</h3>" not in PAGE)

print("== the italic note is unchanged ==")
check("the note keeps its text and class",
      '<div id="badgesnote" class="badgesnote">Guardrails will appear here when you install them.</div>' in PAGE)
check("the note is still italic", re.search(r"\.badgesnote\{[^}]*font-style:italic", PAGE) is not None)
check("the note still hides only once a badge shows", "if(note) note.hidden = shown>0;" in FN)

print("== applyControls sets the heading from the badge count ==")
rule = "if(head) head.textContent = shown>0 ? 'Guardrails installed' : 'No guardrails installed';"
check("the heading is set from shown, both ways", rule in FN)
check("it is set after the badges are counted", FN.find(rule) > FN.find("shown++;") > 0)
check("it reads the #badgeshead element", "document.getElementById('badgeshead')" in FN)
check("only its text changes: no class, style or hidden is touched",
      not re.search(r"head\.(className|classList|style|hidden|setAttribute|innerHTML)", FN))
# Code only: the comments above CHAT_ENDPOINT and in applyControls name the hostname to say why it is not used.
CODE = re.sub(r"//[^\n]*", "", FN)
check("the hostname plays no part in it", "location" not in CODE and "hostname" not in CODE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All guardrails-heading checks passed.")
