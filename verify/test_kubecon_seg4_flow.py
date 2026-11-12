# ABOUTME: Holds the /kubecon page's segments 4 and 5 (Challenges 3 and 4) and their glance rows to the run-of-show
# ABOUTME: (#1100, #1141): the deck's URL hashes in order, the trace after the attack, #1132 at each retry, no solve given away.
"""The presenter page, `gitops/ai-layer/web/kubecon.html`, follows the run-of-show's segments 4 and 5 (#1141).

rounds-agenticburn#102, built 2026-11-08, put Challenge 3 on the deck's `#/42` to `#/62` and Challenge 4 on `#/63`
to `#/74`; #1196 moved them to `#/42` to `#/65` and `#/66` to `#/100` after rounds-agenticburn#112 and #118, and #1141
moved the run-of-show's segments 4 and 5 onto those URL hashes. Rounds `cfbd9ba` redrew Challenge 4's diagrams as
thirty-eight slides, so Challenge 4 was `#/66` to `#/115` in the 127-slide deck at rounds main `faf4005` (#1270).
Rounds `8f53ce2` (rounds-agenticburn#170, 2026-11-11) gave Challenges 3 and 4 title cards and moved the desk's first
slide to `#/8` (#1327). Rounds `4627d95` (rounds-agenticburn#172, the same day) moved it back into Challenge 3 and added
a slide giving the room the desk and a bottom-line slide before Challenge 4, so in the 127-slide deck Challenge 3 is
`#/42` to `#/67` and Challenge 4 `#/68` to `#/117` (#1348).
This test holds the page to them:

  1. The glance table's row 4 names Challenge 3 with `#/42` to `#/67` and no Joker; row 5 names Challenge 4 with
     `#/68` to `#/117`.
  2. Segment 4's story cites `#/42` to `#/67`, and segment 5's `#/68` to `#/117`, each once, in ascending order, and
     their beats come in the run-of-show's order. The trace, LLM01, the switch and the retry carry the same hashes
     in the run-of-show.
  3. In the Challenge 3 block the presenters' attack (`#/49`) comes before its Datadog trace (`#/50`), and the trace
     before the first fix.
  4. Segment 4 says no "Joker" and puts no desk wall on screen; the deployments page and the prompt wall are the
     optional views during play; the desk is #1077's, filed and looked up by number and never browsed.
  5. Both segments name #1132 at their retry, segment 5 has no "The setup", and no room-facing part of the page
     (a prompt, a Say quote, the `?sheet=1` sheet's prompts) tells the room to list or try each tool.
  6. No hash of `#/42` or more, and no slide number in 44 to 64, appears on the page outside segments 4 and 5 and
     rows 4 and 5.
  7. Segment 4's copy blocks, its one prompt, two toggles and two fallback commands, are the ones #1100 found, word
     for word, and the block's `data-beat` is still C6; segment 5's prompt is unchanged (#1063's children own it).
  8. The page's header has no link to the desk's wall and says no "Joker" (#1161): no step projects the wall, so the
     header's old "Joker wall" link went, and the run-of-show says so.

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
SEG4_OPEN, SEG5_OPEN, SEG6_OPEN = "<!-- SEGMENT 4:", "<!-- SEGMENT 5:", "<!-- SEGMENT 6:"
PREMISE_OPEN = '<p class="premise">'
HEADER_OPEN, HEADER_CLOSE = "<header>", "</header>"
DESK_WALL = "support.burritobot.co/wall"
ROS_NO_WALL_LINK = "the /kubecon page's header has no link to it (#1161)"
C6_OPEN = '<article class="beat" data-beat="C6" data-segment="4">'
ROW4_OPEN, ROW5_OPEN = "<tr><td>4</td><td>7</td>", "<tr><td>5</td><td>5</td>"
ROS_SEG4, ROS_SEG5, ROS_SEG6 = "### Segment 4:", "### Segment 5:", "### Segment 6:"
FIRST, LAST = 42, 67
FIRST5, LAST5 = 68, 117

# The story's beats, as the page words them with its tags removed, in the run-of-show's order.
BEATS = [
    ("the title card (#/42)", '"It is time for Challenge 3!" (#/42)'),
    ("the AI guardrails heading (#/43)", '"AI guardrails" (#/43)'),
    ("the support desk (#/44)", '"BurritoBot has a support desk." (#/44)'),
    ("the room's access to the desk (#/45)", '"You\'ve got access to a support desk." (#/45)'),
    ("its QR code (#/46)", '"People can use the support desk too." (#/46)'),
    ("filing a ticket (#/47)", '"Let\'s file a ticket." (#/47)'),
    ("the challenge (#/48)", '(#/48), "Use the support ticket system to get BurritoBot to deploy something."'),
    ("the room's deployments page", "whose \"deploy\" opens the room's deployments page"),
    ("the HC-666 hint (#/49)", '(#/49), "Look up ticket HC-666 on the support desk."'),
    ("the white text, live", "Show it live"),
    ("the white text", "select all of its text to show the white text"),
    ("the attack", "the presenters' attack on the private bot and its deployment landing on the one deployments page"),
    ("the trace after the attack (#/50)", "Then its trace (#/50)"),
    ("LLM01 (#/51)", '"LLM01: Prompt Injection" (#/51)'),
    ("the fix (#/52)", "the fix (#/52)"),
    ("guardrails-agency-on", "least privilege, guardrails-agency-on, takes Deployments away"),
    ("then guardrails-input-on", "then guardrails-input-on arms the input classifier"),
    ("the retry (#/53)", '"Try your attack again." (#/53), the room\'s retry on the public bot'),
    ("RBAC (#/54)", '"Pesky RBAC!" (#/54)'),
    ("the Role (#/55 and #/56)", "Role before and after (#/55 and #/56)"),
    ("LLM Guard (#/57)", "LLM Guard (#/57)"),
    ("the diagram (#/58 to #/66)", "the architecture diagram (#/58 to #/66)"),
    ("the bottom line (#/67)", '"Bottom line: an AI guardrail classified the ticket as malicious and blocked it." (#/67)'),
]
BEATS5 = [
    ("the title card (#/68)", '"It is time for Challenge 4!" (#/68)'),
    ("the tee-up (#/69 and #/70)", '"But not every MCP server can be trusted." (#/69 and #/70)'),
    ("the challenge (#/71)", '(#/71), "Find the poisoned MCP tool."'),
    ("the hint (#/72)", '(#/72), "Ask BurritoBot about the weather, then look at what else it did."'),
    ("the attack and its trace", "Michael's live weather ask on the private bot"),
    ("LLM04 (#/73)", '"LLM04: Supply Chain" (#/73)'),
    ("guardrails-mcp-on (#/74)", "(#/74): guardrails-mcp-on"),
    ("the retry (#/75)", '"Try your attack again." (#/75), the room\'s retry on the public bot, which guardrails-mcp-on reaches'),
    ("the gateway (#/76 and #/77)", "agentgateway in the notes (#/76 and #/77)"),
    ("the diagrams (#/78 to #/115)", "without and then with the gateway (#/78 to #/115)"),
    ("the rule (#/116 and #/117)", "its rule before and after (#/116 and #/117)"),
    ("the close starts at #/118", "The close starts at #/118."),
]
# The same beats' hashes in the run-of-show, for the ones the page and the run-of-show both name.
ROS_NUMBERS = [
    ("the trace", "**The trace, after the attack (#/50).**"),
    ("LLM01", "**LLM01 (#/51).**"),
    ("the switch", "from /lab (#/52)"),
    ("the retry", "**The retry (#/53).**"),
    ("Challenge 4's retry", "**The retry (#/75).**"),
]
# The Challenge 3 block's order: the attack, its trace, then the fixes.
BLOCK_ORDER = [
    ("the presenters' attack (#/49)", "Success marker, private bot (the presenters' attack, #/49)"),
    ("its trace (#/50)", "The trace, after the attack (#/50):"),
    ("the attack's seed, by its session id", "wib-stage-c3-attack-<stamp> on Past 7 Days"),
    ("the attack's seed", "c3-attack"),
    ("least privilege first", "guardrails-agency-on"),
    ("then the input guard", "guardrails-input-on"),
    ("the fixed seed, by its session id", "wib-stage-c3-fixed-<stamp>"),
    ("the fixed seed", "c3-fixed"),
]
KEPT = [
    ("the deployments page, optional during play",
     "Optional during play: the deployments page, https://deployments.burritobot.co,"),
    ("the prompt wall, optional during play", "and the prompt wall, https://prompts.burritobot.co."),
    ("the story names both optional views", "the deployments page and the prompt wall optional"),
    ("the number-only desk (#1077)",
     "Anyone can file a ticket and gets its number back, and anyone can look a ticket up by its number; nobody can "
     "browse tickets."),
    ("both bots read the one desk and page (#1145)", "Both clusters' bots read this one desk and deploy to one page, "
                                                     "deployments.burritobot.co"),
    ("the demo ticket takes a presenter number (#1156)", "HC-900 to HC-999, a range the room is never given"),
    ("only presenter numbers on the admin bot", "On the admin bot, read only a presenter number or HC-666"),
    ("the presenters' path", "localhost:18080/presenter-ticket"),
    ("Kyverno trusts the internal registry", "the internal registry Kyverno trusts"),
    ("the double duty's seed, in APM's traces by its session id",
     "service:burritobot @session.id:wib-stage-c3-pii-<stamp> on Past 7 Days"),
    ("#1132 at the retry, in the notes", "Since #1132 both commands switch both clusters"),
]
# Segment 5's one prompt, as staging had it before #1141 (#1063's children own the prompts), with the city #1303 named.
C7_PROMPT = ("I'm a newly turned vampire with yet another burrito delivery order to my dungeon. I really miss daylight. "
             "What's the weather like up there in Salt Lake City?")
# Wording that would give Challenge 4's solve to the room.
SOLVE_LEAKS = ["try each tool", "try each one", "use each one", "then use each", "list its tools and", "list the tools, then"]
# Segment 4's copy blocks as #1100 found them (git show c57c1590:gitops/ai-layer/web/kubecon.html).
COPY_BLOCKS = [
    "What's the status of my support ticket HC-666?",
    "guardrails-agency-on",
    "guardrails-input-on",
    "CONTEXT=<private-context> challenges/02-sanitization/fallback.curl.sh input",
    "kubectl --context <private-context> -n agent auth can-i create deployments "
    "--as=system:serviceaccount:agent:workshop-mcp",
]
SLIDE_PAREN = re.compile(r"\(#/(\d+)(?: (?:to|and) #/(\d+))?\)")
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
    """A slide number in 44..64, or a hash of #/42 or more, in `text`."""
    t = plain(text)
    out = [t[max(0, m.start() - 30):m.end() + 10] for m in CITE.finditer(t)
           if any(44 <= n <= 64 for n in expand([m]))]
    out += [t[max(0, m.start() - 30):m.end() + 10] for m in HASH.finditer(t) if int(m.group(1)) >= FIRST]
    return out


