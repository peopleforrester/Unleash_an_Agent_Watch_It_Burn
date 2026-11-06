# ABOUTME: PROGRESS.md carries the changelog entries of #759 (both), #905 and #915 (#892): each a dated bullet,
# ABOUTME: once, under a ### heading in [Unreleased], that records the facts of its change as literal text.
"""Pins the "Update PROGRESS.md" criterion of #759, #905 and #915, which no test checked (#892).

#759 has two entries: the 2026-11-03 bullet for verify/dd_traces.py and the 2026-11-05 "live check" bullet that
#892 names. #905 (the allergen card) and #915 (the /display page's masked prompts) reported the same gap on #892.
The facts are read as literal text, not from the code: a changelog line is history, and a later change gets its
own entry rather than rewriting an old one. The finder is also run with each entry taken out, moved below
[Unreleased], stripped of its date, doubled and left with no ### heading above it, so a check that could never
fail would show up here. verify/test_progress_764.py holds #764's entry the same way.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PROGRESS = (REPO / "PROGRESS.md").read_text(encoding="utf-8")

# (issue, the line's start, [(what the check says, the literal text the entry must hold), ...])
ENTRIES: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("#759", "- (2026-11-03) #759:", [
        ("it names the reader it added", "`verify/dd_traces.py`"),
        ("it names the app whose traces are read", "`ml_app:burritobot`"),
        ("it says the APM spans come with --apm", "`--apm`"),
        ("it says only GETs are sent", "GETs only"),
        ("it names the secret the read-only pair lives in", "Secrets Manager `watch-it-burn/datadog`"),
        ("it gives a dispatched run's command",
         "`. \"$HECATON_CLUSTER_ENV\"` then `python3 verify/dd_traces.py --profile accen-dev --minutes 1440 "
         "--traces 1 --apm`"),
        ("it says other orgs are refused", "refuses any org but the sandbox org"),
        ("it names the offline tests", "`verify/test_dd_traces.py`"),
        ("it names the live check", "`verify/test_dd_traces_live.py`"),
        ("it says the live read was owed and why", "run 16653 could not read its session files"),
        ("it points at its decisions.md entry", "(decisions.md, 2026-11-03, #759)"),
    ]),
    ("#759", "- (2026-11-05) #759, live check:", [
        ("it says a dispatched run read the newest trace",
         "a dispatched run read BurritoBot's newest `ml_app:burritobot` trace and its APM spans"),
        ("it names the secret the pair was read from", "Secrets Manager `watch-it-burn/datadog`"),
        ("it gives the command it ran",
         "`. \"$HECATON_CLUSTER_ENV\"` then `python3 verify/dd_traces.py --profile accen-dev --minutes 1440 "
         "--traces 1 --apm`"),
        ("it names the two read permissions the pair carries", "`llm_observability_read` and `apm_read`"),
        ("it says no new key is needed", "no new key is needed"),
        ("it names the new --scopes mode", "New `--scopes`"),
        ("it names the application key and its scope count", "(`Burritobot-app-key`, 145 scopes)"),
        ("it says --scopes fails on any scope that is not read-only", "exits 1 unless every scope is read-only"),
        ("it says the live test runs --scopes", "`verify/test_dd_traces_live.py` runs it after the trace read"),
        ("it points at its decisions.md entry", "(decisions.md, 2026-11-05, #759)"),
    ]),
    ("#905", "- (2026-11-05) #905:", [
        ("it says what BurritoBot now answers", "BurritoBot answers allergy and diet questions"),
        ("it names the persona file the card is in", "`gitops/workshop-agent/agent.yaml`"),
        ("it names the nine allergens", "the nine major US allergens per item"),
        ("it names the diet tags", "vegan, vegetarian and gluten-free tags"),
        ("it records the chicken stock fact",
         "chicken stock in Black-Bog Rice and none in Cilantro-Slime Rice"),
        ("it names the three made-up allergies", "(fun, cursed food, anything made under a full moon)"),
        ("it says the secret sauce holds none of the nine", "The secret sauce recipe has none of the nine"),
        ("it names guard-proxy's topic list change", "guard-proxy's `TOPIC_ON_LIST`"),
        ("it records the refusal that moved it",
         "live BanTopics alone refused \"I'm allergic to anything made under a full moon\""),
        ("it names the card's test", "`verify/test_allergen_card.py`"),
        ("it names the 18 topic cases", "`verify/topic_cases.py` adds 18 allergy asks"),
        ("it names the probe's new beat", "`topic-on-3`"),
        ("it says the probes after deploy are owed", "The probes on both clusters after deploy are owed"),
        ("it points at its decisions.md entry", "(decisions.md, 2026-11-05, #905)"),
    ]),
    ("#915", "- (2026-11-05) #915:", [
        ("it names the page it changed", "the `/display` page (`gitops/ai-layer/web/display.js`)"),
        ("it says masked prompts are left off", "leaves off any prompt whose text contains `[redacted]`, in any case"),
        ("it says unmasked prompts still show", "prompts without the mask still show, newest first"),
        ("it says moderate() and its feed are unchanged", "guard-proxy's `moderate()` and its feed are unchanged"),
        ("it says /prompts keeps the masked copy", "`/prompts` keeps the masked copy"),
        ("it names the tools-tier test", "`verify/test_display_masked_prompts_e2e.py` (tools tier)"),
        ("it names the offline test", "`verify/test_stream.py`"),
        ("it names the wall's change", "prompts-agenticburn#15"),
        ("it says the live check after deploy is owed", "the live check on `/display` after deploy is owed"),
        ("it points at its decisions.md entry", "(decisions.md, 2026-11-05, #915)"),
    ]),
]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def unreleased(text: str) -> str:
    """The [Unreleased] section: from its heading to the next level-2 heading, or the end of the file."""
    m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(1) if m else ""


def entry(text: str, head: str) -> str:
    """The one line starting `head` in [Unreleased], under a ### heading; empty when there is not exactly one."""
    section = unreleased(text)
    lines = [ln for ln in section.splitlines() if ln.startswith(head)]
    if len(lines) != 1:
        return ""
    before = section[: section.index(lines[0])]
    return lines[0] if re.search(r"^### \S", before, flags=re.M) else ""


