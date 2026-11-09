# ABOUTME: Holds the run-of-show's Night Before step "Seed the stage's Datadog traces" to verify/stage_traces.py (#1207):
# ABOUTME: its spans to SEEDS, its prompt-source paragraph to SEED_BEATS, and its ids and searches to the script's own.
"""#1207, from #1139's third criterion: the step's spans and prompt source match verify/stage_traces.py as #1137 and
#1138 left it. verify/test_stage_trace_slides.py holds SEEDS' attack spans to the segment steps and the deck's notes;
verify/test_stage_trace_prompts.py holds SEED_BEATS to the /kubecon page. Neither reads the Night Before step itself,
so this test holds each part of that step to the script it describes:

    the table of four links   each attack seed's key, session id and spans, in SEEDS' order and must column
    the -fixed bullets        each -fixed seed's spans (must) and the spans it shows absent ("no X", must_not)
    the wait list             the tool spans the run waits for, challenge by challenge, and what a fix leaves out
    the c3-pii bullet         its APM search (pii_view's query) and the guard stage judge_pii_trace reads
    the prompt source         the page SEED_BEATS reads, each challenge's beat and prompt, the -fixed seeds' sameness,
                              and the one off-page seed
    the ids and searches      session_id, attempt_session's "-2", ATTEMPTS, the seed count, the filtered link, the
                              retention filter and the room's link

Each check is shown failing on a changed step and on a changed SEEDS, SEED_BEATS or OFF_PAGE_SEEDS."""
from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import stage_traces as st  # noqa: E402

kp = st.kp  # the page's reader, through the script, which reads its prompts with it

failures: list[str] = []
ROS_REL = "facilitation/kubecon-na-2026-run-of-show.md"
NIGHT_BEFORE = "\n## Night Before\n"
STEP_START, NEXT_STEP = "- [ ] **Seed the stage's Datadog traces (#648)", "\n- [ ] **"
SOURCE_START, SOURCE_END = "The seeds read their prompts from `/kubecon` (#1137).", "First, what the input guard refuses."
WAIT_START, WAIT_END = "carries the tool spans the stage points at (", "), and until the"
TABLE_HEAD = "| Slide (URL hash) | Where Datadog opens | Seed and session | The spans the presenter shows |"
FIXED_START, FIXED_END = "**The `-fixed` seeds and `c3-pii`**", "\n  The room's link"
SITE = "datadoghq.com"
WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
TOOL = re.compile(r"(\bno )?`([a-z]+(?:_[a-z]+)+)`")
TICKS = re.compile(r"`([^`]+)`")


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


def between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i + len(start))]


def tools(text: str) -> tuple[list[str], list[str]]:
    """The backticked snake_case tool names a passage gives, in order: those shown, and those it says are absent
    ("no `deploy_app`")."""
    shown, absent = [], []
    for no, name in TOOL.findall(text):
        (absent if no else shown).append(name)
    return shown, absent


def challenge_of(seeds) -> dict[str, int]:
    return {k: int(c.split()[-1]) for k, c, *_ in seeds}


def table_drift(step: str, seeds) -> list[str]:
    """The four-link table: one row per attack seed, in SEEDS' order, each naming the seed, its session_id and its
    must spans in order, and nothing shown absent."""
    rows = [ln.strip() for ln in step.split("\n") if ln.strip().startswith("| `#/")]
    attack = [(k, must, must_not) for k, _, _, must, must_not in seeds if k.endswith("-attack")]
    out = []
    keys = []
    for row in rows:
        cols = [c.strip() for c in row.strip("|").split("|")]
        if len(cols) != 4:
            out.append(f"a table row without four columns: {row!r}")
            continue
        named = TICKS.findall(cols[2])
        keys.append(named[0] if named else cols[2])
        want = next((a for a in attack if a[0] == keys[-1]), None)
        if want is None:
            out.append(f"the row for {keys[-1]!r} names no attack seed in SEEDS")
            continue
        if named[1:] != [st.session_id(keys[-1], "<stamp>")]:
            out.append(f"{keys[-1]}: the row names session {named[1:]}, the script "
                       f"{st.session_id(keys[-1], '<stamp>')!r}")
        shown, absent = tools(cols[3])
        if shown != list(want[1]) or absent != list(want[2]):
            out.append(f"{keys[-1]}: the row shows {shown} and no {absent}, SEEDS {list(want[1])} and no "
                       f"{list(want[2])}")
    if keys != [a[0] for a in attack]:
        out.append(f"the table's seeds are {keys}, SEEDS' attack seeds {[a[0] for a in attack]}")
    return out


