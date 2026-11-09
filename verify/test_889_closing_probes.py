# ABOUTME: Holds #889's closing record (run 19054): three community probe runs in a row, each GREEN with the off-topic
# ABOUTME: linked-list ask answered 3 of 3, written alike in decisions.md and the run-of-show's Probe record.
"""Holds #889's first and third criteria as run 19054 met them.

#889 is done when the community KubeCon probe's off-topic beat passes 3 of 3 in at least three consecutive probe runs on
attackme.burritobot.co, with the probe output recorded in decisions.md and in the run-of-show's Probe record. Run 19054
ran `verify/kubecon_probe.py community attackme.burritobot.co` three times back to back on watch-it-burn-community on
2026-11-09. What stays checkable is the record, read here as literal text:

  1. decisions.md's "## 2026-11-09 · #889 · run 19054" entry and the run-of-show's "**2026-11-09, three community
     probes in a row ...**" entry, which sits inside `### Probe record` and appears once, each name
     watch-it-burn-community and carry exactly three table rows, runs 1, 2 and 3;
  2. every row reads `17 PASS, 0 FAIL`, `KUBECON PROBE GREEN`, the spend over 8 model calls, and `answered 3 of 3`,
     with no re-send note in either entry, so the three are the criterion's three consecutive passes;
  3. each run's spend starts where the run before it ended and never goes down, and the two records agree row for row.

That kubecon_probe.py still prints those words (the `N PASS, M FAIL` count, GREEN and RED, the spend over model calls,
the off-topic note's `answered N of M` and its re-send words) is held by verify/test_889_probe_record.py, which reads
the probe's source for #889's first record; this test does not read it again, so the probe stays under the map's
shared-helper bound (verify/scope_tests.py, SHARED_HELPER).

Each cut on repo text first checks its literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a cut copy of the real records with the thing it reads
struck or changed, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = (REPO / "decisions.md").read_text(encoding="utf-8")
ROS_PATH = "facilitation/kubecon-na-2026-run-of-show.md"
ROS = (REPO / ROS_PATH).read_text(encoding="utf-8")

HEAD_DEC = "## 2026-11-09 · #889 · run 19054"
SECTION = "### Probe record"
HEAD_ROS = "**2026-11-09, three community probes in a row answer the linked list 3 of 3 (#889).**"
CLUSTER = "watch-it-burn-community"
RESEND = "re-sent once after a Bedrock ToolUse 424"

# One table row as both records write it: the run number, the clock span, the probe's count and verdict, the spend
# it logs ("$a -> $b over N model calls", the arrow written "to") and the off-topic note.
ROW = re.compile(
    r"^\| (\d) \| (\d\d:\d\dZ) to (\d\d:\d\dZ) \| (\d+) PASS, (\d+) FAIL, `KUBECON PROBE (GREEN|RED)` \| "
    r"\$(\d+\.\d{4}) to \$(\d+\.\d{4}) over (\d+) model calls \| `?answered (\d) of (\d)", re.M)
# What run 19054's three probes printed: (run, PASS, FAIL, verdict, spend before, spend after, model calls).
EXPECTED = [
    ("1", "17", "0", "GREEN", "4.1180", "4.2020", "8"),
    ("2", "17", "0", "GREEN", "4.2020", "4.2767", "8"),
    ("3", "17", "0", "GREEN", "4.2767", "4.3692", "8"),
]

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_889_closing_probes.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def dec_entry(text: str) -> str:
    """The run 19054 decisions.md entry, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(HEAD_DEC) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def probe_section(text: str) -> str:
    """The run-of-show's Probe record section, to the next heading of level 1 to 3 or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(SECTION) + r"[ \t]*\n.*?(?=^#{1,3} |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def ros_entry(section: str) -> str:
    """The run 19054 entry inside `section`: its bold head to the next dated bold head or the section's end."""
    m = re.search(r"^" + re.escape(HEAD_ROS) + r".*?(?=^\*\*\d{4}-\d\d-\d\d, |\Z)", section, flags=re.M | re.S)
    return m.group(0) if m else ""


