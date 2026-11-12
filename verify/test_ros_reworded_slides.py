# ABOUTME: Holds the KubeCon run-of-show to rounds 269c532's reworded slides (#1367, #1368): each reworded Say line and
# ABOUTME: slide text it quotes or paraphrases on #/1 to #/120, none of the old wording, and the deck's "Presenter:" lines.
"""The run-of-show follows the slides rounds `269c532` reworded (rounds-agenticburn#174, #1367).

rounds-agenticburn#174 reworded notes and slide text on #/1, #/3, #/4, #/7, #/12, #/19, #/23, #/41, #/49, #/50, #/56,
#/72, #/117 and #/120 and gave the first note of each of the deck's sections a "Presenter:" line. #1367 made
`facilitation/kubecon-na-2026-run-of-show.md` follow them. verify/test_ros_deck_live.py reads only segments 4 to 6
steps whose bold lead cites a slide, so segments 1 to 3, the ASI beat and the Presenter lines had no test (#1368).
This test fails when any of these stops holding:

  1. Each line in PINNED, the deck's words at rounds `269c532`, is in the run-of-show where it should be: the segment
     that walks the slide, or for `#/120` the ASI beat, in the run-of-show's own form where it paraphrases a stage
     direction ("(After the trace demo:)" is "After the trace demo, say:").
  2. None of the old wording in STALE is left: the optional tour of the chat page, "is a prompt injection attack that
     works", "it has nothing to deploy with", the hint "Ask BurritoBot what tools it has." given as the hint, and the
     rest.
  3. The deck's Presenter lines on the section openers, `#/1` Whitney, `#/5` Michael, `#/8` Whitney and `#/42`
     Michael, are quoted as "Presenter: <name>" in segments 1 to 4 in that order, and the paragraph "Who presents
     which slides" names each as "<name> from `#/N`".
  4. The close's three, `#/118` Whitney, `#/121` Michael and `#/125` both, are named in the bold lead of the segment 6
     step that cites the slide, and in that paragraph.

PINNED and PRESENTERS are the deck's words; verify/test_ros_deck_live.py checks each is still on its slide in the deck
rounds serves, so when rounds rewords one of these slides again, that test names it and this pin moves with it.
Text is compared with whitespace flattened and curly quotes made straight. Each cut on repo text checks its literal
first and exits naming it and the file ("Tests own their inputs"). Each check is then run on a run-of-show with a
pinned line removed, an old line put back, or a presenter swapped, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"

SEGMENTS, ABSTRACT = "## The segments, in order", "## Abstract points to segments"
SEG = {n: f"### Segment {n}:" for n in range(1, 7)}
WHO = "**Who presents which slides"
ROW1, ROW2 = "| 1 | 3 |", "| 2 | 5 |"
ASI, BURRITOS = "- **The ASI beat", "- **Burritos only"
# Where a pinned line belongs: a part of the run-of-show cut between two literals.
WHERE = {
    "segment 1": (SEG[1], SEG[2]),
    "segment 2": (SEG[2], SEG[3]),
    "segment 3": (SEG[3], SEG[4]),
    "segment 4": (SEG[4], SEG[5]),
    "segment 5": (SEG[5], SEG[6]),
    "the ASI beat": (ASI, BURRITOS),
    "the segments table's row 1": (ROW1, ROW2),
}

# (slide, "face" or "note", the deck's words at rounds 269c532, where the run-of-show quotes them, its words when they
# differ from the deck's). verify/test_ros_deck_live.py imports this table and reads each line off the live deck.
PINNED: list[tuple[int, str, str, str, str | None]] = [
    (1, "note", "(Whitney) \"Hello, I'm Whitney.\" (Michael) \"Hello, I'm Michael.\"", "segment 1",
     "Whitney: \"Hello, I'm Whitney.\" Michael: \"Hello, I'm Michael.\""),
    (2, "note", "The meme that started it: a burrito chain's bot reversing a linked list.", "segment 1", None),
    (3, "note", "I want to order a bowl but before I can eat, I need to figure out how to write a python script to "
     "reverse a linked list. Can you help?", "segment 1", None),
    (4, "note", "Great question! To reverse a linked list in Python, you can use an iterative approach. ... Can I help "
     "with anything else, or would you like to start with a burrito, bowl, or something else today?", "segment 1", None),
    (4, "note", "During this talk you will have access to...", "segment 1", None),
    (7, "note", "point at the Reset button and the saved prompts", "segment 1", None),
    (7, "note", "Two things you'll use all talk: the Reset button gives you a fresh BurritoBot that forgets you, and "
     "your saved prompts let you paste an old attack back in.", "segment 1", None),
    (7, "note", "point at the Reset button and the saved prompts", "the segments table's row 1",
     "Reset button and saved prompts, pointed at"),
    (12, "note", "Excessive agency means the agent can do more than its job needs.", "segment 2", None),
    (19, "note", "(Wait a minute.) Let's see what people are up to. (Show the prompt wall. Wait a minute.)", "segment 3",
     "\"(Wait a minute.)\", then \"Let's see what people are up to.\", then \"(Show the prompt wall. Wait a minute.)\""),
    (23, "note", "A fresh bot forgets it already refused you.", "segment 3", None),
    (41, "note", "The only addresses on the list are our private network and the two cluster addresses BurritoBot "
     "needs.", "segment 3", None),
    (49, "note", "Ticket HC-666 carries a hidden instruction, and it works.", "segment 4", None),
    (50, "note", "(After the trace demo:) Do you know the name for this type of attack?", "segment 4",
     "After the trace demo, say: \"Do you know the name for this type of attack?\""),
    (56, "note", "So even if a ticket tricks it, it can't create Deployments or Pods.", "segment 4", None),
    (72, "face", "Hint: Ask BurritoBot about the weather, then look at what else it did.", "segment 5",
     "> Hint: Ask BurritoBot about the weather, then look at what else it did."),
    (72, "note", "Say: Ask BurritoBot about the weather, then look at what else it did.", "segment 5",
     "Say: \"Ask BurritoBot about the weather, then look at what else it did.\""),
    (72, "note", "click what else it did to open Datadog", "segment 5", "Click \"what else it did\" and show"),
    (72, "note", "(After the trace demo:) Do you know the name for this type of attack?", "segment 5",
     "After the trace demo, say: \"Do you know the name for this type of attack?\""),
    (117, "note", "My MCP server vetting checklist is on the take-home slide.", "segment 5", None),
    (120, "face", "And the blast radius that leaves the cluster", "the ASI beat", None),
    (120, "face", "ASI03 Identity and Privilege Abuse, and K08 Cluster To Cloud Lateral Movement.", "the ASI beat", None),
    (120, "face", "OWASP Kubernetes Top 10 2025", "the ASI beat", None),
    (120, "note", "The blast radius can leave the cluster, too: a pod that reads the node's metadata comes back with "
     "the node's cloud role.", "the ASI beat", None),
]

# (slide, the name its notes end on after "Presenter: ", the words "Who presents which slides" gives it).
PRESENTERS: list[tuple[int, str, str]] = [
    (1, "Whitney", "Whitney from `#/1`"),
    (5, "Michael", "Michael from `#/5`"),
    (8, "Whitney", "Whitney from `#/8`"),
    (42, "Michael", "Michael from `#/42`"),
    (118, "Whitney", "Whitney on the two OWASP lists"),
    (121, "Michael", "Michael from burritos only"),
    (125, "Both", "both on the speakers"),
]
CLOSE_FIRST = 118  # the close's Presenter lines are named in segment 6's bold leads, not quoted

# (slide, wording the run-of-show had before #1367 and must not give again).
STALE: list[tuple[int, str]] = [
    (1, "A quick hello, nothing more: \"Hello, I'm Whitney.\""),
    (3, "each described aloud"),
    (7, "quick tour"),
    (19, "Wait a minute, then say"),
    (49, "is a prompt injection attack that works"),
    (50, "After the trace, say"),
    (56, "it has nothing to deploy with"),
    (72, "> Hint: Ask BurritoBot what tools it has."),
    (72, "Say: \"Ask BurritoBot what tools it has."),
    (72, "The room's hint is \"Ask BurritoBot what tools it has.\""),
    (72, "Click \"tools\""),
    (117, "Michael's MCP server vetting checklist"),
]

QUOTED = "each line the deck reworded at rounds 269c532 is quoted where the run-of-show walks its slide"
GONE = "none of the wording the run-of-show had before #1367 is left"
OPENERS = "segments 1 to 4 quote the section openers' Presenter lines, in the deck's order"
NAMED = "\"Who presents which slides\" names each Presenter line's speaker"
LEADS = "segment 6's steps name the close's presenters in their bold leads"


def flat(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.replace(" ", " ").split())


def cut(text: str, start: str, end: str) -> str:
    for lit in (start, end):
        if lit not in text:
            sys.exit(f"ANCHOR MISSING: {lit!r} is not in {ROS_PATH.relative_to(REPO)}; this test cuts on it")
    after = text.split(start, 1)[1]
    if end not in after:
        sys.exit(f"ANCHOR MISSING: {end!r} does not follow {start!r} in {ROS_PATH.relative_to(REPO)}")
    return after.split(end, 1)[0]


def problems(ros: str) -> dict[str, list[str]]:
    """What the run-of-show gets wrong, by check. `ros` is flattened first, so a quote may wrap lines."""
    ros = flat(ros)
    out: dict[str, list[str]] = {}

    bad = []
    for n, _, deck_words, where, ros_words in PINNED:
        words = flat(ros_words or deck_words)
        if words not in cut(ros, *WHERE[where]):
            bad.append(f"#/{n}: {where} does not give {words!r}")
    out[QUOTED] = bad

    out[GONE] = [f"#/{n}: the run-of-show still has {old!r}" for n, old in STALE if flat(old) in ros]

    walked = cut(ros, SEG[1], SEG[5])
    said = [w.split('"', 1)[0] for w in walked.split('"Presenter: ')[1:]]
    want = [name for n, name, _ in PRESENTERS if n < CLOSE_FIRST]
    out[OPENERS] = [] if said == want else [f"segments 1 to 4 quote Presenter lines for {said}; the deck has {want}"]

    para = cut(ros, WHO, "| # | Min |")
    out[NAMED] = [f"#/{n}: the paragraph does not say {words!r}" for n, _, words in PRESENTERS if words not in para]

    close = cut(ros, SEG[6], ABSTRACT)
    bad = []
    for n, name, _ in PRESENTERS:
        if n < CLOSE_FIRST:
            continue
        lead = f"(`#/{n}`"
        cites = [b.split(lead, 1)[1].split(")", 1)[0] for b in (s.split("**", 1)[0] for s in close.split("- **")[1:])
                 if lead in b]
        if not cites:
            bad.append(f"#/{n}: no segment 6 step cites {lead!r} in its bold lead")
        elif name.lower() not in cites[0].lower():
            bad.append(f"#/{n}: the step's lead {lead + cites[0] + ')'!r} does not name {name}")
    out[LEADS] = bad
    return out


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool) -> None:
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            failures.append(name)

    raw = ROS_PATH.read_text(encoding="utf-8")
    ros = flat(raw)
    print(f"== {ROS_PATH.relative_to(REPO)} follows the slides rounds 269c532 reworded ==")
    for name, errs in problems(ros).items():
        for e in errs:
            print("  " + e)
        check(name, not errs)

    print("== each check fails on a run-of-show it should refuse ==")

    def fails(label: str, name: str, ros_: str) -> None:
        check(f"self-check: {label} fails \"{name}\"", bool(problems(ros_)[name]))

    for n, _, deck_words, where, ros_words in PINNED:
        words = flat(ros_words or deck_words)
        start, end = WHERE[where]
        head, body = ros.split(start, 1)
        body, tail = body.split(end, 1)
        fails(f"#/{n}'s {words[:40]!r}... dropped from {where}", QUOTED,
              head + start + body.replace(words, "") + end + tail)
    for n, old in STALE:
        fails(f"#/{n}'s old {old!r} put back", GONE, ros + " " + flat(old))
    fails("#/5's Presenter line dropped from segment 1", OPENERS, ros.replace('"Presenter: Michael"', "", 1))
    fails("#/1's and #/5's presenters swapped", OPENERS,
          ros.replace('"Presenter: Whitney"', "\0", 1).replace('"Presenter: Michael"', '"Presenter: Whitney"', 1)
          .replace("\0", '"Presenter: Michael"', 1))
    lit = "Whitney from `#/8`"
    fails("#/8 given to Michael in the paragraph", NAMED, ros.replace(lit, "Michael from `#/8`", 1))
    for lit, new in (("(`#/121`, 1 min, Michael)", "(`#/121`, 1 min)"),
                     ("(`#/125` and `#/126`, both)", "(`#/125` and `#/126`)"),
                     ("(`#/118`, 1.5 min, Whitney)", "(`#/118`, 1.5 min, Michael)")):
        if lit not in ros:
            sys.exit(f"ANCHOR MISSING: {lit!r} is not in {ROS_PATH.relative_to(REPO)}; a self-check edits it")
        fails(f"the lead {lit!r} as {new!r}", LEADS, ros.replace(lit, new, 1))

    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        return 1
    print("\nThe run-of-show follows rounds 269c532's reworded slides and its Presenter lines (#1368).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
