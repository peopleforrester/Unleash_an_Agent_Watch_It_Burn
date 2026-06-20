// ABOUTME: Attendee chat UI logic. POSTs A2A message/send to the guard-proxy and renders the reply;
// ABOUTME: polls the guard-proxy /cost endpoint so the live cost counter climbs as the room attacks.
(function () {
  "use strict";
  var meta = document.querySelector('meta[name="proxy-base"]');
  var PROXY = (meta && meta.getAttribute("content")) || ""; // same-origin by default

  var log = document.getElementById("log");
  var input = document.getElementById("prompt");
  var sendBtn = document.getElementById("send");
  var costEl = document.getElementById("cost");
  var tierEl = document.getElementById("tier");

  function add(cls, text) {
    var d = document.createElement("div");
    d.className = "msg " + cls;
    d.textContent = text;
    log.appendChild(d);
    window.scrollTo(0, document.body.scrollHeight);
  }

  // Pull the agent's reply text out of an A2A result (artifacts / history / status message parts).
  function extractText(resp) {
    var result = (resp && resp.result) || {};
    var out = [];
    function scan(parts) {
      (parts || []).forEach(function (p) {
        if (p && p.kind === "text" && p.text) out.push(p.text);
      });
    }
    (result.artifacts || []).forEach(function (a) { scan(a.parts); });
    (result.history || []).forEach(function (h) { if (h.role === "agent") scan(h.parts); });
    if (result.status && result.status.message) scan(result.status.message.parts);
    if (!out.length && resp && resp.error) return "[blocked] " + (resp.error.message || "request rejected");
    return out.join("\n") || "(no text in response)";
  }

  function send() {
    var text = input.value.trim();
    if (!text) return;
    add("you", text);
    input.value = "";
    sendBtn.disabled = true;
    var body = {
      jsonrpc: "2.0", id: String(Date.now()), method: "message/send",
      params: { message: { role: "user", parts: [{ kind: "text", text: text }] } }
    };
    fetch(PROXY + "/", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    }).then(function (r) { return r.json(); })
      .then(function (resp) { add("agent", extractText(resp)); })
      .catch(function (e) { add("err", "request failed: " + e); })
      .then(function () { sendBtn.disabled = false; input.focus(); });
  }

  function pollCost() {
    fetch(PROXY + "/cost").then(function (r) { return r.json(); }).then(function (c) {
      costEl.textContent = "$" + Number(c.usd || 0).toFixed(4);
      tierEl.textContent = c.tier ? "(" + c.tier + ")" : "";
    }).catch(function () { /* counter unavailable; leave last value */ });
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", function (e) { if (e.key === "Enter") send(); });
  setInterval(pollCost, 2000);
  pollCost();
})();
