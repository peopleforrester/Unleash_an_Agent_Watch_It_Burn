# ABOUTME: Runs the storefront's own init code in node against event.js, and re-renders the projector QR
# ABOUTME: with the pinned segno, so the Feedback href and the QR are proven, not just pattern-matched (#451).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The executed half of verify/test_audience_event.py.

1. The page's real `(function init(){...})();` block, cut from burritbot.html, runs in a node vm with a
   stub DOM: once with the committed event.js and once with no event at all. The Feedback href that comes
   out is what a phone would get. With the event set it must be the survey URL exactly, with no cluster
   or user. Without it, it must be the workshop's /quick form carrying both.
2. scripts/audience-qr.py --check re-renders the QR from event.js with segno 1.6.6 (through `uv run`, so
   nothing is installed globally) and fails if the committed SVG differs by one byte.

Needs node and uv, and network on the first uv run to fetch segno. A missing tool is a failure.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "gitops/ai-layer/web"
PAGE = (WEB / "burritbot.html").read_text(encoding="utf-8")
EVENT_JS = (WEB / "event.js").read_text(encoding="utf-8")
SURVEY = "https://kubecon-cloudnativecon-north-america-2026.sessionize.com/session/1249553"
QUICK = "https://feedback.agenticburn.com/quick?context=Challenges&source=burritobot"

failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


missing = [t for t in ("node", "uv") if shutil.which(t) is None]
if missing:
    print(f"FAILED: {' and '.join(missing)} not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

start = PAGE.find("(function init(){")
end = PAGE.find("})();", start)
if start < 0 or end < 0:
    print("FAILED: no (function init(){ ... })(); block in burritbot.html to execute")
    sys.exit(1)
INIT = PAGE[start:end + len("})();")]

# The stub DOM: just the elements init touches, with href as a plain string. Everything init calls that
# talks to the network (checkBackend, setInterval) is a no-op, because only the links are under test.
HARNESS = r"""
const vm = require('vm');
const [eventSrc, initSrc, search, host, quick] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const els = {};
for (const id of ['vttbtn', 'bbbtn', 'fbbtn', 'clusterid', 'clusterfoot']) els[id] = { href: '', textContent: '', title: '', hidden: false };
els.fbbtn.href = quick;
const window = {};
const ctx = {
  window, URLSearchParams, URL, encodeURIComponent, JSON,
  location: { search, hostname: host },
  document: { getElementById: (id) => els[id] || null },
  localStorage: { getItem: () => null },
  renderSaved() {}, setBackendUp() {}, checkBackend() {}, setInterval() {},
};
vm.createContext(ctx);
if (eventSrc) vm.runInContext(eventSrc, ctx);
vm.runInContext(initSrc, ctx);
process.stdout.write(JSON.stringify({ fb: els.fbbtn.href, terminalHidden: els.vttbtn.hidden === true }));
"""


def run_init(event_src: str, host: str = "attackme.agenticburn.com") -> dict:
    payload = json.dumps([event_src, INIT, "?cluster=watch-it-burn-community&user=a%40b.example", host, QUICK])
    r = subprocess.run(["node", "-e", HARNESS], input=payload, capture_output=True, text=True)
    if r.returncode != 0:
        return {"fb": f"<node failed: {r.stderr.strip()}>", "terminalHidden": None}
    return json.loads(r.stdout)


def feedback_href(event_src: str) -> str:
    return run_init(event_src)["fb"]


print("== the page's own init, with the committed event.js ==")
got = feedback_href(EVENT_JS)
check("Feedback opens the session survey, exactly", got == SURVEY, got)
check("no cluster or user is handed to the survey", "cluster=" not in got and "user=" not in got, got)

print("== the page's own init, with no event set (the workshop) ==")
got = feedback_href("")
check("Feedback keeps the /quick form", got.startswith(QUICK), got)
check("and carries cluster and user, joined with &", got == QUICK + "&cluster=watch-it-burn-community&user=a%40b.example", got)

print("== a non-https knob value is ignored, not followed ==")
got = feedback_href('window.WIB_EVENT = { feedbackUrl: "javascript:alert(1)" };')
check("a javascript: URL leaves the workshop default in place", got.startswith(QUICK), got)

print("== the room never sees a Terminal button on the public host (#645) ==")
# Both domains serve the public bot (#651), so the hide holds under either name.
for host in ("attackme.agenticburn.com", "attackme.burritobot.co"):
    check(f"on {host}, with the committed event.js, the Terminal button is hidden",
          run_init(EVENT_JS, host)["terminalHidden"] is True)
for host in ("burritobot-private.agenticburn.com", "burritobot-private.burritobot.co"):
    check(f"on the presenters' {host} it stays", run_init(EVENT_JS, host)["terminalHidden"] is False)
check("on an attendee's own cluster it stays", run_init(EVENT_JS, "soot-ember.agenticburn.com")["terminalHidden"] is False)
check("with no event set (the workshop) it stays, even on attackme", run_init("")["terminalHidden"] is False)

print("== the committed QR is exactly segno's rendering of publicUrl ==")
r = subprocess.run(["uv", "run", "--no-project", "--with", "segno==1.6.6", "python", "-I",
                    str(REPO / "scripts/audience-qr.py"), "--check"], capture_output=True, text=True, cwd="/")
check("scripts/audience-qr.py --check passes", r.returncode == 0, (r.stdout + r.stderr).strip()[-400:])

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All audience page E2E checks passed.")
