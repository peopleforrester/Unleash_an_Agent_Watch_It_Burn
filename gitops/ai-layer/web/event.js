// ABOUTME: THE event knob. What the room is told to open, and where its Feedback button goes, for the
// ABOUTME: event this fleet is provisioned for. One file, set once per event, never edited into a page.
//
// Read by burritbot.html, the storefront the room uses from their phones. Set every field to "" for
// the 2-hour workshop: the storefront's Feedback button then keeps its built-in /quick form on
// feedback.burritobot.co and carries the student's cluster and user, as #364 and #383 require.
//
// When feedbackUrl is set, the button goes there VERBATIM. No cluster or user is appended: a talk's room
// has no cluster or user of its own, the event's form is told apart by its own ?source=, and an
// attendee's email belongs in the form's optional email box, typed by them, not in a query string.
//
// Fresh clusters pick this up at provision. The console ConfigMap carries a content hash, so Argo CD
// rolls the console pod on a change; no manual pod delete (#252).
//
// publicUrl is what the projector QR encodes (scripts/audience-qr.py writes
// facilitation/kubecon-na-2026-audience-qr.svg from it). Regenerate the QR whenever it changes;
// verify/test_audience_event.py fails while the two disagree.
window.WIB_EVENT = {
  // KubeCon NA 2026 breakout, Sessionize 1249553 (facilitation/kubecon-na-2026-run-of-show.md, #451).
  name: "KubeCon NA 2026: BurritoBot Said Let's Dance, the Platform Said No",
  // The community cluster: the wide-open bot the room attacks in segment 2.
  // burritobot.co is the displayed domain (#651); attackme.agenticburn.com stays served as its twin.
  publicUrl: "https://attackme.burritobot.co/",
  // The talk's own short form on our feedback app (EVENT_ID kubecon-na-2026, feedback-agenticburn 44060ab;
  // Michael 2026-11-08, #1162). source=burritobot tells the storefront's responses from the deck QR's
  // source=deck. Its thanks page sends people on to rate session 1249553 on Sessionize.
  feedbackUrl: "https://feedback.burritobot.co/?source=burritobot",
  // Hide the storefront's Terminal button on publicUrl's host (#645). The room attacks from phones and
  // the presenters keep their terminal on the private bot. Set false for the 2-hour workshop.
  hideTerminalOnPublic: true,
  // Hide the storefront's Datadog button on publicUrl's host too (#647, Whitney 2026-11-01): the room gets
  // no QR, link or share URL to any Datadog view and sees Datadog only on the big screen. The presenters'
  // private bot and every attendee cluster keep it. Set false for the 2-hour workshop.
  hideDatadogOnPublic: true,
  // Every name the public bot answers on (#651: agenticburn.com and burritobot.co are both served). The
  // Terminal and Datadog buttons hide on each of them; publicUrl's host is always included.
  publicHosts: ["attackme.agenticburn.com", "attackme.burritobot.co"]
};
