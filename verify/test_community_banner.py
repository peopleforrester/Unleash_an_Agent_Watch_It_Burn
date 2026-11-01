# ABOUTME: The private (administrator) BurritoBot announces itself so a presenter switching bots mid-demo
# ABOUTME: knows which one they are on; the public bot and every attendee cluster carry no banner (#761).
"""Pins the private-bot banner (#292, inverted in #761).

The same chat page ships to every cluster. The old community banner told the room "this is the community
bot", which the room did not need: they only ever use the public bot. #761 retires that banner and instead
warns on the PRIVATE bot, because the two presenters switch between the public and private bots during the
demo and nothing told them which one was on screen. So the test cares as much about where the banner must
NOT show (public and attendee) as where it must (the private host).
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
PROXY = (REPO / "gitops/ai-layer/guard-proxy/proxy.py").read_text(encoding="utf-8")
RES = (REPO / "gitops/ai-layer/resources.yaml").read_text(encoding="utf-8")

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== the cluster tells the page who it is ==")
check("guard-proxy is given its public host", "WIB_PUBLIC_HOST" in RES and "cluster-identity" in RES)
check("the env is optional, so a cluster without the ConfigMap still starts",
      re.search(r"key: public-host, optional: true", RES) is not None)
check("/controls reports the host", '"host": os.environ.get("WIB_PUBLIC_HOST"' in PROXY)

print("== the banner exists and starts hidden ==")
check("the element is in the Backend Insights panel", 'id="privatebanner"' in PAGE)
check("it starts hidden, so nothing flashes before identity is known", 'class="combanner" hidden' in PAGE)
check("it has its own style", ".combanner{" in PAGE)
# Red, and specifically NOT the page accent. The banner is the only warning on a page that is
# Accenture purple throughout, so matching the accent made it read as branding (#335).
check("it is red", "background:#C62222" in PAGE)
check("it does not wear the page accent", "background:var(--acn" not in
      PAGE[PAGE.index(".combanner{"):PAGE.index(".combanner{") + 260])

print("== it says exactly one thing ==")
m = re.search(r'id="privatebanner"[^>]*>([^<]*)<', PAGE)
text = (m.group(1) if m else "").strip()
check("the text names the private (administrator) bot",
      text == "This is the private (administrator) BurritoBot.")
# Whitney's standing objection (#292): naming the student bot reveals that attendees will get their own
# cluster later, which they have not been told yet. The private warning must not reintroduce that.
# Comments are stripped first: the markup RECORDS the retired community banner's rationale so nobody
# reinstates it, and a check that cannot tell a comment from rendered text would fail on its own docs.
VISIBLE = re.sub(r"<!--.*?-->", "", PAGE, flags=re.S)
check("it does NOT mention the student BurritoBot", "student BurritoBot" not in VISIBLE)
check("no visible community-bot banner survives", "This is the Community BurritoBot." not in VISIBLE)

print("== it shows only on the private bot, never on public or attendee ==")
check("visibility is driven by the reported host", "privatebanner" in PAGE and "c.host" in PAGE)
check("it matches the private hostname (burritobot-private.)",
      re.search(r"burritobot-private\\?\.", PAGE) is not None)
check("it is hidden whenever the host is anything else", "ban.hidden = !(" in PAGE)
# The driving rule is the private host and nothing else, so the public bot (attackme.) and every attendee
# cluster fall through to hidden. Assert the banner rule does not key on attackme any more.
banner_rule = re.search(r"var ban=document\.getElementById\('privatebanner'\);\s*\n\s*if\(ban\)\{[^}]*\}",
                        PAGE)
check("the banner rule exists", banner_rule is not None)
rule_text = banner_rule.group(0) if banner_rule else ""
check("the public bot (attackme.) triggers no banner", "attackme" not in rule_text)
check("the private host is the trigger", "burritobot-private" in rule_text)
# The page must not decide this for itself: a hardcoded banner would ship to every student cluster.
check("the page hardcodes no cluster name",
      "watch-it-burn-community" not in PAGE and "watch-it-burn-private" not in PAGE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All private-banner checks passed.")
