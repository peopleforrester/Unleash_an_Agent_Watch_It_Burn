<!-- ABOUTME: The 30-minute KubeCon NA 2026 breakout run-of-show for Michael and Whitney, cut from the
     ABOUTME: 2-hour workshop: a demo-only session on one platform, audience on phones, no attendee labs. -->

# KubeCon NA 2026 Run of Show

"BurritoBot Said Let's Dance, the Platform Said No." Sessionize session 1249553.
Thursday 2026-11-12, 13:50 to 14:20 MST (30 minutes), Grand Ballroom BDF, Salt
Lake City. Michael Forrester (Accenture) and Whitney Lee.

**This is the breakout, not the workshop.** It is a demo. Nobody in the room
provisions a cluster. The audience takes part only from their phones against the
wide-open community bot. Do not point anyone at the attendee lab, the
provisioning page, or the per-challenge install steps: those are the 2-hour
workshop and they stay off for this session.

- The 2-hour workshop files (`facilitation/runbook.md`,
  `facilitation/slides-outline.md`, `docs/RUN-OF-SHOW-2026-08.md`) are the other
  format. This file does not replace them.
- The presenters drive from the slides built in `peopleforrester/rounds-agenticburn`
  (checkout `~/repos/agenticburn/rounds-agenticburn`). Issue rounds-agenticburn#38
  cuts that deck from this run-of-show, beat for beat.
- The prompts the presenters send are not reproduced here. They live, copy-ready,
  on `/brief` on each cluster (`gitops/ai-layer/web/brief.html`) and in
  `challenges/PROMPT-CATALOG.md` with their verified results. Drive from `/brief`,
  read the timing from this file.

## The one platform, and the two clusters on it

The session runs on the agenticburn fleet. For a demo that means the roster in
`infra/terraform/fleet/roster.tsv`, not the attendee pool:

- **Community cluster**, `attackme.agenticburn.com`: no guardrails at all. This is
  what the room attacks from their phones, and where the wide-open start happens.
- **A presenter admin cluster**, `michael-admin.agenticburn.com` (Whitney's is
  `whitney-admin.agenticburn.com`): the full IDP with every Kubernetes control
  armed, and the AI guardrails present but toggled off at the start so they can be
  turned on live. This is the guarded half of every before/after.

Terminal login on both is `sprouts` / `sprouts`. Read it off the cluster if in
doubt:
`kubectl -n agent get secret terminal-auth -o jsonpath='{.data.TTYD_CREDENTIAL}' | base64 -d`.

Guard toggles on the admin cluster, from its terminal: `guards-off` and
`guards-on` flip everything; `guard-output-on`, `guard-input-on`, `guard-mcp-on`
and `guard-budget-on` flip one at a time. They go through the guard-proxy
`/toggle` endpoint, which Argo CD does not revert and which keeps the cost counter
alive, so never flip a guard with `kubectl set env`.

---

## The segments, in order (30 minutes)

| # | Min | Who | On screen | The room | Abstract points |
|---|-----|-----|-----------|----------|-----------------|
| 1 | 2 | M | Title, then the deleted-cluster hook | Listens | framing |
| 2 | 5 | W leads, M on cost | Community bot `attackme.agenticburn.com`, cost counter | Attacks it from their phones | 1, 4, 9 (live half) |
| 3 | 3 | M | The admin cluster: Argo CD apps, the platform tour | Watches | 3 |
| 4 | 6 | W narrates, M names controls | Admin cluster: re-run the attacks, each blocked | Watches | 5 |
| 5 | 7 | M+W | Admin cluster: toggle the AI guardrails on live | Watches | 2, 6 |
| 6 | 3 | W | Datadog traces on the shared org | Watches | 7 |
| 7 | 4 | M+W | On-topic guardrail on, then the close | Watches | 8 |

Total 30 minutes. Demo (segments 2 to 6) is 24 minutes. Open and close (segments
1 and 7) are 6 minutes.

