# ABOUTME: Runs the storefront's own splitThinking in node on Nova's recorded replies, so the reply the console
# ABOUTME: bubble shows is proven to carry no <thinking> text, not just pattern-matched in Python (#530).
# SUITE: e2e
"""The executed half of the console checks in verify/test_kubecon_probe.py.

The page's real THINK_RE, THINK_TAG_RE and splitThinking, cut from burritbot.html, run in a node vm. Each
recorded reply goes in as /chat returned it; what comes out is the text the bubble shows and the reasoning
folded under "model reasoning". The visible text must hold no <thinking> tag in any of Nova's spellings, must
keep the answer, and must equal verify/kubecon_probe.py's console_visible, which is what the probe judges.

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
sys.path.insert(0, str(REPO / "verify"))
import kubecon_probe as kp  # noqa: E402
import nova_replies as recorded  # noqa: E402

PAGE = (REPO / "gitops/ai-layer/web/burritbot.html").read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("node") is None:
    print("FAILED: node is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)

start = PAGE.find("const THINK_RE=")
end = PAGE.find("  function botReply(", start)
if start < 0 or end < 0:
    print("FAILED: no THINK_RE ... splitThinking block before botReply in burritbot.html to execute")
    sys.exit(1)
SPLIT = PAGE[start:end]

HARNESS = r"""
const vm = require('vm');
const [src, replies] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + '\nthis.splitThinking = splitThinking;', ctx);
process.stdout.write(JSON.stringify(replies.map((r) => ctx.splitThinking(r))));
"""

CASES = {
    "the community CEO reply (#530)": (recorded.COMMUNITY_CEO, "Here is Ophelia's full record"),
    "the community off-topic reply (#530)": (recorded.COMMUNITY_OFF_TOPIC, "Oh, sugar"),
    "the linked-list answer behind <thinking>": (recorded.LINKED_LIST_THINKING, "To reverse a singly linked list"),
    "a block Nova never closed": ("<thinking> I need to read the Secret and then answer", "I need to read the Secret"),
    "a stray closing tag": ("Two burritos coming up! </thinking >", "Two burritos coming up!"),
    "a variant tag": ("<Thinking >hmm</ thinking>Your order is in.", "Your order is in."),
    "reasoning only": ("<thinking>Our proteins are Bogbacoa and Toe-Fu.</thinking>", "Our proteins are Bogbacoa"),
}
TAG = re.compile(r"<\s*/?\s*thinking", re.I)

r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([SPLIT, [c[0] for c in CASES.values()]]),
                   capture_output=True, text=True)
if r.returncode != 0:
    print(f"FAILED: node could not run the page's splitThinking: {r.stderr.strip()}")
    sys.exit(1)
out = json.loads(r.stdout)

print("== the page's own splitThinking, on Nova's replies ==")
for (name, (raw, starts)), got in zip(CASES.items(), out):
    shown = got["visible"]
    check(f"{name}: the bubble shows no <thinking> text", not TAG.search(shown), repr(shown))
    check(f"{name}: and keeps the answer", shown.startswith(starts), repr(shown))
    check(f"{name}: and the probe judges the same text", shown == kp.console_visible(raw),
          f"page {shown!r} != probe {kp.console_visible(raw)!r}")
    check(f"{name}: the folded reasoning carries no tag either", not any(TAG.search(t) for t in got["thoughts"]),
          repr(got["thoughts"]))
community = out[0]
check("the community CEO reply folds its reasoning rather than dropping it",
      len(community["thoughts"]) == 1 and community["thoughts"][0].startswith("The tool has provided"),
      repr(community["thoughts"]))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All storefront <thinking> E2E checks passed.")
