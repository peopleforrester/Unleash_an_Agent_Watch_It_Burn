# ABOUTME: The KubeCon run-of-show's segment 4 names the desk the talk uses on each cluster and warns that no bot host
# ABOUTME: serves /support (#931, #946). Offline: it reads the run-of-show and the presenter page against support_desk_hosts.
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


print("== segment 4 names each cluster's desk ==")
community, community_alt = sd.DESKS["watch-it-burn-community"]
private, _ = sd.DESKS["watch-it-burn-private"]
check(f"segment 4 gives the room the desk at `{community}`", f"support desk at `{community}`" in SEG)
check(f"segment 4 says the bare `{community}` routes to attackme's desk",
      f"The bare `{community}` routes to attackme's desk" in SEG)
check(f"segment 4 names `{community_alt}` as the same desk if the bare name fails",
      f"`{community_alt}` is the same desk if the bare name ever fails" in SEG)
check(f"segment 4 names the private cluster's desk, `{private}`",
      f"The private cluster's desk, the one the admin bot reads, is `{private}`" in SEG)


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
attackme = sd.BOT_HOSTS["watch-it-burn-community"]
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
print("The run-of-show names each cluster's desk and warns that the bot hosts serve no /support.")
