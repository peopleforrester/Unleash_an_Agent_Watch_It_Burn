# ABOUTME: Pins #986's attendee criterion (#1031): whatever an attendee has to do after a failover is listed in the
# ABOUTME: run-of-show's standby section or removed, read against the page's outage text and the drill's judge checks.
"""Holds the criterion of #986 that test review run 18050 found no test checked (#1031).

#986's criterion: anything an attendee would have to do is either removed or listed in the run-of-show's standby
section. Lost saved prompts and the deployments wall going down are acceptable.

The standby section is "### Standbys and automatic promotion (#643)" in facilitation/kubecon-na-2026-run-of-show.md,
to its first sub-heading. The test reads it as literal text and holds:

  1. Listed. The section carries exactly one "- **What an attendee has to do after a promotion.**" bullet, and the
     bullet says "One thing:", names it (resend a message that failed while the cluster was down), says it is
     already in "Your saved prompts", and ends "Nothing else: no refresh, no new link, no new name."
  2. The listed step is the page's own ask. Every outage message gitops/ai-layer/web/burritbot.html shows (each
     line of code naming the kitchen, setting the composer's placeholder or raising the no-burritos screen, read
     with all its string literals) asks for nothing but a wait and a resend, at least one asks for the resend, and
     none asks for a refresh, a reload, a new link or name, a sign-in, or anyone's help. send() saves the message
     to "Your saved prompts" before it calls the backend, so a message that failed is there, and a saved prompt
     refills the composer when tapped.
  3. Removed. Each thing the bullet's "Nothing else" says is not needed is a check of failover_drill.judge, which
     verify/test_kubecon_failover_attendee_live.py runs on both KubeCon clusters and fails on: no refresh is the
     page never reloaded, the composer coming back by itself and the no-burritos screen never showing; no new link
     is attackme's rows moving and the same page chatting again; no new name is the witch name and session staying.
  4. The acceptable losses. The "What the room sees (#986)." bullet's "What is lost, and needs nothing from
     anyone:" list names the deployments wall and asks nothing of an attendee. Lost saved prompts would also be
     acceptable, so the test does not ask that they survive; it asks only that the bullet does not say they are lost
     while the attendee's one step reads them.

Each cut on repo text first checks the literal is there and exits naming the literal and the file when it is not
("Tests own their inputs"). Every check is also run against a copy of the real texts with the thing it reads struck
or flipped, so a check that could never fail shows up here.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
FILES = {
    "ros": "facilitation/kubecon-na-2026-run-of-show.md",
    "html": "gitops/ai-layer/web/burritbot.html",
    "drill": "verify/failover_drill.py",
    "live": "verify/test_kubecon_failover_attendee_live.py",
}
REAL = {k: (REPO / v).read_text(encoding="utf-8") for k, v in FILES.items()}

SECTION_HEAD = "### Standbys and automatic promotion (#643)"
TODO_LABEL = "- **What an attendee has to do after a promotion.**"
SEES_LABEL = "- **What the room sees (#986).**"
LOST_LABEL = "What is lost, and needs nothing from anyone:"
TODO_NEEDS = ("One thing:", "resend a message that failed while the cluster was down",
              'It is already in "Your saved prompts"')
NOTHING_ELSE = "Nothing else: no refresh, no new link, no new name."
# What the bullet says is not needed, and the failover_drill.judge checks that make it so.
REMOVED = {
    "no refresh": ("the page was never reloaded or navigated away", "the composer came back by itself within",
                   "the composer stayed on once it came back", "the no-burritos screen never showed"),
    "no new link": ("of attackme's rows now route to", "after the promotion the same page chats again and"),
    "no new name": ("the witch name in the page header is the same after the switch",
                    "the chat after the switch carried the same witch name and session as the one before",
                    "a refresh afterwards keeps the witch name, the cookie and the session"),
}
LIVE_NEEDS = ("for name, ok, detail in drill.judge(report):",
              'if not ok:\n                failures.append(f"{primary} -> {standby}: {name}")',
              'if failures:\n    print(f"\\nFAILED: {len(failures)} check(s):\\n"'
              ' + "\\n".join(f"  - {f}" for f in failures))\n    sys.exit(1)')
# An outage message may ask for these and only these: a wait, and the resend the bullet lists.
RESEND = "send that again"
# Words that would be an attendee step the bullet does not list.
ASKS = ("refresh", "reload", "re-load", "reopen", "re-open", "new link", "new tab", "new name", "witch name",
        "sign in", "log in", "rescan", "scan the", "qr", "ask a", "ask the", "facilitator", "presenter", "raise",
        "come back later", "copy", "paste", "re-enter", "type it again", "click", "tap", "open ")
# An outage line is a line of code (not a comment) naming the kitchen, setting the composer's placeholder, or raising
# the no-burritos screen; its message is every string literal on it, so one built by concatenation is read whole.
OUTAGE_LINE = re.compile(r"kitchen|\.placeholder\s*=|noBurritos\(true", re.I)
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
SEND_FN = re.compile(r"async function send\(\)\{(.*?)fetch\(CHAT_ENDPOINT", re.S)
SAVED_HEAD = "Your saved prompts"
REUSE = re.compile(r"const reuse=\(\)=>\{const i=document\.getElementById\('inp'\);i\.value=t;.*?\};"
                   r"\s*tx\.onclick=reuse;", re.S)
JUDGE_FN = re.compile(r"^def judge\(.*?(?=^def )", re.M | re.S)

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(text: str, literal: str, where: str) -> None:
    """Exit naming the literal and the file when a cut-anchor is not present, so a reword reads as that."""
    if literal not in text:
        sys.exit(f"test_986_attendee_todo_listed.py: {where} no longer holds the literal {literal!r}; "
                 f"reword the test's anchor to match, do not revert the doc")


def flat(text: str) -> str:
    """`text` with each run of whitespace one space, so a phrase wrapped across lines reads as one line."""
    return " ".join(text.split())


def section(ros: str) -> str:
    """The standby section: its heading to the next level-3 or level-4 heading; empty when absent."""
    m = re.search(r"^" + re.escape(SECTION_HEAD) + r"\n.*?(?=^#{3,4} |\Z)", ros, flags=re.M | re.S)
    return m.group(0) if m else ""


def bullets(sec: str, label: str) -> list[str]:
    """Each top-level bullet of `sec` that starts `label`, flattened, to the next top-level bullet or the end."""
    return [flat(m.group(0)) for m in re.finditer(r"^" + re.escape(label) + r".*?(?=^- |\Z)", sec, flags=re.M | re.S)]


def asks_in(text: str) -> list[str]:
    low = text.lower()
    return [a for a in ASKS if a in low]


def outage_messages(html: str) -> list[str]:
    """Each outage line's string literals joined, one message per outage line of code."""
    out = []
    for line in html.splitlines():
        code = line.strip()
        if code.startswith(("//", "/*", "*", "<!--")) or not OUTAGE_LINE.search(code):
            continue
        out.append(" ".join(a or b for a, b in STRING.findall(code)))
    return out


