# ABOUTME: Pins #1140's record (#1212): its decisions.md entry names, as owed live, Whitney opening each attack trace
# ABOUTME: from its slide's link and confirming it shows what the slide says, and names every seed with no /kubecon beat.
"""Holds the criterion of #1140 that test review run 18731 found no test checked (#1212).

#1140 ran the stage trace seed on watch-it-burn-private and wrote its record in decisions.md, in the entry
"## 2026-11-08 · #1140 · run 18722". Its paragraph "**The traces Whitney can open now.**" must:
  1. name each attack trace the slides open, by seed key in backticks, with the stamp of the run that holds them;
  2. say Whitney opening each of them from its slide's link and confirming it shows what the slide says is owed live;
  3. name every seed that has no `/kubecon` beat, in backticks, after "The seed with no `/kubecon` beat is".
PROGRESS.md's #1140 bullet must say the same check is owed live.

The attack traces and the off-page seeds are read from verify/stage_traces.py (its SEEDS and OFF_PAGE_SEEDS), not
copied here, so a seed added to either without the record naming it fails this test. The record's own count word
("each of the four") is held to the number of attack seeds.

Each cut this test makes on repo text first checks the literal is there and exits naming the literal and the file
when it is not (per "Tests own their inputs"), so a reworded anchor reads as that, not as a broken check further on.
Every check is also run against a copy with the thing it reads struck out, so a check that could never fail shows.
"""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import stage_traces as st  # noqa: E402

DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
PROGRESS = (REPO / "PROGRESS.md").read_text(encoding="utf-8")

DEC_HEAD = "## 2026-11-08 · #1140 · run 18722"
TRACES_LABEL = "**The traces Whitney can open now.**"
STAMP = "`202611081721`"
OWED = "from its slide's link and confirming it shows what the slide says is owed live"
OFF_PAGE_LEAD = "The seed with no `/kubecon` beat is"
PROG_HEAD = "- (2026-11-08) #1140, part of #1130:"
PROG_OWED = "Whitney's check of each from its slide's link is owed live"

COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
ATTACK_SEEDS = tuple(s[0] for s in st.SEEDS if s[0].endswith("-attack"))

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_1140_trace_check_owed.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the record")


