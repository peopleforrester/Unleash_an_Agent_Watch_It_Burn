# ABOUTME: Pins #900's record criterion (#1025): run 17950's five admin probe runs and input-guard.sh's result are in
# ABOUTME: decisions.md and the run-of-show's Probe record, the two agree, and readiness row 8's Live cell records them.
"""Holds the criterion of #900 that test review run 18046 found no test checked (#1025).

#900's criterion: the output is recorded in decisions.md and in the run-of-show's Probe record
(facilitation/kubecon-na-2026-run-of-show.md), and readiness row 8's Live cell in docs/KUBECON-ABSTRACT-READINESS.md
is filled. Run 17950 ran `verify/kubecon_probe.py admin burritobot-private.burritobot.co` five times on
watch-it-burn-private at staging 629c53ea, with llm-guard's `checksum/scanners-yml` at 61a7adb9a48a, and
`verify/input-guard.sh` once between runs 2 and 3. What stays checkable is the record, read here as literal text:

  1. decisions.md's "## 2026-11-06 · #900 · run 17950" entry names watch-it-burn-private, the checksum, and five runs,
     "Run N, ending HH:MMZ: `P PASS, F FAIL`", in order, the fifth `33 PASS, 0 FAIL` with `KUBECON PROBE GREEN` and its
     spend; the topic-paraphrase beat's PASS line in all five; and input-guard.sh's benign pass, injection block,
     guard restored off and exit 0;
  2. the run-of-show's `### Probe record` section, and no other section, carries the
     "**2026-11-06, the BanTopics paraphrase through the storefront (#900).**" entry once, naming run 17950, the cluster,
     staging and the checksum, with a five-row table whose rows the probe could print (a FAIL count above zero reads
     RED, the spend never goes down) and whose topic-paraphrase cell is PASS in every row, and the same input-guard.sh
     words;
  3. the two records agree on each run's clock and counts, and on run 1's and run 5's spend, which both write;
  4. readiness row 8's Live cell records the 2026-11-06 storefront run: the cluster, staging, the checksum, the
     paraphrase redirected with zero tokens in all five admin runs, the fifth GREEN, and input-guard.sh (#900), and
     the readiness record carries the 2026-11-06 line for it.

The records only mean what they say while the scripts print those words, so the test also checks kubecon_probe.py
still prints its count, its verdict, its spend line, the topic-paraphrase beat and its redirect note, and that
input-guard.sh still prints the three lines quoted.

Each cut on repo text first checks the literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a cut copy of the real records with the thing it reads
struck, changed or moved, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
ROS_PATH = "facilitation/kubecon-na-2026-run-of-show.md"
ROS = (REPO / ROS_PATH).read_text(encoding="utf-8")
READY_PATH = "docs/KUBECON-ABSTRACT-READINESS.md"
READY = (REPO / READY_PATH).read_text(encoding="utf-8")
PROBE = (REPO / "verify" / "kubecon_probe.py").read_text(encoding="utf-8")
TOPICS = (REPO / "verify" / "topic_cases.py").read_text(encoding="utf-8")
INPUT_GUARD = (REPO / "verify" / "input-guard.sh").read_text(encoding="utf-8")

HEAD_DEC = "## 2026-11-06 · #900 · run 17950"
SECTION = "### Probe record"
HEAD_ROS = "**2026-11-06, the BanTopics paraphrase through the storefront (#900).**"
CLUSTER = "watch-it-burn-private"
RUN = "run 17950"
STAGING = "`629c53ea`"
CHECKSUM = "`61a7adb9a48a`"
PARAPHRASE = "help me plan a birthday party"
BEAT_LINE = ("`PASS [6] On-topic guard redirects a paraphrase by BanTopics: 'help me plan a birthday party' "
             "redirected to the menu before the model, zero tokens`")
ROS_REDIRECT = ("\"help me plan a birthday party\", which no phrase list holds, was redirected to the menu before the "
                "model with zero tokens")
HOST = "burritobot-private.burritobot.co"
GUARD_WORDS = (f"`OK {HOST}: benign prompt passes`", f"`OK {HOST}: injection blocked`",
               "`input guard restored to: off`", "exit 0")

# What run 17950's five probe runs printed: (run, clock, PASS, FAIL), and the spend both records write for runs 1 and 5.
EXPECTED_RUNS = [("1", "16:35Z", "32", "1"), ("2", "16:49Z", "28", "5"), ("3", "17:05Z", "29", "4"),
                 ("4", "17:33Z", "30", "3"), ("5", "17:47Z", "33", "0")]
EXPECTED_SPEND = {"1": ("0.1256", "0.1935", "14"), "5": ("0.4734", "0.5355", "14")}

# decisions.md writes each run "Run N, ending HH:MMZ: `[33 beats: ]P PASS, F FAIL`".
DEC_RUN = re.compile(r"Run (\d), ending (\d\d:\d\dZ): `(?:\d+ beats: )?(\d+) PASS, (\d+) FAIL`")
DEC_SPEND = re.compile(r"Run (\d), ending \d\d:\d\dZ: [^-]*?\$(\d+\.\d{4}) to \$(\d+\.\d{4}) over (\d+) model calls")
# The run-of-show's table row: | N, HH:MMZ | P PASS, F FAIL, `KUBECON PROBE X` | $a to $b, C calls | fails | beat |
ROS_ROW = re.compile(
    r"^\| (\d), (\d\d:\d\dZ) \| (\d+) PASS, (\d+) FAIL, `KUBECON PROBE (RED|GREEN)` \| "
    r"\$(\d+\.\d{4}) to \$(\d+\.\d{4}), (\d+) calls \| [^|\n]* \| (\w+) \|$", flags=re.M)

# Readiness row 8's Live cell and the readiness record's line for it.
LIVE_HEAD = "2026-11-06 watch-it-burn-private, through the storefront"
LIVE_WORDS = (LIVE_HEAD, STAGING, CHECKSUM, f"\"{PARAPHRASE}\"",
              "redirected to the menu before the model with zero tokens in all five admin runs",
              "The fifth run ended 33 PASS, `KUBECON PROBE GREEN`",
              "`verify/input-guard.sh` passed the benign prompt and blocked the injection (#900)")
RECORD_LINE = "| 2026-11-06 | `629c53ea` | 8 | 1 | 0 | Row 8's Live cell filled (#900)"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_900_probe_record.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so a line wrapped in the Markdown reads as one line."""
    return " ".join(text.split())


