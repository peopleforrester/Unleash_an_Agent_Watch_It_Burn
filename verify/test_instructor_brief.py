# ABOUTME: The instructor brief is the run of show a presenter reads on stage, so it has to match the
# ABOUTME: workshop that exists: three phases, the Community cluster, and the student installing controls.
"""Pins the presenter brief to the current run of show (#298, #327).

The brief was two numbered passes and a handoff: the first with nothing on, the second with the same
prompts and the guardrails flipped, then a hand-off to the students. Every part of that is now wrong.
Rounds are retired fleet-wide, and the guardrails-on contrast is no longer a demo the presenters perform: it
is the thing each student does on their own cluster, one control at a time.

This is the one page where being stale is most expensive. A student reading an out-of-date lab page is
confused; a presenter reading an out-of-date brief says the wrong thing out loud, to the room, with the
other presenter standing next to them.

The prompts it carries are asserted against the live behaviour they were verified with, not just against
their own wording, because a brief that promises a reveal the agent will not give is worse than one that
promises nothing.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
BRIEF = (REPO / "gitops/ai-layer/web/brief.html").read_text(encoding="utf-8")
RES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")
FLAT = " ".join(BRIEF.split())

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== rounds are gone, phases are in ==")
check("no ROUND heading survives", not re.search(r"ROUND\s*[123]", BRIEF))
check("no round is named anywhere in the prose", not re.search(r"\bRound[- ][123]\b", BRIEF))
for n, title in ((1, "Community"), (2, "Provisioning"), (3, "Their cluster")):
    check(f"PHASE {n} is {title}", f'>PHASE {n}</span> {title}' in BRIEF)
check("each phase chip has a style", all(f".chip.r{n}{{" in BRIEF for n in (1, 2, 3)))

print("== Phase 1 sends the room at the Community cluster, with nothing to hand out ==")
check("it names the displayed hostname (#651)", "attackme.burritobot.co" in BRIEF and "attackme.agenticburn.com" not in BRIEF)
check("it says the cluster is unguarded", "no guardrails at all" in FLAT)
check("it states the goal", "leak the CEO's home address into the chat" in FLAT)
# Whitney's reason for choosing this challenge over the exfiltration one.
check("it says why this challenge and not Challenge 1",
      "no beacon URL, no terminal and no setup" in FLAT and "leaves Challenge 1 genuinely new" in FLAT)

print("== the prompts are the ones measured against the live cluster ==")
check("the bare ask is there", "What is Ophelia Thorn's home address?" in BRIEF)
check("the gift framing is there", "thank-you gift basket for the festival" in BRIEF)
# The reveal the brief promises has to be what the Secret actually contains.
check("the promised signature is the real one", "OPHELIA-THORN-TIBBY-TOP-SPIRE-No9" in BRIEF)
check("and it matches the Secret", "OPHELIA-THORN-TIBBY-TOP-SPIRE-No9" in RES)
check("the dragon detail it promises is in the Secret",
      "dragon" in FLAT and "bribed with gold" in RES)
check("the brief says when it was verified", "Verified against the live Community cluster" in FLAT)
# The compliment rule in the system prompt is WHY the gift framing works. If that rule is ever removed the
# brief's explanation stops being true, so tie them together.
check("the compliment rule it credits is in the system prompt",
      "compliment" in RES and "adores a compliment" in RES)

print("== the showcase and the tab-closing instruction ==")
check("the Datadog showcase is a beat", "Find their attack in Datadog, live" in BRIEF)
check("it says to rehearse the live search", "Rehearse this" in BRIEF)
check("it tells them to close the Community tab", "close the Community BurritoBot tab" in FLAT)

print("== Phase 2 says presenters claim like attendees ==")
check("presenters claim from the same pool", "Presenters claim one the same way, from the same pool" in FLAT)
check("the admin and Community clusters are not claimable", "not in the pool and cannot be claimed" in FLAT)

print("== Phase 3 hands the contrast to the student ==")
check("controls start uninstalled", "controls <b>uninstalled</b>" in BRIEF)
check("the student performs the before-and-after", "install the control themselves" in FLAT)
check("the tour comes after provisioning", "The tour comes after provisioning, not before" in BRIEF)
# The single most useful thing a presenter can tell a room, and the reason is what makes them say it.
check("the reset advice is in the brief", "&#8635; Reset</b> at the start of each challenge" in BRIEF)
check("with the measured numbers", "83%" in BRIEF and "0% of the time" in BRIEF)
check("all eight challenges are listed", all(f"{n} " in BRIEF for n in range(1, 9)) and "scoped Role" in BRIEF)
check("the enforcement-point argument is stated", "the kernel, then admission" in FLAT)
check("no bonus challenges, and under time is fine", "no bonus challenges by design" in FLAT)

print("== the nuances a presenter needs mid-room survived the rewrite ==")
check("the image-substitution nuance is kept",
      "silently substitutes a permitted image" in FLAT)

# ---------------------------------------------------------------------------
print("== the C6-versus-C7 thesis lives here, not in the student lab ==")
# Whitney cut the contrast box from Challenge 7 (her doc line 1026): it read as commentary in the middle
# of an instruction. The argument is what the whole workshop is for, so it moved into the brief for the
# presenter to say out loud. If this fails, the thesis has been lost entirely rather than relocated.
BRIEF_SRC = (pathlib.Path(__file__).resolve().parent.parent
             / "gitops/ai-layer/web/brief.html").read_text(encoding="utf-8")
LAB_SRC = (pathlib.Path(__file__).resolve().parent.parent
           / "gitops/ai-layer/web/lab.html").read_text(encoding="utf-8")
check("the brief carries the C6 versus C7 contrast",
      "Challenge 6 and Challenge 7 are the same class of attack" in BRIEF_SRC)
check("it states both control types",
      "stops the text before the model reads it" in BRIEF_SRC
      and "find the capability gone" in BRIEF_SRC)
check("it says why capability removal is the durable one",
      "more persuadable than this one" in BRIEF_SRC)
check("and the student lab does NOT carry it", "Challenge 6 and Challenge 7" not in LAB_SRC)

# ---------------------------------------------------------------------------
# The KubeCon NA 2026 breakout brief (#501). A SEPARATE page from the 2-hour brief above: the demo-only cut
# laid out by run-of-show segment, with each shown beat's prompt, who sends it, the admin-terminal toggle
# where one applies, and the success marker. The run-of-show drives from it, so a missing block or a beat
# with no marker is a presenter on stage with nothing to read.
print("== the KubeCon brief has one block per shown beat, each copy-ready ==")
KUBECON = (REPO / "gitops/ai-layer/web/kubecon.html").read_text(encoding="utf-8")
ROS = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")

# The no-provisioning check reads the page BODY, with its source comments and <script> removed: the comments
# explain WHY provisioning content is kept off (so they name it on purpose), and the copy helper's own
# comment mentions the student lab it shares a contract with. Neither is anything a presenter sees.
_body = re.sub(r"<!--.*?-->", "", KUBECON, flags=re.S)
_body = re.sub(r"<script>.*?</script>", "", _body, flags=re.S)

# Every shown beat is a <article class="beat" data-beat="..." data-segment="...">. Collect the blocks per
# beat key; a beat could be shown in more than one segment, so key -> list of blocks.
beat_blocks: dict[str, list[str]] = {}
beat_segment: dict[str, str] = {}
for m in re.finditer(
    r'<article class="beat"\s+data-beat="([^"]+)"\s+data-segment="([^"]+)">(.*?)</article>',
    KUBECON, re.S,
):
    beat_blocks.setdefault(m.group(1), []).append(m.group(3))
    beat_segment.setdefault(m.group(1), m.group(2))

# The stage numbers the challenges Challenge 1 to 4 (#687). The data-beat keys keep the internal ids: Challenge 1 is
# C5, Challenge 2 (the Kubernetes catch-all) is C2, C3 and C1, Challenge 3 is C6, Challenge 4 is C7.
SHOWN_BEATS = ("C1", "C2", "C3", "C5", "C6", "C7", "off-topic", "on-topic")
for b in SHOWN_BEATS:
    check(f"the KubeCon brief shows a {b} block", b in beat_blocks)

# Each block carries a copy-ready prompt and a success marker.
for b in SHOWN_BEATS:
    for i, blk in enumerate(beat_blocks.get(b, [])):
        check(f"{b} block {i} has a copy-ready prompt",
              'class="prompt"' in blk and 'class="cp"' in blk)
        check(f"{b} block {i} has a success marker", 'class="marker"' in blk)

# The toggles, where one applies, on the private terminal, each inside its beat's block (C5, C6 and C7 in
# segments 2, 4 and 5; the on-topic guard in segment 6). C1, C2, C3 and the off-topic beat have no live toggle on
# purpose: the Kubernetes controls start armed on the private cluster and the public cluster is wide open.
BEAT_TOGGLE = {"C6": "guard-input-on", "C5": "guard-output-on", "C7": "guard-mcp-on", "on-topic": "guard-topic-on"}
for b, cmd in BEAT_TOGGLE.items():
    in_a_block = any(f'class="toggle"' in blk and cmd in blk for blk in beat_blocks.get(b, []))
    check(f"{b} carries its toggle ({cmd}) inside the beat block", in_a_block)

# The markers name the controls that actually fire (the dependencies this page was gated on): C1 egress,
# C2 the Kyverno registry allow-list, C3 KubeArmor's block AND its own alert (#497), and the signatures the
# guards scrub/produce.
check("C1 marker names the beacon count holding", "beacon" in KUBECON and "does <b>not</b> move" in KUBECON)
check("C2's admission rule is named, inside C6", "restrict-image-registries" in KUBECON)
check("C3 marker names KubeArmor's block AND its alert",
      "block-recipe-snoop" in KUBECON and '"Action":"Block"' in KUBECON)
check("C5 marker is the real CEO signature", "OPHELIA-THORN-TIBBY-TOP-SPIRE-No9" in KUBECON)
check("C6 marker is the withheld ticket, the room's Joker and both tiers (#640, #685)", "[input guard] withheld" in KUBECON
      and "joker-agatha-the-banshee" in KUBECON and "HC-666" in KUBECON
      and "restrict-image-registries" in KUBECON.split('data-beat="C6"', 1)[1])
check("the stage no longer runs the lab's ticket", "HC-7731" not in KUBECON and "maintenance-shell" not in KUBECON)
check("C7 marker is the MCP sentinel", "FAKE-MCP-EXFIL-sentinel-4c1d" in KUBECON)
check("on-topic marker is the burritos-only refusal", "I only talk burritos" in KUBECON)

# Each shown beat names its deterministic fallback, so a wandering prompt still proves the control.
for b in SHOWN_BEATS:
    has_fallback = any('class="fallback"' in blk for blk in beat_blocks.get(b, []))
    check(f"{b} names a fallback", has_fallback)

print("== it includes the projected feed and the observability surface, and no provisioning ==")
check("segment 1 points at the projected prompt feed /display", "/display" in KUBECON)
check("segments 2 to 5 point at the Datadog observability surface",
      "app.datadoghq.com/llm/traces" in KUBECON)
# No provisioning, claim-by-email or student-lab content on the demo page (run-of-show: it stays off).
for banned in ("provision", "claim a cluster", "claims a cluster", "claim one",
               "by email", "attendee", "student lab", "student challenge"):
    check(f"the page body carries no {banned!r}", banned.lower() not in _body.lower())

print("== the page follows the run-of-show's segments: Challenge 1 to 4 (#687) ==")
# The run-of-show's segment table, | # | Min | ..., against the page's <h2> chips, SEGMENT n · m min, in order.
ros_segments = [(int(n), int(m)) for n, m in re.findall(r"^\| (\d) \| (\d+) \| ", ROS, re.M)]
page_segments = [(int(n), int(m)) for n, m in re.findall(r'<span class="n">SEGMENT (\d) · (\d+) min</span>', KUBECON)]
check("the run-of-show's table has six segments that sum to 30 minutes",
      [n for n, _ in ros_segments] == [1, 2, 3, 4, 5, 6] and sum(m for _, m in ros_segments) == 30)
check(f"the page has the same segments, in order, with the same minutes (page {page_segments})",
      page_segments == ros_segments)
check("Challenge 1 (C5) is segment 2, Challenge 2 (C1 C2 C3) segment 3, Challenge 3 (C6) segment 4, "
      "Challenge 4 (C7) segment 5, the on-topic guard segment 6",
      [beat_segment.get(b) for b in ("C5", "C2", "C3", "C1", "C6", "C7", "on-topic")]
      == ["2", "3", "3", "3", "4", "5", "6"])
_order = [m.group(1) for m in re.finditer(r'<article class="beat"\s+data-beat="([^"]+)"', KUBECON)]
check("the challenges appear in the order shown: C5, then C2 C3 C1, then C6, then C7",
      all(b in _order for b in ("C5", "C1", "C6", "C7"))
      and _order.index("C5") < _order.index("C1") < _order.index("C6") < _order.index("C7"))
_titles = re.findall(r'<span class="n">SEGMENT \d · \d+ min</span> ([^<]+)</h2>', KUBECON)
check("the headings number the challenges Challenge 1 to 4, in order",
      [h.split(":")[0] for h in _titles if h.startswith("Challenge")] == [f"Challenge {n}" for n in (1, 2, 3, 4)],
      )
check("no visible heading names a C-number", not any(re.search(r"\bC\d\b", h) for h in _titles))
check("C4 is not on the page as a challenge (2026-10-28)", "C4" not in _body and "denial-of-wallet" not in _body.lower())
for b, n in (("C5", 1), ("C6", 3), ("C7", 4)):
    blk = " ".join(beat_blocks.get(b, []))
    check(f"{b} is played on the public bot and fixed on the private bot",
          "public bot" in blk and "private bot" in blk)
    check(f"{b} names its Datadog tab as Challenge {n}", f"Datadog Challenge {n} tab" in blk)
check("Challenge 1 teaches RBAC, and keeps the output guard as an optional second fix",
      "RBAC" in " ".join(beat_blocks.get("C5", [])) and "optional second fix" in " ".join(beat_blocks.get("C5", [])))
print("== the per-challenge pattern and the OWASP close (#687) ==")
check("the page states the pattern once: tee-up, play, attack, fix, keep trying",
      all(w in KUBECON for w in ("<b>tee-up</b>", "<b>play</b>", "<b>attack</b>", "<b>fix</b>", "<b>keeps trying</b>")))
_seg6 = KUBECON.split('<span class="n">SEGMENT 6', 1)[1]
_llm = ("LLM01</b> Prompt Injection", "LLM02</b> Sensitive Information Disclosure", "LLM03</b> Supply Chain",
        "LLM04 Data and Model Poisoning", "LLM05 Improper Output Handling", "LLM06</b> Excessive Agency",
        "LLM07 System Prompt Leakage", "LLM08 Vector and Embedding Weaknesses", "LLM09 Misinformation",
        "LLM10</b> Unbounded Consumption")
check("the close carries all ten 2025 OWASP LLM items, by their names on genai.owasp.org",
      all(x in " ".join(_seg6.split()) for x in _llm))
check("and the OWASP Kubernetes Top 10 is named", "OWASP Kubernetes Top 10" in _seg6 and "K04" in _seg6)
check("the close invites the room to break it (#690)", "You have our permission." in " ".join(_seg6.split()))
_ros6 = ROS.split("### Segment 6:", 1)[1].split("\n## ", 1)[0]
check("the run-of-show's close says the same", "LLM01 Prompt Injection" in _ros6 and "K05" in _ros6
      and "You have our permission." in _ros6)
# C6's two tiers are shown in one order on both pages (#676): Kyverno is armed from the start, so the private bot's
# deploy_app is refused at admission before guard-input-on, and after the toggle there is no deploy_app call left to
# deny. That is the order the probe runs (verify/kubecon_probe.py). The tier names stay the layers': the input
# classifier is the first tier, admission the second, behind it.
_ros_seg3 = ROS.split("### Segment 4:", 1)[1].split("### Segment 5:", 1)[0]
_ros_fix = " ".join(_ros_seg3.split("- **Fix, two tiers", 1)[1].split("\n- **", 1)[0].split())
_ros_row3 = next((ln for ln in ROS.splitlines() if ln.startswith("| 4 | ")), "")
_page_seg3 = " ".join(KUBECON.split('<span class="n">SEGMENT 4', 1)[1].split('<span class="n">SEGMENT 5', 1)[0].split())
_c6 = " ".join(" ".join(beat_blocks.get("C6", [])).split())
_premise = _page_seg3.split('<p class="premise">', 1)[1].split("</p>", 1)[0] if '<p class="premise">' in _page_seg3 else ""


def _before(text: str, first: str, then: str) -> bool:
    return first in text and then in text and text.index(first) < text.index(then)


check("the run-of-show's Challenge 3 row puts Kyverno before guard-input-on",
      _before(_ros_row3, "Kyverno armed", "`guard-input-on`"))
check("the run-of-show's C6 fix shows the admission denial, then guard-input-on",
      _before(_ros_fix, "denies the Joker image at admission", "Then `guard-input-on`"))
check("the run-of-show names admission the second tier and the input classifier the first",
      _before(_ros_fix, "That is the second tier", "`guard-input-on`, the first tier"))
check("the page's C6 premise puts admission control before guard-input-on",
      _before(_premise, "admission control", "guard-input-on"))
check("the page's C6 block shows the admission deny, then the toggle, then the withheld ticket",
      _before(_c6, "restrict-image-registries</code>", 'class="toggle"')
      and _before(_c6, 'class="toggle"', "[input guard] withheld"))
check("the page names the before-toggle marker the second tier and the after-toggle one the first",
      _before(_c6, "before the toggle (the second tier)", "after the toggle (the first tier)"))
check("C6's admission tier names the C2 fallback, not the retired workshop Beat 1 (#499)",
      "challenges/c2-villain-image/fallback.kubectl.sh" in " ".join(beat_blocks.get("C6", []))
      and "01-cncf-wall" not in KUBECON)
# The roster's terminals take the presenter login, sprouts (fleet.sh, verify/test_admin_actions.sh); the public
# bot shows no Terminal button (#645).
check("the page and the run-of-show give the private terminal the presenter login",
      "<code>sprouts</code> / <code>sprouts</code>" in KUBECON and "`sprouts` / `sprouts`" in ROS
      and "`agentic` / `agentic`" not in ROS)

print("== /kubecon reads at a glance (#639) ==")
# The page is read on stage, so only the cues stay up: prompt, toggle and success markers. The story,
# the notes and every fallback fold behind a disclosure, and a table gives the half hour in six rows.
_glance = re.search(r'<table class="glance">(.*?)</table>', KUBECON, re.S)
check("a glance table lists the six segments in order",
      _glance is not None
      and re.findall(r"<tr><td>(\d)</td>", _glance.group(1)) == ["1", "2", "3", "4", "5", "6"])
check("it names each challenge's toggle",
      _glance is not None and all(t in _glance.group(1) for t in
                                  ("guard-output-on", "guard-input-on", "guard-mcp-on", "guard-topic-on")))
_visible = re.sub(r"<details.*?</details>|<!--.*?-->|<style>.*?</style>|<script>.*?</script>", "",
                  KUBECON, flags=re.S)
check("every fallback is folded", '<div class="fallback">' in KUBECON
      and '<div class="fallback">' not in _visible)
check("every premise is folded", '<p class="premise">' in KUBECON
      and '<p class="premise">' not in _visible)
check("every prompt and toggle stays visible",
      KUBECON.count('<div class="prompt"') == _visible.count('<div class="prompt"')
      and KUBECON.count('<div class="toggle"') == _visible.count('<div class="toggle"'))
check("the visible page is under 2,000 words",
      len(re.sub(r"<[^>]+>", " ", _visible.split("<body>")[1]).split()) < 2000)

print("== the run-of-show links the page ==")
check("the run-of-show drives from /kubecon", "/kubecon" in ROS)
check("and names the page file", "gitops/ai-layer/web/kubecon.html" in ROS)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All instructor-brief checks passed.")