def verdict(t: dict[str, str]) -> list[str]:
    """What #986's attendee criterion, read against the repo texts in `t`, fails to hold; empty when it holds."""
    bad: list[str] = []
    sec = section(t["ros"])
    if not sec:
        return [f"the run-of-show has no {SECTION_HEAD!r} section"]

    # 1. Listed.
    todo = bullets(sec, TODO_LABEL)
    if len(todo) != 1:
        return [f"the standby section has {len(todo)} {TODO_LABEL!r} bullets; it needs exactly one"]
    todo_text = todo[0]
    bad += [f"the attendee bullet does not say {n!r}" for n in TODO_NEEDS if n not in todo_text]
    if not todo_text.rstrip().endswith(NOTHING_ELSE):
        bad.append(f"the attendee bullet does not end {NOTHING_ELSE!r}")
    said = [s.strip() for s in todo_text.split("Nothing else:", 1)[-1].rstrip(".").split(",")]
    if sorted(said) != sorted(REMOVED):
        bad.append(f"the attendee bullet's 'Nothing else' names {said}, not {sorted(REMOVED)}")
    one_thing = todo_text.split("One thing:", 1)[-1].split("Nothing else:", 1)[0]
    extra = [a for a in asks_in(one_thing) if a not in ("tap",)]
    if extra:
        bad.append(f"the attendee bullet's one thing also asks for {extra}")

    # 2. The listed step is the page's own ask.
    outage = outage_messages(t["html"])
    if not outage:
        bad.append("burritbot.html shows no outage message (no code line naming the kitchen or the placeholder)")
    for s in outage:
        if asks_in(s):
            bad.append(f"burritbot.html's outage message {s!r} asks for {asks_in(s)}, which the attendee bullet "
                       f"does not list")
    resends = [s for s in outage if RESEND in s]
    if not resends:
        bad.append(f"no outage message in burritbot.html asks the attendee to {RESEND!r}, the bullet's one thing")
    elif "resend" not in todo_text:
        bad.append("burritbot.html asks for a resend and the attendee bullet does not list it")
    send = SEND_FN.search(t["html"])
    if not send or not re.search(r"\bsave\(v\)", send.group(1)):
        bad.append("send() no longer saves the message before calling the backend, so a failed one is not in "
                   f"{SAVED_HEAD!r}")
    if f">{SAVED_HEAD}" not in t["html"]:
        bad.append(f"burritbot.html has no {SAVED_HEAD!r} card")
    if not REUSE.search(t["html"]):
        bad.append("a saved prompt no longer refills the composer when tapped")

    # 3. Removed.
    judge = JUDGE_FN.search(t["drill"])
    judge_src = judge.group(0) if judge else ""
    if not judge_src:
        bad.append("failover_drill.py has no judge()")
    for thing, checks in REMOVED.items():
        missing = [c for c in checks if c not in judge_src]
        if missing:
            bad.append(f"the bullet says {thing!r} and failover_drill.judge has no check {missing}")
    bad += [f"test_kubecon_failover_attendee_live.py no longer has {n!r}, so judge's checks fail nothing live"
            for n in LIVE_NEEDS if n not in t["live"]]

    # 4. The acceptable losses.
    sees = bullets(sec, SEES_LABEL)
    if len(sees) != 1:
        bad.append(f"the standby section has {len(sees)} {SEES_LABEL!r} bullets; it needs exactly one")
        return bad
    lost = re.search(re.escape(LOST_LABEL) + r" (.*?\.)(?= [A-Z]|\Z)", sees[0])
    if not lost:
        bad.append(f"the room bullet has no {LOST_LABEL!r} list")
        return bad
    if "the deployments wall" not in lost.group(1):
        bad.append("the 'What is lost' list does not name the deployments wall")
    if asks_in(lost.group(1)):
        bad.append(f"the 'What is lost' list asks the attendee for {asks_in(lost.group(1))}")
    if "saved prompts" in lost.group(1) and "saved prompts" in one_thing:
        bad.append("the 'What is lost' list loses the saved prompts the attendee's one thing reads from")
    return bad


