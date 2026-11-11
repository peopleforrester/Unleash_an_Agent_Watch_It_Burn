# ABOUTME: Reads rounds-agenticburn#171 and #1346 with gh's token and checks #171 maps each deck DO note's old switch
# ABOUTME: to its guardrails-<name> replacement, and a comment on #1346 links #171 (#1352's criterion, #1365).
# SUITE: e2e (needs the network and gh with a token: `gh issue view` is asked for both issues' comments)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. #1352 renamed the stage switches on the presenter pages, and one of its criteria is that the deck side is
# mapped for the deck's own repo: "rounds-agenticburn#171 lists each deck DO note's old switch with its
# guardrails-<name> replacement, and a comment on #1346 links it". The deck lives in rounds-agenticburn, so no file
# here holds that mapping; the comments are the work, and run 20474's test review found nothing read them (#1365).
#
# The deck's DO notes. Run 20473 read them from rounds-agenticburn main 4627d95 (attendee.html, 127 slides) and
# recorded them in decisions.md's #1352 entry: four notes name a switch. DECK_NOTES below is that record, and this test
# first checks decisions.md still says each pair, so the two cannot drift apart. It does not read the live deck: once
# the deck is renamed its DO notes name only the new switches, and the mapping is of the deck as it was.
#
# Each replacement is checked against the rename rule #1350 made (guardrails-on/off is guardrails-k8s-on/off,
# guards-on/off is guardrails-ai-on/off, guard-<name>-on/off is guardrails-<name>-on/off), not against the terminal's
# ALIASES table, which #1363 removes after the talk on 2026-11-12.
#
# Then the comment: one comment on #171, by Michael or hecaton, has a table row for each slide hash whose old cell
# names each old switch and whose new cell names its replacement, in the same order, and names the deck commit it was
# read from. And one comment on #1346, by Michael or hecaton, links the mapping: the mapping comment's URL, or #171
# with its DO notes and each slide hash (a run report there names #171 in passing, which is not the link).
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
import gh_comments  # noqa: E402

DECISIONS = REPO / "decisions.md"
DECK_ISSUE = "peopleforrester/rounds-agenticburn#171"
LINK_ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#1346"
# Who may post the mapping and the link: the repo's owner, and the dispatcher that posts for runs.
# gh issue view reads them through GraphQL, which names the hecatongithub app's bot without REST's "[bot]".
AUTHORS = {"hecatongithub", "peopleforrester"}
# The rounds-agenticburn commit the DO notes were read from (decisions.md, #1352).
DECK_COMMIT = "4627d95"
# Slide hash -> the DO note's old switches, in the order the note types them, each with its replacement.
DECK_NOTES: dict[str, list[tuple[str, str]]] = {
    "#/27": [("guardrails-on", "guardrails-k8s-on")],
    "#/52": [("guard-agency-on", "guardrails-agency-on"), ("guard-input-on", "guardrails-input-on")],
    "#/74": [("guard-mcp-on", "guardrails-mcp-on")],
    "#/121": [("guard-topic-on", "guardrails-topic-on")],
}
ENTRY_HEAD = "## 2026-11-11 · #1352 · run 20473 ·"
NOTES_HEAD = "**The deck's DO notes.**"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def renamed(old: str) -> str:
    """#1350's rename rule: the guardrails-<name> form of an old switch name, or "" when it is not one."""
    m = re.fullmatch(r"guardrails-(on|off)", old)
    if m:
        return f"guardrails-k8s-{m.group(1)}"
    m = re.fullmatch(r"guards-(on|off)", old)
    if m:
        return f"guardrails-ai-{m.group(1)}"
    if old == "guards-status":
        return "guardrails-status"
    m = re.fullmatch(r"guard-([a-z0-9]+)-(on|off)", old)
    return f"guardrails-{m.group(1)}-{m.group(2)}" if m else ""


OLD_SWITCH = re.compile(r"`(guardrails-o(?:n|ff)|guards-(?:on|off|status)|guard-[a-z0-9]+-o(?:n|ff))`")
NEW_SWITCH = re.compile(r"`(guardrails-[a-z0-9]+-o(?:n|ff)|guardrails-status)`")

print("== the record of the deck's DO notes ==")
for slide, pairs in DECK_NOTES.items():
    for old, new in pairs:
        check(f"{slide}: {new} is {old}'s guardrails-<name> form by #1350's rule", renamed(old) == new,
              f"the rule gives {renamed(old)!r}")

text = DECISIONS.read_text(encoding="utf-8")
if ENTRY_HEAD not in text:
    sys.exit(f"ANCHOR MISSING: {ENTRY_HEAD!r} in {DECISIONS.relative_to(REPO)}")
entry = text.split(ENTRY_HEAD, 1)[1].split("\n## ", 1)[0]
if NOTES_HEAD not in entry:
    sys.exit(f"ANCHOR MISSING: {NOTES_HEAD!r} in the #1352 entry of {DECISIONS.relative_to(REPO)}")