### Segment 1: Cold open (2 min). Owner: Michael, alone.

The hook before any introductions. A compressed form of
`facilitation/cold-open-script.md`: the night an agent deleted a cluster, then one
line that moves it to production stakes. Do not run the full two-tier script; this
is a 30-minute slot, not the workshop's three-minute open. One beat on the story,
one beat on what changes when the same agent has that access in production, then
introduce Michael and Whitney and the burrito chain.

- **Delivers:** the framing the rest hangs on. No abstract point by itself.
- **Hand-off to Whitney:** "So here is a burrito chain's chatbot on a real
  cluster. It is wide open right now. Let's see what the room can do to it."

### Segment 2: Wide-open start, the audience hacks it live (5 min). Owner: Whitney leads, Michael on the cost counter.

Put `attackme.agenticburn.com` on screen and give the room the URL. Say the one
housekeeping line first: the prompts they send show on screen, so nothing personal
in the box (the feed is `STREAM_PROMPTS`, masked by a wordlist, so the disclosure
is what makes projecting it fair). Then let them attack from their phones while
Whitney drives a couple of asks herself to prove the bot is a working burrito-chain
bot before it misbehaves.

- BurritoBot answers as the burrito chain (menu, an order), then the room coaxes it
  off the rails: the weird off-topic asks the abstract invites, and the leak of the
  fictional CEO's record. Prompts and verified results are on `/brief` (Community
  phase) and in `challenges/PROMPT-CATALOG.md`.
- **Michael on cost:** keep the live cost counter on the bot visible. Narrate it
  climbing while the room hammers it. "Nothing crashed, nothing is red, and the
  bill is the attack." This is the denial-of-wallet point, delivered as narration
  rather than a separate before/after beat (C4 is cut as its own segment to protect
  time; see the cut table).
- **Challenges shown live:** C5 (the record leak) as the headline audience beat.
- **Delivers:** point 1 (a burrito-chain bot), point 4 (starts wide open, audience
  hacks it live), and the live half of point 9 (weirdest off-topic question over
  the venue network). The recorded fallback half of point 9 is the Night Before
  step below.
- **Hand-off to Michael:** "Before we fix any of that, look at what they are
  attacking."

### Segment 3: The platform you are attacking, the full IDP (3 min). Owner: Michael.

Switch to the admin cluster. Show that this is a real internal developer platform,
not a chatbot on a laptop.

```bash
# on the admin cluster terminal
kubectl get applications -n argocd      # the app-of-apps and its components
kubectl get pods -A | head -40          # what that looks like running
```

Name the layers from the stack walkthrough table (agent, admission, network,
runtime, AI guardrails, observability, delivery) and land the one line: one column
is the developer's, everything else is the platform team's, and the platform team's
column is what actually stops an agent.

- **Delivers:** point 3 (deployed on a full IDP). Say the governance line the
  accurate way per `docs/ABSTRACT.md`: a CNCF floor, AAIF agent protocols, and a
  guardrail layer with no foundation behind it. Do not claim a fixed component
  count; say "about forty Argo applications" or leave the number out.
- **Hand-off to Whitney:** "Same asks the room just landed, now on the cluster with
  the controls a mature team already runs."

### Segment 4: The Kubernetes layers block it (6 min). Owner: Whitney narrates, Michael names each control.

Re-run on the admin cluster the asks that just worked on the community bot. The
Kubernetes controls are already armed here, so each one is blocked, each by a
different control. This is the community-versus-admin contrast, and it is the
abstract's "the Kubernetes security layers you should already have."

- C1 exfiltrate the customer data, blocked by the egress NetworkPolicy. Keep the
  beacon view on screen so the room sees the count not move.
- C2 deploy the villain image, denied at admission by the Kyverno registry
  allow-list. Read the deny message aloud. Watch for the agent silently
  substituting a permitted image and claiming success (check the running image
  before saying the wall failed; it is a better story when it lies).