def fixed_drift(step: str, seeds) -> list[str]:
    """The -fixed bullets: one per -fixed seed and one for c3-pii, each -fixed seed's tools shown as its must spans,
    in order, and those it says are absent as its must_not."""
    section = between(step, FIXED_START, FIXED_END)
    bullets = {}
    for chunk in section.split("\n  - ")[1:]:
        named = TICKS.findall(chunk)
        bullets[named[0] if named else chunk[:30]] = flat(chunk)
    fixed = [(k, must, must_not) for k, _, _, must, must_not in seeds if k.endswith("-fixed")]
    want_keys = [k for k, _, _ in fixed] + [st.PII_SEED[0]]
    out = []
    if sorted(bullets) != sorted(want_keys):
        out.append(f"the bullets name {sorted(bullets)}, SEEDS' -fixed seeds and the PII seed {sorted(want_keys)}")
    for k, must, must_not in fixed:
        if k in bullets:
            shown, absent = tools(bullets[k])
            if shown != list(must) or absent != list(must_not):
                out.append(f"{k}: the bullet shows {shown} and no {absent}, SEEDS {list(must)} and no {list(must_not)}")
    return out


def wait_drift(step: str, seeds) -> list[str]:
    """The wait list: one group per challenge, in order, each showing its attack seed's must spans in order and,
    as absent, every must_not of that challenge's seeds."""
    groups = [g.strip() for g in between(flat(step), WAIT_START, WAIT_END)[len(WAIT_START):].split(";")]
    by = challenge_of(seeds)
    challenges = sorted(set(by.values()))
    out = []
    if len(groups) != len(challenges):
        return [f"the wait list has {len(groups)} group(s), SEEDS {len(challenges)} challenge(s): {groups}"]
    for n, group in zip(challenges, groups):
        attack = next(must for k, _, _, must, _ in seeds if k == f"c{n}-attack")
        gone = [x for k, _, _, _, must_not in seeds if by[k] == n for x in must_not]
        shown, absent = tools(group)
        if shown != list(attack) or absent != gone:
            out.append(f"Challenge {n}: the wait list shows {shown} and no {absent}, SEEDS {list(attack)} and no {gone}")
    return out


def source_drift(step: str, seed_beats: dict, off_page: tuple, page: pathlib.Path = st.KUBECON_PAGE) -> list[str]:
    """The prompt-source paragraph against SEED_BEATS: the page, each challenge's beat and which of its prompts
    (the first, or the last), each -fixed seed reading its attack seed's, and the off-page seed."""
    para = flat(between(step, SOURCE_START, SOURCE_END))
    out = []
    pages = [p for p in TICKS.findall(para) if p.endswith(".html")]
    if pages != [str(page.relative_to(REPO))]:
        out.append(f"the paragraph names the page {pages}, the script reads {page.relative_to(REPO)}")
    but = re.findall(r"every seed but `([a-z0-9-]+)`", para)
    if tuple(but) != tuple(off_page):
        out.append(f"the paragraph sends every seed but {but} off the page, OFF_PAGE_SEEDS is {list(off_page)}")
    named = {}
    for n, how, beat in re.findall(r"Challenge (\d)'s (from(?: the)?|the last prompt of the) (C\d+)", para):
        named[int(n)] = (beat, "last" if how.startswith("the last") else "first")
    on_page = {k: v for k, v in seed_beats.items()}
    keys = sorted({int(k[1]) for k in on_page})
    if sorted(named) != keys:
        out.append(f"the paragraph names Challenges {sorted(named)}, SEED_BEATS {keys}")
    for n in keys:
        beat, pos = on_page[f"c{n}-attack"]
        count = len(kp.kubecon_prompts(beat, page))
        index = pos % count
        which = "first" if index == 0 else "last" if index == count - 1 else f"prompt {index}"
        if n in named and named[n] != (beat, which):
            out.append(f"Challenge {n}: the paragraph reads the {named[n][1]} prompt of {named[n][0]}, SEED_BEATS the "
                       f"{which} of {beat} {(beat, pos)}")
    if "each `-fixed` seed the same prompt as its attack" not in para:
        out.append("the paragraph no longer says each -fixed seed sends its attack's prompt")
    same = [k for k in on_page if k.endswith("-fixed") and on_page[k] != on_page.get(k.replace("-fixed", "-attack"))]
    if same:
        out.append(f"the paragraph says each -fixed seed sends its attack's prompt, SEED_BEATS differs for {same}")
    pii = re.findall(r"so `([a-z0-9-]+)` sends the script's own", para)
    if pii != [st.PII_SEED[0]] or st.PII_SEED[0] in on_page or tuple(off_page) != (st.PII_SEED[0],):
        out.append(f"the paragraph has {pii} send the script's own prompt; PII_SEED is {st.PII_SEED[0]!r}, "
                   f"OFF_PAGE_SEEDS {list(off_page)}, on the page: {st.PII_SEED[0] in on_page}")
    return out


