# ABOUTME: The support desk the KubeCon talk sends the room to, per cluster (#931, #946): the hosts the run-of-show
# ABOUTME: and #916 name, the bot hosts that serve no /support, and segment 4 of the run-of-show they are read from.
"""One list of the desk hosts, for the offline test that reads the run-of-show and the live test that asks them.

#931 found `/support` answering 404 on both bot hosts while #916's criteria expected 200 there. No bot host has ever
served `/support`: the desk lives only on its own host, `support-<cluster>.burritobot.co` (fleet.sh's
WIB_VILLAIN_HOSTS), and the bare `support.burritobot.co` routes to attackme's desk (apex-agenticburn#46). So the talk
names the desk's host, and these are the hosts:

- watch-it-burn-community, the public cluster (attackme): the bare `support.burritobot.co`, which the room is given,
  and `support-attackme.burritobot.co`, the same desk if the bare name fails.
- watch-it-burn-private, the admin cluster (burritobot-private): `support-burritobot-private.burritobot.co`, the
  desk its bot reads in the fix.

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

# The cluster, then the desk the talk gives the room for it, then the same desk under the cluster's own name, or ""
# when the desk's host is already that name.
DESKS = {
    "watch-it-burn-community": ("support.burritobot.co", "support-attackme.burritobot.co"),
    "watch-it-burn-private": ("support-burritobot-private.burritobot.co", ""),
}
# Each cluster's bot host, which serves no /support (#931).
BOT_HOSTS = {
    "watch-it-burn-community": "attackme.burritobot.co",
    "watch-it-burn-private": "burritobot-private.agenticburn.com",
}
# The pre-made ticket Challenge 3 reads, on every desk.
TICKET = "/ticket/HC-666"


def desk_hosts() -> list[tuple[str, str]]:
    """Every (cluster, host) the desk answers on, the talk's own host first for each cluster."""
    return [(c, h) for c, hosts in DESKS.items() for h in hosts if h]


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
