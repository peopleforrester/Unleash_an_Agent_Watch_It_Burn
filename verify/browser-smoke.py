#!/usr/bin/env python3
# ABOUTME: Drives a real browser against every live cluster and asserts what a STUDENT actually sees.
# ABOUTME: Exists because two workshop-breaking bugs in one day were invisible to every curl check.
"""Browser smoke test for the student-facing surfaces.

WHY THIS EXISTS, and why curl is not enough.

On 2026-09-03 two bugs reached a live demo and neither was detectable over HTTP:

1. An Origin check on the agent endpoint compared the browser's Origin against the request's Host. Behind
   the apex router Host is the load-balancer name, so a real browser never matched and every chat request
   returned 403 "the kitchen isn't answering right now". Every probe passed because curl sends no Origin
   header, and the check treated a missing Origin as allowed. A guard that only fires for browsers cannot
   be validated without one.

2. The round banner is computed client-side from the hostname. Attendee clusters carry themed names
   (hexhen-zelda), which matched no round pattern and fell through to the round-1 default, so a student on
   a fully-guarded cluster was told "NO GUARDRAILS - you're talking straight to the model. Nothing is
   watching." The DOM was wrong while the HTTP response was perfect.

Both are the same class: the failure lives in what the browser does with the response, not in the
response. So this drives Chrome, sends a real prompt through the page's own fetch, and reads the rendered
DOM.

Usage:
    uv run --with playwright verify/browser-smoke.py                  # all live clusters
    uv run --with playwright verify/browser-smoke.py michael-round1   # named hosts only

Exits non-zero if any cluster fails, so it can gate a demo.
"""
from __future__ import annotations

import asyncio
import re
import sys

# The banner is asserted against the cluster's OWN /guards response, not against its hostname.
#
# This used to derive the expected banner from the hostname, mirroring the page's own logic. That made
# the test worse than useless for the bug it should have caught: the page guessed from the hostname, the
# test guessed the same way, and the two agreed while both were wrong. Student clusters ship with every
# AI guard off so the attacks land, and the page was telling students "ALL GUARDRAILS" (#193).
#
# Reading the cluster's own state here means the test measures the same thing a student can measure, so
# a badge that disagrees with the cluster fails regardless of what either side believes about the
# hostname. The page renders eight badges from /controls ({ai:{...}, infra:{...}}); each badge is lit
# iff its backing field is true. Falco is always-on, so its badge is always lit. This mapping mirrors
# the BADGES array in burritbot.html; kept here independently so a drift in either fails the test.
BADGE_FIELDS = [
    ("infra", "networkpolicy"), ("infra", "kyverno"), ("infra", "kubearmor"),
    ("infra", "falco"),
    ("ai", "budget"), ("ai", "output"), ("ai", "input_blocklist"),
    ("infra", "tool_allowlist"),
]


def expected_lit(controls: dict) -> int:
    ai = controls.get("ai") or {}
    infra = controls.get("infra") or {}
    src = {"ai": ai, "infra": infra}
    return sum(1 for s, k in BADGE_FIELDS if src[s].get(k) is True)


