# ABOUTME: Holds the /kubecon page's segment 4 (Challenge 3) and its glance row to the run-of-show's segment 4 (#1100):
# ABOUTME: slides 44 to 64 in order, the trace after the attack, the optional views, the number-only desk, no Joker.
"""The presenter page, `gitops/ai-layer/web/kubecon.html`, follows the run-of-show's segment 4 (#1100, from #1076).

#1098 rewrote the run-of-show's segment 4 to the 2026-11-07 deck's Challenge 3, slides 44 to 64 in the run-of-show's
numbering (the deck's `#/43` to `#/63`), and #1099 checked that no file under facilitation/, challenges/ or verify/
cites one of those numbers outside it. This test holds the page to the same flow:

  1. The glance table's row 4 names Challenge 3 with slides 44 to 64 and says no Joker.
  2. Segment 4's story cites slides 44 to 64, each once, in ascending order, and its beats come in the run-of-show's
     order: the desk, its QR code, filing a ticket, the challenge, the HC-666 hint, the white text, the attack, the
     trace, LLM01, `guard-agency-on` then `guard-input-on`, the retry, least privilege, the input guard, the diagram.
     The trace (49), LLM01 (50), the switch (51) and the retry (52) carry the same numbers in the run-of-show.
  3. In the Challenge 3 block the presenters' attack (slide 48) comes before its Datadog trace (slide 49), and the
     trace before the first fix.
  4. Segment 4 says no "Joker" and puts no desk wall on screen; the deployments page and the prompt wall are the
     optional views during play; the desk is #1077's, filed and looked up by number and never browsed.
  5. No slide number in 44 to 64 and no hash of `#/43` or more appears on the page outside segment 4 and row 4.
  6. Segment 4's copy blocks, its one prompt, two toggles and two fallback commands, are the ones #1100 found, word
     for word, and the block's `data-beat` is still C6: #1100 rewrote the prose around them and none of them.

Segment 3's hand-off on the page is verify/test_instructor_brief.py's. Each cut on page text checks its literal first
and exits naming it when it is gone ("Tests own their inputs"), and each check is run again on a copy with the old
wording put back or one beat moved, so a check that could never fail shows up here.
"""
from __future__ import annotations

import html
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE_PATH = REPO / "gitops/ai-layer/web/kubecon.html"
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
SEG4_OPEN, SEG5_OPEN = "<!-- SEGMENT 4:", "<!-- SEGMENT 5:"
PREMISE_OPEN = '<p class="premise">'
C6_OPEN = '<article class="beat" data-beat="C6" data-segment="4">'
ROW4_OPEN = "<tr><td>4</td><td>7</td>"
ROS_SEG4, ROS_SEG5 = "### Segment 4:", "### Segment 5:"
FIRST, LAST = 44, 64