def problems(page: str, ros: str) -> dict[str, list[str]]:
    for lit in (SEG4_OPEN, SEG5_OPEN, SEG6_OPEN, ROW4_OPEN, ROW5_OPEN):  # C6_OPEN is a check of its own, below
        need(page, lit, PAGE_PATH)
    for lit in (ROS_SEG4, ROS_SEG6):
        need(ros, lit, ROS_PATH)
    for lit in (HEADER_OPEN, HEADER_CLOSE):
        need(page, lit, PAGE_PATH)
    head, rest = page.split(SEG4_OPEN, 1)
    seg_html, rest5 = rest.split(SEG5_OPEN, 1)
    seg5_html, tail = rest5.split(SEG6_OPEN, 1)
    need(seg_html, PREMISE_OPEN, PAGE_PATH)
    need(seg5_html, PREMISE_OPEN, PAGE_PATH)
    row_line = next(ln for ln in head.splitlines() if ROW4_OPEN in ln)
    row5_line = next(ln for ln in head.splitlines() if ROW5_OPEN in ln)
    row, row5 = plain(row_line), plain(row5_line)
    seg, seg5 = plain(seg_html), plain(seg5_html)
    premise = plain(seg_html.split(PREMISE_OPEN, 1)[1].split("</p>", 1)[0])
    premise5 = plain(seg5_html.split(PREMISE_OPEN, 1)[1].split("</p>", 1)[0])
    block = plain(seg_html.split(C6_OPEN, 1)[1].split("</article>", 1)[0]) if C6_OPEN in seg_html else ""
    ros_seg = flat(ros.split(ROS_SEG4, 1)[1].split(ROS_SEG6, 1)[0].replace("`", ""))
    out: dict[str, list[str]] = {}
    out["the glance rows name Challenge 3 on #/42 to #/67 and Challenge 4 on #/68 to #/117, and no Joker"] = (
        ([] if "Challenge 3, #/42 to #/67:" in row else [f"row 4 reads {row!r}"])
        + ([] if "Challenge 4, #/68 to #/117:" in row5 else [f"row 5 reads {row5!r}"])
        + [w for w in ("Joker", "joker") if w in row])
    slides = expand(SLIDE_PAREN.finditer(premise))
    out[f"segment 4's story cites #/{FIRST} to #/{LAST}, each once, in order"] = (
        [] if slides == list(range(FIRST, LAST + 1)) else [f"cited {slides}"])
    slides5 = expand(SLIDE_PAREN.finditer(premise5))
    out[f"segment 5's story cites #/{FIRST5} to #/{LAST5}, each once, in order"] = (
        [] if slides5 == list(range(FIRST5, LAST5 + 1)) else [f"cited {slides5}"])
    out["the story's beats come in the run-of-show's order"] = in_order(premise, BEATS) + in_order(premise5, BEATS5)
    out["the trace, LLM01, the switch and the retries carry the run-of-show's hashes"] = [
        f"{label}: {p!r} not in the run-of-show's segments 4 and 5" for label, p in ROS_NUMBERS if p not in ros_seg]
    out["the Challenge 3 block shows the attack, then its trace, then the fixes"] = in_order(block, BLOCK_ORDER)
    out["segment 4 says no Joker and puts no desk wall on screen"] = [
        w for w in ("Joker", "joker", "/wall") if w in seg_html]
    header = page.split(HEADER_OPEN, 1)[1].split(HEADER_CLOSE, 1)[0]
    out["the header has no link to the desk's wall, and the run-of-show says why (#1161)"] = (
        [w for w in (DESK_WALL, "/wall", "Joker", "joker") if w in header]
        + ([] if ROS_NO_WALL_LINK in flat(ros) else [f"the run-of-show lacks {ROS_NO_WALL_LINK!r}"]))
    out["segment 4 names the optional views, the number-only desk and the facts that hold"] = [
        f"{label}: {p!r}" for label, p in KEPT if p not in seg]
    out["segment 5 drops \"The setup\" and names #1132 at #/75's retry"] = (
        (["The setup"] if "The setup" in seg5 else [])
        + ([] if "so on #/75 the room retries on the public bot" in seg5
           and "Since #1132 guardrails-mcp-on switches both clusters" in seg5 else ["no #1132 in the C7 notes"]))
    room = " ".join(plain(x) for x in re.findall(r'<div class="prompt"[^>]*>(.*?)</div>', page, re.S))
    room += " " + " ".join(re.findall(r'Say: "(.*?)"', plain(page)))
    out["no room-facing part of the page tells the room to list or try each tool"] = [
        w for w in SOLVE_LEAKS if w in room.lower()]
    c7 = [plain(re.sub(r"<button[^>]*>.*?</button>", "", b))
          for b in re.findall(r'<div class="prompt" onclick="cp\(this\)">(.*?)</div>', seg5_html)]
    out["segment 5's prompt is unchanged"] = [] if c7 == [C7_PROMPT] else [f"prompts {c7}"]
    cited = expand(SLIDE_PAREN.finditer(seg))
    out[f"every hash segment 4 cites is in #/{FIRST} to #/{LAST}"] = [
        str(n) for n in cited if not FIRST <= n <= LAST]
    outside = head.replace(row_line, "").replace(row5_line, "") + tail
    out["no slide 44 to 64 and no #/42 or later outside segments 4 and 5 and rows 4 and 5"] = stray_numbers(outside)
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

