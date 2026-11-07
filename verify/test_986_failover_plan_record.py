# ABOUTME: Pins #986's test-plan criterion (#1030): its decisions.md entry records the plan for failing over a KubeCon
# ABOUTME: cluster before the 2026-11-12 talk, how a KubeCon standby is built and promoted, and no lifecycle touched.
"""Holds the criterion of #986 that test review run 18050 found no test checked (#1030).

#986's criterion: decisions.md records the test plan for failing over a KubeCon cluster before 2026-11-12, including
how a KubeCon-profile standby is built and promoted without touching the two live clusters' own lifecycle (no
creating or tearing down clusters unless the plan says which standby and Michael's ruling covers it).

The record is the "## 2026-11-06 · #986 · run 17914" entry, read here as literal text. It must carry exactly one bold
"**The test plan, for before the talk on <date>.**" block, and that block must hold:

  1. the talk's date, the KubeCon start the run-of-show gives (2026-11-12), with the entry dated before it;
  2. numbered items 1, 2, 3, ... in order, among them "What is tested", "Which clusters", "The real standbys" and
     "Not covered";
  3. under "What is tested": the failover as attendees meet it on `attackme.burritobot.co`, backups.py's Watcher
     promoting, and a KubeCon-profile cluster answering afterwards;
  4. under "Which clusters": how a standby is built, by name (`backups.py up`, fleet.sh's
     `bootstrap_profile_for_role` under event.sh's `WIB_ROSTER_PROFILES=kubecon`, giving `kubecon-community`, as
     `verify/test_backups.py` holds), and that no cluster is created or torn down, no run builds a standby and
     neither cluster is changed, on Michael's ruling of 2026-11-02 (#809, hecaton#496);
  5. under "The real standbys": the standby that is really built, named as a backups.tsv row in that row's region,
     in Michael's hand rehearsal, which the issue does not wait on; no standby is named anywhere else in the plan,
     and the plan carries no command that creates or deletes a cluster.

The record only means what it says while the repo agrees, so the test also reads the names against their sources:
fleet.sh maps kubecon:community to `kubecon-community`, event.sh defaults `WIB_ROSTER_PROFILES` to kubecon,
backups.py has its `up` verb, its Watcher and the PROMOTED line, test_backups.py checks the KubeCon profile,
CLAUDE.md records the ruling with the same date and issues and that a run never creates or tears down a cluster,
and the run-of-show's rehearsal step builds the standby's wave and runs the drill against it.

Each cut on repo text first checks the literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a copy of the real record, or of a source it reads, with
the thing it reads struck or flipped, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
FILES = {
    "decisions": "decisions.md",
    "claude": "CLAUDE.md",
    "fleet": "infra/terraform/fleet/fleet.sh",
    "event": "infra/terraform/fleet/event.sh",
    "backups": "infra/terraform/fleet/backups.py",
    "tsv": "infra/terraform/fleet/backups.tsv",
    "test_backups": "verify/test_backups.py",
    "ros": "facilitation/kubecon-na-2026-run-of-show.md",
}
REAL = {k: (REPO / v).read_text(encoding="utf-8") for k, v in FILES.items()}

HEAD_986 = "## 2026-11-06 · #986 · run 17914"
PLAN_LABEL = re.compile(r"^\*\*The test plan, for before the talk on (\d{4}-\d{2}-\d{2})\.\*\*", re.M)
ITEM = re.compile(r"^(\d+)\. \*([^*]+)\*(.*?)(?=^\d+\. \*|\Z)", re.M | re.S)
STANDBY = re.compile(r"watch-it-burn-(?:community|private)-b\d\d")
KUBECON_START = re.compile(r"The KubeCon start is (\d{4}-\d{2}-\d{2})")
RULING_PLAN = "Michael's ruling of 2026-11-02 (#809, hecaton#496)"
RULING_CLAUDE = "Michael's ruling of 2026-11-02 (hecaton#496, #809)"
NO_RUN_LIFECYCLE_CLAUDE = "A run never creates or tears down a cluster"
LIFECYCLE_COMMANDS = ("eksctl create", "eksctl delete", "backups.py down", "terraform destroy", "fleet.sh up",
                      "create-cluster", "delete-cluster", "create-nodegroup", "delete-nodegroup")
NEEDED_ITEMS = ("What is tested", "Which clusters", "The real standbys", "Not covered")
TESTED_NEEDS = ("failover", "`attackme.burritobot.co`", "backups.py's Watcher", "promoting",
                "KubeCon-profile cluster answering")
BUILD_NEEDS = ("is a `kubecon-community` cluster", "the profile `backups.py up` builds a community standby with",
               "`bootstrap_profile_for_role`", "`WIB_ROSTER_PROFILES=kubecon`",
               "`verify/test_backups.py` holds for every standby")
NO_LIFECYCLE_NEEDS = ("No cluster is created or torn down.", "no run builds a standby", "Neither cluster is changed",
                      RULING_PLAN)
STANDBYS_NEEDS = ("Michael's hand rehearsal", "this issue does not wait on it")
FLEET_KUBECON = "kubecon:community) printf 'kubecon-community'"
EVENT_DEFAULT = 'WIB_ROSTER_PROFILES="${WIB_ROSTER_PROFILES:-kubecon}"'
BACKUPS_NEEDS = ('sub.add_parser("up")', "def cmd_up(", "class Watcher:", ": PROMOTED ")
TEST_BACKUPS_NEEDS = ('fleet("bootstrap_profile_for_role", want_role)', '"kubecon-community"')
REHEARSAL_STEP = re.compile(r"^3\. \*\*Rehearsal, once\*\*.*?(?=^4\. \*\*)", re.M | re.S)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_986_failover_plan_record.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so a phrase wrapped across lines reads as one line."""
    return " ".join(text.split())