def dec_entry(text: str) -> str:
    """The #1140 decisions.md entry, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(DEC_HEAD) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def traces_para(entry: str) -> str:
    """The 'traces Whitney can open now' paragraph of the entry, to the next bold label or EOF; empty when absent."""
    m = re.search(re.escape(TRACES_LABEL) + r"(.*?)(?=\n\n\*\*|\Z)", entry, flags=re.S)
    return m.group(1) if m else ""


def flat(text: str) -> str:
    """The text with its line wrapping undone, so a phrase the record wraps across lines still reads whole."""
    return re.sub(r"\s+", " ", text)


def owed_sentence(para: str) -> str:
    """The sentence of the paragraph that says the check is owed live; empty when absent."""
    for sentence in re.split(r"(?<=[.;])\s+", flat(para)):
        if OWED in sentence:
            return sentence
    return ""


def names_attack_traces(para: str) -> bool:
    return STAMP in para and all(f"`{k}`" in para for k in ATTACK_SEEDS)


def owes_whitney_each(para: str) -> bool:
    s = owed_sentence(para)
    count = COUNT_WORDS.get(len(ATTACK_SEEDS), str(len(ATTACK_SEEDS)))
    return bool(s) and s.startswith("Whitney opening each of the ") and f"each of the {count} " in s


def off_page_named(para: str) -> list[str]:
    """The backticked seed keys named after the off-page lead, up to the end of that sentence."""
    text = flat(para)
    i = text.find(OFF_PAGE_LEAD)
    if i < 0:
        return []
    rest = text[i + len(OFF_PAGE_LEAD):]
    end = re.search(r",\s+whose\b|\.\s", rest)
    named = rest[: end.start()] if end else rest
    return re.findall(r"`(c\d-[a-z]+)`", named)


def names_off_page(para: str) -> bool:
    return sorted(off_page_named(para)) == sorted(st.OFF_PAGE_SEEDS)


def prog_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.startswith(PROG_HEAD)]
    return lines[0] if len(lines) == 1 else ""


# ---- what stage_traces.py says the record must cover ----
print("== the seeds the record is held to, read from verify/stage_traces.py ==")
check("stage_traces.py has attack seeds", bool(ATTACK_SEEDS), str([s[0] for s in st.SEEDS]))
check("stage_traces.py names at least one off-page seed", bool(st.OFF_PAGE_SEEDS), str(st.OFF_PAGE_SEEDS))
print(f"        attack seeds: {list(ATTACK_SEEDS)}; off-page seeds: {list(st.OFF_PAGE_SEEDS)}")

# ---- decisions.md: #1140's entry ----
anchor(DECISIONS, DEC_HEAD, "decisions.md")
entry = dec_entry(DECISIONS)
check("the #1140 decisions.md entry is present", bool(entry), f"no entry starting {DEC_HEAD!r}")
anchor(entry, TRACES_LABEL, "decisions.md #1140 entry")
para = traces_para(entry)
check("the entry has its 'traces Whitney can open now' paragraph", bool(para))
anchor(para, STAMP, "decisions.md #1140 traces paragraph")
anchor(flat(para), OWED, "decisions.md #1140 traces paragraph")
anchor(flat(para), OFF_PAGE_LEAD, "decisions.md #1140 traces paragraph")

print("== it names each attack trace the slides open, with the stamp that holds them ==")
for k in ATTACK_SEEDS:
    check(f"the paragraph names `{k}`", f"`{k}`" in para)
check(f"the paragraph names stamp {STAMP}", STAMP in para)

print("== it says Whitney's check of each, from its slide's link, is owed live ==")
check("the owed sentence says Whitney opens each attack trace from its slide's link and checks it against the slide",
      owes_whitney_each(para), repr(owed_sentence(para)))

print("== it names every seed with no /kubecon beat, and only those ==")
check("the off-page seeds named are stage_traces.OFF_PAGE_SEEDS", names_off_page(para),
      f"named {off_page_named(para)}, stage_traces.py has {list(st.OFF_PAGE_SEEDS)}")

# ---- PROGRESS.md: the #1140 bullet ----
anchor(PROGRESS, PROG_HEAD, "PROGRESS.md")
line = prog_line(PROGRESS)
print("== PROGRESS.md's #1140 bullet says the check is owed live ==")
check("the #1140 PROGRESS.md bullet is found once", bool(line))
check("it says Whitney's check of each from its slide's link is owed live", PROG_OWED in line)

# ---- each check fails when what it reads is struck ----
print("== each check fails when the criterion stops holding ==")
check("with the #1140 heading struck, the entry is not found",
      dec_entry(DECISIONS.replace(DEC_HEAD, "## 2026-11-08 · #0000 · struck", 1)) == "")
check("with the paragraph's label struck, the paragraph is not found",
      traces_para(entry.replace(TRACES_LABEL, "**Struck.**", 1)) == "")
check("the paragraph as written passes the attack-trace check", names_attack_traces(para))
for k in ATTACK_SEEDS:
    anchor(para, f"`{k}`", "decisions.md #1140 traces paragraph")
    check(f"with `{k}` struck, the attack-trace check fails",
          not names_attack_traces(para.replace(f"`{k}`", "`struck`")))
check("with the stamp struck, the attack-trace check fails",
      not names_attack_traces(para.replace(STAMP, "`000000000000`")))
check("with 'owed live' struck, the owed check fails",
      not owes_whitney_each(flat(para).replace("is owed live", "is done")))
check("with Whitney's name struck, the owed check fails",
      not owes_whitney_each(flat(para).replace("Whitney opening each", "Someone opening each")))
wrong = 3 if len(ATTACK_SEEDS) != 3 else 5
check("with the count word not the number of attack seeds, the owed check fails",
      not owes_whitney_each(flat(para).replace(f"each of the {COUNT_WORDS[len(ATTACK_SEEDS)]} ",
                                               f"each of the {COUNT_WORDS[wrong]} ")))
for k in st.OFF_PAGE_SEEDS:
    check(f"with off-page seed `{k}` struck, the off-page check fails",
          not names_off_page(flat(para).replace(f"{OFF_PAGE_LEAD} `{k}`", f"{OFF_PAGE_LEAD} nothing")))
check("with a seed named off the page that stage_traces.py does not list, the off-page check fails",
      not names_off_page(flat(para).replace(OFF_PAGE_LEAD, f"{OFF_PAGE_LEAD} `c1-fixed` and", 1)))
check("with the off-page lead struck, the off-page check fails",
      not names_off_page(flat(para).replace(OFF_PAGE_LEAD, "The seed is", 1)))
check("with the PROGRESS bullet doubled, it is not found once",
      prog_line(PROGRESS.replace(line, line + "\n" + line, 1)) == "")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("All #1140 trace-check-owed checks passed (decisions.md entry and PROGRESS.md bullet).")