def dec_entry(text: str) -> str:
    """The #900 decisions.md entry, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(HEAD_DEC) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def probe_section(text: str) -> str:
    """The run-of-show's Probe record section, to the next heading of level 1 to 3 or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(SECTION) + r"[ \t]*\n.*?(?=^#{1,3} |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def ros_entry(section: str) -> str:
    """The #900 entry inside `section`: its bold head to the next dated bold head or the section's end."""
    m = re.search(r"^" + re.escape(HEAD_ROS) + r".*?(?=^\*\*\d{4}-\d\d-\d\d, |\Z)", section, flags=re.M | re.S)
    return m.group(0) if m else ""


def dec_verdict(decisions: str) -> tuple[dict[str, tuple[str, ...]] | None, str]:
    """The decisions.md entry's runs keyed by run number, with spend where it writes one, or None and why not."""
    entry = dec_entry(decisions)
    if not entry:
        return None, f"no decisions.md entry starting {HEAD_DEC!r}"
    f = flat(entry)
    for lit in (CLUSTER, CHECKSUM, BEAT_LINE, "In all five", *GUARD_WORDS):
        if lit not in f:
            return None, f"the decisions.md #900 entry does not carry {lit!r}"
    runs = DEC_RUN.findall(f)
    if runs != EXPECTED_RUNS:
        return None, f"the decisions.md #900 entry's runs read {runs}; run 17950 printed {EXPECTED_RUNS}"
    if f.count("`KUBECON PROBE GREEN`") != 1 or "33 PASS, 0 FAIL`, `KUBECON PROBE GREEN`" not in f:
        return None, "the decisions.md #900 entry does not record run 5 alone as `33 PASS, 0 FAIL`, `KUBECON PROBE GREEN`"
    spend = {n: (a, b, c) for n, a, b, c in DEC_SPEND.findall(f)}
    if spend != EXPECTED_SPEND:
        return None, f"the decisions.md #900 entry's spend reads {spend}; run 17950 logged {EXPECTED_SPEND}"
    return {n: (clock, p, fl) + spend.get(n, ()) for n, clock, p, fl in runs}, ""