# The story's beats, as the page words them with its tags removed, in the run-of-show's order.
BEATS = [
    ("the desk (44)", '"BurritoBot has a support desk." (44)'),
    ("its QR code (45)", '"People can use the support desk too." (45)'),
    ("filing a ticket (46)", '"Let\'s file a ticket." (46)'),
    ("the challenge (47)", '(47), "Use the support ticket system to get BurritoBot to deploy something."'),
    ("the HC-666 hint (48)", '(48), "Look up ticket HC-666 on the support desk."'),
    ("the white text", "select all of its text to show the white text"),
    ("the attack", "the presenters' attack on the private bot and its deployment landing"),
    ("the trace after the attack (49)", "Then its trace (49)"),
    ("LLM01 (50)", '"LLM01: Prompt Injection" (50)'),
    ("the fix (51)", "the fix (51)"),
    ("guard-agency-on", "least privilege, guard-agency-on, takes Deployments away"),
    ("then guard-input-on", "then guard-input-on arms the input classifier"),
    ("the retry (52)", '"Try your attack again." (52)'),
    ("least privilege (53 to 56)", "least privilege and its Role before and after (53 to 56)"),
    ("the input guard (57 and 58)", "the input guard (57 and 58)"),
    ("the diagram (59 to 64)", "the architecture diagram (59 to 64)"),
]
# The same beats' numbers in the run-of-show's segment 4, for the four the page and the run-of-show both name.
ROS_NUMBERS = [
    ("the trace", "**The trace, after the attack (slide 49).**"),
    ("LLM01", "**LLM01 (slide 50).**"),
    ("the switch", "from `/lab` (slide 51)"),
    ("the retry", "**The retry (slide 52).**"),
]
# The Challenge 3 block's order: the attack, its trace, then the fixes.
BLOCK_ORDER = [
    ("the presenters' attack (slide 48)", "Success marker, private bot (the presenters' attack, slide 48)"),
    ("its trace (slide 49)", "Datadog Challenge 3 tab, after the attack (slide 49):"),
    ("the attack's saved view", "c3-attack"),
    ("least privilege first", "guard-agency-on"),
    ("then the input guard", "guard-input-on"),
    ("the fixed saved view", "c3-fixed"),
]
KEPT = [
    ("the deployments page, optional during play",
     "Optional during play: the deployments page, https://deployments.burritobot.co,"),
    ("the prompt wall, optional during play", "and the prompt wall, https://prompts.burritobot.co."),
    ("the story names both optional views", "the deployments page and the prompt wall optional"),
    ("the number-only desk (#1077)",
     "Anyone can file a ticket and gets its number back, and anyone can look a ticket up by its number; nobody can "
     "browse tickets."),
    ("the admin bot reads the private desk", "file the ticket on the private cluster's desk, "
                                             "support-burritobot-private.burritobot.co,"),
    ("Kyverno trusts the internal registry", "the internal registry Kyverno trusts"),
    ("the double duty's saved view", "c3-pii"),
]
# Segment 4's copy blocks as #1100 found them (git show c57c1590:gitops/ai-layer/web/kubecon.html).
COPY_BLOCKS = [
    "What's the status of my support ticket HC-666?",
    "guard-agency-on",
    "guard-input-on",
    "CONTEXT=<private-context> challenges/02-sanitization/fallback.curl.sh input",
    "kubectl --context <private-context> -n agent auth can-i create deployments "
    "--as=system:serviceaccount:agent:workshop-mcp",
]
SLIDE_PAREN = re.compile(r"\((\d+)(?: (?:to|and) (\d+))?\)")
CITE = re.compile(r"\bslides? (\d+)(?: (?:to|and) (\d+))?", re.IGNORECASE)
HASH = re.compile(r"#/(\d+)")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def need(text: str, literal: str, where: pathlib.Path) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {where.relative_to(REPO)}; the segment 4 checks cut on it")


def flat(text: str) -> str:
    return " ".join(text.split())


def plain(fragment: str) -> str:
    """The fragment as a reader sees it: tags removed, entities decoded, whitespace flattened."""
    return flat(html.unescape(re.sub(r"<[^>]+>", "", fragment)))


def in_order(text: str, phrases: list[tuple[str, str]]) -> list[str]:
    bad, at = [], -1
    for label, phrase in phrases:
        i = text.find(phrase, at + 1)
        if i < 0:
            bad.append(f"{label}: {phrase!r} missing or before the beat ahead of it")
        else:
            at = i
    return bad


def expand(matches) -> list[int]:
    out: list[int] = []
    for m in matches:
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        out.extend(range(lo, hi + 1))
    return out


def stray_numbers(text: str) -> list[str]:
    """A slide number in FIRST..LAST, or a hash of #/43 or more, in `text`."""
    t = plain(text)
    out = [t[max(0, m.start() - 30):m.end() + 10] for m in CITE.finditer(t)
           if any(FIRST <= n <= LAST for n in expand([m]))]
    out += [t[max(0, m.start() - 30):m.end() + 10] for m in HASH.finditer(t) if int(m.group(1)) >= FIRST - 1]
    return out