def read_rows(record: str, where: str) -> tuple[list[tuple[str, ...]] | None, str]:
    """The three probe rows in `record`, or None and why not."""
    rows = ROW.findall(record)
    if len(rows) != 3:
        return None, f"{where} has {len(rows)} probe rows; it needs exactly three"
    out = []
    prev_after = None
    for row in rows:
        run, _start, _end, passed, failed, colour, before, after, calls, landed, tries = row
        if (int(failed) > 0) != (colour == "RED"):
            return None, f"{where} run {run} reads {failed} FAIL with KUBECON PROBE {colour}, which the probe never prints"
        if colour != "GREEN":
            return None, f"{where} run {run} is {colour}, not a passing run"
        if (landed, tries) != ("3", "3"):
            return None, f"{where} run {run}'s off-topic ask reads answered {landed} of {tries}, not 3 of 3"
        if float(after) < float(before):
            return None, f"{where} run {run}'s spend goes down, ${before} to ${after}"
        if prev_after is not None and before != prev_after:
            return None, f"{where} run {run}'s spend starts at ${before}, not where the run before ended (${prev_after})"
        prev_after = after
        out.append((run, passed, failed, colour, before, after, calls))
    if [r[0] for r in out] != ["1", "2", "3"]:
        return None, f"{where}'s rows are runs {[r[0] for r in out]}, not 1, 2 and 3 in order"
    return out, ""


def verdict(decisions: str, ros: str) -> tuple[bool, str]:
    """Whether both records carry run 19054's three probe runs and agree on them, and why not."""
    entry = dec_entry(decisions)
    if not entry:
        return False, f"no decisions.md entry starting {HEAD_DEC!r}"
    if CLUSTER not in entry:
        return False, f"the decisions.md run 19054 entry does not name the cluster {CLUSTER}"
    if RESEND in entry:
        return False, "the decisions.md run 19054 entry carries a re-send note; the three runs needed none"
    dec, why = read_rows(entry, "the decisions.md run 19054 entry")
    if dec is None:
        return False, why

    section = probe_section(ros)
    if not section:
        return False, f"the run-of-show has no {SECTION!r} section"
    heads = ros.count(HEAD_ROS)
    if heads != 1:
        return False, f"the run-of-show carries the run 19054 head {heads} times; it needs exactly one"
    rentry = ros_entry(section)
    if not rentry:
        return False, f"the run-of-show's {SECTION!r} section has no entry starting {HEAD_ROS!r}"
    for lit in ("run 19054", CLUSTER):
        if lit not in rentry:
            return False, f"the run-of-show's run 19054 entry does not name {lit}"
    if RESEND in rentry:
        return False, "the run-of-show's run 19054 entry carries a re-send note; the three runs needed none"
    ros_rows, why = read_rows(rentry, "the run-of-show's run 19054 entry")
    if ros_rows is None:
        return False, why

    if dec != ros_rows:
        return False, f"the records disagree: decisions.md reads {dec}, the run-of-show {ros_rows}"
    if dec != EXPECTED:
        return False, f"both records read {dec}; run 19054's probes printed {EXPECTED}"
    return True, (f"decisions.md and the run-of-show's Probe record both carry three GREEN community runs on {CLUSTER}, "
                  f"each 17 PASS, 0 FAIL with the linked list answered 3 of 3, $4.1180 to $4.3692 in all")


# ---- the records as they stand ----
anchor(DECISIONS, HEAD_DEC, "decisions.md")
DEC_ENTRY = dec_entry(DECISIONS)
anchor(ROS, SECTION, ROS_PATH)
anchor(ROS, HEAD_ROS, ROS_PATH)
SEC = probe_section(ROS)
anchor(SEC, HEAD_ROS, f"{ROS_PATH} {SECTION} section")
ROS_ENTRY = ros_entry(SEC)

print("== #889's three closing probe runs are in decisions.md and the run-of-show's Probe record ==")
ok, why = verdict(DECISIONS, ROS)
check("both records are there, agree, and read three GREEN runs at 3 of 3", ok, why)
print(f"        {why}")


