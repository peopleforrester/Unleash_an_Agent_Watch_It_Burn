# ABOUTME: Pins #889's record criterion (#999): its 13:37Z community probe output is written in its decisions.md entry
# ABOUTME: and in the run-of-show's Probe record, the two agree, and the probe still prints the words they quote.
"""Holds the criterion of #889 that test review run 17942 found no test checked (#999).

#889's criterion: the probe's output is recorded in decisions.md and in the run-of-show's Probe record. Run 17911 ran
`verify/kubecon_probe.py` once on watch-it-burn-community at 13:37Z on 2026-11-06. What stays checkable is the record,
read here as literal text:

  1. decisions.md's "## 2026-11-06 · #889 · run 17911" entry names watch-it-burn-community and carries exactly one
     probe line, `13:37Z ... 11 PASS, 1 FAIL, `KUBECON PROBE RED`, $0.4179 to $0.4879 over 8 model calls`, and the
     off-topic note the probe printed: `answered 2 of 3` with `(1 of 3 re-sent once after a Bedrock ToolUse 424)`;
  2. facilitation/kubecon-na-2026-run-of-show.md's `### Probe record` section, and no other section, carries the
     "**2026-11-06, the linked-list ask's misses traced to one cause (#889).**" entry, naming run 17911 and
     watch-it-burn-community, with exactly one probe line, the same output, and the linked-list ask `answered 2 of 3`
     with its one re-send;
  3. the two records agree, and each line is one the probe could print: a FAIL count above zero reads RED, and the
     spend does not go down.

The records only mean what they say while the probe prints those words, so the test also checks kubecon_probe.py
still prints its `N PASS, M FAIL` count, `KUBECON PROBE RED` and `GREEN`, the spend line over model calls, and the
off-topic note's `answered N of M` and re-send words.

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
PROBE = (REPO / "verify" / "kubecon_probe.py").read_text(encoding="utf-8")

HEAD_DEC = "## 2026-11-06 · #889 · run 17911"
SECTION = "### Probe record"
HEAD_ROS = "**2026-11-06, the linked-list ask's misses traced to one cause (#889).**"
CLUSTER = "watch-it-burn-community"
RUN = "run 17911"
OFF_TOPIC = "answered 2 of 3"
RESENT_NOTE = "(1 of 3 re-sent once after a Bedrock ToolUse 424)"
ROS_RESEND = "answered on the probe's one re-send"

# The probe's summary line as both records write it: the clock, its `N PASS, M FAIL` count, its verdict line, and the
# spend it logs ("$a -> $b over N model calls"), the arrow written "to".
PROBE_LINE = re.compile(
    r"(\d\d:\d\dZ)[^.;]*?(\d+) PASS, (\d+) FAIL, `KUBECON PROBE (RED|GREEN)`, "
    r"\$(\d+\.\d{4}) to \$(\d+\.\d{4}) over (\d+) model calls")
# What run 17911's probe printed: (clock, PASS, FAIL, verdict, spend before, spend after, model calls).
EXPECTED = ("13:37Z", "11", "1", "RED", "0.4179", "0.4879", "8")
EXPECTED_TEXT = "11 PASS, 1 FAIL, `KUBECON PROBE RED`, $0.4179 to $0.4879 over 8 model calls"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_889_probe_record.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so a line wrapped in the Markdown reads as one line."""
    return " ".join(text.split())


def dec_entry(text: str) -> str:
    """The #889 decisions.md entry, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(HEAD_DEC) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def probe_section(text: str) -> str:
    """The run-of-show's Probe record section, to the next heading of level 1 to 3 or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(SECTION) + r"[ \t]*\n.*?(?=^#{1,3} |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def ros_entry(section: str) -> str:
    """The #889 entry inside `section`: its bold head to the next dated bold head or the section's end."""
    m = re.search(r"^" + re.escape(HEAD_ROS) + r".*?(?=^\*\*\d{4}-\d\d-\d\d, |\Z)", section, flags=re.M | re.S)
    return m.group(0) if m else ""


def read_line(record: str, where: str) -> tuple[tuple[str, ...] | None, str]:
    """The one probe line in `record` as a tuple, or None and why not."""
    lines = PROBE_LINE.findall(flat(record))
    if len(lines) != 1:
        return None, f"{where} has {len(lines)} probe output lines; it needs exactly one"
    got = tuple(lines[0])
    _, passed, failed, colour, before, after, calls = got
    if (int(failed) > 0) != (colour == "RED"):
        return None, f"{where}'s line reads {failed} FAIL with KUBECON PROBE {colour}, which the probe never prints"
    if float(after) < float(before):
        return None, f"{where}'s spend goes down, ${before} to ${after}"
    if int(calls) == 0 or int(passed) + int(failed) == 0:
        return None, f"{where}'s line records no beats or no model calls"
    return got, ""