def problems(page: str, ros: str) -> dict[str, list[str]]:
    for lit in (SEG4_OPEN, SEG5_OPEN, ROW4_OPEN):  # C6_OPEN is a check of its own, below
        need(page, lit, PAGE_PATH)
    for lit in (ROS_SEG4, ROS_SEG5):
        need(ros, lit, ROS_PATH)
    head, rest = page.split(SEG4_OPEN, 1)
    seg_html, tail = rest.split(SEG5_OPEN, 1)
    need(seg_html, PREMISE_OPEN, PAGE_PATH)
    row_line = next(ln for ln in head.splitlines() if ROW4_OPEN in ln)
    row = plain(row_line)
    seg = plain(seg_html)
    premise = plain(seg_html.split(PREMISE_OPEN, 1)[1].split("</p>", 1)[0])
    block = plain(seg_html.split(C6_OPEN, 1)[1].split("</article>", 1)[0]) if C6_OPEN in seg_html else ""
    ros_seg = flat(ros.split(ROS_SEG4, 1)[1].split(ROS_SEG5, 1)[0])
    out: dict[str, list[str]] = {}
    out["the glance row names Challenge 3, slides 44 to 64, and no Joker"] = (
        ([] if "Challenge 3, slides 44 to 64:" in row else [f"row reads {row!r}"])
        + [w for w in ("Joker", "joker") if w in row])
    slides = expand(SLIDE_PAREN.finditer(premise))
    out[f"the story cites slides {FIRST} to {LAST}, each once, in order"] = (
        [] if slides == list(range(FIRST, LAST + 1)) else [f"cited {slides}"])
    out["the story's beats come in the run-of-show's order"] = in_order(premise, BEATS)
    out["the trace, LLM01, the switch and the retry carry the run-of-show's numbers"] = [
        f"{label}: {p!r} not in the run-of-show's segment 4" for label, p in ROS_NUMBERS if p not in ros_seg]
    out["the Challenge 3 block shows the attack, then its trace, then the fixes"] = in_order(block, BLOCK_ORDER)
    out["segment 4 says no Joker and puts no desk wall on screen"] = [
        w for w in ("Joker", "joker", "/wall") if w in seg_html]
    out["segment 4 names the optional views, the number-only desk and the facts that hold"] = [
        f"{label}: {p!r}" for label, p in KEPT if p not in seg]
    cited = expand(CITE.finditer(seg)) + expand(SLIDE_PAREN.finditer(seg))
    out[f"every slide segment 4 cites is in {FIRST} to {LAST}"] = [
        str(n) for n in cited if not FIRST <= n <= LAST]
    outside = head.replace(row_line, "") + tail
    out["no slide 44 to 64 and no #/43 or later outside segment 4 and row 4"] = stray_numbers(outside)
    blocks = [plain(re.sub(r"<button[^>]*>.*?</button>", "", b)) for b in
              re.findall(r'<(?:div|code) class="(?:prompt|toggle)" onclick="cp\(this\)">(.*?)</(?:div|code)>'
                         r'|<code onclick="cp\(this\)">(.*?)</code>', seg_html) for b in b if b]
    blocks = [re.sub(r"^(Fix, least privilege · private terminal · prints its kubectl apply|"
                     r"Toggle, the input guard · private terminal)", "", b).strip() for b in blocks]
    out["segment 4's copy blocks are #1100's, word for word, under data-beat C6"] = (
        ([] if blocks == COPY_BLOCKS else [f"copy blocks {blocks}"])
        + ([] if C6_OPEN in seg_html else ["the C6 block's data-beat or data-segment changed"]))
    return out


page = PAGE_PATH.read_text(encoding="utf-8")
ros = ROS_PATH.read_text(encoding="utf-8")

print("== /kubecon's segment 4 follows the run-of-show's (#1100) ==")
for name, errs in problems(page, ros).items():
    for e in errs:
        print("    " + e)
    check(name, not errs)

print("== each check fails on a page it should refuse ==")


