#!/usr/bin/env python3
# ABOUTME: Opens the student lab page in a real browser and asserts it actually rendered: every step,
# ABOUTME: every caret with a body, the observability links, and no markup leaking into visible text.
"""Render check for the student lab page.

Tag-balance checks in a shell pipeline are not the same thing as a page that renders. The lab is one
large hand-edited HTML file whose challenges are built from nested <details> blocks, and the failure
mode of a bad edit there is a caret that opens onto nothing, or a mangled tag that shows its own
markup to the student. Both serve HTTP 200 and both look fine to curl.

Run after any structural edit to lab.html, and after rolling it to the fleet:

    uv run --with playwright verify/lab-render.py                 # whitney-student
    uv run --with playwright verify/lab-render.py michael-student

Exits non-zero if the page did not render as expected.
"""
import asyncio, re, sys
from playwright.async_api import async_playwright

HOST = sys.argv[1] if len(sys.argv) > 1 else "whitney-student"


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1440, "height": 900})
        await pg.goto(f"https://{HOST}.agenticburn.com/lab?cb=2",
                      wait_until="domcontentloaded", timeout=60000)

        steps = await pg.evaluate(
            "() => Array.from(document.querySelectorAll('.guide .step .h .t'))"
            ".map(e => e.textContent.trim())")
        print(f"  steps rendered: {len(steps)}")
        for s in steps:
            print("   ", s[:62])

        res = await pg.evaluate("""() => {
            const d = Array.from(document.querySelectorAll('details'));
            d.forEach(x => { x.open = true; });
            return {total: d.length,
                    empty: d.filter(x => (x.textContent || '').trim().length < 40).length};
        }""")
        print(f"  carets: {res['total']} total, {res['empty']} with no body")

        dd = await pg.evaluate(
            "() => document.querySelectorAll('a[href*=\"traces\"]').length")
        print(f"  Agent Observability links: {dd}")

        # Raw markup showing as visible text means a tag was mangled. Checked in Python so no
        # regex has to survive two layers of shell and JS quoting.
        text = await pg.evaluate("() => document.body.innerText")
        leaked = len(re.findall(r"</?(?:p|div|details|summary|b)\b", text))
        print(f"  raw markup leaked into visible text: {leaked}")

        await b.close()

    # 11 steps (tour + 8 challenges + reset + feedback) and one Agent Observability link per challenge.
    ok = len(steps) == 11 and res["empty"] == 0 and dd == 8 and leaked == 0
    print("  LAB RENDER OK" if ok else "  LAB RENDER PROBLEM")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
