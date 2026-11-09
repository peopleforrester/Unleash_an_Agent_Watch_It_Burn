# ABOUTME: The two term-list candidates of the code-of-conduct spike (#1267): guard-proxy's PROFANITY regex as it runs
# ABOUTME: today, and the proposed floor (a longer list, folded spellings, leetspeak, spaced letters), each find and mask.
"""Term floors, standard library only, so guard-proxy (proxy.py), ticket_site.py and workshop-mcp-server.py can carry
the proposed one as it is.

current   guard-proxy-agenticburn a637e68's `_profanity_pattern(_DEFAULT_PROFANITY)`: 40 terms, whole word, optional
          plural s, case-insensitive. Copied, not imported, so this spike runs with the submodule not checked out.

proposed  the spike's floor. Before matching, each character of the text is folded on its own (so a match maps back
          onto the original text one to one): zero-width characters and soft hyphens dropped, compatibility and accent
          forms reduced to their base letter (fullwidth "ｆ" to "f", "ñ" to "n"), Cyrillic and Greek look-alikes mapped
          to Latin, lower case. Each term then matches as a whole word with:
            - each letter's leetspeak stand-ins (0 o, 1 i l, 3 e, 4 a, 5 s, 7 t, 8 b, 9 g, @ a, $ s, ! i, | l, ( c,
              + t),
            - "*" in place of any vowel ("f*ck"),
            - each letter repeatable as itself or a digit stand-in ("fuuuck", "sh1iit", "a55hole"),
            - or the whole term spelt out with one separator between every letter ("f u c k", "c.u.n.t"); a separator
              only between some letters does not count, so "put a" is not "puta".
          Phrases (two or three words) match with any run of spaces, dots, dashes or underscores between the words.

Matching is linear in the length of the text (#1300). Each letter was its whole class repeated (`[s5$]+`), and the
classes overlap: a run of `$`, `5$`, `(` or `4@` let a term start after every symbol in it, each start read to the
run's end, and so did each way of splitting the run between two letters, so 4,000 characters cost seconds. Now a
letter is one character of its class, then a run of only the letter and its digit stand-ins, less any the next
letter's class holds. A symbol or "*" stands for one letter once, so no start reads past a run of symbols, and a term
cannot start inside a run of letters or digits (the leading edge refuses one). Where one letter ends and the next
begins is never in doubt (the doubled s of "ass" is one s and then a run, the 1 of "kil1" is an l), so no split is
tried twice. Every text of the spike's abuse set, hard negatives, stage text and terms matches as it did before.
"""
from __future__ import annotations

import re
import unicodedata

import corpus

_LEET = {"a": "4@", "b": "8", "c": "(", "e": "3", "g": "9", "i": "1!|", "l": "1|", "o": "0", "s": "5$", "t": "7+"}
_VOWELS = set("aeiou")
_SEP = r"[\s._*\-]"
_ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿", "­"}
# Cyrillic and Greek letters that render as Latin ones, and the dotless i (U+0131), which has no decomposition and which
# guard-proxy's case-blind match (Python's re.IGNORECASE) reads as i (#1301)
_HOMOGLYPH = str.maketrans("аеорсухіјѕԁԛԝкмтвнАЕОРСУХІЈЅКМТВНαοερτυνκιΑΒΕΖΗΙΚΜΝΟΡΤΥΧı",
                           "aeopcyxijsdqwkmtbhaeopcyxijskmtbhaoeptuvkiabezhikmnoptyxi")
# Letters Python's re.IGNORECASE reads as a Latin letter and RE2's (?i) does not: Go's case folding keeps the dotless i
# in an orbit of its own (unicode.SimpleFold(0x131) is 0x131). fold() maps it through _HOMOGLYPH, but the portable form
# cannot fold, so there each class that holds the Latin letter takes it as one more alternative (#1301).
_RE2_UNFOLDED = {"i": "ı"}


def current_pattern() -> re.Pattern:
    alternation = "|".join(sorted((re.escape(t) for t in corpus.terms("current")), key=len, reverse=True))
    return re.compile(r"\b(?:" + alternation + r")s?\b", re.IGNORECASE)


def fold(text: str) -> tuple[str, list[int]]:
    """The text folded one character at a time, and for each folded character the index it came from."""
    out, where = [], []
    for i, ch in enumerate(text):
        if ch in _ZERO_WIDTH:
            continue
        base = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in base if not unicodedata.combining(c)) or ch
        base = base[0].translate(_HOMOGLYPH).lower()
        out.append(base[0] if base else ch)
        where.append(i)
    return "".join(out), where


def _letter(ch: str) -> str:
    alts = re.escape(ch) + "".join(re.escape(c) for c in _LEET.get(ch, ""))
    if ch in _VOWELS:
        alts += r"\*"
    return "[" + alts + "]"


