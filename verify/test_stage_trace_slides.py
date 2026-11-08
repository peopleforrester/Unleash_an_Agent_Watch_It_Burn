# ABOUTME: Holds each attack seed's expected tool spans in verify/stage_traces.py's SEEDS, in order, to what its slide's
# ABOUTME: notes say the Datadog trace shows (#1138), and judge_spans to that order on start_ns.
"""#1138, part of #1130: each challenge's slide opens Datadog on a pre-seeded attack trace, and SEEDS names the tool
spans that trace must carry. This test holds the four attack seeds to the slides that open them:

    #/11  "Ophelia Thorn"              c1-attack  the Secret read: get_vault_entry
    #/26  the presenter opens Datadog  c2-attack  run_shell
    #/48  "Let's look at the trace."   c3-attack  read_support_ticket, then deploy_app
    #/68  "tools"                      c4-attack  get_weather, then read_internal_config

Each slide's note is quoted below word for word from the deck (rounds-agenticburn attendee.html at 9c80fb7a, read
2026-11-08; slide numbers are the URL hash, from 0). The deck is another repo, so the run-of-show's step for each
trace, this repo's copy of those notes, is read too, and the tool names it gives must be the same, in the same order.
Slide 11's note names no tool ("show the pre-seeded trace where it works"); its run-of-show step calls it the Secret
read, and workshop-mcp's get_vault_entry is the tool that reads a Secret.

Then judge_spans: a trace with the spans in the slide's order passes, the same spans in the other order fail, and a
span with no start_ns fails rather than passing on list order. It is run on run 17405's real Challenge 3 trace too.
Every check is shown failing on a changed SEEDS, a changed note and a changed run-of-show."""
from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import stage_traces as st  # noqa: E402

failures: list[str] = []
ROS_REL = "facilitation/kubecon-na-2026-run-of-show.md"
MCP_REL = "gitops/ai-layer/workshop-mcp-server.py"
FIXTURE_REL = "verify/fixtures/llmobs-chat-judge/chat-098fcb00.json"
# The tool that reads a Secret, and the line of its docstring that says so.
SECRET_READ = "get_vault_entry"
SECRET_DOC = 'def get_vault_entry(name: str = "") -> str:\n    """REAL read of a Secret'

# slide hash, the link that opens Datadog, the seed, the note's sentence on the trace (word for word), the spans in
# the order the trace shows them, and the run-of-show's step for that trace (from its first words to the next step's).
SLIDES = (
    ("#/11", "Ophelia Thorn", "c1-attack",
     "Click Ophelia Thorn to open Datadog and show the pre-seeded trace where it works.",
     (SECRET_READ,), ("Show the pre-seeded Challenge 1 trace where it works", "**No fix in this segment")),
    ("#/26", "the presenter opens Datadog", "c2-attack",
     "Then open Datadog and show the pre-seeded Challenge 2 trace: the run_shell call that reads the recipe.",
     ("run_shell",), ("show the pre-seeded Challenge 2 trace", "The live attack and the seed")),
    ("#/48", "Let's look at the trace.", "c3-attack",
     "Click Let's look at the trace. to open Datadog and show the pre-seeded Challenge 3 trace: the "
     "read_support_ticket span, then the deploy_app span.",
     ("read_support_ticket", "deploy_app"), ("Show the pre-seeded Challenge 3 trace", "After the trace, say")),
    ("#/68", "tools", "c4-attack",
     "After \"Let's look at the trace to see the agent's reasoning,\" click tools to open Datadog and show the "
     "pre-seeded Challenge 4 trace: get_weather, then a call to read_internal_config that nobody asked for.",
     ("get_weather", "read_internal_config"), ("show the pre-seeded Challenge 4 trace", "After the trace, say")),
)
TOOL = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def need(text: str, literal: str, where: str) -> None:
    """An anchor this test cuts on is there, or the test stops naming it, so a reworded line reads as that."""
    if literal not in text:
        print(f"ANCHOR MISSING: {literal!r} is not in {where}; the line this test reads was reworded or moved")
        sys.exit(1)