def fails_on(label: str, mutated: str, check_name: str) -> None:
    check(f"self-check: {label}", bool(problems(mutated, ros)[check_name]))


def swap(text: str, old: str, new: str) -> str:
    if old not in text:
        sys.exit(f"ANCHOR MISSING: {old!r} is not in {PAGE_PATH.relative_to(REPO)}; a self-check edits on it")
    return text.replace(old, new, 1)


fails_on("the old row put back",
         swap(page, "Challenge 3, slides 44 to 64: a support ticket gets the bot to deploy something",
              "Challenge 3: ticket HC-666 deploys your Joker"),
         "the glance row names Challenge 3, slides 44 to 64, and no Joker")
fails_on("a slide cited out of order in the story",
         swap(page, "Then its trace\n    (49)", "Then its trace\n    (50)"),
         f"the story cites slides {FIRST} to {LAST}, each once, in order")
fails_on("the trace moved ahead of the attack in the story",
         swap(swap(page, "Then its trace\n    (49), ", ""),
              "The hint (48),", "Then its trace (49), the hint (48),"),
         "the story's beats come in the run-of-show's order")
_trace = page[page.index("<b>Datadog Challenge 3 tab"):page.index("leads to.</div>") + len("leads to.</div>")]
fails_on("the Datadog line moved above the attack's marker",
         swap(swap(page, _trace, "</div>"),
              "<span class=\"lbl\">Success marker, private bot (the presenters'", _trace + "<span class=\"lbl\">Success "
              "marker, private bot (the presenters'"),
         "the Challenge 3 block shows the attack, then its trace, then the fixes")
fails_on("the desk's wall put back on screen",
         swap(page, "and the prompt wall, <code>https://prompts.burritobot.co</code>.",
              "and the prompt wall, <code>https://prompts.burritobot.co</code>. Project "
              "<code>https://support.burritobot.co/wall</code>."),
         "segment 4 says no Joker and puts no desk wall on screen")
fails_on("a Joker put back in the marker",
         swap(page, "under their witch name. The bot", "under their witch name, as joker-agatha-the-banshee. The bot"),
         "segment 4 says no Joker and puts no desk wall on screen")
fails_on("the number-only desk dropped",
         swap(page, "nobody can browse\n    tickets.", "the front page lists them."),
         "segment 4 names the optional views, the number-only desk and the facts that hold")
fails_on("a slide number 40 cited in segment 4",
         swap(page, "slide 52, the retry", "slide 40, the retry"),
         f"every slide segment 4 cites is in {FIRST} to {LAST}")
fails_on("slide 51 cited in segment 5",
         swap(page, "<h3>Challenge 4: the under-protected MCP server</h3>",
              "<h3>Challenge 4 (slide 51): the under-protected MCP server</h3>"),
         "no slide 44 to 64 and no #/43 or later outside segment 4 and row 4")
fails_on("a #/50 hash cited in segment 6",
         swap(page, "<h3>Burritos only (1 min): re-send the weird asks</h3>",
              "<h3>Burritos only (1 min, #/50): re-send the weird asks</h3>"),
         "no slide 44 to 64 and no #/43 or later outside segment 4 and row 4")
fails_on("the Challenge 3 prompt reworded",
         swap(page, "What's the status of my support ticket HC-666?<button",
              "What does my support ticket HC-666 say?<button"),
         "segment 4's copy blocks are #1100's, word for word, under data-beat C6")
fails_on("the C6 beat key changed",
         swap(page, C6_OPEN, '<article class="beat" data-beat="C6-desk" data-segment="4">'),
         "segment 4's copy blocks are #1100's, word for word, under data-beat C6")
check("self-check: segment 3's slides 28 to 42 and a shifted slide 65 pass the outside check",
      not stray_numbers("slide 28, slides 30 to 42, slides 40 to 42, slide 65"))
check("self-check: and a #/43 hash does not", bool(stray_numbers("the deck's #/43")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The /kubecon page's segment 4 and its row follow the run-of-show's segment 4, slides 44 to 64 (#1100).")
