# ABOUTME: Holds the KubeCon run-of-show's slide citations to the deck rounds serves, read live (#1270): the count,
# ABOUTME: each `#/N` step's quoted lines and notes, each diagram note word for word, and where the close starts.
# SUITE: e2e (needs the network: https://rounds.agenticburn.com/attendee.html, the deck rounds-agenticburn serves)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The run-of-show follows the deck at https://rounds.agenticburn.com, read when the test runs (#1270).

verify/test_ros_seg4_flow.py and verify/test_kubecon_seg4_flow.py hold segments 4 and 5 to a copy of the deck, so they
stayed green while rounds-agenticburn redrew Challenge 4's diagrams and retired the appendix, and the deck went from
154 slides to 127 (rounds `f73c102` to `389c384`, 2026-11-08). This test reads the deck rounds serves instead, and
fails naming each slide the run-of-show no longer matches:

  1. Every "the deck has N slides" in `facilitation/kubecon-na-2026-run-of-show.md` gives the deck's count.
  2. Every diagram note the run-of-show quotes as `` `#/N`: "..." `` is slide N's Say note, word for word.
  3. In segments 4 to 6, every quote in a step whose bold lead cites `(`#/N`)`, `(`#/N` and `#/M`)` or
     `(`#/N` to `#/M`)` is on one of those slides, on its face or in its notes; and every quote followed at once by a
     hash, `"..." (`#/N`)`, in those segments and in the segments table, is on that slide.
  4. The steps of segments 4 and 5 cite the deck from `#/43` without a gap, and segment 6 opens on the next slide and
     runs to the deck's last.
  5. Every `"..." (#/N)` on `/kubecon` (`gitops/ai-layer/web/kubecon.html`) is on slide N.

A slide is its `<section>` in `attendee.html`, counted from 0 as the URL hash counts; its face is the text outside its
`<aside class="notes">`, and its Say note is the notes' text after "Say:", up to a "Do:" when there is one. Quotes are
compared with markup removed, whitespace flattened and curly quotes made straight. A fetch that fails exits 1 naming
the URL; nothing here skips. Run it at the Night Before (the step "The run-of-show still matches the deck") and in the
tools tier. Each check is run again on a copy of the deck with a slide inserted, a note reworded or the close moved,
and on a run-of-show with a quote reworded, so a check that could never fail shows up here.
"""
from __future__ import annotations

import html
import pathlib
import re
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
PAGE_PATH = REPO / "gitops/ai-layer/web/kubecon.html"
DECK_URL = "https://rounds.agenticburn.com/attendee.html"
SLIDES_OPEN = '<div class="slides">'
SEGMENTS, ABSTRACT = "## The segments, in order", "## Abstract points to segments"
SEG4, SEG5, SEG6 = "### Segment 4:", "### Segment 5:", "### Segment 6:"
ROWS = ("| 4 | 7 |", "| 5 | 5 |", "| 6 | 5 |")
PAGE_SEG4, PAGE_SEG6 = "<!-- SEGMENT 4:", "<!-- SEGMENT 6:"
FIRST = 43  # segment 4's first slide, the support desk
# The checks, by name, so a self-check names the one it expects to fail.
COUNTED = "every \"the deck has N slides\" gives the deck's count"
NOTED = "each diagram note the run-of-show quotes is the slide's Say note, word for word"
STEPPED = "every quote in a step is on a slide its bold lead cites"
HASHED = "every \"...\" (#/N) in segments 4 to 6 and the segments table is on slide N"
RANGED = "segments 4 and 5 cite the deck from #/43 without a gap, and segment 6 runs from the next slide to the last"
PAGED = "every \"...\" (#/N) on /kubecon's glance rows and segments 4 and 5 is on slide N"

BLOCK_TAG = re.compile(r"<(?=/?(?:p|div|li|br|h[1-6]|tr|td|th|text|pre|section)\b)", re.I)
NOTES = re.compile(r'<aside class="notes">(.*?)</aside>', re.S)
SECTION = re.compile(r"<section\b[^>]*>(.*?)</section>", re.S)
COUNT = re.compile(r"\bdeck has (\d+) slides\b")
NOTE_QUOTE = re.compile(r'`#/(\d+)`: "(.*?)"(?=\s*(?:\n|$))', re.S)
LEAD = re.compile(r"^- \*\*(.*?)\*\*", re.S)
LEAD_REF = re.compile(r"\(`#/(\d+)`(?:,[^)]*)?(?: (?:to|and) `#/(\d+)`)?")
HASH_AFTER_QUOTE = re.compile(r'"([^"]+)" \(`?#/(\d+)`?(?: (?:to|and) `?#/(\d+)`?)?\)')
RANGE = re.compile(r"`#/(\d+)` to `#/(\d+)`")
SAID = re.compile(r'(?:\b[Ss]ay:|\breads|\badds|\brecalls)\s+"([^"]+)"')
BLOCKQUOTE = re.compile(r"^[ \t]*>[ \t]?(.*\S)[ \t]*$", re.M)
CODE = re.compile(r"`([^`]*)`")


def flat(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.replace(" ", " ").split())


def plain(fragment: str) -> str:
    """Markup as a reader sees it: a block tag is a space, an inline tag is nothing, entities decoded."""
    return flat(html.unescape(re.sub(r"<[^>]+>", "", BLOCK_TAG.sub(" <", fragment))))


def slides(deck: str) -> list[tuple[str, str]]:
    """Each slide's face and notes, in deck order, so slide i is `#/i`."""
    if SLIDES_OPEN not in deck:
        sys.exit(f"the deck has no {SLIDES_OPEN!r}; rounds-agenticburn's attendee.html changed its layout")
    out = []
    for body in SECTION.findall(deck[deck.index(SLIDES_OPEN):]):
        m = NOTES.search(body)
        out.append((plain(NOTES.sub("", body)), plain(m.group(1)) if m else ""))
    return out


