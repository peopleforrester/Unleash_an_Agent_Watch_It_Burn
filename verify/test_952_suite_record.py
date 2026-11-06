# ABOUTME: Pins #952's suite criterion (#975): its decisions.md entry records run-e2e-tools.sh finishing green, the
# ABOUTME: offline suite and the tools tier both, with the iPad prompt-sheet test named and recorded as passing.
"""Holds the criterion of #952 that test review run 17827 found no test checked (#975).

#952's criterion: `bash verify/run-tests.sh` and `bash verify/run-e2e-tools.sh` finish green (the prompt-sheet test
passing), with the result recorded in decisions.md. The suites ran once, in run 17818; what stays checkable is the
record, read here as literal text. The "## 2026-11-06 · #952 · run 17805" entry must carry exactly one bold
"**The suites ...**" paragraph, and that paragraph must record:

  1. the command, `bash verify/run-e2e-tools.sh`, which runs run-tests.sh first;
  2. the offline suite green: an `N tests ran` count (N > 0) and `ALL OFFLINE RENDER-GATE TESTS GREEN`;
  3. the tools tier green: an `N checks ran (the offline suite and M tier tests) in XmYYs` line, with N = M + 1 as
     run-e2e-tools.sh counts it and M > 0, then `ALL E2E TOOLS TIER CHECKS GREEN` and `exit=0`;
  4. `verify/test_kubecon_prompt_sheet_e2e.py` named as passed, quoting the line that test prints on a pass;
  5. no failure marker (`SOME TESTS FAILED`, `SOME E2E TOOLS TIER CHECKS FAILED`, `FAILED:` or a non-zero `exit=`).

The record only means what it says while the scripts print those words, so the test also checks run-tests.sh and
run-e2e-tools.sh still print the green lines and counts it reads, that the prompt-sheet test is in the tools tier
(`# E2E TIER: tools`, so a green tier ran it), and that it still prints the pass line the record quotes.

Each cut on repo text first checks the literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a mutated copy of the real record with the thing it reads
struck or flipped, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
RUN_TESTS = (REPO / "verify" / "run-tests.sh").read_text(encoding="utf-8")
RUN_TOOLS = (REPO / "verify" / "run-e2e-tools.sh").read_text(encoding="utf-8")
SHEET_PATH = REPO / "verify" / "test_kubecon_prompt_sheet_e2e.py"
SHEET_TEST = SHEET_PATH.read_text(encoding="utf-8")

HEAD_952 = "## 2026-11-06 · #952 · run 17805"
SUITES_LABEL = "**The suites"
COMMAND = "`bash verify/run-e2e-tools.sh`"
OFFLINE_GREEN = "ALL OFFLINE RENDER-GATE TESTS GREEN"
TIER_GREEN = "ALL E2E TOOLS TIER CHECKS GREEN"
SHEET_NAME = "verify/test_kubecon_prompt_sheet_e2e.py"
SHEET_PASS = "The iPad prompt sheet carries every /kubecon prompt, in order."
TESTS_RAN = re.compile(r"`(\d+) tests ran`")
CHECKS_RAN = re.compile(r"`(\d+) checks ran \(the offline suite and (\d+) tier tests\) in (\d+)m(\d\d)s`")
EXIT = re.compile(r"`exit=(\d+)`")
SHEET_PASSED = re.compile(re.escape(f"`{SHEET_NAME}` passed") + ': "' + re.escape(SHEET_PASS) + '"')
FAIL_MARKERS = ("SOME TESTS FAILED", "SOME E2E TOOLS TIER CHECKS FAILED", "FAILED:")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_952_suite_record.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def dec_entry(text: str, head: str) -> str:
    """The decisions.md entry starting `head`, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(head) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def suites_paragraphs(entry: str) -> list[str]:
    """Every paragraph of `entry` that opens with the bold suites label."""
    return [p for p in re.split(r"\n\s*\n", entry) if p.lstrip().startswith(SUITES_LABEL)]


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so a quote wrapped across lines reads as one line."""
    return " ".join(text.split())


def verdict(decisions: str) -> tuple[bool, str]:
    """Whether #952's suite record shows both suites green with the prompt-sheet test passing, and why not."""
    entry = dec_entry(decisions, HEAD_952)
    if not entry:
        return False, f"no decisions.md entry starting {HEAD_952!r}"
    paras = suites_paragraphs(entry)
    if len(paras) != 1:
        return False, f"the #952 entry has {len(paras)} paragraphs opening {SUITES_LABEL!r}; it needs exactly one"
    para = flat(paras[0])
    if COMMAND not in para:
        return False, f"the suites paragraph does not name the command {COMMAND}"
    for marker in FAIL_MARKERS:
        if marker in para:
            return False, f"the suites paragraph carries the failure marker {marker!r}"
    m = TESTS_RAN.search(para)
    if not m or int(m.group(1)) == 0:
        return False, "the offline suite's `N tests ran` count (N > 0) is not recorded"
    if f"`{OFFLINE_GREEN}`" not in para:
        return False, f"the offline suite's {OFFLINE_GREEN!r} is not recorded"
    if para.index(m.group(0)) > para.index(f"`{OFFLINE_GREEN}`"):
        return False, "the offline green line is recorded before its `tests ran` count, not as the script prints it"
    c = CHECKS_RAN.search(para)
    if not c:
        return False, "the tier's `N checks ran (the offline suite and M tier tests) in XmYYs` line is not recorded"
    checks, tier = int(c.group(1)), int(c.group(2))
    if tier == 0 or checks != tier + 1:
        return False, (f"the tier line records {checks} checks and {tier} tier tests; run-e2e-tools.sh counts "
                       f"the offline suite as one check, so it needs M > 0 and N = M + 1")
    if int(c.group(4)) > 59:
        return False, f"the tier line's duration {c.group(3)}m{c.group(4)}s is not a time the script prints"
    if f"`{TIER_GREEN}`" not in para:
        return False, f"the tools tier's {TIER_GREEN!r} is not recorded"
    exits = EXIT.findall(para)
    if not exits:
        return False, "the run's `exit=0` is not recorded"
    if any(e != "0" for e in exits):
        return False, f"the suites paragraph records a non-zero exit: {', '.join('exit=' + e for e in exits)}"
    if not SHEET_PASSED.search(para):
        return False, (f"the suites paragraph does not record `{SHEET_NAME}` as passed, quoting its pass line "
                       f"{SHEET_PASS!r}")
    return True, (f"{m.group(1)} tests ran green offline, then {checks} checks ({tier} tier tests) green in "
                  f"{c.group(3)}m{c.group(4)}s, exit=0, the prompt-sheet test among them")


