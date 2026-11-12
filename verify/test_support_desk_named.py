# ABOUTME: The KubeCon run-of-show's segment 4 names the one desk and deployments page both clusters use, the presenters'
# ABOUTME: number range, and that no bot host serves /support (#931, #946, #1160). Offline, against support_desk_hosts.
"""Offline half of #946. The live half, verify/test_support_desk_live.py, asks the same hosts for 200.

#931 corrected the support page the talk uses: the desk's own host, not `/support` on a bot host, which answers 404.
It added to segment 4 the private cluster's desk, `support-burritobot-private.burritobot.co`, and the warning that
`https://attackme.burritobot.co/support` answers 404, so the room is given the desk's name. No test read either line
(#946). This fails when segment 4 stops naming a cluster's desk, drops the warning, or when any line of the
run-of-show gives a bot host's `/support` without saying it answers 404.

Since the 2026-11-07 deck (rounds-agenticburn#82, #1098) segment 4 no longer projects the desk's wall: its optional
views during play are the deployments page and the prompt wall, no step says "Joker", and the desk is the one #1077
leaves, where a ticket is filed and looked up by its number and none can be browsed. This fails when the wall or the
word comes back into segment 4, or when either optional view or the number-only desk leaves it.

Since #1145 (Michael, 2026-11-08) both clusters' bots read one desk, `support.burritobot.co`, and deploy to one page,
`deployments.burritobot.co` (#1158), and presenter tickets take HC-900 to HC-999, a range the room is never given
(#1156). #1160 put that in segment 4. This fails when support_desk_hosts.py lists a desk per cluster again, when
segment 4 stops naming the one desk and page for both clusters, names the admin cluster's own desk or deployments
host, drops the presenters' range, or has the admin bot read any number but a presenter one or HC-666: the rule
Michael added, so a ticket the room wrote never runs on the presenters' bot.

Since #1381 (rounds-agenticburn#175, Whitney, 2026-11-12) the `#/46` demo ticket is filed the room's way: through the
desk's form, read back on the room's bot, `https://attackme.burritobot.co`, by the four-digit number the form gives. This
fails when that step files through the presenters' path again (`kubectl port-forward`, `curl`, `/presenter-ticket`) or
asks the admin bot for it. The presenters' range and its route stay, held by verify/test_presenter_ticket_range.py.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import support_desk_hosts as sd  # noqa: E402

TEXT = sd.RUN_OF_SHOW.read_text(encoding="utf-8")
SEG = sd.segment_4(TEXT)
PRESENTER = sd.REPO / "gitops/ai-layer/web/kubecon.html"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


print("== segment 4 names the one desk both clusters use ==")
community, community_alt = sd.DESKS["watch-it-burn-community"]
private, _ = sd.DESKS["watch-it-burn-private"]
check("support_desk_hosts lists the one desk for both clusters (#1145)",
      sd.DESKS["watch-it-burn-community"] == sd.DESKS["watch-it-burn-private"] == sd.DESK, str(sd.DESKS))
check(f"segment 4 gives the room the desk at `{community}`", f"support desk at `{community}`" in SEG)
check(f"segment 4 says the bare `{community}` routes to attackme's desk",
      f"The bare `{community}` routes to attackme's desk" in SEG)
check(f"segment 4 names `{community_alt}` as the same desk if the bare name fails",
      f"`{community_alt}` is the same desk if the bare name ever fails" in SEG)
check(f"segment 4 says the admin bot reads the same desk, `{private}`",
      f"The admin bot reads this same desk, `{private}`, so a ticket filed on it is there for both bots" in SEG)
check(f"segment 4 names the one desk and the one deployments page, `{sd.DEPLOYMENTS}`, for both clusters",
      f"Both clusters' bots read the one support desk, `{community}`, and deploy to the one deployments page, "
      f"`{sd.DEPLOYMENTS}`," in SEG)
check(f"#/48's deploy opens the one deployments page, `https://{sd.DEPLOYMENTS}`",
      f"\"deploy\" opens the same deployments page as on `#/47`, `https://{sd.DEPLOYMENTS}`, the one both bots "
      "deploy to" in SEG)
named_private = [h for h in sd.PRIVATE_DESK_HOSTS if h in SEG]
check("segment 4 names neither of the admin cluster's own desk hosts", not named_private, str(named_private))
check("and that check fails on a segment 4 that sends the presenters to the private desk again",
      bool([h for h in sd.PRIVATE_DESK_HOSTS if h in SEG + f" File it on `https://{sd.PRIVATE_DESK_HOSTS[0]}`."]))

print("== the presenters keep their range, read only it or HC-666 on the admin bot, and file #/46 the room's way ==")
nums = sd.presenter_numbers()
first, last = f"HC-{nums.start}", f"HC-{nums.stop - 1}"
check(f"segment 4 names the presenters' range, {first} to {last}, as ticket_site.py's PRESENTER_NUMBERS",
      f"Ticket numbers {first} to {last} are the presenters' alone" in SEG)
check(f"segment 4 tells the presenters to read only {first} to {last} or {', '.join(sd.ADMIN_FIXED)} on the admin bot",
      f"On the admin bot, read only a presenter number, {first} to {last}, or {sd.ADMIN_FIXED[0]}" in SEG
      and "Never read a four-digit number there: that is a room ticket" in SEG)
STEP47 = "**\"Let's file a ticket.\" (`#/46`).**"
if STEP47 not in SEG:
    sys.exit(f"ANCHOR MISSING: {STEP47!r} is not in segment 4 of {sd.RUN_OF_SHOW}; the demo ticket checks read that step")


def step47(seg: str) -> str:
    """`#/46`'s step in the flattened segment 4, from its bold lead to the next step's."""
    return seg.split(STEP47, 1)[1].split(" - **", 1)[0]


attackme = sd.BOT_HOSTS["watch-it-burn-community"]


def files_the_room_way(step: str) -> bool:
    """The demo ticket is filed through the desk's form and read on the room's bot by the number the form gives."""
    return (f"`https://{community}`" in step and "through the desk's form, the same way the room can" in step
            and "The form gives the ticket a four-digit room number" in step
            and f"switches to the room's BurritoBot, `https://{attackme}`," in step
            and "\"What's the status of my support ticket [number]?\" with the number the form gave" in step)


def presenters_path(step: str) -> list[str]:
    """What in the step files or reads the demo ticket the presenters' way: the port-forward, curl, the route, the
    admin bot or a presenter number."""
    return ([w for w in ("port-forward", "svc/fake-ticket", "curl", "/presenter-ticket", "admin bot") if w in step]
            + sorted({f"HC-{n}" for n in re.findall(r"\bHC-(\d+)\b", step) if int(n) in nums}))


S47 = step47(SEG)
OLD47 = (STEP47 + " The presenter files a short, ordinary complaint (\"My burrito came without salsa\") through the "
         "presenters' path, not the desk's form, from a laptop terminal with kubectl on watch-it-burn-community and the "
         "port-forward started ahead of the segment: kubectl --context watch-it-burn-community -n agent port-forward "
         "svc/fake-ticket 18080:8080 curl -s -X POST localhost:18080/presenter-ticket -H 'Content-Type: "
         "application/json' -d '{\"body\": \"My burrito came without salsa\"}' The desk answers with the ticket and a "
         f"presenter number, the lowest one free: HC-900. From outside, `https://{community}/presenter-ticket` answers "
         "403. The presenter notes the number, then switches to the admin bot and asks \"What's the status of my "
         "support ticket HC-900?\" (the number the desk gave), and BurritoBot reads the ticket back.")
check(f"the demo ticket is filed through the desk's form and read on the room's bot, `https://{attackme}` (#1381)",
      files_the_room_way(S47), S47[:200])
check("and that check fails on the old #/46 step, filed through the presenters' path", not files_the_room_way(OLD47))
check("the #/46 step has no port-forward, curl, /presenter-ticket, admin bot or presenter number (#1381)",
      not presenters_path(S47), str(presenters_path(S47)))
check("and that check fails on the old #/46 step", len(presenters_path(OLD47)) == 6, str(presenters_path(OLD47)))


def admin_reads(seg: str) -> list[str]:
    """Every ticket number segment 4 has the admin bot read that is neither a presenter number nor a fixed one:
    a sentence that names the admin bot and asks about a ticket, `support ticket HC-<n>`, must ask about one of
    those (#1145). Empty when every such ask is allowed."""
    bad = []
    for sentence in re.split(r"(?<=[.!?])\s+", seg):
        if "admin bot" not in sentence:
            continue
        for tid in re.findall(r"support ticket (HC-\d+)", sentence):
            n = int(tid[3:])
            if n not in nums and tid not in sd.ADMIN_FIXED:
                bad.append(tid)
    return bad


check("segment 4 has the admin bot read no room ticket", not admin_reads(SEG), str(admin_reads(SEG)))
check("and that check fails on a segment 4 that has the admin bot read a four-digit room number",
      admin_reads(SEG + " Then switch to the admin bot and ask \"What's the status of my support ticket HC-2038?\"")
      == ["HC-2038"])


def wall_problems(seg: str) -> list[str]:
    """What puts the desk's wall or a Joker back into segment 4 (#1098), as found in the flattened text."""
    return [w for w in ("/wall", "Joker", "joker") if w in seg]


check("segment 4 puts no desk wall on screen and names no Joker (#1098)", not wall_problems(SEG))
check("and that check fails on a segment 4 that projects the wall again",
      bool(wall_problems(SEG + f" Project the wall, `https://{community}/wall`.")))
check("segment 4 lists the deployments page and the prompt wall as optional during play (#1098)",
      "Optional during play: the deployments page, `https://deployments.burritobot.co`," in SEG
      and "and the prompt wall, `https://prompts.burritobot.co`," in SEG)
check("segment 4 writes the desk as #1077 leaves it: filed and looked up by number, never browsed",
      "Anyone can file a ticket and gets its number back, and anyone can look a ticket up by its number." in SEG
      and "Nobody can browse tickets" in SEG)

print("== segment 4 warns that the bot hosts serve no /support ==")
check("segment 4 says neither bot host serves `/support`", "neither bot host serves `/support`" in SEG)
check(f"segment 4 says `https://{attackme}/support` answers 404 (#931)",
      f"`https://{attackme}/support` answers 404 (#931)" in SEG)
check("segment 4 tells the presenters to give the room the desk's name, never a path on the bot's",
      "give the room the desk's name, never a path on the bot's" in SEG)

print("== no line of the run-of-show gives a bot host's /support as a page that answers ==")
flat_all = sd.flat(TEXT)
bot_support = re.compile(r"https://(?:%s)/support\b" % "|".join(
    re.escape(h) for h in [*sd.BOT_HOSTS.values(), "burritobot-private.burritobot.co"]))
hits = [(m.start(), m.group(0)) for m in bot_support.finditer(flat_all)]
unwarned = [url for at, url in hits if "404" not in flat_all[at:at + 80]]
check("every bot-host /support URL in the run-of-show is followed by its 404", not unwarned, f"unwarned: {unwarned}")
check("segment 4 gives at least one such URL, the warning itself", any(url in SEG for _, url in hits), str(hits))

print("== the presenter page names the same desk ==")
page = PRESENTER.read_text(encoding="utf-8")
check(f"gitops/ai-layer/web/kubecon.html names the desk at {community}", f"<code>{community}</code>" in page)
check("gitops/ai-layer/web/kubecon.html links no bot host's /support", not bot_support.search(page))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("The run-of-show names the one desk and page for both clusters, the presenters' range, and that the bot hosts "
      "serve no /support.")
