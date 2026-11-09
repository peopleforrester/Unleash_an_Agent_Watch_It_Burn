# ABOUTME: Offline half of #1244: holds verify/feedback_admin_1162.py's comment verdict to a real confirmation and
# ABOUTME: checks it refuses a comment missing /admin, the event, the row's source or a marked #1162 submission.
"""Nothing here reaches GitHub or the feedback app.

#1162's last criterion (#1244): a test submission shows in feedback's /admin under kubecon-na-2026 with source
burritobot, confirmed in a comment on #1162. verify/test_feedback_admin_1162_live.py reads #1162's comments and holds
them to verify/feedback_admin_1162.py's `comment_verdict`. This test holds that verdict:

- The confirmation Michael posted on #1162 on 2026-11-09 (issuecomment-6733846674), copied below, passes, and names
  run 19100. The same record in backticks, bolded or wrapped passes too.
- That comment with each required item cut (/admin, kubecon-na-2026, the row's source burritobot, the marked
  submission, the word "confirmed") fails, and its reason names the cut item and only it. A comment with none of
  them names all five.
- The ask is not the answer: run 19100's report on #1162, which names all four items and says /admin answers 403 to
  it, fails, and its reason says /admin was not read.
- The link's `?source=burritobot` alone is not the row's source, and a marker for another issue, or one without
  "please set aside", is not a marked #1162 submission.
- The live test reads #1162 through gh_comments, holds the comments by AUTHORS to the verdict, and is in run-e2e.sh's
  suite but not the promotion gate's tools tier, since it is red until the confirming comment exists.

Run: python3 verify/test_feedback_admin_1162_record.py
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import feedback_admin_1162 as fa  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def cut(text: str, literal: str, new: str) -> str:
    """text with literal replaced, exiting naming the literal when it is not there, so a reworded fixture reads as
    that and not as a broken check."""
    if literal not in text:
        sys.exit(f"test_feedback_admin_1162_record.py: the fixture no longer holds the literal {literal!r}; "
                 "reword the test's anchor to match")
    return text.replace(literal, new)


# Michael's confirmation on #1162, 2026-11-09T06:32:42Z, as gh issue view returned it.
GOOD = """Confirmed: the storefront test submission reached the feedback app and is filed under the right event and source.

I read the feedback app's admin page (https://feedback.burritobot.co/admin, filtered to the event kubecon-na-2026) and its CSV export, and kept only the one test row. It is response number 10:

- Created 2026-11-09 at 01:41:46 UTC
- Event: kubecon-na-2026
- Source: burritobot
- Usefulness: 3
- Anonymous, with no email
- "One thing you'll change": TEST submission by Unleash_an_Agent_Watch_It_Burn#1162 hecaton run 19100, please set aside

