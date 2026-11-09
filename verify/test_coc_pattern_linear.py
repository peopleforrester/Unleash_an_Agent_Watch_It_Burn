#!/usr/bin/env python3
# ABOUTME: The code-of-conduct pattern matches in time linear in the text (#1300): floor.py and every copy of it under
# ABOUTME: gitops/ are timed on 1,000 and 4,000 characters of each repeated leetspeak pair, and fail growing faster.
"""Offline: floor.py, the two ports of it (workshop-mcp-server.py and ticket_site.py, run from their own block) and the
copies of floor.portable_pattern() that verify/coc_pattern_copies.py finds (the admission policy's and the collector's),
standard library and PyYAML only. No cluster, no network.

Runs 19692 and 19727 timed the floor for #1292 and found a 4,000-character run of `5$` took a second in
workshop-mcp-server.py's coc_spans(), and floor.py the same: each letter of a term was its whole class repeated, so a
run of symbols let a term start after every symbol and each start read to the run's end. A guest could send that to
deploy_app, the ticket desk or, once guard-proxy runs the floor, /chat.

1. Each case of verify/coc_linear_cases.py (a run of each repeated leetspeak pair, and each term up to two neighbouring
   letters that share a character, then a run of what they share) is timed at 1,000 and 4,000 characters on each copy.
   At 4,000 characters each must take under 50 ms, and four times the text at most eight times as long, which linear
   time meets and time in the square of the length does not (coc_linear_cases.within() says how it is timed).
2. The check catches the pattern as it was before #1300: built the old way, a run of `$` fails it.
3. The cases reach every place the old form went quadratic: every pair of neighbouring letters in the term list whose
   classes share a character has a case.

The admission policy and the collector run the pattern in RE2, which is linear in any pattern; Python's backtracking
engine is not, so timing their copies here shows the pattern itself has no run that costs more than its length.
The chat page's JavaScript port is timed on the same cases in node by the test_chat_coc_e2e check.
"""
from __future__ import annotations

import codecs
import pathlib
import re
import sys
import time
import unicodedata

VERIFY = pathlib.Path(__file__).resolve().parent
REPO = VERIFY.parent
sys.path.insert(0, str(VERIFY))

import coc_linear_cases as cases  # noqa: E402
import coc_pattern_copies as cpc  # noqa: E402
from coc_linear_cases import floor  # noqa: E402

SHORT, LONG, LIMIT_MS, GROWTH = cases.SHORT, cases.LONG, cases.LIMIT_MS, cases.GROWTH

failures: list[str] = []


def check(what: str, ok: bool) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + what)
    if not ok:
        failures.append(what)


def best_ms(fn, texts: tuple[str, ...], runs: int) -> list[float]:
    """The fastest of `runs` timings of fn on each text, in ms. The texts take turns, so a burst of load on the host
    falls on both lengths rather than on one."""
    best = [float("inf")] * len(texts)
    for _ in range(runs):
        for i, text in enumerate(texts):
            t0 = time.perf_counter()
            fn(text)
            best[i] = min(best[i], time.perf_counter() - t0)
    return [b * 1000 for b in best]


def judge(fn, prefix: str, unit: str, runs: int = cases.RUNS, again: bool = True) -> tuple[float, float, bool]:
    """(ms at SHORT, ms at LONG, coc_linear_cases.within() of them), timed again over CONFIRM_RUNS when outside."""
    texts = (cases.text(prefix, unit, SHORT), cases.text(prefix, unit, LONG))
    for n in (runs, cases.CONFIRM_RUNS) if again else (runs,):
        short, long = best_ms(fn, texts, n)
        ok = cases.within(short, long)
        if ok:
            break
    return short, long, ok


FILES = cpc.gitops_files()


def port(p: cpc.Port):
    """The coc_spans() of a file's port of floor.py, run from the block between its markers alone."""
    path, text = p.path, FILES[p.path]
    for marker in (p.start, p.end):
        if text.count(marker) != 1:
            sys.exit(f"FAIL {path}: the marker {marker!r} is there {text.count(marker)} times, not once; this test "
                     "runs the block between the two markers")
    ns = {"__name__": f"coc_port_{pathlib.Path(path).stem}", "codecs": codecs, "re": re, "unicodedata": unicodedata}
    body = text.split(p.start, 1)[1].split("\n", 1)[1].split(p.end, 1)[0]  # from the line after the start marker
    exec(compile(body, path, "exec"), ns)
    if ns["_COC_RE"].pattern != floor.proposed_pattern().pattern:
        sys.exit(f"FAIL {path}: its port builds a pattern other than floor.proposed_pattern(); "
                 "the test_deploy_coc check names the difference")
    return ns["coc_spans"]


