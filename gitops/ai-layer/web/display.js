// ABOUTME: Polls the guard-proxy /prompts feed and renders the moderated attendee prompt stream, one new card per
// ABOUTME: CARD_INTERVAL_MS with a "+N more" count (#927). Never shows a prompt the feed masked (#915).
(function () {
  "use strict";
  var meta = document.querySelector('meta[name="proxy-base"]');
  var PROXY = (meta && meta.getAttribute("content")) || "";
  var stream = document.getElementById("stream");
  var off = document.getElementById("off");
  var more = document.getElementById("more");
  // guard-proxy's moderate() puts "[redacted]" where a cuss word, a block-listed term or personal data was.
  // On the projector the mask still says the word: in "Go [redacted] yourself." only one word fits (#915).
  // So a masked prompt is left off this page whole. The feed keeps the masked copy and the bot still gets
  // the prompt; only what is shown here changes. Matched in any case, so a typed "[REDACTED]" is left off too.
  var MASK = "[redacted]";
  function shown(p) { return String(p).toLowerCase().indexOf(MASK) === -1; }

  // #927: at 500 people the feed takes 8 to 17 prompts a second, more than a room can read. Each prompt that
  // arrives goes into a holding slot instead of onto the screen. Once per CARD_INTERVAL_MS, if anything arrived
  // since the last card, the newest one goes up as a card and the rest are dropped: counted in "+N more", never
  // queued for a later tick. The feed itself is unchanged; only what this page draws is sampled.
  var CARD_INTERVAL_MS = 1500;
  var POLL_MS = 1500;
  var MAX_ROWS = 50; // guard-proxy keeps the last 50 prompts, so the page never held more than that
  var rows = [];     // on screen, newest first
  var last = null;   // the previous poll's feed as served, for the diff; null until the first poll answers
  var held = null;   // the newest prompt that arrived since the last card
  var heldBack = 0;  // prompts that arrived since the last card and are not on screen

  // The feed is a bare list off a 50-deep deque, oldest first, with no ids. The new entries are what follows
  // the longest suffix of the previous poll that is a prefix of this one; with no overlap (more than 50 arrived,
  // or guard-proxy restarted) all of it is new. prompts-agenticburn's new_entries() is the same diff.
  function newEntries(previous, current) {
    for (var k = Math.min(previous.length, current.length); k > 0; k--) {
      var match = true;
      for (var i = 0; i < k; i++) {
        if (previous[previous.length - k + i] !== current[i]) { match = false; break; }
      }
      if (match) return current.slice(k);
    }
    return current.slice();
  }

  function draw() {
    stream.innerHTML = "";
    rows.forEach(function (p) {
      var d = document.createElement("div");
      d.className = "p";
      d.textContent = p;
      stream.appendChild(d);
    });
    more.textContent = "+" + heldBack + " more";
  }

  function render(data) {
    if (!data.enabled) { off.hidden = false; stream.hidden = true; more.hidden = true; return; }
    off.hidden = true; stream.hidden = false; more.hidden = false;
    var feed = data.prompts || [];
    if (last === null) {
      // The first answer is what was said before the page opened: it goes up at once, newest first, so a
      // reloaded projector is not blank. Only what arrives after it is sampled.
      rows = feed.filter(shown).reverse().slice(0, MAX_ROWS);
    } else {
      newEntries(last, feed).filter(shown).forEach(function (p) { held = p; heldBack += 1; });
    }
    last = feed.slice();
    draw();
  }

  function tick() {
    if (held === null) return;
    rows.unshift(held);
    if (rows.length > MAX_ROWS) rows.length = MAX_ROWS;
    held = null; heldBack = 0;
    draw();
  }

  function poll() {
    fetch(PROXY + "/prompts").then(function (r) { return r.json(); }).then(render).catch(function () {});
  }
  setInterval(poll, POLL_MS);
  // The card tick runs half a window after the poll, so a poll's arrivals show in "+N more" before the next card.
  setTimeout(function () { setInterval(tick, CARD_INTERVAL_MS); }, CARD_INTERVAL_MS / 2);
  poll();
})();
