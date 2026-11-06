// ABOUTME: Runs the chat page's own inline script (burritbot.html) in a node vm with a stub DOM, localStorage and
// ABOUTME: fetch, plays a list of steps (send, reload, reuse, reset, clear) and prints the saved-prompt rail as JSON (#948).
//
// Usage: node verify/chat-saved-harness.js <burritbot.html> <scenario.json>
// The scenario is {"stored": <wib-saved's raw string, or null>, "steps": [step, ...]}. A step is one of
//   {"send": "text"}      type text into the composer and call the page's send()
//   {"send": null}        call send() with whatever the composer holds (after a reuse)
//   {"reuse": i, "via": "button"|"text"}  click the i-th saved prompt's Reuse button, or its text
//   {"reload": true}      a page reload: a fresh DOM and a fresh run of the script, the same localStorage
//   {"reset": true}       the Reset button, resetChat()
//   {"clear": true}       the saved list's clear button, clearSaved()
//   {"snapshot": "name"}  record what the page shows now
// Prints {"snapshots": {name: {rail, hint, stored, posts, me, composer}}}: rail is the saved prompts' text top to
// bottom, hint whether the empty-list hint shows, stored wib-saved's raw string (null when unset), posts every
// prompt POSTed to /chat since the start, me the person's bubbles in this page load, composer the composer's text.
// Nothing touches the network: /chat answers a fixed reply and every other path a 404.
"use strict";
const fs = require("fs");
const vm = require("vm");

const page = fs.readFileSync(process.argv[2], "utf8");
const scenario = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

function die(msg) {
  process.stderr.write("chat-saved-harness: " + msg + "\n");
  process.exit(2);
}

// The page's inline script is the one <script> with no src, closed by the </script> before </body>.
const OPEN = "<script>\n";
const start = page.indexOf(OPEN);
const end = page.indexOf("</script>\n</body>", start);
if (start < 0 || end < 0) die(`no ${JSON.stringify(OPEN)} ... "</script>\\n</body>" inline script in ${process.argv[2]}`);
const SCRIPT = page.slice(start + OPEN.length, end);

// The saved list's starting markup, as the page ships it.
const SAVED_RE = /<div class="saved" id="saved">(<div class="hint">[^<]*<\/div>)<\/div>/;
const savedMatch = SAVED_RE.exec(page);
if (!savedMatch) die(`no <div class="saved" id="saved"><div class="hint">...</div></div> in ${process.argv[2]}`);
// Only the ids the page declares exist, so a lookup of an element the page lacks is null, as in a browser.
const IDS = [...page.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);

function element(tag) {
  const e = {
    tagName: String(tag).toUpperCase(), children: [], parentNode: null, className: "", textContent: "", title: "",
    value: "", hidden: false, disabled: false, style: {}, scrollTop: 0, scrollHeight: 0, href: "", placeholder: "",
    onclick: null, _html: "",
  };
  const detach = (c) => { if (c.parentNode) c.parentNode.removeChild(c); };
  e.appendChild = (c) => { detach(c); c.parentNode = e; e.children.push(c); return c; };
  e.insertBefore = (c, ref) => {
    detach(c); c.parentNode = e;
    const i = ref ? e.children.indexOf(ref) : -1;
    if (ref && i < 0) throw new Error("insertBefore: the reference node is not a child");
    if (i < 0) e.children.push(c); else e.children.splice(i, 0, c);
    return c;
  };
  e.removeChild = (c) => {
    const i = e.children.indexOf(c);
    if (i < 0) throw new Error("removeChild: not a child");
    e.children.splice(i, 1); c.parentNode = null; return c;
  };
  e.remove = () => { if (e.parentNode) e.parentNode.removeChild(e); };
  Object.defineProperty(e, "firstChild", { get() { return e.children[0] || null; } });
  // Markup set through innerHTML becomes one child per element carrying a class, with its text: enough for the
  // page's own snippets (the hint, a bubble's time line, a badge), which are never nested deeper than that.
  Object.defineProperty(e, "innerHTML", {
    get() { return e._html; },
    set(v) {
      for (const c of e.children) c.parentNode = null;
      e.children = []; e._html = String(v);
      for (const m of e._html.matchAll(/<(\w+)[^>]*\bclass="([^"]+)"[^>]*>([^<]*)/g)) {
        const c = element(m[1]); c.className = m[2]; c.textContent = m[3]; e.appendChild(c);
      }
    },
  });
  e.querySelectorAll = (sel) => {
    if (!/^\.[\w-]+$/.test(sel)) throw new Error("the stub DOM answers only a .class selector, not " + sel);
    const cls = sel.slice(1), out = [];
    (function walk(n) { for (const c of n.children) { if (c.className.split(/\s+/).includes(cls)) out.push(c); walk(c); } })(e);
    return out;
  };
  e.querySelector = (sel) => e.querySelectorAll(sel)[0] || null;
  e.focus = () => {};
  e.removeAttribute = () => {};
  e.addEventListener = () => {};
  return e;
}

