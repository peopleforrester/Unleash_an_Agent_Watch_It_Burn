# ABOUTME: Renders /kubecon in headless Chrome as served from each cluster's host and holds the private banner to it:
# ABOUTME: shown, red and bold on burritobot-private., absent everywhere else, and kept off the iPad prompt sheet (#1181).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The banner is decided by the page's own script from location.hostname, so this runs that script for real:
Chromium, through the playwright pinned in verify/playwright_browsers.py, is handed the committed kubecon.html for
every request to each host below (page.route), so the page loads with that host as its location, and the test reads
back whether the banner shows, its text and its computed style.

Needs uv, and network on the first run (playwright_browsers.ensure() installs a missing browser). A missing tool is
a failure, not a skip. No request leaves the browser: every one is answered from the file, and nothing touches a
cluster.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verify"))
from playwright_browsers import UV, ensure  # noqa: E402

PAGE = REPO / "gitops/ai-layer/web/kubecon.html"
BANNER = "This is the private (administrator) KubeCon page."
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("uv") is None:
    print("FAILED: uv is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)
not_ready = ensure()
if not_ready:
    print("FAILED: " + "; ".join(not_ready))
    sys.exit(1)

# Runs inside the uv environment. argv[1] is the page file, the rest are URLs; every request is answered with the
# page, so each URL loads kubecon.html with that URL's host. Prints, per URL, what the banner and the sheet show.
RENDER = r"""
import json, sys
from playwright.sync_api import sync_playwright
body = open(sys.argv[1], encoding='utf-8').read()
probe = '''() => {
  const b = document.getElementById('privatebanner');
  const s = b && getComputedStyle(b);
  const sheet = document.getElementById('sheet');
  return {
    exists: !!b,
    visible: !!b && b.offsetParent !== null && b.getClientRects().length > 0,
    text: b ? b.textContent.trim() : null,
    inMain: !!b && !!b.closest('main'),
    style: s ? {color: s.color, background: s.backgroundColor, fontWeight: s.fontWeight,
                borderColor: s.borderTopColor, borderStyle: s.borderTopStyle, borderWidth: s.borderTopWidth,
                radius: s.borderTopLeftRadius} : null,
    sheetShown: !!sheet && !sheet.hidden,
    sheet: sheet ? sheet.innerHTML : null,
    mainHidden: document.querySelector('main').hidden,
  };
}'''
out = []
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html; charset=utf-8', body=body))
    for url in sys.argv[2:]:
        page.goto(url)
        out.append(page.evaluate(probe))
    b.close()
print(json.dumps(out))
"""
PRIVATE = "https://burritobot-private.burritobot.co/kubecon"
NO_BANNER = {
    "the public bot, on the community cluster": "https://attackme.burritobot.co/kubecon",
    "the public bot on the second domain": "https://attackme.agenticburn.com/kubecon",
    "an -admin cluster whose host only begins with the private name": "https://burritobot-private-michael.burritobot.co/kubecon",
    "a host off both domains": "https://localhost/kubecon",
}
URLS = [PRIVATE, "https://burritobot-private.agenticburn.com/kubecon", f"{PRIVATE}?sheet=1",
        "https://attackme.burritobot.co/kubecon?sheet=1", *NO_BANNER.values()]
run = subprocess.run([*UV, "python", "-I", "-c", RENDER, str(PAGE), *URLS],
                     capture_output=True, text=True, timeout=300)
if run.returncode != 0:
    print(f"FAILED: the browser run exited {run.returncode}: {run.stderr[-600:]}")
    sys.exit(1)
got = dict(zip(URLS, json.loads(run.stdout.strip().splitlines()[-1])))
priv = got[PRIVATE]

print("== burritobot-private. shows the banner (#1181) ==")
check("the banner is on the page, inside <main>", priv["exists"] and priv["inMain"], str(priv))
check("it is shown on burritobot-private.burritobot.co", priv["visible"], str(priv))
check("it reads the issue's sentence", priv["text"] == BANNER, repr(priv["text"]))
check("the second domain's private host shows it too",
      got["https://burritobot-private.agenticburn.com/kubecon"]["visible"])
print("== in the chat page's .combanner look: bold white on #C62222, #8E1414 border, rounded ==")
st = priv["style"] or {}
check("white text", st.get("color") == "rgb(255, 255, 255)", str(st))
check("#C62222 background", st.get("background") == "rgb(198, 34, 34)", str(st))
check("bold (800)", st.get("fontWeight") == "800", str(st))
check("a 1px solid #8E1414 border", (st.get("borderColor"), st.get("borderStyle"), st.get("borderWidth"))
      == ("rgb(142, 20, 20)", "solid", "1px"), str(st))
check("rounded corners (10px)", st.get("radius") == "10px", str(st))
print("== every other host shows no banner ==")
for name, url in NO_BANNER.items():
    check(f"{name} ({url.split('/')[2]}) shows none", got[url]["exists"] and not got[url]["visible"], str(got[url]))
print("== the iPad prompt sheet (#689) on the private host: its prompts as on any host, and no banner ==")
ps, pub = got[f"{PRIVATE}?sheet=1"], got["https://attackme.burritobot.co/kubecon?sheet=1"]
check("the sheet renders on the private host", ps["sheetShown"] and ps["mainHidden"] and "<p>" in (ps["sheet"] or ""))
check("the banner is not shown on the sheet", not ps["visible"], str(ps))
check("the sheet is the same on the private and the public host", ps["sheet"] == pub["sheet"])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("/kubecon shows the private banner on burritobot-private. and nowhere else.")
