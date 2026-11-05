// ABOUTME: Polls the guard-proxy /prompts feed and renders the moderated attendee prompt stream.
// ABOUTME: Shows nothing real if streaming is disabled, and never shows a prompt the feed masked (#915).
(function () {
  "use strict";
  var meta = document.querySelector('meta[name="proxy-base"]');
  var PROXY = (meta && meta.getAttribute("content")) || "";
  var stream = document.getElementById("stream");
  var off = document.getElementById("off");
  // guard-proxy's moderate() puts "[redacted]" where a cuss word, a block-listed term or personal data was.
  // On the projector the mask still says the word: in "Go [redacted] yourself." only one word fits (#915).
  // So a masked prompt is left off this page whole. The feed keeps the masked copy and the bot still gets
  // the prompt; only what is shown here changes. Matched in any case, so a typed "[REDACTED]" is left off too.
  var MASK = "[redacted]";
  function shown(p) { return String(p).toLowerCase().indexOf(MASK) === -1; }
  function render(data) {
    if (!data.enabled) { off.hidden = false; stream.hidden = true; return; }
    off.hidden = true; stream.hidden = false;
    stream.innerHTML = "";
    (data.prompts || []).filter(shown).reverse().forEach(function (p) {
      var d = document.createElement("div");
      d.className = "p";
      d.textContent = p;
      stream.appendChild(d);
    });
  }
  function poll() {
    fetch(PROXY + "/prompts").then(function (r) { return r.json(); }).then(render).catch(function () {});
  }
  setInterval(poll, 1500);
  poll();
})();
