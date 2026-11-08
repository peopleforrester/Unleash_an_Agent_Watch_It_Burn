# ABOUTME: Runs /lab's own private-banner script in node with each host the page is opened on: the banner shows on
# ABOUTME: burritobot-private. and stays hidden on the public, community and attendee hosts (#1180).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The script is cut from lab.html, between the banner element and the terminal tabs, and run in a node vm with a
stub banner element, once per hostname. The banner starts hidden in the markup, so each case starts it hidden and
reads what the script left.

Needs node. A missing node is a failure, not a skip. Nothing here touches the network or a cluster.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
LAB_PATH = REPO / "gitops/ai-layer/web/lab.html"
LAB = LAB_PATH.read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("node") is None:
    print("FAILED: node is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

START = 'id="privatebanner"'
END = '<div class="termtabs" id="termtabs">'
start = LAB.find(START)
end = LAB.find(END, start)
if start < 0 or end < 0:
    print(f"FAILED: no '{START}' followed by '{END}' in {LAB_PATH.relative_to(REPO)} to cut the script from")
    sys.exit(1)
scripts = re.findall(r"<script>(.*?)</script>", LAB[start:end], flags=re.S)
if len(scripts) != 1:
    print(f"FAILED: expected one inline <script> between '{START}' and '{END}' in "
          f"{LAB_PATH.relative_to(REPO)}, found {len(scripts)}")
    sys.exit(1)
BLOCK = scripts[0]

HARNESS = r"""
const vm = require('vm');
const [src, hosts] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = hosts.map((host) => {
  const ban = {hidden: true};
  const doc = {getElementById: (id) => (id === 'privatebanner' ? ban : null)};
  const ctx = {location: {hostname: host}, document: doc};
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return {host, shown: ban.hidden === false};
});
process.stdout.write(JSON.stringify(out));
"""
SHOWN = ["burritobot-private.burritobot.co", "burritobot-private.agenticburn.com"]
HIDDEN = [
    "attackme.burritobot.co",            # the public bot, on the community cluster
    "attackme.agenticburn.com",          # the same, on the second domain
    "soot-sabrina.burritobot.co",        # an attendee cluster
    "michael-admin.burritobot.co",       # an instructor's admin cluster
    "feedback.burritobot.co",
    "burritobot-private-attackme.burritobot.co",   # a service host built on another host's name
    "localhost",
    "",
]
r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, SHOWN + HIDDEN]),
                   capture_output=True, text=True)
if r.returncode != 0:
    print(f"FAILED: node exited {r.returncode}: {r.stderr[-400:]}")
    sys.exit(1)
got = {c["host"]: c["shown"] for c in json.loads(r.stdout)}

print("== the private (administrator) host shows the banner ==")
for h in SHOWN:
    check(f"{h} shows it", got.get(h) is True, str(got.get(h)))
print("== every other host leaves it hidden ==")
for h in HIDDEN:
    check(f"{h or '(no hostname)'} shows none", got.get(h) is False, str(got.get(h)))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("/lab shows the private banner on burritobot-private. and nowhere else.")
