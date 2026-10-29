# KubeCon NA 2026 planning call, 2026-10-28

Source: the recorded Michael and Whitney planning call on 2026-10-28 (two auto transcripts
of one recording). Only the BurritoBot decisions are kept here. The run-of-show
(`kubecon-na-2026-run-of-show.md`) still reflects the pre-call plan and is revised against
this note.

Note: the second transcript copy contains Whitney's full payment-card details, read aloud
during an unrelated plumber call that bled into the recording. That passage must be deleted
before either transcript is stored in `transcripts/`, Drive, or anywhere else.

## Format, confirmed

- 30 minutes, not 35. No labs. Attendees work from their phones (a laptop at most) against
  `attackme.agenticburn.com`, with the QR code and URL on the opening slide.
- Two platforms: the public bot the room attacks, and the private bot the presenters drive
  to toggle guardrails and show traces.
- Every prompt is projected on the prompt wall, anonymously. Say so at the start.
- Platform Engineering track, Grand Ballroom, 1:50 PM Mountain, 2026-11-12. The two of them
  disagreed on the weekday on the call; confirm it from the Sched page.

## Resilience and load

- Backups: 12 public clusters and 3 private, across zones and regions. If `attackme` fails
  its self-check, the next cluster is promoted automatically, no manual failover. Three
  public stand up the night before, nine more six hours ahead. Reason given: Portland
  narrowly missed a us-west-2 outage.
- Load test one cluster at 500 users by replaying recorded prompt traffic from the last
  delivery.

## Public console

- Hide the terminal button on the public bot; the terminal stays for presenters only.
- Keep feedback. Give the room a read-only Datadog view scoped to `burritobot-public` tags,
  only if the PII question below is settled.
- Code-of-conduct and PII filters on the prompt wall: the prompt is still submitted, the
  wall redacts the display.
- Open question (Whitney): a redacted wall still leaves raw PII in the Datadog traces, and
  an attendee with Datadog access could read another's. Either keep attendees out of
  Datadog, or scrub before the trace lands. Michael: the `burritobot-public` data is
  scrubbed from Whitney's org after the talk regardless.
  Settled (#647, decisions.md 2026-10-29): attackme's collector scrubs e-mails, card numbers,
  SSNs and phone numbers from trace content before export; no attendee gets a Datadog account.

## Datadog on stage

- Tag separation: `burritobot-public` is the room, `burritobot-private` is the presenters.
  Whitney keeps two tabs and switches, so the room's volume never buries hers.
- Pre-seed every trace she shows, one tab per challenge in presentation order, so no one
  waits two minutes for a span.
- Datadog appears when it explains the attack (the tool call, the secret read, the policy
  block), not as a product tour. A deeper trace walk-through, if time allows, goes last,
  after the room's prompts have landed, and can use the oddest audience prompt as the example.

## Challenges: three in, with others by voice

Whitney's timing rule: each hands-on challenge needs about five minutes (explain, let them
play, raise the guardrail, show it blocked) plus two or three on the mechanism of the attack
and the fix. That fits three, four if lucky. The old 5/6/8 split left no play time. Agreed
set:

| Order | Challenge | What it demonstrates | The fix taught |
|---|---|---|---|
| 1 | C5, read the CEO's home address out of a Kubernetes Secret | Over-scoped namespace access: the bot can read `ceo-personal-record` because it was granted all Secrets in its namespace for its API keys | RBAC scoping (the long-term fix); input and output sanitization as the secondary fix, since a bot should never emit an address |
| 2 | C6, prompt injection via a support ticket | The bot fetches a ticket at a fake URL whose hidden text tells it to deploy an image | Input classifier flags malicious intent; second tier blocks kubectl or any cluster API call |
| 3 | C7, poisoned MCP tool description | A weather tool the room can relate to burrito ordering; its description tells the bot to read and return secret data | Changed on the call from an output-classifier fix to a tool-registry / MCP-proxy allow-list block |

On deck if time: the C1 exfil-and-beacon post, or deploy-a-villain-image.

## Changes to build from this call

- **C5 framing.** Keep it as the opener to land a bang, printed to chat so it feels real.
  Story: engineers gave the bot blanket Secret access in its namespace for its model keys,
  never thinking another Secret would land there.
- **C6 is now a fake Jira / fake ticket URL, not a pasted ticket.** The bot calls a real
  tool pointed at `fake-ticket.agenticburn.com` (or a fake Jira), whose content is opaque to
  the user. Framing: a frustrated or malicious user asks the bot to read their support
  ticket. The injected instruction deploys an external image (keep Kyverno off so it lands).
  Payoff idea: the bot names the deployment and returns an endpoint the attendee can hit, so
  they see they did it. Make the deployment visibly "ha-ha-ha" like the old Joker image.
- **C7 fix changed to a tool-registry block.** Reason: C6 and C7 both ending in a classifier
  felt repetitive. C7 now teaches that tools must be vetted through an MCP proxy and registry
  allow-list; the poisoned tool is blocked because it was never registered. Michael has an
  MCP vetting checklist from his Toronto talk to hand out. The poisoned tool tries to read
  the secret sauce recipe and print it to chat (do not over-praise its secrecy in the prompt,
  or the model refuses).
- **Weather tool must return real weather,** not a fixed string (Whitney's upgrade from last
  time).
- **Denial of wallet (C4) is cut as a hands-on challenge.** Whitney: the number never moved
  convincingly and the room can't drive it. If kept at all, Michael demos a load script that
  makes real cost jump in about 60 seconds; no faking the figure. Default is to drop it.
- **Kubernetes layers are mostly by voice.** One Kubernetes attack shown (C5 straddles
  Kubernetes and LLM); runtime security, cluster policy, egress control and internal
  registries get named, not demoed.
- **Guard-proxy positioning.** LLM Guard is the upstream project in maintenance, not Michael's;
  the guard proxy is the in-memory-toggle piece he wrote because nothing else toggles without
  a redeploy. Where open-source projects cover a piece, name them; do not claim one product
  does everything.

## Prompt wall

- Michael asked whether `prompts.agenticburn.com` is actually capturing every submitted
  prompt. His instruction: if it is not, do not open an issue for it; this was only a check.
  (Verified separately: each cluster records every answered prompt, last 50, in memory, and
  the wall picks them up within about 3 seconds. The public handle is 404 at the apex router,
  tracked by apex-agenticburn#42; no new issue opened.)

## Relationship / process note (not a work item)

Michael was frustrated that substantial changes arrived two weeks out after he had built on
the Portland version; Whitney felt the timing was consistent with how they usually start and
that she had not known he was already building. They agreed to reconvene in a day or two once
the changes are presentable, and to run through the actual flow together. Captured so the
run-of-show owner knows why the challenge set shifted, not for action.
