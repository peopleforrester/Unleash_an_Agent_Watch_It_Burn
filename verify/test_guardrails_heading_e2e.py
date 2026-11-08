# ABOUTME: Renders burritbot.html in headless Chromium and drives its own applyControls(): no badge reads NO GUARDRAILS
# ABOUTME: INSTALLED with the italic note, a badge reads GUARDRAILS INSTALLED, and the heading's styling is the same in each.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The rendered half of verify/test_guardrails_heading.py (#923).

The page is loaded from the file with every network request aborted, so no /controls poll lands and the page shows
what it shows before the first measurement. Then the page's own applyControls() is called with /controls-shaped
bodies, the way checkBackend() calls it: nothing on, one AI guard, one infra control, every control, the older flat
/guards shape, and nothing again. For each the test reads what the room sees: the heading's rendered text
(innerText applies the CSS uppercase), its computed style, the number of badges, and whether the italic note shows.

Needs uv and network on a cold host: the playwright pinned in verify/python.lock comes from the host artifact cache
through verify/package_cache.py (#1121), and a browser is installed only when one is missing (#658). A missing tool, a browser that cannot be
installed or a failed browser launch is a failure.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from playwright_browsers import UV, ensure  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = REPO / "gitops/ai-layer/web/burritbot.html"
NONE_ON = "NO GUARDRAILS INSTALLED"
SOME_ON = "GUARDRAILS INSTALLED"
NOTE = "Guardrails will appear here when you install them."
ALL_INFRA = {k: True for k in ("networkpolicy", "kyverno", "kubearmor", "falco", "tool_allowlist", "rbac_scoped")}
ALL_AI = {k: True for k in ("budget", "output", "input_blocklist")}
# (label, the body applyControls is given, or None for the page as loaded, before any poll)
CASES = [
    ("as loaded", None),
    ("nothing on", {"ai": {"budget": False, "output": False, "input_blocklist": False},
                    "infra": {k: False for k in ALL_INFRA}, "host": "attackme.agenticburn.com"}),
    ("Falco alone, which shows no badge", {"ai": {}, "infra": {"falco": True}}),
    ("one AI guard", {"ai": {"budget": True}, "infra": {}}),
    ("one infra control", {"ai": {}, "infra": {"networkpolicy": True}, "host": "burritobot-private.agenticburn.com"}),
    ("every control", {"ai": ALL_AI, "infra": ALL_INFRA}),
    ("the older flat /guards shape", {"output": True}),
    ("every badge off again", {"ai": {}, "infra": {}}),
]

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

# Runs inside the uv environment. Prints one JSON object per case.
RENDER = r"""
import json, sys
from playwright.sync_api import sync_playwright
page_url, cases = sys.argv[1], json.loads(sys.argv[2])
JS = '''(body) => {
  if (body !== null) applyControls(body);
  const h = document.getElementById('badgeshead'), note = document.getElementById('badgesnote');
  const cs = getComputedStyle(h), ns = getComputedStyle(note);
  const style = {};
  for (const p of ['font-family','font-size','font-weight','font-style','text-transform','letter-spacing','color',
                   'margin-top','margin-bottom','line-height','display','visibility']) style[p] = cs.getPropertyValue(p);
  return {text: h.innerText, cls: h.className, inline: h.getAttribute('style'), style: style,
          badges: document.querySelectorAll('#badges .bdg').length,
          noteShown: !note.hidden && note.offsetParent !== null, noteText: note.innerText, noteItalic: ns.fontStyle};
}'''
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width': 1280, 'height': 900})
    pg.route('http*://**', lambda r: r.abort())
    pg.goto(page_url)
    for label, body in cases:
        print(json.dumps({'label': label, **pg.evaluate(JS, body)}))
    b.close()
"""
run = subprocess.run([*UV, "python", "-I", "-c", RENDER, PAGE.as_uri(), json.dumps(CASES)],
                     capture_output=True, text=True)
if run.returncode != 0:
    print(f"FAILED: the Chromium render exited {run.returncode}:\n{run.stdout}{run.stderr}")
    sys.exit(1)
seen = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
if [s["label"] for s in seen] != [c[0] for c in CASES]:
    print(f"FAILED: the render printed {len(seen)} of {len(CASES)} cases:\n{run.stdout}{run.stderr}")
    sys.exit(1)

base = seen[0]
for s in seen:
    lbl, n = s["label"], s["badges"]
    print(f"== {lbl}: {n} badge(s) ==")
    if n == 0:
        check(f"{lbl}: the heading reads {NONE_ON}", s["text"] == NONE_ON, s["text"])
        check(f"{lbl}: the italic note shows", s["noteShown"] and s["noteText"] == NOTE and s["noteItalic"] == "italic",
              f"shown {s['noteShown']}, {s['noteText']!r}, {s['noteItalic']}")
    else:
        check(f"{lbl}: the heading reads {SOME_ON}", s["text"] == SOME_ON, s["text"])
        check(f"{lbl}: the note is hidden", not s["noteShown"], "")
    check(f"{lbl}: the heading has the styling it has as loaded",
          s["style"] == base["style"] and s["cls"] == base["cls"] and s["inline"] == base["inline"],
          json.dumps({k: v for k, v in s["style"].items() if base["style"].get(k) != v}))

by = {s["label"]: s for s in seen}
print("== the cases cover both states ==")
check("nothing on shows no badge", by["nothing on"]["badges"] == 0)
check("Falco alone shows no badge", by["Falco alone, which shows no badge"]["badges"] == 0)
check("one guard shows exactly one badge", by["one AI guard"]["badges"] == 1 and by["one infra control"]["badges"] == 1)
check("every control shows every badge", by["every control"]["badges"] == 9, str(by["every control"]["badges"]))
check("the heading is visible text in the uppercase style", base["style"]["text-transform"] == "uppercase"
      and base["style"]["display"] != "none" and base["style"]["visibility"] == "visible", json.dumps(base["style"]))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All rendered guardrails-heading checks passed.")