# Anchors the cuts and the mutations below rely on.
anchor(REAL["ros"], SECTION_HEAD, FILES["ros"])
for lit in (TODO_LABEL, SEES_LABEL, LOST_LABEL, NOTHING_ELSE, "It is already in", "Nothing else:"):
    anchor(flat(REAL["ros"]), lit, FILES["ros"])
for lit in ("async function send(){", "fetch(CHAT_ENDPOINT", "save(v);", "Give it a second and send that again.",
            "give it a moment and send that again.", "BurritoBot backend is starting up", f">{SAVED_HEAD}",
            "tx.onclick=reuse;"):
    anchor(REAL["html"], lit, FILES["html"])
anchor(REAL["drill"], "def judge(", FILES["drill"])
for lit in LIVE_NEEDS:
    anchor(REAL["live"], lit, FILES["live"])

print("== #986's attendee criterion, on the repo as it is ==")
real = verdict(REAL)
check("whatever an attendee has to do after a promotion is listed in the standby section or removed", not real,
      "; ".join(real))


def wrapped(literal: str) -> re.Pattern[str]:
    """`literal` as a pattern that also matches it wrapped across lines."""
    return re.compile(r"\s+".join(re.escape(w) for w in literal.split()))


def with_(key: str, old: str, new: str) -> dict[str, str]:
    """A copy of the real texts with the first `old` (wrapped or not) replaced by `new` in one file."""
    t = dict(REAL)
    anchor(flat(t[key]), flat(old), FILES[key])
    t[key] = wrapped(old).sub(lambda _: new, t[key], count=1)
    return t


def refused(name: str, t: dict[str, str]) -> None:
    got = verdict(t)
    check(f"refused: {name}", bool(got), "the verdict found nothing wrong")


