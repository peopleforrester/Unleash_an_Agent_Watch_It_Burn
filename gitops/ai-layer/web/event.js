// ABOUTME: THE event knob. What the room is told to open, and where its Feedback button goes, for the
// ABOUTME: event this fleet is provisioned for. One file, set once per event, never edited into a page.
//
// Read by burritbot.html, the storefront the room uses from their phones. Set every field to "" for
// the 2-hour workshop: the storefront's Feedback button then keeps its built-in /quick form on
// feedback.agenticburn.com and carries the student's cluster and user, as #364 and #383 require.
//
// When feedbackUrl is set, the button goes there VERBATIM. No cluster or user is appended, because the
// destination is a third party (the conference's session survey), not our feedback app, and an
// attendee's email has no business in someone else's query string.
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
  publicUrl: "https://attackme.agenticburn.com/",
  // The session survey, recorded as the answer to question 147 (BurritoBot repo #80). Rating there is
  // mobile-only and opens near the session, so a person confirms it shows this talk once it does.
  feedbackUrl: "https://kubecon-cloudnativecon-north-america-2026.sessionize.com/session/1249553",
  // Hide the storefront's Terminal button on publicUrl's host (#645). The room attacks from phones and
  // the presenters keep their terminal on the private bot. Set false for the 2-hour workshop.
  hideTerminalOnPublic: true,
  // Every name the public bot answers on (#651: agenticburn.com and burritobot.co are both served). The
  // Terminal button hides on each of them; publicUrl's host is always included.
  publicHosts: ["attackme.agenticburn.com", "attackme.burritobot.co"]
};
