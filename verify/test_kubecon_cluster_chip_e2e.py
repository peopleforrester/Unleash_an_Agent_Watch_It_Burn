# ABOUTME: Runs /kubecon's own cluster-chip block in node, so the header names the cluster the tab is on: from the
# ABOUTME: fleet's ?cluster= link when given, else from the host the page was opened on.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Walked in Chrome 2026-10-30: https://burritobot-private.burritobot.co/kubecon, opened directly, showed
"(cluster not specified)", because only a ?cluster= link set the chip. The block is cut from kubecon.html and run
in a node vm with stub elements.

Needs node. A missing node is a failure, not a skip. Nothing here touches the network or a cluster.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/kubecon.html").read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("node") is None:
    print("FAILED: node is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

start = PAGE.find("  // Carry the cluster identity")
end = PAGE.find("  // The iPad prompt sheet", start)
if start < 0 or end < 0:
    print("FAILED: no cluster-chip block before the prompt-sheet block in kubecon.html to execute")
    sys.exit(1)
BLOCK = PAGE[start:end]

HARNESS = r"""
const vm = require('vm');
const [src, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(([host, search]) => {
  const els = {cl: {textContent: '(cluster not specified)'}, bb: {href: '/'}};
  const doc = {title: 'KubeCon brief', getElementById: (id) => els[id] || null};
  const ctx = {location: {hostname: host, search}, document: doc, URLSearchParams};
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return {chip: els.cl.textContent, bb: els.bb.href, title: doc.title};
});
process.stdout.write(JSON.stringify(out));
"""
CASES = [
    ("burritobot-private.burritobot.co", ""),
    ("attackme.burritobot.co", ""),
    ("attackme.agenticburn.com", ""),
    ("attackme.burritobot.co", "?cluster=burritobot-public"),
    ("localhost", ""),
]
r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, CASES]), capture_output=True, text=True)
if r.returncode != 0:
    print(f"FAILED: node exited {r.returncode}: {r.stderr[-400:]}")
    sys.exit(1)
private, public, other_domain, linked, local = json.loads(r.stdout)

print("== opened directly, the chip names the cluster from the host ==")
check("burritobot-private.burritobot.co names burritobot-private", private["chip"] == "burritobot-private", str(private))
check("and its BurritoBot link carries it", private["bb"] == "/?cluster=burritobot-private", private["bb"])
check("attackme.burritobot.co names attackme", public["chip"] == "attackme", str(public))
check("the second domain names the same cluster", other_domain["chip"] == "attackme", str(other_domain))
check("the tab title names it", private["title"] == "KubeCon brief: burritobot-private", private["title"])
print("== the fleet's ?cluster= link still wins, and an unknown host is left alone ==")
check("?cluster= wins over the host", linked["chip"] == "burritobot-public", str(linked))
check("a host off both domains keeps 'not specified'", local["chip"] == "(cluster not specified)", str(local))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The KubeCon brief names the cluster its tab is on.")