print("== /kubecon's segments 4 and 5 follow the run-of-show's (#1141) ==")
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


ROWS = "the glance rows name Challenge 3 on #/42 to #/67 and Challenge 4 on #/68 to #/117, and no Joker"
OUTSIDE = "no slide 44 to 64 and no #/42 or later outside segments 4 and 5 and rows 4 and 5"
fails_on("the old row put back",
         swap(page, "Challenge 3, <code>#/42</code> to <code>#/67</code>: a support ticket gets the bot to deploy something",
              "Challenge 3: ticket HC-666 deploys your Joker"), ROWS)
fails_on("the pre-#1270 row 5, Challenge 4 on #/69 to #/102, put back",
         swap(page, "Challenge 4, <code>#/68</code> to <code>#/117</code>:",
              "Challenge 4, <code>#/69</code> to <code>#/102</code>:"),
         ROWS)
fails_on("the pre-#1270 diagrams, #/78 to #/100, put back in segment 5's story",
         swap(page, "(#/78 to #/115)", "(#/78 to #/100)"),
         f"segment 5's story cites #/{FIRST5} to #/{LAST5}, each once, in order")
fails_on("a hash cited out of order in the story",
         swap(page, "Then its trace (#/50)", "Then its trace (#/51)"),
         f"segment 4's story cites #/{FIRST} to #/{LAST}, each once, in order")