def _run(ch: str, after: str) -> str:
    """One letter of a word, `after` being the letter that follows it ("" at the word's end): one character of its
    class, then any run of the letter and its digit stand-ins that the next letter's class does not hold."""
    own = ch + _LEET.get(ch, "")
    again = "".join(c for c in own if (c == ch or c.isdigit()) and c not in after + _LEET.get(after, ""))
    if not again:
        return _letter(ch)
    if again == own and ch not in _VOWELS:
        return _letter(ch) + "+"
    return _letter(ch) + "[" + re.escape(again) + "]*"


def _word(word: str) -> str:
    return "".join(_run(c, word[i + 1:i + 2]) for i, c in enumerate(word))


def _term(term: str) -> str:
    words = fold(term)[0].split()
    joined = (_SEP + "+").join(_word(w) for w in words)
    if len(words) == 1 and len(words[0]) >= 3:
        spaced = _SEP.join(_letter(c) for c in words[0])
        return f"(?:{joined}|{spaced})"
    return f"(?:{joined})"


def proposed_pattern(terms: list[str] | None = None) -> re.Pattern:
    terms = corpus.terms("proposed") if terms is None else terms
    alts = [_term(t) for t in sorted(terms, key=len, reverse=True)]
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(alts) + r")s?(?![a-z0-9])")


def portable_pattern(terms: list[str] | None = None) -> str:
    """The proposed pattern in the syntax RE2 shares with Python: no lookarounds, so the word edges are groups 1 and 3
    and a replacement keeps them ("$1[redacted]$3"; "$$1[redacted]$$3" in a collector config). An edge is consumed,
    so two terms one separator apart need the replacement applied twice. RE2 is what OTTL's replace_all_patterns
    (the collector) and CEL's matches() (a ValidatingAdmissionPolicy) run; neither can fold the text first, so
    zero-width characters, look-alike letters and accents get past this form.

    The collector reads JSON (#1277): gen_ai.input.messages and its kin are JSON strings, so a newline before a term is
    the two characters `\\n`, and guard-proxy's json.dumps writes every non-ASCII character as `\\uXXXX`. A leading
    edge therefore also takes `\\n`, `\\r`, `\\t` or a `\\uXXXX` escape (a curly quote or an emoji before the term),
    and a non-ASCII letter of a term also matches as its escape. None of these occurs in text that is not
    JSON-encoded, so the form still agrees with the folded floor there.

    RE2's (?i) folds fewer letters than Python's re.IGNORECASE: it leaves the dotless i apart from i, where fold()
    and guard-proxy's match read it as i. Each class holding a letter of _RE2_UNFOLDED therefore also matches that
    letter and its escape (#1301)."""
    terms = corpus.terms("proposed") if terms is None else terms
    alts = "|".join(_term(t) for t in sorted(terms, key=len, reverse=True))
    for ch in sorted({c for c in alts if not c.isascii()}):
        if alts.count(ch) != alts.count(f"[{ch}]"):
            raise ValueError(f"U+{ord(ch):04X} sits in a class with other letters; its JSON escape needs that class split")
        alts = alts.replace(f"[{ch}]", f"(?:{ch}|\\\\u{ord(ch):04x})")
    for latin, other in _RE2_UNFOLDED.items():
        classes = re.compile(r"\[[^\]]*" + re.escape(latin) + r"[^\]]*\]")
        alts = classes.sub(lambda m: f"(?:{m.group(0)}|{other}|\\\\u{ord(other):04x})", alts)
    hexd = "[0-9a-f]" * 4  # not {4}: no brace reaches the collector's Helm-templated config
    return r"(?i)(^|[^a-z0-9]|\\[nrt]|\\u" + hexd + r")((?:" + alts + r")s?)($|[^a-z0-9])"


def portable_mask(text: str, pattern: re.Pattern, with_: str = "[redacted]") -> str:
    for _ in range(2):
        text = pattern.sub(lambda m: m.group(1) + with_ + m.group(3), text)
    return text


class Floor:
    def __init__(self, name: str):
        self.name = name
        self._fold = name == "proposed"
        self.pattern = proposed_pattern() if self._fold else current_pattern()

    def spans(self, text: str) -> list[tuple[int, int]]:
        if not self._fold:
            return [m.span() for m in self.pattern.finditer(text)]
        folded, where = fold(text)
        return [(where[m.start()], where[m.end() - 1] + 1) for m in self.pattern.finditer(folded)]

    def hits(self, text: str) -> list[str]:
        return [text[a:b] for a, b in self.spans(text)]

    def mask(self, text: str, with_: str = "[redacted]") -> str:
        out, last = [], 0
        for a, b in self.spans(text):
            out.append(text[last:a] + with_)
            last = b
        return "".join(out) + text[last:]