def id_drift(step: str, seeds, attempts: int) -> list[str]:
    """The seed count, the session id and its retries, and the searches the step types, against the script's."""
    text = flat(step)
    out = []
    model, total = len(seeds), len(seeds) + 1
    if f"{WORDS.get(total)} `/chat` requests ({WORDS.get(model)} model calls; the PII one spends no tokens)" not in text:
        out.append(f"the step does not count {WORDS.get(total)} requests, {WORDS.get(model)} model calls")
    if f"Each seed is its own session, `{st.session_id('<key>', '<stamp>')}`" not in text:
        out.append(f"the step's session id is not the script's {st.session_id('<key>', '<stamp>')!r}")
    if f"(`{seeds[0][0]}` to `{seeds[-1][0]}`)" not in text:
        out.append(f"the step's keys do not run {seeds[0][0]} to {seeds[-1][0]}")
    s1, s2, s3 = (st.attempt_session("k", "s", n) for n in (1, 2, 3))
    if not (s2 == s1 + "-2" and s3 == s1 + "-3") or "the same id with `-2` after it, then `-3`" not in text:
        out.append(f"the step's retried session ids are not the script's: {s2!r}, {s3!r}")
    if f"up to {WORDS.get(attempts)} asks" not in text:
        out.append(f"the step's asks are not ATTEMPTS ({attempts})")
    filtered = st.llmobs_url(SITE, f"k8s.cluster.name:{st.PRESENTER_CLUSTER}")
    if f"(`{filtered}`)" not in text:
        out.append(f"the step's filtered link is not the presenters' view, {filtered}")
    if f"`{st.llmobs_url(SITE, '').split('?')[0].split('//')[1]}`" not in text:
        out.append("the step's typed traces page is not the script's llmobs_url page")
    seed_q = f"session_id:{st.session_id('<key>', '<stamp>')}"
    if f"Add `{seed_q}` to the search" not in text or f"search `ml_app:{st.ML_APP} {seed_q}`" not in text:
        out.append(f"the step's seed searches are not the script's query, {seed_q}")
    keep = f"service:{st.PROXY_SERVICE} @session.id:{st.session_id('KEY', 'S').split('KEY')[0]}*"
    if f"query `{keep}`" not in text:
        out.append(f"the retention filter is not {keep!r}")
    if f"`k8s.cluster.name:{st.ROOM_CLUSTER}`" not in text:
        out.append(f"the room's link is not k8s.cluster.name:{st.ROOM_CLUSTER}")
    if f"the grep of `{st.RECIPE_DIR}`" not in text:
        out.append(f"Challenge 2's row does not grep {st.RECIPE_DIR}")
    return out


def pii_drift(step: str) -> list[str]:
    """The c3-pii bullet's APM page and search, and the guard stage it names, against pii_view and judge_pii_trace."""
    section = flat(between(step, FIXED_START, FIXED_END))
    view = st.pii_view(SITE, "<stamp>")
    out = []
    if f"type `{view['url'].split('?')[0].split('//')[1]}`" not in section:
        out.append(f"the c3-pii bullet does not type APM's page, {view['url'].split('?')[0]}")
    if f"search `{view['query']}`" not in section:
        out.append(f"the c3-pii bullet does not search pii_view's query, {view['query']!r}")
    stage = re.findall(r"decided by `([a-z_]+)`", section)
    root = [{"attributes": {"service": st.PROXY_SERVICE, "witb.guard.decision": s}} for s in stage]
    ok, _ = st.judge_pii_trace(root, root)
    wrong, _ = st.judge_pii_trace([{"attributes": {"witb.guard.decision": "output_guard"}}], root)
    if len(stage) != 1 or not ok or wrong:
        out.append(f"the c3-pii bullet's stage {stage} is not the one judge_pii_trace reads")
    if "no agent span" not in section:
        out.append("the c3-pii bullet does not say no agent span")
    return out


