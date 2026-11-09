#!/usr/bin/env python3
# ABOUTME: Holds the run-of-show's Night Before seed step to verify/stage_traces.py: for each of the deck's four Datadog
# ABOUTME: links, the seed and session shown, its spans in order, and how to reach it from the filtered and home links.
"""#1206, the test #1139 shipped without. The run-of-show's Night Before step "Seed the stage's Datadog traces" has a
table with one row per Datadog link in the deck (`#/11`, `#/26`, `#/48`, `#/68`) naming the attack seed the presenter
shows, its session `wib-stage-<key>-<stamp>` and the spans shown, and two bullets on reaching that trace: from the
filtered Agent Observability link, and from the Datadog home page link. This test reads that step and holds it to
verify/stage_traces.py, which seeds the traces and reads them back:

  - four rows, the four slides in deck order, each with its link's words and its challenge's attack seed;
  - each row's session is stage_traces.session_id(seed, "<stamp>");
  - each row's spans are the seed's SEEDS must spans, in SEEDS' order, and none of its must_not;
  - the filtered link is stage_traces' presenters tab URL, word for word (ml_app and the admin cluster);
  - the filtered bullet adds the seed's session_id query to the link's own and sets Past 7 Days;
  - the home bullet types the filtered link's page, searches stage_traces' own query for the seed (ml_app and the
    session id) and sets Past 7 Days;
  - both end on the one trace the session filter leaves.

Every check is then shown failing on a changed step: a row dropped, spans swapped, a session miskeyed, the link
pointed at the room's cluster, the time range or the session filter taken out of either bullet."""
from __future__ import annotations

import pathlib
import re
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import stage_traces as st  # noqa: E402

ROS_REL = "facilitation/kubecon-na-2026-run-of-show.md"
SITE = "datadoghq.com"
STAMP = "<stamp>"
KEY = "<key>"
STEP_START = "**The four Datadog links.**"
STEP_END = "**The `-fixed` seeds and `c3-pii`**"
FILTERED_START = "**The filtered link**"
HOME_START = "**The home page link**"
RANGE = "Past 7 Days"
ONE_TRACE = "click the one trace"

# slide hash, the segment, the words the link sits on (as the run-of-show's "Where Datadog opens" cell quotes the
# deck), and the challenge whose attack seed it opens. verify/test_stage_trace_slides.py holds each seed's spans to
# the slide's own note; this list is the four links #1139's step is written around.
LINKS = (
    ("#/11", "segment 2", '"Ophelia Thorn"', "Challenge 1"),
    ("#/26", "segment 3", "Whitney opens Datadog", "Challenge 2"),
    ("#/48", "segment 4", "\"Let's look at the trace.\"", "Challenge 3"),
    ("#/68", "segment 5", '"tools"', "Challenge 4"),
)
TOOL = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
CODE = re.compile(r"`([^`]+)`")
URL = re.compile(r"\(`(https://[^`]+)`\)")

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


def step_of(ros: str) -> str:
    i = ros.index(STEP_START)
    return ros[i:ros.index(STEP_END, i)]


def attack_seeds() -> dict[str, tuple[str, tuple, tuple]]:
    """challenge -> (attack seed key, must spans, must_not spans), from SEEDS."""
    return {c: (k, tuple(must), tuple(must_not)) for k, c, _, must, must_not in st.SEEDS if k.endswith("-attack")}


def rows_of(step: str) -> list[list[str]]:
    return [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in step.splitlines() if line.strip().startswith("| `#/")]


def bullet(step: str, start: str) -> str:
    """The bullet from `start` to the next bullet or the blank line that ends the list, flattened."""
    i = step.index(start)
    rest = step[i:]
    ends = [j for j in (rest.find("\n  - ", 1), rest.find("\n\n", 1)) if j > 0]
    return flat(rest[:min(ends)] if ends else rest)