def verdict(decisions: str, ros: str) -> tuple[bool, str]:
    """Whether both records carry #889's probe output and agree on it, and why not."""
    entry = dec_entry(decisions)
    if not entry:
        return False, f"no decisions.md entry starting {HEAD_DEC!r}"
    dflat = flat(entry)
    if CLUSTER not in dflat:
        return False, f"the decisions.md #889 entry does not name the cluster {CLUSTER}"
    dec, why = read_line(entry, "the decisions.md #889 entry")
    if dec is None:
        return False, why
    if OFF_TOPIC not in dflat or RESENT_NOTE not in dflat:
        return False, (f"the decisions.md #889 entry does not carry the probe's off-topic note "
                       f"{OFF_TOPIC!r} with {RESENT_NOTE!r}")

    section = probe_section(ros)
    if not section:
        return False, f"the run-of-show has no {SECTION!r} section"
    heads = flat(ros).count(flat(HEAD_ROS))
    if heads != 1:
        return False, f"the run-of-show carries the #889 head {heads} times; it needs exactly one"
    rentry = ros_entry(section)
    if not rentry:
        return False, f"the run-of-show's {SECTION!r} section has no entry starting {HEAD_ROS!r}"
    rflat = flat(rentry)
    for lit in (RUN, CLUSTER):
        if lit not in rflat:
            return False, f"the run-of-show's #889 entry does not name {lit}"
    ros_line, why = read_line(rentry, "the run-of-show's #889 entry")
    if ros_line is None:
        return False, why
    if OFF_TOPIC not in rflat or ROS_RESEND not in rflat:
        return False, f"the run-of-show's #889 entry does not record the linked-list ask {OFF_TOPIC!r} with its re-send"

    if dec != ros_line:
        return False, f"the records disagree: decisions.md reads {dec}, the run-of-show {ros_line}"
    if dec != EXPECTED:
        return False, f"both records read {dec}; run 17911's probe printed {EXPECTED}"
    return True, (f"decisions.md and the run-of-show's Probe record both carry {CLUSTER} at {dec[0]}: "
                  f"{EXPECTED_TEXT}, the off-topic ask {OFF_TOPIC} with one re-send")


# ---- what the records' words mean: the probe still prints them ----
print("== kubecon_probe.py still prints the words the records quote ==")
check("it prints its `N PASS, M FAIL` count",
      'print(f"\\n{len(results)} beats: {len(results) - len(fails)} PASS, {len(fails)} FAIL")' in PROBE)
check("it prints KUBECON PROBE GREEN with no FAIL and RED with one",
      'print("KUBECON PROBE GREEN" if not fails else "KUBECON PROBE RED")' in PROBE)
check("it logs the spend before and after over the model calls",
      re.search(r'"spend on %s: \$%\.4f -> \$%\.4f over %d model calls', PROBE) is not None)
check("the off-topic note reads `answered N of M`", 'f"answered {landed} of {len(attempts)}' in PROBE)
check("the off-topic note names its re-sends", "re-sent once after a Bedrock ToolUse 424)" in PROBE)

# ---- the records as they stand ----
anchor(DECISIONS, HEAD_DEC, "decisions.md")
DEC_ENTRY = dec_entry(DECISIONS)
DEC_FLAT = flat(DEC_ENTRY)
for lit in (CLUSTER, "13:37Z", EXPECTED_TEXT, OFF_TOPIC, RESENT_NOTE):
    anchor(DEC_FLAT, lit, "decisions.md #889 entry")
anchor(ROS, SECTION, ROS_PATH)
anchor(ROS, HEAD_ROS, ROS_PATH)
SEC = probe_section(ROS)
anchor(SEC, HEAD_ROS, f"{ROS_PATH} {SECTION} section")
ROS_ENTRY = ros_entry(SEC)
ROS_FLAT = flat(ROS_ENTRY)
for lit in (RUN, CLUSTER, "Community, 13:37Z: " + EXPECTED_TEXT, OFF_TOPIC, ROS_RESEND):
    anchor(ROS_FLAT, lit, f"{ROS_PATH} #889 entry")

print("== #889's probe output is in decisions.md and the run-of-show's Probe record ==")
ok, why = verdict(DECISIONS, ROS)
check("both records are there and agree with what the probe printed", ok, why)
print(f"        {why}")


def cut_dec(old: str, new: str, count: int = 1) -> str:
    """decisions.md with `old` replaced by `new` inside the #889 entry only (the entry flattened); count -1 is all."""
    anchor(DEC_FLAT, old, "decisions.md #889 entry")
    return DECISIONS.replace(DEC_ENTRY, DEC_FLAT.replace(old, new, count) + "\n\n", 1)


def cut_ros(old: str, new: str, count: int = 1) -> str:
    """The run-of-show with `old` replaced by `new` inside the #889 entry only (the entry flattened); -1 is all."""
    anchor(ROS_FLAT, old, f"{ROS_PATH} #889 entry")
    return ROS.replace(ROS_ENTRY, ROS_FLAT.replace(old, new, count) + "\n\n", 1)


