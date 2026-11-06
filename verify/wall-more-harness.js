// ABOUTME: Runs the prompt wall page's own inline script (prompts-agenticburn's wall.html, as served) in a node vm on
// ABOUTME: a fake clock, a stub DOM, a fake /api/prompts and a fake /events stream, and prints each frame (#935).
//
// Usage: node verify/wall-clock-harness.js <page.html> <script.json>
// The page is the rendered HTML the wall serves at /. The script is {"history": [entry, ...], "steps": [step, ...]}.
// An entry is {"cluster", "text", "witch"}; the fake server numbers them from seq 1 as app.py's ingest() does, under
// one boot id. The page's first fetch('/api/prompts') answers with the history. A step is one of:
//   {"ingest": [entry, ...]}  the server takes these prompts (nothing reaches the page yet)
//   {"sse": true}             the open /events stream sends one frame: every prompt after that stream's cursor
//   {"sse": {"since": n}}     the same, but from seq n: a replay of prompts the page may already hold
//   {"drop": true}            the open stream errors, as a dropped connection does
//   {"advance": ms}           move the fake clock, firing every timer that falls due, in due order
// A fetch('/api/prompts?since=n') answers with every prompt after n, as app.py's snapshot() does.
// Prints {"frames": [frame, ...], "log": [event, ...]}: one frame after the page loads and one after each step,
// each {"t", "step", "log_len", "cards", "top", "more", "more_class", "more_hidden", "more_display"}. The log holds,
// in order, {"deliver": [seq, ...]} for every answer the page was handed (a fetch or a stream frame) and
// {"card": seq, "text"} for every card the page put on the stream. Nothing here touches the network or a real timer.
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

// The page's own script: the inline <script> blocks, in order. A <script src> is not the wall's.
const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
if (!inline.length) { console.error("the page has no inline <script>"); process.exit(1); }
const markup = html.replace(/<script[\s\S]*?<\/script>/g, "");

const log = [];
let now = 0;

function element(tag, attrs) {
  attrs = attrs || {};
  const el = {
    tagName: String(tag).toUpperCase(), id: attrs.id || "", hidden: "hidden" in attrs, children: [], parent: null,
    dataset: {}, listeners: {}, attributes: { ...attrs }, scrollTop: 0, value: "", type: "", title: "",
  };
  let text = attrs.__text || "";
  let cls = attrs.class || "";
  Object.defineProperty(el, "textContent", {
    get() { return el.children.length ? el.children.map((c) => c.textContent).join("") : text; },
    set(v) { text = String(v); el.children = []; },
  });
  Object.defineProperty(el, "className", { get() { return cls; }, set(v) { cls = String(v); } });
  Object.defineProperty(el, "innerHTML", { get() { return ""; }, set() { el.children = []; text = ""; } });
  Object.defineProperty(el, "lastChild", { get() { return el.children[el.children.length - 1] || null; } });
  Object.defineProperty(el, "firstChild", { get() { return el.children[0] || null; } });
  const names = () => cls.split(/\s+/).filter(Boolean);
  el.classList = {
    contains: (c) => names().includes(c),
    add: (...cs) => { cls = [...new Set([...names(), ...cs])].join(" "); },
    remove: (...cs) => { cls = names().filter((n) => !cs.includes(n)).join(" "); },
    toggle: (c, force) => {
      const on = force === undefined ? !names().includes(c) : !!force;
      if (on) el.classList.add(c); else el.classList.remove(c);
      return on;
    },
  };
  const style = {};
  style.setProperty = (k, v) => { style[k] = String(v); };
  style.getPropertyValue = (k) => style[k] || "";
  el.style = style;
  const adopt = (c) => { if (c && c.parent) c.parent.removeChild(c); if (c) c.parent = el; return c; };
  el.appendChild = (c) => { el.children.push(adopt(c)); return c; };
  el.append = (...cs) => { for (const c of cs) el.appendChild(typeof c === "string" ? element("#text", { __text: c }) : c); };
  el.prepend = (...cs) => {
    for (const c of [...cs].reverse()) {
      el.children.unshift(adopt(c));
      if (c && c.className === "card") log.push({ card: Number(c.dataset.seq), text: cardText(c) });
    }
  };
  el.removeChild = (c) => { const i = el.children.indexOf(c); if (i >= 0) el.children.splice(i, 1); c.parent = null; return c; };
  el.remove = () => { if (el.parent) el.parent.removeChild(el); };
  el.setAttribute = (k, v) => { el.attributes[k] = String(v); };
  el.getAttribute = (k) => (k in el.attributes ? el.attributes[k] : null);
  el.addEventListener = (type, fn) => { (el.listeners[type] ||= []).push(fn); };
  el.removeEventListener = () => {};
  el.focus = () => {};
  el.select = () => {};
  el.querySelector = () => null;
  el.querySelectorAll = () => [];
  return el;
}

function cardText(card) {
  const t = card.children.find((c) => c.className === "text");
  return t ? t.textContent : "";
}

