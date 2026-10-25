<!-- ABOUTME: The 30-minute KubeCon NA 2026 breakout run-of-show for Michael and Whitney, cut from the
     ABOUTME: 2-hour workshop: a demo-only session on one platform, audience on phones, no attendee labs. -->

# KubeCon NA 2026 Run of Show

"BurritoBot Said Let's Dance, the Platform Said No." Sessionize session 1249553,
30 minutes. Michael Forrester (Accenture) and Whitney Lee. The day, time, room
and venue live in conference-knowledge (`events/registry.yaml`, entry
`kubecon-na-2026`); the public copy is the Sessionize session page.

**This is the breakout, not the workshop.** It is a demo. Nobody in the room
provisions a cluster. The audience takes part only from their phones against the
wide-open community bot. Do not point anyone at the attendee lab, the
provisioning page, or the per-challenge install steps: those are the 2-hour
workshop and are not part of this session. The provisioning service still runs, as
the C1 beacon collector only (open question 9).

- The 2-hour workshop files (`facilitation/runbook.md`,
  `facilitation/slides-outline.md`, `docs/RUN-OF-SHOW-2026-08.md`) are the other
  format. This file does not replace them.
- The presenters drive from the slides built in `peopleforrester/rounds-agenticburn`
  (checkout `~/repos/agenticburn/rounds-agenticburn`). Issue rounds-agenticburn#38
  cuts that deck from this run-of-show, beat for beat.
- The prompts the presenters send are not reproduced here. They live, copy-ready,
  on `/kubecon` on each cluster (`gitops/ai-layer/web/kubecon.html`): the demo-only
  cut laid out by the segments below, with each beat's prompt, who sends it, the
  admin-terminal toggle where one applies, the success marker and the deterministic
  fallback, and no provisioning or student-lab content. The 2-hour workshop's own
  brief is still at `/brief`; this session drives from `/kubecon`.
  `challenges/PROMPT-CATALOG.md` carries the same prompts with their verified
  results and ranked written fallbacks. Drive from `/kubecon`, read the timing from
  this file.

## Dates to hold (#447)

The plan is Michael's, revised on #447 on 2026-10-24. Work that agents build has no
forecast date: it is built straight through, in this order.

