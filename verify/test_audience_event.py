# ABOUTME: The KubeCon room's two addresses come from one event knob: the storefront's Feedback button
# ABOUTME: opens the session survey, and the projector QR encodes the community cluster's public URL (#451).
"""Pins the event knob (gitops/ai-layer/web/event.js) and what reads it.

The storefront's Feedback button was hardcoded to feedback.agenticburn.com/quick. For the KubeCon breakout
that app stays off (#448), so a room of phones would tap Feedback and land nowhere. The destination is now
set once per event in event.js, never edited into the page, and the projector QR is rendered from the
same file, so the slide and the page cannot disagree about where the room is.

Offline string checks: no network, no browser, no segno. Executing the page's own init code and
re-rendering the QR byte for byte is verify/test_audience_page_e2e.py, in the E2E suite.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "gitops/ai-layer/web"
EVENT = (WEB / "event.js").read_text(encoding="utf-8")
PAGE = (WEB / "burritbot.html").read_text(encoding="utf-8")
KUST = (REPO / "gitops/ai-layer/kustomization.yaml").read_text(encoding="utf-8")
QR = REPO / "facilitation/kubecon-na-2026-audience-qr.svg"
CHECK = REPO / "facilitation/kubecon-na-2026-phone-check.md"
ROS = (REPO / "facilitation/kubecon-na-2026-run-of-show.md").read_text(encoding="utf-8")

SURVEY = "https://kubecon-cloudnativecon-north-america-2026.sessionize.com/session/1249553"
PUBLIC = "https://attackme.agenticburn.com/"

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def field(name: str) -> str | None:
    m = re.search(rf'^\s*{name}:\s*"([^"]*)"', EVENT, re.M)
    return m.group(1) if m else None


print("== the event knob names this event ==")
check("event.js sets window.WIB_EVENT", "window.WIB_EVENT = {" in EVENT)
check("feedbackUrl is the KubeCon session survey (question 147)", field("feedbackUrl") == SURVEY)
check("publicUrl is the community cluster the room attacks", field("publicUrl") == PUBLIC)
# fleet.sh public_host_for() is what actually publishes the community cluster under this name.
check("fleet.sh publishes the community cluster as attackme",
      "watch-it-burn-community\" ]] && { printf 'attackme.agenticburn.com'"
      in (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8"))

print("== the knob ships to the cluster ==")
console_src = KUST[KUST.index("name: console-src"):KUST.index("name: console-conf")]
check("console-src carries web/event.js", re.search(r"^\s*- web/event\.js\b", console_src, re.M) is not None)

print("== the storefront reads it ==")
loader = PAGE.find('<script src="event.js"></script>')
check("burritbot.html loads event.js", loader >= 0)
# A relative src resolves to /event.js from both / and /burritbot, the two paths nginx serves the page at.
check("it loads before the page's own script, so init can see WIB_EVENT",
      0 <= loader < PAGE.find("<script>", loader) and PAGE.find("(function init(){") > loader)
init = PAGE[PAGE.find("(function init(){"):]
check("init reads window.WIB_EVENT", "window.WIB_EVENT||{}" in init)
check("only an https URL from the knob is used", "/^https:\\/\\//.test(ev.feedbackUrl)" in init)
check("an event URL replaces the button's href", "if(fb&&evfb)fb.href=evfb;" in init)
# The survey belongs to a third party. A student's email in its query string is a leak, not a feature.
check("cluster and user are NOT appended to an event URL", "if(fb&&!evfb)fb.href+=" in init)
check("the workshop default is still /quick in the markup",
      re.search(r'id="fbbtn"[^>]*href="https://feedback\.agenticburn\.com/quick\?', PAGE) is not None)
check("the event URL is not hardcoded into the page", SURVEY not in PAGE)
check("the button opens in a new tab, so the chat is still there afterwards",
      re.search(r'id="fbbtn"[^>]*target="_blank"', PAGE) is not None)

print("== the projector QR encodes the knob's public URL ==")
svg = QR.read_text(encoding="utf-8") if QR.exists() else ""
check("the QR SVG is committed", bool(svg))
title = re.search(r"<title>([^<]*)</title>", svg)
check("the QR says which URL it encodes, and it is publicUrl", bool(title) and title.group(1) == field("publicUrl"))
check("black modules on white, for a projector", 'fill="#fff"' in svg and 'stroke="#000"' in svg)
check("the generator reads publicUrl from event.js", "web/event.js" in (REPO / "scripts/audience-qr.py").read_text())

print("== a person has the real-device rows to fill ==")
doc = CHECK.read_text(encoding="utf-8") if CHECK.exists() else ""
check("the phone-check checklist exists", bool(doc))
for dev in ("iPhone", "Android"):
    for net in ("Wi-Fi", "cellular"):
        check(f"a row for {dev} on {net}",
              re.search(rf"^\|[^\n]*{dev}[^\n]*{net}[^\n]*\|", doc, re.M | re.I) is not None)
check("a row for scanning the QR from the back of the room", "back of the room" in doc)
check("a row confirming the survey shows this talk once rating opens", "1249553" in doc and "rating opens" in doc)
check("headless emulation is ruled out in writing", "emulation does not count" in doc)
check("the run-of-show points at the checklist", "kubecon-na-2026-phone-check.md" in ROS)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All audience event checks passed.")