def finditer(regex: str):
    compiled = re.compile(regex)
    return lambda text: list(compiled.finditer(text))


# Each copy, by what runs it. The Sites' copies decode to one regex, which is timed once for all of them.
COPIES: dict[str, object] = {"floor.py Floor('proposed').spans (folding, then proposed_pattern())":
                             floor.Floor("proposed").spans}
for p in cpc.PORTS:
    COPIES[f"{p.path} coc_spans()"] = port(p)
found, problems = cpc.scan(FILES)
if problems or not found:
    sys.exit("FAIL verify/coc_pattern_copies.py finds no copy or a problem; the test_coc_pattern_copies check names "
             f"it: {problems[:2]}")
by_regex: dict[str, list[str]] = {}
for c in found:
    by_regex.setdefault(c.decoded, []).append(c.site.path)
by_regex.setdefault(floor.portable_pattern(), []).insert(0, "floor.portable_pattern()")
for regex, where in by_regex.items():
    COPIES[" and ".join(where) + f" ({len(regex):,} characters, in Python's re)"] = finditer(regex)

ALL = cases.cases()
print(f"== 1. each of {len(ALL)} runs, at {SHORT:,} and {LONG:,} characters, on each of {len(COPIES)} copies ==")
for name, fn in COPIES.items():
    worst, bad = (0.0, 0.0, ""), []
    started = time.perf_counter()
    for label, prefix, unit in ALL:
        short, long, ok = judge(fn, prefix, unit)
        if long > worst[1]:
            worst = (short, long, label)
        if not ok:
            bad.append(f"{label}: {short:.1f} ms at {SHORT:,}, {long:.1f} ms at {LONG:,}")
    for line in bad[:5]:
        print(f"        {line}")
    check(f"{name}: every run of {LONG:,} characters under {LIMIT_MS:.0f} ms and at most {GROWTH:.0f} times its "
          f"{SHORT:,}-character cost (slowest: {worst[2]}, {worst[0]:.1f} ms then {worst[1]:.1f} ms; "
          f"{len(bad)} failed; {time.perf_counter() - started:.1f} s)", not bad)

print("== 2. the check fails the pattern as it was before #1300 ==")
real = floor._run
floor._run = lambda ch, after: floor._letter(ch) + "+"  # each letter its whole class repeated, as before #1300
try:
    before = floor.proposed_pattern()
finally:
    floor._run = real
check("the old form differs from the pattern now", before.pattern != floor.proposed_pattern().pattern)
for unit in ("$", "5$"):
    short, long, ok = judge(lambda t: list(before.finditer(t)), "", unit, runs=1, again=False)
    check(f"built the old way, a run of {unit!r} fails the check ({short:.0f} ms at {SHORT:,}, {long:.0f} ms at "
          f"{LONG:,})", not ok)

print("== 3. the cases reach every pair of neighbouring letters that share a character ==")
covered = {(label.split("where ")[1][:-1]) for label, prefix, _ in ALL if prefix}
pairs = set()
for term in cases.corpus.terms("proposed"):
    text = " ".join(floor.fold(term)[0].split())
    pairs |= {f"{x!r} meets {y!r}" for x, y in zip(text, text[1:]) if set(cases.chars(x)) & set(cases.chars(y))}
check(f"each of the {len(pairs)} pairs of neighbouring letters whose classes share a character has a case "
      f"(missing: {sorted(pairs - covered)})", pairs <= covered and len(pairs) > 20)
check("every letter with a leetspeak stand-in has its runs among the cases",
      {u for _, p, u in cases.pair_cases()} >= {c for ch in floor._LEET for c in cases.chars(ch)})

print()
if failures:
    print(f"FAIL: {len(failures)} checks failed")
    sys.exit(1)
print(f"PASS: floor.py's pattern and its {len(cpc.PORTS) + len(found)} copies under gitops/ match each repeated "
      "leetspeak run in time linear in its length")
