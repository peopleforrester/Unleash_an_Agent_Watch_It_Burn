# ABOUTME: Renders /kubecon?sheet=1 in headless Chrome and holds the iPad prompt sheet to the page it is built from:
# ABOUTME: every /kubecon prompt, word for word, in order, under its segment's title, and nothing else shown (#689).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The sheet is built in the page by its own script from the .prompt blocks, so this runs that script for real:
Chromium, through the playwright pinned in verify/playwright_browsers.py, loads the committed kubecon.html from disk
with ?sheet=1, and again without it, and hands back each DOM.

Needs uv, and network on the first run (playwright_browsers.ensure() installs a missing browser). A missing tool is
a failure, not a skip. Nothing else touches the network, and nothing touches a cluster.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
from playwright_browsers import UV, ensure  # noqa: E402

PAGE = REPO / "gitops/ai-layer/web/kubecon.html"
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


if shutil.which("uv") is None:
    print("FAILED: uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)
not_ready = ensure()
if not_ready:
    print("FAILED: " + "; ".join(not_ready))
    sys.exit(1)

# Runs inside the uv environment: prints the rendered DOM of each URL it is given, as a JSON list.
RENDER = r"""
import json, sys
from playwright.sync_api import sync_playwright
out = []
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    for url in sys.argv[1:]:
        page.goto(url)
        out.append(page.content())
    b.close()
print(json.dumps(out))
"""
run = subprocess.run([*UV, "python", "-I", "-c", RENDER, f"{PAGE.as_uri()}?sheet=1", PAGE.as_uri()],
                     capture_output=True, text=True, timeout=300)
if run.returncode != 0:
    print(f"FAILED: the browser run exited {run.returncode}: {run.stderr[-600:]}")
    sys.exit(1)
dom, plain = json.loads(run.stdout.strip().splitlines()[-1])

src = PAGE.read_text(encoding="utf-8")
# What the page shows a presenter: each segment's title and its prompts, in order, minus the copy button.
want: list[tuple[str, list[str]]] = []
for seg in re.findall(r'<section class="seg">(.*?)</section>', src, re.S):
    prompts = [text(p.rsplit("<button", 1)[0]) for p in re.findall(r'<div class="prompt"[^>]*>(.*?)</div>', seg, re.S)]
    if prompts:
        title = text(re.search(r"<h2>(.*?)</h2>", seg, re.S).group(1))
        want.append((re.sub(r"^SEGMENT \d · \d+ min\s*", "", title), prompts))

sheet = re.search(r'<section id="sheet">(.*?)</section>', dom, re.S)
check("the sheet renders, and is not hidden", sheet is not None, dom[-300:])
body = sheet.group(1) if sheet else ""
got: list[tuple[str, list[str]]] = []
for part in re.split(r"(?=<h2>)", body):
    h = re.match(r"<h2>(.*?)</h2>", part, re.S)
    if h:
        got.append((text(h.group(1)), [text(p) for p in re.findall(r"<p>(.*?)</p>", part, re.S)]))

print("== every /kubecon prompt is on the sheet, word for word, in order (#689) ==")
check("the page has prompts to put on the sheet", sum(len(ps) for _, ps in want) >= 12, str(want))
check("the sheet has the same segments, titles and prompts, in the same order", got == want,
      f"got {got!r}")
check("the Challenge 3 stage ask is on it", any("HC-666" in p for _, ps in got for p in ps))
check("the sheet carries no copy-button text", not any(p.endswith("copy") for _, ps in got for p in ps))
print("== only the sheet is shown ==")
for tag in ("header", "main", "footer"):
    m = re.search(rf"<{tag}\b([^>]*)>", dom)
    check(f"<{tag}> is hidden on the sheet", m is not None and "hidden" in m.group(1), m.group(0) if m else "absent")
check("the tab is titled for the iPad", "<title>KubeCon prompts</title>" in dom)
print("== and the page without ?sheet is the brief, unchanged ==")
check("without ?sheet the sheet stays hidden and empty", '<section id="sheet" hidden=""></section>' in plain)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The iPad prompt sheet carries every /kubecon prompt, in order.")
