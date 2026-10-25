# ABOUTME: The retired round vocabulary as regexes, shared by the docs test and the code test so the two
# ABOUTME: hold the same shapes: the numbered names, the shorthand, and the date that makes a line history.
"""The shapes the round model left behind (#290, #291, #498, #560).

`test_docs_current.py` holds the current-description markdown to `ROUND_SHAPES`. `test_round_names_retired.py`
holds the fleet scripts and the gitops Applications to `CODE_SHAPES`, which is the same vocabulary less the
cluster and host names. A comment in code records where something was measured or what a hostname used to
be, often on the line after its date, so the name of a retired cluster (`watch-it-burn-r2-1`,
`michael-round2`) is history there. What must not survive is wording that describes a cluster as a round.
"""
from __future__ import annotations

import re

# The bare R1/R2/R3 is matched in capitals only, so a CSS variable like `--r3` or a cluster suffix stays out.
NUMBERED = r"\b(?:Rounds?\s*[123]\b|round-[123]\b|watch-it-burn-r[0-9]|round[123]\.agenticburn)"
SHORTHAND = (r"(?-i:\bR[123]\b)|\br[123](?:/r[123])+\b|\bthree[- ]rounds?\b|\bper-round\b|\bcross-round\b"
             r"|\bround (?:table|toggles?|state)\b|\bround-toggle\b")
ROUND_SHAPES = re.compile(f"{NUMBERED}|{SHORTHAND}", re.I)
NUMBERED_SHAPES = re.compile(NUMBERED, re.I)

# A round spelled out as words ("Round 2", "round-2/3", "rounds 2 and 3") but not a name joined to its
# number ("michael-round2"), plus the shorthand.
SPELLED = r"\bRounds?[\s-]+[123]\b"
CODE_SHAPES = re.compile(f"{SPELLED}|{SHORTHAND}", re.I)

# A dated measurement or verification is a historical fact, so a line that carries a date may name it.
DATED = re.compile(r"\b20[0-9]{2}-[01][0-9]-[0-3][0-9]\b")
