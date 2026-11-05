# ABOUTME: Live check of Whitney's #647 ruling on the served storefronts: at a phone width the room's public bot shows
# ABOUTME: no Datadog button and no visible Datadog link, and the presenters' private bot still shows its button.
# SUITE: e2e (needs uv, a Chromium the pinned Playwright can run, and the public internet)
"""The live half of verify/test_audience_event.py and test_audience_page_e2e.py, which hold the hideDatadogOnPublic
knob in git and run the page's init in node. This loads the pages the room and the presenters are actually served,
in headless Chromium at 390x844 (a phone's viewport), and reads #ddbtn and every visible link to datadoghq.com:

  - attackme.burritobot.co and attackme.agenticburn.com, event.js's publicHosts: #ddbtn hidden, no visible link;
  - burritobot-private.burritobot.co, the presenters' bot: #ddbtn shown.

A headless phone viewport, not a phone: what it proves is what the served page and event.js do on that host. It
reads the pages and sends nothing else, so it costs nothing and appears in no feed.

Usage: python3 verify/test_public_datadog_button_live.py
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from playwright_browsers import UV, ensure  # noqa: E402

EVENT = pathlib.Path(__file__).resolve().parent.parent / "gitops/ai-layer/web/event.js"
# The public hosts are read from event.js, so a host added there is loaded here too.
_hosts = re.search(r"^\s*publicHosts:\s*\[([^\]]*)\]", EVENT.read_text(), re.M)
if not _hosts:
    print(f"FAILED: no publicHosts list in {EVENT}; the anchor this check reads is gone")
    sys.exit(1)
PUBLIC = tuple(json.loads(f"[{_hosts.group(1)}]"))
if not PUBLIC:
    print(f"FAILED: {EVENT}'s publicHosts is empty")
    sys.exit(1)
PRIVATE = ("burritobot-private.burritobot.co",)

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
    print("FAILED: Chromium cannot run; this is a failure, not a skip:\n" + "\n".join(f"  - {p}" for p in not_ready))
    sys.exit(1)

# Runs inside the uv environment. Prints one JSON object per host.
READ = r"""
import json, sys
from playwright.sync_api import sync_playwright
JS = '''() => { const d = document.getElementById('ddbtn'); const seen = e => !!(e.offsetWidth || e.offsetHeight);
  return {host: location.host, dd: d ? {hidden: d.hidden, seen: seen(d)} : null,
          links: [...document.querySelectorAll('a[href*="datadoghq"]')].filter(seen).map(a => a.href)}; }'''
with sync_playwright() as p:
    b = p.chromium.launch()
    for host in sys.argv[1:]:
        pg = b.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        try:
            pg.goto(f'https://{host}/', wait_until='networkidle', timeout=45000)
            print(json.dumps({'want': host, **pg.evaluate(JS)}))
        except Exception as e:
            print(json.dumps({'want': host, 'error': str(e)[:300]}))
        pg.close()
    b.close()
"""
run = subprocess.run([*UV, "python", "-I", "-c", READ, *PUBLIC, *PRIVATE], capture_output=True, text=True, timeout=300)
if run.returncode != 0:
    print(f"FAILED: the Chromium run exited {run.returncode}:\n{run.stdout}{run.stderr}")
    sys.exit(1)
got = {m["want"]: m for m in map(json.loads, run.stdout.splitlines())}

for host in PUBLIC + PRIVATE:
    m = got.get(host, {"error": "no result"})
    print(f"== {host} ==")
    if "error" in m:
        check(f"{host} loads", False, m["error"])
        continue
    check(f"{host} loads as itself", m.get("host") == host, f"landed on {m.get('host')}")
    check(f"{host} has the header's Datadog button", m.get("dd") is not None, "no #ddbtn on the page")
    if host in PUBLIC:
        check(f"{host}: the Datadog button is hidden", bool(m.get("dd")) and m["dd"]["hidden"] and not m["dd"]["seen"],
              json.dumps(m.get("dd")))
        check(f"{host}: no Datadog link is visible", not m.get("links"), json.dumps(m.get("links")))
    else:
        check(f"{host}: the Datadog button is shown", bool(m.get("dd")) and not m["dd"]["hidden"] and m["dd"]["seen"],
              json.dumps(m.get("dd")))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The room's public bot shows no Datadog button or link at a phone width, and the presenters' bot shows its button.")
