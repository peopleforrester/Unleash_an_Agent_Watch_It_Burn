// ABOUTME: Runs one party page's script against a stubbed canvas at two refresh rates and reports how
// ABOUTME: far the creatures diverge, which is the measurement behind the delta-time fix in #393.
//
// Usage: node verify/party-refresh-rate.js <extracted.js> [label]
// Math.random is pinned to 0.5 so the two runs differ only in frame rate. Before the fix the same
// page drifted 236 px in three simulated seconds; after it, 1.3 px, which is integration error.
// Does a creature cover the same ground in the same wall-clock time at 60 Hz and at 144 Hz?
// Math.random is pinned so the two runs differ ONLY in frame rate, which is the thing under test.
const fs = require('fs');
const js = fs.readFileSync(process.argv[2], 'utf8');

function run(hz, seconds) {
  let raf = null, now = 0;
  const ctx = new Proxy({}, { get(_, k) {
      if (k === 'canvas') return { width: 1280, height: 800 };
      if (String(k).startsWith('create')) return () => ({ addColorStop: () => {} });
      return () => {};
    }, set() { return true; } });
  const el = () => ({ width: 1280, height: 800, style: {}, textContent: '',
    getContext: () => ctx, addEventListener: () => {}, appendChild: () => {} });
  const sandbox = {
    document: { getElementById: el, createElement: el, body: el(), addEventListener: () => {} },
    window: { innerWidth: 1280, innerHeight: 800, addEventListener: () => {} },
    innerWidth: 1280, innerHeight: 800, addEventListener: () => {},
    requestAnimationFrame: (fn) => { raf = fn; return 1; },
    setTimeout: () => 0,
    performance: { now: () => now },
  };
  Object.assign(global, sandbox);
  const realRandom = Math.random;
  Math.random = () => 0.5;                       // pinned: identical decisions in both runs
  try {
    (0, eval)(js + "\n;globalThis.__snap=()=>creatures.map(c=>[c.x,c.y]);");
    const step = 1000 / hz, frames = Math.round(seconds * hz);
    for (let i = 0; i < frames; i++) { now += step; const fn = raf; raf = null; fn(now); }
    return globalThis.__snap();
  } finally { Math.random = realRandom; }
}

const a = run(60, 3), b = run(144, 3);
const n = Math.min(a.length, b.length);
let worst = 0;
for (let i = 0; i < n; i++) {
  const d = Math.hypot(a[i][0] - b[i][0], a[i][1] - b[i][1]);
  if (d > worst) worst = d;
}
console.log(`${process.argv[3] || ''} creatures=${n} worst drift after 3s = ${worst.toFixed(1)} px`);