MOVED_TODO = (TODO_LABEL + ' One thing: resend a message that failed while the cluster was down. It is already in '
              '"Your saved prompts", so it is one tap. ' + NOTHING_ELSE + "\n\n")

print("\n== each check fails on a copy with what it reads struck or flipped ==")
refused("with the standby section's heading renamed",
        with_("ros", SECTION_HEAD, "### Standbys (#643)"))
refused("with the attendee bullet struck",
        with_("ros", TODO_LABEL, "- **Afterwards.**"))
moved = with_("ros", TODO_LABEL, "- **Afterwards.**")
moved["ros"] = moved["ros"].replace("#### Bring-up and teardown commands\n\n",
                                    "#### Bring-up and teardown commands\n\n" + MOVED_TODO, 1)
refused("with the attendee bullet moved below the section's first sub-heading", moved)
refused("with the attendee bullet doubled",
        with_("ros", "- **After a promotion on stage.**",
              TODO_LABEL + " One thing: tap.\n- **After a promotion on stage.**"))
refused("with the resend step dropped from the bullet",
        with_("ros", "resend a message that failed while the cluster was down",
              "wait for the chat to come back"))
refused("with 'One thing:' struck",
        with_("ros", "One thing:", "Mostly:"))
refused("with the saved-prompts sentence struck",
        with_("ros", 'It is already in "Your saved prompts"', "It is gone"))
refused("with a refresh added to the one thing",
        with_("ros", "so it is one tap.", "so it is one tap, after a refresh."))
refused("with 'Nothing else' struck",
        with_("ros", NOTHING_ELSE, ""))
refused("with 'no new name' dropped from 'Nothing else'",
        with_("ros", NOTHING_ELSE, "Nothing else: no refresh, no new link."))
refused("with a step the drill does not hold added to 'Nothing else'",
        with_("ros", NOTHING_ELSE, "Nothing else: no refresh, no new link, no new name, no new seat."))
refused("with the page's 502 message asking for a refresh",
        with_("html", "Give it a second and send that again.", "Refresh the page and send that again."))
refused("with the page's unreachable message asking for a facilitator",
        with_("html", "give it a moment and send that again.", "ask a facilitator for a new link."))
refused("with the greyed composer's placeholder asking for a reload",
        with_("html", "BurritoBot backend is starting up", "BurritoBot backend is down, reload the page"))
refused("with no outage message asking for the resend",
        dict(REAL, html=REAL["html"].replace("send that again", "wait")))
refused("with no outage message at all",
        dict(REAL, html=OUTAGE_LINE.sub("x", REAL["html"])))
refused("with send() no longer saving the message",
        with_("html", "bubble(v,'me');save(v);", "bubble(v,'me');"))
late = with_("html", "bubble(v,'me');save(v);", "bubble(v,'me');")
late["html"] = late["html"].replace("const data=await res.json();", "const data=await res.json();save(v);", 1)
refused("with the message saved only after the backend answers", late)
refused("with the saved-prompts card renamed",
        dict(REAL, html=REAL["html"].replace(f">{SAVED_HEAD}", ">History")))
refused("with a saved prompt no longer refilling the composer",
        with_("html", "tx.onclick=reuse;", "tx.onclick=null;"))
for thing, checks in REMOVED.items():
    for c in checks:
        refused(f"with failover_drill.judge's check {c!r} ({thing}) renamed",
                with_("drill", c, "something else"))
refused("with failover_drill.py's judge() gone",
        with_("drill", "def judge(", "def judged("))
for n in LIVE_NEEDS:
    refused(f"with the live test's {n!r} struck", with_("live", n, "pass"))
refused("with the room bullet struck",
        with_("ros", SEES_LABEL, "- **The room.**"))
refused("with the 'What is lost' list struck",
        with_("ros", LOST_LABEL, "Kept:"))
refused("with the deployments wall dropped from the 'What is lost' list",
        with_("ros", "the deployments wall,", ""))
refused("with an attendee step hidden in the 'What is lost' list",
        with_("ros", "the deployments wall,", "the deployments wall (refresh it),"))
refused("with the saved prompts lost while the one thing reads from them",
        with_("ros", "the deployments wall,", "the saved prompts, the deployments wall,"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n in failures:
        print(f"  - {n}")
    sys.exit(1)
print("#986's attendee criterion holds: the one step an attendee has after a promotion is listed in the standby "
      "section, and the rest is removed and held by the drill's judge.")
