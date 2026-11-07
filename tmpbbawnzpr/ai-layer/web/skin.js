// ABOUTME: Applies the active VTT skin (from active-skin.js, defined in skins.js) to the terminal chrome.
// ABOUTME: Palette vars are set on <html> immediately (no color flash); brand text/title/favicon on DOM ready.
//
// Loaded in <head> of lab.html and console.html AFTER skins.js + active-skin.js. Every hook is optional:
// an element a given page does not have is simply skipped, so one applier serves both pages. The page
// identifies itself with <html data-vtt-page="lab|console"> so the right title token is chosen.
(function () {
  var key = window.WITB_ACTIVE_SKIN || "burritobot";
  var skins = window.WITB_SKINS || {};
  var s = skins[key] || skins.burritobot;
  if (!s) return;
  var root = document.documentElement;

  // Palette first, on <html> which exists even while <head> parses -> the chrome paints in-skin, no flash.
  if (s.vars) {
    for (var k in s.vars) {
      if (Object.prototype.hasOwnProperty.call(s.vars, k)) root.style.setProperty(k, s.vars[k]);
    }
  }

  function applyText() {
    document.querySelectorAll('[data-brand="name"]').forEach(function (el) {
      if (s.brandName != null) el.textContent = s.brandName;
    });
    document.querySelectorAll('[data-brand="emoji"]').forEach(function (el) {
      if (s.brandEmoji != null) el.textContent = s.brandEmoji;
    });
    document.querySelectorAll('[data-brand="h1console"]').forEach(function (el) {
      if (s.h1Console != null) el.textContent = s.h1Console;
    });

    var page = root.getAttribute("data-vtt-page");
    if (page === "lab" && s.titleLab) document.title = s.titleLab;
    if (page === "console" && s.titleConsole) document.title = s.titleConsole;

    if (s.favicon) {
      var link = document.querySelector('link[rel="icon"]');
      if (link) {
        link.setAttribute(
          "href",
          "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>" +
            "<text y='.9em' font-size='90'>" + encodeURIComponent(s.favicon) + "</text></svg>"
        );
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyText);
  } else {
    applyText();
  }
})();
