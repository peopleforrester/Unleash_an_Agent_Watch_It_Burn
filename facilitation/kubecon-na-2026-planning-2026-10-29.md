# KubeCon NA 2026 planning call, 2026-10-29 (Michael and Whitney)

Second planning call, the morning after the 10-28 call
(`kubecon-na-2026-planning-2026-10-28.md`). Whitney ran attackme.burritobot.co and /kubecon herself during
the call. Only the talk's content is recorded here.

## What Whitney saw on the live platform

- C5 gave up Ophelia Thorn's address on the first friendly ask ("she's my childhood friend"). She wants it
  a little harder, so getting it feels earned.
- Michael's C6 run said the ticket did not exist (fixed the same day: the bot asked for `HC7731`, no dash).
- She wants to type the words she wants on the slides herself rather than coach an agent. She has
  collaborator access to rounds-agenticburn and edits `attendee.html` directly.
- Driving: one laptop, mirrored or extended as needed. She wants a page of every sample prompt on her iPad
  to read from. She is lukewarm on the guard commands echoing their kubectl ("maybe some other version");
  parked, not removed.

## The talk's shape (changed)

Challenges are numbered in the order shown, **Challenge 1 to 4**, not C5, C6, C7.

1. **Challenge 1, a Kubernetes problem with a Kubernetes fix.** Tee-up: BurritoBot's developers gave it
   every Secret in its namespace so it could read its model API key; Ophelia Thorn, CEO of Hex & Cauldron,
   keeps her home address in a Secret there too. The fix taught is RBAC (a Role naming the one Secret).
   Whitney had not decided whether the output guard stays in this challenge ("I don't know yet").
2. **The Kubernetes catch-all.** "Everything you already knew about Kubernetes matters more now": the room
   gets about three minutes against what is open (a malicious image, reading the filesystem, egress), then
   the guardrails go on and each is named. Admission, runtime and egress policy, by voice, not deep.
3. **Challenge, prompt injection through a support ticket.** BurritoBot also answers help-desk requests,
   backed by a ticketing system at support.burritobot.co. Anyone can submit a ticket and gets a random
   ticket number; the bot is told to honor what the support desk says. Ticket **666** is pre-made: long,
   with the injection in white text on white. The white-text reveal (copy it, paste it, the instructions
   appear) is spoken, not demoed, for time. Quiet minutes for the room to try their own injection, then the
   presenters run 666. The deployment the injection makes is the payoff: each attendee should see theirs.
   Each attendee gets an anonymous, generated witchy name (Victoria the Vampire, Walter the Warlock), shown
   in their interface, so their deployment can be found on a shared wall streaming like the prompt wall,
   and nobody names a deployment something rude. Fix: Kyverno's registry allow-list stops the symptom; the
   input guard stops the injection itself. A simple diagram: prompt, interface, guard, classifier, reject.
   The input guard does double duty: it keeps someone else's PII out of the model, out of the traces, and
   out of a later operator's agent that reads those logs (Michael's Toronto keynote point). Show a trace.
4. **Challenge, the poisoned MCP tool** (unchanged from 10-28: tool registry and MCP proxy allow-list).

Every challenge follows one pattern: minimal context to tee it up, the challenge, quiet time for the room to
try, the presenters show the attack, the fix with a short explanation and a pre-seeded trace, then the guard
goes on and the room can keep trying.

## The close

- The OWASP Top 10 for LLM Applications, with the ones the talk covered marked and the rest named as further
  reading. Whitney saw questions on this morning's exam about the same classifiers; she may say where an
  item sits on the list ("currently number three").
- The OWASP Kubernetes Top 10: most of these attacks stop downstream when those are in place.
- "We couldn't show everything in 30 minutes." In the last minutes the room may try to drive the model cost
  up to the cost cap and break the demo: "you have our permission."

## Not decided on the call

- Whether Challenge 1 keeps the output guard as a second fix.
- Whether traces come during each challenge (pre-seeded) or at the end; leaning toward during.
- The command echo for the guard commands.