def say(notes: str) -> str:
    """The notes' Say text: after "Say:", up to a "Do:" when there is one."""
    m = re.match(r"Say:\s*(.*?)(?:\s+Do:.*)?$", notes)
    return m.group(1) if m else notes


def need(text: str, literal: str, where: pathlib.Path) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {where.relative_to(REPO)}; this test cuts on it")


def section(ros: str, start: str, end: str) -> str:
    need(ros, start, ROS_PATH)
    need(ros, end, ROS_PATH)
    return ros.split(start, 1)[1].split(end, 1)[0]


def steps(seg: str) -> list[tuple[list[int], str]]:
    """Each top-level `- **...**` step that cites slides in its bold lead: the slides it cites and its text."""
    out = []
    for block in re.split(r"\n(?=- |#)", seg):
        m = LEAD.match(block)
        ref = LEAD_REF.search(m.group(1)) if m else None
        if ref:
            lo, hi = int(ref.group(1)), int(ref.group(2) or ref.group(1))
            out.append((list(range(lo, hi + 1)), block))
    return out


def quotes(text: str) -> list[str]:
    """What a step says a slide holds: each `> ` line, and each quote after "Say:", "reads", "adds" or "recalls";
    code spans holding a quote mark dropped, bold removed."""
    t = CODE.sub(lambda m: "" if '"' in m.group(1) else m.group(1), text).replace("**", "")
    return [flat(q) for q in BLOCKQUOTE.findall(t)] + [flat(q) for q in SAID.findall(flat(t))]


def on(deck: list[tuple[str, str]], quote: str, nums: list[int]) -> bool:
    return any(0 <= n < len(deck) and (quote in deck[n][0] or quote in deck[n][1]) for n in nums)


