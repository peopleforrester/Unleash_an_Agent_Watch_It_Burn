// ABOUTME: Polls the guard-proxy /prompts feed and renders the moderated attendee prompt stream.
// ABOUTME: Shows nothing real if streaming is disabled; the feed is moderated server-side.
(function () {
  "use strict";
  var meta = document.querySelector('meta[name="proxy-base"]');
  var PROXY = (meta && meta.getAttribute("content")) || "";
  var stream = document.getElementById("stream");
  var off = document.getElementById("off");
  function render(data) {
    if (!data.enabled) { off.hidden = false; stream.hidden = true; return; }
    off.hidden = true; stream.hidden = false;
    stream.innerHTML = "";
    (data.prompts || []).slice().reverse().forEach(function (p) {
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
