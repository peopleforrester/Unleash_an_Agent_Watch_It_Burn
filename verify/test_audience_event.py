# ABOUTME: The KubeCon room's two addresses come from one event knob: the storefront's Feedback button
# ABOUTME: opens the talk's own feedback form, and the projector QR encodes the community cluster's public URL (#451).
"""Pins the event knob (gitops/ai-layer/web/event.js) and what reads it.

The storefront's Feedback button was hardcoded to feedback.agenticburn.com/quick. For the KubeCon breakout
that app stays off (#448), so a room of phones would tap Feedback and land nowhere. The destination is now
set once per event in event.js, never edited into the page: since #1162 (Michael, 2026-11-08) the talk's own
short form on feedback.burritobot.co, whose thanks page links on to the Sessionize rating, and the projector QR is rendered from the
same file, so the slide and the page cannot disagree about where the room is. The same knob hides the
storefront's Datadog button on the public bot, because the room gets no link to any Datadog view (#647).

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

FORM = "https://feedback.burritobot.co/?source=burritobot"  # the talk form (#1162); its thanks page rates on Sessionize
PUBLIC = "https://attackme.burritobot.co/"  # the displayed domain (#651 step B)

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
check("feedbackUrl is the talk's own form, tagged source=burritobot (#1162)", field("feedbackUrl") == FORM)
check("publicUrl is the community cluster the room attacks", field("publicUrl") == PUBLIC)
# fleet.sh public_host_for() is what actually publishes the community cluster under this name.
check("fleet.sh routes a burritobot.co twin of every roster row, so publicUrl's host is served",
      'readonly WIB_TWIN_DOMAIN="burritobot.co"' in (REPO / "infra/terraform/fleet/fleet.sh").read_text())
check("fleet.sh publishes the community cluster as attackme",
      "watch-it-burn-community\" ]] && { printf 'attackme.agenticburn.com'"
      in (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8"))



def comments_of(js: str) -> str:
    """Every // comment in js, joined with spaces, so a phrase wrapped across two comment lines reads whole."""
    return " ".join(m.group(1).strip() for m in re.finditer(r"^\s*//\s?(.*)$", js, re.M))


print("== event.js's comments say what feedbackUrl is, and do not call it a third party (#1162, #1240) ==")
COMMENTS = comments_of(EVENT)
# The comment block right above the feedbackUrl line: the field's own description.
_fb_line = EVENT.find("  feedbackUrl:")
_fb_block = EVENT[:_fb_line].rsplit("\n", 1)[0] if _fb_line >= 0 else ""
_fb_lines: list[str] = []
for _line in reversed(_fb_block.splitlines()):
    if not _line.strip().startswith("//"):
        break
    _fb_lines.insert(0, _line.strip()[2:].strip())
FB_COMMENT = " ".join(_fb_lines)
_THIRD = re.compile(r"third[\s-]*part(?:y|ies)", re.I)
check("the third-party pattern finds 'third party', 'third-party' and a phrase wrapped across comment lines",
      all(_THIRD.search(s) for s in ("a third party form", "a Third-Party form",
                                     comments_of("  // goes to a third\n  // party form\n")))
      and not _THIRD.search("our feedback app"))
check("event.js has comments to read", bool(COMMENTS))
check("no comment in event.js calls the feedback destination a third party", not _THIRD.search(COMMENTS))
check("the button goes to feedbackUrl VERBATIM, with no cluster or user appended, says the comment",
      "When feedbackUrl is set, the button goes there VERBATIM. No cluster or user is appended" in COMMENTS)
check("the comment says why: a talk's room has none, and the form tells sources apart by its own ?source=",
      "a talk's room has no cluster or user of its own, the event's form is told apart by its own ?source=" in COMMENTS)
check("feedbackUrl has its own comment above it", bool(FB_COMMENT))
check("feedbackUrl's comment names the destination as our own feedback app (#1162)",
      "The talk's own short form on our feedback app" in FB_COMMENT and "source=burritobot" in FB_COMMENT)

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
# A talk's room has no cluster or user, and the form tells the storefront apart by its own source=. An
# attendee's email in a query string is a leak, not a feature.
check("cluster and user are NOT appended to an event URL", "if(fb&&!evfb)fb.href+=" in init)
check("the workshop default is still /quick in the markup",
      re.search(r'id="fbbtn"[^>]*href="https://feedback\.burritobot\.co/quick\?', PAGE) is not None)