def problems(ros: str, page: str, deck: list[tuple[str, str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    counts = COUNT.findall(ros)
    out[COUNTED] = (
        [f"the run-of-show says {n}; the deck has {len(deck)}" for n in counts if int(n) != len(deck)]
        or ([] if counts else ["the run-of-show states no slide count"]))

    bad = []
    for n, quoted in NOTE_QUOTE.findall(ros):
        n = int(n)
        if n >= len(deck):
            bad.append(f"#/{n}: the deck ends at #/{len(deck) - 1}")
        elif flat(quoted) != say(deck[n][1]):
            bad.append(f"#/{n}: the run-of-show quotes {flat(quoted)!r}; the deck's note is {say(deck[n][1])!r}")
    out[NOTED] = bad

    segs = section(ros, SEG4, ABSTRACT)
    bad = []
    for nums, block in steps(segs):
        for q in quotes(block):
            if not on(deck, q, nums):
                bad.append(f"#/{nums[0]}" + (f" to #/{nums[-1]}" if len(nums) > 1 else "") + f": {q!r} is not there")
    out[STEPPED] = bad

    table = "\n".join(ln for ln in section(ros, SEGMENTS, SEG4).splitlines() if ln.startswith(ROWS))
    if len(table.splitlines()) != len(ROWS):
        sys.exit(f"the segments table no longer has the rows {ROWS}; this test reads them")
    bad = []
    for text in (segs, table):
        t = CODE.sub(lambda m: m.group(0) if m.group(1).startswith("#/") else m.group(1), flat(text).replace("**", ""))
        for m in HASH_AFTER_QUOTE.finditer(t):
            lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
            if not on(deck, flat(m.group(1)), list(range(lo, hi + 1))):
                bad.append(f"#/{lo}" + (f" to #/{hi}" if hi != lo else "") + f": {m.group(1)!r} is not there")
    out[HASHED] = bad

    cited = sorted({n for part in (section(ros, SEG4, SEG5), section(ros, SEG5, SEG6))
                    for nums, _ in steps(part) for n in nums})
    close = RANGE.search(section(ros, SEG6, ABSTRACT))
    bad = []
    if cited != list(range(FIRST, (cited or [FIRST])[-1] + 1)):
        bad.append(f"segments 4 and 5 cite {cited}, not #/{FIRST} on without a gap")
    if not close:
        bad.append("segment 6 cites no `#/N` to `#/M` range")
    else:
        lo, hi = int(close.group(1)), int(close.group(2))
        if cited and lo != cited[-1] + 1:
            bad.append(f"segment 6 opens on #/{lo}, not #/{cited[-1] + 1}, the slide after segment 5's last")
        if hi != len(deck) - 1:
            bad.append(f"segment 6 ends on #/{hi}; the deck's last slide is #/{len(deck) - 1}")
    out[RANGED] = bad

    need(page, PAGE_SEG4, PAGE_PATH)
    need(page, PAGE_SEG6, PAGE_PATH)
    head = page.split(PAGE_SEG4, 1)[0]
    rows = "\n".join(ln for ln in head.splitlines() if "<tr><td>" in ln)
    page_segs = plain(rows + " " + page.split(PAGE_SEG4, 1)[1].split(PAGE_SEG6, 1)[0])
    bad = []
    for m in HASH_AFTER_QUOTE.finditer(page_segs):
        lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
        if not on(deck, flat(m.group(1)), list(range(lo, hi + 1))):
            bad.append(f"#/{lo}" + (f" to #/{hi}" if hi != lo else "") + f": {m.group(1)!r} is not there")
    out[PAGED] = bad
    return out


def fetch() -> str:
    try:
        with urllib.request.urlopen(urllib.request.Request(DECK_URL, headers={"User-Agent": "wib-verify"}),
                                    timeout=60) as resp:
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError, UnicodeDecodeError) as exc:
        sys.exit(f"FAIL: could not read the deck at {DECK_URL}: {exc}")


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool) -> None:
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            failures.append(name)

    deck = slides(fetch())
    ros = ROS_PATH.read_text(encoding="utf-8")
    page = PAGE_PATH.read_text(encoding="utf-8")
    print(f"== the run-of-show and /kubecon follow the deck at {DECK_URL}, {len(deck)} slides ==")
    found = problems(ros, page, deck)
    for name, errs in found.items():
        for e in errs:
            print("  " + e)
        check(name, not errs)

    print("== each check fails on a deck or a run-of-show it should refuse ==")

    def fails(label: str, name: str, ros_: str = ros, page_: str = page, deck_: list[tuple[str, str]] = deck) -> None:
        check(f"self-check: {label} fails \"{name}\"", bool(problems(ros_, page_, deck_)[name]))

    cited = [n for n, _ in NOTE_QUOTE.findall(ros)]
    check("self-check: the run-of-show quotes diagram notes for the notes check to read", len(cited) > 30)
    fails("a slide added to the deck", COUNTED, deck_=deck + [("Appendix", "")])
    n = int(cited[len(cited) // 2])
    reworded = list(deck)
    reworded[n] = (deck[n][0], deck[n][1].replace(".", ", again.", 1))
    fails(f"#/{n}'s note reworded in the deck", NOTED, deck_=reworded)
    inserted = deck[:FIRST + 3] + [("A new slide", "Say: Something new.")] + deck[FIRST + 3:]
    fails(f"a slide inserted at #/{FIRST + 3}", STEPPED, deck_=inserted)
    fails(f"a slide inserted at #/{FIRST + 3}", HASHED, deck_=inserted)
    fails("a slide added after the close", RANGED, deck_=deck + [("Appendix", "")])
    lit = "Say: \"So why didn't it work this time?\""
    need(ros, lit, ROS_PATH)
    fails("a step's Say quote reworded in the run-of-show", STEPPED,
          ros_=ros.replace(lit, lit.replace("So why", "Why"), 1))
    lit = "(`#/114` to `#/126`)"
    need(ros, lit, ROS_PATH)
    fails("segment 6 opened a slide late", RANGED, ros_=ros.replace(lit, "(`#/115` to `#/126`)", 1))
    lit = '"Try your attack again." (#/71)'
    need(plain(page), lit, PAGE_PATH)
    fails("a /kubecon quote cited on the wrong slide", PAGED, page_=page.replace("(#/71)", "(#/72)", 1))

    if failures:
        print(f"\nFAILED: {len(failures)} check(s)")
        return 1
    print(f"\nThe run-of-show and /kubecon follow the {len(deck)}-slide deck rounds serves (#1270).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
