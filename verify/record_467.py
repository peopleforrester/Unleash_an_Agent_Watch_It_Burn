# ABOUTME: The verdicts on #467's live-run record (#1017): decisions.md's run 17944 entry and the run report on #467
# ABOUTME: must each give the commands run on both KubeCon clusters and what they printed. Imported by two tests.
"""What "the result and the commands are recorded on this issue and in decisions.md" means for #467, as code.

#467 (validate the Kyverno CEL policy migration on a live cluster) has two criteria. The first was met live by run
17944 on 2026-11-06: no ClusterPolicy on watch-it-burn-private or watch-it-burn-community, and each cluster's CEL
policies READY. The second is that the result and the commands are recorded on the issue and in decisions.md. Test
review run 18030 found no test held that second one (#1017). The live run is not repeatable from a test, but its
record is, and these two verdicts read it:

  `entry_verdict(decisions)` reads the "## 2026-11-06 · #467 · run 17944" entry. Its paragraph labelled
  "**Both clusters, the commands and what they printed (<date>, <hh:mm> to <hh:mm> UTC).**" must be followed by an
  indented block of commands, each with what it printed indented under it, and for each cluster that block must
  hold `kubectl --context <cluster> get clusterpolicy` printing `No resources found` and
  `kubectl --context <cluster> get validatingpolicy,imagevalidatingpolicy` printing the policies it listed with
  READY true. The prose after it must give each cluster's profile and its count of policies, a count equal to the
  names the block lists, and record `CONTEXT=<context> python3 -u verify/test_kyverno_cel_live.py` passing its
  prerequisites and steps 1 to 3 on both.

  `comment_verdict(body, entry)` reads one comment on #467: the run report hecaton posts. It must name both
  clusters, `kubectl --context watch-it-burn-private get clusterpolicy`, `get clusterpolicy` printing
  'No resources found' on each, `get validatingpolicy,imagevalidatingpolicy`, the same policy counts the entry
  gives with READY, the live check passing its prerequisites, the run's own branch (`agent/467-<run>`, the run the
  entry is headed with), and the second criterion's table row marked yes with decisions.md named in it.

Each returns (ok, why); `why` names the first thing missing. verify/test_467_live_record.py runs the first on the
tree and both on cut copies of the real texts; verify/test_467_live_record_comment_e2e.py reads #467's comments with
gh's token (verify/gh_comments.py) and runs the second on each.
"""
from __future__ import annotations

import re

HEAD = "## 2026-11-06 · #467 · run 17944"
RUN = "17944"
CLUSTERS = {"private": "watch-it-burn-private", "community": "watch-it-burn-community"}
PROFILES = {"private": "kubecon-private", "community": "kubecon-community"}
LABEL = "**Both clusters, the commands and what they printed"
LABEL_TIME = re.compile(re.escape(LABEL) + r" \((\d{4}-\d\d-\d\d), (\d\d:\d\d) to (\d\d:\d\d) UTC\)\.\*\*")
LIVE_CHECK = "`CONTEXT=<context> python3 -u verify/test_kyverno_cel_live.py` passed its prerequisites and steps 1 to 3 on both"
CRITERION = "The result and the commands are recorded on this issue and in decisions.md"
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15}
# A policy name as the block lists it: lower-case words joined by hyphens.
POLICY = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
NOT_READY = re.compile(r"READY false|not READY|NotReady", re.I)


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so words wrapped across lines read as one line."""
    return " ".join(text.split())


def dec_entry(text: str, head: str = HEAD) -> str:
    """The decisions.md entry starting `head`, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(head) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def command_block(entry: str) -> list[tuple[str, str]]:
    """The indented block after the commands label, as [(command, what it printed)], in order. A command line is
    indented four spaces and starts with `kubectl`; each line indented further under it is what it printed."""
    at = entry.find(LABEL)
    if at < 0:
        return []
    rest = entry[at:].split("\n", 1)[1] if "\n" in entry[at:] else ""
    pairs: list[list[str]] = []
    for line in rest.split("\n"):
        if not line.strip():
            continue
        if not line.startswith("    "):
            break
        if line.startswith("    kubectl"):
            pairs.append([line.strip(), ""])
        elif line.startswith("      ") and pairs:
            pairs[-1][1] = (pairs[-1][1] + " " + line.strip()).strip()
        else:
            break
    return [(c, o) for c, o in pairs]


def number(word: str) -> int:
    return NUMBERS.get(word.lower(), -1)