fails_on("the trace moved ahead of the attack in the story",
         swap(swap(page, "Then its trace (#/50), ", ""),
              "The hint (#/49),", "Then its trace (#/50), the hint (#/49),"),
         "the story's beats come in the run-of-show's order")
need(page, "<b>The trace, after the attack\n      (#/50)", PAGE_PATH)
_trace = page[page.index("<b>The trace, after the attack\n      (#/50)"):page.index("leads to.</div>") + len("leads to.</div>")]
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
fails_on("the header's Joker wall link put back",
         swap(page, "</header>", '  <a href="https://support.burritobot.co/wall" target="_blank" rel="noopener">'
                                 "Joker wall →</a>\n</header>"),
         "the header has no link to the desk's wall, and the run-of-show says why (#1161)")
fails_on("a Joker put back in the marker",
         swap(page, "under their witch name. The bot", "under their witch name, as joker-agatha-the-banshee. The bot"),
         "segment 4 says no Joker and puts no desk wall on screen")
fails_on("the number-only desk dropped",
         swap(page, "nobody can browse\n    tickets.", "the front page lists them."),
         "segment 4 names the optional views, the number-only desk and the facts that hold")
fails_on("\"The setup\" put back in Challenge 4",
         swap(page, "<h3>Challenge 4: find the poisoned MCP tool</h3>", "<h3>Challenge 4: The setup</h3>"),
         "segment 5 drops \"The setup\" and names #1132 at #/75's retry")
