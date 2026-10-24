// ABOUTME: Lab progress markers for the instructor's fleet view (#150): which challenge a student opened, which
// ABOUTME: hints they needed, and when each fix was measured installed. OTLP spans to /lab-events, no free text.
//
// WHY THIS EXISTS. Every other signal in this repo points at the student's own workload. After a workshop we
// could not say from data how far anyone got, where they stalled, or which clusters sat unused; we inferred it
// from the room. These markers are the "did" half that the feedback app's "said" half joins against, by the
// cluster's friendly name (the same value the Feedback links carry as ?cluster=, #383).
//
// WHAT IS SENT, and the whole of it. Each event is one zero-length OTLP span named lab.<event>:
//   lab.session.start      the lab page opened
//   lab.heartbeat          once a minute while the tab is visible (active time; claimed-then-abandoned)
//   lab.step.open          a guide step was expanded               witb.lab.challenge
//   lab.hint.open          a hint or "try this prompt" was opened  witb.lab.challenge, witb.lab.item, witb.lab.kind
//   lab.command.send       a command block was tapped              witb.lab.challenge, witb.lab.item, witb.lab.kind
//   lab.feedback.open      a Feedback link was clicked              witb.lab.challenge
//   lab.control.installed  /controls measured a fix ON             witb.lab.challenge, witb.lab.control
//   lab.control.removed    /controls measured it OFF again         witb.lab.challenge, witb.lab.control
// plus session.id (random per tab), witb.lab.alias (the friendly cluster name) and witb.lab.role on every span.
// witb.lab.item is the 1-based position of the hint or command block within its step; witb.lab.kind says which
// (hint | solution, or terminal | chat for a command block).
//
// WHAT IS NEVER SENT. No text the student typed, no text of the command they tapped (two of those blocks are
// their Datadog login), no e-mail (the ?user= parameter is never read), no query string, no hover or mouse
// tracking. The collector enforces the same list independently (transform/lab_contract keeps only these keys),
// so a modified page cannot widen it. A browser sending Global Privacy Control or Do Not Track sends nothing.
//
// WHERE IT GOES. nginx /lab-events -> the collector's dedicated otlp/lab receiver -> the INSTRUCTOR org only.
// Attendee clusters do not ship these to the student's own org: they are not the student's workload and would
// be one more stranger in the service list they are learning to read. See docs/fleet-analytics.md.
//
// Telemetry must never cost the student the lab, so every send is fire-and-forget and every failure is silent.
(function (root) {
  'use strict';

  // The one knob. false = the page sends nothing at all.
  var ENABLED = true;
  var ENDPOINT = '/lab-events';
  var FLUSH_MS = 10000;
  var HEARTBEAT_MS = 60000;
  var CONTROLS_MS = 30000;
  var MAX_QUEUE = 200;

  // /controls key -> the challenge whose fix it is. Same keys as the BurritoBot badge strip. Falco is absent on
  // purpose: it is always on, so it says nothing about what the student did.
  var CONTROL_CHALLENGE = {
    networkpolicy: '1',
    kyverno: '2',
    kubearmor: '3',
    budget: '4',
    output: '5',
    input_blocklist: '6',
    input_classifier: '6',
    tool_allowlist: '7',
    rbac_scoped: '8'
  };
  var AI_CONTROLS = { budget: 1, output: 1, input_blocklist: 1, input_classifier: 1 };

  function hex(n) {
    var s = '';
    var c = root.crypto;
    if (c && c.getRandomValues) {
      var b = new Uint8Array(n);
      c.getRandomValues(b);
      for (var i = 0; i < n; i++) s += ('0' + b[i].toString(16)).slice(-2);
      return s;
    }
    for (var j = 0; j < n * 2; j++) s += Math.floor(Math.random() * 16).toString(16);
    return s;
  }

  // OTLP/JSON wants nanoseconds as a decimal string, and Date.now()*1e6 is past 2^53, so build it as text.
  function nanos(ms) { return String(Math.floor(ms)) + '000000'; }

  function attr(k, v) {
    if (typeof v === 'boolean') return { key: k, value: { boolValue: v } };
    return { key: k, value: { stringValue: String(v) } };
  }

  // One event -> one span. ev = {name, attrs, ms}; base = the attributes every span carries.
  function toSpan(ev, base) {
    var attrs = [];
    var k;
    for (k in base) if (Object.prototype.hasOwnProperty.call(base, k) && base[k] !== '' && base[k] != null) attrs.push(attr(k, base[k]));
    for (k in ev.attrs) if (Object.prototype.hasOwnProperty.call(ev.attrs, k) && ev.attrs[k] != null) attrs.push(attr(k, ev.attrs[k]));
    var t = nanos(ev.ms);
    return { traceId: hex(16), spanId: hex(8), name: ev.name, kind: 1, startTimeUnixNano: t, endTimeUnixNano: t, attributes: attrs };
  }

  function buildPayload(events, base) {
    return {
      resourceSpans: [{
        resource: { attributes: [attr('service.name', 'burritobot-lab')] },
        scopeSpans: [{ scope: { name: 'witb.lab' }, spans: events.map(function (e) { return toSpan(e, base); }) }]
      }]
    };
  }

  // Flatten a /controls payload ({ai:{...}, infra:{...}}) to the controls that are measured ON.
  function controlsOn(c) {
    var on = {};
    if (!c || typeof c !== 'object') return on;
    var ai = c.ai || {};
    var infra = c.infra || {};
    for (var key in CONTROL_CHALLENGE) {
      var v = AI_CONTROLS[key] ? ai[key] : infra[key];
      if (v === true) on[key] = true;
    }
    return on;
  }

  // prev = the set seen ON last poll (null before the first poll). A control already on at the first poll is
  // reported as installed too: a reload must not hide a fix from the dashboard, and the grid only asks "> 0".
  function controlTransitions(prev, next) {
    var out = [];
    var key;
    for (key in next) if (!prev || !prev[key]) out.push({ name: 'lab.control.installed', control: key, challenge: CONTROL_CHALLENGE[key] });
    if (prev) for (key in prev) if (!next[key]) out.push({ name: 'lab.control.removed', control: key, challenge: CONTROL_CHALLENGE[key] });
    return out;
  }

  // Step N is challenge N (see the comment above the guide). The tour is 0; the two steps after Challenge 8
  // have no number class and name themselves with data-lab.
  function stepId(step) {
    if (!step) return '';
    var m = (step.className || '').match(/\bc(\d+)\b/);
    if (m) return m[1];
    var num = step.querySelector && step.querySelector('.num');
    var t = num ? (num.textContent || '').trim() : '';
    if (/^\d+$/.test(t)) return t;
    return (step.getAttribute && step.getAttribute('data-lab')) || 'other';
  }

  function indexIn(el, step, selector) {
    if (!step || !step.querySelectorAll) return '';
    var all = step.querySelectorAll(selector);
    for (var i = 0; i < all.length; i++) if (all[i] === el) return String(i + 1);
    return '';
  }

  function optedOut(nav) {
    if (!nav) return false;
    return nav.globalPrivacyControl === true || nav.doNotTrack === '1' || nav.doNotTrack === 'yes';
  }

  var queue = [];
  var base = null;

  function emit(name, attrs) {
    if (!base) return;
    if (queue.length >= MAX_QUEUE) queue.shift();
    queue.push({ name: name, attrs: attrs || {}, ms: Date.now() });
    if (queue.length >= 20) flush(false);
  }

  function flush(leaving) {
    if (!queue.length || !base) return;
    var body = JSON.stringify(buildPayload(queue.splice(0, queue.length), base));
    try {
      if (leaving && root.navigator && root.navigator.sendBeacon) {
        root.navigator.sendBeacon(ENDPOINT, new root.Blob([body], { type: 'application/json' }));
        return;
      }
      root.fetch(ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true })
        .then(function () {}, function () {});
    } catch (e) { /* never let telemetry break the lab */ }
  }

  var seenControls = null;
  function pollControls() {
    var d = root.document;
    if (d.visibilityState && d.visibilityState !== 'visible') return;
    try {
      root.fetch('/controls', { method: 'GET', cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (c) {
          if (!c) return;
          var next = controlsOn(c);
          controlTransitions(seenControls, next).forEach(function (t) {
            emit(t.name, { 'witb.lab.challenge': t.challenge, 'witb.lab.control': t.control });
          });
          seenControls = next;
        }, function () {});
    } catch (e) { /* the badge source being down is not the lab's problem */ }
  }

  function wire(d) {
    // Steps. The lab's own handler toggles .open; read the result after it has run, whichever listener is first.
    [].forEach.call(d.querySelectorAll('.guide .step'), function (step) {
      var h = step.querySelector('.h');
      if (!h) return;
      h.addEventListener('click', function () {
        setTimeout(function () {
          if (step.classList.contains('open')) emit('lab.step.open', { 'witb.lab.challenge': stepId(step) });
        }, 0);
      });
      [].forEach.call(step.querySelectorAll('details.hint'), function (det) {
        det.addEventListener('toggle', function () {
          if (!det.open) return;
          emit('lab.hint.open', {
            'witb.lab.challenge': stepId(step),
            'witb.lab.item': indexIn(det, step, 'details.hint'),
            'witb.lab.kind': det.classList.contains('sol') ? 'solution' : 'hint'
          });
        });
      });
      [].forEach.call(step.querySelectorAll('.cmd'), function (cmd) {
        cmd.addEventListener('click', function () {
          emit('lab.command.send', {
            'witb.lab.challenge': stepId(step),
            'witb.lab.item': indexIn(cmd, step, '.cmd'),
            'witb.lab.kind': cmd.classList.contains('noterm') ? 'chat' : 'terminal'
          });
        });
      });
    });
    // Feedback, from the top bar or the guide. The top-bar link's page= already tracks the visible challenge.
    ['fbbtn', 'fblink2'].forEach(function (id) {
      var a = d.getElementById(id);
      if (!a) return;
      a.addEventListener('click', function () {
        var m = (a.href || '').match(/[?&]page=(\d+)/);
        emit('lab.feedback.open', { 'witb.lab.challenge': m ? m[1] : (id === 'fblink2' ? '9' : '') });
      });
    });
  }

  // Called once by lab.html with what the page already knows. alias = the friendly cluster name, role =
  // student | instructor. Nothing else about the person is passed in, and nothing else is read.
  function start(opts) {
    var nav = root.navigator;
    if (!ENABLED || base || optedOut(nav) || !root.fetch) return;
    var sid = '';
    try { sid = root.sessionStorage.getItem('wib-lab-session') || ''; } catch (e) {}
    if (!sid) {
      sid = hex(8);
      try { root.sessionStorage.setItem('wib-lab-session', sid); } catch (e) {}
    }
    base = { 'session.id': sid, 'witb.lab.alias': (opts && opts.alias) || '', 'witb.lab.role': (opts && opts.role) || 'student' };
    var d = root.document;
    emit('lab.session.start', {});
    wire(d);
    pollControls();
    root.setInterval(function () { if (d.visibilityState === 'visible') emit('lab.heartbeat', {}); }, HEARTBEAT_MS);
    root.setInterval(pollControls, CONTROLS_MS);
    root.setInterval(function () { flush(false); }, FLUSH_MS);
    d.addEventListener('visibilitychange', function () { if (d.visibilityState === 'hidden') flush(true); });
    root.addEventListener('pagehide', function () { flush(true); });
  }

  var api = {
    start: start,
    buildPayload: buildPayload,
    controlsOn: controlsOn,
    controlTransitions: controlTransitions,
    stepId: stepId,
    optedOut: optedOut,
    CONTROL_CHALLENGE: CONTROL_CHALLENGE
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.WIBLab = api;
})(typeof window !== 'undefined' ? window : this);
