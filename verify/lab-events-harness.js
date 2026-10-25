// ABOUTME: Runs gitops/ai-layer/web/lab-events.js against a minimal fake lab page under node and prints what it
// ABOUTME: would POST, so test_lab_events_behaviour.py can assert the wire format and what is (not) in it.
//
// Usage: node verify/lab-events-harness.js <path to lab-events.js> [armed|optout|shipped]
//   armed (default)  the ENABLED switch forced on, so the sending code itself is exercised
//   optout           armed, in a browser sending Global Privacy Control
//   shipped          the file exactly as committed, switch and all
// Prints one JSON object: {posts: [<OTLP payloads sent to /lab-events>], pure: {...}}.
'use strict';
const fs = require('fs');
const vm = require('vm');

const mode = process.argv[3] || 'armed';
const optout = mode === 'optout';
let src = fs.readFileSync(process.argv[2], 'utf8');
if (mode !== 'shipped') {
  const SWITCH = /^(\s*var ENABLED = )(true|false);/m;
  if (!SWITCH.test(src)) {
    process.stderr.write('lab-events.js has no `var ENABLED = true|false;` line to arm; the harness cannot run it\n');
    process.exit(2);
  }
  src = src.replace(SWITCH, '$1true;');
}

function classList(el) {
  return {
    contains: (c) => el.className.split(/\s+/).includes(c),
    toggle: (c) => {
      const has = el.className.split(/\s+/).includes(c);
      el.className = has ? el.className.split(/\s+/).filter((x) => x !== c).join(' ') : (el.className + ' ' + c).trim();
      return !has;
    },
  };
}
function el(tag, className, extra) {
  const e = Object.assign({ tagName: tag, className: className || '', children: [], listeners: {}, attrs: {} }, extra || {});
  e.classList = classList(e);
  e.addEventListener = (t, f) => { (e.listeners[t] = e.listeners[t] || []).push(f); };
  e.fire = (t) => (e.listeners[t] || []).forEach((f) => f({ type: t }));
  e.getAttribute = (k) => (k in e.attrs ? e.attrs[k] : null);
  e.matches = (sel) => sel.split('.').slice(1).every((c) => e.classList.contains(c)) &&
    (sel.split('.')[0] === '' || sel.split('.')[0] === e.tagName);
  e.all = () => e.children.reduce((a, c) => a.concat([c], c.all()), []);
  e.querySelectorAll = (sel) => e.all().filter((c) => c.matches(sel));
  e.querySelector = (sel) => e.querySelectorAll(sel)[0] || null;
  e.append = (...cs) => { e.children.push(...cs); return e; };
  return e;
}

// Challenge 1: two hints (the second is the "try this prompt" one) and two command blocks, one a chat prompt.
const h1 = el('div', 'h').append(el('div', 'num', { textContent: '1' }));
const hint1 = el('details', 'hint', { open: false });
const sol1 = el('details', 'hint sol', { open: false });
const cmdT = el('div', 'cmd', { textContent: 'kubectl apply -f secret-thing.yaml copy' });
const cmdC = el('div', 'cmd noterm', { textContent: 'my-datadog-password copy' });
const step1 = el('div', 'step c1').append(h1, hint1, sol1, cmdT, cmdC);
const hR = el('div', 'h').append(el('div', 'num', { textContent: '↻' }));
const stepR = el('div', 'step').append(hR);
stepR.attrs['data-lab'] = 'reset';
const fb = el('a', '', { href: 'https://feedback.agenticburn.com/quick?context=Challenges&page=3&cluster=bane-agatha&user=a%40b.c' });

const intervals = [];
const posts = [];
const pending = [];
const doc = {
  visibilityState: 'visible',
  listeners: {},
  addEventListener: (t, f) => { (doc.listeners[t] = doc.listeners[t] || []).push(f); },
  querySelectorAll: (sel) => (sel === '.guide .step' ? [step1, stepR] : []),
  getElementById: (id) => (id === 'fbbtn' ? fb : null),
};
const store = {};
const sandbox = {
  document: doc,
  navigator: optout ? { globalPrivacyControl: true } : {},
  crypto: globalThis.crypto,
  Uint8Array, Blob, JSON, Math, Date, String, Object, Array, RegExp,
  sessionStorage: { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } },
  setTimeout: (f) => f(),
  setInterval: (f, ms) => { intervals.push({ f, ms }); },
  addEventListener: () => {},
  fetch: (url, opts) => {
    if (url === '/controls') {
      const p = Promise.resolve({ ok: true, json: () => ({ ai: { budget: true, output: false }, infra: { networkpolicy: true, falco: true } }) });
      pending.push(p);
      return p;
    }
    posts.push({ url, body: JSON.parse(opts.body), method: opts.method, type: opts.headers['Content-Type'] });
    return Promise.resolve({ ok: true });
  },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);
const W = sandbox.WIBLab;

(async () => {
  W.start({ alias: 'bane-agatha', role: 'student' });
  // The lab's own handler toggles .open; the harness plays that part, then fires the click lab-events listens to.
  step1.classList.toggle('open'); h1.fire('click');
  hint1.open = true; hint1.fire('toggle');
  sol1.open = true; sol1.fire('toggle');
  cmdT.fire('click'); cmdC.fire('click');
  fb.fire('click');
  stepR.classList.toggle('open'); hR.fire('click');
  await Promise.all(pending); await new Promise((r) => setImmediate(r));
  const flush = intervals.find((i) => i.ms === 10000);
  if (flush) flush.f();
  const heartbeat = intervals.find((i) => i.ms === 60000);
  if (heartbeat) heartbeat.f();
  if (flush) flush.f();
  const pure = {
    first: W.controlTransitions(null, { networkpolicy: true }),
    removed: W.controlTransitions({ networkpolicy: true, kyverno: true }, { kyverno: true }),
    on: W.controlsOn({ ai: { budget: true, output: 'yes' }, infra: { kubearmor: true, falco: true } }),
    dnt: W.optedOut({ doNotTrack: '1' }),
    plain: W.optedOut({}),
  };
  process.stdout.write(JSON.stringify({ posts, pure, intervals: intervals.map((i) => i.ms) }));
})();
