*Facilitator-facing minute-by-minute runbook: the 2-hour three-cluster run-of-show, with a compressed 60-minute fallback. Names the toggles, fallbacks, and hand-offs. Not attendee copy.*

# Runbook, "Build a Platform, Unleash an Agent on it... and Watch it Burn!"

AI Engineer World's Fair 2026, Moscone West. Michael Forrester (Accenture) with Whitney Lee.

**Confirmed slot:** Day 1 (Workshop Day), **2:20–4:20pm**, **Track 5**, **2 hours**.
(Public schedule lists Michael solo; Whitney is co-speaker per the accepted abstract, the organizers have been emailed to add her.)

Split: Michael owns architecture, the security thesis, and the cost argument. Whitney owns the live
attack narration, the observability view, and the attendee experience. Every segment has an owner and
a hand-off marker. Keep the deterministic-guardrail point out of spoken copy; it is a talk payoff.

## Pre-flight (before doors, both)

- [ ] Fleet up and green: 3x Cluster 1 live + ~10 disposable spares (no guardrails, no floor, die in
      one prompt), 3x Cluster 2 (CNCF), 3x instructor Cluster 3 (one per model tier: Haiku/Sonnet/Opus,
      for the optional closing demo), and the per-attendee Cluster 3s (plus reserve). Argo CD
      app-of-apps Synced/Healthy. Provision before doors; never live.
- [ ] If running the optional closing demo: the 3 instructor clusters are pinned to their tiers (verified
      inference-profile ids), guards OFF, on adjacent screens. If not running it, they are the
      follow-along copies as before.
- [ ] Cost counter visible on the shared screen, reading from the live clusters.
- [ ] Guard start state on Cluster 3: output `off`, input `off`, MCP authz `off`. Guards flip at
      runtime via the guard-proxy `/toggle` endpoint (Argo CD-safe; no restart, counter survives) , 
      NOT via `kubectl set env`, which self-heal reverts.
- [ ] MCP-restriction status known: LIVE if the build-spike passed, else RECORDED. Say which, out loud.
- [ ] Attendee access ready: chat UI + browser terminal links / QR (`access/quickstart.md`).
- [ ] Whitney's trace view open (input / output / tool-call dashboard).
- [ ] Room-online contingency agreed: if WiFi can't carry the room, Whitney drives one path; room watches.

---

## 2-hour run, total = 120 minutes (PRIMARY)

| Time | Min | Owner | Segment | Toggle / artifact |
|------|-----|-------|---------|-------------------|
| 0:00 | 10 | **Michael** | Intro + platform tour (the IDP is already built) | none |
| 0:10 | 15 | **Whitney** (Michael on cost) | Cluster 1, no guardrails (dies fast, rotate spares) | rotate ~10 spares; cost counter |
| 0:25 | 20 | **Whitney** (Michael on controls) | Cluster 2, CNCF guardrails block it | none (controls already on) |
| 0:45 | 45 | **Whitney** (Michael on the gaps) | Cluster 3, your own cluster: guards on + free-play | output → input (2-stage) → MCP via `/toggle` |
| 1:30 | 30 | **Both** (Michael leads) | Regroup + governance map + self-assessment + Q&A | none |

Total: **120 minutes**.

> **Optional beats (not rows):** the model-tier closing demo (~8 to 10 min) and the trace re-leak trap
> (~15 min) both run inside the Cluster 3 / free-play window if time allows. Cut order when running
> long: closing demo first, then the trace re-leak trap, then free-play. Never cut the regroup.
> Dedicated sections below.

### 0:00–0:10, Intro + platform tour (Michael)

- **Reveal-style (Whitney):** tour the MINIMAL, guards-OFF platform here. Show Argo CD + the running
  apps + the telemetry view (Datadog primary, Grafana fallback), and note "it is all in the repo, take
  it home." Do NOT explain the whole security suite now. The CNCF security projects (Kyverno enforce,
  Falco, NetworkPolicy, ESO, image signing) get introduced WHEN they turn on at Cluster 2.
- Frame the two hours: turn an AI agent loose on this platform and watch what stops it.
- Public-safe 80/20 line: "most of what you would try is already handled; a thin slice is not, and that
  slice is the whole point." Do not preview which attacks leak.
- **HAND-OFF → Whitney:** "It is wide open right now. Let's see what happens."

### 0:10–0:25, Cluster 1: no guardrails, the burn (Whitney narrates, Michael on cost)

- Point the room at Cluster 1 via the chat UI only (no kubectl). Let them attack it.
- There is no floor and no admission control on Cluster 1, so a single destructive prompt can kill it.
  That is the point: it dies fast. Over the 15 minutes let several people each one-shot a fresh spare;
  as each dies, rotate to the next of ~10 spare URLs from the SSH session: "that one's gone, here's two."