notes = flat(entry.split(NOTES_HEAD, 1)[1].split("\n\n", 1)[0])
check(f"decisions.md's #1352 entry read the DO notes from rounds-agenticburn {DECK_COMMIT}", DECK_COMMIT in notes)
# The paragraph gives each slide as "`#/N` (...) `old` to `new` and `old` to `new`;", up to the next slide hash.
recorded: dict[str, list[tuple[str, str]]] = {}
for part in re.split(r"(?=`#/\d+`)", notes):
    m = re.match(r"`(#/\d+)`", part)
    if m:
        recorded[m.group(1)] = re.findall(r"`([a-z0-9-]+)` to `([a-z0-9-]+)`", part.split(". ", 1)[0])
check("decisions.md's #1352 entry records the same DO notes, old switch to new, as this test",
      recorded == DECK_NOTES, f"recorded {recorded}")


def table_rows(body: str) -> dict[str, list[str]]:
    """Each markdown table row whose first cell is a backticked slide hash, as its cells, keyed by the hash."""
    rows: dict[str, list[str]] = {}
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.match(r"`(#/\d+)`", cells[0]) if line.lstrip().startswith("|") else None
        if m and len(cells) >= 3:
            rows[m.group(1)] = cells
    return rows


def maps_every_note(body: str) -> list[str]:
    """Why this comment does not map every DO note, or [] when it does: a row per slide hash whose next-to-last cell
    names the note's old switches and whose last cell names their replacements, in order, and no row that names an
    old switch without its replacement. The comment names the deck commit it read."""
    why: list[str] = []
    rows = table_rows(body)
    for slide, pairs in DECK_NOTES.items():
        cells = rows.get(slide)
        if not cells:
            why.append(f"no table row for {slide}")
            continue
        olds = OLD_SWITCH.findall(cells[-2])
        news = NEW_SWITCH.findall(cells[-1])
        if olds != [o for o, _ in pairs]:
            why.append(f"{slide}'s old cell names {olds}, not {[o for o, _ in pairs]}")
        if news != [n for _, n in pairs]:
            why.append(f"{slide}'s new cell names {news}, not {[n for _, n in pairs]}")
    for slide, cells in rows.items():
        if slide in DECK_NOTES:
            continue
        olds = OLD_SWITCH.findall(cells[-2])
        news = NEW_SWITCH.findall(cells[-1])
        if [renamed(o) for o in olds] != news:
            why.append(f"{slide}'s row names {olds} with {news}, not each old switch's replacement")
    if DECK_COMMIT not in body:
        why.append(f"it does not name the deck commit {DECK_COMMIT} it was read from")
    return why


print(f"== a comment on {DECK_ISSUE} maps each DO note's old switch to its replacement ==")
owner_repo, _, number = DECK_ISSUE.partition("#")
read = gh_comments.read(owner_repo, number)
gh_comments.check_read(read, DECK_ISSUE, check)
ours = [c for c in read.comments if c["login"] in AUTHORS]
if read.comments:
    check(f"at least one comment is by {' or '.join(sorted(AUTHORS))}", bool(ours),
          ", ".join(sorted({c["login"] for c in read.comments})))
mapping: list[str] = []
if ours:
    verdicts = [(c["url"], maps_every_note(c["body"])) for c in ours]
    mapping = [url for url, why in verdicts if not why]
    nearest = min((why for _, why in verdicts), key=len)
    check(f"one comment has a table row for each of the {len(DECK_NOTES)} DO notes "
          f"({', '.join(DECK_NOTES)}), each old switch with its guardrails-<name> replacement, read from "
          f"{DECK_COMMIT}", bool(mapping), "; ".join(nearest))
    if mapping:
        print(f"  the mapping is at {mapping[0]}")

print(f"== a comment on {LINK_ISSUE} links {DECK_ISSUE} ==")
owner_repo, _, number = LINK_ISSUE.partition("#")
read = gh_comments.read(owner_repo, number)
gh_comments.check_read(read, LINK_ISSUE, check)
ours = [c for c in read.comments if c["login"] in AUTHORS]
if read.comments:
    check(f"at least one comment is by {' or '.join(sorted(AUTHORS))}", bool(ours),
          ", ".join(sorted({c["login"] for c in read.comments})))
LINK = re.compile(r"peopleforrester/rounds-agenticburn(?:#|/issues/)171(?!\d)")


def links_mapping(body: str) -> bool:
    """The comment points to the mapping: it gives the mapping comment's own URL, or it names #171 (or its URL), the
    DO notes, and each of their slide hashes, so a passing mention of #171 in another comment does not count."""
    if any(url in body for url in mapping):
        return True
    return (bool(LINK.search(body)) and "do note" in flat(body).lower()
            and all(f"`{slide}`" in body for slide in DECK_NOTES))


if ours:
    links = [c["url"] for c in ours if links_mapping(c["body"])]
    check(f"a comment links {DECK_ISSUE} (or the mapping comment's URL) as where each of the {len(DECK_NOTES)} "
          "DO notes is mapped", bool(links))
    if links:
        print(f"  the link is at {links[0]}")

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All rounds-agenticburn#171 DO note mapping checks passed.")
