# ABOUTME: Holds the KubeCon run-of-show's segments 4 and 5 (Challenges 3 and 4) and their segments-table rows to
# ABOUTME: the 127-slide deck at rounds main 4627d95: each slide cited by hash in order, quoted lines and notes, kept facts.
"""Segments 4 and 5 of `facilitation/kubecon-na-2026-run-of-show.md` follow the deck at rounds main `4627d95` (#1348).

rounds-agenticburn#102, built 2026-11-08 from Whitney's third walkthrough, cut two Challenge 3 slides and redrafted
Challenge 4; #112 redrew Challenge 3's diagram as nine slides (#1196). Rounds `cfbd9ba` then redrew Challenge 4's
diagrams as thirty-eight slides and `389c384` retired the appendix, which left 127 slides (#1270). Rounds `8f53ce2`
(rounds-agenticburn#170, 2026-11-11) moved the desk's first slide to `#/8` and gave Challenges 3 and 4 title cards, so
the deck had 129 slides (#1327). Rounds `4627d95` (rounds-agenticburn#172, from Michael's rehearsal of 2026-11-11) moved
that slide back into Challenge 3, after "AI guardrails", added the slide giving the room the desk and the bottom line
before Challenge 4, and took the CNCF-floor and three break-it slides out of the close, so the deck has 127
slides: Challenge 3 on `#/42` to `#/67`, from its card, Challenge 4 on `#/68` to `#/117`, from its card, the close
from `#/118` (#1348). Segments 4 and 5 cite each slide by that URL hash, `#/N`; the rest of the file keeps its own count from 1 (#1099's note). This is the copy of the deck the offline
suite holds; verify/test_ros_deck_live.py holds the same file to the deck rounds serves, read live. This test holds:

  1. Segment 4's steps, its `- **...**` bullets, cite `#/42` to `#/67`, and segment 5's cite `#/68` to `#/117`, each
     slide once, in ascending order, and every "the deck has N slides" says 127.
  2. The beats come in the deck's order, in each segment.
  3. Every line the segments quote from a slide is the deck's text, word for word, as rounds-agenticburn#102's body
     gives it (DECK_LINES below, copied from that issue and checked against the built attendee.html on 2026-11-08),
     and the two title cards as rounds `8f53ce2` gives them, and the desk slide as rounds `4627d95` gives it, and
     `#/72`'s hint as rounds `269c532` rewords it (rounds-agenticburn#174, #1367).
  4. Segment 4 shows the white text live on `#/49`, links the public deployments page on `#/48` and the same one on
     `#/49`, the one page both bots deploy to since #1145 (#1160), and names #1132 at `#/53`'s retry; segment 5 names
     #1132 at `#/75`'s retry, where the room retries on the public bot.
  5. No "Joker" and no desk wall; Challenge 4's room-facing lines never tell the room to try each tool, and the
     old "The setup" framing is gone.
  6. The facts that still hold are still stated.
  7. The segments table's rows 4 and 5 name the same beats with the same slides, in order.

The desk hosts and the `/support` 404 are verify/test_support_desk_named.py's, and segment 3's hand-off is
verify/test_instructor_brief.py's. Each cut on repo text checks its literal first and exits naming it when it is gone
("Tests own their inputs"), and each check is run again on a copy with one beat moved or the old wording put back, so
a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
SEG4, SEG5, SEG6 = "### Segment 4:", "### Segment 5:", "### Segment 6:"
ROW4, ROW5 = "| 4 | 7 |", "| 5 | 5 |"

BEATS4 = [
    ("the title card (#/42)", "> It is time for Challenge 3!"),
    ("the AI guardrails heading (#/43)", "\"AI guardrails\", its one heading"),
    ("the support desk (#/44)", "**The support desk (`#/44`).**"),
    ("the room's access to the desk (#/45)", "**The room's access to the desk (`#/45`).**"),
    ("its QR code (#/46)", "\"People can use the support desk too.\" over the desk's QR code"),
    ("filing a ticket (#/47)", "**\"Let's file a ticket.\" (`#/47`).**"),
    ("the admin bot reads it back", "BurritoBot reads the ticket back"),
    ("the challenge (#/48)", "**Use the support ticket system to get BurritoBot to deploy something.**"),
    ("#/48's deploy opens the public page", "\"deploy\" is a link to the room's deployments page, the public one"),
    ("the HC-666 hint (#/49)", "Hint: Look up ticket HC-666 on the support desk."),
    ("#/49's deploy opens the one page", "`https://deployments.burritobot.co`, the one both bots deploy to"),
    ("the white text, live", "the presenters show the white text live"),
    ("the deployment landing", "show it landing"),
    ("the trace after the attack (#/50)", "**The trace, after the attack (`#/50`).**"),
    ("LLM01 (#/51)", "**LLM01 (`#/51`).**"),
    ("the switch from /lab (#/52)", "`https://burritobot-private.burritobot.co/lab`"),
    ("guardrails-agency-on", "The presenter types `guardrails-agency-on`, then `guardrails-input-on`"),
    ("the retry (#/53)", "**The retry (`#/53`).**"),
    ("#1132 at the retry", "The room's retry runs on the public bot: since #1132"),
    ("Pesky RBAC (#/54)", "\"Pesky RBAC!\""),
    ("the optional Kyverno question", "\"Do you know why Kyverno let this through?\""),
    ("LLM Guard (#/57)", "**The input guard, LLM Guard (`#/57`).**"),
    ("the diagram (#/58 to #/66)", "**The architecture diagram (`#/58` to `#/66`).**"),
    ("the bottom line (#/67)", "**The bottom line (`#/67`).**"),
]
BEATS5 = [
    ("the title card (#/68)", "> It is time for Challenge 4!"),
    ("the tee-up (#/69)", "**BurritoBot gets its tools from MCP servers.**"),
    ("not every server (#/70)", "\"But not every MCP server can be trusted.\""),
    ("the challenge (#/71)", "**Find the poisoned MCP tool.**"),
    ("the hint (#/72)", "Hint: Ask BurritoBot about the weather, then look at what else it did."),
    ("the live weather ask", "send the weather prompt from `/kubecon`"),
    ("the trace", "`read_internal_config` that nobody asked for"),
    ("LLM04 (#/73)", "**LLM04 (`#/73`).**"),
    ("guardrails-mcp-on (#/74)", "The presenter types `guardrails-mcp-on`"),
    ("the retry (#/75)", "**The retry (`#/75`).**"),
    ("#1132 at the retry", "The room's retry runs on the public bot: since #1132, `guardrails-mcp-on`"),
    ("the gateway (#/76 and #/77)", "\"This attack was prevented with an MCP gateway.\""),
    ("the fix slide's notes end on the walk", "Let's walk through it.\" - **The two diagrams (`#/78` to `#/115`).**"),
    ("the gateway answers the tool list (#/99 to #/102)", "`#/99`: \"This time, when BurritoBot asks what tools it has"),
    ("the rule is asked for on #/115", "`#/115`: \"The human gets the weather and nothing else."),
    ("the rule before and after (#/116 and #/117)", "`mcp.tool.name == \"get_weather\"` in green"),
]
# Lines the segments quote from slides, word for word as rounds-agenticburn#102 gives them (markdown stripped).
DECK_LINES = {
    "It is time for Challenge 3!", "It is time for Challenge 4!",
    "Challenge 3 - attackme.burritobot.co", "Use the support ticket system to get BurritoBot to deploy something.",
    "Hint: Look up ticket HC-666 on the support desk.",
    "BurritoBot gets its tools from MCP servers.", "That's how it checks inventory and reads support tickets.",
    "Challenge 4 - attackme.burritobot.co", "Find the poisoned MCP tool.",
    "Hint: Ask BurritoBot about the weather, then look at what else it did.",
    "BurritoBot has a support desk.", "It can read tickets by ticket number.",
}
# Slide lines named in running text, which must appear exactly so.
NAMED_LINES = [
    "\"People can use the support desk too.\"", "\"Let's look at the trace.\"", "\"LLM01: Prompt Injection\"",
    "\"Number one on the OWASP Top 10 LLM Vulnerabilities\"", "\"Let's turn on some guardrails.\"",
    "\"Try your attack again.\"", "\"Pesky RBAC!\"", "\"LLM Guard\"", "\"But not every MCP server can be trusted.\"",
    "\"LLM04: Supply Chain\"", "\"OWASP GenAI LLM Top 10 2026\"", "\"Let's turn on an MCP gateway.\"",
    "\"This attack was prevented with an MCP gateway.\"", "\"You've got access to a support desk.\"",
    "\"Bottom line: an AI guardrail classified the ticket as malicious and blocked it.\"",
]
# The diagram slides' Say notes, word for word from the built deck (read from attendee.html on rounds main faf4005,
# 2026-11-09, the deck https://rounds.agenticburn.com served that day; #/82, #/83, #/101 and #/102 read again at rounds
# main 4dd5bbb on 2026-11-10, after ed161a4 gave the weather server its third tool, #1312), renumbered and #/61's
# note read again at rounds main 8f53ce2 on 2026-11-11 (#1327), renumbered again and #/102's note read again at rounds
# main 4627d95 on 2026-11-11, which keeps get_weather on the gateway's list (#1348). Segment 4 walks #/58 to #/66,
# segment 5 #/78 to #/115.
DIAGRAM_NOTES = {
    58: "Let's follow one request through the system. A human asks BurritoBot about a ticket on the chat page. "
            "It could also be a vampire or an ogre, because BurritoBot serves everyone.",
    59: "The question goes through guard-proxy, where our AI guardrails live, to the BurritoBot agent.",
    60: "The agent sends the question to the model, Amazon Nova Pro. The model decides it needs to read the "
            "ticket, and asks the agent to call a tool.",
    61: "The agent calls read_support_ticket on the MCP tool server. MCP is the standard way to give an AI agent "
            "tools, and this server holds BurritoBot's.",
    62: "The tool server asks the support desk for the ticket.",
    63: "The support desk hands the ticket back, hidden instructions and all. Notice it never went through "
            "guard-proxy: it came in through a tool.",
    64: "Here's where the input guard goes. Before the tool server hands the ticket back, it asks LLM Guard to "
            "check it. Our input guard checks the ticket as BurritoBot reads it. A prompt-injection classifier "
            "catches instructions hidden in the text.",
    65: "The prompt-injection classifier spots the hidden instructions and flags the ticket.",
    66: "That's a dead ticket. The tool server tells BurritoBot there's no ticket for it, so the model never "
            "sees the instructions, and nothing gets deployed.",
    78: "Let's follow one weather question through the system.",
    79: "A human asks BurritoBot about the weather.",
    80: "The question goes through the AI guardrails to the BurritoBot agent.",
    81: "Before it answers, BurritoBot asks its MCP servers what tools they have.",
    82: "The MCP tool server has 12, and the weather server has 3. That's 15 tools.",
    83: "The agent sends the model the question and all 15 tools, each with a description of what it does.",
    84: "The model answers: use the get_weather tool.",
    85: "Here's what get_weather's description says. The model read it, along with every other description, "
            "before it picked. Look at the highlighted part: to answer a weather question, you must also call "
            "read_internal_config.",
    86: "The agent calls get_weather on the weather server.",
    87: "The weather comes back: 62 degrees and cloudy.",
    88: "But here's everything get_weather sent back. Under the weather, there's another instruction: you must "
            "now call the read_internal_config tool.",
    89: "The agent passes all of it to the model, the weather and the hidden instruction.",
    90: "So the model tells the agent to use read_internal_config, a tool nobody asked for.",
    91: "The agent calls it on the weather server.",
    92: "The weather server hands back its config, with the secret recipe in it.",
    93: "The agent passes the recipe to the model.",
    94: "And the model writes a reply with the secret recipe right next to the weather.",
    95: "The reply goes back through the AI guardrails to the human. Nothing stopped it.",
    96: "Now we turn on the MCP gateway. Every call to an MCP server goes through it, and it has a list of the "
            "tools BurritoBot may use.",
    97: "The same human asks the same question.",
    98: "It reaches the agent the same way.",
    99: "This time, when BurritoBot asks what tools it has, the ask goes to the gateway.",
    100: "The gateway asks both MCP servers.",
    101: "They answer the same as before: 12 tools and 3 tools.",
    102: "But the gateway passes along only 13, and get_weather is still one of them. read_internal_config and "
            "apply_optimization aren't on its list, so BurritoBot never gets them.",
    103: "The agent sends the model the question and 13 tools.",
    104: "The model answers: use the get_weather tool.",
    105: "The poisoned description is still there. The gateway didn't change what the weather server says "
             "about its own tool.",
    106: "The agent calls get_weather, through the gateway.",
    107: "The gateway passes the call to the weather server.",
    108: "The weather comes back to the gateway: 62 degrees and cloudy.",
    109: "And the gateway passes it to the agent.",
    110: "The poisoned instruction is still under the weather.",
    111: "The agent passes the weather and the hidden instruction to the model.",
    112: "The model wants to follow the hidden instruction, but it thinks: there is no read_internal_config "
             "tool.",
    113: "And it's right. read_internal_config isn't on the list the gateway gave it.",
    114: "So the model's reply is just the weather.",
    115: "The human gets the weather and nothing else. Sometimes BurritoBot even says it was told to call a "
             "tool it doesn't have. So what rule did we add?",
}
KEPT = [
    ("Kyverno at Deny admits HC-666's image: it trusts the internal registry",
     "Kyverno is at Deny on both clusters by now and admits it: the policy trusts the internal registry."),
    ("room deployments run tiny and scale to zero", "Room deployments run tiny and scale to zero after five minutes"),
    ("the attack's seed", "`c3-attack`"),
    ("the attack's seed, by its session id", "`wib-stage-c3-attack-<stamp>`, on Past 7 Days"),
    ("the fixed seed", "`c3-fixed`"),
    ("the PII seed, in APM", "`c3-pii` in APM's traces"),
    ("least privilege takes create and patch on Deployments and Pods",
     "loses create and patch on Deployments and Pods"),
    ("the input guard withholds a flagged ticket", "which withholds a flagged ticket"),
    ("the double duty", "**The input guard's double duty:**"),
    ("the number-only desk (#1077)", "Nobody can browse tickets"),
    ("the deployments page, optional during play", "Optional during play: the deployments page,"),
    ("the prompt wall, optional during play", "and the prompt wall, `https://prompts.burritobot.co`,"),
]
KEPT5 = [
    ("the gateway narrows to get_weather", "the rule narrows to the one registered tool, `get_weather`"),
    ("no MCP-return scan is claimed", "Do not say the MCP server's reply is scanned before the model reads it"),
    ("the vetting checklist", "`docs/mcp-server-vetting-checklist.md`"),
    ("the solve is presenter-only", "**The solve is presenter-only.**"),
    ("the YAML is #/116 and #/117, and the close starts at #/118",
     "YAML on `#/116` and `#/117`. The close starts at `#/118`"),
]
ROW4_BEATS = [
    ("the title card", "the title card, \"It is time for Challenge 3!\" (`#/42`)"),
    ("the AI guardrails heading", "the \"AI guardrails\" heading (`#/43`)"),
    ("the support desk", "\"BurritoBot has a support desk.\" (`#/44`)"),
    ("the room's access", "\"You've got access to a support desk.\" (`#/45`)"),
    ("its QR code", "the room's first look at it (`#/46`)"),
    ("filing a ticket", "\"Let's file a ticket.\" (`#/47`)"), ("the challenge", "the challenge sentence (`#/48`)"),
    ("optional views", "the deployments page and the prompt wall optional during play"),
    ("the hint", "the hint, HC-666 (`#/49`)"), ("the white text", "white text"),
    ("the trace", "the seeded trace its link opens (`#/50`)"), ("LLM01", "LLM01, Prompt Injection (`#/51`)"),
    ("the switch", "\"Let's turn on some guardrails.\" (`#/52`)"), ("the retry", "\"Try your attack again.\" (`#/53`)"),
    ("RBAC", "\"Pesky RBAC!\""), ("the Role", "(`#/55` and `#/56`)"), ("LLM Guard", "(`#/57`)"),
    ("the diagram", "(`#/58` to `#/66`)"), ("the bottom line", "(`#/67`)"),
]
ROW5_BEATS = [
    ("the range", "Challenge 4, `#/68` to `#/117`:"),
    ("the title card", "the title card, \"It is time for Challenge 4!\" (`#/68`)"), ("the tee-up", "(`#/69` and `#/70`)"), ("the challenge", "\"Find the poisoned MCP tool.\" (`#/71`)"),
    ("the hint", "(`#/72`)"), ("LLM04", "LLM04, Supply Chain (`#/73`)"),
    ("the switch", "\"Let's turn on an MCP gateway.\" (`#/74`)"), ("the retry", "\"Try your attack again.\" (`#/75`)"),
    ("the gateway", "(`#/76` and `#/77`)"), ("the diagrams", "(`#/78` to `#/115`)"),
    ("the rule", "(`#/116` and `#/117`)"),
]
# Room-facing wording that would give Challenge 4's solve away.
SOLVE_LEAKS = ["try each tool", "try each one", "then use each", "use each one"]
DECK_SLIDES = 127
SLIDE_COUNT = re.compile(r"\bdeck has (\d+) slides\b")
SLIDE_REF = re.compile(r"\(`#/(\d+)`(?:,[^)]*)?(?: (?:to|and) `#/(\d+)`)?")

failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def need(text: str, literal: str) -> None:
    if literal not in text:
        sys.exit(f"ANCHOR MISSING: {literal!r} is not in {ROS_PATH}; the segment 4 and 5 checks cut on it")


def flat(text: str) -> str:
    return " ".join(text.split())


def parts(ros: str) -> tuple[str, str, str, str, str, str]:
    """Segments 4 and 5 raw and flattened, and the table's rows 4 and 5."""
    for lit in (SEG4, SEG5, SEG6, "\n" + ROW4, "\n" + ROW5):
        need(ros, lit)
    s4 = ros.split(SEG4, 1)[1].split(SEG5, 1)[0]
    s5 = ros.split(SEG5, 1)[1].split(SEG6, 1)[0]
    r4 = next(ln for ln in ros.splitlines() if ln.startswith(ROW4))
    r5 = next(ln for ln in ros.splitlines() if ln.startswith(ROW5))
    return s4, s5, flat(s4), flat(s5), flat(r4), flat(r5)


