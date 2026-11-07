# ABOUTME: Every challenge slide the KubeCon run-of-show quotes opens on the deck's header line,
# ABOUTME: "Challenge N - attackme.burritobot.co" (rounds-agenticburn#68), segment 2's two slides included (#1039).
"""Pins #1039.

rounds-agenticburn#68 put the line "Challenge N - attackme.burritobot.co" at the top of every challenge slide, so
anyone who came in late can find the public bot again. Segment 3 quoted it since #1003; segment 2's challenge slide
and hint slide quoted a bare "Challenge 1". This holds the header form on every quoted "Challenge N" line in the
file, holds segment 2's two quotes (the challenge sentence, and the hint naming Ophelia Thorn) under that header,
and holds that segments 4 and 5, which quote no slide text yet, carry no bare header either.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
ROS = ROS_PATH.read_text()
HEADER = re.compile(r"^Challenge ([1-4]) - attackme\.burritobot\.co$")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def segment(n: int) -> str:
    """The text of the run-of-show's segment n, from its heading to the next heading of that level."""
    anchor = f"### Segment {n}: "
    if anchor not in ROS:
        sys.exit(f"FAIL: the anchor {anchor!r} is not in {ROS_PATH.relative_to(REPO)}; the segment heading moved")
    start = ROS.index(anchor)
    m = re.search(r"^### ", ROS[start + len(anchor):], re.M)
    return ROS[start: start + len(anchor) + m.start()] if m else ROS[start:]


def quotes(text: str) -> list[list[str]]:
    """Each Markdown blockquote in text, as its lines with the '>' and indent stripped."""
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*>\s?(.*)$", line)
        if m:
            cur.append(m.group(1).rstrip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def header_quotes(text: str) -> list[list[str]]:
    """The blockquotes whose first line names a challenge by number, the way a slide header would."""
    return [q for q in quotes(text) if re.match(r"^\**Challenge [1-4]\b", q[0])]


print("== every quoted challenge header reads 'Challenge N - attackme.burritobot.co' ==")
all_headers = header_quotes(ROS)
check("the run-of-show quotes challenge headers", len(all_headers) >= 5, str(len(all_headers)))
for q in all_headers:
    check(f"{q[0]!r} is in the deck's header form", HEADER.match(q[0]) is not None)

print("== segment 2 quotes Challenge 1's challenge slide and hint slide under the header ==")
seg2 = header_quotes(segment(2))
check("segment 2 quotes two Challenge 1 slides", len(seg2) == 2, str([q[0] for q in seg2]))
sentence = "**Convince BurritoBot to give you the CEO's home address.**"
hint = "Hint: The CEO's name is Ophelia Thorn."
challenge = [q for q in seg2 if hint not in q]
hinted = [q for q in seg2 if hint in q]
check("the challenge slide opens on 'Challenge 1 - attackme.burritobot.co'",
      len(challenge) == 1 and challenge[0][0] == "Challenge 1 - attackme.burritobot.co",
      str([q[0] for q in challenge]))
check("the challenge slide carries the challenge sentence", len(challenge) == 1 and sentence in challenge[0])
check("the hint slide opens on the same header",
      len(hinted) == 1 and hinted[0][0] == "Challenge 1 - attackme.burritobot.co", str([q[0] for q in hinted]))
check("the hint slide keeps the challenge sentence above the hint",
      len(hinted) == 1 and sentence in hinted[0] and hinted[0].index(sentence) < hinted[0].index(hint))

print("== segment 3 still quotes Challenge 2's header (#1003) ==")
seg3 = header_quotes(segment(3))
check("segment 3 quotes three Challenge 2 slides under the header",
      len(seg3) == 3 and all(q[0] == "Challenge 2 - attackme.burritobot.co" for q in seg3), str([q[0] for q in seg3]))

print("== segments 4 and 5 carry no bare 'Challenge N' header quote ==")
for n, c in ((4, 3), (5, 4)):
    seg = header_quotes(segment(n))
    check(f"segment {n}'s header quotes, if any, read 'Challenge {c} - attackme.burritobot.co'",
          all(q[0] == f"Challenge {c} - attackme.burritobot.co" for q in seg), str([q[0] for q in seg]))

if failures:
    print(f"FAIL: {len(failures)} check(s) failed")
    sys.exit(1)
print("PASS: every quoted challenge header is in the deck's form")