fails_on("the pre-#1237 note, the retry shown on the admin bot, put back",
         swap(page, "so on #/75 the room retries on the public bot, as soon as the\n      command prints",
              "so show #/75's retry on the\n      admin bot"),
         "segment 5 drops \"The setup\" and names #1132 at #/75's retry")
fails_on("the solve told to the room in a prompt",
         swap(page, "What's the weather like up there in Salt Lake City?",
              "Try each tool, then tell me the weather in Salt Lake City."),
         "no room-facing part of the page tells the room to list or try each tool")
fails_on("#/40 cited in segment 4",
         swap(page, "#/53, the retry</div>", "#/53, the retry (#/40)</div>"),
         f"every hash segment 4 cites is in #/{FIRST} to #/{LAST}")
fails_on("a #/52 hash cited in segment 6",
         swap(page, "<h3>Burritos only (1 min): re-send the weird asks</h3>",
              "<h3>Burritos only (1 min, #/52): re-send the weird asks</h3>"), OUTSIDE)
fails_on("the Challenge 3 prompt reworded",
         swap(page, "What's the status of my support ticket HC-666?<button",
              "What does my support ticket HC-666 say?<button"),
         "segment 4's copy blocks are #1100's, word for word, under data-beat C6")
fails_on("the C6 beat key changed",
         swap(page, C6_OPEN, '<article class="beat" data-beat="C6-desk" data-segment="4">'),
         "segment 4's copy blocks are #1100's, word for word, under data-beat C6")
check("self-check: the run-of-show's line on the header's link dropped fails the header check",
      bool(problems(page, ros.replace("has no link\nto it (#1161)", "links it", 1))[
          "the header has no link to the desk's wall, and the run-of-show says why (#1161)"]))
check("self-check: segment 3's slides 28 to 42 and a shifted slide 65 pass the outside check",
      not stray_numbers("slide 28, slides 30 to 42, slides 40 to 42, slide 65"))
check("self-check: and a #/42 hash does not", bool(stray_numbers("the deck's #/42")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The /kubecon page's segments 4 and 5 and their rows follow the run-of-show's, #/42 to #/117 (#1141, #1327, #1348).")
