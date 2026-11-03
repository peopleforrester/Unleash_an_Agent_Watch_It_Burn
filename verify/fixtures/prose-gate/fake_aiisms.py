# ABOUTME: A stand-in for hecaton's ai-isms scanner with the same interface, for verify/test_prose_gate.py (#796).
# ABOUTME: Two patterns and the em-dash, inline code stripped, and every file of 50 or more words reads "major".
"""The offline suite runs on hosts without hecaton, so verify/test_prose_gate.py cannot load the real scanner.

This keeps the parts of `hecaton.run.aiisms` that verify/prose_gate.py relies on: `Scan` with `counts` and
`severity`, `EMPTY`, `is_prose`, `exempt` from frontmatter, `scan` over prose with inline code removed, and `added`,
which reports a dash at any severity and a pattern only where the file reads `major` and the label grew.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

EM_LABEL = "em-dash"
PATTERNS = (
    ("vocabulary: hype verbs", re.compile(r"\bunleash(es|ed|ing)?\b", re.IGNORECASE)),
    ("connective: let's", re.compile(r"\blet'?s\s", re.IGNORECASE)),
)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_EXEMPT = re.compile(r"^\s*ai-isms-exempt\s*:\s*true\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Scan:
    words: int
    counts: Counter[str] = field(default_factory=Counter)
    severity: str = "clean"


EMPTY = Scan(words=0)


def is_prose(path: str) -> bool:
    return path.lower().endswith((".md", ".mdx", ".markdown", ".adoc", ".rst", ".txt", ".html", ".htm"))


def exempt(text: str) -> bool:
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    return end >= 0 and bool(_EXEMPT.search(text[3:end]))


def scan(text: str, path: str = "") -> Scan:
    prose = _INLINE_CODE.sub(" ", text)
    words = len(prose.split())
    counts: Counter[str] = Counter({EM_LABEL: prose.count("—")})
    for label, pattern in PATTERNS:
        counts[label] = sum(1 for _ in pattern.finditer(prose))
    return Scan(words, +counts, "major" if words >= 50 else "clean")


def added(before: Scan, after: Scan, grew: Counter[str] | None = None) -> list[str]:
    gained = after.counts - before.counts
    if grew is not None:
        gained = Counter({label: n for label, n in gained.items() if grew[label] > 0})
    problems = [f"{EM_LABEL} (+{gained[EM_LABEL]})"] if gained[EM_LABEL] else []
    patterns = sorted((label, n) for label, n in gained.items() if label != EM_LABEL)
    if patterns and after.severity == "major":
        problems.append("reads major for AI-isms, adding " + ", ".join(f"{label} (+{n})" for label, n in patterns))
    return problems
