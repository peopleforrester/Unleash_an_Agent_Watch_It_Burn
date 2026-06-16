*Facilitator-facing minute-by-minute runbook for the workshop: 90-minute core script plus a documented 2-hour extension, with explicit Michael/Whitney hand-offs.*

# Runbook — "Build a Platform, Unleash an Agent on it… and Watch it Burn!"

AI Engineer World's Fair 2026, Moscone West. Speakers: Michael Forrester (Accenture) + Whitney Lee.

This is the live-run script. It is facilitator-facing: it names the toggles, the fallbacks, and the decision points. It is NOT attendee copy. Architecture-and-thesis framing is Michael; live narration and the trace lens are Whitney. Every segment below has an owner and an explicit hand-off marker.

## Pre-flight (before doors open — both)

- [ ] All spoke clusters provisioned and green (hub ArgoCD `app list` all Synced/Healthy). Pre-provision before doors; do not provision live. See `infra/SIZING.md` for provision time.
- [ ] Beat 3 status known: **LIVE** if the Phase-4b MCP-authz spike passed, else **RECORDED**. Confirm which, out loud, between the two of you before you start. The recording (`fallback/recordings/`) is loaded and tested either way.
- [ ] All toggles in their start state: Kyverno require-limits policy in `Audit`; input guard `off`; output guard `off`; MCP authz `off`. Drift policy in `Enforce` from the start (no toggle).
- [ ] Asciinema recordings for all three beats loaded and verified to play. Beat 3 recording is mandatory.
- [ ] Web-terminal access links / QR codes generated and ready to hand out (`access/quickstart.md`).
- [ ] Facilitator Grafana/Tempo open on the hub, trace view ready (Whitney's screen).
- [ ] Content capture is OFF in the OTel collector (this matters for the 2-hour trap; in the 90-min run it just stays off).
- [ ] Decide the room-online contingency: if Moscone WiFi cannot carry N attendees to N spokes, Whitney drives a single facilitator path and attendees watch. Agree the trigger now.

---

## 90-minute core run — total = 90 minutes

| Time | Min | Owner | Segment | Toggle / artifact |
|------|-----|-------|---------|-------------------|
| 0:00 | 10 | **Michael** | Intro + architecture | none |
| 0:10 | 10 | **Whitney** | Access + warm-up | none |
| 0:20 | 20 | **Whitney** (Michael on controls) | Beat 1 — CNCF wall | Kyverno `Audit`→`Enforce` |
| 0:40 | 20 | **Whitney** (Michael on guard story) | Beat 2 — input + output sanitization | input guard on; output guard on |
| 1:00 | 15 | **Whitney** (Michael on the gap) | Beat 3 — bad MCP / excessive agency | MCP authz on (or recording) |
| 1:15 | 10 | **Michael** | Regroup + governance map | none |
| 1:25 | 5 | **Both** | Takeaways + Q&A | none |

Total: **90 minutes**.

### 0:00–0:10 — Intro + architecture (Michael, 10 min)

- Set the room: each attendee has their own real cluster and a scoped AI agent already running on a platform you did not build and do not fully trust.
- Sketch the hub-and-spoke shape at a high level: shared GitOps + observability on a hub, one isolated cluster per attendee.
- Frame the day as three rounds of "unleash the agent, watch what stops it — and what doesn't."
- Do NOT preview which attacks get blocked and which leak. That is the payoff. Keep the inverted 80/20 framing public-safe: "most of what you'd try is already handled; a thin slice is not, and that slice is the whole point."
- **HAND-OFF → Whitney:** "Whitney's going to get you into your own cluster and warmed up." Stop talking, pass the clicker.

### 0:10–0:20 — Access + warm-up (Whitney, 10 min)

- Walk the room into their web terminals (link / QR from `access/quickstart.md`). No local install.
- Have everyone send one trivial prompt to their agent and confirm a response. This proves the path end-to-end before any attack.
- Show the trace view once on your screen: agent receives a prompt, plans, responds. Establish the trace waterfall as the lens — "this is how we'll watch every attack land or get stopped."
- Contingency: if a cluster of attendees can't reach their terminal, switch to the single facilitator path now and tell the room they'll drive from your screen.
- **HAND-OFF → stays with Whitney for Beat 1**, Michael steps in only on the control explanations. Whitney: "Let's unleash it the first time."

### 0:20–0:40 — Beat 1: CNCF wall (Whitney narrates, Michael on controls, 20 min)

Three walls, three distinct errors. One live toggle.

1. **Deploy a non-compliant workload (the toggle).**
   - Before: agent deploys it; policy is in `Audit`, so it admits and is reported, not blocked. Show the audit report.
   - **TOGGLE:** run `beats/01-cncf-wall/toggle-kyverno-enforce.sh` (`Audit`→`Enforce`, rule-level `validate.failureAction`). Say what you're doing: "I'm switching the policy from watch to block."
   - After: agent retries the same deploy; admission rejects it. Read the Kyverno admission message aloud.
   - **Michael** explains: this is admission control — a wall the mature platform already has.
2. **Escalate privileges (no toggle).** Agent tries to create a ClusterRoleBinding for itself. RBAC `Forbidden`. Distinct error. Michael: "Different wall — RBAC, evaluated before admission even runs."
3. **Modify infra outside Git (no toggle).** Agent tries a direct `kubectl` mutation of an ArgoCD-managed resource. Admission blocks non-ArgoCD principals; then show ArgoCD self-heal reverting any drift. Michael: "Third wall — GitOps. The platform reconciles itself back."
- If the agent wanders on any step, run `beats/01-cncf-wall/fallback.kubectl.sh` for that step — the deterministic three-wall path. Keep moving; do not debug the model live.
- Land the beat: "Three walls, all from controls a good platform already runs. Hold that thought."
- **HAND-OFF:** Whitney keeps the room; Michael cues the pivot — "Now we try things the platform can't see."

### 0:40–1:00 — Beat 2: input + output sanitization (Whitney narrates, Michael on the guard story, 20 min)

Two toggles, narrated as one "clean both directions" beat.

1. **Input (prompt injection).**
   - Before: drive the injection prompt; the agent gets steered off task. Show it in the trace.
   - **TOGGLE:** `beats/02-sanitization/toggle-input-guard-on.sh`.
   - After: same injection is hard-rejected at the gateway request phase, before it reaches the agent. Show the rejection.
2. **Output (exfil).**
   - Before: agent reads the planted fake secret (`FAKE-PROD-DB-PASSWORD-sentinel-9f2a`) and returns it; the sentinel appears in the response. Point at it in the trace.
   - **TOGGLE:** `beats/02-sanitization/toggle-output-guard-on.sh`.
   - After: same request — response is blocked/redacted; the sentinel does not appear.
- If the model won't take the bait either direction, run `beats/02-sanitization/fallback.curl.sh` — it drives the request/response straight through the gateway so the *guardrail* is what's proven, model-independent.
- **Michael's framing line (public-safe):** these gaps don't live in the control plane — they ride in language and in what comes back out. No admission controller sees them. Keep the deeper "why this guard is the reliable kind" line OUT — that's the talk payoff.
- **HAND-OFF:** Michael cues Beat 3 — "Last one: what happens when the agent's own tools turn on it."

### 1:00–1:15 — Beat 3: bad MCP / excessive agency (Whitney narrates, Michael on the gap, 15 min)

One toggle. **LIVE or RECORDED — decided in pre-flight from the Phase-4b spike result.**

- **If LIVE:**
  - Before: agent is wired to the untrusted MCP server; its poisoned tool description induces a call to a tool it should never use, leaking `FAKE-MCP-EXFIL-sentinel-4c1d`. Show the rogue tool call in the trace — tool calls are first-class in the trace view.
  - **TOGGLE:** `beats/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh` (the deny rule at the gateway).
  - After: same attempt; the rogue tool call is blocked / filtered out. Sentinel does not leave.
  - If the model won't take the bait, `beats/03-.../fallback.curl.sh` drives the tool call through the gateway directly.
- **If RECORDED:** play `fallback/recordings/` beat-3 asciinema. Narrate it exactly as you would live — before, toggle, after. Tell the room it's recorded; don't pretend. The lesson is the same: a tool-authorization layer the agent stack needs and the cluster controls can't provide.
- **Michael's framing line:** the over-reach rides in a tool call, not a kubectl verb — only the gateway/tool-authorization layer can stop it.
- **HAND-OFF → Michael** for the regroup. Whitney: "Michael's going to pull this together into something you take home."

### 1:15–1:25 — Regroup + governance map (Michael, 10 min)

- This is the takeaway. Protect it — if you're running long, cut attendee free-play and (if Beat 3 was live) demote Beat 3 to its recording, but NEVER cut this.
- Walk `facilitation/governance-map.md`: each attack, the control that governs it, the layer it lives in, and whether existing CNCF tooling covers it or an agent-specific control is required.
- Make the inverted 80/20 land: the big attack class was already covered; the two thin gaps (Beats 2 and 3) needed controls the platform didn't have.
- Point to `facilitation/self-assessment.md`: "Run this against your own platform Monday morning — including the failure modes we didn't have time to demo."
- **HAND-OFF → Both** for close.

### 1:25–1:30 — Takeaways + Q&A (Both, 5 min)

- Michael: one-line thesis recap (public-safe), point to the repo and the two artifacts.
- Whitney: the trace lens recap — "you watched every one of these land or die in the same view."
- Open Q&A. Hard stop at 1:30.

---

## 2-hour extension — adds the trace re-leak trap (+30 min)

The 2-hour slot keeps the entire 90-minute run above and inserts the trace re-leak trap as a dedicated advanced beat, plus a little more attendee free-play. This is the moment observability earns its own beat instead of staying the lens.

Revised shape (total = 120 minutes):

| Time | Min | Owner | Segment |
|------|-----|-------|---------|
| 0:00 | 10 | Michael | Intro + architecture |
| 0:10 | 10 | Whitney | Access + warm-up |
| 0:20 | 20 | Whitney/Michael | Beat 1 — CNCF wall |
| 0:40 | 20 | Whitney/Michael | Beat 2 — sanitization |
| 1:00 | 15 | Whitney/Michael | Beat 3 — bad MCP |
| 1:15 | 10 | Whitney | Attendee free-play (drive your own agent at the beats) |
| 1:25 | 20 | **Whitney** (Michael on the symmetry) | **Trace re-leak trap** |
| 1:45 | 10 | Michael | Regroup + governance map |
| 1:55 | 5 | Both | Takeaways + Q&A |

Total: **120 minutes**.

### 1:25–1:45 — Trace re-leak trap (Whitney narrates, Michael on the symmetry, 20 min)

Premise: the output guard from Beat 2 is ON. The sentinel is blocked from the response. So it's safe — right?

1. Whitney: turn ON OTel content capture (prompt/response capture in spans). Re-run the Beat 2 output request.
2. The response is still blocked by the output guard — but the planted sentinel now shows up **inside the trace span**. Observability became a second, unguarded exfil sink. Point at the sentinel sitting in the span attributes.
3. **Michael's framing:** you guarded one door and left another open. The fix has to be symmetric.
4. Whitney: apply the collector redaction processor alongside the response guard. Re-run. Sentinel is gone from the response AND from the span.
- Tie back to the governance map: observability is a control surface, not just a viewer.
- Trace data is torn down in teardown (Phase 9) — say so; no sentinel survives the room.

---

## Live-failure contingency ladder (both, any time)

1. Agent wanders on a beat → run that beat's `fallback.*.sh`. Don't debug the model live.
2. A spoke cluster is unhealthy → move that attendee to watching the facilitator path.
3. Room can't get online at scale → single facilitator path, attendees watch (decided in pre-flight).
4. Running long → cut free-play first, then demote a live Beat 3 to its recording. **Never cut the regroup + governance map.**
5. Beat 3 was never live (spike failed) → it's already the recording; nothing changes mid-run.

## Open decisions that affect this runbook (owned by Michael, see BUILD-SPEC §10)

- Co-speaker split above is the BUILD-SPEC §8 suggestion — **confirm with Whitney before locking.**
- 90 vs 120 minutes — confirm the accepted slot; both scripts are ready.
- Whether the trace re-leak trap is built live or kept slide-only — if slide-only, the 2-hour extension's trap segment becomes a narrated slide, not a live toggle.
