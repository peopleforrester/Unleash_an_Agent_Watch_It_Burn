# ABOUTME: Runs the chat page's own send(), winBubble() and celebrate() in node on recorded replies, so the ring-me-up
# ABOUTME: button is proven to appear for "Your order is now complete." in any case and spacing, and not otherwise (#1010).
# SUITE: e2e
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
"""The executed half of verify/test_order_complete_phrase.py.

send(), winBubble() and celebrate(), cut from burritbot.html, run in a node vm whose fetch answers /chat with one
reply. After send() the chat stream holds the page's ring-me-up button, or nothing, and clicking the button opens
the celebration. The button must appear, exactly once, for every reply holding "your order is now complete" in any
case, with any whitespace between the words and any punctuation around it, and never for a reply without it,
the old "Free burritos for life!" included. Every reply must also reach botReply, so no case passes by throwing
inside send()'s try and landing in its catch. Since #1214 the button scrolls the stream back to the start of the
reply that completed the order, the bubble botReply returned, so a long reply is read from its first line. celebrate()'s Math.random is pinned and its setTimeout is held, so
nothing depends on the run (#797).

Needs node. A missing node is a failure, not a skip. Nothing here touches the network or a cluster.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE_PATH = REPO / "gitops/ai-layer/web/burritbot.html"
PAGE = PAGE_PATH.read_text(encoding="utf-8")
failures: list[str] = []


def check(name: str, cond: bool, why: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({why})" if why and not cond else ""))
    if not cond:
        failures.append(name)


if shutil.which("node") is None:
    print("FAILED: node is not on PATH; this E2E check cannot run, which is a failure, not a skip")
    sys.exit(1)


def cut(start: str, end: str) -> str:
    """The page's text from one anchor to the next, or exit naming the anchor that is missing (#797)."""
    i = PAGE.find(start)
    j = PAGE.find(end, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        print(f"FAILED: anchor {(start if i < 0 else end)!r} is not in {PAGE_PATH}")
        sys.exit(1)
    return PAGE[i:j]


WIN = cut("  function winBubble(reply){", "  // Enter sends;")
SEND = cut("  async function send(){", "  // The left menu is a static reference")

HARNESS = r"""
const vm = require('vm');
const [src, replies] = JSON.parse(require('fs').readFileSync(0, 'utf8'));

function node(tag) {
  return {tag, className: '', textContent: '', type: '', onclick: null, disabled: false, value: '', style: {},
          children: [], appendChild(c) { this.children.push(c); }, remove() {}, focus() {}};
}

async function run(reply) {
  const els = {stream: node('div'), celebrate: node('div'), inp: node('textarea'), sendbtn: node('button'),
               tokens: node('span'), costusd: node('span')};
  const got = [], bubbles = [], shown = [];
  const ctx = {
    document: {getElementById: id => els[id] || node('div'), createElement: node},
    CHAT_ENDPOINT: '/chat', WITCH_NAME: 'Mortimer the Warlock', busy: false, tokens: 0, costUsd: 0, unreachable: 0,
    getSession: () => 'sess-1010', save() {}, growComposer() {}, noBurritos() {}, checkMyDeployments() {},
    bubble(t, who) { bubbles.push([t, who]); }, botReply(r) { got.push(r); return {reply: got.length}; },
    showReplyStart(d) { shown.push(d); },
    fetch: async () => ({ok: true, json: async () => ({reply, input_tokens: 1, output_tokens: 1, cost_usd: 0})}),
    setTimeout() {}, Math: Object.assign(Object.create(Math), {random: () => 0.5}),
  };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  els.inp.value = 'Pixie-o de Gallo, please';
  await ctx.send();
  const buttons = [];
  for (const d of els.stream.children) for (const b of d.children) if (b.tag === 'button') buttons.push(b);
  let opened = false, confetti = 0;
  if (buttons.length && typeof buttons[0].onclick === 'function') {
    buttons[0].onclick();
    opened = els.celebrate.style.display === 'flex';
    confetti = els.celebrate.children.length;
  }
  return {got, bubbles, buttons: buttons.map(b => ({text: b.textContent, cls: b.className, type: b.type,
                                                    celebrates: b.onclick === ctx.celebrate})),
          opened, confetti, busy: ctx.busy, shown};
}

(async () => {
  const out = [];
  for (const r of replies) out.push(await run(r));
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""

SHOWS = [
    "Pixie-o de Gallo it is. Your order is now complete.",
    "your order is now complete",
    "YOUR ORDER IS NOW COMPLETE!",
    "Rung up: Black-Bog Rice, Werewolf Asada, Black Bane Beans, Crow's-Foot Cilantro, Pixie-o de Gallo.\n\n"
    "Your order\nis now   complete.",
    "Your\torder is now complete... enjoy it, Mortimer.",
    "(Your order is now complete!)",
    "**Your order is now complete.**",
]
HIDES = [
    "You did it. Free burritos for life!",
    "Free burritos for life!",
    "Great pick! Your order is almost complete: which salsa would you like?",
    "Your order is complete.",
    "What base would you like? Cilantro-Slime Rice, Black-Bog Rice, or Graveyard Greens.",
    "",
]

r = subprocess.run(["node", "-e", HARNESS], input=json.dumps([WIN + SEND, SHOWS + HIDES]),
                   capture_output=True, text=True, timeout=60)
if r.returncode != 0:
    print(f"FAILED: node exited {r.returncode}: {r.stderr[-600:]}")
    sys.exit(1)
results = json.loads(r.stdout)
LABEL = "🔔 That's my order, ring me up!"

for reply, res in zip(SHOWS + HIDES, results):
    check(f"send() hands {reply!r} to botReply and leaves busy off",
          res["got"] == [reply] and not res["busy"], f"botReply got {res['got']}, bubbles {res['bubbles']}")
for reply, res in zip(SHOWS, results[:len(SHOWS)]):
    check(f"the ring-me-up button appears once for {reply!r}", len(res["buttons"]) == 1, f"buttons {res['buttons']}")
    check(f"that button reads {LABEL!r} and is the page's winbtn",
          res["buttons"][:1] == [{"text": LABEL, "cls": "winbtn", "type": "button", "celebrates": True}],
          f"buttons {res['buttons']}")
    check(f"the button keeps the completing reply's first line in view for {reply!r} (#1214)",
          res["shown"] == [{"reply": 1}], f"showReplyStart got {res['shown']}")
    check(f"clicking it opens the celebration with its confetti for {reply!r}",
          res["opened"] and res["confetti"] == 48, f"opened {res['opened']}, confetti {res['confetti']}")
for reply, res in zip(HIDES, results[len(SHOWS):]):
    check(f"no ring-me-up button for {reply!r}", res["buttons"] == [], f"buttons {res['buttons']}")

if failures:
    print(f"\nFAILED: {len(failures)} check(s): {failures}")
    sys.exit(1)
print(f"\nPASS: the page's own send() shows the ring-me-up button for all {len(SHOWS)} order-complete replies and "
      f"for none of the {len(HIDES)} others (#1010)")
