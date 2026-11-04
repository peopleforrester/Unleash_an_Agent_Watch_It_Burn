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
RES = "\n".join((REPO / p).read_text(encoding="utf-8")  # the Agent has its own bundle since #707
                for p in ("gitops/ai-layer/resources.yaml", "gitops/workshop-agent/agent.yaml"))
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
BEAT_TOGGLE = {"C6": "guard-input-on", "C5": "guard-rbac-on", "C7": "guard-mcp-on", "on-topic": "guard-topic-on"}
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
check("C6 marker is the withheld ticket, the room's Joker and both fixes (#640, #685, #775)",
      "[input guard] withheld" in KUBECON and "joker-agatha-the-banshee" in KUBECON and "HC-666" in KUBECON
      and "answers Forbidden" in KUBECON.split('data-beat="C6"', 1)[1].split("</article>", 1)[0])
# The room's Joker pages live on the maintenance-shell host, under joker-<name> (#775); the lab's own Deployment of
# that name, and its ticket, are not on the stage.
check("the stage no longer runs the lab's ticket", "HC-7731" not in KUBECON
      and re.sub(r"https://maintenance-shell-attackme\.burritobot\.co/joker-", "", KUBECON).count("maintenance-shell") == 0)
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
# No provisioning, claim-by-email or student-lab content on the demo page (run-of-show: it stays off). The prompts
# are what the room sends, and Challenge 2's Tron ask (#773) is about a festival's attendees, so they are left out.
_unprompted = re.sub(r'<div class="prompt".*?</div>', "", _body, flags=re.S)
for banned in ("provision", "claim a cluster", "claims a cluster", "claim one",
               "by email", "attendee", "student lab", "student challenge"):
    check(f"the page body carries no {banned!r} outside the prompts", banned.lower() not in _unprompted.lower())

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
# Michael, 2026-10-31: RBAC is Challenge 1's only fix, run as guard-rbac-on; the output guard is not a second fix.
check("Challenge 1 teaches RBAC as its only fix, run with guard-rbac-on, and offers no output guard",
      "RBAC" in " ".join(beat_blocks.get("C5", [])) and "guard-rbac-on" in " ".join(beat_blocks.get("C5", []))
      and "guard-output-on" not in " ".join(beat_blocks.get("C5", [])))
check("Challenge 3 runs least privilege as guard-agency-on, and admission is not one of its fixes (#775)",
      "guard-agency-on" in " ".join(beat_blocks.get("C6", []))
      and "guard-admission-on" not in " ".join(beat_blocks.get("C6", [])))
print("== the per-challenge pattern and the OWASP close (#687) ==")
# Since the 2026-11-01 slide-by-slide review (#776, #818) the room tries first and each trace follows the
# presenters' attack; the page's pattern line follows the run-of-show's numbered pattern (#848).
_PAT_ANCHOR = '<p class="note">Every challenge runs one pattern:'
if _PAT_ANCHOR not in KUBECON:
    sys.exit(f"anchor {_PAT_ANCHOR!r} is not in gitops/ai-layer/web/kubecon.html: reword the test with it")
_pat = KUBECON.split(_PAT_ANCHOR, 1)[1].split("</p>", 1)[0]
_steps = [m.group(1) for m in re.finditer(r"<b>([^<]+)</b>", _pat)]
check("the page states the pattern once, in the run-of-show's order: challenge slide, hint, attack, trace, fix, "
      "keep trying (#848)",
      _steps == ["challenge slide", "hint", "attack", "trace", "fix", "keeps trying"])
check("the trace comes after the presenters' attack, not before the room plays (#776, #818, #848)",
      _steps.index("attack") < _steps.index("trace") and "before the room plays" not in _pat
      and "<b>play</b>" not in _pat and "<b>tee-up</b>" not in _pat)
_ROS_PAT_ANCHOR = "Every challenge runs one pattern:"
if _ROS_PAT_ANCHOR not in ROS:
    sys.exit(f"anchor {_ROS_PAT_ANCHOR!r} is not in facilitation/kubecon-na-2026-run-of-show.md: reword the test with it")
