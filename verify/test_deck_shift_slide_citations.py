# ABOUTME: Holds #1099: the run-of-show says its slides count from 1 and the deck's URL hash is one less, and no file
# ABOUTME: under facilitation/, challenges/ or verify/ cites slides 44 to 64 or hash #/43 on outside segment 4's own text.
"""The 14-place deck shift of 2026-11-07, held across the run-of-show and the three directories (#1099, from #1076).

rounds-agenticburn#82 and #93 replaced the old seven Challenge 3 slides with twenty-one, so every slide from live
`#/50` on (Challenge 4 and the close) moved 14 places: live `#/50` is now `#/64`. The deck's URL hash counts from 0
and the run-of-show from 1, so Challenge 3 is now the run-of-show's slides 44 to 64 (`#/43` to `#/63`) and Challenge 4
starts at slide 65. A number in 44 to 64, or a hash of `#/43` or more, is therefore either a citation of the new
Challenge 3, which is segment 4's alone, or a number left over from the old deck: the old Challenge 3 was 44 to 50,
the old Challenge 4 and close 51 on. This test holds:

  1. The run-of-show's "The segments, in order" section opens, before its first numbered step and its table, on one
     line saying slide numbers count from 1 and the deck's URL hash is one less.
  2. Every file git tracks or would track under `facilitation/`, `challenges/` and `verify/`, read with backticks
     and `*` blanked and whitespace flattened, cites no slide number in 44 to 64 after "slide" or "slides" (each
     number of a list or range: "slides 20 and 25 to 27") and no hash `#/N` with N of 43 or more, except in the
     run-of-show's segment 4 (`### Segment 4:` to `### Segment 5:`) and its segments-table row 4, in the Night Before
     step "Seed the stage's Datadog traces", which names the slide that opens each challenge's trace (#1139), and in SEG4_READERS,
     the tests that hold segment 4 to the deck, and the numbering line itself. Numbers of 65 or more after "slide" pass: they are the shifted ones.
     This test's own docstring and fixtures name the forms it bans, so it is the one file the search leaves out.

Numbers up to 43 point at segments 1 to 3, which the shift did not move, and pass. The self-checks show a stale
citation planted in segment 5, in another file and in a hash is found, and the current wording passes.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DIRS = ("facilitation", "challenges", "verify")
ROS_REL = "facilitation/kubecon-na-2026-run-of-show.md"
SEGMENTS = "## The segments, in order (30 minutes)"
FIRST_STEP = "1. **Challenge slide:**"
TABLE = "| # | Min | Who | On screen | The room | Abstract points |"
NUMBERING = ("Slide numbers in this file count from 1, the title slide being slide 1; the deck's URL hash counts from 0 "
             "and is one less, so slide 44 is #/43 at https://rounds.agenticburn.com.")
LINE_START = "Slide numbers in this file count from 1"
SEG4, SEG5, SEG6, ROW4, ROW5 = "### Segment 4:", "### Segment 5:", "### Segment 6:", "| 4 | 7 |", "| 5 | 5 |"
# Since #1141, segment 5 and its row cite rounds-agenticburn#102's Challenge 4 by hash (#/62 to #/72), so the cut
# runs from segment 4 to segment 6 and drops rows 4 and 5.
# The tests that hold segment 4's slides to the 2026-11-07 deck, and so quote its numbers: the run-of-show's (#1098)
# and the /kubecon page's (#1100); and the one that holds the stage-trace seeds to the notes of the slides that open
# Challenge 3's and Challenge 4's traces, #/48 and #/68 (#1138); and the one that holds segment 4's desk lines, which
# quote what #/46 and #/47's "deploy" open (#1160); and the one that holds the Night Before seed step to its four
# Datadog links, #/48 and #/68 among them, and fails on #/65 there (#1205).
SEG4_READERS = {"verify/test_ros_seg4_flow.py", "verify/test_kubecon_seg4_flow.py", "verify/test_stage_trace_slides.py",
                "verify/test_support_desk_named.py", "verify/test_ros_seed_step_links.py"}
LOW, HIGH = 44, 64  # the new Challenge 3, which the old deck's Challenge 3, Challenge 4 and close numbers land in
HASH_FROM = 43      # #/43 is slide 44
# The Night Before step that names each challenge's Datadog link by hash, #/48 and #/68 among them (#1139), from its
# first words to the next step's.
SEED_STEP, NEXT_STEP = "- [ ] **Seed the stage's Datadog traces", "\n- [ ] **"

S = "slide"
NUM = r"(?:#/)?\d+"
SEP = r"\s*(?:,|and|to|through|-|–)\s*"
CITE = re.compile(rf"\b{S}s?\s+((?:{NUM})(?:{SEP}{NUM})*)", re.IGNORECASE)
HASH = re.compile(r"#/(\d+)")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def flat(text: str) -> str:
    return " ".join(text.replace("`", "").replace("*", "").split())


def need(text: str, literal: str, where: str) -> None:
    if literal not in text:
        sys.exit(f"test_deck_shift_slide_citations.py: {where} no longer holds the literal {literal!r}; "
                 "the anchor moved, so update this test with the text")


def hits(text: str) -> list[str]:
    """Each stale-looking citation in `text`: a slide number in LOW..HIGH, or a hash of HASH_FROM or more."""
    t = flat(text)
    out = []
    for m in CITE.finditer(t):
        for n in re.findall(r"(?:#/)?(\d+)", m.group(1)):
            if LOW <= int(n) <= HIGH:
                out.append(t[max(0, m.start() - 30):m.end() + 10])
                break
    for m in HASH.finditer(t):
        if int(m.group(1)) >= HASH_FROM:
            out.append(t[max(0, m.start() - 40):m.end() + 10])
    return out


def ros_outside_seg4(ros: str) -> str:
    """The run-of-show with segments 4 and 5, the segments table's rows 4 and 5 and the seed step cut out."""
    need(ros, SEG4, ROS_REL)
    need(ros, SEED_STEP, ROS_REL)
    i = ros.index(SEED_STEP)
    need(ros[i + 1:], NEXT_STEP, f"{ROS_REL} after {SEED_STEP!r}")
    ros = ros[:i] + ros[ros.index(NEXT_STEP, i) + 1:]
    need(ros, SEG6, ROS_REL)
    head, rest = ros.split(SEG4, 1)
    tail = rest.split(SEG6, 1)[1]
    need(head, LINE_START, ROS_REL)
    i = head.index(LINE_START)
    head = head[:i] + head[head.index("\n\n", i):]
    lines = [ln for ln in (head + "\n" + SEG6 + tail).splitlines() if not ln.startswith((ROW4, ROW5))]
    return "\n".join(lines)