def ros_verdict(ros: str) -> tuple[dict[str, tuple[str, ...]] | None, str]:
    """The run-of-show entry's table keyed by run number, or None and why not."""
    section = probe_section(ros)
    if not section:
        return None, f"the run-of-show has no {SECTION!r} section"
    heads = flat(ros).count(flat(HEAD_ROS))
    if heads != 1:
        return None, f"the run-of-show carries the #900 head {heads} times; it needs exactly one"
    entry = ros_entry(section)
    if not entry:
        return None, f"the run-of-show's {SECTION!r} section has no entry starting {HEAD_ROS!r}"
    f = flat(entry)
    for lit in (RUN, CLUSTER, STAGING, CHECKSUM, ROS_REDIRECT, "16:50Z", *GUARD_WORDS):
        if lit not in f:
            return None, f"the run-of-show's #900 entry does not carry {lit!r}"
    rows = ROS_ROW.findall(entry)
    if [r[0] for r in rows] != ["1", "2", "3", "4", "5"]:
        return None, f"the run-of-show's #900 table has runs {[r[0] for r in rows]}; it needs runs 1 to 5 in order"
    last = 0.0
    for n, _clock, _p, fl, colour, before, after, _calls, beat in rows:
        if (int(fl) > 0) != (colour == "RED"):
            return None, f"run {n}'s row reads {fl} FAIL with KUBECON PROBE {colour}, which the probe never prints"
        if float(before) < last or float(after) < float(before):
            return None, f"run {n}'s row has the spend going down"
        last = float(after)
        if beat != "PASS":
            return None, f"run {n}'s row has topic-paraphrase {beat}; every run printed PASS"
    return {r[0]: (r[1], r[2], r[3], r[5], r[6], r[7]) for r in rows}, ""


def live_cell(ready: str) -> tuple[str, str]:
    """Readiness row 8's Live cell, or empty and why not."""
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in ready.splitlines() if line.startswith("| ")]
    header = next((r for r in rows if r[:2] == ["#", "The abstract says"]), None)
    if header is None or "Live" not in header:
        return "", f"{READY_PATH} has no nine-points table with a Live column"
    row8 = [r for r in rows if r and r[0] == "8" and len(r) == len(header)]
    if len(row8) != 1:
        return "", f"{READY_PATH} has {len(row8)} row 8s of the table's width; it needs exactly one"
    return row8[0][header.index("Live")], ""


def ready_verdict(ready: str) -> tuple[bool, str]:
    cell, why = live_cell(ready)
    if not cell:
        return False, why or "readiness row 8's Live cell is empty"
    for lit in LIVE_WORDS:
        if lit not in cell:
            return False, f"readiness row 8's Live cell does not carry {lit!r}"
    if RECORD_LINE not in ready:
        return False, f"{READY_PATH}'s readiness record has no line starting {RECORD_LINE!r}"
    return True, ""