ros = (REPO / ROS_REL).read_text(encoding="utf-8")
need(ros, NIGHT_BEFORE, ROS_REL)
night = ros.split(NIGHT_BEFORE, 1)[1]
need(night, STEP_START, f"{ROS_REL}'s Night Before")
STEP = between(night, STEP_START, NEXT_STEP)
for anchor in (SOURCE_START, SOURCE_END, TABLE_HEAD, FIXED_START, FIXED_END):
    need(STEP, anchor, "the seed step")
need(flat(STEP), WAIT_START, "the seed step")

print("== the Night Before seed step's spans match SEEDS ==")
check("the four-link table names each attack seed, its session and its must spans, in SEEDS' order",
      not table_drift(STEP, st.SEEDS), "; ".join(table_drift(STEP, st.SEEDS)))
check("each -fixed bullet shows its seed's must spans and, as absent, its must_not",
      not fixed_drift(STEP, st.SEEDS), "; ".join(fixed_drift(STEP, st.SEEDS)))
check("the wait list shows each challenge's attack spans, and what its fix leaves out",
      not wait_drift(STEP, st.SEEDS), "; ".join(wait_drift(STEP, st.SEEDS)))
check("the c3-pii bullet searches pii_view's query and names the stage judge_pii_trace reads",
      not pii_drift(STEP), "; ".join(pii_drift(STEP)))

print("== its prompt source matches SEED_BEATS and OFF_PAGE_SEEDS ==")
check("the prompt-source paragraph names the page, each challenge's beat and prompt, and the off-page seed",
      not source_drift(STEP, st.SEED_BEATS, st.OFF_PAGE_SEEDS), "; ".join(source_drift(STEP, st.SEED_BEATS,
                                                                                         st.OFF_PAGE_SEEDS)))

print("== its ids, counts and searches match the script ==")
check("the seed count, session ids, retries and searches are the script's",
      not id_drift(STEP, st.SEEDS, st.ATTEMPTS), "; ".join(id_drift(STEP, st.SEEDS, st.ATTEMPTS)))

print("== each check fails on a change to the step ==")


def edit(old: str, new: str) -> str:
    need(STEP, old, "the seed step")
    return STEP.replace(old, new)


c4_row = "`get_weather`, then `read_internal_config`, which nobody asked for"
check("a table row giving Challenge 4's spans in the other order fails",
      bool(table_drift(edit(c4_row, "`read_internal_config`, then `get_weather`, which nobody asked for"), st.SEEDS)))
check("a table row naming another session fails",
      bool(table_drift(edit("`wib-stage-c2-attack-<stamp>`", "`wib-stage-c2-<stamp>`"), st.SEEDS)))
c3_fixed = "`read_support_ticket` with the guard's withheld notice, and no `deploy_app`"
check("a c3-fixed bullet that drops 'no deploy_app' fails",
      bool(fixed_drift(edit(c3_fixed, "`read_support_ticket` with the guard's withheld notice"), st.SEEDS)))
check("a c1-fixed bullet naming another tool fails",
      bool(fixed_drift(edit("`get_vault_entry`, its result Forbidden", "`list_secrets`, its result Forbidden"),
                       st.SEEDS)))
check("a wait list with Challenge 3's deploy_app shown after the fix fails",
      bool(wait_drift(edit("and no `deploy_app` once fixed", "and `deploy_app` once fixed"), st.SEEDS)))
check("a wait list missing Challenge 2's group fails",
      bool(wait_drift(edit("`run_shell`, the recipe grep; ", ""), st.SEEDS)))
check("a paragraph reading Challenge 2 from the C3 beat's first prompt fails",
      bool(source_drift(edit("Challenge 2's\n  the last prompt of the C3 beat", "Challenge 2's\n  from the C3 beat"),
                        st.SEED_BEATS, st.OFF_PAGE_SEEDS)))