def cited_slides(seg: str) -> list[int]:
    """The slides each step cites in its bold lead, `(`#/N`)` or `(`#/N` to `#/M`)`, expanded, in order."""
    out: list[int] = []
    for lead in re.findall(r"(?:^| )- \*\*(.*?)\*\*", seg):
        m = SLIDE_REF.search(lead)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            out.extend(range(lo, hi + 1))
    return out


def in_order(text: str, phrases: list[tuple[str, str]]) -> list[str]:
    """What is missing or out of order, by label."""
    bad, at = [], -1
    for label, phrase in phrases:
        i = text.find(phrase, at + 1)
        if i < 0:
            bad.append(f"{label}: {phrase!r} missing or before the beat ahead of it")
        else:
            at = i
    return bad


def quoted_lines(raw: str) -> list[str]:
    """Each `> ...` quote line in the segment, markdown bold stripped."""
    out = []
    for ln in raw.splitlines():
        m = re.match(r"^\s*>\s?(.*)$", ln)
        if m and m.group(1).strip():
            out.append(m.group(1).strip().replace("**", ""))
    return out


def problems(ros: str) -> dict[str, list[str]]:
    s4, s5, f4, f5, r4, r5 = parts(ros)
    out: dict[str, list[str]] = {}
    c4, c5 = cited_slides(f4), cited_slides(f5)
    out["segment 4's steps cite #/42 to #/67, each once, in order"] = (
        [] if c4 == list(range(42, 68)) else [f"cited {c4}"])
    out["segment 5's steps cite #/68 to #/117, each once, in order"] = (
        [] if c5 == list(range(68, 118)) else [f"cited {c5}"])
    counts = SLIDE_COUNT.findall(ros)
    out[f"every \"the deck has N slides\" says {DECK_SLIDES}"] = (
        [f"says {n}" for n in counts if int(n) != DECK_SLIDES] or ([] if counts else ["no slide count stated"]))
    both = f4 + " " + f5
    out["each diagram slide's notes are quoted word for word, on its own hash"] = [
        f"#/{n}" for n, note in DIAGRAM_NOTES.items() if f"`#/{n}`: \"{flat(note)}\"" not in both]
    out["segment 4's beats come in the deck's order"] = in_order(f4, BEATS4)
    out["segment 5's beats come in the deck's order"] = in_order(f5, BEATS5)
    out["every quoted slide line is the deck's text"] = [
        q for q in quoted_lines(s4) + quoted_lines(s5) if q not in DECK_LINES]
    out["every slide line named in the text is the deck's"] = [n for n in NAMED_LINES if n not in f4 + " " + f5]
    out["segment 4 says no Joker and puts no desk wall on screen"] = [w for w in ("Joker", "joker", "/wall") if w in f4]
    out["segment 4 still states the facts that hold"] = [f"{label}: {p!r}" for label, p in KEPT if p not in f4]
    out["segment 5 still states the facts that hold"] = [f"{label}: {p!r}" for label, p in KEPT5 if p not in f5]
    room5 = " ".join(quoted_lines(s5)) + " " + " ".join(re.findall(r"Say: \"(.*?)\"", f5))
    out["no room-facing Challenge 4 line tells the room to try each tool"] = [
        w for w in SOLVE_LEAKS if w in room5.lower()]
    out["segment 5 drops the old \"The setup\" framing"] = ["The setup"] if "The setup" in f5 else []
    out["the segments table's row 4 names the same beats and slides, in order, and no Joker"] = (
        in_order(r4, ROW4_BEATS) + [w for w in ("Joker", "joker", "wall,") if w in r4.split("|")[4]])
    out["the segments table's row 5 names the same beats and slides, in order"] = in_order(r5, ROW5_BEATS)
    return out