- **Michael, on the cost counter:** the bill climbed the whole time. Wasted tokens are a denial-of-service.
- **HAND-OFF:** "Same attack, on a platform with the controls a mature team already runs."

### 0:25–0:45, Cluster 2: CNCF guardrails block it (Whitney narrates, Michael on controls)

- **CNCF security tour, now that they are ON (Whitney presents some):** introduce the projects as the
  room meets them here, not in the intro: Kyverno (admission), Falco (runtime), NetworkPolicy,
  External Secrets, image signing / Harbor, and (planned) a service mesh for mTLS + SPIFFE/SPIRE
  identity feeding Kyverno cluster policy. Keep it to the ones actually enabled on Cluster 2.
- Same destructive attack against Cluster 2. Walk each wall with its distinct error: Kyverno admission
  message, RBAC Forbidden, Argo CD drift block with self-heal reverting the change.
- **Michael:** the damage was stopped, but the cost counter still moved. The request reached the model
  before admission rejected it. Kyverno is the last mile and the most expensive, because by then the
  tokens are already spent.
- Agent wanders → `beats/01-cncf-wall/fallback.kubectl.sh` for that step. Do not debug live.
- **HAND-OFF → Michael:** "Now your own cluster, where you turn on the guardrails built for agents."

### 0:45–1:30, Cluster 3: your own cluster, guards on + free-play (Whitney narrates, Michael on the gaps)

Each attendee drives their own Cluster 3 (chat UI + terminal). An agent is already running on it. With
45 minutes there is room to demo each guard, run the optional beats if time allows, and let the room try to beat it.

1. **Output sanitization**, before: the agent reads the planted fake secret
   (`FAKE-PROD-DB-PASSWORD-sentinel-9f2a`) and returns it. Toggle on with
   `beats/02-sanitization/toggle-output-guard-on.sh` (runtime `/toggle`): redacted, sentinel gone. The
   same guard blocks a dangerous tool call with a human-in-the-loop stop.
2. **Input sanitization (two stages, enabled progressively)**, before: a destructive request reaches
   the model, cost ticks up. Stage 1, toggle on `toggle-input-guard-on.sh`: the deterministic block-list
   catches "delete" intent before the model and the cost counter flatlines. Stage 2, enable the
   classifier to catch a phrasing the block-list misses (still pre-LLM). Security and cost together.
   Spoken copy: say "deterministic" for the block-list only, never for the classifier.
3. **MCP tool restriction**, the agent is wired to an untrusted MCP server whose poisoned tool
   description induces it to call a tool it should not, leaking `FAKE-MCP-EXFIL-sentinel-4c1d`. Toggle on
   with `beats/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh` (the kagent `toolNames` allowlist):
   the rogue tool is not exposed and the call cannot happen. LIVE or RECORDED per pre-flight.
4. **Free-play**, let the room try to defeat each guard on their own cluster. Whitney narrates the
   interesting ones on the trace view.
- Observability is the lens throughout: input, output, and tool calls on the dashboard.
- Model wanders → that beat's `fallback.*.sh` drives the request through the guard so the guardrail is
  what is proven, not the model's mood.
- **HAND-OFF → Whitney:** "One more, the thing you have been trusting all session."

### OPTIONAL challenges, attendee free-play games (Whitney; cut under time pressure)

Run in the Cluster 3 free-play window if time allows; they make the room compete instead of just watch.

- **ESO / S3 exfil "basketball":** a shared External Secrets Operator (AWS ESO; Vault a possible
  addition) holds one planted secret. The room uses system prompts to get their agent to exfiltrate it
  and post it into a target S3 bucket; first to score wins. Built: `games/eso-s3-exfil/` (manifests,
  plant/hoop/score/teardown scripts, difficulty ladder). verify-at-build: spike each difficulty level live.
- **Challenge ladder (evaluate difficulty per level):** (1) exfiltrate some data, (2) get the agent to
  reveal a secret, (3) break the cluster. Plant funny Kubernetes secrets for flavor. Each level needs a
  spike confirming it behaves as intended on the guards-off vs guards-on state.
- **Partner cluster-breaking (LAST resort only):** trade agent endpoints and try to break each other's
  Cluster 3. Lower priority (attendees must restore); keep it as a final optional challenge, not a beat.

### OPTIONAL closing demo, model-tier comparison on parallel screens (both; cut first if short)

The optional fifth beat. Run it only if the core arc landed and time allows; it is the first thing to
cut when running long, ahead of the trace re-leak trap and free-play. It does not change the thesis, it
reinforces it.

