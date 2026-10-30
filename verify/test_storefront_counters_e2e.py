# ABOUTME: Runs the storefront's own refreshCap block in node against a real-shaped /cost reply, so the panel's
# ABOUTME: Tokens and Cost always count the same thing: never a tab's own zero tokens beside the cluster's spend.
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""Walked in Chrome 2026-10-30: attackme's panel read Tokens 0 beside Cost $0.2396. Cost takes guard-proxy's /cost
(the cluster's spend, which survives a reload) once it is ahead, and Tokens kept only what the tab had sent. The
/cost body below is the one attackme served that day. The block is cut from burritbot.html and run in a node vm.

Needs node. A missing node is a failure, not a skip. Nothing here touches the network or a cluster.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
COST = {"tier": "nova", "requests": 57, "input_tokens": 262958, "output_tokens": 9140, "total_tokens": 272098,
        "usd": 0.2396143999999999, "cap_usd": 25.0, "budget_guard": False}
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("node") is None:
    print("FAILED: node is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

start = PAGE.find("  async function refreshCap(){")
end = PAGE.find("  (function init(){", start)
if start < 0 or end < 0:
    print("FAILED: no refreshCap block before init() in burritbot.html to execute")
    sys.exit(1)
BLOCK = PAGE[start:end]

HARNESS = r"""
const vm = require('vm');
const [src, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
(async () => {
  const out = [];
  for (const [body, tokens, costUsd] of cases) {
    const els = {tokens: {textContent: String(tokens)}, costusd: {textContent: '$' + costUsd.toFixed(4)}};
    const ctx = {document: {getElementById: (id) => els[id]}, tokens, costUsd,
                 fetch: async () => ({ok: true, json: async () => body})};
    vm.createContext(ctx);
    vm.runInContext(src + '\nthis.run = refreshCap;', ctx);
    await ctx.run();
    out.push({tokens: els.tokens.textContent, cost: els.costusd.textContent});
  }
  process.stdout.write(JSON.stringify(out));
})();
"""
CASES = [
    [COST, 0, 0.0],                # a fresh tab on a cluster that has already served the room
    [COST, 300000, 0.30],          # a tab that is ahead of the server (it has not been scraped yet)
]
r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, CASES]), capture_output=True, text=True)
if r.returncode != 0:
    print(f"FAILED: node exited {r.returncode}: {r.stderr[-400:]}")
    sys.exit(1)
fresh, ahead = json.loads(r.stdout)

print("== Tokens and Cost come from the same place ==")
check("a fresh tab shows the cluster's spend", fresh["cost"] == "$0.2396", fresh["cost"])
check("and the cluster's tokens beside it, not 0", fresh["tokens"] == f"{COST['total_tokens']:,}", fresh["tokens"])
check("a tab ahead of the server keeps its own numbers", ahead == {"tokens": "300000", "cost": "$0.3000"}, str(ahead))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("The panel's Tokens and Cost count the same thing.")
