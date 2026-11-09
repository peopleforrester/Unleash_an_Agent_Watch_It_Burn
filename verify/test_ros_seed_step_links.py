# ABOUTME: Holds the run-of-show's Night Before step "Seed the stage's Datadog traces" to the deck's four Datadog links,
# ABOUTME: #/11, #/26, #/48 and #/68, each with its attack seed, session and spans, and to no saved views (#1205, #1139).
"""#1139 rewrote the Night Before step "Seed the stage's Datadog traces" in
`facilitation/kubecon-na-2026-run-of-show.md`. Before it, the step told Whitney to open each of the nine seeds' links
and save it as a view ("saves it as a view, in that order", "presses Save on a seed view"). The deck opens Datadog once
per challenge, from the slide that shows the attack's trace, so the step now names those four links. #1205 asked for
the test that fails when that stops holding. This one reads the step, from its first words to the next step, and
fails when any of these stops holding:

  1. The step has its "The four Datadog links" paragraph and says the deck opens Datadog once per challenge.
  2. Its table has one row per link, and the rows are `#/11`, `#/26`, `#/48` and `#/68`, in that order. The issue
     named slides 11, 26, 48 and 65; Challenge 4's link is `#/68`, the "tools" hint, since the deck grew
     (rounds-agenticburn#118; #1138 and #1139 in decisions.md, 2026-11-08), and `#/65` is segment 5's tee-up.
  3. Each row gives its segment, the words that open Datadog, the attack seed `cN-attack`, its session
     `wib-stage-cN-attack-<stamp>`, and the spans in the order `verify/stage_traces.py`'s SEEDS holds them.
  4. The step cites no slide hash but those four.
  5. The step tells the presenter to save no view: no "save", "saves" or "saving", no "saved view" but in "not from
     saved views", and no "nine views" or "nine links".

The step is cut on its literal first words and on the next step's "- [ ] **", each checked first, so a reworded anchor
exits naming the literal and the file ("Tests own their inputs"). Every check is then run on a copy of the step
changed to break it, the pre-#1139 save instruction among them, so a check that could never fail shows up here."""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import stage_traces as st  # noqa: E402

ROS_REL = "facilitation/kubecon-na-2026-run-of-show.md"
SEED_STEP, NEXT_STEP = "- [ ] **Seed the stage's Datadog traces", "\n- [ ] **"
HEADING = "**The four Datadog links.**"
ONCE = "The deck opens Datadog once per challenge, from the slide that shows the attack's trace"
TABLE_HEAD = "| Slide (URL hash) | Where Datadog opens | Seed and session | The spans the presenter shows |"
# The one place the step may say "saved views": where it says the links are not them.
NOT_SAVED = "not from saved views"

# Each link: the slide's URL hash, its segment, the words in the row that open Datadog, and the attack seed it shows.
LINKS = (
    ("#/11", 2, '"Ophelia Thorn"', "c1-attack"),
    ("#/26", 3, "opens Datadog", "c2-attack"),
    ("#/48", 4, '"Let\'s look at the trace."', "c3-attack"),
    ("#/68", 5, '"tools"', "c4-attack"),
)
MUST = {key: must for key, _c, _what, must, _not in st.SEEDS}
HASH = re.compile(r"#/\d+")
TOOL = re.compile(r"`([a-z]+(?:_[a-z]+)+)`")
SAVE = re.compile(r"\bsav(?:e|es|ing)\b", re.I)
SAVED_VIEW = re.compile(r"\bsaved\s+views?\b", re.I)
NINE = re.compile(r"\bnine\s+(?:saved\s+)?(?:views|links)\b", re.I)

failures: list[str] = []


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


def seed_step(ros: str) -> str:
    need(ros, SEED_STEP, ROS_REL)
    i = ros.index(SEED_STEP)
    need(ros[i + 1:], NEXT_STEP, f"{ROS_REL} after {SEED_STEP!r}")
    return ros[i:ros.index(NEXT_STEP, i + 1)]


def rows(step: str) -> list[list[str]]:
    """The link table's body rows, each split into its cells."""
    lines = step.splitlines()
    heads = [n for n, line in enumerate(lines) if line.strip() == TABLE_HEAD]
    if not heads:
        return []
    out = []
    for line in lines[heads[0] + 2:]:
        if not line.strip().startswith("|"):
            break
        out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out