check("a paragraph reading Challenge 4 from C6 fails",
      bool(source_drift(edit("Challenge 4's from C7", "Challenge 4's from C6"), st.SEED_BEATS, st.OFF_PAGE_SEEDS)))
check("a paragraph naming another page fails",
      bool(source_drift(edit("`gitops/ai-layer/web/kubecon.html`", "`gitops/ai-layer/web/burritbot.html`"),
                        st.SEED_BEATS, st.OFF_PAGE_SEEDS)))
check("a paragraph that drops the -fixed seeds' sameness fails",
      bool(source_drift(edit(", each\n  `-fixed` seed the same prompt as its attack", ""), st.SEED_BEATS,
                        st.OFF_PAGE_SEEDS)))
check("a step counting ten requests fails", bool(id_drift(edit("nine `/chat` requests", "ten `/chat` requests"),
                                                          st.SEEDS, st.ATTEMPTS)))
check("a c3-pii bullet searching another service fails",
      bool(pii_drift(edit("`service:burritobot @session.id:wib-stage-c3-pii-<stamp>`",
                          "`service:burritobot-agent @session.id:wib-stage-c3-pii-<stamp>`"))))
check("a c3-pii bullet naming another guard stage fails",
      bool(pii_drift(edit("decided by `input_classifier`", "decided by `output_guard`"))))

print("== each check fails on a change to stage_traces.py ==")


def with_seed(key: str, must=None, must_not=None) -> tuple:
    return tuple((k, c, w, must if k == key and must is not None else m,
                  must_not if k == key and must_not is not None else n) for k, c, w, m, n in st.SEEDS)


check("SEEDS with c3-attack's spans swapped fails the table and the wait list",
      bool(table_drift(STEP, with_seed("c3-attack", ("deploy_app", "read_support_ticket"))))
      and bool(wait_drift(STEP, with_seed("c3-attack", ("deploy_app", "read_support_ticket")))))
check("SEEDS with c3-fixed's must_not dropped fails the bullets and the wait list",
      bool(fixed_drift(STEP, with_seed("c3-fixed", must_not=()))) and bool(wait_drift(STEP, with_seed("c3-fixed",
                                                                                                       must_not=()))))
check("SEEDS with c2-fixed expecting another tool fails the bullets",
      bool(fixed_drift(STEP, with_seed("c2-fixed", ("list_files",)))))
check("SEEDS with a seed added fails the count and the bullets",
      bool(id_drift(STEP, (*st.SEEDS, ("c5-fixed", "Challenge 4", "x", ("get_weather",), ())), st.ATTEMPTS))
      and bool(fixed_drift(STEP, (*st.SEEDS, ("c5-fixed", "Challenge 4", "x", ("get_weather",), ())))))
check("ATTEMPTS of three fails", bool(id_drift(STEP, st.SEEDS, 3)))
check("SEED_BEATS reading Challenge 2 from the C3 beat's first prompt fails",
      bool(source_drift(STEP, {**st.SEED_BEATS, "c2-attack": ("C3", 0), "c2-fixed": ("C3", 0)}, st.OFF_PAGE_SEEDS)))
check("SEED_BEATS with c4-fixed reading another beat than c4-attack fails",
      bool(source_drift(STEP, {**st.SEED_BEATS, "c4-fixed": ("C6", 0)}, st.OFF_PAGE_SEEDS)))
check("SEED_BEATS with c1 on the C5 beat's last prompt, the same one, still passes",
      not source_drift(STEP, {**st.SEED_BEATS, "c1-attack": ("C5", -1), "c1-fixed": ("C5", -1)}, st.OFF_PAGE_SEEDS),
      "; ".join(source_drift(STEP, {**st.SEED_BEATS, "c1-attack": ("C5", -1), "c1-fixed": ("C5", -1)},
                             st.OFF_PAGE_SEEDS)))
check("OFF_PAGE_SEEDS with another seed fails", bool(source_drift(STEP, st.SEED_BEATS, ("c3-pii", "c4-fixed"))))
check("c3-pii put on the page in SEED_BEATS fails",
      bool(source_drift(STEP, {**st.SEED_BEATS, "c3-pii": ("C6", 0)}, st.OFF_PAGE_SEEDS)))

if failures:
    print(f"\n{len(failures)} seed-step check(s) FAILED: {failures}")
    sys.exit(1)
print("\nEvery seed-step check passed.")