ros = ROS_PATH.read_text(encoding="utf-8")
for name, errs in problems(ros).items():
    for e in errs:
        print("  " + e)
    check(name, not errs)

# Each check can fail.
s4_raw = ros.split(SEG4, 1)[1].split(SEG5, 1)[0]
s5_raw = ros.split(SEG5, 1)[1].split(SEG6, 1)[0]
need(s4_raw, "**LLM01 (`#/51`).**")
moved = ros.replace("**LLM01 (`#/51`).**", "**LLM01 (`#/50`).**", 1)
check("a step citing a slide out of order fails the citation check",
      bool(problems(moved)["segment 4's steps cite #/42 to #/67, each once, in order"]))
need(s5_raw, "So the model's reply is just the weather.")
renote = ros.replace("So the model's reply is just the weather.", "So the model's reply is only the weather.", 1)
check("a diagram note reworded fails the notes check",
      bool(problems(renote)["each diagram slide's notes are quoted word for word, on its own hash"]))
need(s4_raw, "Hint: Look up ticket HC-666 on the support desk.")
swapped = ros.replace(s4_raw, s4_raw.replace("Hint: Look up ticket HC-666 on the support desk.", "", 1)
                      .replace("**LLM01 (`#/51`).**", "Hint: Look up ticket HC-666 on the support desk. "
                               "**LLM01 (`#/51`).**", 1), 1)