_ros_pat = ROS.split(_ROS_PAT_ANCHOR, 1)[1].split("\n\n", 2)[1]
check("and the run-of-show's numbered pattern runs in the same order",
      [re.sub(r"[:,]$", "", s) for s in re.findall(r"^\d\. \*\*([^*]+)\*\*", _ros_pat, re.M)]
      == ["Challenge slide", "Hint slide", "Attack", "Trace", "Fix", "Keep trying"])
check("the KubeCon opening carries no deleted-cluster story (#740)",
      "deleted-cluster" not in KUBECON and "Cold open" not in KUBECON
      and "deleted-cluster hook" not in ROS and "### Segment 1: Opening" in ROS)
# Since the 2026-11-01 review (#776, #820, #821) segment 2 runs no fix, and segment 3's guardrails-on (#774) turns
# all four Kubernetes layers on together, RBAC among them. The cut table's rows follow that flow (#847).
_CUT_ROW_ANCHORS = ("| Challenge 1, the CEO's record (", "| Challenge 2, the Kubernetes catch-all (")
_cut_rows = {a: next((ln for ln in ROS.splitlines() if ln.startswith(a)), None) for a in _CUT_ROW_ANCHORS}
for _a, _row in _cut_rows.items():
    if _row is None:
        sys.exit(f"anchor {_a!r} is not a row in facilitation/kubecon-na-2026-run-of-show.md: reword the test with it")
_cut1, _cut2 = (_cut_rows[a] for a in _CUT_ROW_ANCHORS)
check("Challenge 1's cut-table row runs no fix in segment 2, has RBAC arrive with guardrails-on, and offers no "
      "output guard (#739, #847)",
      "output guard optional" not in ROS and "no fix in segment 2" in _cut1 and "`guardrails-on`" in _cut1
      and "no output guard" in _cut1 and "guard-rbac-on" not in _cut1)
check("Challenge 2's cut-table row has guardrails-on turn on all four layers, not name them untoggled (#847)",
      "`guardrails-on`" in _cut2 and all(w in _cut2 for w in ("RBAC", "Kyverno", "KubeArmor", "NetworkPolicy"))
      and "not toggled" not in _cut2)
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
# Segment 2 names LLM06 as exploited in Challenge 1 (#820, deck slide 13), so the close maps LLM06 from Challenge 1
# on, on both pages (#842).
_ros2 = ROS.split("### Segment 2:", 1)[1].split("### Segment 3:", 1)[0]
check("segment 2 names LLM06, Excessive Agency, as what Challenge 1 exploited (#820)",
      "**LLM06, Excessive Agency**" in _ros2)
check("so the close maps LLM06 to Challenges 1 to 4 in the run-of-show and on the page (#842)",
      "LLM06 Excessive Agency (Challenges 1 to 4)" in " ".join(_ros6.split())
      and "LLM06</b> Excessive Agency (Challenges 1 to 4)" in " ".join(_seg6.split())
      and "Challenges 2 to 4" not in _ros6 and "Challenges 2 to 4" not in _seg6)
# #849 settled LLM06 at Challenges 1 to 4 against the deck's "Challenges 1, 2": since #775, Challenge 3's fix is least
# privilege, which segment 4 names LLM06 on both pages, and Challenge 4's fix takes an unneeded tool away. The deck's
# table (rounds-agenticburn) is the copy that follows.
_page_seg4 = " ".join(KUBECON.split('<span class="n">SEGMENT 4', 1)[1].split('<span class="n">SEGMENT 5', 1)[0].split())
check("and Challenge 3's least-privilege fix is named LLM06, Excessive Agency, on the page too (#849)",
      "guard-agency-on</code>, takes Deployments away from the bot (OWASP LLM06, Excessive Agency)" in _page_seg4)