async def check(page, host: str) -> tuple[bool, str]:
    url = f"https://{host}.agenticburn.com/"
    # Cache-bust: a stale page is the single most common false PASS here, and it looks identical to a
    # working one. Verified 2026-09-03, when a fixed cluster kept serving the old banner from cache.
    await page.goto(f"{url}?smoke=1", wait_until="domcontentloaded", timeout=60_000)

    # Ask the cluster what is actually on, through the page's own origin, then hold the DOM to it.
    controls = await page.evaluate(
        """async () => { try { const r = await fetch('/controls', {cache:'no-store'});
                               return r.ok ? await r.json() : null; } catch (e) { return null; } }"""
    )
    if controls is None:
        return False, "/controls did not answer, so the badges cannot be verified"
    want_lit = expected_lit(controls)

    # The badges are filled in by the first poll rather than being present in the markup, so give them a
    # moment. Asserting immediately would race the fetch and read the empty strip.
    try:
        await page.wait_for_function(
            "() => document.querySelectorAll('#badges .bdg').length >= 8",
            timeout=15_000,
        )
    except Exception:
        return False, "badge strip never populated all eight (the /controls poll did not land)"

    lit = await page.evaluate("() => document.querySelectorAll('#badges .bdg.on').length")
    falco_lit = await page.evaluate(
        "() => Array.from(document.querySelectorAll('#badges .bdg.on'))"
        ".some(e => /Falco/.test(e.textContent))")
    if not falco_lit:
        return False, "Falco badge is not lit, but Falco is always engaged"
    if lit != want_lit:
        return False, f"{lit} badge(s) lit but /controls implies {want_lit} should be"

    # Send a prompt through the PAGE's own fetch, so the browser attaches Origin exactly as it does for a
    # student. This is the check the 403 would have failed.
    #
    # Carries PROBE_MARKER so the guard-proxy answers normally but does NOT record it in the side-screen
    # feed. Without it, running this against 13 clusters put the same prompt on every one of them, and the
    # instructor console merged them into what looked like a room firing duplicates.
    res = await page.evaluate(
        """async () => {
             const r = await fetch('/chat', {method:'POST',
                 headers:{'Content-Type':'application/json'},
                 body: JSON.stringify({prompt:'[[wib-probe]] what proteins do you have?'})});
             let j = {}; try { j = await r.json(); } catch (e) {}
             return {status: r.status, reply: j.reply || j.error || ''};
           }"""
    )
    if res["status"] != 200:
        return False, f"chat returned {res['status']}: {res['reply'][:80]}"
    if "kitchen isn't answering" in res["reply"]:
        return False, f"kitchen error surfaced: {res['reply'][:80]}"

    # The reply must contain an ANSWER, not only reasoning. #100 was thinking-shown/answer-missing, and a
    # status check alone cannot tell those apart.
    # Case-insensitive and whitespace-tolerant. Nova varies the tag: <Thinking>, </thinking >, and a
    # leading space inside the tag all occur. A stricter pattern leaves the tag in place, and the leftover
    # markup then counts as the "answer", so the test reports a pass or a nonsense failure depending on
    # which way it lands. It reported 0 visible chars on three healthy clusters before this.
    visible = re.sub(r"<\s*thinking\s*>.*?<\s*/\s*thinking\s*>", "", res["reply"],
                     flags=re.S | re.I).strip()
    if len(visible) < 20:
        return False, f"reply has no visible answer outside <thinking> ({len(visible)} chars)"
    if re.search(r"<\s*/?\s*thinking\s*>", visible, re.I):
        return False, "raw <thinking> tag leaked into the student-visible reply"

    # The composer is the one control a student must always be able to reach.
    send_visible = await page.evaluate(
        """() => { const b = document.getElementById('sendbtn');
                   if (!b) return false;
                   const r = b.getBoundingClientRect();
                   return r.bottom <= window.innerHeight + 1 && r.top >= 0 && r.width > 0; }"""
    )
    if not send_visible:
        return False, "Send button is not visible in the viewport"

    return True, f"{lit} badge(s) lit, chat 200, answer {len(visible)} chars"


async def main(hosts: list[str]) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed. Run:  uv run --with playwright "
              "python -m playwright install chromium", file=sys.stderr)
        return 2

    failures = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        for host in hosts:
            try:
                ok, detail = await check(page, host)
            except Exception as exc:  # a hang or nav failure is a failure, not a skip
                ok, detail = False, f"{type(exc).__name__}: {exc}".replace("\n", " ")[:110]
            print(f"  {'PASS' if ok else 'FAIL'}  {host:<20} {detail}")
            if not ok:
                failures.append(host)
        await browser.close()

    print()
    if failures:
        print(f"BROWSER SMOKE FAILED: {len(failures)}/{len(hosts)} -> {', '.join(failures)}",
              file=sys.stderr)
        return 1
    print(f"BROWSER SMOKE CLEAN: {len(hosts)}/{len(hosts)} clusters")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = [
            "michael-student", "whitney-student",
            "michael-round1", "michael-round2", "michael-round3",
            "whitney-round1", "whitney-round2", "whitney-round3",
        ]
    sys.exit(asyncio.run(main(args)))