def refused(name: str, decisions: str = DECISIONS, ros: str = ROS) -> None:
    ok_, why_ = verdict(decisions, ros)
    check(name, not ok_, f"the verdict still held: {why_}")


# The flattening itself must not change the verdict, or every cut below would be read as refused for that alone.
check("a flattened copy of each record still reads green",
      verdict(cut_dec(OFF_TOPIC, OFF_TOPIC), cut_ros(OFF_TOPIC, OFF_TOPIC))[0])

print("== each cut of the real decisions.md entry is refused ==")
refused("with the #889 heading struck, the entry is not found",
        DECISIONS.replace(HEAD_DEC, "## 2026-11-06 · #000 · struck", 1))
refused("with the entry removed, nothing is recorded", DECISIONS.replace(DEC_ENTRY, "", 1))
refused("with the cluster nowhere named, it is refused", cut_dec(CLUSTER, "the cluster", -1))
refused("with the probe line struck, it is refused", cut_dec(EXPECTED_TEXT, "the probe ran"))
refused("with the probe line doubled, the record is ambiguous",
        cut_dec(EXPECTED_TEXT, EXPECTED_TEXT + "; again 13:37Z: " + EXPECTED_TEXT))
refused("with another clock, it is refused", cut_dec("13:37Z", "13:38Z"))
refused("with another PASS count, it is refused", cut_dec("11 PASS", "12 PASS"))
refused("with no FAIL but still RED, it is refused", cut_dec("1 FAIL", "0 FAIL"))
refused("with GREEN over one FAIL, it is refused", cut_dec("`KUBECON PROBE RED`", "`KUBECON PROBE GREEN`"))
refused("with another starting spend, it is refused", cut_dec("$0.4179 to", "$0.4180 to"))
refused("with the spend going down, it is refused", cut_dec("to $0.4879", "to $0.4000"))
refused("with another call count, it is refused", cut_dec("over 8 model calls", "over 9 model calls"))
refused("with the off-topic count struck, it is refused", cut_dec(OFF_TOPIC, "answered 3 of 3"))
refused("with the re-send note struck, it is refused", cut_dec(RESENT_NOTE, "(after a retry)"))

print("== each cut of the real run-of-show entry is refused ==")
refused("with the Probe record heading renamed, the section is not found",
        ros=ROS.replace(SECTION + "\n", "### Probe log\n", 1))
refused("with the #889 entry removed, nothing is recorded", ros=ROS.replace(ROS_ENTRY, "", 1))
NEXT_SECTION = re.search(r"^#{1,3} .*$", ROS[ROS.index(SEC) + len(SEC):], flags=re.M)
if NEXT_SECTION is None:
    sys.exit(f"test_889_probe_record.py: {ROS_PATH} has no heading after {SECTION!r} to move the #889 entry under")
MOVED = ROS.replace(ROS_ENTRY, "", 1).replace(NEXT_SECTION.group(0), NEXT_SECTION.group(0) + "\n\n" + ROS_ENTRY, 1)
refused("with the #889 entry moved out of the Probe record, it is refused", ros=MOVED)
refused("with the #889 entry doubled, it is ambiguous", ros=ROS.replace(ROS_ENTRY, ROS_ENTRY + ROS_ENTRY, 1))
refused("with the run not named, it is refused", ros=cut_ros(RUN, "a run"))
refused("with the cluster nowhere named, it is refused", ros=cut_ros(CLUSTER, "the cluster", -1))
refused("with the probe line struck, it is refused", ros=cut_ros(EXPECTED_TEXT, "the probe ran"))
refused("with another clock, it is refused", ros=cut_ros("Community, 13:37Z", "Community, 13:38Z"))
refused("with another PASS count, so the records disagree, it is refused", ros=cut_ros("11 PASS", "12 PASS"))
refused("with GREEN over one FAIL, it is refused", ros=cut_ros("`KUBECON PROBE RED`", "`KUBECON PROBE GREEN`"))
refused("with another closing spend, it is refused", ros=cut_ros("to $0.4879", "to $0.4878"))
refused("with another call count, it is refused", ros=cut_ros("over 8 model calls", "over 7 model calls"))
refused("with the linked-list count struck, it is refused", ros=cut_ros(OFF_TOPIC, "answered 3 of 3"))
refused("with the re-send not recorded, it is refused", ros=cut_ros(ROS_RESEND, "answered on the next try"))

print("== both records changed alike still differ from what the probe printed ==")
refused("with both records reading 12 PASS, it is refused",
        cut_dec("11 PASS", "12 PASS"), cut_ros("11 PASS", "12 PASS"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#889's probe output holds in decisions.md and the run-of-show's Probe record, and the two agree.")