def judge(step: str) -> dict[str, list[str]]:
    """Each check's name and what breaks it in `step`; an empty list is a pass."""
    out: dict[str, list[str]] = {}
    f = flat(step)
    out["the step has its four-links paragraph and opens Datadog once per challenge"] = (
        [f"no {lit!r}" for lit in (HEADING, ONCE) if lit not in f])

    body = rows(step)
    hashes = [HASH.findall(r[0])[:1][0] if r and HASH.findall(r[0]) else "?" for r in body]
    want = [h for h, *_ in LINKS]
    out["the link table's rows are #/11, #/26, #/48 and #/68, in that order"] = (
        [] if hashes == want else [f"rows read {hashes}, not {want}"])

    bad = []
    for (h, seg, opens, key), r in zip(LINKS, body):
        if len(r) != 4:
            bad.append(f"{h}'s row has {len(r)} cells")
            continue
        if r[0] != f"`{h}`, segment {seg}":
            bad.append(f"{h}'s slide cell reads {r[0]!r}")
        if opens not in r[1]:
            bad.append(f"{h}'s row does not say {opens}")
        if r[2] != f"`{key}`, `wib-stage-{key}-<stamp>`":
            bad.append(f"{h}'s seed cell reads {r[2]!r}")
        if tuple(TOOL.findall(r[3])) != tuple(MUST[key]):
            bad.append(f"{h}'s spans read {TOOL.findall(r[3])}, SEEDS holds {list(MUST[key])}")
    out["each row names its segment, link, attack seed, session and SEEDS' spans in order"] = bad

    extra = sorted(set(HASH.findall(step)) - set(want))
    out["the step cites no slide hash but the four links"] = [f"cites {h}" for h in extra]

    told = [m.group(0) for m in SAVE.finditer(step)]
    told += [m.group(0) for m in SAVED_VIEW.finditer(f.replace(NOT_SAVED, ""))]
    told += [m.group(0) for m in NINE.finditer(f)]
    out["the step tells the presenter to save no view"] = [f"says {w!r}" for w in told]
    return out


def report(results: dict[str, list[str]]) -> None:
    for name, problems in results.items():
        check(name, not problems, "; ".join(problems))


def broken(results: dict[str, list[str]], name: str) -> bool:
    return bool(results[name])


ros = (REPO / ROS_REL).read_text()
step = seed_step(ros)
print(f"{ROS_REL}, the Night Before step {SEED_STEP[6:]!r}:")
report(judge(step))

ROW_C4 = "| `#/68`, segment 5 |"
ROW_C2 = next((line for line in step.splitlines() if line.lstrip().startswith("| `#/26`")), None)
for lit in (HEADING, ROW_C4, "`wib-stage-c2-attack-<stamp>`", "`get_weather`, then `read_internal_config`",
            "the PII one\n  spends no tokens"):
    need(step, lit, f"{ROS_REL}'s seed step")
if ROW_C2 is None:
    print(f"ANCHOR MISSING: no row starting '| `#/26`' in {ROS_REL}'s seed step")
    sys.exit(1)
lines = step.splitlines()
r3, r4 = (next(n for n, line in enumerate(lines) if line.lstrip().startswith(p)) for p in ("| `#/48`", "| `#/68`"))
swapped = lines[:]
swapped[r3], swapped[r4] = swapped[r4], swapped[r3]

FOUR = "the link table's rows are #/11, #/26, #/48 and #/68, in that order"
ROW = "each row names its segment, link, attack seed, session and SEEDS' spans in order"
SAVE_NAME = "the step tells the presenter to save no view"
cases = (
    ("the four-links paragraph cut", step.replace(HEADING, ""),
     "the step has its four-links paragraph and opens Datadog once per challenge"),
    ("Challenge 4's link put back on #/65", step.replace(ROW_C4, "| `#/65`, segment 5 |"), FOUR),
    ("the #/26 row dropped", step.replace(ROW_C2 + "\n", ""), FOUR),
    ("the #/48 and #/68 rows swapped", "\n".join(swapped), FOUR),
    ("Challenge 2's row showing the fix's session",
     step.replace("`wib-stage-c2-attack-<stamp>`", "`wib-stage-c2-fixed-<stamp>`"), ROW),
    ("Challenge 4's spans in the other order",
     step.replace("`get_weather`, then `read_internal_config`", "`read_internal_config`, then `get_weather`"), ROW),
    ("#/65 cited as well", step.replace(HEADING, HEADING + " Segment 5's tee-up is `#/65`."),
     "the step cites no slide hash but the four links"),
    ("the pre-#1139 save instruction put back",
     step + "  Whitney opens each link in her org and saves it as a\n  view, in that order.\n", SAVE_NAME),
    ("a Save press", step + "  When she presses Save on a seed view, she sets Past 7 Days.\n", SAVE_NAME),
    ("a saved view kept on its window", step + "  A saved view keeps its time picker.\n", SAVE_NAME),
    ("nine views", step.replace("the PII one\n  spends no tokens", "the PII one\n  spends no tokens; nine views"),
     SAVE_NAME),
)
print("Each check, run on a copy of the step changed to break it:")
for label, text, name in cases:
    check(f"{name}: fails on {label}", broken(judge(text), name))

if failures:
    print(f"\nFAIL: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("\nThe seed step names the four Datadog links, #/11, #/26, #/48 and #/68, and tells the presenter to save no view.")