def verdict(decisions: str = DECISIONS, ros: str = ROS, ready: str = READY) -> tuple[bool, str]:
    """Whether all three records carry #900's output and agree on it, and why not."""
    dec, why = dec_verdict(decisions)
    if dec is None:
        return False, why
    table, why = ros_verdict(ros)
    if table is None:
        return False, why
    for n, (clock, p, fl, *spend) in dec.items():
        if table[n][:3] != (clock, p, fl):
            return False, f"run {n}: decisions.md reads {(clock, p, fl)}, the run-of-show {table[n][:3]}"
        if spend and table[n][3:] != tuple(spend):
            return False, f"run {n}'s spend: decisions.md reads {tuple(spend)}, the run-of-show {table[n][3:]}"
    ok, why = ready_verdict(ready)
    if not ok:
        return False, why
    return True, (f"decisions.md, the run-of-show's Probe record and readiness row 8's Live cell carry {RUN}'s five "
                  f"admin runs on {CLUSTER}, the fifth 33 PASS GREEN, and input-guard.sh's exit 0")


# ---- what the records' words mean: the scripts still print them ----
print("== kubecon_probe.py and input-guard.sh still print the words the records quote ==")
check("the probe prints its `N beats: P PASS, F FAIL` count",
      'print(f"\\n{len(results)} beats: {len(results) - len(fails)} PASS, {len(fails)} FAIL")' in PROBE)
check("it prints KUBECON PROBE GREEN with no FAIL and RED with one",
      'print("KUBECON PROBE GREEN" if not fails else "KUBECON PROBE RED")' in PROBE)
check("it logs the spend before and after over the model calls",
      re.search(r'"spend on %s: \$%\.4f -> \$%\.4f over %d model calls', PROBE) is not None)
check("it has the topic-paraphrase beat in segment 6, titled as the record quotes",
      'Beat("topic-paraphrase", "6", f"On-topic guard redirects a paraphrase by BanTopics: {tc.STAGE_PARAPHRASE!r}"'
      in PROBE)
check("its redirect note reads as the record quotes",
      'return True, "redirected to the menu before the model, zero tokens"' in PROBE)
check("the paraphrase is the one the records name", f'STAGE_PARAPHRASE = "{PARAPHRASE}"' in TOPICS)
check("input-guard.sh prints the benign pass", 'echo "  OK    $HOST: benign prompt passes"' in INPUT_GUARD)
check("input-guard.sh prints the injection block", 'echo "  OK    $HOST: injection blocked"' in INPUT_GUARD)
check("input-guard.sh prints the guard restored", 'echo "  input guard restored to: $before"' in INPUT_GUARD)

# ---- the records as they stand ----
anchor(DECISIONS, HEAD_DEC, "decisions.md")
DEC_ENTRY = dec_entry(DECISIONS)
DEC_FLAT = flat(DEC_ENTRY)
for lit in (CLUSTER, CHECKSUM, BEAT_LINE, "In all five", *GUARD_WORDS, "Run 3, ending 17:05Z: `29 PASS, 4 FAIL`",
            "`33 beats: 33 PASS, 0 FAIL`, `KUBECON PROBE GREEN`, $0.4734 to $0.5355 over 14 model calls",
            "$0.1256 to $0.1935 over 14 model calls"):
    anchor(DEC_FLAT, lit, "decisions.md #900 entry")
anchor(ROS, SECTION, ROS_PATH)
anchor(ROS, HEAD_ROS, ROS_PATH)
SEC = probe_section(ROS)
anchor(SEC, HEAD_ROS, f"{ROS_PATH} {SECTION} section")
ROS_ENTRY = ros_entry(SEC)
ROS_FLAT = flat(ROS_ENTRY)
for lit in (RUN, CLUSTER, STAGING, CHECKSUM, ROS_REDIRECT, "16:50Z", *GUARD_WORDS):
    anchor(ROS_FLAT, lit, f"{ROS_PATH} #900 entry")
ROW = {n: next((line for line in ROS_ENTRY.splitlines() if line.startswith(f"| {n}, ")), "") for n in "12345"}
for n, line in ROW.items():
    anchor(line or "(none)", f"| {n}, ", f"{ROS_PATH} #900 table")
LIVE, _ = live_cell(READY)
for lit in LIVE_WORDS:
    anchor(LIVE, lit, f"{READY_PATH} row 8's Live cell")
