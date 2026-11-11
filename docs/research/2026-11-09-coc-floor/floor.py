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

The list (#1316). terms-proposed.rot13 was the spike's 144 terms when it measured them (README.md's figures). Since
#1316 it is guard-proxy's default list as guard-proxy-agenticburn#84 grew it, 1,253 terms in guard-proxy's order: the
144, then Urban Dictionary-style slang, its alphanumeric spellings, coded hate and regional slang. One list for every
surface stays the rule (#1289). So proposed_pattern() groups its alternatives by their first character, as guard-proxy
does, and the two RE2 forms the cluster carries are factored on shared leading pieces (portable_pattern() for the
collector, name_pattern() for the admission policy on names), which keeps each inside the limit of where it runs.
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


def _chars(ch: str) -> str:
    """The characters one letter of a term matches: itself, its leetspeak stand-ins, and "*" for a vowel."""
    return ch + _LEET.get(ch, "") + ("*" if ch in _VOWELS else "")


def _letter(ch: str) -> str:
    return "[" + "".join(re.escape(c) for c in _chars(ch)) + "]"


def _run(ch: str, after: str) -> str:
    """One letter of a word, `after` being the letter that follows it ("" at the word's end): one character of its
    class, then any run of the letter and its digit stand-ins that the next letter's class does not hold. A run of
    the whole class is written `[k][k]*`, as guard-proxy writes it since guard-proxy-agenticburn#84, not `[k]+`, so
    every alternative of a term starts with exactly one character of its first letter (proposed_pattern() groups on
    that character)."""
    own = ch + _LEET.get(ch, "")
    again = "".join(c for c in own if (c == ch or c.isdigit()) and c not in after + _LEET.get(after, ""))
    if not again:
        return _letter(ch)
    return _letter(ch) + "[" + re.escape(again) + "]*"


def _word(word: str) -> str:
    return "".join(_run(c, word[i + 1:i + 2]) for i, c in enumerate(word))


def _alternatives(term: str) -> list[tuple[str, ...]]:
    """The term's alternatives, each as its pieces in order: its words' letters run together (each letter a _run,
    a run of separators between words), and a one-word term of three or more letters also spelt out with one
    separator between every letter. Each starts with one character of the term's first letter."""
    words = fold(term)[0].split()
    joined: list[str] = []
    for i, w in enumerate(words):
        if i:
            joined.append(_SEP + "+")
        joined += [_run(c, w[j + 1:j + 2]) for j, c in enumerate(w)]
    out = [tuple(joined)]
    if len(words) == 1 and len(words[0]) >= 3:
        spaced: list[str] = []
        for j, c in enumerate(words[0]):
            if j:
                spaced.append(_SEP)
            spaced.append(_letter(c))
        out.append(tuple(spaced))
    return out


def _term(term: str) -> str:
    return "(?:" + "|".join("".join(a) for a in _alternatives(term)) + ")"


def _ordered(terms: list[str]) -> list[str]:
    """The terms longest first, and only those that fold to a word: one that folds to nothing (zero-width characters
    alone) would be an empty alternative that matches everywhere."""
    return [t for t in sorted(terms, key=len, reverse=True) if fold(t)[0].split()]


def proposed_pattern(terms: list[str] | None = None) -> re.Pattern:
    """The floor on the folded text: each term a whole word with an optional plural s.

    The alternatives are grouped by the character they start with, as guard-proxy builds its pattern since
    guard-proxy-agenticburn#84. One alternation of every term in a row has the engine try each term at every word
    start: with the 1,253 terms a 4,000-character run of "$" cost 0.17 s of CPU here. Grouped, a word start tries
    only the alternatives its first character can begin. Each character goes to one group, the group of every first
    letter whose class holds it ("*" is any vowel's, "1" both i's and l's), and a group keeps its alternatives in the
    order the single alternation tries them, longest term first, so the spans are those of the single alternation."""
    terms = corpus.terms("proposed") if terms is None else terms
    alternatives = []  # (first letter, the alternative after that letter's one character)
    for term in _ordered(terms):
        first = fold(term)[0].split()[0][0]
        alternatives += [(first, "".join(a)[len(_letter(first)):]) for a in _alternatives(term)]
    owners: dict[str, set[str]] = {}
    for first, _ in alternatives:
        for ch in _chars(first):
            owners.setdefault(ch, set()).add(first)
    groups: dict[frozenset, list[str]] = {}
    for ch, firsts in owners.items():
        groups.setdefault(frozenset(firsts), []).append(ch)
    alternation = "|".join(
        "[" + "".join(re.escape(ch) for ch in chars) + "](?:"
        + "|".join(rest for first, rest in alternatives if first in firsts) + ")"
        for firsts, chars in groups.items())
    return re.compile(r"(?<![a-z0-9])(?:" + alternation + r")s?(?![a-z0-9])")


def _factored(sequences: list[tuple[str, ...]]) -> str:
    """One alternation of the sequences with each shared run of leading pieces written once: a trie, emitted as a
    regex. The single alternation of 1,253 terms is 212,409 characters of RE2; this keeps the copies the cluster
    carries inside its limits (CEL's cost budget in the admission policy, the 262,144-byte annotation the collector's
    ConfigMap is applied with). Children keep the order of the sequences that made them, longest term first, and a
    term that ends where a longer one goes on is an optional (greedy) tail, so a leftmost-first engine such as RE2
    prefers the longer term, as the single alternation does."""
    root: dict = {}
    for seq in sequences:
        node = root
        for piece in seq:
            node = node.setdefault(piece, {})
        node[None] = {}

    def emit(node: dict) -> str:
        alts = [piece + emit(child) for piece, child in node.items() if piece is not None]
        if not alts:
            return ""
        body = alts[0] if len(alts) == 1 else "(?:" + "|".join(alts) + ")"
        if None in node:
            body = ("(?:" + body + ")" if len(alts) == 1 else body) + "?"
        return body

    return emit(root)


def _two_kinds(alternatives: list[list[tuple[str, ...]]]) -> str:
    """Each term's alternatives (from _alternatives), factored as two alternations, every spelt-out one first. A
    spelt-out term ("f u c k") is matched before a phrase of short words ("f u"), as the single alternation, longest
    term first, has it; factored together they share their first letter's piece and the phrase would win."""
    spaced = [alts[1] for alts in alternatives if len(alts) > 1]
    joined = [alts[0] for alts in alternatives]
    return "(?:" + _factored(spaced) + "|" + _factored(joined) + ")"


def _compact(regex: str) -> str:
    """The same regex, shorter: a class of one ASCII letter or digit written as the character itself (`[k]` is `k`),
    and a class followed by itself starred written as the class once and a plus (`[o0][o0]*` is `[o0]+`)."""
    regex = re.sub(r"\[([a-z0-9])\]", r"\1", regex)
    return re.sub(r"(\[(?:\\.|[^\]\\])*\]|[a-z0-9])\1\*", r"\1+", regex)


def _json_escape(ch: str) -> str:
    """The character as json.dumps writes it, `\\uXXXX`, in regex syntax: a character past U+FFFF (the finger emoji
    of guard-proxy-agenticburn#84) is written as its UTF-16 surrogate pair, two escapes."""
    units = ch.encode("utf-16-be")
    return "".join(f"\\\\u{int.from_bytes(units[i:i + 2], 'big'):04x}" for i in range(0, len(units), 2))


def portable_pattern(terms: list[str] | None = None) -> str:
    """The proposed pattern in the syntax RE2 shares with Python: no lookarounds, so the word edges are groups 1 and 3
    and a replacement keeps them ("$1[redacted]$3"; "$$1[redacted]$$3" in a collector config). An edge is consumed,
    so two terms one separator apart need the replacement applied twice. RE2 is what OTTL's replace_all_patterns
    (the collector) runs; it cannot fold the text first, so zero-width characters, look-alike letters and accents get
    past this form. The alternatives are factored on their shared leading pieces (_factored), which matches the same
    texts in a fifth of the single alternation's length.

    The collector reads JSON (#1277): gen_ai.input.messages and its kin are JSON strings, so a newline before a term is
    the two characters `\\n`, and guard-proxy's json.dumps writes every non-ASCII character as `\\uXXXX`. A leading
    edge therefore also takes `\\n`, `\\r`, `\\t` or a `\\uXXXX` escape (a curly quote or an emoji before the term),
    and a non-ASCII letter of a term also matches as its escape. None of these occurs in text that is not
    JSON-encoded, so the form still agrees with the folded floor there.

    RE2's (?i) folds fewer letters than Python's re.IGNORECASE: it leaves the dotless i apart from i, where fold()
    and guard-proxy's match read it as i. Each class holding a letter of _RE2_UNFOLDED therefore also matches that
    letter and its escape (#1301)."""
    terms = corpus.terms("proposed") if terms is None else terms
    alts = _two_kinds([_alternatives(t) for t in _ordered(terms)])
    for ch in sorted({c for c in alts if not c.isascii()}):
        if alts.count(ch) != alts.count(f"[{ch}]"):
            raise ValueError(f"U+{ord(ch):04X} sits in a class with other letters; its JSON escape needs that class split")
        alts = alts.replace(f"[{ch}]", f"(?:{ch}|{_json_escape(ch)})")
    for latin, other in _RE2_UNFOLDED.items():
        classes = re.compile(r"\[[^\]]*" + re.escape(latin) + r"[^\]]*\]")
        alts = classes.sub(lambda m: f"(?:{m.group(0)}|{other}|\\\\u{ord(other):04x})", alts)
    hexd = "[0-9a-f]" * 4  # not {4}: no brace reaches the collector's Helm-templated config
    return r"(?i)(^|[^a-z0-9]|\\[nrt]|\\u" + hexd + r")((?:" + _compact(alts) + r")s?)" + _trailing_edge()


def _trailing_edge() -> str:
    """Group 3, what ends a word: the text's end or a character that is not a letter or a digit, less each letter of
    _RE2_UNFOLDED and its JSON escape, which the folded floor reads as a letter (the dotless i is an i). Without that a
    shorter term ending before a dotless i would match where the floor reads on into a longer one ("shitt" before
    "\u0131est"). RE2 has no lookahead, so a backslash ends a word only when what follows it is not that escape."""
    if len(_RE2_UNFOLDED) != 1:
        raise ValueError("the trailing edge spells out one escape it is not; more letters need more of them")
    (other,) = _RE2_UNFOLDED.values()
    esc = f"u{ord(other):04x}"
    not_esc = ["\\\\$", "\\\\[^u]"] + [f"\\\\{esc[:i]}[^{esc[i]}]" for i in range(1, len(esc))]
    return "($|[^a-z0-9" + other + "\\\\]|" + "|".join(not_esc) + ")"


# What an object's name or label can hold: a DNS name or label is letters, digits, ".", "-" and "_" (a label key also
# "/"). Kinds named by any path segment (a Role, a RoleBinding) can hold more, and no identity of the stage may create
# one in `agent` (kubectl auth can-i, 2026-11-11, #1316).
_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-_/=:")
_NAME_SEP = r"[._\-]"
_CLASS = re.compile(r"\[((?:\\.|[^\]\\])*)\](\*?)")


def _for_names(piece: str) -> str | None:
    """A piece of an alternative with every character a name cannot hold taken out of its classes: None when a
    letter then matches nothing, so the alternative cannot occur in a name."""
    if piece.startswith(_SEP):
        return _NAME_SEP + piece[len(_SEP):]
    out, at = [], 0
    for m in _CLASS.finditer(piece):
        if m.start() != at:
            raise ValueError(f"piece {piece!r} is not a run of classes")
        at = m.end()
        kept = "".join(a or b for a, b in re.findall(r"\\(.)|([^\\])", m.group(1)) if (a or b) in _NAME_CHARS)
        if kept:
            out.append("[" + "".join(re.escape(c) for c in kept) + "]" + m.group(2))
        elif not m.group(2):
            return None
    if at != len(piece):
        raise ValueError(f"piece {piece!r} is not a run of classes")
    return "".join(out)


def name_pattern(terms: list[str] | None = None) -> str:
    """portable_pattern() for text made of object names and labels, which the admission policy on names in `agent`
    reads (#1278). Such text holds only letters, digits, ".", "-", "_", "/", "=" and ":", none of the JSON escapes,
    and no other symbol or space, so every class keeps only those characters, a separator is ".", "_" or "-", and
    the leading edge is a plain one. On such text it refuses exactly what portable_pattern() does. CEL charges matches()
    about 0.025 times the text's length times the pattern's, against 1,000,000 a call, so the shorter pattern is a
    longer name and labels the policy can read before the evaluation fails."""
    terms = corpus.terms("proposed") if terms is None else terms
    sequences = []
    for t in _ordered(terms):
        for alt in _alternatives(t):
            pieces = [_for_names(p) for p in alt]
            if None not in pieces:
                sequences.append(tuple(pieces))
    return r"(?i)(^|[^a-z0-9])((?:" + _compact(_factored(sequences)) + r")s?)($|[^a-z0-9])"


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