def numbering_ok(ros: str) -> tuple[bool, str]:
    need(ros, SEGMENTS, ROS_REL)
    section = ros.split(SEGMENTS, 1)[1]
    cut = min(i for i in (section.find(FIRST_STEP), section.find(TABLE)) if i >= 0)
    lead = flat(section[:cut])
    if NUMBERING not in lead:
        return False, "the segments section does not open on the numbering line before its first step and table"
    return True, ""


def tree_files() -> list[str]:
    res = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                          "--", *DIRS], capture_output=True, check=False)
    if res.returncode != 0:
        sys.exit(f"git ls-files failed in {REPO}: {res.stderr.decode(errors='replace').strip()}")
    return sorted(p for p in set(res.stdout.decode().split("\0")) if p and (REPO / p).is_file())


def read_text(rel: str) -> str | None:
    data = (REPO / rel).read_bytes()
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def scan(texts: dict[str, str], me: str) -> list[str]:
    out = []
    for rel, text in texts.items():
        if rel == me or rel in SEG4_READERS:
            continue
        body = ros_outside_seg4(text) if rel == ROS_REL else text
        out += [f"{rel}: {h!r}" for h in hits(body)]
    return out


ros = (REPO / ROS_REL).read_text(encoding="utf-8")
need(ros, FIRST_STEP, ROS_REL)
need(ros, TABLE, ROS_REL)