// Every element the markup gives an id, with its tag, class, hidden attribute and leading text, so the page reads
// the #more line the room sees as it is shipped. #empty starts inside #stream, as in the markup.
const byId = {};
for (const m of markup.matchAll(/<([a-zA-Z][\w-]*)((?:\s+[^\s>]+(?:=(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*\/?>([^<]*)/g)) {
  const attrs = {};
  for (const a of m[2].matchAll(/([^\s=]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
    attrs[a[1].toLowerCase()] = a[2] ?? a[3] ?? a[4] ?? "";
  }
  if (!attrs.id || byId[attrs.id]) continue;
  attrs.__text = m[3].trim();
  byId[attrs.id] = element(m[1], attrs);
}
if (byId.stream && byId.empty) { byId.stream.appendChild(byId.empty); }
const body = element("body");

// The fake server: app.py's entries, snapshot() and the /events stream's cursor.
const BOOT = "harness-boot";
const entries = [];
let seq = 0;
function ingest(list) {
  for (const e of list) {
    seq += 1;
    entries.push({ seq, cluster: e.cluster, witch: e.witch || "", text: e.text, ts: 1_800_000_000 + now / 1000 });
  }
}
function snapshot(since) {
  return { prompts: entries.filter((e) => e.seq > since).map((e) => ({ ...e })), clusters: [], seq, boot: BOOT };
}
ingest(script.history || []);

let tseq = 0;
const timers = [];
function addTimer(fn, delay, repeat) {
  const t = { id: ++tseq, due: now + (Number(delay) || 0), delay: Number(delay) || 0, fn, repeat, seq: tseq };
  timers.push(t);
  return t.id;
}
function clearTimer(id) { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); }

const sources = [];
class EventSource {
  constructor(url) {
    const m = /[?&]since=(\d+)/.exec(url);
    this.url = url; this.cursor = m ? Number(m[1]) : 0; this.closed = false;
    this.onmessage = null; this.onerror = null;
    sources.push(this);
  }
  close() { this.closed = true; }
}
function openSource() {
  for (let i = sources.length - 1; i >= 0; i--) if (!sources[i].closed) return sources[i];
  return null;
}

class FakeDate extends Date {
  constructor(...a) { super(...(a.length ? a : [1_800_000_000_000 + now])); }
  static now() { return 1_800_000_000_000 + now; }
}

const reloads = [];
const sandbox = {
  document: {
    getElementById: (id) => byId[id] || null,
    createElement: (tag) => element(tag),
    addEventListener: () => {},
    removeEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: () => [],
    execCommand: () => true,
    body,
  },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  location: { reload: () => { reloads.push(now); } },
  performance: { now: () => now },
  Date: FakeDate,
  EventSource,
  fetch: (url) => {
    const m = /^\/api\/prompts(?:\?since=(\d+))?$/.exec(String(url));
    if (!m) return Promise.reject(new Error("the harness serves only /api/prompts, not " + url));
    const snap = snapshot(m[1] ? Number(m[1]) : 0);
    // Logged when the page reads the body, which is when it can apply it.
    return Promise.resolve({
      ok: true,
      json: () => { log.push({ deliver: snap.prompts.map((e) => e.seq) }); return Promise.resolve(snap); },
    });
  },
  setInterval: (fn, delay) => addTimer(fn, delay, true),
  setTimeout: (fn, delay) => addTimer(fn, delay, false),
  clearInterval: clearTimer,
  clearTimeout: clearTimer,
  console,
};
sandbox.window = sandbox;

// A fetch's promise chain settles in microtasks; one macrotask of node's own runs after all of them.
const settle = () => new Promise((r) => setImmediate(r));

function frame(step) {
  const more = byId.more || null;
  const cards = byId.stream ? byId.stream.children.filter((c) => c.className === "card") : [];
  return {
    t: now, step, log_len: log.length, cards: cards.length, top: cards.length ? cardText(cards[0]) : null,
    more: more ? more.textContent : null, more_class: more ? more.className : null,
    more_hidden: more ? more.hidden : null, more_display: more ? (more.style.display || "") : null,
    reloads: reloads.length,
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
    if (next.repeat) { next.due += next.delay; next.seq = ++tseq; } else { timers.splice(timers.indexOf(next), 1); }
    next.fn();
    await settle();
  }
  now = target;
}

(async () => {
  vm.createContext(sandbox);
  for (const [i, js] of inline.entries()) vm.runInContext(js, sandbox, { filename: `wall.html <script> #${i + 1}` });
  await settle();
  await settle();
  const frames = [frame("load")];
  for (const step of script.steps) {
    if ("ingest" in step) ingest(step.ingest);
    else if ("sse" in step) {
      const s = openSource();
      if (!s) throw new Error("an sse step found no open EventSource");
      const since = step.sse && typeof step.sse === "object" ? step.sse.since : s.cursor;
      const snap = snapshot(since);
      if (snap.prompts.length) s.cursor = Math.max(s.cursor, snap.prompts[snap.prompts.length - 1].seq);
      log.push({ deliver: snap.prompts.map((e) => e.seq) });
      if (s.onmessage) s.onmessage({ data: JSON.stringify(snap) });
      await settle();
    } else if ("drop" in step) {
      const s = openSource();
      if (!s) throw new Error("a drop step found no open EventSource");
      if (s.onerror) s.onerror(new Error("dropped"));
      await settle();
    } else if ("advance" in step) await advance(step.advance);
    else throw new Error("unknown step " + JSON.stringify(step));
    frames.push(frame(Object.keys(step)[0]));
  }
  console.log(JSON.stringify({ frames, log }));
})().catch((e) => { console.error(e && e.stack ? e.stack : String(e)); process.exit(1); });