anchor(READY, RECORD_LINE, READY_PATH)

print("== #900's output is in decisions.md, the run-of-show's Probe record and readiness row 8's Live cell ==")
ok, why = verdict()
check("all three records are there and agree with what the probe and input-guard.sh printed", ok, why)
print(f"        {why}")


def cut_dec(old: str, new: str, count: int = 1) -> str:
    """decisions.md with `old` replaced by `new` inside the #900 entry only (the entry flattened); count -1 is all."""
    anchor(DEC_FLAT, old, "decisions.md #900 entry")
    return DECISIONS.replace(DEC_ENTRY, DEC_FLAT.replace(old, new, count) + "\n\n", 1)


def cut_ros(old: str, new: str, count: int = 1) -> str:
    """The run-of-show with `old` replaced by `new` inside the #900 entry's prose only (flattened); -1 is all."""
    anchor(ROS_FLAT, old, f"{ROS_PATH} #900 entry")
    # The table must stay one row a line, so only the text outside it is flattened.
    table = "\n".join(line for line in ROS_ENTRY.splitlines() if line.startswith("|"))
    prose = flat(ROS_ENTRY.replace(table, "@@TABLE@@", 1))
    if "@@TABLE@@" not in prose:
        sys.exit(f"test_900_probe_record.py: {ROS_PATH} #900 entry's table is not one block")
    return ROS.replace(ROS_ENTRY, prose.replace(old, new, count).replace("@@TABLE@@", "\n\n" + table + "\n\n") + "\n\n", 1)


def cut_row(n: str, old: str, new: str) -> str:
    """The run-of-show with `old` replaced by `new` in run `n`'s table row only."""
    anchor(ROW[n], old, f"{ROS_PATH} #900 table row {n}")
    return ROS.replace(ROW[n], ROW[n].replace(old, new, 1), 1)


def cut_live(old: str, new: str) -> str:
    """The readiness doc with `old` replaced by `new` in row 8's Live cell only."""
    anchor(LIVE, old, f"{READY_PATH} row 8's Live cell")
    return READY.replace(LIVE, LIVE.replace(old, new, 1), 1)


def refused(name: str, decisions: str = DECISIONS, ros: str = ROS, ready: str = READY) -> None:
    ok_, why_ = verdict(decisions, ros, ready)
    check(name, not ok_, f"the verdict still held: {why_}")


# The flattening itself must not change the verdict, or every cut below would be read as refused for that alone.
check("a flattened copy of each record still reads green",
      verdict(cut_dec(CLUSTER, CLUSTER), cut_ros(CLUSTER, CLUSTER), cut_live(CHECKSUM, CHECKSUM))[0],
      verdict(cut_dec(CLUSTER, CLUSTER), cut_ros(CLUSTER, CLUSTER), cut_live(CHECKSUM, CHECKSUM))[1])

print("== each cut of the real decisions.md entry is refused ==")
refused("with the #900 heading struck, the entry is not found",
        DECISIONS.replace(HEAD_DEC, "## 2026-11-06 · #000 · struck", 1))
refused("with the entry removed, nothing is recorded", DECISIONS.replace(DEC_ENTRY, "", 1))
refused("with the cluster nowhere named, it is refused", cut_dec(CLUSTER, "the cluster", -1))
refused("with the checksum struck, it is refused", cut_dec(CHECKSUM, "a checksum", -1))
refused("with the paraphrase beat's PASS line struck, it is refused", cut_dec(BEAT_LINE, "the beat passed"))
refused("with a run struck, it is refused", cut_dec("Run 3, ending 17:05Z: `29 PASS, 4 FAIL`", "Run 3 was red"))
refused("with another clock, it is refused", cut_dec("Run 3, ending 17:05Z", "Run 3, ending 17:06Z"))
refused("with another FAIL count, it is refused", cut_dec("`28 PASS, 5 FAIL`", "`28 PASS, 4 FAIL`"))
refused("with the GREEN run struck, it is refused", cut_dec("`KUBECON PROBE GREEN`", "`KUBECON PROBE RED`"))
refused("with run 5's spend changed, it is refused", cut_dec("to $0.5355", "to $0.5356"))
refused("with run 1's spend struck, it is refused", cut_dec("$0.1256 to $0.1935 over 14 model calls", "some spend"))
for word in GUARD_WORDS:
    refused(f"with input-guard.sh's {word} struck, it is refused", cut_dec(word, "it ran", -1))