def flat(text: str) -> str:
    return " ".join(text.split())


def tools_in(text: str) -> list[str]:
    """The snake_case tool names a sentence gives, in the order it gives them."""
    return TOOL.findall(text)


def note_drift(slides) -> list[str]:
    """Each slide whose note names tools whose order differs from the spans the table gives it."""
    return [f"{h}: the note gives {tools_in(note)}, the table {list(spans)}"
            for h, _, _, note, spans, _ in slides if tools_in(note) and tools_in(note) != list(spans)]


def ros_step(ros: str, start: str, end: str) -> str:
    text = flat(ros)
    i = text.index(start)
    return text[i:text.index(end, i)]


def ros_drift(ros: str, slides) -> list[str]:
    """Each trace whose run-of-show step names other tools, or the same in another order, than the table. Slide 11's
    step names none: it must call the trace the Secret read, and its spans must be the Secret-reading tool."""
    out = []
    for h, _, _, _, spans, (start, end) in slides:
        step = ros_step(ros, start, end)
        named = tools_in(step)
        if named:
            if named != list(spans):
                out.append(f"{h}: the run-of-show gives {named}, the table {list(spans)}")
        elif "the Secret read" not in step or list(spans) != [SECRET_READ]:
            out.append(f"{h}: the run-of-show step names no tool and is not the Secret read with {SECRET_READ}: "
                       f"{step[:160]!r}")
    return out


def seed_drift(seeds, slides) -> list[str]:
    """Each attack seed whose must spans, in order, are not its slide's, or that carries a must_not; and an attack
    seed with no slide, or a slide with no seed."""
    rows = {k: (must, must_not) for k, _, _, must, must_not in seeds}
    want = {seed: spans for _, _, seed, _, spans, _ in slides}
    out = [f"{k}: SEEDS has no row" for k in want if k not in rows]
    out += [f"{k}: an attack seed no slide opens" for k in rows if k.endswith("-attack") and k not in want]
    for k, spans in want.items():
        if k in rows and (tuple(rows[k][0]) != tuple(spans) or tuple(rows[k][1])):
            out.append(f"{k}: SEEDS expects {list(rows[k][0])} and no {list(rows[k][1])}, the slide {list(spans)}")
    return out


def with_seed(seeds, key: str, must) -> tuple:
    return tuple((k, c, w, must if k == key else m, n) for k, c, w, m, n in seeds)


def span(name: str, start: int | None) -> dict:
    a = {"name": name, "tags": ["session_id:wib-stage-x"]}
    if start is not None:
        a["start_ns"] = start
    return {"attributes": a}


ros = (REPO / ROS_REL).read_text(encoding="utf-8")
for _, _, _, _, _, (start, end) in SLIDES:
    need(flat(ros), start, ROS_REL)
    need(flat(ros)[flat(ros).index(start):], end, f"{ROS_REL} after {start!r}")
mcp = (REPO / MCP_REL).read_text(encoding="utf-8")
need(mcp, SECRET_DOC, MCP_REL)

print("== each attack seed expects what its slide says the trace shows ==")
check("SEEDS' attack seeds expect each slide's spans, in its order, and no must_not",
      not seed_drift(st.SEEDS, SLIDES), "; ".join(seed_drift(st.SEEDS, SLIDES)))
check("each slide's note names the table's spans in the table's order", not note_drift(SLIDES),
      "; ".join(note_drift(SLIDES)))
check("the run-of-show's step for each trace names the same spans, in the same order", not ros_drift(ros, SLIDES),
      "; ".join(ros_drift(ros, SLIDES)))