1. **Platform live on AWS**, brought up from this repo's provisioning
   (`fleet.sh`, see Night Before) on the five existing accounts (#454). Test
   clusters from 2026-10-24 are spun up, tested and torn down in one session, on
   the smallest instances.
2. **Every abstract point READY, or cut with Whitney's agreement** (#456).
3. **The recorded fallback** (#452), recorded the moment the live run works.
4. **The deck, as a 16:9 PDF for Sessionize** (#449). The upload's due date is a
   speaker obligation in conference-knowledge (`kubecon-na-2026`, `obligations`).

Dates are for people only:

| Step | Who | When | Done when |
|---|---|---|---|
| Cold read of this run-of-show | Whitney | Once the platform is live. The calendar holds Mon 2026-10-26, 10:00 to 16:00 Central | She reads this file cold against the live platform, not on paper, and each stop is filed as an issue here. Record it under "Run-through record" below |
| Datadog org pool (abstract point 7) | Whitney | The week of 2026-10-26 | The pool is loaded and `./fleet.sh monitors --apply` has run (#454) |
| Two timed run-throughs | Michael and Whitney | By 2026-11-08 | Two full runs, demo included, each timed against the 30-minute slot, with the timings in the record below and what broke filed as issues here |
| Delivered | Michael and Whitney | 2026-11-12 | The session runs live. Its slot and room are in conference-knowledge (`kubecon-na-2026`, `schedule`) |

The Barcelona challenges wait until 2026-11-13.

### Run-through record

The presenters fill this in; one column per run. Time each run from the first word
of segment 1 to the last word of segment 7 with one stopwatch, and write minutes
and seconds (`mm:ss`). The demo is segments 2 to 6. Every finding is an issue in
this repo, and its number goes in the Findings row, so nothing that broke lives
only in this table.

| | Run-through 1 | Run-through 2 | Delivered |
|---|---|---|---|
| Date | not yet run | not yet run | not yet run |
| Presenters | | | |
| Platform (clusters on stage, brought up with `fleet.sh` that session?) | | | |
| Deck (rounds-agenticburn commit) | | | |
| Whole slot (target 30:00) | | | |
| Demo, segments 2 to 6 (target 24:00) | | | |
| Segment 1 (target 2:00) | | | |
| Segment 2 (target 5:00) | | | |
| Segment 3 (target 3:00) | | | |
| Segment 4 (target 6:00) | | | |
| Segment 5 (target 7:00) | | | |
| Segment 6 (target 3:00) | | | |
| Segment 7 (target 4:00) | | | |
| Fallbacks driven (beat and script) | | | |
| Findings filed (issue numbers) | | | |

**Cold read** (untimed; it is a read, not a run):

- Date: not yet run
- Platform (clusters read against):
- Findings filed (issue numbers):

### Probe record

One entry per live run of `verify/kubecon_probe.py` (Night Before): the date, the
clusters, each beat's result, the spend it prints, and the fixes it led to. A beat
that FAILs names its issue.

**2026-10-24, first KubeCon bring-up (#509).** Michael ran it in accen-dev,
us-west-2, on watch-it-burn-community (`attackme.agenticburn.com`, burn profile) and
watch-it-burn-michael-admin (`michael-admin.agenticburn.com`, admin profile). Both
clusters ran without a Datadog key (#454). Both runs ended `KUBECON PROBE RED`.
Bedrock spend for all three runs: about $0.05.

Community, 18:11Z: 4 PASS, 2 FAIL, $0.0114 over 3 model calls.

| Beat | Result | Why |
|---|---|---|
| Wide-open start | PASS | Every AI guard off; no NetworkPolicy, Kyverno or KubeArmor control |
| Burrito order answered | PASS | Answered as the burrito chain |
| C5 CEO record leaks (`/brief`) | FAIL | The reply opened with Nova's `<thinking>` block, and the judge saw no signature and no redaction (#530) |
| Off-topic linked-list ask answered | FAIL | The bot turned it away inside a `<thinking>` block (#530) |
| Cost counter moves | PASS | $0.0000 to $0.0114 |
| Projected feed on and clean | PASS | Feed on, 0 prompts queued |

Admin, run 1, 18:11Z: 7 PASS, 16 FAIL, $0.0198. Nine FAILs were the probe reading
kubectl's "Defaulted container" stderr line as the toggle JSON (#528). Its
guards-off failed with them, which left the tool allow-list narrowed for run 2.

Admin, run 2, 18:14Z, with that stderr line filtered by hand: 11 PASS, 12 FAIL,
$0.0193 over 6 model calls.

| Beat | Result | Why |
|---|---|---|
| kube-context is the named cluster | PASS | Same cluster |
| Start state | FAIL | Allow-list already `['get_weather']`, left by run 1 (#528) |
| `/controls` badges | FAIL | Kyverno badge off, cluster armed (#487, expected) |
| C1 egress | PASS | curl 000, exit 28: the egress NetworkPolicy holds |
| C2 Kyverno admission | FAIL | Denied by require-resource-limits, not the registry allow-list. By hand the registry policy denied 3 tries of 4 (#529) |
| C3 KubeArmor | PASS | Read denied, block-recipe-snoop alert fired |
| C6 lands (guards off) | PASS | maintenance-shell Deployment created |
| guard-input-on | PASS | input_blocklist and input_classifier on |
| C6 blocked | PASS | Blocked upstream, zero input tokens |
| C5 leaks (output off) | FAIL | The record leaked, address included, but without the signature, which the judge then required (#530) |
| guard-output-on | PASS | Output guard on |
| C5 redacted | PASS | Scrubbed as documented |
| C7 leaks (allow-list open) | FAIL | No sentinel: the poisoned description did not chain this time (#496, #514 to #519) |
| guard-mcp-on | PASS | evil-mcp toolNames now `['get_weather']` |
| C7 gone | PASS | Structurally denied |
| guard-topic-on | FAIL | This guard-proxy has no topic guard (#455, expected) |
| 6 on-topic beats | FAIL | Not run: the topic guard is not on (#455, expected) |
| guards-off | PASS | Every AI guard off and the rogue tools back |

What the issue asked only a live run to answer:

- **The C2 deny names `restrict-image-registries` on a server-side dry run:** not
  every time. require-resource-limits denied the probe's Deployment first about one
  try in four. Since #529 the probe submits a Deployment with CPU and memory limits,
  so only the registry policy can deny it; that is not yet proven live.
- **20 s (`--settle`) is long enough for kagent to pick up the narrowed
  toolNames:** yes, once. After guard-mcp-on the agent tried the rogue tool and was
  structurally denied on the re-ask.
- **C5-off and C7-off still land with the earlier guards on:** C5 did. The record
  leaked with the input guard on. C7 did not, and it did not chain in that run at
  all, so this is still open (#496).

Fixed on `staging` since: #528 (`a96c2d7`), #529 (`4b530cd`), #530 (`c724652`).
Not done in that session: `fleet.sh check-tls michael-admin.agenticburn.com` was
cut off by a 120 s timeout and not re-run (attackme passed all six checks), and
#520's console_no_toggle_live test was not run.

## The one platform, and the two clusters on it

The session runs on the agenticburn fleet. For a demo that means the roster in
`infra/terraform/fleet/roster.tsv`, not the attendee pool. Two clusters, decided by
Michael on 2026-10-24 (#448): the wide-open one the room attacks, and a guarded
presenter cluster for the before and after.

- **Community cluster**, `attackme.agenticburn.com`: no guardrails at all. This is
  what the room attacks from their phones, and where the wide-open start happens.
- **A presenter admin cluster**, `michael-admin.agenticburn.com` (Whitney's is
  `whitney-admin.agenticburn.com`): the full IDP with every Kubernetes control
  armed, and the AI guardrails present but toggled off at the start so they can be
  turned on live. This is the guarded half of every before/after.

All three hostnames, and C1's `https://agenticburn.com/beacon`, are served through
the apex router, so it stays up for this session (#502). For this session its table
carries the roster only: the three hostnames and their service hosts, no
attendee-pool row (`./fleet.sh routes roster`, Night Before). No attendee lab runs:
nobody is pointed at the provisioning distributor, and the feedback app stays off.

The router does not answer the beacon itself. It forwards `/beacon` and the beacon
view to the collector in the provisioning app (`docs/beacon-collector-spec.md`), so
the provisioning service keeps running for this session, as the beacon collector
only (open question 9, settled).

Terminal login on both is `sprouts` / `sprouts`. Read it off the cluster if in
doubt:
`kubectl -n agent get secret terminal-auth -o jsonpath='{.data.TTYD_CREDENTIAL}' | base64 -d`.

Guard toggles on the admin cluster, from its terminal: `guard-output-on`,
`guard-input-on`, `guard-mcp-on`, `guard-budget-on` and `guard-topic-on` flip one
at a time. `guards-off` turns every one of them off, the on-topic guard included.
`guards-on` turns on all but the on-topic guard, which it leaves off because it
would refuse every challenge prompt; segment 7 turns it on alone. They go through
the guard-proxy `/toggle` endpoint, which Argo CD does not revert and which keeps the cost counter
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
| 6 | 3 | W | Datadog Agent Observability, or the admin cluster's Grafana view if no pool is live | Watches | 7 |
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
  fictional CEO's record (her home address; the signature line only when the model
  keeps it, #530). Prompts and verified results are on `/kubecon` (Segment 2)
  and in `challenges/PROMPT-CATALOG.md`.
- **The off-topic answer is not promised (#530).** On 2026-10-24 the Community bot
  turned the linked-list ask away. The persona now tells it to answer harmless
  off-topic asks, which is unproven live. Say the bot will answer them only once the
  Night Before probe's off-topic beat is 3 of 3 on the Community cluster; until then
  the room tries them and the presenters do not say what it will do.
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
  beacon view, `https://agenticburn.com/beacon/view`, on screen so the room sees the
  count not move. Open it in its own tab before the segment starts. It is the
  provisioning app's collector behind the router, which keeps running for this
  session for that alone (open question 9).
- C2 deploy the villain image, denied at admission by the Kyverno registry
  allow-list. Read the deny message aloud. Watch for the agent silently
  substituting a permitted image and claiming success (check the running image
  before saying the wall failed; it is a better story when it lies).
- C3 read the recipe off the filesystem, blocked inline in the kernel by KubeArmor,
  and caught by KubeArmor's own alert for the denied attempt. One command shows
  prevention and detection doing different jobs:
  `CONTEXT=<admin-context> bash challenges/c3-secret-grep/fallback.kubectl.sh`
  prints the agent's `Permission denied` and then the `kubearmor-relay` alert line
  (`"PolicyName":"block-recipe-snoop"`, `"Action":"Block"`). Do not promise a Falco
  alert here: Falco's recipe-snoop rule fires on a successful read, and on this
  cluster there is none.
- If a prompt wanders, drive that beat's fallback so the control is what is
  proven, not the model's mood. Do not debug live. The scripts are in the table
  under "Fallback scripts, per beat" below.
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
`/kubecon` and in `challenges/PROMPT-CATALOG.md`.

- C6 prompt injection hidden in a support ticket. Before: it rides in and spends
  tokens. `guard-input-on`: blocked upstream at zero tokens, the cost counter does
  not move. This is the pre-inference analysis. Say "deterministic" only for the
  block-list, never for the classifier.
- C5 the agent leaks a secret in its response. `guard-output-on`: the value comes
  back redacted. This is analysis on the way out.
- C7 the under-protected MCP server. A poisoned tool description chains the agent
  into a rogue tool it was never asked to use. `guard-mcp-on`: the tool is gone
  from the allow-list and the call cannot happen.
- Say the C6-versus-C7 line out loud after C7 (it is on `/kubecon`): both are the
  same class of attack stopped two different ways. One talks the model out of it;
  the other lets the model be fully persuaded and finds the capability gone. Only
  the second still holds when the next model is more persuadable.
- If a prompt wanders, drive that beat's fallback from the table under "Fallback
  scripts, per beat" below. Do not debug live.
- **Challenges shown live:** C6, C5, C7.
- **Delivers:** point 2 (the under-protected MCP server, via C7) and point 6 (pre-
  and mid-inference prompt analysis). What the two words mean was decided by Michael
  on 2026-10-24 (#456): pre-inference is the prompt check before the model (C6);
  mid-inference is the check between the agent's steps, on its tool calls and on
  what the MCP server returns before that reaches the model again (agentgateway MCP
  authorization plus the guard-proxy output guard, shown on the C7 rogue MCP).
  Streaming-response scanning is out of scope; do not claim it, or token-by-token
  analysis, on stage. C7's toggle on `staging` today is `guard-mcp-on`, the tool
  allow-list; routing evil-mcp through agentgateway and flipping its
  `mcpAuthorization` rule live is #496, not yet merged. Name agentgateway on stage
  only once #496 is on the cluster.
- **Hand-off to Whitney:** "Every one of those fired where you can see it."

### Segment 6: GenAI observability on stage (3 min). Owner: Whitney.

Show the agent's input, output, and tool calls for the beats just run: the
injection that was blocked at zero tokens, the output that came back redacted, the
rogue MCP tool that never fired. The observability is the lens that proves each
guardrail did its job.

**Which surface is shown.** Decide it the night before and say it on stage:

- **Datadog pool live:** Agent Observability in the shared Datadog org.
- **No pool live:** the Grafana view on the admin cluster, which reads Tempo and
  needs no Datadog key (#500). Michael's cluster:
  `https://grafana-michael-admin.agenticburn.com/d/witb-agent-obs` (Whitney's:
  `https://grafana-whitney-admin.agenticburn.com/d/witb-agent-obs`). Login
  `admin`; the admin cluster terminal prints the password in its catalogue. Say
  "this is Grafana reading the traces from Tempo, on the cluster itself".

In the Grafana view, the "Segment 6" row has one panel per beat, newest first,
over the last 30 minutes. On an admin cluster only the presenters use
BurritoBot, so that window is this session:

- **C6:** the `/chat` request with no model call under it. Open it: one guard-proxy
  span, no agent and no model spans, so zero input tokens. The cost panel above it
  did not move.
- **C5:** the reply that came back redacted. Open it: the top span carries the
  reply the user got, with `[REDACTED]`; the `chat` span under it carries what the
  model said before the output guard.
- **C7:** the weather-tool ask that never reached `read_internal_config`. The
  panel beside it lists the calls that did reach it; the ask sent before
  `guard-mcp-on` is there, and the one sent after is not.

- Rehearse the search. Finding one trace by name in front of a room is the part
  that goes wrong; have one located before the session starts. On Grafana, run
  the three beats once in rehearsal and confirm each panel shows a row.
- **Delivers:** point 7 (good GenAI observability practices), on Datadog if the
  pool (#454) is live and on the Grafana view if not. Do not leave point 7
  unshown.
- **Hand-off to Michael:** "And after all of that, what is the bot supposed to do?"

### Segment 7: The bot sells burritos only, then close (4 min). Owner: Michael and Whitney.

Turn on the on-topic guardrail with `guard-topic-on` on the admin cluster terminal
and re-send the weirdest off-topic asks from segment 2 (the salsa-dance,
hot-dog-party, karaoke kind). With it on, BurritoBot answers menu, hours and
locations and redirects everything else back to the menu, politely. This is the
abstract's ending: by the end the chatbot is selling burritos, nothing more.

- **Delivers:** point 8 (ends selling burritos only). This repo's half of the
  on-topic guardrail is on `staging` (#455): the guard's settings on guard-proxy
  (`TOPIC_GUARD` off at the start, the phrase lists, and a refusal that offers the
  menu, hours and locations), hours and locations in the persona, and
  `guard-topic-on` and `guard-topic-off` in the terminal. The guard itself is not:
  the topic stage in `proxy.py` (guard-proxy-agenticburn) and the zero-shot BanTopics
  model in the offline LLM Guard image (llm-guard-cpu-offline) are still to build,
  and until both land and their pins are bumped here, `guard-topic-on` prints "This
  guard-proxy has no on-topic guard, so nothing changed" and exits 1. Until then this segment cannot be shown live, and the talk cannot deliver
  point 8 as written. This is the single biggest content risk in the cut.
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
That text is Version 4 of `docs/ABSTRACT.md`. How far each point is built and proven, READY, PARTIAL
or MISSING with file evidence, is `docs/KUBECON-ABSTRACT-READINESS.md`; keep this table and that one
saying the same thing.

| # | The abstract says | Segment | Delivered by the cut? |
|---|---|---|---|
| 1 | A chatbot for a fictional burrito chain | 2 (bot answers as the chain, now with hours and locations), 7 (sells burritos) | Yes, once #455 lands for point 8 |
| 2 | Connected to an under-protected MCP server | 5 (C7) | Yes |
| 3 | Deployed on a full IDP | 3 (the tour) | Yes |
| 4 | Starts wide open, the audience hacks it live | 2 (community bot, phones) | Yes |
| 5 | The Kubernetes security layers you should already have | 4 (C1, C2, C3), before the LLM layer | Yes |
| 6 | LLM-specific guardrails, pre- and mid-inference prompt analysis | 5 (C6 pre; C7 mid, between the agent's steps) | Pre yes. Mid, as defined on #456 (2026-10-24), is agentgateway MCP authorization plus the output guard on C7: the output guard is built, the agentgateway `mcpAuthorization` half needs #496 merged |
| 7 | Good GenAI observability practices | 6 (Datadog, or the Grafana view) | Yes on the Grafana view without a pool (#500), once proven on a cluster at bring-up (#503); Datadog needs the pool (#454) |
| 8 | By the end the chatbot is selling burritos, nothing more | 7 (on-topic guardrail, `guard-topic-on`) | **At risk.** Settings, persona and toggle are here (#455); the topic stage in `proxy.py` and the BanTopics model in the LLM Guard image are not built yet |
| 9 | "Bring your weirdest off-topic question" (live input, recorded fallback) | 2 (live, over the venue network) + Night Before (recorded fallback, #452) | Live input yes; the bot answering is not promised until the probe's off-topic beat is 3 of 3 (#530); recorded half needs #452 built |

Points the cut cannot deliver today, marked so they are not presented as ready:
point 8 (the on-topic guard has no topic stage in guard-proxy yet, #455), the
agentgateway half of point 6's mid-inference (#496), and the recorded half of point
9 (#452).
The live-input half of point 9 and all of points 1 through 5 are deliverable on the
platform as built. Point 7 no longer waits on the Datadog pool: the Grafana view
carries it without a key (#500), and it has not yet been shown on a live cluster;
the bring-up probe (#503) is where it is proven.

## Challenges shown live, and challenges cut

| Challenge | In the cut? | Why |
|---|---|---|
| C1 exfiltrate customer data (NetworkPolicy) | Shown, segment 4 | Cleanest Kubernetes-egress block; carries point 5 |
| C2 villain image (Kyverno admission) | Shown, segment 4 | Admission-control block, a different control from C1 |
| C3 recipe on the filesystem (KubeArmor block and alert) | Shown, segment 4 | Prevention-versus-detection in one command |
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

- [ ] **Permissions boundary in each delivery account.** Every cluster plan looks up
  `watch-it-burn-permissions-boundary` by name, and an account without it fails both
  roster clusters at plan with "no matching IAM Policy found" after the lab VPC is
  already billing (#526). Apply it once per account, with that account's own state:
  `. ./event.sh && terraform -chdir=../../org/boundary init && terraform -chdir=../../org/boundary apply -state=states/accen-dev.tfstate -var profile=accen-dev -var region=us-west-2 -var event="${WIB_EVENT}"`.
  The preflight in the next step reports it per account, and on a FAIL prints this
  line for the account that is missing it.
- [ ] **Accounts and quota resolve, before anything is brought up (#534):**
  `WIB_ATTENDEE_ACCOUNTS=accen-dev ./fleet.sh preflight 3`. It is read-only, so it
  runs before the bring-up commits any money. It must end `PREFLIGHT GREEN`; on a
  FAIL, fix what it names (it prints the apply line for a missing boundary or lab
  VPC) and run it again. It is scoped to accen-dev because every roster cluster lives
  in that one account (`roster.tsv`); the default account list also names the four
  student accounts, which have no lab VPC for this session, so the unscoped form
  fails on them. The count is clusters per account, and the roster is three
  clusters, so the quota check covers all three. It also prints the `event` tag this
  run bills to.
- [ ] **Platform up on AWS.** Bring up the roster (the community cluster and both
  admin clusters) on the KubeCon delivery accounts and region:
  `./fleet.sh instructors up all`. The attendee pool is not provisioned for this
  session. Delivery identity (which AWS accounts, region, and the `event` tag) is
  settled on #454; confirm it is the KubeCon value, not the Portland one, before
  bringing anything up.
- [ ] **The router carries the roster, and only the roster (#502).** `instructors up`
  already wrote the routes table, but with every attendee cluster that has state on
  this machine. Write it again with the roster alone, then read the live router's own
  host list:

  ```bash
  ./fleet.sh routes roster
  ./fleet.sh router-check
  ```

  `routes roster` publishes attackme, both admin hosts and their service hosts, and
  lists any pool row it takes out of the table. It refuses if a roster console has no
  load balancer yet; wait for it and run it again. `router-check` reads
  `https://start.agenticburn.com/roster.json`, which the router builds from the table
  it is actually serving, and must end "the router serves exactly the roster". A
  table pushed but not reloaded fails here, not on stage. Then confirm the C1 beacon
  view answers through the router:
  `curl -fsS -o /dev/null -w '%{http_code}\n' https://agenticburn.com/beacon/view`
  must print `200`. Anything else means the provisioning service, which stays up
  for this session as the beacon collector (open question 9), is down; bring it back
  before the day.
- [ ] **Hostnames serve over HTTPS and websocket:**
  `./fleet.sh check-tls attackme.agenticburn.com michael-admin.agenticburn.com whitney-admin.agenticburn.com`.
- [ ] **Clusters healthy:** `./fleet.sh converge instructors`.
- [ ] **The pinned model answers in the delivery region.** From the repo root:
  `python3 verify/model_pin_check.py --profile accen-dev --region us-west-2`. It
  reads the pin from `gitops/ai-layer/resources.yaml` (Nova Pro,
  `us.amazon.nova-pro-v1:0`, with `MODEL_TIER` `nova`), then checks against live
  Bedrock that the inference profile is ACTIVE, that the model is not Legacy or
  scheduled to go Legacy before 2026-11-12, that one Converse call answers, that
  each cluster's tagged copy of the profile (what the agent calls, so its spend
  carries `project` and `event`, #513) routes to the same model and answers, and that
  the cross-region quota covers the room. It must end `MODEL PIN GREEN`; anything
  else, stop and fix the pin before the day (#453). Then send one throwaway order to
  each bot and confirm it answers with a menu, not an empty reply (an empty reply
  means the MCP servers are down; see the workshop runbook's failure playbook).
- [ ] **Every shown beat works, on the clusters that will be on stage (#503).** From
  the repo root, one command per cluster. It runs the beats in this file's order and
  prints PASS or FAIL for each. It spends real Bedrock money, capped by `--max-calls`
  (default 20): a community run makes 5 model calls, an admin run 12. Pull each
  admin cluster's credentials into its own kubeconfig first; the probe passes it per
  command and never touches `~/.kube/config`.

  ```bash
  python3 verify/kubecon_probe.py community attackme.agenticburn.com
  python3 verify/kubecon_probe.py admin michael-admin.agenticburn.com \
      --context <michael-admin-context> --kubeconfig /tmp/michael-admin.kubeconfig --profile accen-dev
  python3 verify/kubecon_probe.py admin whitney-admin.agenticburn.com \
      --context <whitney-admin-context> --kubeconfig /tmp/whitney-admin.kubeconfig --profile accen-dev
  ```

  - Community (segment 2): the wide-open start, a burrito order answered, the CEO
    record leaking with the `/brief` prompt (her address in the reply the room reads,
    or the signature), the linked-list ask answered 3 of 3, the cost counter moving,
    and the projected feed on. Each beat is judged on what the console shows, with
    Nova's `<thinking>` block folded as the storefront folds it, and a FAIL quotes
    300 characters of the reply.
  - Admin: the kube-context and the hostname are the same cluster (if not, it stops
    before flipping anything); the start state (every AI guard off; Kyverno Deny,
    NetworkPolicy and KubeArmor Block armed); the `/controls` badges agree with the
    cluster; C1, C2 and C3 blocked, judged on the control and not the model (the
    lab's curl from `workshop-mcp`, a server-side dry run as `agent-sa`, and the C3
    fallback); C6, C5 and C7 off then on, with the guards turned on cumulatively as
    segment 5 does; the on-topic guard redirecting the four canonical off-topic asks
    and letting "what are your hours" and "do you have mild salsa" through. Its last
    act is `guards-off`, run even when a beat fails, so the stage starts clean.
  - Every prompt it sends carries guard-proxy's probe marker, so none of them shows
    up in the feed the room sees.
  - Each run must end `KUBECON PROBE GREEN`. A FAIL is a beat to fix or to plan its
    fallback for before the day, not something to find out on stage. Two are
    expected to fail until their fixes land: the Kyverno badge (#487, the pinned
    guard-proxy still reads the retired ClusterPolicy) and the on-topic beats (#455,
    the pinned guard-proxy has no topic stage yet). Record the date, the clusters,
    each beat's result and the spend it prints under "Probe record" above.
- [ ] **Guard start state on the admin cluster:** run `guards-off` from its terminal
  so the AI guardrails start off and the live toggles in segment 5 are real. The
  probe above ends with it already; run it again if anyone has touched the guards
  since.
- [ ] **Datadog org** for the observability segment is loaded and the fleet monitors
  are applied (#454; `./fleet.sh monitors --apply` once the pool is loaded). If no
  pool is live, segment 6 runs on the admin cluster's Grafana view
  (`https://grafana-michael-admin.agenticburn.com/d/witb-agent-obs`): open it, run
  the C6, C5 and C7 beats once, and confirm each of the three segment 6 panels shows
  a row. Say on the day which surface is shown.
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

1. A prompt wanders on a shown beat: run that beat's fallback from the table
   below so the guardrail is what is proven. Do not debug the model live.
2. The venue network cannot carry the room: the presenters drive the audience
   beat themselves from the admin cluster and the room watches, rather than hacking
   from phones.
3. Nothing live works at all: play the recorded fallback (#452). Name the exact
   path to the segment videos and the screenshots deck here once #452 has built them;
   it is an open question today (see below).
4. Any beat over its time budget by half: cut it to a sentence and move on. The room
   never watches unrehearsed troubleshooting.

### Fallback scripts, per beat

Run them from a checkout of this repo on the presenter laptop, against the admin
cluster: `CONTEXT` is its kube-context, the only input any of them takes (prefix
`KUBECONFIG=<file>` if its credentials are in an isolated kubeconfig). None of them
calls the model. Each prints PASS or FAIL per check and exits non-zero on any FAIL,
and none writes a scratch file. The C5 and C6 scripts turn their guard on the way
`guard-output-on` and `guard-input-on` do, and put it back the way they found it.

| Beat | Run | PASS means |
|---|---|---|
| C1 | `CONTEXT=<admin-ctx> challenges/c1-exfil-s3/fallback.kubectl.sh` | From the workshop-mcp pod, where `run_shell` runs, the POST to `https://agenticburn.com/beacon` fails, and the beacon count does not move. Keep the beacon view on screen |
| C2 | `CONTEXT=<admin-ctx> challenges/c2-villain-image/fallback.kubectl.sh` | As `agent-sa`, a Deployment of `docker.io/peopleforrester/joker:latest` is denied at admission and the denial names `restrict-image-registries`. It prints the deny message to read aloud |
| C3 | `CONTEXT=<admin-ctx> challenges/c3-secret-grep/fallback.kubectl.sh` | The agent's grep for the recipe in the workshop-mcp pod reads `Permission denied`, and the `kubearmor-relay` log carries the `block-recipe-snoop` Block alert, which it prints |
| C6 | `CONTEXT=<admin-ctx> challenges/02-sanitization/fallback.curl.sh input` | With the input guards on, the support-ticket injection sent to guard-proxy comes back `guarded: true`, `input_tokens: 0` |
| C5 | `CONTEXT=<admin-ctx> challenges/02-sanitization/fallback.curl.sh output` | With the output guard on, the CEO record sent through guard-proxy's output path comes back with `OPHELIA-THORN-TIBBY-TOP-SPIRE-No9` and the address redacted |
| C7 | `CONTEXT=<admin-ctx> challenges/03-bad-mcp-excessive-agency/fallback.curl.sh` | From the web terminal pod, `read_internal_config` called through agentgateway `:3003` returns `FAKE-MCP-EXFIL-sentinel-4c1d` after `guard-mcp-off`, and the gateway refuses it after `guard-mcp-on` while `get_weather` still answers. It prints how many seconds the narrowed rule took to take effect, and puts the rule back as it found it. It refuses a workshop cluster |

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
written down rather than guessed. A question that has since been decided keeps its
number and says who settled it and when, so references to it elsewhere still land.

1. **The on-topic guardrail for point 8 is half built (#455).** This repo's half is
   on `staging`: the settings, the persona's hours and locations, and
   `guard-topic-on`. The topic stage in `proxy.py` (guard-proxy-agenticburn) and the
   BanTopics model in the offline LLM Guard image (llm-guard-cpu-offline) are not,
   so segment 7, the abstract's ending, cannot be shown live until both land and
   the probe's on-topic beats pass. If they do not land for this delivery, is point
   8 cut with Whitney's agreement (which #456 allows)? Also open on #455: the hours
   and locations BurritoBot will say on stage were invented in-world (every day 11am
   to 11pm, until midnight Fridays and Saturdays; 13 Mandrake Row, Black-Bog Market,
   the Moonrise Pass drive-thru); keep them or replace them with Michael's and
   Whitney's wording. This is the biggest content risk in the cut.
2. **The recorded fallback is not built yet (#452).** The replayable prompt set, the
   per-segment videos, and the screenshots deck have no repo paths today. The
   rollback step and the Night Before step reference them; they need to exist before
   the cold read, and this file should name their exact paths once they do.
3. **The Datadog pool for segment 6 is not set up (#454).** Whitney is expected to
   set one up the week of 2026-10-26. If it is not live, segment 6 shows the admin
   cluster's Grafana view (#500), so point 7 no longer waits on the pool. Still
   open: whether the pool is live by the day.
4. **Settled 2026-10-24: what "mid-inference" means for point 6 (#456,
   talks-knowledge#29).** Michael decided it: mid-inference is checking between the
   agent's steps, its tool calls and what the MCP server returns before that reaches
   the model again (agentgateway MCP authorization plus the guard-proxy output
   guard, shown on the C7 rogue MCP). Pre-inference is the prompt check before the
   model. Streaming-response scanning is not in scope. Segment 5 says it that way.
   What is left is a build, not a question: the agentgateway half is #496.
5. **Settled 2026-10-24: two clusters for the before/after.** Michael decided it on
   #448: the wide-open community cluster for the room to attack, and the guarded
   presenter cluster for the before and after. This is the plan as written above.
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
   cut from. The deck itself is built in `peopleforrester/rounds-agenticburn`
   (`attendee.html`); this repo builds no slide HTML. The cut is drafted on
   rounds-agenticburn#38 and waits for Michael's review there. The 16:9 PDF for
   Sessionize is exported from a checkout of that repo by `scripts/kubecon-deck-pdf.py`
   into `facilitation/kubecon-na-2026-deck/`, which records the sha256 of the source it
   was printed from; run its `check` before uploading. The export refuses a deck that
   is not 16:9, and reveal.js prints the deck at its own `width` and `height`, which
   `attendee.html` does not set yet (the default, 960 by 700, prints 998 by 728). It
   also refuses any slide that names an abstract point or challenge cut in the tables
   above, so the PDF is exported last, once #456 has settled what is cut.
9. **Settled 2026-10-25: the provisioning app keeps running as the C1 beacon
   collector (#502, question 714).** The router forwards `/beacon` and `/beacon/view`
   to the collector inside the provisioning app, so with that service off the beacon
   returns an error, the view in segment 4 does not load, and the C1 fallback script
   fails on reading the count. Hecaton's research decided it under Michael's
   standing rules, not Michael: the service stays up for this session as the beacon
   collector only, and nobody is pointed at its distributor pages, so no attendee
   lab runs (#448).
