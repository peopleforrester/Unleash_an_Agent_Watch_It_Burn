# ABOUTME: Holds the #1267 note's mapping of the CNCF Code of Conduct's categories to what the term floor catches, what
# ABOUTME: the classifier adds and what neither catches, against results.json, the abuse set and the floor as it runs (#1291).
"""No cluster, no network, standard library and PyYAML (corpus.py's).

#1267 asks for the CNCF Code of Conduct's categories mapped to what the floor catches and what it cannot. That mapping
is the table under "## What the CNCF Code of Conduct rules out" in docs/research/2026-11-09-coc-floor/README.md.
test_coc_floor_spike.py holds the floor's catch counts per abuse-set category and test_coc_floor_note.py the surfaces
table; neither reads this one, so a row dropped, a count that drifted from the measurement, or a "what neither
catches" example the floor in fact catches passed every test.

This reads the section and fails on:
- a category the code names (quoted in the section's prose) that is no longer quoted, or has no row;
- a row with an empty "The term floor" or "What neither catches" cell;
- a "N of M" count that resolves to no abuse-set category, a category set per cell other than the one held below,
  an M that is not the abuse set's size for that category, or an N that differs from results.json (the term floor
  column from the term-proposed candidate, the classifier column from the chosen pair, "from Bedrock alone" from the
  chosen Bedrock guardrail on its own);
- the floor as it runs (floor.py on terms-proposed.rot13) catching fewer texts of a category than the term floor
  column states, or missing a phrase that column quotes as caught;
- a phrase the "What neither catches" column quotes that is no abuse-set text, or that the floor as it runs flags.
The classifier's misses are read from results.json's counts only: the spike kept no per-text Bedrock verdicts.

It then writes each fault into the note, and two into the floor (the 40-term list, and a list that gains a term the
note says nothing catches), and fails when a check stops seeing its fault.
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
NOTE_PATH = SPIKE / "README.md"
RESULTS_PATH = SPIKE / "results.json"
sys.path.insert(0, str(SPIKE))

import corpus  # noqa: E402
import floor  # noqa: E402

HEADING = "What the CNCF Code of Conduct rules out"
COLUMNS = ("Category the code names", "The term floor", "With the classifier", "What neither catches")
# The candidates of results.json each column's counts come from: the README's choice is the term floor with Bedrock
# Guardrails Standard, HATE, INSULTS and SEXUAL at MEDIUM and VIOLENCE at LOW.
FLOOR_CANDIDATE = "term-proposed"
COMBINED_CANDIDATE = "term-proposed+bedrock-standard-coc-medium+violence-low"
BEDROCK_ALONE_CANDIDATE = "bedrock-standard-coc-medium+violence-low"

# Each row: the pattern its first cell matches, the abuse-set category an unlabelled count in it means, and the
# categories its term floor and classifier cells must give counts for (empty: the row carries no count there).
ROWS = {
    "Sexualized language": (r"^sexualized language", "sexual", {"sexual"}, {"sexual"}),
    "Insulting or derogatory comments": (r"^insulting or derogatory", None, {"expletive", "slur"}, {"slur", "insult"}),
    "Personal or political attacks; harassment": (r"personal or political attacks", None, set(), {"insult"}),
    "Hate speech": (r"^hate speech", "hate", {"hate"}, {"hate"}),
    "Violence, threatening violence": (r"^violence", "threat", {"threat"}, {"threat"}),
    "Private information": (r"^private information", None, set(), set()),
    "Political campaigning": (r"^political campaigning", None, set(), set()),
    "Other languages": (r"^other languages", "foreign", {"foreign"}, {"foreign"}),
}
# What the codes name, quoted in the section's prose, and the row each maps to. The first five are the CNCF code's,
# the last the Linux Foundation events code's, which "derogatory comments" and it together make the slur and hate row.
CODE_QUOTES = {
    "The use of sexualized language or imagery": ["Sexualized language"],
    "Trolling, insulting or derogatory comments, and personal or political attacks": [
        "Insulting or derogatory comments", "Personal or political attacks; harassment", "Political campaigning"],
    "Public or private harassment in any form": ["Personal or political attacks; harassment"],
    "Publishing others' private information, such as a physical or email address, without their explicit permission":
        ["Private information"],
    "Violence, threatening violence, or encouraging others to engage in violent behavior":
        ["Violence, threatening violence"],
    "Harassment includes the use of abusive, offensive or degrading language": ["Hate speech"],
}
# The word next to a count that names its category.
LABELS = {"sexual": "sexual", "expletive": "expletive", "slurs": "slur", "slur": "slur", "insults": "insult",
          "insult": "insult", "hate": "hate", "threats": "threat", "foreign": "foreign"}
COUNT = re.compile(r"(?:(\w+) )?(\d+) of (\d+)(?: (\w+))?")
QUOTED = re.compile(r'"([^"]+)"')
BEDROCK_ALONE = "from Bedrock alone"


def section(text: str, heading: str) -> str | None:
    match = re.search(r"^## " + re.escape(heading) + r"\s*$", text, re.M)
    if not match:
        return None
    rest = text[match.end():]
    end = re.search(r"^## ", rest, re.M)
    return rest[: end.start()] if end else rest


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def counts(cell: str, default: str | None) -> list[tuple[str | None, int, int, bool]]:
    """(category, n, m, from Bedrock alone) for each "N of M" in a cell; category None when nothing names it."""
    out = []
    for part in cell.split(";"):
        for m in COUNT.finditer(part):
            before, n, total, after = m.groups()
            category = LABELS.get((before or "").lower()) or LABELS.get((after or "").lower()) or default
            out.append((category, int(n), int(total), BEDROCK_ALONE in part[m.start():]))
    return out


def problems(text: str, results: dict, fl: floor.Floor, abuse: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    body = section(text, HEADING)
    if body is None:
        return [f"the note has no '## {HEADING}' section"]

    prose = " ".join(line for line in body.splitlines() if not line.startswith("|"))
    prose = re.sub(r"\s+", " ", prose)
    for quote in CODE_QUOTES:
        if f'"{quote}' not in prose:
            found.append(f"the section no longer quotes the code's {quote[:60]!r}")

    rows = [cells(line) for line in body.splitlines() if line.startswith("|")]
    if not rows or tuple(rows[0][: len(COLUMNS)]) != COLUMNS:
        found.append(f"the mapping table's header is not {' | '.join(COLUMNS)} (found {rows[0] if rows else None})")
        return found
    data = [r + [""] * (len(COLUMNS) - len(r)) for r in rows[2:] if r and r[0]]

    by_row: dict[str, list[str]] = {}
    for name, (pattern, *_rest) in ROWS.items():
        matched = [r for r in data if re.search(pattern, r[0], re.I)]
        if len(matched) != 1:
            found.append(f"row '{name}': {len(matched)} rows in the mapping table, want 1")
            continue
        by_row[name] = matched[0]
    for quote, names in CODE_QUOTES.items():
        for name in names:
            if name not in by_row:
                found.append(f"the code's {quote[:40]!r} maps to row '{name}', which the table no longer has")

    size = collections.Counter(c for c, _ in abuse)
    caught_now = collections.Counter(c for c, t in abuse if fl.spans(t))
    measured = {
        "floor": results["candidates"][FLOOR_CANDIDATE]["abuse_by_category"],
        "combined": results["candidates"][COMBINED_CANDIDATE]["abuse_by_category"],
        "alone": results["candidates"][BEDROCK_ALONE_CANDIDATE]["abuse_by_category"],
    }

    for name, row in by_row.items():
        _pattern, default, floor_cats, classifier_cats = ROWS[name]
        for column, cell in ((COLUMNS[1], row[1]), (COLUMNS[3], row[3])):
            if len(cell.split()) < 3:
                found.append(f"row '{name}': its '{column}' cell is empty or a stub ({cell!r})")

        for column, cell, want, source in ((COLUMNS[1], row[1], floor_cats, "floor"),
                                          (COLUMNS[2], row[2], classifier_cats, "combined")):
            stated = counts(cell, default)
            for category, n, total, alone in stated:
                if category is None:
                    found.append(f"row '{name}': '{n} of {total}' in its '{column}' cell names no abuse-set category")
                    continue
                if total != size[category]:
                    found.append(f"row '{name}': '{n} of {total}' {category} texts, but the abuse set holds "
                                 f"{size[category]}")
                key = "alone" if alone else source
                if f"{n}/{total}" != measured[key][category]:
                    found.append(f"row '{name}': its '{column}' cell states {n} of {total} {category} texts, "
                                 f"results.json's {key} measurement is {measured[key][category]}")
                if source == "floor" and caught_now[category] < n:
                    found.append(f"row '{name}': the note says the term floor catches {n} {category} texts, the "
                                 f"floor as it runs catches {caught_now[category]}")
            got = {c for c, *_ in stated if c is not None}
            if got != want:
                found.append(f"row '{name}': its '{column}' cell gives counts for {sorted(got)}, want {sorted(want)}")

        if floor_cats:
            for phrase in QUOTED.findall(row[1]):
                if not fl.spans(phrase):
                    found.append(f"row '{name}': the term floor column quotes {phrase!r} as caught, the floor as it "
                                 f"runs does not flag it")
        for phrase in QUOTED.findall(row[3]):
            texts = [t for _, t in abuse if phrase.lower() in t.lower()]
            if not texts:
                found.append(f"row '{name}': 'What neither catches' quotes {phrase!r}, which is in no abuse-set text, "
                             f"so nothing measured it")
            for t in texts:
                if fl.spans(t):
                    found.append(f"row '{name}': 'What neither catches' quotes {phrase!r}, but the floor as it runs "
                                 f"flags {fl.hits(t)} in it")
    return found


def replace_once(text: str, old: str, new: str) -> str:
    """The mutation's anchor must be in the note, so a reworded note reads as that and not as a broken check."""
    if text.count(old) != 1:
        print(f"FAIL anchor {old[:70]!r} appears {text.count(old)} times in {NOTE_PATH.relative_to(REPO)}, want 1")
        sys.exit(1)
    return text.replace(old, new)


