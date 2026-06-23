// ABOUTME: Console behavior: tab switching (instructions beats + right-pane terminal/agent) and the
// ABOUTME: live cost counter polling the guard-proxy /cost endpoint (same-origin via the console frontend).
(function () {
  function wireTabs(tabSel, bodyAttr, tabAttr) {
    var tabs = document.querySelectorAll(tabSel);
    tabs.forEach(function (t) {
      t.addEventListener('click', function () {
        var key = t.getAttribute(tabAttr);
        tabs.forEach(function (x) { x.classList.toggle('active', x === t); });
        document.querySelectorAll('[' + bodyAttr + ']').forEach(function (b) {
          b.classList.toggle('hidden', b.getAttribute(bodyAttr) !== key);
        });
      });
    });
  }
  // Instruction beats (left) and right-pane tabs (terminal/agent).
  wireTabs('.ins-tabs .tab', 'data-ins-body', 'data-ins');
  wireTabs('.right .tabs .tab', 'data-pane-body', 'data-pane');

  // Live cost counter — same-origin /cost is proxied to the guard-proxy by the console frontend.
  var costEl = document.getElementById('cost');
  function poll() {
    fetch('/cost', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (j && typeof j.cost_usd !== 'undefined') costEl.textContent = '$' + Number(j.cost_usd).toFixed(4);
      })
      .catch(function () { /* guard-proxy may not be up yet; leave last value */ });
  }
  poll();
  setInterval(poll, 3000);
})();
