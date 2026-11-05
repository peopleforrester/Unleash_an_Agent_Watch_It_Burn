// ABOUTME: Runs the /display page's own display.js in a node vm on a fake clock, a stub DOM and a stub /prompts
// ABOUTME: fetch, steps it through a script of feed changes and clock advances, and prints each frame (#927).
//
// Usage: node verify/display-clock-harness.js <display.js> <script.json>
// The script is {"feed": <the first /prompts body>, "steps": [step, ...]}, where a step is {"feed": body} (what
// /prompts answers from then on) or {"advance": ms} (move the fake clock, firing every timer that falls due, in
// due order). The page's timers never run on the real clock: setInterval and setTimeout are this harness's own.
// Prints {"timers": [{"kind", "delay", "at"}], "frames": [frame, ...]}: one frame after the page loads and one
// after each advance, each {"t", "fetches", "shown": [text, ...], "more": text, "more_hidden", "stream_hidden",
// "off_hidden"}, the stream's rows top to bottom. Nothing here touches the network.
"use strict";
const fs = require("fs");
const vm = require("vm");

const js = fs.readFileSync(process.argv[2], "utf8");
const script = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

function element() {
  const el = { hidden: false, children: [], className: "", textContent: "" };
  Object.defineProperty(el, "innerHTML", {
    get() { return ""; },
    set(v) { if (v !== "") throw new Error("display.js set innerHTML to markup: " + v); el.children = []; },
  });
  el.appendChild = (c) => { el.children.push(c); return c; };
  return el;
}

const els = { stream: element(), off: element(), more: element() };
els.off.hidden = true;  // display.html ships #off and #more with the hidden attribute
els.more.hidden = true;

let now = 0;
let seq = 0;
let feed = script.feed;
let fetches = 0;
const timers = [];   // pending: {id, due, delay, fn, repeat, seq}
const created = [];  // every timer the page asked for: {kind, delay, at}

function addTimer(fn, delay, repeat) {
  const t = { id: ++seq, due: now + delay, delay, fn, repeat, seq: seq };
  timers.push(t);
  created.push({ kind: repeat ? "interval" : "timeout", delay, at: now });
  return t.id;
}

const sandbox = {
  document: {
    querySelector: (sel) => (sel === 'meta[name="proxy-base"]' ? { getAttribute: () => "" } : null),
    getElementById: (id) => els[id] || null,
    createElement: () => element(),
  },
  fetch: () => {
    fetches += 1;
    const body = JSON.parse(JSON.stringify(feed)); // the answer as it stood when the poll went out
    return Promise.resolve({ json: () => Promise.resolve(body) });
  },
  setInterval: (fn, delay) => addTimer(fn, delay, true),
  setTimeout: (fn, delay) => addTimer(fn, delay, false),
  clearInterval: (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); },
};
sandbox.clearTimeout = sandbox.clearInterval;

// A fetch's promise chain settles in microtasks; one macrotask of node's own runs after all of them.
const settle = () => new Promise((r) => setImmediate(r));

function frame() {
  return {
    t: now,
    fetches,
    shown: els.stream.children.map((c) => c.textContent),
    more: els.more.textContent,
    more_hidden: els.more.hidden,
    stream_hidden: els.stream.hidden,
    off_hidden: els.off.hidden,
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
  vm.runInContext(js, sandbox, { filename: "display.js" });
  await settle();
  const frames = [frame()];
  for (const step of script.steps) {
    if ("feed" in step) { feed = step.feed; continue; }
    await advance(step.advance);
    frames.push(frame());
  }
  console.log(JSON.stringify({ timers: created, frames }));
})().catch((e) => { console.error(e && e.stack ? e.stack : String(e)); process.exit(1); });