- C3 read the recipe off the filesystem, blocked inline in the kernel by KubeArmor
  with Falco alerting. One command shows prevention and detection doing different
  jobs.
- If a prompt wanders, drive that beat's `challenges/<beat>/fallback.*.sh` so the
  control is what is proven, not the model's mood. Do not debug live.
- **Michael's thread:** the damage was stopped, but the cost counter still moved on
  the community side, because the request reached the model before admission
  refused it. Admission is the last mile and the most expensive.
- **Challenges shown live:** C1, C2, C3. **Cut here:** C4 as its own before/after
  (covered as cost narration in segment 2) and C8 (see the cut table).
- **Delivers:** point 5 (Kubernetes layers), shown before the LLM layer, which is
  the order the abstract promises.
- **Hand-off to Michael:** "The infra floor is necessary and not sufficient. The
  agent can still be talked into things no NetworkPolicy sees. That is the next
  layer."

### Segment 5: LLM-specific guardrails, turned on live (7 min). Owner: Michael and Whitney.

On the admin cluster the AI guardrails start off. Turn them on one at a time from
the terminal and re-run the same ask each time, so the room watches one platform
setting change the outcome. Prompts and verified both-direction results are on
`/brief` and in `challenges/PROMPT-CATALOG.md`.

- C6 prompt injection hidden in a support ticket. Before: it rides in and spends
  tokens. `guard-input-on`: blocked upstream at zero tokens, the cost counter does
  not move. This is the pre-inference analysis. Say "deterministic" only for the
  block-list, never for the classifier.
- C5 the agent leaks a secret in its response. `guard-output-on`: the value comes
  back redacted. This is analysis on the way out.
- C7 the under-protected MCP server. A poisoned tool description chains the agent
  into a rogue tool it was never asked to use. `guard-mcp-on`: the tool is gone
  from the allow-list and the call cannot happen.
- Say the C6-versus-C7 line out loud after C7 (it is on `/brief`): both are the
  same class of attack stopped two different ways. One talks the model out of it;
  the other lets the model be fully persuaded and finds the capability gone. Only
  the second still holds when the next model is more persuadable.
