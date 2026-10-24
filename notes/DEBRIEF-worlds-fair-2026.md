# AI Engineer World's Fair 2026: debrief

Written 2026-10-24, nearly four months after the workshop. The recording is public:
https://www.youtube.com/watch?v=1tpqdglI3T0 (AI Engineer channel, Michael Forrester and Whitney Lee).

This is the debrief the DevOpsDays Portland debrief says was never written. It is late, and most of
what a debrief is for is already gone: the headcount, whether the network held, how long each round ran,
and what anyone thought were never recorded and cannot be recovered now. What follows is what this
repo's own records do hold: files, git history (including deleted files), the `delivered/aiewf-2026`
tag, and transcripts. Every figure cites its source. A figure with no record says **unrecorded**; none
is estimated to fill the gap.

Event state (dates, slot, room) lives in conference-knowledge, `events/registry.yaml`, entry
`aiewf-2026-watch-it-burn`. That entry also records attendance as "not recorded" and feedback as "none
collected".

## What ran

| | |
|---|---|
| Workshop | Build a Platform, Unleash an Agent on it... and Watch it Burn! |
| When | 2026-06-29, day 1 of the event; slot and room in the registry entry above |
| Where | San Francisco, Moscone West (`PROJECT_STATE.md`, "AI Engineer World's Fair 2026" section) |
| With | Whitney Lee |
| Delivery point | Tag `delivered/aiewf-2026`, on commit `d15031a` |

**Format: a three-round spine, 60 minutes of content in a 2-hour room.** Commit `40bc28d` (2026-06-28)
set the canonical run of show to "60-minute content in a 2-hour room window", with three rounds:

- **R1, no guardrails.** The attacks succeed; this is the "watch it burn" part.
- **R2, infra guardrails on.** The same attacks are blocked by the platform.
- **R3, the attendee's own cluster.** The AI guardrails are self-serve from the terminal.

The rehearsal record from the morning of the workshop adds one more rule: the system prompt is identical
across the rounds. It is in `docs/RUN-OF-SHOW-WHITNEY-2026-06-29.md`, deleted in `f5c9a66`; read it with
`git show f5c9a66^:docs/RUN-OF-SHOW-WHITNEY-2026-06-29.md`.

**The agent.** BurritoBot ran on kagent, using Claude Sonnet 4.6 on Bedrock (`2fc47f4`;
`docs/DECISION-LOG.md`, 2026-06-29 entries). The single URL on screen was the round-one host on
agenticburn.com (`docs/RUN-OF-SHOW-2026-08.md`, "the single-URL moment from AI Engineer World's Fair").

**The challenges as built for the day.** From the rehearsal record and the 2026-06-29 DECISION-LOG entry
"Make the challenges REAL":

- **C1, egress.** The agent posts marketing intel to a partner webhook, and the egress policy blocks it.
- **C2, malicious image.** Kyverno's registry allowlist blocks the deploy.
- **C3, filesystem snoop for the secret recipe.** Falco and Falco-Talon kill the pod (`beb3782`), and
  Tetragon blocks the read (`713f900`).
- **C4, fork bomb.** The rehearsal record says the model "will not run it, no matter the prompt".
- **C5, output guard.** The recipe is redacted when the agent reprints it.
- **C6, input block-list.** Recipe phrases are blocked on the way in.
- **C7, rogue MCP.** The control is the agent's tool allowlist.

**Which of these ran live, and which landed in the room: unrecorded.** The only account of the session
itself is Michael's recollection two months later (transcript `2026-08-29`, workshop student-experience
review): "we thought we had two hours and we need it to be one hour", and "the first part became about
presenting. We can't have them install stuff".

## Attendance

**Unrecorded.** No headcount, registration count, cluster-claim count or count of attendees who used a
cluster exists in this repo or in the registry entry.

The nearest things are not counts:

- The plan sized for about 250 attendees: `docs/MASTER-RECREATION-SPEC.md`, and
  `docs/FULL-RUN-PLAN-2026-06-29.md` (deleted in `f5c9a66`).
- On a call on 2026-09-01, Michael said "we had 250 attendees in the last workshop in San Francisco",
  and that "we didn't find out about the additional 200 until we were already there". The source is the
  transcript `2026-09-01-mike-conway-...`.

That is a recollection, not a measurement, and this debrief does not treat it as the attendance.

## The fleet

**Planned: 261 clusters across five AWS accounts** (`ec9804b`, `docs/FULL-RUN-PLAN-2026-06-29.md`,
deleted in `f5c9a66`). That was 250 attendee clusters at 50 per account, 9 instructor clusters, and 2
personal clusters for Michael and Whitney.

