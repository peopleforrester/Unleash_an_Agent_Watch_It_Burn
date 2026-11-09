# ABOUTME: Offline check of what the code-of-conduct floor's chosen option adds to a /chat turn (#1267, #1292): the
# ABOUTME: spike README's latency figures agree with results.json, and the term floor still costs on this checkout what it did.
"""No cluster, no network, no AWS, standard library only.

docs/research/2026-11-09-coc-floor/README.md chose a term floor on every surface plus a Bedrock Guardrails Standard
classifier on the /chat prompt, and its "Latency on a `/chat` turn" section records what that pair adds to a turn:
the term floor 1.07 ms median, 11.4 ms p99 and 16 ms max over 1,099 observed turns (the prompt checked, the reply
masked), Bedrock Standard 466 ms median, about half a second on a 3.8 s turn in all. This test fails when that stops
holding, in two halves:

1. The record. Each figure the README states is held to results.json, which measure.py wrote from the measurement,
   at the precision the README prints it. The Bedrock rows are measured on the 69 observed prompts, which results.json
   does not break out (it holds each guardrail's median over all its calls), so those are held to within 10% of the
   all-calls median and to the prompt count results.json does hold. The README's sum, "about half a second" on a
   3.8 s turn and "about a millisecond" for the floor alone, is recomputed from the figures.
2. The floor as it stands. The proposed term floor (floor.py and terms-proposed.rot13, read as measure.py reads them)
   is timed on turns built from the repo's own /chat prompts and a reply the size the README's Go row names, each turn
   the best of 5 runs, so a loaded host does not read as a regression. The costliest turn must stay within the
   16 ms the worst observed turn cost, about four times what it costs today, and masking a reply ten times as long
   must cost at most twenty times as much, so a longer list or a pattern change that makes the floor slow, or slow
   in the reply's length beyond linear, fails here and not as a slow turn in the room.

The Bedrock half is not re-measured: its guardrail was deleted after the spike, and calling one needs AWS.
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
README = SPIKE / "README.md"
RESULTS = SPIKE / "results.json"
sys.path.insert(0, str(SPIKE))

import corpus  # noqa: E402
import floor  # noqa: E402

SECTION = "## Latency on a `/chat` turn"
FLOOR_ROW = "Term floor, prompt checked and reply masked"
GO_ROW = "The same pattern in Go's RE2 (`regexp`)"
STANDARD_ROW = "Bedrock Standard ApplyGuardrail on the prompt"
CLASSIC_ROW = "Bedrock Classic ApplyGuardrail on the prompt"
TOXICITY_ROW = "LLM Guard Toxicity, per text"
# The /chat prompts the repo holds: the room's /kubecon prompts, the KubeCon replay set, the catalog, topic_cases' asks.
PROMPT_SOURCES = ("kubecon-prompt", "replay-prompt", "catalog-prompt", "probe-prompt")
# What the bot hands back: the tools' descriptions and data, and the Secrets and ConfigMaps it reads.
REPLY_SOURCES = ("tool-data", "cluster-data")
RUNS = 5

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def need(pattern: str, text: str, where: str) -> re.Match:
    """The README text a check reads, or exit naming the pattern and the file (Tests own their inputs, point 2)."""
    m = re.search(pattern, text)
    if not m:
        sys.exit(f"FAIL {README.relative_to(REPO)}: no text matches {pattern!r} in {where}; the README was reworded, "
                 f"so this test's reading of it changes in the same commit")
    return m


def num(s: str) -> float:
    return float(s.replace(",", ""))


def agrees(stated: str, value: float) -> bool:
    """The README's figure is the measured value rounded to the digits the README prints."""
    decimals = len(stated.split(".")[1]) if "." in stated else 0
    return abs(num(stated) - value) <= 0.5 * 10 ** -decimals + 1e-9


def within(stated: str, value: float, share: float) -> bool:
    return abs(num(stated) - value) <= share * value


def best_us(fn, text: str) -> float:
    best = float("inf")
    for _ in range(RUNS):
        t0 = time.perf_counter()
        fn(text)
        best = min(best, time.perf_counter() - t0)
    return best * 1e6