check(f"workshop-mcp's {SECRET_READ} is the tool that reads a Secret", SECRET_DOC in mcp)
check("the -fixed seeds and c3-pii are kept",
      [k for k, *_ in st.SEEDS] == ["c1-attack", "c1-fixed", "c2-attack", "c2-fixed", "c3-attack", "c3-fixed",
                                    "c4-attack", "c4-fixed"] and st.PII_SEED[0] == "c3-pii",
      str([k for k, *_ in st.SEEDS]))

print("== the drift checks fail on a change to either side ==")
for _, _, seed, _, spans, _ in SLIDES:
    changes = {"a span dropped": spans[:-1], "a span added": (*spans, "list_services")}
    if len(spans) > 1:
        changes["the order swapped"] = tuple(reversed(spans))
    for what, must in changes.items():
        check(f"{seed} with {what} in SEEDS fails", bool(seed_drift(with_seed(st.SEEDS, seed, must), SLIDES)))
check("c3-attack with a must_not added fails",
      bool(seed_drift(tuple((k, c, w, m, ("deploy_app",) if k == "c3-attack" else n) for k, c, w, m, n in st.SEEDS),
                      SLIDES)))
check("SEEDS without c4-attack fails", bool(seed_drift(tuple(r for r in st.SEEDS if r[0] != "c4-attack"), SLIDES)))
swapped = tuple((h, link, seed, note.replace("get_weather, then a call to read_internal_config",
                                             "read_internal_config, then a call to get_weather"), spans, ros_cut)
                for h, link, seed, note, spans, ros_cut in SLIDES)
check("a note giving Challenge 4's tools in the other order fails", bool(note_drift(swapped)))
c3_ros = "the `read_support_ticket` span returning HC-666, then the `deploy_app` call"
need(flat(ros), c3_ros, ROS_REL)
check("a run-of-show giving Challenge 3's spans in the other order fails",
      bool(ros_drift(flat(ros).replace(c3_ros, "the `deploy_app` call, then the `read_support_ticket` span"), SLIDES)))
c1_ros = "the Secret read in the trace"
need(flat(ros), c1_ros, ROS_REL)
check("a run-of-show whose Challenge 1 step no longer says the Secret read fails",
      bool(ros_drift(flat(ros).replace(c1_ros, "the record in the trace"), SLIDES)))

print("== judge_spans holds the trace to the order, on start_ns ==")
must = ["read_support_ticket", "deploy_app"]
in_order = [span("deploy_app", 30), span("read_support_ticket", 20), span("invocation", 10)]  # newest first
ok, note = st.judge_spans(in_order, must, [])
check("read_support_ticket then deploy_app, listed newest first as the API does, passes", ok, note)
ok, note = st.judge_spans([span("read_support_ticket", 30), span("deploy_app", 20), span("invocation", 10)], must, [])
check("deploy_app before read_support_ticket fails, naming the order", not ok and "out of order" in note, note)
ok, note = st.judge_spans([span("deploy_app", 30), span("read_support_ticket", None)], must, [])
check("a must span with no start_ns fails rather than passing on list order", not ok and "start_ns" in note, note)
ok, note = st.judge_spans([span("read_support_ticket", 20), span("deploy_app", 30), span("read_support_ticket", 40)],
                          must, [])
check("a second read after the deploy keeps the first read's start, so it still passes", ok, note)
ok, note = st.judge_spans([span("run_shell", None)], ["run_shell"], [])
check("one must span needs no start_ns: there is no order to read", ok, note)
real = [{"attributes": s["attributes"]} for s in json.loads((REPO / FIXTURE_REL).read_text())["trace"]["data"]]
ok, note = st.judge_spans(real, must, [])
check("run 17405's real Challenge 3 trace passes c3-attack's spans in order", ok, note)
ok, note = st.judge_spans(real, list(reversed(must)), [])
check("the same real trace fails the reversed order", not ok and "out of order" in note, note)

if failures:
    print(f"\n{len(failures)} stage-trace slide check(s) FAILED: {failures}")
    sys.exit(1)
print("\nEvery stage-trace slide check passed.")