# C6's two fixes are shown in one order on both pages (#775): HC-666's image is the internal registry's, which
# Kyverno trusts, so the Joker lands with the guardrails on. Least privilege comes first, so the private bot's
# deploy_app is Forbidden before guard-input-on, and after the toggle there is no deploy_app call left to refuse.
# That is the order the probe runs (verify/kubecon_probe.py).
_ros_seg3 = ROS.split("### Segment 4:", 1)[1].split("### Segment 5:", 1)[0]
_ros_fix = " ".join(_ros_seg3.split("- **Fix, two AI-era layers", 1)[1].split("\n- **", 1)[0].split())
_ros_row3 = next((ln for ln in ROS.splitlines() if ln.startswith("| 4 | ")), "")
_page_seg3 = " ".join(KUBECON.split('<span class="n">SEGMENT 4', 1)[1].split('<span class="n">SEGMENT 5', 1)[0].split())
_c6 = " ".join(" ".join(beat_blocks.get("C6", [])).split())
_premise = _page_seg3.split('<p class="premise">', 1)[1].split("</p>", 1)[0] if '<p class="premise">' in _page_seg3 else ""


def _before(text: str, first: str, then: str) -> bool:
    return first in text and then in text and text.index(first) < text.index(then)


check("the run-of-show's Challenge 3 row puts guard-agency-on before guard-input-on",
      _before(_ros_row3, "`guard-agency-on`", "`guard-input-on`") and "guard-admission-on" not in _ros_row3)
check("the run-of-show's C6 fix says admission is not one of them, shows the Forbidden, then guard-input-on",
      _before(_ros_fix, "admission is not one of them", "Run `guard-agency-on`")
      and _before(_ros_fix, "the Kubernetes API answers Forbidden", "Then `guard-input-on`"))
check("the run-of-show names least privilege OWASP LLM06, Excessive Agency",
      "OWASP LLM06, Excessive Agency" in _ros_fix)
check("the run-of-show says the Joker lands with Kyverno at Deny, from a registry it trusts",
      "Kyverno is at Deny on both clusters by now and admits it" in " ".join(_ros_seg3.split()))
check("the page's C6 premise puts least privilege before guard-input-on, and says Kyverno trusts the image",
      _before(_premise, "guard-agency-on", "guard-input-on") and "the internal registry Kyverno trusts" in _premise)
check("the page's C6 block runs guard-agency-on, shows the Forbidden, then guard-input-on, then the withheld ticket",
      _before(_c6, "guard-agency-on", "answers Forbidden")
      and _before(_c6, "answers Forbidden", "guard-input-on")
      and _before(_c6, "guard-input-on", "[input guard] withheld"))
check("the page names the before-toggle marker least privilege and the after-toggle one the input guard",
      _before(_c6, "before the toggle (least privilege)", "after the toggle (the input guard)"))
check("C6's least-privilege fallback asks the API whether workshop-mcp may create Deployments, without the model",
      "auth can-i create deployments --as=system:serviceaccount:agent:workshop-mcp" in _c6
      and "01-cncf-wall" not in KUBECON)
check("the page hands each person their own Joker page and the deployments page",
      "https://maintenance-shell-attackme.burritobot.co/joker-</code> plus their name" in _c6
      and "https://deployments.burritobot.co</code> under their witch name" in _c6)
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
                                  ("guard-rbac-on", "guard-agency-on", "guard-input-on", "guard-mcp-on",
                                   "guard-topic-on")))
_visible = re.sub(r"<details.*?</details>|<!--.*?-->|<style>.*?</style>|<script>.*?</script>", "",
                  KUBECON, flags=re.S)
check("every fallback is folded", '<div class="fallback">' in KUBECON
      and '<div class="fallback">' not in _visible)
check("every premise is folded", '<p class="premise">' in KUBECON
      and '<p class="premise">' not in _visible)
check("every prompt and toggle stays visible",
      KUBECON.count('<div class="prompt"') == _visible.count('<div class="prompt"')
      and KUBECON.count('<div class="toggle"') == _visible.count('<div class="toggle"'))
# 2,100 since #773: Challenge 2's ask is the 2026-11-01 Tron prompt and its follow-up, word for word (83 words,
# where the promo-mascot prompt was 41), and its marker was cut to one line to make room.
check("the visible page is under 2,100 words",
      len(re.sub(r"<[^>]+>", " ", _visible.split("<body>")[1]).split()) < 2100)

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