def dec_entry(text: str, head: str) -> str:
    """The decisions.md entry starting `head`, to the next level-2 heading or EOF; empty when absent."""
    m = re.search(r"^" + re.escape(head) + r".*?(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(0) if m else ""


def plan_blocks(entry: str) -> list[tuple[str, str]]:
    """Each (date, block) for a plan label in `entry`; a block runs to the next bold paragraph or the entry's end."""
    out = []
    for m in PLAN_LABEL.finditer(entry):
        rest = entry[m.end():]
        stop = re.search(r"\n\s*\n\*\*", rest)
        out.append((m.group(1), rest[: stop.start()] if stop else rest))
    return out


def tsv_rows(tsv: str) -> dict[str, tuple[str, str, str]]:
    """backups.tsv's standbys: name -> (role, region, wave)."""
    rows = {}
    for line in tsv.splitlines():
        cols = line.split("|")
        if len(cols) >= 4 and STANDBY.fullmatch(cols[0].strip()):
            rows[cols[0].strip()] = (cols[1].strip(), cols[2].strip(), cols[3].strip())
    return rows


def verdict(t: dict[str, str]) -> list[str]:
    """What #986's plan record, read against the repo texts in `t`, fails to hold; empty when it holds."""
    entry = dec_entry(t["decisions"], HEAD_986)
    if not entry:
        return [f"no decisions.md entry starting {HEAD_986!r}"]
    blocks = plan_blocks(entry)
    if len(blocks) != 1:
        return [f"the #986 entry has {len(blocks)} test-plan blocks; it needs exactly one"]
    date, block = blocks[0]
    bad: list[str] = []

    # 1. The talk's date.
    start = KUBECON_START.search(flat(t["ros"]))
    if not start:
        bad.append("the run-of-show no longer gives the KubeCon start the plan is dated against")
    elif date != start.group(1):
        bad.append(f"the plan is for before the talk on {date}, but the KubeCon start is {start.group(1)}")
    entry_date = HEAD_986.split(" · ")[0].removeprefix("## ")
    if not entry_date < date:
        bad.append(f"the entry, dated {entry_date}, is not before the talk on {date}")

    # 2. The items.
    items = [(int(m.group(1)), m.group(2).strip(), flat(m.group(3))) for m in ITEM.finditer(block)]
    numbers = [n for n, _, _ in items]
    if numbers != list(range(1, len(items) + 1)):
        bad.append(f"the plan's items are numbered {numbers}, not 1, 2, 3, ... in order")
    by_label = {}
    for need in NEEDED_ITEMS:
        hits = [body for _, label, body in items if label.startswith(need)]
        if len(hits) != 1:
            bad.append(f"the plan has {len(hits)} items labelled {need!r}; it needs one")
        by_label[need] = hits[0] if hits else ""

    # 3. What is tested: the failover, the Watcher promoting, a KubeCon-profile cluster after.
    for need in TESTED_NEEDS:
        if need not in by_label["What is tested"]:
            bad.append(f"'What is tested' does not name {need!r}")

    # 4. How a standby is built, and no lifecycle touched on the ruling.
    clusters = by_label["Which clusters"]
    for need in BUILD_NEEDS + NO_LIFECYCLE_NEEDS:
        if need not in clusters:
            bad.append(f"'Which clusters' does not say {need!r}")
    claude = flat(t["claude"])
    if RULING_CLAUDE not in claude:
        bad.append(f"CLAUDE.md does not record {RULING_CLAUDE!r}, the ruling the plan cites")
    if NO_RUN_LIFECYCLE_CLAUDE not in claude:
        bad.append(f"CLAUDE.md does not say {NO_RUN_LIFECYCLE_CLAUDE!r}, what the ruling gives runs")
    if FLEET_KUBECON not in t["fleet"]:
        bad.append("fleet.sh's bootstrap_profile_for_role no longer maps kubecon:community to kubecon-community")
    if EVENT_DEFAULT not in t["event"]:
        bad.append("event.sh no longer defaults WIB_ROSTER_PROFILES to kubecon")
    for need in BACKUPS_NEEDS:
        if need not in t["backups"]:
            bad.append(f"backups.py no longer has {need!r}, which the plan's build or promotion names")
    for need in TEST_BACKUPS_NEEDS:
        if need not in t["test_backups"]:
            bad.append(f"verify/test_backups.py no longer checks {need!r} for every standby")

    # 5. Which standby is really built, by whom, and nothing else named or run.
    standbys_item = by_label["The real standbys"]
    named = sorted(set(STANDBY.findall(standbys_item)))
    elsewhere = sorted(set(STANDBY.findall(block)) - set(named))
    if not named:
        bad.append("'The real standbys' names no standby cluster")
    if elsewhere:
        bad.append(f"the plan names standby {', '.join(elsewhere)} outside 'The real standbys'")
    for need in STANDBYS_NEEDS:
        if need not in standbys_item:
            bad.append(f"'The real standbys' does not say {need!r}")
    rows = tsv_rows(t["tsv"])
    step = REHEARSAL_STEP.search(t["ros"])
    if not step:
        bad.append("the run-of-show has no step 3, '**Rehearsal, once**', for the standby to belong to")
    for name in named:
        if name not in rows:
            bad.append(f"the plan's standby {name} is not a backups.tsv row")
            continue
        _, region, wave = rows[name]
        if f"`{name}` in {region}" not in standbys_item:
            bad.append(f"the plan does not give {name} in its backups.tsv region, {region}")
        if step and f"--standby {name}" not in step.group(0):
            bad.append(f"the run-of-show's rehearsal step does not run the attendee's drill against {name}")
        if step and f"backups.py up {wave}" not in step.group(0):
            bad.append(f"the run-of-show's rehearsal step does not build {name}'s wave, {wave}")
    for cmd in LIFECYCLE_COMMANDS:
        if cmd in flat(block):
            bad.append(f"the plan carries the lifecycle command {cmd!r}")
    return bad


# ---- the record as it stands ----
for key, lit in (("decisions", HEAD_986), ("decisions", "**The test plan, for before the talk on 2026-11-12.**"),
                 ("ros", "3. **Rehearsal, once**"), ("ros", "4. **Install the KubeCon schedule:**")):
    anchor(REAL[key], lit, FILES[key])
ENTRY = dec_entry(REAL["decisions"], HEAD_986)
BLOCK = plan_blocks(ENTRY)[0][1]

print("== #986's decisions.md entry records the KubeCon failover test plan, read against the repo ==")
problems = verdict(REAL)
check("the plan is there, says how a KubeCon standby is built and promoted, and touches no cluster lifecycle",
      not problems, "; ".join(problems))
for n in sorted(set(STANDBY.findall(BLOCK))):
    print(f"        the plan's one real standby: {n} {tsv_rows(REAL['tsv']).get(n)}")


def with_(key: str, old: str, new: str, *, in_block: bool = False) -> dict[str, str]:
    """The repo texts with `old` replaced once by `new` in `key` (inside the plan block only, when `in_block`)."""
    t = dict(REAL)
    if in_block:
        flat_block = flat(BLOCK)
        anchor(flat_block, old, "decisions.md #986 test-plan block")
        # Reflow the block so a phrase wrapped across lines is cut whole; ITEM still splits it, on "N. *".
        reflowed = re.sub(r"\s+(?=\d+\. \*)", "\n", flat_block).replace(old, new, 1)
        t["decisions"] = REAL["decisions"].replace(BLOCK, "\n\n" + reflowed, 1)
        return t
    anchor(flat(REAL[key]) if key == "claude" else REAL[key], old, FILES[key])
    t[key] = (flat(REAL[key]) if key == "claude" else REAL[key]).replace(old, new, 1)
    return t


def refused(name: str, t: dict[str, str]) -> None:
    check(name, bool(verdict(t)), "the verdict still held")


print("== the reflowed block alone still holds, so each cut below is read on the cut alone ==")
check("the plan reflowed onto one line per item still holds", not verdict(with_("decisions", "", "", in_block=True)),
      "; ".join(verdict(with_("decisions", "", "", in_block=True))))

print("== each cut of the real record, or of a source it reads, is refused ==")
P = "**The test plan, for before the talk on 2026-11-12.**"
refused("with the #986 heading struck, the entry is not found",
        with_("decisions", HEAD_986, "## 2026-11-06 · #000 · struck"))
refused("with the plan's label struck, there is no plan", with_("decisions", P, "**A plan.**"))
refused("with the plan's label doubled, the record is ambiguous", with_("decisions", P, P + "\n\n" + P + "\n\n1. *x*"))
refused("with the plan dated after the talk, it is refused",
        with_("decisions", P, P.replace("2026-11-12", "2026-11-13")))
refused("with the run-of-show's KubeCon start moved, the plan's date no longer matches",
        with_("ros", "The KubeCon start is 2026-11-12", "The KubeCon start is 2026-11-19"))
refused("with an item number skipped, it is refused", with_("decisions", "3. *The live router", "7. *The live router",
                                                             in_block=True))
for label in NEEDED_ITEMS:
    refused(f"with the {label!r} item relabelled, it is refused",
            with_("decisions", f"*{label}", "*Something else", in_block=True))
for need in TESTED_NEEDS:
    refused(f"with {need!r} struck from 'What is tested', it is refused",
            with_("decisions", need, "it", in_block=True))
for need in BUILD_NEEDS:
    refused(f"with {need!r} struck from 'Which clusters', how a standby is built is not said",
            with_("decisions", need, "a script", in_block=True))
refused("with a cluster created and torn down, it is refused",
        with_("decisions", "No cluster is created or torn down.", "A cluster is created and torn down.", in_block=True))
refused("with a run building a standby, it is refused",
        with_("decisions", "no run builds a standby", "this run builds a standby", in_block=True))
refused("with the clusters changed, it is refused",
        with_("decisions", "Neither cluster is changed", "Both clusters are changed", in_block=True))
refused("with the ruling's date wrong, it is refused",
        with_("decisions", "ruling of 2026-11-02", "ruling of 2026-11-03", in_block=True))
refused("with the ruling's issue struck, it is refused", with_("decisions", "(#809, hecaton#496)", "(#809)",
                                                               in_block=True))
refused("with CLAUDE.md no longer recording the ruling, the citation has no source",
        with_("claude", RULING_CLAUDE, "Michael's ruling of 2026-11-09 (hecaton#496, #809)"))
refused("with CLAUDE.md letting a run build clusters, the ruling no longer covers the plan",
        with_("claude", NO_RUN_LIFECYCLE_CLAUDE, "A run may create a cluster"))
refused("with fleet.sh giving a community standby the burn profile, the build is not KubeCon's",
        with_("fleet", FLEET_KUBECON, "kubecon:community) printf 'burn'"))
refused("with event.sh defaulting to the workshop profiles, the build is not KubeCon's",
        with_("event", EVENT_DEFAULT, EVENT_DEFAULT.replace(":-kubecon", ":-workshop")))
for need in BACKUPS_NEEDS:
    refused(f"with backups.py's {need!r} gone, the plan's build or promotion has no code",
            with_("backups", need, "# struck"))
for need in TEST_BACKUPS_NEEDS:
    refused(f"with test_backups.py's {need!r} gone, the plan's 'holds for every standby' has no test",
            with_("test_backups", need, "None"))
refused("with the real standby not a backups.tsv row, it is refused",
        with_("decisions", "`watch-it-burn-community-b03`", "`watch-it-burn-community-b99`", in_block=True))
refused("with the real standby in the wrong region, it is refused",
        with_("decisions", "`watch-it-burn-community-b03` in us-west-2", "`watch-it-burn-community-b03` in us-east-1",
              in_block=True))
refused("with no standby named in 'The real standbys', it is refused",
        with_("decisions", "`watch-it-burn-community-b03` in us-west-2", "a standby", in_block=True))
refused("with a second standby named outside 'The real standbys', it is refused",
        with_("decisions", "no run builds a standby", "no run builds a standby but watch-it-burn-private-b03",
              in_block=True))
for need in STANDBYS_NEEDS:
    refused(f"with {need!r} struck from 'The real standbys', it is refused",
            with_("decisions", need, "a run", in_block=True))
refused("with the rehearsal step's drill run against another standby, it is refused",
        with_("ros", "--standby watch-it-burn-community-b03", "--standby watch-it-burn-community-b04"))
refused("with the rehearsal step not building the standby's wave, it is refused",
        with_("ros", "   infra/terraform/fleet/backups.py up night-before\n", "\n"))
refused("with a cluster-create command in the plan, it is refused",
        with_("decisions", "No cluster is created or torn down.",
              "No cluster is created or torn down. Then `eksctl create cluster`.", in_block=True))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#986's test-plan record holds: the KubeCon failover plan, the standby's build and promotion, no lifecycle "
      "touched.")
