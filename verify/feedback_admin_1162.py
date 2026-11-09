# ABOUTME: The verdict #1244's tests hold #1162's last criterion to: a comment on #1162 by the repo owner or hecaton
# ABOUTME: confirms a marked #1162 test submission in feedback's /admin under kubecon-na-2026 with source burritobot.
"""What "a test submission shows in feedback's /admin under kubecon-na-2026 with source burritobot" means, as a
verdict on one comment (#1244).

#1162's last criterion: a test submission made through the storefront's Feedback button shows in the feedback app's
`/admin` under the event `kubecon-na-2026` with source `burritobot`. `/admin` answers 403 to this repo's runs, so the
row is read by someone who can sign in to it (Michael, or a feedback-agenticburn run with the admin token), and the
confirmation is a comment on #1162. This follows #1166's pattern (verify/purge_647.py): the record lives on GitHub,
and verify/test_feedback_admin_1162_live.py reads it through verify/gh_comments.py.

`comment_verdict(body)` needs a comment to name all four of:

- `/admin`, the page the row was read on;
- `kubecon-na-2026`, the event the row is filed under;
- source `burritobot` ("Source: burritobot", "source `burritobot`"): the row's source field. The Feedback button's
  own URL, `?source=burritobot`, does not count, since naming the link says nothing of what the row holds;
- a marked #1162 test submission, quoted as its change text: "TEST submission by
  Unleash_an_Agent_Watch_It_Burn#1162 hecaton run <N>, please set aside".

A comment that names all four can still be the ask and not the answer: run 19100's own report on #1162 names
/admin, the event, source burritobot and its marker, and says /admin answers 403 to it. So the verdict also needs:

- the word "confirmed", the writer saying the row was found;
- no word that /admin was not read: "/admin answers 403" (or returns, returned), "could not read", "cannot read",
  "can only be confirmed".

When a comment falls short, the reason names every item it lacks, so the live test's FAIL says what is missing.

The marked submissions made for #1162 are in SUBMISSIONS, so the live test can say which of them a comment confirms.
"""
from __future__ import annotations

import re

ISSUE = "peopleforrester/Unleash_an_Agent_Watch_It_Burn#1162"
# Who may confirm the row: the repo's owner, and the dispatcher that posts each run's report, as which a
# feedback-agenticburn run's report also lands. gh issue view reads them through GraphQL, which names the
# hecatongithub app's bot without REST's "[bot]".
AUTHORS = {"peopleforrester", "hecatongithub"}
EVENT = "kubecon-na-2026"
SOURCE = "burritobot"
# The marked submissions posted to https://feedback.burritobot.co/submit for #1162, by hecaton run, with when
# each reached /thanks (decisions.md, #1162 run 19100 and #1244 run 19507).
SUBMISSIONS = {"19100": "2026-11-09T01:41Z", "19507": "2026-11-09T12:01:45Z"}

ADMIN = re.compile(r"/admin\b")
EVENT_RE = re.compile(r"(?<![\w-])" + re.escape(EVENT) + r"(?![\w-])")
# "Source: burritobot" or "source burritobot", never "?source=burritobot": whitespace must sit before the value.
SOURCE_RE = re.compile(r"(?<![\w?&=])source:?\s+" + re.escape(SOURCE) + r"(?![\w-])", re.I)
CONFIRMED = re.compile(r"\bconfirmed\b", re.I)
NOT_READ = re.compile(r"/admin (?:answers|answered|returns|returned) 403|could not read|cannot read|"
                      r"can only be confirmed", re.I)
MARKER = re.compile(r"TEST submission by Unleash_an_Agent_Watch_It_Burn#1162 hecaton run (\d+), please set aside")


def flat(body: str) -> str:
    """The body with Markdown's backticks and bold marks taken out and every run of whitespace one space, so a quoted
    field reads the same in a code block, in backticks, bolded or wrapped."""
    return re.sub(r"\s+", " ", body.replace("`", "").replace("**", "")).strip()


def runs(body: str) -> list[str]:
    """The hecaton runs whose marked #1162 test submission the comment quotes, in the order it quotes them."""
    return list(dict.fromkeys(MARKER.findall(flat(body))))


def missing(body: str) -> list[str]:
    """Each required item the comment does not name, in a fixed order."""
    text = flat(body)
    out = []
    if not ADMIN.search(text):
        out.append("it does not name /admin, the page the row was read on")
    if not EVENT_RE.search(text):
        out.append(f"it does not name the event {EVENT}")
    if not SOURCE_RE.search(text):
        out.append(f"it does not name the row's source {SOURCE} ('Source: {SOURCE}', since the link's "
                   f"?source={SOURCE} does not count)")
    if not MARKER.search(text):
        out.append("it quotes no marked #1162 test submission ('TEST submission by "
                   "Unleash_an_Agent_Watch_It_Burn#1162 hecaton run N, please set aside')")
    if not CONFIRMED.search(text):
        out.append("it does not say the row was confirmed (the word 'confirmed')")
    not_read = NOT_READ.search(text)
    if not_read:
        out.append(f"it says /admin was not read ({not_read.group(0)!r}), so it is the ask, not the answer")
    return out


def comment_verdict(body: str) -> tuple[bool, str]:
    """(True, what it confirms) when the comment names /admin, kubecon-na-2026, source burritobot and a marked #1162
    test submission, says "confirmed" and says nothing of /admin not being read; else (False, every item it
    lacks)."""
    lacks = missing(body)
    if lacks:
        return False, "; ".join(lacks)
    return True, (f"/admin, event {EVENT}, source {SOURCE}, marked submission of run "
                  + " and run ".join(runs(body)))
