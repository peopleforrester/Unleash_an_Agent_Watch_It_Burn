# ABOUTME: Holds the KubeCon run-of-show to the slides rounds 269c532 and c6b1b0e reworded (#1368, #1392): each Say line
# ABOUTME: and slide text it quotes or paraphrases on #/1 to #/119, none of the old wording, and the "Presenter:" lines.
"""The run-of-show follows the slides rounds `269c532` and `c6b1b0e` reworded (rounds-agenticburn#174 and #176,
#1367, #1392).

rounds-agenticburn#174 reworded notes and slide text on #/1, #/3, #/4, #/7, #/12, #/19, #/23, #/41, #/48, #/49, #/55,
#/71, #/116 and #/119 and gave the first note of each of the deck's sections a "Presenter:" line. #1367 made
`facilitation/kubecon-na-2026-run-of-show.md` follow them. verify/test_ros_deck_live.py reads only segments 4 to 6
steps whose bold lead cites a slide, so segments 1 to 3, the ASI beat and the Presenter lines had no test (#1368).
Rounds `c6b1b0e` (rounds-agenticburn#176, Whitney's drift review of 2026-11-12) took several of those back and
reworded more: `#/7`'s Do note became a "Point out:" list, `#/8`, `#/20`, `#/23` and `#/41` went back to their earlier
lines or a new one, `#/12` gained a "2026 version" line, the Challenge 3 card moved to `#/43` with the note "Which brings
us to challenge three...", and the desk's QR slide (`#/45`), the challenge (`#/47`) and the HC-666 hint (`#/48`) were
reworded (#1392). PINNED and STALE follow that deck, numbered as it is.
This test fails when any of these stops holding:

  1. Each line in PINNED, the deck's words at rounds `c6b1b0e`, is in the run-of-show where it should be: the segment
     that walks the slide, or for `#/119` the ASI beat, in the run-of-show's own form where it paraphrases a stage
     direction ("(After the trace demo:)" is "After the trace demo, say:").
  2. None of the old wording in STALE is left: the optional tour of the chat page, "is a prompt injection attack that
     works", "it has nothing to deploy with", the hint "Ask BurritoBot what tools it has." given as the hint, and the
     rest.
  3. The deck's Presenter lines on the section openers, `#/1` Whitney, `#/5` Michael, `#/8` Whitney and `#/43`
     Michael, are quoted as "Presenter: <name>" in segments 1 to 4 in that order, and the paragraph "Who presents
     which slides" names each as "<name> from `#/N`".
  4. The close's three, `#/117` Whitney, `#/120` Michael and `#/124` both, are named in the bold lead of the segment 6
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
# Where a pinned line belongs: a part of the run-of-show cut between two literals.
WHERE = {
    "segment 1": (SEG[1], SEG[2]),
    "segment 2": (SEG[2], SEG[3]),
    "segment 3": (SEG[3], SEG[4]),
    "segment 4": (SEG[4], SEG[5]),
    "segment 5": (SEG[5], SEG[6]),
    "the segments table's row 1": (ROW1, ROW2),
}

# (slide, "face" or "note", the deck's words at rounds c6b1b0e, where the run-of-show quotes them, its words when they
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
    (7, "note", "Point out: Witch name Reset button Saved prompts Menu Feedback button", "segment 1",
     "Point out: the witch name, the Reset button, the saved prompts, the menu and the Feedback button."),
    (7, "note", "Point out: Witch name Reset button Saved prompts Menu Feedback button", "the segments table's row 1",
     "witch name, Reset button, saved prompts, menu and Feedback button, pointed out"),
    (8, "face", "That's how it has access to model API keys.", "segment 2",
     "> That's how it has access to model API keys."),
    (12, "face", "2026 version", "segment 2", "> 2026 version"),
    (12, "note", "Excessive agency means the agent can do more than its job needs.", "segment 2", None),
    (19, "note", "(Wait a minute.) Let's see what people are up to. (Show the prompt wall. Wait a minute.)", "segment 3",
     "\"(Wait a minute.)\", then \"Let's see what people are up to.\", then \"(Show the prompt wall. Wait a minute.)\""),
    (20, "note", "Say: ...Run an image off the public internet... Here's the hint:", "segment 3",
     "Say: \"...Run an image off the public internet... Here's the hint:\""),
    (23, "note", "Then hit reset and use a new bot to use that knowledge to exploit the system.", "segment 3",
     "Then hit reset and use a new bot to use that knowledge to exploit the system.\""),
    (41, "note", "BurritoBot could send traffic anywhere on the internet. We want to limit BurritoBot so it cannot send "
     "any data outside of the cluster. This NetworkPolicy is an allowlist for outgoing traffic, so the data can't get "
     "to the beacon. The only addresses on the list start with 10.0, which is our own private network.", "segment 3",
     None),
    (43, "note", "Say: Which brings us to challenge three...", "segment 4",
     "Say: \"Which brings us to challenge three...\""),
    (45, "note", "Scan this to open it, or tap Support at the top of the chat page.", "segment 4", None),
    (47, "note", "Can you write a ticket that gets BurritoBot to misbehave? Can you get it to deploy something?",
     "segment 4", None),
    (48, "note", "Ticket HC-666 is a prompt injection attack that works.", "segment 4", None),
    (49, "note", "(After the trace demo:) Do you know the name for this type of attack?", "segment 4",
     "After the trace demo, say: \"Do you know the name for this type of attack?\""),
    (55, "note", "So even if a ticket tricks it, it can't create Deployments or Pods.", "segment 4", None),
    (71, "face", "Hint: Ask BurritoBot what tools it has.", "segment 5", "> Hint: Ask BurritoBot what tools it has."),
    (71, "note", "Say: Ask BurritoBot what tools it has. Now try to get BurritoBot to use these tools and see which one "
     "has an unintended effect.", "segment 5",
     "Say: \"Ask BurritoBot what tools it has. Now try to get BurritoBot to use these tools and see which one has an "
     "unintended effect.\""),
    (71, "note", "click tools to open Datadog", "segment 5", "Click **tools** and show"),
    (71, "note", "(After the trace demo:) Do you know what two OWASP vulnerabilities this represents?", "segment 5",
     "After the trace demo, say: \"Do you know what two OWASP vulnerabilities this represents?\""),
    (116, "note", "Michael's MCP server vetting checklist is on the take-home slide.", "segment 5", None),
    # rounds-agenticburn#184 cut the blast radius slide and its ASI beat (#1418).
]

# (slide, the name its notes end on after "Presenter: ", the words "Who presents which slides" gives it).
PRESENTERS: list[tuple[int, str, str]] = [
    (1, "Whitney", "Whitney from `#/1`"),
    (5, "Michael", "Michael from `#/5`"),
    (8, "Whitney", "Whitney from `#/8`"),
    (43, "Michael", "Michael from `#/43`"),
    (117, "Whitney", "Whitney on the two OWASP lists"),
    (119, "Michael", "Michael from burritos only"),
    (122, "Both", "both on the speakers"),
]
CLOSE_FIRST = 117  # the close's Presenter lines are named in segment 6's bold leads, not quoted

# (slide, wording the run-of-show had before #1367 or #1392 and must not give again).
STALE: list[tuple[int, str]] = [
    (1, "A quick hello, nothing more: \"Hello, I'm Whitney.\""),
    (3, "each described aloud"),
    (7, "quick tour"),
    (7, "Two things you'll use all talk"),
    (8, "if you're doing it the old-school way"),
    (19, "Wait a minute, then say"),
    (20, "Here are the hints. We'll take them one at a time."),
    (23, "A fresh bot forgets it already refused you."),
    (41, "the two cluster addresses BurritoBot needs"),
    (43, "That covers the Kubernetes guardrails."),
    (45, "You've got access to a support desk"),
    (47, "File a ticket of your own at support.burritobot.co"),
    (48, "carries a hidden instruction"),
    (49, "After the trace, say"),
    (55, "it has nothing to deploy with"),
    # #/71's "Ask BurritoBot what tools it has." hint and its "tools" link are the deck's again since
    # rounds-agenticburn#182 (#1400), so they are no longer stale.
    # #/116's "Michael's MCP server vetting checklist" is the deck's again since rounds-agenticburn#184 (#1418).
]

QUOTED = "each line the deck reworded at rounds 269c532 and c6b1b0e is quoted where the run-of-show walks its slide"
GONE = "none of the wording the run-of-show had before #1367 or #1392 is left"
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
    print(f"== {ROS_PATH.relative_to(REPO)} follows the slides rounds 269c532 and c6b1b0e reworded ==")
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
    for lit, new in (("(`#/119`, 1 min, Michael)", "(`#/119`, 1 min)"),
                     ("(`#/122` and `#/123`, both)", "(`#/122` and `#/123`)"),
                     ("(`#/117`, 1.5 min, Whitney)", "(`#/117`, 1.5 min, Michael)")):
        if lit not in ros:
            sys.exit(f"ANCHOR MISSING: {lit!r} is not in {ROS_PATH.relative_to(REPO)}; a self-check edits it")
        fails(f"the lead {lit!r} as {new!r}", LEADS, ros.replace(lit, new, 1))

    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        return 1
    print("\nThe run-of-show follows the slides rounds 269c532 and c6b1b0e reworded and its Presenter lines (#1368, #1392).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