# ---- what the record's words mean: the scripts still print them ----
print("== the scripts still print the lines the record quotes ==")
check("run-tests.sh prints its `tests ran` count", "%d tests ran" in RUN_TESTS)
check(f"run-tests.sh prints {OFFLINE_GREEN!r}", OFFLINE_GREEN in RUN_TESTS)
check("run-e2e-tools.sh runs run-tests.sh first", re.search(r"^[^#\n]*run-tests\.sh", RUN_TOOLS, re.M) is not None)
check("run-e2e-tools.sh prints its `checks ran` line with the duration",
      "%d checks ran (the offline suite and %d tier tests) in %dm%02ds" in RUN_TOOLS)
check(f"run-e2e-tools.sh prints {TIER_GREEN!r}", TIER_GREEN in RUN_TOOLS)
check(f"{SHEET_NAME} is in the tools tier, so a green tier ran it",
      re.search(r"^# E2E TIER: tools", SHEET_TEST, re.M) is not None)
check(f"{SHEET_NAME} still prints the pass line the record quotes", f'print("{SHEET_PASS}")' in SHEET_TEST)

# ---- the record as it stands ----
anchor(DECISIONS, HEAD_952, "decisions.md")
ENTRY = dec_entry(DECISIONS, HEAD_952)
anchor(ENTRY, SUITES_LABEL, "decisions.md #952 entry")
PARA = suites_paragraphs(ENTRY)[0]
FLAT = flat(PARA)
for lit in (COMMAND, "`284 tests ran`", f"`{OFFLINE_GREEN}`", "`65 checks ran", "64 tier tests", "51m34s`",
            f"`{TIER_GREEN}`", "`exit=0`", f"`{SHEET_NAME}` passed", SHEET_PASS):
    anchor(FLAT, lit, "decisions.md #952 suites paragraph")

print("== #952's decisions.md entry records both suites green, the prompt-sheet test passing ==")
ok, why = verdict(DECISIONS)
check("the suite record is there and reads green", ok, why)
print(f"        {why}")


def cut(old: str, new: str) -> str:
    """decisions.md with `old` replaced by `new` once inside the #952 suites paragraph only."""
    anchor(FLAT, old, "decisions.md #952 suites paragraph")
    return DECISIONS.replace(PARA, FLAT.replace(old, new, 1), 1)


def refused(name: str, decisions: str) -> None:
    ok_, why_ = verdict(decisions)
    check(name, not ok_, f"the verdict still held: {why_}")


print("== each cut of the real record is refused ==")
anchor(DECISIONS, HEAD_952, "decisions.md")
refused("with the #952 heading struck, the entry is not found",
        DECISIONS.replace(HEAD_952, "## 2026-11-06 · #000 · struck", 1))
refused("with the suites paragraph removed, nothing is recorded", DECISIONS.replace(PARA, "", 1))
refused("with the suites paragraph doubled, the record is ambiguous",
        DECISIONS.replace(PARA, PARA + "\n\n" + PARA, 1))
refused("with the command not named, it is refused", cut(COMMAND, "the suite"))
refused("with the `tests ran` count struck, it is refused", cut("`284 tests ran`", "the tests"))
refused("with zero tests ran, it is refused", cut("`284 tests ran`", "`0 tests ran`"))
refused("with the offline green line struck, it is refused", cut(f"`{OFFLINE_GREEN}`", "`SOME TESTS FAILED`"))
refused("with the offline green line only unquoted, it is refused", cut(f"`{OFFLINE_GREEN}`", "the offline suite"))
refused("with the `checks ran` line struck, it is refused",
        cut("`65 checks ran (the offline suite and 64 tier tests) in 51m34s`", "the tier"))
refused("with the duration struck, it is refused", cut(" in 51m34s`", "`"))
refused("with the checks count not the tier count plus one, it is refused", cut("`65 checks ran", "`64 checks ran"))
refused("with the tier green line struck, it is refused", cut(f"`{TIER_GREEN}`", "the tier ended"))
refused("with the tier's failure line in its place, it is refused",
        cut(f"`{TIER_GREEN}`", "`SOME E2E TOOLS TIER CHECKS FAILED`"))
refused("with `exit=0` struck, it is refused", cut("`exit=0`", "the exit"))
refused("with `exit=1` in its place, it is refused", cut("`exit=0`", "`exit=1`"))
refused("with the prompt-sheet test not named, it is refused", cut(f"`{SHEET_NAME}` passed", "the sheet test passed"))
refused("with the prompt-sheet test failing, it is refused", cut(f"`{SHEET_NAME}` passed", f"`{SHEET_NAME}` failed"))
refused("with the prompt-sheet pass line struck, it is refused", cut(SHEET_PASS, "it ran"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#952's suite record holds: both suites green, the prompt-sheet test passing.")
