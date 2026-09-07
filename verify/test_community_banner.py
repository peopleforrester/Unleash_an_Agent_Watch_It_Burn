# ABOUTME: The community BurritoBot announces itself; a student's own cluster must not. The banner is
# ABOUTME: driven by the cluster identity guard-proxy reports, never by anything baked into the page.
"""Pins the community banner (#292).

The same chat page ships to every cluster. A banner that appeared on all of them would be worse than no
banner: fifty students would be told they are sharing a bot they are not sharing. So the test cares as
much about when it must NOT show as when it must.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
PROXY = (REPO / "gitops/ai-layer/proxy.py").read_text(encoding="utf-8")
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
check("the element is in the workshop panel", 'id="communitybanner"' in PAGE)
check("it starts hidden, so nothing flashes before identity is known", 'class="combanner" hidden' in PAGE)
check("it has its own style", ".combanner{" in PAGE)
# Red, and specifically NOT the page accent. The banner is the only warning on a page that is
# Accenture purple throughout, so matching the accent made it read as branding (#335).
check("it is red", "background:#C62222" in PAGE)
check("it does not wear the page accent", "background:var(--acn" not in
      PAGE[PAGE.index(".combanner{"):PAGE.index(".combanner{") + 260])

print("== it says exactly one thing ==")
m = re.search(r'id="communitybanner"[^>]*>([^<]*)<', PAGE)
text = (m.group(1) if m else "").strip()
check("the text names the community bot", text == "This is the Community BurritoBot.")
# Whitney's objection: naming the student bot reveals that they will get their own cluster, which they
# have not been told yet. The one-sentence form is deliberate, not an abbreviation.
# Comments are stripped first: the markup deliberately RECORDS the rejected draft so nobody reinstates
# it, and a check that cannot tell a comment from rendered text would fail on its own documentation.
VISIBLE = re.sub(r"<!--.*?-->", "", PAGE, flags=re.S)
check("it does NOT mention the student BurritoBot", "student BurritoBot" not in VISIBLE)

print("== it shows only on the community cluster ==")
check("visibility is driven by the reported host", "communitybanner" in PAGE and "c.host" in PAGE)
check("it matches the attackme hostname", re.search(r"attackme\\?\.", PAGE) is not None)
check("it is hidden whenever the host is anything else",
      "ban.hidden = !(" in PAGE)
# The page must not decide this for itself: a hardcoded banner would ship to every student cluster.
check("the page hardcodes no cluster name", "watch-it-burn-community" not in PAGE)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All community-banner checks passed.")
