# ABOUTME: AGENTS.md's "Tests own their inputs" section names the two runs #797 was filed for, its grep finds the
# ABOUTME: tests that read a phrase, and the witch-name test it cites pins every random draw and tries every first name.
"""Holds the friction #797 removed, as AGENTS.md states it.

Run 9643 (#612) reworded row 8's readiness cell in the KubeCon run-of-show, and the deck export's test, which edited
that file on the literal `| **At risk.**`, broke; the run put the old label back. Run 15808 (#583) saw the E2E tier
go red because `verify/test_storefront_witch_name_e2e.py` asserted "rude" was not in a randomly drawn name, and the
page's vocabulary has "Prudence". Both tests hung on something they did not own: text another change rewords, and a
random draw.

This checks that the section says what to do about each, that the grep it gives does find a test reading a phrase,
and that the witch-name test still runs with no unpinned draw and tries every first name the page can pick.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
AGENTS = REPO / "AGENTS.md"
WITCH = REPO / "verify" / "test_storefront_witch_name_e2e.py"

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def item(body: str, label: str) -> str:
    """The text of the numbered item whose bold label starts with `label`, continuation lines included."""
    m = re.search(rf"^\d+\. \*\*{re.escape(label)}.*?(?=^\d+\. |^\S|\Z)", body, re.M | re.S)
    return flat(m.group(0)) if m else ""


body = section(AGENTS.read_text(encoding="utf-8"), "Tests own their inputs")
intro = flat(body.split("\n1. ", 1)[0])

print("== AGENTS.md names the two runs and their causes ==")
check("a '## Tests own their inputs' section exists", bool(body.strip()))
for token in ("#797", "Run 9643 (#612)", "Run 15808 (#583)", "`| **At risk.**`", '"Prudence"'):
    check(f"its opening names {token}", token in intro)

print("== reword: find the tests that read the words first ==")
grep_item = item(body, "Find the tests that read the words")
cmd = "git grep -nF '<the exact words you are changing>' -- verify scripts"
check(f"it gives `{cmd}`", f"`{cmd}`" in grep_item)
check("it says the test changes in the same commit as the text", "same commit as the text" in grep_item)
check("it says correct text is never reverted to suit a test", "never reverted to suit a test" in grep_item)
# The command as given, on an anchor the witch-name test cuts the page on, lists that test.
anchor = "var WITCH_FIRST="
r = subprocess.run(["git", "grep", "-nF", anchor, "--", "verify", "scripts"], cwd=REPO, capture_output=True,
                   text=True)
check(f"the grep on {anchor!r} lists the witch-name test that reads it",
      r.returncode == 0 and "verify/test_storefront_witch_name_e2e.py:" in r.stdout, r.stderr or r.stdout[:300])

print("== an anchor is checked before it is used ==")
check("an item says an anchor a test edits or splits on is checked first",
      "exits naming the literal and the file" in item(body, "An anchor a test edits or splits on is checked first"))

print("== randomness is pinned or enumerated ==")
rand = item(body, "Randomness is pinned or enumerated")
check("an item says a test pins or enumerates randomness and each check holds for every value",
      "stubs `Math.random`" in rand and "holds for every one of them" in rand)
check("it says a test that passes on a rerun is broken, not flaky", "broken, not flaky" in rand)
check("it cites the witch-name test, which exists", "`verify/test_storefront_witch_name_e2e.py`" in rand
      and WITCH.is_file())
witch = WITCH.read_text(encoding="utf-8") if WITCH.is_file() else ""
check("the witch-name harness gives the page a stubbed Math, never the real one",
      "Math: M" in witch and "? Math :" not in witch and "Math," not in witch.split("HARNESS", 1)[-1])
check("its stub fails when the page draws more than a case pinned",
      "throw new Error('the page drew more random values than this case pinned')" in witch)
check("its replaced-cookie case runs once per first name", "for i in range(len(site.FIRST))]" in witch)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("AGENTS.md says how a test owns its inputs, and the test it cites does.")