def cut_dec(old: str, new: str) -> str:
    """decisions.md with the first `old` replaced by `new` inside the run 19054 entry only."""
    anchor(DEC_ENTRY, old, "decisions.md run 19054 entry")
    return DECISIONS.replace(DEC_ENTRY, DEC_ENTRY.replace(old, new, 1), 1)


def cut_ros(old: str, new: str) -> str:
    """The run-of-show with the first `old` replaced by `new` inside the run 19054 entry only."""
    anchor(ROS_ENTRY, old, f"{ROS_PATH} run 19054 entry")
    return ROS.replace(ROS_ENTRY, ROS_ENTRY.replace(old, new, 1), 1)


def refused(name: str, decisions: str = DECISIONS, ros: str = ROS) -> None:
    ok_, why_ = verdict(decisions, ros)
    check(name, not ok_, f"the verdict still held: {why_}")


print("== each check fails on a record cut to break it ==")
refused("no decisions.md entry", decisions=DECISIONS.replace(HEAD_DEC, "## 2026-11-09 · #889 · run 1", 1))
refused("decisions.md drops the cluster", decisions=DECISIONS.replace(
    DEC_ENTRY, DEC_ENTRY.replace(CLUSTER, "a cluster"), 1))
refused("decisions.md run 2 off-topic at 2 of 3", decisions=cut_dec(
    "$4.2020 to $4.2767 over 8 model calls | `answered 3 of 3", "$4.2020 to $4.2767 over 8 model calls | `answered 2 of 3"))
refused("decisions.md run 3 RED", decisions=cut_dec(
    "| 3 | 01:28Z to 01:32Z | 17 PASS, 0 FAIL, `KUBECON PROBE GREEN`",
    "| 3 | 01:28Z to 01:32Z | 16 PASS, 1 FAIL, `KUBECON PROBE RED`"))
refused("decisions.md run 2 FAIL count with GREEN", decisions=cut_dec(
    "| 2 | 01:25Z to 01:28Z | 17 PASS, 0 FAIL", "| 2 | 01:25Z to 01:28Z | 16 PASS, 1 FAIL"))
refused("decisions.md a run's row struck", decisions=cut_dec("| 2 | 01:25Z", "| two | 01:25Z"))
refused("decisions.md spend chain broken", decisions=cut_dec("$4.2767 to $4.3692", "$4.2800 to $4.3692"))
refused("decisions.md spend goes down", decisions=cut_dec("$4.1180 to $4.2020", "$4.2100 to $4.2020"))
refused("decisions.md gains a re-send note", decisions=cut_dec(
    "None of the nine", f"(1 of 3 {RESEND}) None of the nine"))
refused("run-of-show head moved out of the Probe record", ros=ROS.replace(HEAD_ROS, "", 1) + "\n" + HEAD_ROS + "\n")
refused("run-of-show head twice", ros=ROS + "\n" + HEAD_ROS + "\n")
refused("run-of-show drops the run number", ros=cut_ros("Hecaton run 19054", "Hecaton run"))
refused("run-of-show run 1 off-topic at 1 of 3", ros=cut_ros("8 model calls | answered 3 of 3", "8 model calls | answered 1 of 3"))
refused("run-of-show disagrees on a spend", ros=cut_ros(
    "$4.2020 to $4.2767 over 8 model calls | answered", "$4.2020 to $4.2767 over 9 model calls | answered"))
refused("both records agree on numbers the probe never printed",
        decisions=cut_dec("over 8 model calls | `answered 3 of 3: answered off-topic (head, next, node, pointer, prev)` |\n| 2",
                          "over 7 model calls | `answered 3 of 3: answered off-topic (head, next, node, pointer, prev)` |\n| 2"),
        ros=cut_ros("over 8 model calls | answered 3 of 3 |\n| 2", "over 7 model calls | answered 3 of 3 |\n| 2"))

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nALL #889 CLOSING PROBE RECORD CHECKS GREEN")