print("== the run-of-show says which numbering it uses (#1099) ==")
ok, why = numbering_ok(ros)
check("the segments section opens on: slides count from 1, the deck's URL hash is one less", ok, why)

print("== no file cites the old deck's slides 44 on, outside segment 4 (#1099) ==")
files = tree_files()
for d in DIRS:
    check(f"the search reads files under {d}/", any(f.startswith(d + "/") for f in files))
me = str(pathlib.Path(__file__).resolve().relative_to(REPO))
check("this test, the one file the search leaves out, is in it", me in files)
check("the run-of-show is in the search", ROS_REL in files)
for r in SEG4_READERS:
    check(f"{r}, a segment 4 reader the search leaves out, is still in the tree", r in files)
texts = {f: t for f in files if (t := read_text(f)) is not None}
found = scan(texts, me)
for f in found:
    print("  " + f)
check("no slide number 44 to 64 and no hash #/43 or more outside segments 4 and 5 and their readers", not found)
check("segments 4 and 5 cite the new deck by hash, so cutting them is what makes the run-of-show pass",
      bool(hits(ros)) and not hits(ros_outside_seg4(ros)))

print("== each check can fail ==")
need(ros, FIRST_STEP, ROS_REL)
no_line = ros.replace(ros[ros.index(LINE_START):ros.index("Four challenges,")], "", 1)
check("with the numbering line removed, the numbering check fails", not numbering_ok(no_line)[0])
moved = no_line.replace(TABLE, ros[ros.index(LINE_START):ros.index("Four challenges,")] + TABLE, 1)
check("with the numbering line moved below the first step, the numbering check fails", not numbering_ok(moved)[0])
need(ros, SEG6 + " The OWASP close", ROS_REL)
planted = ros.replace(SEG6 + " The OWASP close", SEG6 + " The OWASP close (slide 51)", 1)
check("a pre-shift number planted in segment 6 is found",
      bool(scan({ROS_REL: planted}, me)))
seed_end = ros.index(NEXT_STEP, ros.index(SEED_STEP)) + 1
after_seed = ros[:seed_end] + "- [ ] **Open the deck at #/50 first.**\n" + ros[seed_end:]
check("a stale hash planted in the Night Before step after the seed step is found",
      bool(scan({ROS_REL: after_seed}, me)))
check("the seed step cites the Challenge 3 and 4 links by hash, so cutting it is what makes it pass",
      bool(hits(ros[ros.index(SEED_STEP):seed_end])))
stale = {
    "an old Challenge 3 range": f"the support ticket on {S}s 44 to 50",
    "a pre-shift close slide": f"the close {S} (see {S} 58) links the vetting guide",
    "a number in a list": f"{S}s 20 and 55",
    "an old Challenge 4 hash": "open the deck at #/50 for Challenge 4",
    "a bolded, wrapped citation": f"**{S.capitalize()}\n  52**",
}
for name, text in stale.items():
    check(f"{name} is flagged", bool(scan({"facilitation/x.md": text}, me)))
current = {
    "segment 3's guardrail sets": f"one set per guardrail on {S}s 30 to 42",
    "segment 3's hand-off": f"{S} #/42's note, said on its one heading",
    "AI guardrails": f"so \"AI guardrails\" is {S} 43",
    "a shifted Challenge 4 number": f"Challenge 4 opens on {S} 65",
}
for name, text in current.items():
    hit = scan({"facilitation/x.md": text}, me)
    check(f"{name} passes", not hit, str(hit))

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll #1099 deck-shift slide citation checks passed.")
