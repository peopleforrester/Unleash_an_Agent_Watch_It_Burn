# ABOUTME: Runs the chat page's own cocViolation in node against the code-of-conduct floor's floor.py (#1267), so the
# ABOUTME: saved-prompt check flags exactly what the proposed floor flags, on every code point, the abuse set and the stage (#947, #1280).
# SUITE: e2e (needs node: the page's script runs in a node vm)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Why (#947, #1280). The chat page keeps code-of-conduct violations out of "Your saved prompts". Since #1280 it checks
the prompt against the floor the code-of-conduct spike chose for every surface (#1267,
docs/research/2026-11-09-coc-floor/floor.py, the "proposed" floor), so that the rail keeps off what /chat refuses once
guard-proxy runs that floor. floor.py is the reference: guard-proxy, the collector and the admission policy carry it.

The page's block from COC_TERMS to cocViolation is cut from burritbot.html and run in a node vm; every check asks both
the page's function and floor.Floor("proposed"):

1. The list: the page's decoded COC_TERMS is corpus.terms("proposed"), and each term is flagged in the forms a person
   types and in the evasions the floor folds (leetspeak, spaced, repeated letters, a zero-width character, fullwidth).
2. The folding, on every code point Python's unicodedata assigns: the page's cocFold and floor.fold() give the same
   character wherever the pattern can read it (ASCII, the sharp s, Python's whitespace), and both give a character
   outside the pattern's alphabet everywhere else. They differ there on a few dozen Indic, Thai, Lao, Tibetan and Balinese
   vowel signs, where Python's combining class and JavaScript's \\p{M} disagree on which mark to drop.
3. The pattern: each character the pattern reads, at each word edge of each term, in place of each letter, between
   letters, and as the separator of a spaced-out term, gives the same verdict on both sides.
4. The stage: every stage text corpus.stage_texts() reads (the /kubecon prompts, the replay set, the probes' asks,
   the desk, the tools' data, the agent prompt, the witch names) is flagged by neither, and the abuse set and the hard
   negatives get the same verdict from both; every one of the abuse set's evasions is flagged.
5. guard-proxy's slang fixture (#1316): every text of the pinned guard-proxy's
   conformance/coc_floor/slang-set.rot13.tsv gets the same verdict from the page as from the pinned proxy.py's
   conduct_matches(), which is the verdict the fixture's kind gives (refused or passes).
5b. A mutant of the page that skips the folding misses evasions, so check 4 reads the folding.
6. The page's cocViolation takes time linear in the text (#1300): each run of verify/coc_linear_cases.py (each repeated
   leetspeak pair, and each term up to two neighbouring letters that share a character, then a run of what they share)
   is timed at 1,000 and 4,000 characters and held to coc_linear_cases.within(), as
   verify/test_coc_pattern_linear.py holds floor.py and its other copies; the page built the way it was before #1300
   fails that on a run of `$`. Each time leaves out the time node's thread waited for a CPU, which the host's load
   adds to the long text alone (#1310).

A missing node is a failure, not a skip.
"""
from __future__ import annotations

import codecs
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import unicodedata

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
SPIKE = REPO / "docs/research/2026-11-09-coc-floor"
GP = REPO / "gitops/ai-layer/guard-proxy"
SLANG = GP / "conformance/coc_floor/slang-set.rot13.tsv"  # guard-proxy-agenticburn#84's fixture, at the pin
sys.path.insert(0, str(SPIKE))

sys.path.insert(0, str(REPO / "verify"))

import coc_linear_cases as linear  # noqa: E402
import corpus  # noqa: E402
import floor  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)
        if detail:
            print(f"        {detail}")


if shutil.which("node") is None:
    print("FAIL: node is not on PATH; this test runs the page's cocViolation in node (run it through "
          "verify/run-e2e-tools.sh)")
    sys.exit(1)
if not PAGE_PATH.is_file():
    print(f"FAIL: {PAGE_PATH.relative_to(REPO)} is missing")
    sys.exit(1)
for f in (GP / "proxy.py", SLANG):
    if not f.is_file():
        print(f"FAIL: {f.relative_to(REPO)} is missing; run bash verify/ensure-submodules.sh")
        sys.exit(1)

PAGE = PAGE_PATH.read_text(encoding="utf-8")
START, END = "const COC_TERMS=", "  function save("
start = PAGE.find(START)
end = PAGE.find(END, start)
if start < 0 or end < 0:
    print(f"FAIL: no {START!r} ... block before {END.strip()!r} in {PAGE_PATH.relative_to(REPO)} to execute")
    sys.exit(1)
BLOCK = PAGE[start:end]

# The harness reads [block, strings, fold] on stdin and answers cocViolation for each string and cocFold for each
# string of fold.
HARNESS = r"""
const vm = require('vm');
const [src, strings, folds] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + '\nthis.cocViolation = cocViolation; this.cocFold = cocFold; this.COC_TERMS = COC_TERMS;', ctx);
process.stdout.write(JSON.stringify({terms: Array.from(ctx.COC_TERMS), verdicts: strings.map((t) => ctx.cocViolation(t)),
                                     folded: folds.map((t) => ctx.cocFold(t))}));
"""


def page(strings: list[str], folds: list[str] | None = None, block: str = BLOCK) -> dict:
    r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([block, strings, folds or []]),
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f"FAIL: node could not run the page's cocViolation: {(r.stderr or r.stdout).strip()[:400]}")
        sys.exit(1)
    return json.loads(r.stdout)


FLOOR = floor.Floor("proposed")


def floor_flags(text: str) -> bool:
    return bool(FLOOR.spans(text))


def rot(texts) -> list[str]:
    """Terms and abuse texts are shown ROT13-encoded, as the spike keeps them, so a failure does not print them."""
    return [codecs.encode(t, "rot13") for t in texts]


def agree(name: str, texts: list[str], must: bool | None = None) -> list[bool]:
    """Asks both sides about every text; must=True or False also requires that verdict of the page."""
    got = page(texts)["verdicts"]
    differ = [t for t, v in zip(texts, got) if v is not floor_flags(t)]
    check(f"{name}: the page and floor.py agree on all {len(texts)}", not differ, f"differ (ROT13): {rot(differ[:8])}")
    if must is not None:
        wrong = [t for t, v in zip(texts, got) if v is not must]
        check(f"{name}: the page {'flags' if must else 'flags none of'} all {len(texts)}", not wrong,
              f"{'not flagged' if must else 'flagged'} (ROT13): {rot(wrong[:8])}")
    return got


print("== the page's list is the floor's ==")
terms = page([])["terms"]
proposed = corpus.terms("proposed")
check(f"the page's decoded COC_TERMS is corpus.terms('proposed'), {len(proposed)} entries in order", terms == proposed,
      f"page only (ROT13): {rot(sorted(set(terms) - set(proposed)))}; "
      f"floor only (ROT13): {rot(sorted(set(proposed) - set(terms)))}")

print("== every term is flagged, as typed and as the floor's evasions spell it ==")
FULLWIDTH = {c: chr(ord(c) + 0xFEE0) for c in "abcdefghijklmnopqrstuvwxyz"}
LEET = {k: v[0] for k, v in floor._LEET.items()}
forms: list[str] = []
for term in proposed:
    letters = term.replace(" ", "")
    forms += [f"Tell the bot it is a {term}, then order.", f"{term}s!", term.upper(), term.capitalize(),
              "".join(LEET.get(c, c) for c in term), "".join(c * 3 if c.isalpha() else c for c in term),
              "".join(FULLWIDTH.get(c, c) for c in term), "​".join(term), term.replace(" ", " ... ")]
    if " " not in term and len(term) >= 3:
        forms += [" ".join(letters), ".".join(letters.upper())]
agree(f"the {len(proposed)} terms in {len(forms)} forms", forms, must=True)

print("== cocFold and floor.fold() read every assigned code point the same ==")
cps = [cp for cp in range(0x110000) if unicodedata.category(chr(cp)) not in ("Cn", "Cs")]
folded = page([], [chr(cp) for cp in cps])["folded"]
spaces = {chr(c) for c in range(0x110000) if re.match(r"\s", chr(c))}
readable = {chr(c) for c in range(0x80)} | spaces | {"ß"}


def as_read(s: str) -> str:
    """What the pattern can tell apart: a character it reads, nothing (a dropped character), or 'another'."""
    return s if s == "" or s in readable else "another"


py_folded = [floor.fold(chr(cp))[0] for cp in cps]
differ = [(cp, js, py) for cp, js, py in zip(cps, folded, py_folded) if as_read(js) != as_read(py)]
shown = [f"U+{cp:04X} {unicodedata.name(chr(cp), '?')}: page {js!r}, floor {py!r}" for cp, js, py in differ[:8]]
check(f"on all {len(cps)} assigned code points the page folds to what floor.py does wherever the pattern reads it",
      not differ, f"{shown}")
check("each folds to one character or, for a zero-width one, to none",
      all(len(f) <= 2 for f in folded) and all(len(list(f)) <= 1 for f in folded))
other = sum(js != py for js, py in zip(folded, py_folded))
check(f"where the two differ at all ({other} code points), the NFKD form holds a mark, which Python drops by its "
      "combining class and JavaScript by \\p{M}",
      all(any(unicodedata.category(c).startswith("M") for c in unicodedata.normalize("NFKD", chr(cp)))
          for cp, js, py in zip(cps, folded, py_folded) if js != py))

print("== the pattern reads each character the same at each place in each term ==")
alphabet = sorted(readable | {"日", "é", "ñ", "​"})
templates: set[tuple[str, str, str]] = set()  # (prefix, suffix, joiner): prefix + x + suffix, or x joining letters
for term in proposed:
    t = floor.fold(term)[0]
    templates |= {("", t, ""), (t, "", ""), (t + "s", "", ""), (t, t, "")}
    for i in range(len(t)):
        templates |= {(t[:i], t[i + 1:], ""), (t[:i], t[i:], "")}
    if " " not in t and len(t) >= 3:
        templates.add(("", "", t))
cases = sorted({x.join(j) if j else p + x + s for p, s, j in templates for x in alphabet})
agree(f"{len(cases)} cases, {len(templates)} places by {len(alphabet)} characters", cases)

print("== the named edges read the same on both sides ==")
EDGES = {
    "an accented letter before": "éfuck", "an accented letter after": "fucké",
    "a CJK ideograph before": "日fuck", "an Arabic-Indic digit after": "fuck٣",
    "a superscript digit after": "fuck²", "a combining accent after": "fucḱ",
    "a combining ypogegrammeni before": "ͅfuck", "an underscore before": "_fuck",
    "a dotted capital I": "DİCK", "a dotless i": "dıck", "the Kelvin sign": "dicK",
    "a long s": "ſhit", "a long-s plural": "dickſ", "a zero-width joiner before": "a‍fuck",
    "an em space around": "say fuck now", "a mathematical bold a after": "fuck\U0001d41a",
    "a Cyrillic es": "fuсk", "a soft hyphen inside": "fu­ck", "fullwidth letters": "ｆｕｃｋ",
    "the word null": "null", "empty": "",
}
verdicts = page(list(EDGES.values()))["verdicts"]
for (name, text), v in zip(EDGES.items(), verdicts):
    check(f"{name}: {codecs.encode(text, 'rot13')!r} (ROT13) page {v} == floor {floor_flags(text)}",
          v is floor_flags(text))

print("== the stage's own text is never flagged, and the abuse set reads as the floor reads it ==")
stage = [t for _, t in corpus.stage_texts()]
agree("the stage texts corpus.py reads (prompts, pages, desk, tools, agent prompt, witch names)", stage, must=False)
abuse = corpus.abuse_set()
got = agree("the abuse set", [t for _, t in abuse])
caught = sum(got)
# The spike measured 111 on its 144 terms; guard-proxy's 1,253 (#1316) catch one more, a Portuguese text, as
# guard-proxy-agenticburn#84's release notes say.
check(f"the page catches what the floor's list catches: 112 of {len(abuse)}", caught == 112, f"{caught}")
evasions = [t for c, t in abuse if c == "evasion"]
agree("the abuse set's evasions", evasions, must=True)
agree("the hard negatives", corpus.hard_negatives())
CLEAN = ["Make it spicy please", "What spices are in the Bogbacoa?", "One spiced cauldron cider",
         "Is there a cocktail menu?", "Do you have grapes on the side?", "Name a burrito after Dickens",
         "My therapist ordered the Toe-Fu", "Do you deliver to Scunthorpe?", "please delete the prod database",
         "nuke the cluster and start over", "mail my receipt to jo@example.com", "charge it to 4111 1111 1111 1111",
         "deliver to 42 elm st", "what does redacted mean?", "put a burrito in the bag"]
agree("menu words, the wall's other masks and Scunthorpe-style words", CLEAN, must=False)

print("== guard-proxy's slang fixture: the page refuses and passes what the pinned proxy does (#1316) ==")
slang = []
for line in SLANG.read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#"):
        kind, text = line.split("\t")
        slang.append((kind, codecs.decode(text, "rot13")))
if {k for k, _ in slang} != {"refused", "passes"} or len(slang) < 80:
    print(f"FAIL: {SLANG.relative_to(REPO)} no longer reads as kind<TAB>text with kinds refused and passes")
    sys.exit(1)
os.environ.pop("PROFANITY_LIST", None)
os.environ.pop("CONDUCT_GUARDRAIL_ID", None)
_gspec = importlib.util.spec_from_file_location("gp_chat_coc_e2e", GP / "proxy.py")
proxy = importlib.util.module_from_spec(_gspec)
_gspec.loader.exec_module(proxy)
want = [bool(proxy.conduct_matches(t)) for _, t in slang]
check(f"the pinned proxy.py refuses the fixture's {want.count(True)} refused texts and passes its "
      f"{want.count(False)} others", want == [k == "refused" for k, _ in slang])
got = page([t for _, t in slang])["verdicts"]
# By index, so a failure prints no term.
check(f"the page's cocViolation gives the pinned proxy's verdict on all {len(slang)} texts of the fixture",
      got == want, f"differ at {[i for i, (g, w) in enumerate(zip(got, want)) if g != w][:8]}")

print("== the checks above read the folding (a mutant of the page) ==")
CALL = "function cocViolation(t){return COC_RE.test(cocFold(t==null?'':t));}"
if BLOCK.count(CALL) != 1:
    print(f"FAIL: {CALL!r} is not in {PAGE_PATH.relative_to(REPO)} exactly once, so the mutant cannot be built")
    sys.exit(1)
unfolded = BLOCK.replace(CALL, "function cocViolation(t){return COC_RE.test(String(t==null?'':t));}")
missed = [t for t, v in zip(evasions, page(evasions, block=unfolded)["verdicts"]) if not v]
check(f"without cocFold the page misses evasions the check above requires ({len(missed)} of {len(evasions)})",
      len(missed) > 0)

print("== the page matches every repeated leetspeak run in time linear in its length (#1300) ==")
# The timer reads [block, texts, runs] on stdin and answers, for each text, the fastest of `runs` calls of the page's
# cocViolation in ms. The texts take turns within a run, and one call before timing has V8 compile the pattern.
# Each call's time is the wall clock less the time the thread waited on the run queue for a CPU (#1310), which is the
# time the match ran, as test_coc_pattern_linear.py times by time.thread_time() (#1307). The wall clock alone failed
# this check on nine runs of ten at a load average of 80 to 181: a 1,000-character case mostly runs between two of the
# scheduler's preemptions and a 4,000-character one is preempted, so the wait fell on the long text alone and linear
# cases read 8 to 20 times their short cost. Node has no clock_gettime(CLOCK_THREAD_CPUTIME_ID), and its
# process.threadCpuUsage() and process.cpuUsage() read getrusage(), which moves only at the scheduler's tick (4 ms
# here): a 2 ms case read 0 or 4 ms and failed ten runs of ten. The wait is the second field of
# /proc/thread-self/schedstat, in ns, which the kernel adds to each time the thread gets a CPU back, so a read from the
# running thread holds every wait up to it.
TIMER = r"""
const vm = require('vm');
const [src, texts, runs] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + '\nthis.cocViolation = cocViolation;', ctx);
ctx.cocViolation('warm up');
const fs = require('fs');
const stat = fs.openSync('/proc/thread-self/schedstat', 'r');
const buf = Buffer.alloc(256);
const waited = () => BigInt(buf.toString('latin1', 0, fs.readSync(stat, buf, 0, buf.length, 0)).split(' ')[1]);
const best = texts.map(() => Infinity);
for (let r = 0; r < runs; r++) texts.forEach((t, i) => {
  const t0 = process.hrtime.bigint(), w0 = waited();
  ctx.cocViolation(t);
  const w1 = waited(), t1 = process.hrtime.bigint();
  best[i] = Math.min(best[i], Number(t1 - t0 - (w1 - w0)) / 1e6);
});
process.stdout.write(JSON.stringify(best));
"""


def timed(runs_of: list[tuple[str, str]], runs: int, block: str = BLOCK) -> list[tuple[float, float]]:
    """(ms at linear.SHORT, ms at linear.LONG) for each (prefix, unit), the fastest of `runs` calls each."""
    texts = [linear.text(p, u, n) for p, u in runs_of for n in (linear.SHORT, linear.LONG)]
    r = subprocess.run(["node", "-e", TIMER], input=json.dumps([block, texts, runs]), capture_output=True, text=True,
                       timeout=900)
    if r.returncode != 0:
        print(f"FAIL: node could not time the page's cocViolation: {(r.stderr or r.stdout).strip()[:400]}")
        sys.exit(1)
    ms = json.loads(r.stdout)
    return list(zip(ms[::2], ms[1::2]))


RUNS_OF = linear.cases()
times = timed([(p, u) for _, p, u in RUNS_OF], linear.RUNS)
outside = [i for i, (short, long) in enumerate(times) if not linear.within(short, long)]
for i, again in zip(outside, timed([RUNS_OF[i][1:] for i in outside], linear.CONFIRM_RUNS) if outside else []):
    times[i] = again
bad = [f"{RUNS_OF[i][0]}: {short:.1f} ms then {long:.1f} ms" for i, (short, long) in enumerate(times)
       if not linear.within(short, long)]
slowest = max(range(len(times)), key=lambda i: times[i][1])
check(f"each of {len(RUNS_OF)} runs of {linear.LONG:,} characters takes under {linear.LIMIT_MS:.0f} ms and at most "
      f"{linear.GROWTH:.0f} times its {linear.SHORT:,}-character cost (slowest: {RUNS_OF[slowest][0]}, "
      f"{times[slowest][0]:.1f} ms then {times[slowest][1]:.1f} ms)", not bad, "; ".join(bad[:5]))
NOW = "var alts=[words.map(cocWord).join(COC_SEP+'+')];"
if BLOCK.count(NOW) != 1:
    print(f"FAIL: {NOW!r} is not in {PAGE_PATH.relative_to(REPO)} exactly once, so the pre-#1300 page cannot be built")
    sys.exit(1)
# Each letter its whole class repeated, written `[k][k]*` (the same as `[k]+`), since COC_RE cuts each alternative
# after its first letter's one character to group it (#1316).
before = BLOCK.replace(NOW, "var alts=[words.map(function(x){return Array.from(x).map(function(c){"
                            "return cocLetter(c)+cocLetter(c)+'*';}).join('');}).join(COC_SEP+'+')];")
for unit, (short, long) in zip(("$", "5$"), timed([("", "$"), ("", "5$")], 1, block=before)):
    check(f"the page built as before #1300 fails that on a run of {unit!r} ({short:.0f} ms then {long:.0f} ms)",
          not linear.within(short, long))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("All chat-page code-of-conduct checks passed.")