- **Challenges shown live:** C6, C5, C7.
- **Delivers:** point 2 (the under-protected MCP server, via C7) and point 6 (pre-
  and mid-inference prompt analysis). See the open question on what "mid-inference"
  means: the guard-proxy scans the request and the response at the gateway, and
  whether a gateway response scan counts as mid-inference is an unsettled scope call
  (#456, talks-knowledge#29). Do not claim streaming or token-by-token analysis
  unless that is built and confirmed by the day.
- **Hand-off to Whitney:** "Every one of those fired where you can see it."

### Segment 6: GenAI observability on stage (3 min). Owner: Whitney.

Open Agent Observability in the shared Datadog org. Show the agent's input, output,
and tool calls for the beats just run: the injection that was blocked at zero
tokens, the output that came back redacted, the rogue MCP tool that never fired.
The observability is the lens that proves each guardrail did its job.

- Rehearse the search. Finding one trace by name in front of a room is the part
  that goes wrong; have one located before the session starts.
- **Delivers:** point 7 (good GenAI observability practices). This segment depends
  on a live Datadog org pool, which is not set up yet (#454); see the open
  questions. If no pool is live by the day, fall back to Grafana or Tempo and say
  which; do not leave point 7 unshown.
- **Hand-off to Michael:** "And after all of that, what is the bot supposed to do?"

### Segment 7: The bot sells burritos only, then close (4 min). Owner: Michael and Whitney.

Turn on the on-topic guardrail and re-send the weirdest off-topic asks from segment
2 (the salsa-dance, hot-dog-party, karaoke kind). With it on, BurritoBot answers
menu, hours and locations and redirects everything else back to the menu, politely.
This is the abstract's ending: by the end the chatbot is selling burritos, nothing
more.

- **Delivers:** point 8 (ends selling burritos only). The on-topic guardrail does
  not exist in this repo yet (#455 is open and MISSING); see the open questions.
  Until it is built and verified, this segment cannot be shown live, and the talk
  cannot deliver point 8 as written. This is the single biggest content risk in the
  cut.
- **The close (Michael, the last ~2 min):** every attack today was a plausible
  request, not an exploit. The controls that stopped them were an egress policy, an
  admission rule, a kernel block, a tool allow-list, a budget, and a guardrail layer
  on top. Boring, countable, owned by the platform team, and they work whether or
  not the model cooperates. Most of what an agent tries is already handled by tools
  teams run today; the small, strange remainder is the part agents change, and that
  is where the AI guardrails sit. Point at the repo as the Monday-morning takeaway.

---

## Abstract points to segments

The nine points are the accepted KubeCon abstract's checklist, transcribed in
talks-knowledge `talks/2026-10-16_hard-dated-commitments.md` section 1 against the
verbatim text in `abstracts/recovered/sessionize-public-profile.md` section 5.

| # | The abstract says | Segment | Delivered by the cut? |
|---|---|---|---|
| 1 | A chatbot for a fictional burrito chain | 2 (bot answers as the chain), 7 (sells burritos) | Yes, once #455 lands for point 8 |
| 2 | Connected to an under-protected MCP server | 5 (C7) | Yes |
| 3 | Deployed on a full IDP | 3 (the tour) | Yes |
| 4 | Starts wide open, the audience hacks it live | 2 (community bot, phones) | Yes |
| 5 | The Kubernetes security layers you should already have | 4 (C1, C2, C3), before the LLM layer | Yes |
| 6 | LLM-specific guardrails, pre- and mid-inference prompt analysis | 5 (C6 pre, C5 and C7 at the gateway) | Partial. "Mid-inference" is an unsettled scope call (open question) |
| 7 | Good GenAI observability practices | 6 (Datadog traces) | At risk. Needs a live Datadog pool (#454), not yet set up |
| 8 | By the end the chatbot is selling burritos, nothing more | 7 (on-topic guardrail) | **At risk.** The on-topic guardrail does not exist yet (#455 MISSING) |
| 9 | "Bring your weirdest off-topic question" (live input, recorded fallback) | 2 (live, over the venue network) + Night Before (recorded fallback, #452) | Live half yes; recorded half needs #452 built |

Points the cut cannot deliver today, marked so they are not presented as ready:
point 8 (no on-topic guardrail yet, #455), point 7 (no live Datadog pool yet,
#454), point 6 "mid-inference" (unsettled definition, #456 and talks-knowledge#29),
and the recorded half of point 9 (#452). The live-input half of point 9 and all of
points 1 through 5 are deliverable on the platform as built.

## Challenges shown live, and challenges cut

| Challenge | In the cut? | Why |
|---|---|---|
| C1 exfiltrate customer data (NetworkPolicy) | Shown, segment 4 | Cleanest Kubernetes-egress block; carries point 5 |
| C2 villain image (Kyverno admission) | Shown, segment 4 | Admission-control block, a different control from C1 |
| C3 recipe on the filesystem (KubeArmor, Falco) | Shown, segment 4 | Prevention-versus-detection in one command |
| C4 denial-of-wallet (budget cap) | Narrated only, segment 2 | The cost-counter story lands as live narration during the wide-open burn; a full before/after beat costs minutes the 30-minute slot does not have. The budget cap stays armed and can be shown in Q&A |
| C5 secret leak (output guard) | Shown, segments 2 and 5 | The audience beat and the output-guard toggle |
| C6 prompt injection (input guard) | Shown, segment 5 | Pre-inference analysis, point 6 |
| C7 rogue MCP tool (tool allow-list) | Shown, segment 5 | The under-protected MCP server, point 2 |
| C8 service-account token theft (scoped Role) | **Cut** | The strongest hands-on beat in the workshop, but it is terminal-driven RBAC work the audience cannot do from a phone, and it needs minutes this slot does not have. It belongs to the 2-hour format |

---

## Night Before

Provision the evening before, never as the room fills. Portland proved this; a
last-minute bring-up is how two of twenty consoles were still answering four hours
before doors (`notes/DEBRIEF.md` in the Portland repo).

Run these from `infra/terraform/fleet/`, read the output, and repair anything that
is merely slow rather than rebuilding:

- [ ] **Platform up on AWS.** Bring up the roster (the community cluster and both
  admin clusters) on the KubeCon delivery accounts and region:
  `./fleet.sh instructors up all`. The attendee pool is not provisioned for this
  session. Delivery identity (which AWS accounts, region, and the `event` tag) is
  settled on #454; confirm it is the KubeCon value, not the Portland one, before
  bringing anything up.
- [ ] **Accounts and quota resolve:** `./fleet.sh preflight 1`.
- [ ] **Hostnames serve over HTTPS and websocket:**
  `./fleet.sh check-tls attackme.agenticburn.com michael-admin.agenticburn.com whitney-admin.agenticburn.com`.
- [ ] **Clusters healthy:** `./fleet.sh converge instructors`.
- [ ] **The pinned model answers in the delivery region.** From the repo root:
  `python3 verify/model_pin_check.py --profile accen-dev --region us-west-2`. It
  reads the pin from `gitops/ai-layer/resources.yaml` (Nova Pro,
  `us.amazon.nova-pro-v1:0`, with `MODEL_TIER` `nova`), then checks against live
  Bedrock that the inference profile is ACTIVE, that the model is not Legacy or
  scheduled to go Legacy before 2026-11-12, that one Converse call answers, and that
  the cross-region quota covers the room. It must end `MODEL PIN GREEN`; anything
  else, stop and fix the pin before the day (#453). Then send one throwaway order to
  each bot and confirm it answers with a menu, not an empty reply (an empty reply
  means the MCP servers are down; see the workshop runbook's failure playbook).
- [ ] **Guard start state on the admin cluster:** run `guards-off` from its terminal
  so the AI guardrails start off and the live toggles in segment 5 are real.
- [ ] **Datadog org** for the observability segment is loaded and the fleet monitors
  are applied (#454; `./fleet.sh monitors --apply` once the pool is loaded). If no
  pool is live, decide the Grafana or Tempo fallback for segment 6 and say so on the
  day.
- [ ] **Recorded fallback proven once (#452).** The replayable prompt set and the
  per-segment videos and screenshots deck must exist and be rehearsed once, so a
  dead venue network does not end the session. The repo paths for these are not
  built yet; see the open questions. The rollback step below names them once they
  exist.
- [ ] **Audience path and phones (#450, #451).** Confirm the room's rate limit and
  timeouts are sized for a ballroom and that the page, the projector QR, and the
  Feedback link work on a real iPhone and a real Android phone on venue-like
  Wi-Fi and on cellular. Fill in `facilitation/kubecon-na-2026-phone-check.md`.
  The QR on the slide is `facilitation/kubecon-na-2026-audience-qr.svg`, and the
  Feedback button opens the session survey, both set in
  `gitops/ai-layer/web/event.js`.

## Rollback on the day

1. A prompt wanders on a shown beat: run that beat's
   `challenges/<beat>/fallback.*.sh` so the guardrail is what is proven. Do not
   debug the model live.
2. The venue network cannot carry the room: the presenters drive the audience
   beat themselves from the admin cluster and the room watches, rather than hacking
   from phones.
3. Nothing live works at all: play the recorded fallback (#452). Name the exact
   path to the segment videos and the screenshots deck here once #452 has built them;
   it is an open question today (see below).
4. Any beat over its time budget by half: cut it to a sentence and move on. The room
   never watches unrehearsed troubleshooting.

## Teardown

The clusters cost real money after the session and are promised to nobody once it
ends. Tear down within a few hours of the session close, the way Portland did (479
hosts at peak, down to 1 within three hours).

- Full teardown, account-aware, ending in a zero-cost audit:
  `teardown/teardown.sh` (a thin wrapper over `fleet.sh down all`, which destroys
  every cluster with state, sweeps leaked load balancers, target groups and volumes,
  destroys each account's lab VPC, and runs `audit-zero`). Pass `--keep-vpc` only if
  a fast rebuild is wanted.
- Confirm nothing billable is left: `infra/terraform/fleet/fleet.sh audit-zero`.
- Sweep any stranded load balancers a failed teardown left behind:
  `infra/terraform/fleet/fleet.sh reap-lbs` (dry run unless `WIB_APPLY=1`).
- The Datadog pool secret is deliberately not destroyed by `down all`; use
  `fleet.sh reap-secrets` only when the pool itself is finished with.
- Record the real spend for the delivery window with
  `teardown/cost-report.sh --start <YYYY-MM-DD> --end <YYYY-MM-DD>` once the `event`
  or `project` cost-allocation tag is activated on the payer account (Portland could
  not, because the tag was never activated; #392 and #454 track it here).

---

## Open questions for Michael and Whitney

These are the things this run-of-show could not settle from a source. They are
written down rather than guessed.

1. **The on-topic guardrail for point 8 does not exist yet (#455).** Segment 7, the
   abstract's ending, cannot be shown live until it is built and verified. Is it
   being built for this delivery, or is point 8 cut with Whitney's agreement (which
   #456 allows)? This is the biggest content risk in the cut.
2. **The recorded fallback is not built yet (#452).** The replayable prompt set, the
   per-segment videos, and the screenshots deck have no repo paths today. The
   rollback step and the Night Before step reference them; they need to exist before
   the cold read, and this file should name their exact paths once they do.
3. **The Datadog pool for segment 6 is not set up (#454).** Whitney is expected to
   set one up the week of 2026-10-26. If it is not live, what is the agreed fallback
   for showing point 7: Grafana, Tempo, or recorded traces?
4. **What "mid-inference" means for point 6 (#456, talks-knowledge#29).** The
   guard-proxy scans request and response at the gateway. Is a gateway response scan
   what the abstract means by mid-inference, or does it mean scanning during
   generation (streaming)? The claim on stage depends on the answer, and streaming
   is not built.
5. **One cluster or two for the before/after.** This plan uses the community cluster
   for the wide-open start and a presenter admin cluster for the guarded half, which
   is the cleanest way to show the Kubernetes-layer contrast (those controls are not
   runtime-toggleable the way the AI guardrails are). Confirm that reading of "one
   demo platform," or say if both halves should run on a single cluster with only the
   AI guardrails toggled.
6. **The model pin and cost counter (#453).** Reconciled: the deployed agent runs
   Nova Pro (`bedrock-nova`, `us.amazon.nova-pro-v1:0`, us-west-2), and
   guard-proxy's `MODEL_TIER` is `nova`, priced at $0.0008 in and $0.0032 out per
   1K tokens. That price matches the AWS price list for us-west-2 (published
   2026-10-16, read 2026-10-24). The Haiku files under `agent/` are pre-GitOps
   copies that nothing applies. The public AWS pages read on 2026-10-24 (the Nova
   Pro model card and Model lifecycle (Legacy)) list Nova Pro as Active, with no
   legacy or end-of-life date. Still open: the live check in the delivery account,
   `python3 verify/model_pin_check.py --profile accen-dev --region us-west-2`, has
   not been run yet. It needs the accen-dev credentials. Record its date and output
   on #453.
7. **The audience rate limit, venue NAT, and timeouts (#450, #451).** Sized for a
   ballroom on one venue Wi-Fi NAT, verified on real phones. Not yet done; needs the
   live platform and two real devices.
8. **The deck (#449, rounds-agenticburn#38).** This file is the beat list the deck is
   cut from. The deck itself is built in `peopleforrester/rounds-agenticburn` and is
   not written against these segments yet.