check("the event URL is not hardcoded into the page", FORM not in PAGE)
check("the button opens in a new tab, so the chat is still there afterwards",
      re.search(r'id="fbbtn"[^>]*target="_blank"', PAGE) is not None)

print("== the room gets no link to Datadog (#647, Whitney 2026-11-01) ==")
# The room sees Datadog only on the big screen: no QR, link or share URL to any Datadog view. The storefront's
# Datadog button is the one such link on the page the room opens, so the event hides it on the public hosts.
check("event.js sets hideDatadogOnPublic: true",
      re.search(r"^\s*hideDatadogOnPublic:\s*true,?\s*$", EVENT, re.M) is not None)
check("the storefront still has its Datadog button for the private bot and attendee clusters",
      re.search(r'<a class="hb" id="ddbtn" href="https://app\.datadoghq\.com"', PAGE) is not None)
check("a hidden header button is not displayed", "header a.hb[hidden]{display:none}" in PAGE)
check("init hides the Datadog button only when the event asks and the host is public",
      "if(ddb && ev.hideDatadogOnPublic===true && onPublic) ddb.hidden=true;" in init)
check("the public test is the same publicHosts list the Terminal hide uses",
      "var onPublic=pubHosts.indexOf(location.hostname)>=0;" in init
      and "if(vtb && ev.hideTerminalOnPublic===true && onPublic) vtb.hidden=true;" in init)
# A share link's host is p.datadoghq.com itself; the presenters' traces page, app.datadoghq.com, which the deck's
# "Ophelia Thorn" link opens (#984), ends in the same letters and is not one, so the host must start at "p.".
_SHARE = re.compile(r"(?<![\w.-])p\.datadoghq\.com|/s/[A-Za-z0-9-]{6,}|room-view-qr|datadog-room/share\.json")
check("the share-link pattern finds a p.datadoghq.com share link and passes app.datadoghq.com",
      bool(_SHARE.search("https://p.datadoghq.com/sb/abc-123")) and bool(_SHARE.search("p.datadoghq.com"))
      and not _SHARE.search("https://app.datadoghq.com/llm/traces?query=ml_app%3Aburritobot"))
check("no Datadog share link or room-view QR is back in the run-of-show (#767)", not _SHARE.search(ROS))

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
check("Feedback opens is checked against the form, not Sessionize (#1162)",
      "**Feedback opens:** tap Feedback. A new tab opens on our form at\n  `feedback.burritobot.co/?source=burritobot`" in doc)
submit = doc[doc.find("## Submit the form, then the Sessionize link"):]
check("each phone submits once and follows the thanks page's Sessionize link to 1249553 (#1162)",
      doc.find("## Submit the form, then the Sessionize link") >= 0
      and "its Sessionize link opens session 1249553" in submit
      and all(re.search(rf"^\| {dev}, [^|]+\|", submit, re.M) for dev in ("iPhone", "Android"))
      and "under `kubecon-na-2026` with source `burritobot`" in submit)
check("the run-of-show's segment 6 asks for feedback at the deck's closing QR (#1162)",
      "feedback.burritobot.co/?source=deck" in ROS[ROS.find("### Segment 6:"):ROS.find("## Abstract points to segments")])
check("headless emulation is ruled out in writing", "emulation does not count" in doc)
check("the checklist names publicUrl as the address the room opens and the QR encodes",
      f"**{PUBLIC}**" in doc and f"`publicUrl`, `{PUBLIC}`" in doc and f"Opens {PUBLIC} |" in doc)
check("the real-phone sign-off is recorded with its source (Michael, 2026-11-01)",
      "Signed off by Michael on 2026-11-01" in doc and "issuecomment-6551797906" in doc)
check("the run-of-show points at the checklist", "kubecon-na-2026-phone-check.md" in ROS)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All audience event checks passed.")
