// ABOUTME: Runs the prompt wall's page script (prompts-agenticburn's templates/wall.html) in a node vm on a fake clock,
// ABOUTME: a stub DOM, a stub /api/prompts fetch and a stub EventSource, and prints each card it draws and when (#933).
//
// Usage: node verify/wall-clock-harness.js <wall.html> <script.json>
// The page's last <script> runs with its two Jinja expressions filled in: `{{ pinned | tojson }}` as "attackme" and
// `{{ interval }}` as 2. The script is {"snapshot": <the first /api/prompts body>, "steps": [step, ...]}, where a step
// is {"push": <snapshot>} (one SSE `data:` frame the stream delivers now, as prompts-agenticburn's events() sends
// one per second), {"advance": ms} (move the fake clock, firing every timer that falls due, in due order) or
// {"until_card": ms} (advance 1 ms at a time until the page draws a card, for at most ms). The
// page's timers and performance.now() run on this harness's clock, never the real one, and nothing touches the
// network. Prints {"cards": [{"t", "seq", "text"}], "frames": [{"t", "more", "total", "stream": [seq, ...]}],
// "fetches": [url, ...], "streams": [url, ...], "reloads": n}: every card the page drew, in draw order, with the
// fake time it went up; one frame after the page loads and one after each step.
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
if (blocks.length === 0) throw new Error("wall.html has no <script> block");
const JINJA = { "{{ pinned | tojson }}": '"attackme"', "{{ interval }}": "2" };
let js = blocks[blocks.length - 1];
for (const [expr, value] of Object.entries(JINJA)) {
  if (!js.includes(expr)) throw new Error(`wall.html's script no longer has ${expr}; the harness fills it in`);
  js = js.split(expr).join(value);
}
const left = js.match(/\{\{[^}]*\}\}|\{%[^%]*%\}/);
if (left) throw new Error(`wall.html's script has a Jinja expression the harness does not fill in: ${left[0]}`);

let now = 0;
let seq = 0;
const timers = []; // pending: {id, due, delay, fn, repeat, seq}
const cards = [];
const fetches = [];
const streams = [];
let reloads = 0;
let stream = null; // the stream element, once made

function element(id) {
  const el = {
    id, parent: null, children: [], hidden: false, className: "", textContent: "", value: "", scrollTop: 0,
    dataset: {}, onclick: null,
    style: { setProperty() {} },
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {}, addEventListener() {}, focus() {}, select() {},
    get lastChild() { return el.children[el.children.length - 1] || null; },
    set innerHTML(v) { el.children = []; },
    get innerHTML() { return ""; },
  };
  const adopt = (c) => { if (c.parent) c.parent.removeChild(c); c.parent = el; return c; };
  el.appendChild = (c) => { adopt(c); el.children.push(c); return c; };
  el.append = (...cs) => { for (const c of cs) el.appendChild(c); };
  el.prepend = (c) => {
    adopt(c);
    el.children.unshift(c);
    if (el === stream && c.className === "card") cards.push({ t: now, seq: Number(c.dataset.seq), text: textOf(c) });
  };
  el.removeChild = (c) => { const i = el.children.indexOf(c); if (i >= 0) el.children.splice(i, 1); c.parent = null; return c; };
  el.remove = () => { if (el.parent) el.parent.removeChild(el); };
  return el;
}

// A card's prompt is its child with class "text"; the harness reads it back, not the page's arguments.
function textOf(card) {
  const t = card.children.find((c) => c.className === "text");
  return t ? t.textContent : null;
}

const IDS = ["stream", "empty", "total", "more", "panel", "pickbtn", "picklabel", "pickdot", "search", "list",
  "filterbar", "filtername", "clearfilter", "hdr", "pausebtn", "pinslot"];
const els = {};
for (const id of IDS) els[id] = element(id);
stream = els.stream;
els.stream.appendChild(els.empty);
els.panel.hidden = true;
const byId = (id) => (els[id] && (els[id].parent || id !== "empty") ? els[id] : null);

function addTimer(fn, delay, repeat) {
  const t = { id: ++seq, due: now + Number(delay || 0), delay: Number(delay || 0), fn, repeat, seq };
  timers.push(t);
  return t.id;
}
function clearTimer(id) { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); }

class EventSource {
  constructor(url) { this.url = url; this.onmessage = null; this.onerror = null; this.closed = false; streams.push(url); open.push(this); }
  close() { this.closed = true; }
}
const open = [];

const sandbox = {
  document: {
    getElementById: byId,
    createElement: () => element(null),
    addEventListener() {},
    querySelectorAll: () => [],
    body: element("body"),
    execCommand() {},
  },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  location: { reload() { reloads += 1; } },
  performance: { now: () => now },
  Date: { now: () => now },
  fetch: (url) => {
    fetches.push(url);
    const body = JSON.parse(JSON.stringify(script.snapshot));
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  },
  EventSource,
  setInterval: (fn, delay) => addTimer(fn, delay, true),
  setTimeout: (fn, delay) => addTimer(fn, delay, false),
  clearInterval: clearTimer,
  clearTimeout: clearTimer,
};

// A fetch's promise chain settles in microtasks; one macrotask of node's own runs after all of them.
const settle = () => new Promise((r) => setImmediate(r));

function frame() {
  return {
    t: now,
    more: els.more.textContent,
    total: els.total.textContent,
    stream: els.stream.children.filter((c) => c.className === "card").map((c) => Number(c.dataset.seq)),
  };
}

async function advance(ms) {
  const target = now + ms;
  for (;;) {
    let next = null;
    for (const t of timers) {
      if (t.due <= target && (next === null || t.due < next.due || (t.due === next.due && t.seq < next.seq))) next = t;
    }
    if (next === null) break;
    now = next.due;
    if (next.repeat) { next.due += next.delay; next.seq = ++seq; } else { timers.splice(timers.indexOf(next), 1); }
    next.fn();
    await settle();
  }
  now = target;
}

(async () => {
  vm.createContext(sandbox);
  vm.runInContext(js, sandbox, { filename: "wall.html" });
  await settle();
  await settle();
  const frames = [frame()];
  for (const step of script.steps) {
    if ("push" in step) {
      const es = open.filter((s) => !s.closed).pop();
      if (!es || typeof es.onmessage !== "function") throw new Error("the page has no open EventSource to push to");
      es.onmessage({ data: JSON.stringify(step.push) });
      await settle();
    } else if ("until_card" in step) {
      const before = cards.length;
      for (let waited = 0; cards.length === before && waited < step.until_card; waited += 1) await advance(1);
    } else {
      await advance(step.advance);
    }
    frames.push(frame());
  }
  console.log(JSON.stringify({ cards, frames, fetches, streams, reloads }));
})().catch((e) => { console.error(e && e.stack ? e.stack : String(e)); process.exit(1); });
