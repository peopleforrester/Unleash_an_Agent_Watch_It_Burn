#!/usr/bin/env python3
# ABOUTME: The collector's code-of-conduct patterns, cut short so the collector parses them in seconds (#1328), mask what
# ABOUTME: the single RE2 form and the folded floor mask: text for text on four corpora, and no term left on generated text.
"""Offline: the spike's floor and corpora, the stage files corpus.stage_texts() reads, and the pinned guard-proxy
submodule's slang fixture; standard library only. No cluster, no network.

#1316 grew the term list to 1,253 terms, and the collector's otelcol-contrib 0.160.0 parses an OTTL string in CPU time
that grows with the square of its length: the single floor.portable_pattern(), four statements of 108,370 characters,
cost about 46 s of CPU at every start (#1326). #1328 cuts it into floor.portable_patterns(), patterns of at most
floor.PORTABLE_LIMIT characters that the collector applies one after another, each twice. Applied in turn, a pattern
masks its terms before a later one sees the text, so the cut can change what is masked where two terms overlap. These
are the checks #1316 held portable_pattern() to, run on the cut, with portable_pattern() beside it:

1. On the spike's abuse set, guard-proxy's slang fixture, the stage texts and the hard negatives, the cut's mask is
   the folded floor's (Floor.mask) on each text that needs no folding, and portable_pattern()'s on every text, as
   written and JSON-encoded.
2. On generated texts (every term of the list, as written, upper case, plural, in two leetspeak spellings and one of
   symbols, joined by "_" or "-", spelt out with " ", "." or "-"; each alone, in a sentence, twice, after a JSON "\\n"
   and in curly quotes; and seeded pairs of terms): the cut masks a text exactly when portable_pattern() does, no term
   the folded floor finds is left in its output where portable_pattern() leaves none, and no character of a floor match
   that portable_pattern() masks is left showing.
3. Two terms spelt out back to back (seeded pairs, "f u c k" then "s h i t"): the cut masks exactly when
   portable_pattern() does and leaves no term the floor finds. Characters can show here that portable_pattern() masks:
   where one spelt-out term runs into the next, the single alternation takes the leftmost and the cut the longest
   (decisions.md, #1328); the count is printed.
4. The checks catch an order that would lose: the same patterns applied shortest terms first fail check 2.

Python's re with re.ASCII reads each pattern as RE2 does (coc_mask_cases.mask() says why);
test_collector_coc_mask_e2e.py runs the cut through the pinned otelcol-contrib.
"""
from __future__ import annotations

import codecs
import json
import pathlib
import random
import re
import sys

VERIFY = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(VERIFY))

from coc_mask_cases import corpora, floor, mask, patterns  # noqa: E402

corpus = floor.corpus
PAIRS = 8000          # seeded pairs of written terms (check 2)
SPELT_PAIRS = 8000    # seeded pairs of spelt-out terms (check 3)
FLOOR = floor.Floor("proposed")

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + what)
    if not ok:
        failures.append(what)


def rot13(texts) -> list[str]:
    return [codecs.encode(t, "rot13")[:80] for t in texts]


def masked(text: str, compiled: list[re.Pattern]) -> list[tuple[str, int | None]]:
    """The text after each pattern in turn, twice, as the collector applies them: each character with the index it
    had in the text, None for the replacement's. Its characters joined are coc_mask_cases.mask()'s output."""
    chars: list[tuple[str, int | None]] = [(c, i) for i, c in enumerate(text)]
    for regex in compiled:
        for _ in range(2):
            now = "".join(c for c, _ in chars)
            out, last = [], 0
            for m in regex.finditer(now):
                out += chars[last:m.start(2)] + [(c, None) for c in "[redacted]"]
                last = m.end(2)
            if not out:  # no match: a second pass finds none either
                break
            chars = out + chars[last:]
    return chars


def text_of(chars) -> str:
    return "".join(c for c, _ in chars)


def shown(text: str, chars) -> set[int]:
    """Each character of a folded floor match in the text that is still there after the mask."""
    inside = {i for a, b in FLOOR.spans(text) for i in range(a, b)}
    return {i for _, i in chars if i is not None and i in inside and text[i].isalnum()}


SINGLE = [re.compile(floor.portable_pattern(), re.ASCII)]
CUT = [re.compile(p, re.ASCII) for p in patterns()]
print(f"floor.portable_patterns(): {len(CUT)} patterns of at most {floor.PORTABLE_LIMIT:,} characters "
      f"({sum(len(p.pattern) for p in CUT):,} in all), against portable_pattern()'s {len(SINGLE[0].pattern):,}")