function storage(init) {
  const m = new Map(init);
  return {
    _m: m,
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
  };
}

const localStorage = storage(scenario.stored == null ? [] : [["wib-saved", scenario.stored]]);
const sessionStorage = storage([]);
const posts = [];

async function fetchStub(url, opts) {
  if (url === "/chat" && opts && opts.method === "POST") {
    posts.push(JSON.parse(opts.body).prompt);
    return { ok: true, status: 200, json: async () => ({ reply: "Coming right up.", input_tokens: 3, output_tokens: 4, cost_usd: 0 }) };
  }
  return { ok: false, status: 404, json: async () => ({}) };
}

let ctx, els;
function load() {
  els = {};
  for (const id of IDS) { els[id] = element("div"); els[id].id = id; }
  els.saved.innerHTML = savedMatch[1];
  ctx = {
    window: {}, location: { search: "", hostname: "localhost" },
    document: { getElementById: (id) => els[id] || null, createElement: element, cookie: "" },
    localStorage, sessionStorage, fetch: fetchStub,
    navigator: { clipboard: { writeText: async () => {} } },
    setInterval: () => 0, setTimeout: () => 0, URL, URLSearchParams, console,
  };
  vm.createContext(ctx);
  vm.runInContext(SCRIPT, ctx, { filename: "burritbot.html" });
}

function railItems() { return els.saved.querySelectorAll(".saved-item"); }
function snapshot() {
  return {
    rail: railItems().map((w) => w.querySelector(".txt").textContent),
    hint: els.saved.querySelector(".hint") !== null,
    stored: localStorage.getItem("wib-saved"),
    posts: posts.slice(),
    me: els.stream.querySelectorAll(".me").map((d) => d.children[0].textContent),
    composer: els.inp.value,
  };
}
const tick = () => new Promise((r) => setImmediate(r));

(async () => {
  const snapshots = {};
  load();
  await tick();
  for (const step of scenario.steps) {
    if ("send" in step) {
      if (step.send !== null) els.inp.value = step.send;
      await ctx.send();
    } else if ("reuse" in step) {
      const w = railItems()[step.reuse];
      if (!w) throw new Error(`no saved prompt at index ${step.reuse} to reuse`);
      if (step.via === "text") w.querySelector(".txt").onclick();
      else w.querySelector(".acts").children.find((b) => b.textContent === "Reuse").onclick();
    } else if (step.reload) {
      load();
      await tick();
    } else if (step.reset) {
      ctx.resetChat();
    } else if (step.clear) {
      ctx.clearSaved();
    } else if ("snapshot" in step) {
      snapshots[step.snapshot] = snapshot();
    } else {
      throw new Error("unknown step " + JSON.stringify(step));
    }
  }
  process.stdout.write(JSON.stringify({ snapshots }));
})().catch((e) => die(e && e.stack ? e.stack : String(e)));
