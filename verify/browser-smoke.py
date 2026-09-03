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

# Round expectations keyed on the hostname shape, mirroring applyRoundFromCluster in burritbot.html.
# Kept here rather than imported so the test states the intent independently of the code under test: if
# both drift together, an assertion that reads the implementation would still pass.
ROUND_RE = re.compile(r"(?:^|[-.])r(?:ound)?([123])(?:[-.]|$)", re.I)
EXPECTED_BANNER = {"r1": "NO GUARDRAILS", "r2": "SOME GUARDRAILS", "r3": "ALL GUARDRAILS"}


def expected_round(host: str) -> str:
    """Round clusters are the named minority; everything else is a student cluster (r3)."""
    label = host.split(".")[0]
    m = ROUND_RE.search(label)
    return f"r{m.group(1)}" if m else "r3"


async def check(page, host: str) -> tuple[bool, str]:
    url = f"https://{host}.agenticburn.com/"
    # Cache-bust: a stale page is the single most common false PASS here, and it looks identical to a
    # working one. Verified 2026-09-03, when a fixed cluster kept serving the old banner from cache.
    await page.goto(f"{url}?smoke=1", wait_until="domcontentloaded", timeout=60_000)

    banner = await page.evaluate(
        "() => document.getElementById('bannertext')?.textContent?.trim() || ''"
    )
    want = EXPECTED_BANNER[expected_round(host)]
    if banner != want:
        return False, f"banner is {banner!r}, expected {want!r} for {expected_round(host)}"

    # Send a prompt through the PAGE's own fetch, so the browser attaches Origin exactly as it does for a
    # student. This is the check the 403 would have failed.
    res = await page.evaluate(
        """async () => {
             const r = await fetch('/chat', {method:'POST',
                 headers:{'Content-Type':'application/json'},
                 body: JSON.stringify({prompt:'what proteins do you have?'})});
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
    visible = re.sub(r"<thinking>.*?</thinking>", "", res["reply"], flags=re.S).strip()
    if len(visible) < 20:
        return False, f"reply has no visible answer outside <thinking> ({len(visible)} chars)"
    if "<thinking>" in visible:
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

    return True, f"{banner}, chat 200, answer {len(visible)} chars"


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