def table_drift(step: str) -> list[str]:
    out = []
    rows = rows_of(step)
    seeds = attack_seeds()
    if [r[0].split(",")[0].strip("`") for r in rows] != [h for h, *_ in LINKS]:
        out.append(f"the table's slides are {[r[0] for r in rows]}, not the four links {[h for h, *_ in LINKS]}")
        return out
    for (h, segment, words, challenge), row in zip(LINKS, rows):
        if len(row) != 4:
            out.append(f"{h}: the row has {len(row)} cells, not 4: {row}")
            continue
        slide, opens, seed_cell, spans_cell = row
        if segment not in slide:
            out.append(f"{h}: the slide cell {slide!r} does not say {segment}")
        if words not in opens:
            out.append(f"{h}: the cell on where Datadog opens, {opens!r}, does not quote {words}")
        if challenge not in seeds:
            out.append(f"{h}: SEEDS has no attack seed for {challenge}")
            continue
        key, must, must_not = seeds[challenge]
        codes = CODE.findall(seed_cell)
        if codes != [key, st.session_id(key, STAMP)]:
            out.append(f"{h}: the seed cell gives {codes}, SEEDS and session_id give {[key, st.session_id(key, STAMP)]}")
        named = TOOL.findall(" ".join(CODE.findall(spans_cell)))
        if named != list(must):
            out.append(f"{h}: the spans cell names {named}, {key}'s SEEDS must spans are {list(must)}")
        if set(named) & set(must_not):
            out.append(f"{h}: the spans cell names {sorted(set(named) & set(must_not))}, which {key} must not carry")
    return out


def presenters_url() -> str:
    return next(v["url"] for v in st.views(SITE, STAMP) if v["key"] == "presenters")


def seed_query(key: str) -> str:
    """The search stage_traces' own link for the seed carries: ml_app and the session id."""
    url = next(v["url"] for v in st.views(SITE, STAMP) if v["key"] == key)
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]


def links_drift(step: str) -> list[str]:
    out = []
    urls = URL.findall(step)
    if urls != [presenters_url()]:
        out.append(f"the filtered link is {urls}, stage_traces' presenters tab is {presenters_url()}")
        return out
    link = urllib.parse.urlparse(urls[0])
    link_query = urllib.parse.parse_qs(link.query)["query"][0]
    page = link.netloc + link.path
    if FILTERED_START not in step or HOME_START not in step:
        return out + [f"the step lacks {FILTERED_START} or {HOME_START}"]
    filtered, home = bullet(step, FILTERED_START), bullet(step, HOME_START)
    generic = f"session_id:{st.session_id(KEY, STAMP)}"
    for _, _, _, challenge in LINKS:
        key = attack_seeds()[challenge][0]
        want = seed_query(key)
        # Filtered: the session filter typed after the query the link brings is the seed's own search.
        typed = [c.replace(KEY, key) for c in CODE.findall(filtered) if c.startswith("session_id:")]
        if len(typed) != 1 or not set(want.split()) <= set(link_query.split() + typed):
            out.append(f"{key}: the filtered bullet types {typed} after {link_query!r}, which does not narrow the "
                       f"link to the seed's search {want!r}")
        # Home page: the page typed is the filtered link's page, and the search is the seed's own.
        h_codes = CODE.findall(home)
        if page not in h_codes:
            out.append(f"{key}: the home bullet does not type the filtered link's page {page}: {h_codes}")
        searched = [c.replace(KEY, key) for c in h_codes if "session_id:" in c]
        if searched != [want]:
            out.append(f"{key}: the home bullet searches {searched}, the seed's search is {want!r}")
    if generic not in filtered:
        out.append(f"the filtered bullet does not add {generic}")
    if "after the query the link brings" not in filtered:
        out.append("the filtered bullet does not keep the query the link brings")
    for name, text in (("filtered", filtered), ("home", home)):
        if RANGE not in text:
            out.append(f"the {name} bullet does not set {RANGE}")
        if ONE_TRACE not in text:
            out.append(f"the {name} bullet does not end on the one trace ({ONE_TRACE!r})")
    if "keeps the list to that one trace" not in flat(step):
        out.append("the step no longer says the session id keeps the list to that one trace")
    return out


ros = (REPO / ROS_REL).read_text(encoding="utf-8")
need(ros, STEP_START, ROS_REL)
need(ros[ros.index(STEP_START):], STEP_END, f"{ROS_REL} after {STEP_START!r}")
step = step_of(ros)
for literal in (FILTERED_START, HOME_START):
    need(step, literal, f"{ROS_REL}'s step from {STEP_START!r}")

print("== the four links' table: seed, session and spans from stage_traces ==")
check("the table has the four links in deck order, each quoting its link and opening its challenge's attack seed, "
      "with session_id's session and SEEDS' must spans in order", not table_drift(step), "; ".join(table_drift(step)))