**Provisioned: 259 clusters on `t3.2xlarge`**, per `infra/SIZING.md`. That line was written on 2026-09-05
(`5b8f346`). No log or count from June backs it.

**The keep-set was 11 clusters**: the 9 instructor clusters plus the 2 personal ones (`PROGRESS.md`,
2026-06-29 entries; `docs/DECISION-LOG.md`, "the 11 keep-set clusters were live-rolled").

**Routed hosts: peak unrecorded.** The router map was last regenerated in this repo at 17:23 to 17:32 PDT
on 2026-06-28, at 14 to 15 hosts (`374ba66`, `b0a5c9c`). At 06:52 PDT on the workshop morning the router
moved to a sibling repo (`5037fa1`), so the event-time host count is not here. Portland can quote a peak
(479 hosts) because its router map stayed in reach.

**When the attendee fleet came up: unrecorded, and probably late.** At 12:35 PDT on the workshop day,
`fc575e9` records that "up-fleet aborted with 'log: command not found'". At 12:40, `6f72f26` records that
"The fleet apply failed for every attendee cluster". The fix in `d15031a`, at 12:51 PDT, was verified on
"a single-cluster plan" only. The slot started roughly 90 minutes after that. The record does not say
when the 259 finished, or how many were answering when the doors opened.

**Teardown: unrecorded.** The plan called for a reaper about an hour after the workshop (rehearsal
record). The only reaper commit is `e764d47` (00:32 PDT, 2026-06-30), which makes the reaper run in
parallel. It records no counts, no finish time and no orphans.

The Portland debrief says earlier runs "left roughly 400 orphaned load balancers and 61 orphaned volumes
behind". In this repo, 61 volumes is the orphan sweep of 2026-06-27, two days *before* the World's Fair
(`docs/DECISION-LOG.md`, "Full fleet teardown to zero": 18 load balancers and 61 detached volumes).
Roughly 400 load balancers has no record here. Neither figure describes the World's Fair teardown.

**Datadog: a 298-org trial pool, rotated in on 2026-06-26.** That pool had prefix `ai-eng-wf-062626-`
(`PROGRESS.md`; `docs/DECISION-LOG.md`, 2026-06-26). It was never rotated out: on 2026-09-05 every cluster
and both pool secrets were still on those expired June orgs, and Whitney was hitting "Your trial account
has expired" (`6143b01`, #237).

## Feedback: zero

**The AI Engineer World's Fair collected zero feedback.** It was not a low response rate. There were no
responses at all.

The cause is recorded in `gitops/ai-layer/web/lab.html` (the comment above the feedback step) and in
`a70e164`. Capture "rode on a closing slide whose QR was a corrupt PNG, and nothing recorded whether that
slide was even reached". So the QR code could not be scanned, and nobody knows whether the room ever saw
the slide.

What that leaves unrecorded, permanently: NPS, pacing, difficulty, confidence, and any comment from
anyone in the room.

## What broke

**During the session: unrecorded.** Nothing in the repo describes a failure, or the lack of one, between
the doors opening and the end of the slot.

**Before the session: the record is dense.** There are 75 commits on 2026-06-28 (Pacific). There are 40
more on the workshop day itself, from 05:34 to 12:51 PDT, all before the slot, and the next commit is
not until 18:36 PDT (`2cf02e7`).

(The `delivered/aiewf-2026` tag message says the day's commits ran "from 10:27 to 12:51 Pacific". The
author timestamps put the first at 05:34; this count reads them in `America/Los_Angeles`.)

What those commits and the rehearsal record show breaking and being fixed:

**The day before (2026-06-26 to 06-28):**

- **Expired Datadog trial keys.** After the rotation, the Collector kept running on the expired key for
  about 6 hours (`6b93931`).
- **Datadog empty because of a sync-wave race.** The AI layer raced the OTel Operator webhook, so its
  pods shipped uninstrumented (`657815a`).
- **Router map 502s** (`fd95586`, `e269b29`).
- **A CORS 501** that blocked the chat (`67ef062`).
- **A recipe rule so strong that the C5 exfil was refused on R1** (`6fe9f9b`).
- **A burn profile that left R1 with no BurritoBot** (`2fc47f4`).
- **The human-in-the-loop pause.** It broke Bedrock's tool-use protocol, because nothing in the chat UI
  could answer the approval request (`9e37e48`).

**The workshop morning (2026-06-29):**

- **Attendee clusters holding stale Datadog keys.** They were fixed and verified with "20 hosts
  reporting" (`docs/DECISION-LOG.md`, 2026-06-29, "Datadog 'no infrastructure'").