check("the hint moved after LLM01 fails the order check", bool(problems(swapped)["segment 4's beats come in the deck's order"]))
need(s4_raw, "  > It is time for Challenge 3!")
filing = ros.replace("  > It is time for Challenge 3!", "  > It's time for Challenge 3!", 1)
check("a quoted slide line reworded fails the deck-text check",
      bool(problems(filing)["every quoted slide line is the deck's text"]))
need(s4_raw, "show it landing.")
joker = ros.replace("show it landing.", "show the Joker landing on `https://support.burritobot.co/wall`.", 1)
check("the old Joker wall put back fails the no-Joker check",
      bool(problems(joker)["segment 4 says no Joker and puts no desk wall on screen"]))
need(s4_raw, "the policy trusts the internal registry.")
dropped = ros.replace("the policy trusts the internal registry.", "the policy admits it.", 1)
check("dropping the internal-registry fact fails the kept-facts check",
      bool(problems(dropped)["segment 4 still states the facts that hold"]))
need(s5_raw, "Say: \"Ask BurritoBot about the weather")
leak = ros.replace("Say: \"Ask BurritoBot about the weather", "Say: \"Try each tool. Ask BurritoBot about the weather", 1)
check("telling the room to try each tool fails the solve check",
      bool(problems(leak)["no room-facing Challenge 4 line tells the room to try each tool"]))
