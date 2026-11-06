# ABOUTME: Runs the storefront's own checkBackend in node with answers that land out of order, so a check that set out
# ABOUTME: before a standby took over can never grey out the composer after a newer check found the standby up (#986).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The failover drill of #986 (verify/failover_drill.py) saw it on 2026-11-06: the standby took attackme, a check
found it up and the composer came back, and then a check that had set out while the primary was dead landed its
failure and greyed the composer out again until the next check, 12 seconds on. The checks overlap because each one
waits out the router's 5-second retry budget twice while the cluster is unreachable.

Here setBackendUp and checkBackend, cut from burritbot.html, run in a node vm with stub elements and a fetch whose
answers the test releases one at a time, in the order each case names:

  - the drill's order: an older check's failures land after a newer check's success: the composer stays on;
  - one check that fails: the composer goes off, so a real outage still disables it;
  - an older failure that lands while a newer check is still out: off, then on when the newer one finds it up;
  - an older success that lands after a newer check's failure: ignored, the composer stays off.

Needs node. A missing node is a failure, not a skip. Nothing here touches the network or a cluster.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
PAGE = PAGE_PATH.read_text(encoding="utf-8")
START, END = "  function setBackendUp(up){", "  // Show the ACTIVE spend ceiling"
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("node") is None:
    print("FAILED: node is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)
start = PAGE.find(START)
end = PAGE.find(END, start)
if start < 0 or end < 0:
    print(f"FAILED: no '{START.strip()}' block ending at '{END.strip()}' in {PAGE_PATH}; the anchors this test cuts on are gone")
    sys.exit(1)
BLOCK = PAGE[start:end]
if "async function checkBackend(){" not in BLOCK:
    print(f"FAILED: the block cut from {PAGE_PATH} holds no checkBackend to run")
    sys.exit(1)

# Each case: whether the composer is on when the checks start, how many checks to start (0 is the oldest), then the
# answers to release in order, each [check, path, ok]; ok false is a failed fetch (the page treats the router's 502
# through a dead upstream, which is not ok, the same way). `want` is the composer, on or off, after each answer.
CASES = [
    {"name": "an older check's failures land after a newer check found the standby up: the composer stays on",
     "on": True, "checks": 2, "answers": [[1, "/controls", True], [0, "/controls", False], [0, "/guards", False]],
     "want": [True, True, True]},
    {"name": "a check whose /controls and /guards both fail turns the composer off",
     "on": True, "checks": 1, "answers": [[0, "/controls", False], [0, "/guards", False]], "want": [True, False]},
    {"name": "an older failure that lands while a newer check is out turns it off, and the newer success turns it on",
     "on": True, "checks": 2, "answers": [[0, "/controls", False], [0, "/guards", False], [1, "/controls", True]],
     "want": [True, False, True]},
    {"name": "an older success that lands after a newer check failed is ignored: the composer stays off",
     "on": False, "checks": 2, "answers": [[1, "/controls", False], [1, "/guards", False], [0, "/controls", True]],
     "want": [False, False, False]},
]

HARNESS = r"""
const vm = require('vm');
const [block, cases] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const tick = () => new Promise(r => setImmediate(r));

async function run(c) {
  const inp = {disabled: !c.on, placeholder: ''}, btn = {disabled: !c.on};
  const pending = [];     // one entry per fetch the page made: {check, path, resolve, reject}
  let starting = -1;      // the check being started; its first fetch is /controls
  let failed = -1;        // the check whose /controls was just failed; its next fetch is /guards
  const ctx = {
    document: {getElementById: id => ({inp, sendbtn: btn})[id] || null},
    refreshCap() {}, applyControls() {}, noBurritos() {},
    fetch(path) {
      const check = path === '/controls' ? starting : failed;
      return new Promise((resolve, reject) => pending.push({check, path, resolve, reject}));
    },
  };
  vm.createContext(ctx);
  vm.runInContext('let unreachable=0;\n' + block + '\nthis.checkBackend = checkBackend;', ctx);
  for (let i = 0; i < c.checks; i++) { starting = i; ctx.checkBackend(); await tick(); }
  const seen = [];
  for (const [check, path, ok] of c.answers) {
    for (let n = 0; n < 20 && !pending.find(p => p.check === check && p.path === path); n++) await tick();
    const i = pending.findIndex(p => p.check === check && p.path === path);
    if (i < 0) return {error: `check ${check} never fetched ${path}`};
    const [p] = pending.splice(i, 1);
    if (ok) p.resolve({ok: true, json: async () => ({})});
    else { failed = check; p.reject(new Error('502 through a dead upstream')); }
    for (let n = 0; n < 10; n++) await tick();
    seen.push(!inp.disabled);
  }
  return {seen, input: !inp.disabled, button: !btn.disabled, placeholder: inp.placeholder};
}

(async () => {
  const out = [];
  for (const c of cases) out.push(await run(c));
  process.stdout.write(JSON.stringify(out));
})();
"""

r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([BLOCK, CASES]), capture_output=True, text=True, timeout=60)
if r.returncode != 0:
    print(f"FAILED: the node harness exited {r.returncode}: {r.stderr.strip()[-800:]}")
    sys.exit(1)
results = json.loads(r.stdout)
print("== checkBackend with answers that land out of order ==")
for c, got in zip(CASES, results):
    if "error" in got:
        check(c["name"], False, got["error"])
        continue
    check(c["name"], got["seen"] == c["want"] and got["input"] == got["button"],
          f"composer on after each answer {got['seen']}, wanted {c['want']}; input on {got['input']}, "
          f"button on {got['button']}")
check("the composer that is off says the backend is starting up",
      "starting up" in results[1].get("placeholder", ""), results[1].get("placeholder", ""))

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("\nALL STOREFRONT BACKEND-CHECK ORDER CHECKS PASSED")