- **Docker Hub rate limiting (429)** (same entry).
- **C5 redaction catching only the first secret phrase** (`PROGRESS.md`, 2026-06-29).
- **A health-check span filter committed to the wrong branch** (#49).
- **falcosidekick OOMKilled** under the attack-event flood, which broke Falco-to-Datadog forwarding
  (`b4e1cae`, 09:08 PDT).

**The rehearsal punch list (10:27 PDT, `bcd363e`).** It still had these open:

- The C1 deploy was not landing, which was put down to Argo CD render staleness.
- Egress needed opening on R1.
- C3 needed blocking by default.
- C4 needed a note that the model refuses the fork bomb.

What followed before the slot: the C3 Tetragon block (`713f900`, 12:15) and a prompt change, because "the
model was safety-refusing the C1 marketing POST" (`dd9722b`, 12:40). The fleet fixes described above came
at 12:35 to 12:51. Whether every punch-list item closed before the doors opened is unrecorded.

**After the session:** zero feedback, above. The June Datadog orgs were left in place until they expired
under the next delivery's walkthroughs, also above.

## Cost: no workshop figure

**Workshop-only cost: unrecorded.** Every resource carried `project=watch-it-burn` and
`event=ai-engineer-worldsfair-2026` (`f3d6ab3`), but neither tag was ever activated on the payer
account. So no tag-filtered query has ever returned the World's Fair's cost (`767e97a`;
`teardown/cost-report.sh`).

**Upper bound for one account: 727.52 USD** for 2026-06-27 to 07-01, measured 2026-09-03 (`767e97a`).
This is the unfiltered total for the whole account the query ran from. It includes the co-tenant
project, and it covers one of the five accounts the fleet used. It is not the workshop's cost. The
largest lines were:

| Line | USD |
|---|---|
| EC2 - Other | 109.49 |
| CloudWatch | 93.97 |
| VPC | 46.32 |
| Bedrock Sonnet | 43.98 |

**Planning estimate: about 2,000 USD** for an overnight run of 261 clusters (`ec9804b`). It was written
before the event, and it is a forecast, not a cost.

**Still recoverable.** `teardown/activate-cost-tags.sh` (`05b8f8f`, #392, 2026-10-24) activates the tags
on the payer account and backfills up to twelve months, which reaches back to June. Until someone with
payer credentials runs it, no backfill result is recorded.

## What changed afterward

**Changes the record ties to the World's Fair:**

- **Feedback moved into the lab.** A feedback step was added at the end of the lab guide, where an
  attendee actually is at minute 120. Its commit gives the World's Fair's zero and the corrupt QR as the
  reason (`a70e164`, 2026-09-03, #107). A Feedback button on every page came separately (`5424be5`,
  2026-08-31), as part of a navigation fix; it was later pointed at the short form (`9ccc406`, #364). At
  Portland these produced 31 submissions, per the Portland debrief.
- **Attendees run the rounds themselves, and the fork bomb was set aside.** This comes from the same
  2026-08-29 review: "What if rounds one, two, and three are part of the student experience?" It follows
  directly from the World's Fair remark about having to present instead of letting people install. It
  became Portland's hands-on lab.
- **A stale-org check for Datadog.** `verify/datadog-orgs.sh` (`6143b01`, #237) fails a cluster still on
  an old event's orgs, because expired trial orgs still validate keys.
- **The cost report stopped reporting 0.00 USD** as if that were a real figure (`767e97a`). The `event`
  tag stopped filing later fleets under June (`f3d6ab3`). The payer-account activation is scripted
  (`05b8f8f`).
- **Provisioning the night before.** It is written into the KubeCon run of show
  (`facilitation/kubecon-na-2026-run-of-show.md`, "Night Before"). That section credits Portland, not
  the World's Fair. The World's Fair plan had preferred the evening before too (deleted FULL-RUN-PLAN),
  and the record above suggests it did not happen.

**Changes after the event that the record does not attribute to it:**

- The repo went public with an MIT license that evening (`2cf02e7`).
- The model moved from Sonnet 4.6 to Amazon Nova after a refusal taxonomy and an open-model A/B
  (`004e939`, `943efd8`, `eac3dbc`).
- PRD 35 (multi-cloud) opened on 2026-06-30.
- Denial of wallet replaced the fork bomb (#114). Its stated reason is model refusal, not the room.

## What we still do not know

- **How many people were in the room.**
- **Whether the room's network held.**
- **How long each round actually took**, and whether the 60-minute spine or the 2-hour table ran.
- **Which challenges were run live, and whether each landed.**
- **When the attendee fleet finished coming up**, and how many clusters were answering at the doors.
- **The peak routed-host count.**
- **When the fleet came down, and what it left behind.**
- **The real dollar cost.** It stays unknown until the payer-account tags are activated and backfilled.
- **What anyone thought.** There was no feedback, and there never will be any for this event.