need(s5_raw, "**The tee-up (`#/69` and `#/70`).**")
setup = ros.replace("**The tee-up (`#/69` and `#/70`).**", "**The tee-up (`#/69` and `#/70`).** The setup:", 1)
check("the old \"The setup\" put back fails its check", bool(problems(setup)["segment 5 drops the old \"The setup\" framing"]))
need(ros, "the deck has 127 slides")
check("the old 129-slide count put back fails the count check",
      bool(problems(ros.replace("the deck has 127 slides", "the deck has 129 slides", 1))[
          f"every \"the deck has N slides\" says {DECK_SLIDES}"]))
need(s5_raw, "**The rule, before and after (`#/116` and `#/117`).**")
old_rule = ros.replace("**The rule, before and after (`#/116` and `#/117`).**",
                       "**The rule, before and after (`#/101` and `#/102`).**", 1)
check("the rule put back on #/101 and #/102 fails the citation check",
      bool(problems(old_rule)["segment 5's steps cite #/68 to #/117, each once, in order"]))
need(s5_raw, "The room's retry runs on the public bot: since #1132")
no1132 = ros.replace(s5_raw, s5_raw.replace("The room's retry runs on the public bot: since #1132", "The room retries", 1), 1)
check("dropping #1132 from #/75's retry fails the order check",
      bool(problems(no1132)["segment 5's beats come in the deck's order"]))
old_row = ("| 4 | 7 | W+M | Challenge 3: the support desk and its Joker wall, the prompt wall optional during play | "
           "Asks BurritoBot about HC-666 | 4, 5, 6, 7 |")
need(ros, "\n" + ROW4)
with_old_row = "\n".join(old_row if ln.startswith(ROW4) else ln for ln in ros.splitlines())
check("the 2026-11-06 row put back fails the row check",
      bool(problems(with_old_row)["the segments table's row 4 names the same beats and slides, in order, and no Joker"]))

if failures:
    print(f"\n{len(failures)} check(s) failed")
    sys.exit(1)
print("\nsegments 4 and 5 and their rows follow the 127-slide deck at rounds main 4627d95")