It is the only kubecon-na-2026 response so far, so the talk has no real responses yet. The Feedback button's link, ?source=burritobot, is recorded as it should be.
"""

print("== a real confirmation passes ==")
ok, why = fa.comment_verdict(GOOD)
check("Michael's confirmation on #1162 passes", ok, why)
check("it names run 19100's marked submission", fa.runs(GOOD) == ["19100"], fa.runs(GOOD))
check("the pass reason names the run", "run 19100" in why, why)
styled = cut(cut(GOOD, "- Source: burritobot", "- **Source:** `burritobot`"),
             "TEST submission by Unleash_an_Agent_Watch_It_Burn#1162 hecaton run 19100, please set aside",
             "`TEST submission by\n  Unleash_an_Agent_Watch_It_Burn#1162 hecaton run 19100, please set aside`")
check("the same record bolded, in backticks and wrapped passes", fa.comment_verdict(styled)[0],
      fa.comment_verdict(styled)[1])
both = GOOD + "\nAlso: TEST submission by Unleash_an_Agent_Watch_It_Burn#1162 hecaton run 19507, please set aside\n"
check("a comment quoting two marked submissions names both runs", fa.runs(both) == ["19100", "19507"], fa.runs(both))
check("both runs are in SUBMISSIONS", set(fa.runs(both)) == set(fa.SUBMISSIONS), fa.SUBMISSIONS)

print("== a comment missing an item fails and names it ==")
no_admin = cut(GOOD, "https://feedback.burritobot.co/admin", "https://feedback.burritobot.co/dashboard")
no_event = cut(GOOD, "kubecon-na-2026", "kubecon-eu-2026")
no_source = cut(GOOD, "- Source: burritobot", "- Source: deck")
no_marker = cut(GOOD, "TEST submission by Unleash_an_Agent_Watch_It_Burn#1162 hecaton run 19100, please set aside",
                "a test row")
no_confirmed = cut(GOOD, "Confirmed: the storefront", "Checked: the storefront")
CASES = [
    ("/admin", no_admin, "it does not name /admin"),
    ("kubecon-na-2026", no_event, "it does not name the event kubecon-na-2026"),
    ("source burritobot", no_source, "it does not name the row's source burritobot"),
    ("a marked #1162 test submission", no_marker, "it quotes no marked #1162 test submission"),
    ("the word confirmed", no_confirmed, "it does not say the row was confirmed"),
]
for item, body, says in CASES:
    ok, why = fa.comment_verdict(body)
    check(f"without {item} it fails", not ok, why)
    check(f"without {item} the reason names it", says in why, why)
    check(f"without {item} the reason names nothing else", len(fa.missing(body)) == 1, fa.missing(body))
ok, why = fa.comment_verdict("Confirmed, looks good.")
check("a comment with none of them fails", not ok)
ok, why = fa.comment_verdict("Looks good.")
check("a comment with none of them fails", not ok)
check("its reason names all five", len(fa.missing("Looks good.")) == 5 and why.count(";") == 4, why)

print("== the ask is not the answer ==")
# Run 19100's report on #1162 (issuecomment-6730250756), its two lines that name /admin, as gh issue view returned them.
ASK = """The outcome is partial because the button on attackme and the /admin row can only be confirmed after promotion, and /admin answers 403 here, so a follow-up asks feedback-agenticburn to read it.
| A test submission shows in feedback's /admin under kubecon-na-2026 with source burritobot (feedback-agenticburn checks if this repo cannot read /admin). | no | One marked test (change text 'TEST submission by Unleash_an_Agent_Watch_It_Burn#1162 hecaton run 19100, please set aside', usefulness 3, anonymous, source=burritobot) was posted to https://feedback.burritobot.co/submit at 01:41 UTC. It returned 302 to /thanks, and that page's only outbound link is Sessionize session 1249553 (200). /admin returns 403 here, so a follow-up asks feedback-agenticburn to confirm the row. |
"""
ok, why = fa.comment_verdict(ASK)
check("run 19100's report, the ask, fails", not ok, why)
check("its only lack is that it says /admin was not read",
      len(fa.missing(ASK)) == 1 and "it says /admin was not read" in why, why)
for said in ("/admin answers 403 to this run", "I could not read the live /admin", "the row can only be confirmed later"):
    check(f"a confirmation that also says {said!r} fails", not fa.comment_verdict(GOOD + "\n" + said + "\n")[0])

print("== near misses are not the items ==")
link_only = cut(GOOD, "- Source: burritobot", "- Source field read")
check("the link's ?source=burritobot alone is not the row's source", not fa.comment_verdict(link_only)[0],
      fa.comment_verdict(link_only)[1])
other = cut(GOOD, "Watch_It_Burn#1162 hecaton", "Watch_It_Burn#1163 hecaton")
check("a marker for #1163 is not a marked #1162 submission", not fa.comment_verdict(other)[0])
unmarked = cut(GOOD, "19100, please set aside", "19100")
check("a marker without 'please set aside' is not a marked submission", not fa.comment_verdict(unmarked)[0])
check("an event named inside a longer slug is not the event",
      not fa.comment_verdict(cut(GOOD, "kubecon-na-2026", "kubecon-na-2026-dryrun"))[0])

print("== the live test holds #1162 with the verdict ==")
src = (HERE / "test_feedback_admin_1162_live.py").read_text(encoding="utf-8")
for need in ("gh_comments.read(", "gh_comments.check_read(", "fa.comment_verdict(", "fa.AUTHORS", "fa.ISSUE"):
    check(f"the live test uses {need}", need in src)
head = src.split('"""', 1)[0]
check("it is in run-e2e.sh's suite", "\n# SUITE: e2e" in "\n" + head)
check("it is not in the promotion gate's tools tier, since it is red until the confirming comment exists",
      "# E2E TIER" not in head)
check("the issue is #1162", fa.ISSUE == "peopleforrester/Unleash_an_Agent_Watch_It_Burn#1162", fa.ISSUE)
check("the repo owner and hecaton may confirm", fa.AUTHORS == {"peopleforrester", "hecatongithub"}, fa.AUTHORS)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#1162's /admin verdict holds: a real confirmation passes, a comment missing /admin, the event, the row's "
      "source, a marked #1162 submission or the word confirmed is refused by name, and so is the ask.")