def main() -> int:
    readme = README.read_text(encoding="utf-8")
    result = json.loads(RESULTS.read_text(encoding="utf-8"))
    timing, texts = result["timing"], result["texts"]
    turn = timing["chat-turn"]
    if SECTION not in readme:
        sys.exit(f"FAIL {README.relative_to(REPO)} has no {SECTION!r} section")
    section = readme.split(SECTION, 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and len(cells) == 3:
            rows[cells[0]] = cells[1:]
    for row in (FLOOR_ROW, GO_ROW, STANDARD_ROW, CLASSIC_ROW, TOXICITY_ROW):
        if row not in rows:
            sys.exit(f"FAIL {README.relative_to(REPO)}: the {SECTION!r} table has no row {row!r}")
    flat = " ".join(readme.split())
    prose = " ".join(section.split())

    # 1. The record agrees with results.json.
    m = need(r"([\d,]+) turns over 7 days: \*\*([\d,]+) ms\*\* \(p90 ([\d,]+) ms\)", prose, SECTION)
    check(num(m[1]) == turn["turns"] and agrees(m[2], turn["turn_ms_median"]) and agrees(m[3], turn["turn_ms_p90"]),
          f"the README's {m[1]} turns, {m[2]} ms median and {m[3]} ms p90 are results.json's chat-turn "
          f"({turn['turns']}, {turn['turn_ms_median']}, {turn['turn_ms_p90']})")
    floor_med, floor_p99, floor_max = (turn[f"proposed_floor_us_per_turn_{k}"] / 1000 for k in ("median", "p99", "max"))
    m = need(r"^([\d.]+) ms median, ([\d.]+) ms p99, ([\d.]+) ms max$", rows[FLOOR_ROW][0], FLOOR_ROW)
    check(agrees(m[1], floor_med) and agrees(m[2], floor_p99) and agrees(m[3], floor_max),
          f"the term floor row's {rows[FLOOR_ROW][0]!r} is results.json's per-turn cost "
          f"({floor_med} ms median, {floor_p99} ms p99, {floor_max} ms max)")
    check(f"{int(turn['turns']):,} observed turns" in rows[FLOOR_ROW][1],
          f"the term floor row was measured over results.json's {turn['turns']:,} turns ({rows[FLOOR_ROW][1]!r})")
    m = need(r"On a `/chat` turn it costs \*\*([\d.]+) ms median, ([\d.]+) ms at p99\*\*, against a median turn of "
             r"([\d.]+) s", flat, "## The answer")
    check(agrees(m[1], floor_med) and agrees(m[2], floor_p99) and agrees(m[3], turn["turn_ms_median"] / 1000),
          f"the answer's {m[1]} ms median, {m[2]} ms p99 on a {m[3]} s turn are results.json's")

    std = timing["bedrock-standard"]
    m = need(r"^([\d,]+) ms median round trip \(([\d,]+) ms of it Bedrock's processing\)$", rows[STANDARD_ROW][0],
             STANDARD_ROW)
    std_ms, std_proc = m[1], m[2]
    check(within(std_ms, std["round_trip_ms_median"], 0.10)
          and within(std_proc, std["guardrail_processing_ms_median"], 0.10) and num(std_proc) < num(std_ms),
          f"Bedrock Standard's {std_ms} ms round trip ({std_proc} ms processing) is within 10% of results.json's "
          f"median over all {std['calls']} calls ({std['round_trip_ms_median']} ms, "
          f"{std['guardrail_processing_ms_median']} ms), and the processing is part of the round trip")
    m = need(r"^(\d+) observed prompts", rows[STANDARD_ROW][1], STANDARD_ROW)
    check(int(m[1]) == texts["observed-prompt"],
          f"Bedrock Standard's {m[1]} observed prompts are results.json's {texts['observed-prompt']}")
    m = need(r"It adds \*\*([\d,]+) ms median\*\* to a turn, one `ApplyGuardrail` round trip from this host, of which "
             r"([\d,]+) ms is Bedrock's own processing", flat, "## The answer")
    check((m[1], m[2]) == (std_ms, std_proc),
          f"the answer's Bedrock {m[1]} ms ({m[2]} ms processing) is the latency table's ({std_ms} ms, {std_proc} ms)")
    check("Amazon Bedrock Guardrails, Standard tier" in flat,
          "the answer chooses Bedrock Guardrails' Standard tier, the row the chosen pair's sum is taken from")

    cls = timing["bedrock-classic"]
    m = need(r"^([\d,]+) ms median \(([\d,]+) ms processing\)$", rows[CLASSIC_ROW][0], CLASSIC_ROW)
    check(within(m[1], cls["round_trip_ms_median"], 0.10) and within(m[2], cls["guardrail_processing_ms_median"], 0.10),
          f"Bedrock Classic's {m[1]} ms ({m[2]} ms processing) is within 10% of results.json's "
          f"({cls['round_trip_ms_median']} ms, {cls['guardrail_processing_ms_median']} ms)")
    tox = timing["toxicity"]
    m = need(r"^([\d,]+) ms median, ([\d,]+) ms p99$", rows[TOXICITY_ROW][0], TOXICITY_ROW)
    check(agrees(m[1], tox["per_text_ms_median"]) and agrees(m[2], tox["per_text_ms_p99"]),
          f"LLM Guard Toxicity's {rows[TOXICITY_ROW][0]!r} is results.json's "
          f"({tox['per_text_ms_median']} ms, {tox['per_text_ms_p99']} ms)")

    m = need(r"The chosen pair adds about half a second to a ([\d.]+) s turn, all of it the classifier's\. The term "
             r"floor alone adds about a millisecond\.", prose, SECTION)
    pair_s = (floor_med + num(std_ms)) / 1000
    check(0.4 <= pair_s <= 0.6 and agrees(m[1], turn["turn_ms_median"] / 1000),
          f"the chosen pair (term floor {floor_med} ms + Bedrock Standard {std_ms} ms = {pair_s:.3f} s) is about half "
          f"a second on a {m[1]} s turn")
    check(0.5 <= floor_med <= 2 and floor_med / (floor_med + num(std_ms)) < 0.01,
          f"the term floor alone ({floor_med} ms) is about a millisecond, under 1% of the pair")

    # 2. The term floor as it stands costs a turn what the record says.
    by_source = collections.defaultdict(list)
    for src, text in corpus.stage_texts():
        by_source[src].append(text)
    prompts = [t for s in PROMPT_SOURCES for t in by_source[s]]
    m = need(r"^([\d.]+) ms on a ([\d,]+)-character reply$", rows[GO_ROW][0], GO_ROW)
    reply_len = int(num(m[2]))
    pool = " ".join(t for s in REPLY_SOURCES for t in by_source[s])
    check(len(prompts) >= 40 and len(pool) >= 10 * reply_len,
          f"corpus.py reads at least 40 /chat prompts ({len(prompts)}) and {10 * reply_len} characters of tool and "
          f"cluster data ({len(pool)}) from the repo")
    reply, long_reply = pool[:reply_len], pool[:10 * reply_len]

    f = floor.Floor("proposed")
    mask_us = best_us(f.mask, reply)
    turns_ms = sorted((best_us(f.spans, p) + mask_us) / 1000 for p in prompts)
    costliest = turns_ms[-1]
    check(costliest <= floor_max,
          f"the costliest of {len(prompts)} turns (a repo /chat prompt checked, a {reply_len:,}-character reply "
          f"masked) costs {costliest:.2f} ms, within the {floor_max} ms the worst observed turn cost "
          f"(median {turns_ms[len(turns_ms) // 2]:.2f} ms, best of {RUNS} each)")
    long_us = best_us(f.mask, long_reply)
    check(long_us <= 20 * mask_us,
          f"masking a {len(long_reply):,}-character reply costs {long_us / 1000:.2f} ms, at most 20 times the "
          f"{mask_us / 1000:.2f} ms of a {reply_len:,}-character one: the floor grows with the reply's length, "
          f"not faster")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