def drop_line(text: str, starts: str) -> str:
    lines = [line for line in text.splitlines(keepends=True) if line.startswith(starts)]
    if len(lines) != 1:
        print(f"FAIL anchor line {starts!r} appears {len(lines)} times in {NOTE_PATH.relative_to(REPO)}, want 1")
        sys.exit(1)
    return text.replace(lines[0], "")


def main() -> int:
    note = NOTE_PATH.read_text(encoding="utf-8")
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    abuse = corpus.abuse_set()
    fl = floor.Floor("proposed")
    failures = 0

    print("== the mapping as it stands ==")
    real = problems(note, results, fl, abuse)
    for problem in real:
        print("FAIL " + problem)
    if not real:
        print(f"PASS every category the code names ({len(CODE_QUOTES)} quotes) maps to one of {len(ROWS)} rows")
        print("PASS every count agrees with results.json and the floor as it runs catches at least what the note states")
        print("PASS every 'What neither catches' example is an abuse-set text the floor as it runs does not flag")
    failures += len(real)

    print("== each fault, written into the note or the floor, is caught ==")
    note_faults = {
        "the violence row removed": (drop_line(note, "| Violence, threatening violence |"),
                                     "row 'Violence, threatening violence': 0 rows"),
        "the hate row's 'What neither catches' emptied": (
            replace_once(note, "| coded language and dog whistles the model has not learned |", "| |"),
            "row 'Hate speech': its 'What neither catches' cell is empty"),
        "the code's violence category no longer quoted": (
            replace_once(note, '"Violence, threatening violence, or encouraging', '"Threats, or encouraging'),
            "no longer quotes the code's 'Violence, threatening violence"),
        "a term floor count raised past the measurement": (
            replace_once(note, "| 4 of 15: fixed phrases", "| 5 of 15: fixed phrases"),
            "states 5 of 15 threat texts, results.json's floor measurement is 4/15"),
        "a classifier count raised past the measurement": (
            replace_once(note, "| 14 of 15 |", "| 15 of 15 |"),
            "states 15 of 15 threat texts, results.json's combined measurement is 14/15"),
        "the Bedrock-alone count changed": (
            replace_once(note, "11 of 20 from Bedrock alone", "12 of 20 from Bedrock alone"),
            "results.json's alone measurement is 11/20"),
        "a count's category label dropped": (
            replace_once(note, "texts; slurs 19 of 20 |", "texts; 19 of 20 |"),
            "'19 of 20' in its 'The term floor' cell names no abuse-set category"),
        "a count's total wrong": (
            replace_once(note, "| 20 of 20 sexual texts", "| 20 of 25 sexual texts"),
            "'20 of 25' sexual texts, but the abuse set holds 20"),
        "a classifier count dropped from its row": (
            replace_once(note, "| slurs 20 of 20; insults 13 of 15 |", "| slurs 20 of 20 |"),
            "gives counts for ['slur'], want ['insult', 'slur']"),
        "a 'neither' example the floor catches": (
            replace_once(note, '("I know where you live")', '("kill yourself")'),
            "quotes 'kill yourself', but the floor as it runs flags"),
        "a 'neither' example nobody measured": (
            replace_once(note, '"imbecile machine"', '"dimwit robot"'),
            "quotes 'dimwit robot', which is in no abuse-set text"),
        "a 'caught' phrase the floor misses": (
            replace_once(note, '("kill yourself", "kys")', '("kill yourself", "I will kill you")'),
            "quotes 'I will kill you' as caught, the floor as it runs does not flag it"),
    }
    shorter = floor.Floor("current")
    widened = floor.Floor("proposed")
    widened.pattern = floor.proposed_pattern(corpus.terms("proposed") + ["imbecile"])
    floor_faults = {
        "the floor shrunk to the 40-term list": (shorter, "the floor as it runs catches 4"),
        "the floor now catches a 'neither' example": (widened, "quotes 'imbecile machine', but the floor as it runs"),
    }
    cases = [(what, mutated, fl, expect) for what, (mutated, expect) in note_faults.items()]
    cases += [(what, note, other, expect) for what, (other, expect) in floor_faults.items()]
    for what, text, use, expect in cases:
        got = problems(text, results, use, abuse)
        hit = [p for p in got if expect in p]
        print(("PASS " if hit else "FAIL ") + f"{what}: " + (hit[0] if hit else f"not caught (got {got})"))
        failures += 0 if hit else 1

    print(f"{failures} failure(s)" if failures else "ALL CHECKS PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