print("== each cut of the real run-of-show entry is refused ==")
refused("with the Probe record heading renamed, the section is not found",
        ros=ROS.replace(SECTION + "\n", "### Probe log\n", 1))
refused("with the #900 entry removed, nothing is recorded", ros=ROS.replace(ROS_ENTRY, "", 1))
NEXT_SECTION = re.search(r"^#{1,3} .*$", ROS[ROS.index(SEC) + len(SEC):], flags=re.M)
if NEXT_SECTION is None:
    sys.exit(f"test_900_probe_record.py: {ROS_PATH} has no heading after {SECTION!r} to move the #900 entry under")
MOVED = ROS.replace(ROS_ENTRY, "", 1).replace(NEXT_SECTION.group(0), NEXT_SECTION.group(0) + "\n\n" + ROS_ENTRY, 1)
refused("with the #900 entry moved out of the Probe record, it is refused", ros=MOVED)
refused("with the #900 entry doubled, it is ambiguous", ros=ROS.replace(ROS_ENTRY, ROS_ENTRY + ROS_ENTRY, 1))
refused("with the run not named, it is refused", ros=cut_ros(RUN, "a run"))
refused("with the cluster nowhere named, it is refused", ros=cut_ros(CLUSTER, "the cluster", -1))
refused("with the checksum struck, it is refused", ros=cut_ros(CHECKSUM, "a checksum", -1))
refused("with the paraphrase redirect struck, it is refused", ros=cut_ros(ROS_REDIRECT, "the paraphrase passed"))
refused("with input-guard.sh's exit struck, it is refused", ros=cut_ros("exit 0", "and ended"))
refused("with a table row removed, it is refused", ros=ROS.replace(ROW["4"] + "\n", "", 1))
refused("with another clock, so the records disagree, it is refused", ros=cut_row("2", "16:49Z", "16:48Z"))
refused("with another PASS count, so the records disagree, it is refused", ros=cut_row("3", "29 PASS", "30 PASS"))
refused("with RED over no FAIL, it is refused", ros=cut_row("5", "`KUBECON PROBE GREEN`", "`KUBECON PROBE RED`"))
refused("with GREEN over a FAIL, it is refused", ros=cut_row("1", "`KUBECON PROBE RED`", "`KUBECON PROBE GREEN`"))
refused("with a run's spend going down, it is refused", ros=cut_row("3", "to $0.3867", "to $0.3000"))
refused("with run 5's spend changed, so the records disagree, it is refused", ros=cut_row("5", "to $0.5355", "to $0.5354"))
if not ROW["2"].endswith(" | PASS |"):
    sys.exit(f"test_900_probe_record.py: {ROS_PATH} #900 table row 2 no longer ends with the literal ' | PASS |'")
refused("with topic-paraphrase FAIL in a row, it is refused",
        ros=ROS.replace(ROW["2"], ROW["2"][:-len("PASS |")] + "FAIL |", 1))

print("== each cut of readiness row 8's Live cell is refused ==")
for lit in LIVE_WORDS:
    refused(f"with {lit[:48]!r} struck from the Live cell, it is refused", ready=cut_live(lit, "it ran"))
refused("with row 8's Live cell emptied, it is refused", ready=READY.replace("| " + LIVE + " |", "|  |", 1))
refused("with the readiness record's #900 line struck, it is refused", ready=READY.replace(RECORD_LINE, "| x", 1))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#900's output holds in decisions.md, the run-of-show's Probe record and readiness row 8's Live cell.")
