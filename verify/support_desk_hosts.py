# ABOUTME: The one support desk and deployments page the KubeCon talk sends the room and both bots to (#931, #946, #1160):
# ABOUTME: the hosts segment 4 of the run-of-show names, the bot hosts that serve no /support, and the presenters' range.
"""One list of the desk hosts, for the offline test that reads the run-of-show and the live test that asks them.

#931 found `/support` answering 404 on both bot hosts while #916's criteria expected 200 there. No bot host has ever
served `/support`: the desk lives only on its own host, `support-<cluster>.burritobot.co` (fleet.sh's
WIB_VILLAIN_HOSTS), and the bare `support.burritobot.co` routes to attackme's desk (apex-agenticburn#46).

Since #1145 (Michael, 2026-11-08) both KubeCon clusters' bots read one desk and deploy to one page, the public ones on
watch-it-burn-community: the admin cluster's bot reaches them through `desk-relay` (#1158). So both clusters list the
same desk:

- `support.burritobot.co`, which the room is given, and `support-attackme.burritobot.co`, the same desk if the bare
  name fails, for watch-it-burn-community (attackme) and watch-it-burn-private (burritobot-private) alike.
- `deployments.burritobot.co`, the one deployments page, each row labelled with the cluster it came from (#1157).

The admin cluster's own desk hosts (`PRIVATE_DESK_HOSTS`) still answer, from its own fake-ticket pod, until #1159 moves
the Night Before probe, the trace seeds, the desk reset and standby failover off them; segment 4 names neither.
Presenter tickets take HC-900 to HC-999, a range the room is never given (#1156, `PRESENTER_NUMBERS` in
gitops/ai-layer/ticket_site.py), and the only numbers the presenters read on the admin bot are those and HC-666.

verify/test_support_desk_named.py holds the run-of-show's segment 4 to these names offline;
verify/test_support_desk_live.py asks each host for its page and HC-666 and reads #916's body for the same names.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
RUN_OF_SHOW = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
SEGMENT_4 = "### Segment 4:"

# The one desk both clusters' bots read (#1145, #1158): the host the talk gives the room, then the same desk under
# attackme's own name, for when the bare name fails.
DESK = ("support.burritobot.co", "support-attackme.burritobot.co")
# The one deployments page both clusters' bots deploy to, each row labelled with its cluster (#1157, #1158).
DEPLOYMENTS = "deployments.burritobot.co"
# The cluster, then the desk the talk gives the room for it, then the same desk under another name, or "".
DESKS = {
    "watch-it-burn-community": DESK,
    "watch-it-burn-private": DESK,
}
# The admin cluster's own desk and deployments page, which its bot no longer reads or reports to (#1158). They still
# answer until #1159 moves the probe, the trace seeds, the desk reset and failover off them; segment 4 names neither.
PRIVATE_DESK_HOSTS = ("support-burritobot-private.burritobot.co", "deployments-burritobot-private.burritobot.co")
# Each cluster's bot host, which serves no /support (#931).
BOT_HOSTS = {
    "watch-it-burn-community": "attackme.burritobot.co",
    "watch-it-burn-private": "burritobot-private.agenticburn.com",
}
# The pre-made ticket Challenge 3 reads, on every desk.
TICKET = "/ticket/HC-666"
# The fixed ticket the presenters' attack reads on the admin bot (`#/47`). It is on every desk and no filed ticket can
# take its number, so it is never a room ticket.
ADMIN_FIXED = ("HC-666",)
TICKET_SITE = REPO / "gitops/ai-layer/ticket_site.py"
PRESENTER_LINE = re.compile(r"^PRESENTER_NUMBERS = range\((\d+), (\d+)\)$", re.M)


def desk_hosts() -> list[tuple[str, str]]:
    """Every (clusters, host) the desk answers on, each host once, the talk's own host first. Both clusters share the
    one desk, so `clusters` names every cluster whose bot reads it, joined with " and "."""
    by_host: dict[str, list[str]] = {}
    for cluster, hosts in DESKS.items():
        for host in hosts:
            if host:
                by_host.setdefault(host, []).append(cluster)
    return [(" and ".join(clusters), host) for host, clusters in by_host.items()]


def presenter_numbers(text: str | None = None) -> range:
    """The presenters' reserved ticket numbers, as ticket_site.py's PRESENTER_NUMBERS has them (#1156). Exits naming
    the line when it is not there, so a reworded definition reads as that and not as a wrong range."""
    m = PRESENTER_LINE.search(TICKET_SITE.read_text(encoding="utf-8") if text is None else text)
    if not m:
        sys.exit(f"ANCHOR MISSING: 'PRESENTER_NUMBERS = range(<start>, <stop>)' is not in {TICKET_SITE}; the desk "
                 "checks read the presenters' range from it")
    return range(int(m.group(1)), int(m.group(2)))


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def segment_4(text: str, where: str = str(RUN_OF_SHOW)) -> str:
    """Segment 4's section of the run-of-show, whitespace flattened. Exits naming the heading when it is not there,
    so a renamed heading reads as that and not as a missing desk name."""
    start = text.find(SEGMENT_4)
    if start < 0:
        sys.exit(f"ANCHOR MISSING: {SEGMENT_4!r} is not in {where}; the desk checks read segment 4 under it")
    nxt = text.find("\n### ", start + len(SEGMENT_4))
    return flat(text[start:nxt if nxt >= 0 else len(text)])
