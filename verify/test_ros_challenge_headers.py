#!/usr/bin/env python3
# ABOUTME: The KubeCon run-of-show quotes each challenge slide's header line as the deck has it since rounds-agenticburn#68.
# ABOUTME: Segment 2's challenge and hint slides open on "Challenge 1 - attackme.burritobot.co" (#1039), segment 3's on Challenge 2's.
"""rounds-agenticburn#68 (2026-11-06) changed the header line on every challenge slide to
'Challenge N - attackme.burritobot.co', so anyone who lost the chat page can find the public bot again.
Segment 3 quoted it from #1003; segment 2's challenge slide and hint slide still quoted a bare 'Challenge 1'
until #1039. Segments 4 and 5 quote no slide header yet; once they do, a bare one fails here too.
facilitation/runbook.md is the 2-hour format and is not read here."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROS = ROOT / "facilitation" / "kubecon-na-2026-run-of-show.md"
FAILS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


TEXT = ROS.read_text()


def segment(n: int) -> str:
    head = f"### Segment {n}:"
    start = TEXT.find(head)
    if start < 0:
        sys.exit(f"FAIL: the anchor {head!r} is not in {ROS.relative_to(ROOT)}")
    end = TEXT.find("\n### Segment ", start + len(head))
    return TEXT[start:end if end > 0 else len(TEXT)]


HEADER = re.compile(r"^\s*> Challenge (\d)\b(.*)$", re.M)

print("== segment 2 quotes Challenge 1's header as the deck has it (#1039) ==")
S2 = segment(2)
heads2 = HEADER.findall(S2)
check("segment 2 quotes two Challenge 1 slide headers, the challenge slide and the hint slide",
      len(heads2) == 2 and all(n == "1" for n, _ in heads2), str(heads2))
check("both read 'Challenge 1 - attackme.burritobot.co'",
      all(rest == " - attackme.burritobot.co" for _, rest in heads2), str(heads2))
check("the hint slide is one of them: the Ophelia Thorn hint follows a quoted header",
      "> Challenge 1 - attackme.burritobot.co\n  >\n  > **Convince BurritoBot to give you the CEO's home address.**\n"
      "  >\n  > Hint: The CEO's name is Ophelia Thorn." in S2)

print("== segment 3 still quotes Challenge 2's header (#1003) ==")
heads3 = HEADER.findall(segment(3))
check("segment 3 quotes Challenge 2's header", len(heads3) >= 1 and all(n == "2" for n, _ in heads3), str(heads3))
check("every one reads 'Challenge 2 - attackme.burritobot.co'",
      all(rest == " - attackme.burritobot.co" for _, rest in heads3), str(heads3))

print("== no quoted challenge header anywhere in the run-of-show is the bare form ==")
bare = [m.group(0).strip() for m in HEADER.finditer(TEXT) if m.group(2) != " - attackme.burritobot.co"]
check("every quoted 'Challenge N' slide header carries ' - attackme.burritobot.co'", not bare, str(bare))
# The pattern itself: a bare header is caught, the deck's form is not.
check("the check catches a bare header",
      [m.group(2) for m in HEADER.finditer("  > Challenge 4\n")] == [""])
check("and passes the deck's form",
      [m.group(2) for m in HEADER.finditer("  > Challenge 4 - attackme.burritobot.co\n")]
      == [" - attackme.burritobot.co"])

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    sys.exit(1)
print("\nALL GREEN")