def entry_verdict(decisions: str) -> tuple[bool, str]:
    """Whether decisions.md records #467's live run: each command on each cluster and what it printed."""
    entry = dec_entry(decisions)
    if not entry:
        return False, f"no decisions.md entry starting {HEAD!r}"
    if LABEL not in entry:
        return False, f"the #467 entry has no paragraph labelled {LABEL!r}"
    t = LABEL_TIME.search(entry)
    if not t:
        return False, "the commands label does not give the date and the UTC times the commands ran"
    block = command_block(entry)
    if not block:
        return False, "no indented `kubectl` commands follow the commands label"
    printed = {c: o for c, o in block}
    names: dict[str, list[str]] = {}
    for side, ctx in CLUSTERS.items():
        cp = f"kubectl --context {ctx} get clusterpolicy"
        if cp not in printed:
            return False, f"the block does not record `{cp}`"
        if not printed[cp].startswith("No resources found"):
            return False, f"`{cp}` is recorded printing {printed[cp][:80]!r}, not 'No resources found'"
        vp = f"kubectl --context {ctx} get validatingpolicy,imagevalidatingpolicy"
        if vp not in printed:
            return False, f"the block does not record `{vp}`"
        out = printed[vp]
        if not out:
            return False, f"`{vp}` is recorded with nothing under it"
        if "READY true" not in out or NOT_READY.search(out):
            return False, f"`{vp}` is not recorded with every policy READY true: {out[:120]!r}"
        listed = sorted(set(POLICY.findall(out)))
        if not listed:
            return False, f"`{vp}` is recorded naming no policy"
        names[side] = listed
    prose = flat(entry[entry.find(LABEL):])
    for side, profile in PROFILES.items():
        if f"lab-platform/profile={profile}" not in flat(entry) and f"`{profile}`" not in flat(entry):
            return False, f"the entry does not record that {CLUSTERS[side]} runs profile {profile}"
        m = re.search(r"\b(" + "|".join(NUMBERS) + r") on " + re.escape(profile) + r"\b", prose, re.I)
        if not m:
            return False, f"the entry does not give the count of policies on {profile} ('<number> on {profile}')"
        if number(m.group(1)) != len(names[side]):
            return False, (f"the entry says {m.group(1)} on {profile}, but its block lists {len(names[side])} "
                           f"policies on {CLUSTERS[side]}: {', '.join(names[side])}")
    if LIVE_CHECK not in prose:
        return False, f"the entry does not record the live check: {LIVE_CHECK!r}"
    return True, (f"{t.group(1)} {t.group(2)} to {t.group(3)} UTC: no ClusterPolicy on either cluster, "
                  f"{len(names['private'])} policies READY on {PROFILES['private']} and "
                  f"{len(names['community'])} on {PROFILES['community']}, the live check through step 3 on both")


def counts(entry: str) -> dict[str, str]:
    """The number words the entry gives for each profile's policies, {side: word}, lower-cased."""
    prose = flat(entry)
    found = {}
    for side, profile in PROFILES.items():
        m = re.search(r"\b(" + "|".join(NUMBERS) + r") on " + re.escape(profile) + r"\b", prose, re.I)
        if m:
            found[side] = m.group(1).lower()
    return found


def comment_verdict(body: str, entry: str) -> tuple[bool, str]:
    """Whether one comment on #467 records the run's result and commands as the decisions.md entry does."""
    text = flat(body)
    if not entry:
        return False, f"no decisions.md entry starting {HEAD!r} to hold the comment against"
    for ctx in CLUSTERS.values():
        if ctx not in text:
            return False, f"the comment does not name {ctx}"
    cp = f"`kubectl --context {CLUSTERS['private']} get clusterpolicy` printed 'No resources found'"
    if cp not in text:
        return False, f"the comment does not record {cp}"
    if text.count("get clusterpolicy` printed 'No resources found'") < len(CLUSTERS):
        return False, "the comment does not record `get clusterpolicy` printing 'No resources found' on each cluster"
    if "`get validatingpolicy,imagevalidatingpolicy`" not in text:
        return False, "the comment does not record the command `get validatingpolicy,imagevalidatingpolicy`"
    want = counts(entry)
    for side in CLUSTERS:
        word = want.get(side)
        if not word:
            return False, f"the entry gives no count on {PROFILES[side]} for the comment to match"
        # The number word in any case ("Two" opens a sentence), READY only as the cluster prints it.
        if not re.search(r"\b(?i:" + word + r")\b[^.|]{0,40}\bREADY\b", text):
            return False, (f"the comment does not give {PROFILES[side]}'s {word} policies as READY, the count "
                           f"decisions.md records")
    if "verify/test_kyverno_cel_live.py` passed its prerequisites" not in text:
        return False, "the comment does not record verify/test_kyverno_cel_live.py passing its prerequisites"
    if f"agent/467-{RUN}" not in text:
        return False, f"the comment is not run {RUN}'s report: it does not name branch agent/467-{RUN}"
    row = re.search(r"\| " + re.escape(CRITERION) + r" \| (\w+) \|([^|]*)\|", text)
    if not row:
        return False, f"the comment has no table row for the criterion {CRITERION!r}"
    if row.group(1) != "yes":
        return False, f"the comment's row for the record criterion reads {row.group(1)!r}, not 'yes'"
    if "decisions.md" not in row.group(2) or f"#467 run {RUN} entry" not in row.group(2):
        return False, f"the comment's row for the record criterion does not name decisions.md's #467 run {RUN} entry"
    return True, (f"run {RUN}'s report records both clusters' commands and results, {want['private']} and "
                  f"{want['community']} policies READY, and names decisions.md's entry")