def undated(head: str) -> str:
    """`head` with its "(YYYY-MM-DD) " taken out; exits naming the head when it has no such date."""
    out = re.sub(r"^- \(\d{4}-\d{2}-\d{2}\) ", "- ", head)
    if out == head:
        sys.exit(f"test_progress_entries.py: the head {head!r} carries no '(YYYY-MM-DD) ' date to strip")
    return out


print("== PROGRESS.md is a Keep a Changelog file with an [Unreleased] section ==")
check("PROGRESS.md opens with the Changelog title", PROGRESS.startswith("# Changelog\n"))
check("it has an [Unreleased] section", bool(unreleased(PROGRESS).strip()))

# The heads are distinct, and no head is the start of another, so each finder reads its own line.
heads = [head for _, head, _ in ENTRIES]
check("each entry's head is its own", all(not b.startswith(a) for a in heads for b in heads if a != b))

for issue, head, facts in ENTRIES:
    found = entry(PROGRESS, head)
    print(f"== {issue}'s entry {head!r} is there, once, under a ### heading in [Unreleased] ==")
    check(f"{issue} {head!r}: the entry is found", bool(found),
          f"no single line starting {head!r} under a ### heading in [Unreleased]")

    print(f"== {issue} {head!r} records what the change did ==")
    for name, literal in facts:
        check(f"{issue} {head!r}: {name}", literal in found, f"the entry does not hold {literal!r}")

    print(f"== {issue} {head!r}: the finder fails when the criterion stops holding ==")
    # An empty entry has already failed above; these still run so the suite never branches on the result.
    line = found or head
    without = PROGRESS.replace(line + "\n", "")
    check(f"{issue} {head!r}: with the entry removed, it is not found", entry(without, head) == "")
    moved = without + "\n## [0.0.0]\n\n### Added\n" + line + "\n"
    check(f"{issue} {head!r}: moved out of [Unreleased], it is not found", entry(moved, head) == "")
    check(f"{issue} {head!r}: without its date, it is not found",
          entry(PROGRESS.replace(line, undated(head) + line[len(head):]), head) == "")
    check(f"{issue} {head!r}: duplicated, it is not found",
          entry(PROGRESS.replace(line, line + "\n" + line), head) == "")
    check(f"{issue} {head!r}: with no ### heading above it, it is not found",
          entry("# Changelog\n\n## [Unreleased]\n\n" + line + "\n", head) == "")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print(f"All {len(ENTRIES)} PROGRESS.md entry checks passed (#759, #905, #915).")