print("== 1. four corpora: the cut masks as the folded floor and portable_pattern() do, text for text ==")
CORPORA = corpora()
MINIMUM = {"abuse set": 150, "slang fixture": 80, "stage texts": 2000, "hard negatives": 50}
for name, texts in CORPORA.items():
    check(len(texts) >= MINIMUM[name], f"{name}: {len(texts)} texts read (at least {MINIMUM[name]})")
    plain = [t for t in texts if floor.fold(t)[0] == t.lower()]
    differ = [t for t in plain if text_of(masked(t, CUT)) != FLOOR.mask(t)]
    check(not differ, f"{name}: on the {len(plain)} texts that need no folding the cut's mask is the folded floor's "
                      f"(differ, ROT13: {rot13(differ[:3])})")
    differ = [t for t in texts for form in (t, json.dumps(t), json.dumps(t, ensure_ascii=False))
              if text_of(masked(form, CUT)) != text_of(masked(form, SINGLE))]
    check(not differ, f"{name}: on all {len(texts)}, as written and JSON-encoded both ways, it is portable_pattern()'s "
                      f"(differ, ROT13: {rot13(differ[:3])})")
masks = sum(text_of(masked(t, CUT)) != t for t in CORPORA["abuse set"])
check(masks >= 100, f"the cut masks {masks} of the abuse set's texts, so the corpora above test a mask")


def leet(word: str, pick: int) -> str:
    return "".join(floor._LEET[c][pick % len(floor._LEET[c])] if c in floor._LEET else c for c in word)


def symbols(word: str) -> str:
    out = []
    for c in word:
        sym = [s for s in floor._LEET.get(c, "") if not s.isalnum()]
        out.append(sym[0] if sym else "*" if c in floor._VOWELS else c)
    return "".join(out)


WORDS = list(dict.fromkeys(w for w in (" ".join(floor.fold(t)[0].split()) for t in corpus.terms("proposed")) if w))
rnd = random.Random(1328)
generated: list[str] = []
for w in WORDS:
    forms = [w, w.upper(), w + "s", leet(w, 0), leet(w, 1), symbols(w), w.replace(" ", "_"), w.replace(" ", "-")]
    if " " not in w and len(w) >= 3:
        forms += [" ".join(w), ".".join(w), "-".join(w), " ".join(w.upper())]
    for f in forms:
        generated += [f, f"you {f}!", f"{f} {f}", json.dumps(f"hey\n{f}"), f"‘{f}’"]
for _ in range(PAIRS):
    a, b = rnd.choice(WORDS), rnd.choice(WORDS)
    sep = rnd.choice([" ", ", ", " and ", "-", "."])
    generated += [a + sep + b, symbols(a) + sep + b, a + " " + (" ".join(b) if " " not in b else symbols(b))]
generated = list(dict.fromkeys(generated))


def compare(texts: list[str], compiled: list[re.Pattern]) -> dict[str, list[str]]:
    """The texts on which the patterns differ from portable_pattern(): masking or not, leaving a floor term, showing a
    character of a floor match that portable_pattern() masks."""
    out: dict[str, list[str]] = {"yes or no": [], "a term left": [], "a character shown": []}
    for t in texts:
        cut, one = masked(t, compiled), masked(t, SINGLE)
        if (text_of(cut) != t) != (text_of(one) != t):
            out["yes or no"].append(t)
        if FLOOR.spans(text_of(cut)) and not FLOOR.spans(text_of(one)):
            out["a term left"].append(t)
        if not shown(t, cut) <= shown(t, one):
            out["a character shown"].append(t)
    return out


print(f"== 2. {len(generated):,} generated texts: the cut leaves nothing portable_pattern() masks ==")
sample = generated[:: max(1, len(generated) // 400)]
check(all(text_of(masked(t, CUT)) == mask(t) for t in sample),
      f"masked() is coc_mask_cases.mask(), the collector's order, on {len(sample)} of the generated texts")
result = compare(generated, CUT)
hits = sum(bool(FLOOR.spans(t)) for t in generated)
check(hits > len(generated) // 2, f"the folded floor finds a term in {hits:,} of them")
for what, texts in result.items():
    check(not texts, f"{what}: none differ from portable_pattern() (differ: {len(texts)}, ROT13: {rot13(texts[:3])})")

print(f"== 3. {SPELT_PAIRS:,} pairs of spelt-out terms, back to back ==")
letters = [w for w in WORDS if " " not in w and len(w) >= 3 and w.isascii() and w.isalpha()]
spelt = list(dict.fromkeys(" ".join(rnd.choice(letters)) + " " + " ".join(rnd.choice(letters))
                           for _ in range(SPELT_PAIRS)))
result = compare(spelt, CUT)
for what in ("yes or no", "a term left"):
    check(not result[what], f"{what}: none differ from portable_pattern() (differ: {len(result[what])}, ROT13: "
                            f"{rot13(result[what][:3])})")
print(f"  INFO  on {len(result['a character shown'])} of {len(spelt):,} a letter of a floor match shows that "
      f"portable_pattern() masks, with no term left (ROT13: {rot13(result['a character shown'][:2])})")

print("== 4. the checks catch an order that would lose ==")
backwards = compare(generated, CUT[::-1])
check(len(backwards["a character shown"]) > 100,
      f"the same patterns applied shortest terms first show a character of a floor match on "
      f"{len(backwards['a character shown']):,} generated texts, so check 2 fails that order")

print()
if failures:
    print(f"FAIL: {len(failures)} checks failed")
    sys.exit(1)
print(f"PASS: the collector's {len(CUT)} code-of-conduct patterns mask what floor.portable_pattern() masks")
