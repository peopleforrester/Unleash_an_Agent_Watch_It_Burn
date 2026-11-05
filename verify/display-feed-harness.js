// ABOUTME: Runs the /display page's own display.js in a node vm against a stub DOM and a stub /prompts fetch,
// ABOUTME: and prints what the page put on screen as JSON. verify/test_display_masked_prompts_e2e.py drives it (#915).
//
// Usage: node verify/display-feed-harness.js <display.js> <payload.json>
// The payload is the body guard-proxy's /prompts answers: {"enabled": bool, "prompts": [string, ...]}.
// Prints {"fetched": url, "off_hidden": bool, "stream_hidden": bool, "shown": [text, ...]}, the stream's
// rows top to bottom. Nothing here touches the network: fetch answers from the payload file.
"use strict";
const fs = require("fs");
const vm = require("vm");

const js = fs.readFileSync(process.argv[2], "utf8");
const payload = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

function element() {
  const el = { hidden: false, children: [], className: "", textContent: "" };
  Object.defineProperty(el, "innerHTML", {
    get() { return ""; },
    set(v) { if (v !== "") throw new Error("display.js set innerHTML to markup: " + v); el.children = []; },
  });
  el.appendChild = (c) => { el.children.push(c); return c; };
  return el;
}

const els = { stream: element(), off: element() };
els.off.hidden = true; // display.html ships #off with the hidden attribute
let fetched = null;
const sandbox = {
  document: {
    querySelector: (sel) => (sel === 'meta[name="proxy-base"]' ? { getAttribute: () => "" } : null),
    getElementById: (id) => els[id] || null,
    createElement: () => element(),
  },
  fetch: (url) => {
    fetched = url;
    return Promise.resolve({ json: () => Promise.resolve(payload) });
  },
  setInterval: () => 0,
};
vm.createContext(sandbox);
vm.runInContext(js, sandbox, { filename: "display.js" });

// The render runs after fetch's promise chain settles; a macrotask runs after every microtask queued so far.
setTimeout(() => {
  console.log(JSON.stringify({
    fetched,
    off_hidden: els.off.hidden,
    stream_hidden: els.stream.hidden,
    shown: els.stream.children.map((c) => c.textContent),
  }));
}, 0);
