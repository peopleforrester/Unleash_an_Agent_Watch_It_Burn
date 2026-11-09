# ABOUTME: The texts the code-of-conduct pattern is timed on (#1300): long runs of each repeated leetspeak pair, and of
# ABOUTME: each character two neighbouring letters of a term share, read from floor.py so they follow its tables.
"""Standard library only; reads docs/research/2026-11-09-coc-floor/floor.py and terms-proposed.rot13.

Before #1300 each letter of a term was its whole class repeated (`[s5$]+`). A run of symbols such as `5$` or `(` let a
term start after every symbol, and each start read to the run's end; a run two neighbouring letters can both take
(the doubled s of a term, the 1 that is both i and l, the `*` a vowel and a separator share) was split every way
there is. Either costs time in the square of the run's length. These are those runs:

    pair_cases()     a run of each pair of characters one letter's class holds (the letter, its leetspeak stand-ins,
                     `*` for a vowel), and of each pair of separator characters, a pair of one character included
    in_term_cases()  for each pair of neighbouring letters (or a letter and the separator of a phrase) whose classes
                     share a character, the first term with them, up to them, then a run of each pair of the shared
                     characters

A case is (label, prefix, unit); text() repeats the unit after the prefix to a length. A label shows a prefix
ROT13-encoded, as the spike's files keep the terms.

within() is the verdict both timing tests give a case (test_coc_pattern_linear on floor.py and its copies,
test_chat_coc_e2e on the chat page's port): at LONG characters under LIMIT_MS, and at most GROWTH times its
SHORT-character cost (linear time takes four times as long on four times the text; time in the square of the length
takes sixteen) wherever LONG characters take NOISE_MS or more, below which the timer's own noise is most of it. Each
time is the best of RUNS, and a case outside a bound is timed again, the best of CONFIRM_RUNS, and that verdict stands:
on a host shared with other runs a burst of load can slow one length's three runs, while a quadratic case is outside
on every run.
"""
from __future__ import annotations

import codecs
import itertools
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "docs/research/2026-11-09-coc-floor"))

import corpus  # noqa: E402
import floor  # noqa: E402

SEPARATORS = " ._*-"  # floor._SEP's characters, its whitespace as the space
SHORT, LONG = 1_000, 4_000
LIMIT_MS, GROWTH, NOISE_MS = 50.0, 8.0, 1.0
RUNS, CONFIRM_RUNS = 3, 9


def within(short_ms: float, long_ms: float) -> bool:
    return long_ms < LIMIT_MS and (long_ms < NOISE_MS or long_ms <= GROWTH * short_ms)


def chars(letter: str) -> str:
    """The characters floor.py's class for the letter matches, or the separator's for " "."""
    if letter == " ":
        return SEPARATORS
    return letter + floor._LEET.get(letter, "") + ("*" if letter in floor._VOWELS else "")


def _units(alphabet: str) -> list[str]:
    return [a + b if a != b else a for a, b in itertools.combinations_with_replacement(alphabet, 2)]


def pair_cases() -> list[tuple[str, str, str]]:
    seen, out = set(), []
    for letter in sorted(floor._LEET) + [" "]:
        for unit in _units(chars(letter)):
            if unit not in seen:
                seen.add(unit)
                out.append((f"a run of {unit!r} (the {'separator' if letter == ' ' else repr(letter)} class)", "", unit))
    return out


def in_term_cases() -> list[tuple[str, str, str]]:
    seen, out = set(), []
    for term in corpus.terms("proposed"):
        text = " ".join(floor.fold(term)[0].split())
        for i in range(len(text) - 1):
            x, y = text[i], text[i + 1]
            shared = "".join(c for c in chars(x) if c in chars(y))
            if not shared or (x, y) in seen:
                continue
            seen.add((x, y))
            prefix = text[:i]
            for unit in _units(shared):
                out.append((f"{codecs.encode(prefix, 'rot13')!r} then a run of {unit!r} (where {x!r} meets {y!r})",
                             prefix, unit))
    return out


def cases() -> list[tuple[str, str, str]]:
    return pair_cases() + in_term_cases()


def text(prefix: str, unit: str, length: int) -> str:
    return prefix + (unit * length)[:length]