- **Setup:** the 3 instructor Cluster 3s run side by side on adjacent screens, each pinned to a
  different model tier (Haiku 4.5, Sonnet 4.6, Opus 4.8), guards OFF, same jail and same system prompt.
  (Fable 5 is not available; access is suspended.)
- **The beat:** give all three the same "escape your own jail" prompt at once and let the room watch
  the contrast. Haiku barely rattles the bars; Opus is methodical and creative about picking the lock.
  Whitney narrates the three trace views; Michael works the three cost counters.
- **The payoff (two punches):** (1) the frontier cluster's cost counter climbs fastest, a more capable
  model burns more tokens per escape attempt, the same denial-of-service shape at a higher rate;
  (2) the smarter model did NOT change whether Kyverno would block it or whether the output guard
  would catch the sentinel. Capability is orthogonal to governance. The model card claims it resists
  this; the platform is what actually enforces it.
- **Why agent held constant on Clusters 1/2/3:** the spine is a controlled experiment, only the
  guardrail layer changes there, so outcomes are attributable to the controls. Agent and model variety
  belongs HERE, where guardrails are held constant instead.
- **Cost / teardown:** about 8 to 10 minutes, drawn from the Cluster 3 free-play window. Tear the tier
  clusters down with the rest of the fleet right after; the frontier tier is the most expensive to leave up.
- **Fallback:** if a screen wanders, drive its prompt through the same per-beat `fallback.*.sh`. If the
  room cannot watch three screens at once, run Haiku then Opus sequentially on two screens.

### OPTIONAL, Trace re-leak trap (Whitney narrates, Michael on symmetry)

*Optional beat, runs inside the free-play window if time allows. Cut order: after the model-tier closing demo, before free-play. Stays built as a recorded beat regardless.*

- Output sanitization is on, so the sentinel is blocked from the response. Turn on OTel content capture
  and re-run. The response is still clean, but the sentinel now sits inside the trace span. The
  observability you trusted is a second, unguarded sink.
- **Michael:** you guarded one door and left another open. The fix has to be symmetric.
- Apply the collector redaction processor, re-run: the sentinel is gone from the response and the span.
- Tie to the governance map: observability is a control surface, not just a viewer. Trace data is torn
  down at the end; no sentinel survives the room.

### 1:30–2:00, Regroup + governance map + self-assessment + Q&A (both, Michael leads)

- Protect this segment. If running long, cut the optional model-tier closing demo first, then the trace
  re-leak trap, then free-play; never cut this.
- Walk `facilitation/governance-map.md`: each attack, the control that stops it, the layer it sits in,
  and whether existing tooling covers it. Land the 80/20.
- Point to `facilitation/self-assessment.md`: run it against your own platform.
- Close: the repo is theirs; the governance map and self-assessment are the takeaways. Hard stop at 4:20pm.

---

## Compressed 60-minute fallback (if the slot shrinks or you run very long)

| Time | Min | Owner | Segment |
|------|-----|-------|---------|
| 0:00 | 5  | Michael | Intro + platform |
| 0:05 | 10 | Whitney | Cluster 1, the burn |
| 0:15 | 10 | Whitney/Michael | Cluster 2, CNCF blocks, cost moves |
| 0:25 | 25 | Whitney/Michael | Cluster 3, guards on (output → input → MCP) |
| 0:50 | 10 | Both | Regroup + governance map |

The model-tier closing demo is not part of the 60-minute version. Drop the trace re-leak trap and
free-play first; protect the regroup.

---

## Live-failure contingency ladder (both, any time)

1. Agent wanders on a step → run that step's `fallback.*.sh`. Do not debug the model live.
2. A Cluster 1 spare dies → switch to the next URL; that is the expected flow.
3. An attendee Cluster 3 gets wrecked → move them to an instructor Cluster 3.
4. Room can't get online at scale → single facilitator path, room watches.
5. Running long → cut the optional model-tier closing demo first, then the trace re-leak trap, then
   free-play. Never cut the regroup.

## Open decisions affecting this runbook

- Co-speaker split is the working split, confirm with Whitney; also confirm her schedule listing.
- Trace re-leak trap: RESOLVED as an optional beat (cut after the closing demo, before free-play);
  built and kept as a recorded beat regardless of whether it runs live.
- Model tier is a comparison variable, not a single pick: the optional closing demo runs Haiku 4.5,
  Sonnet 4.6, and Opus 4.8 side by side (BUILD-SPEC §2). Per-tier Bedrock access + use-case forms are
  owed by the provisioning project; only Haiku's is submitted.
- Considered and set aside: different agent TYPES on Clusters 1/2/3. Holding the agent constant across
  the three keeps the governance comparison a clean controlled experiment (only the guardrail layer
  changes); agent and model variety lives in the closing demo instead. Revisit if you want it.