check("the four rows' seeds are SEEDS' four attack seeds",
      sorted(CODE.findall(r[2])[0] for r in rows_of(step)) == sorted(k for k, *_ in attack_seeds().values()),
      str([r[2] for r in rows_of(step)]))

print("== reaching each seed from the filtered link and the home page link ==")
check("the filtered link is stage_traces' presenters tab, and both bullets reach each seed's own search on "
      f"{RANGE}, ending on the one trace", not links_drift(step), "; ".join(links_drift(step)))

print("== the drift checks fail on a changed step ==")
c3_row = next(line for line in step.splitlines() if line.strip().startswith("| `#/48`"))
c4_row = next(line for line in step.splitlines() if line.strip().startswith("| `#/68`"))
c3_spans = "`read_support_ticket` returning HC-666, then `deploy_app`"
need(c3_row, c3_spans, f"{ROS_REL}'s #/48 row")
c4_spans = "`get_weather`, then `read_internal_config`"
need(c4_row, c4_spans, f"{ROS_REL}'s #/68 row")
c2_session = "`wib-stage-c2-attack-<stamp>`"
need(step, c2_session, f"{ROS_REL}'s #/26 row")
table_cases = {
    "the #/68 row dropped": step.replace(c4_row + "\n", ""),
    "Challenge 3's spans swapped": step.replace(c3_spans, "`deploy_app`, then `read_support_ticket` returning HC-666"),
    "Challenge 4's second span dropped": step.replace(c4_spans, "`get_weather`"),
    "Challenge 2's session keyed to c2-fixed": step.replace(c2_session, "`wib-stage-c2-fixed-<stamp>`"),
    "Challenge 3's row opening c3-fixed": step.replace("`c3-attack`, `wib-stage-c3-attack", "`c3-fixed`, `wib-stage-c3-fixed"),
    "Challenge 1's link words changed": step.replace('"Ophelia Thorn"', '"the CEO"'),
}
for what, changed in table_cases.items():
    check(f"a step with {what} fails", changed != step and bool(table_drift(changed)))
private = f"k8s.cluster.name%3A{st.PRESENTER_CLUSTER}"
need(step, private, f"{ROS_REL}'s filtered link")
filtered_add = f"Add `session_id:{st.session_id(KEY, STAMP)}` to the search"
need(step, filtered_add, f"{ROS_REL}'s filtered bullet")
home_search = f"search `ml_app:{st.ML_APP} session_id:{st.session_id(KEY, STAMP)}`"
need(step, home_search, f"{ROS_REL}'s home bullet")
home_page = "`app.datadoghq.com/llm/traces`"
need(step, home_page, f"{ROS_REL}'s home bullet")
filtered_text = step[step.index(FILTERED_START):step.index(HOME_START)]
home_text = step[step.index(HOME_START):]
need(filtered_text, "Past 7 Days", f"{ROS_REL}'s filtered bullet")
need(home_text, "Past\n    7 Days", f"{ROS_REL}'s home bullet")
links_cases = {
    "the link pointed at the room's cluster": step.replace(private, f"k8s.cluster.name%3A{st.ROOM_CLUSTER}"),
    "the filtered bullet's session filter taken out": step.replace(filtered_add, "Search"),
    "the filtered bullet's session filter on the wrong field":
        step.replace(filtered_add, filtered_add.replace("session_id:", "service:")),
    "the filtered bullet on Past 15 Minutes":
        step.replace(filtered_text, filtered_text.replace("Past 7 Days", "Past 15 Minutes")),
    "the home bullet's session filter taken out": step.replace(home_search, f"search `ml_app:{st.ML_APP}`"),
    "the home bullet searching another app":
        step.replace(home_search, home_search.replace(f"ml_app:{st.ML_APP}", "ml_app:storefront")),
    "the home bullet on APM's page": step.replace(home_page, "`app.datadoghq.com/apm/traces`"),
    "the home bullet on no time range": step.replace(home_text, home_text.replace("Past\n    7 Days", "nothing")),
    "the home bullet not clicking the trace": step.replace(home_text, home_text.replace(ONE_TRACE, "read the list")),
}
for what, changed in links_cases.items():
    check(f"a step with {what} fails", changed != step and bool(links_drift(changed)))

if failures:
    print(f"\n{len(failures)} stage seed link check(s) FAILED: {failures}")
    sys.exit(1)
print("\nEvery stage seed link check passed.")
