*Facilitator-facing minute-by-minute runbook: the 2-hour three-cluster run-of-show, with a compressed 60-minute fallback. Names the toggles, fallbacks, and hand-offs. Not attendee copy.*

# Runbook — "Build a Platform, Unleash an Agent on it... and Watch it Burn!"

AI Engineer World's Fair 2026, Moscone West. Michael Forrester (Accenture) with Whitney Lee.

**Confirmed slot:** Day 1 (Workshop Day), **2:20–4:20pm**, **Track 5**, **2 hours**.
(Public schedule lists Michael solo; Whitney is co-speaker per the accepted abstract — the organizers have been emailed to add her.)

Split: Michael owns architecture, the security thesis, and the cost argument. Whitney owns the live
attack narration, the observability view, and the attendee experience. Every segment has an owner and
a hand-off marker. Keep the deterministic-guardrail point out of spoken copy; it is a talk payoff.

## Pre-flight (before doors — both)

- [ ] Fleet up and green: 3x Cluster 1 (no guardrails), 3x Cluster 2 (CNCF), 2x instructor Cluster 3,
      and the per-attendee Cluster 3s (plus reserve). Argo CD app-of-apps Synced/Healthy. Provision
      before doors; never live.
- [ ] Cost counter visible on the shared screen, reading from the live clusters.
- [ ] Guard start state on Cluster 3: output `off`, input `off`, MCP authz `off`. Guards flip at
      runtime via the guard-proxy `/toggle` endpoint (Argo CD-safe; no restart, counter survives) —
      NOT via `kubectl set env`, which self-heal reverts.
- [ ] MCP-restriction status known: LIVE if the build-spike passed, else RECORDED. Say which, out loud.
- [ ] Attendee access ready: chat UI + browser terminal links / QR (`access/quickstart.md`).
- [ ] Whitney's trace view open (input / output / tool-call dashboard).
- [ ] Room-online contingency agreed: if WiFi can't carry the room, Whitney drives one path; room watches.

---

## 2-hour run — total = 120 minutes (PRIMARY)

| Time | Min | Owner | Segment | Toggle / artifact |
|------|-----|-------|---------|-------------------|
| 0:00 | 10 | **Michael** | Intro + platform tour (the IDP is already built) | none |
| 0:10 | 15 | **Whitney** (Michael on cost) | Cluster 1 — no guardrails (the burn) | rotate spares; cost counter |
| 0:25 | 20 | **Whitney** (Michael on controls) | Cluster 2 — CNCF guardrails block it | none (controls already on) |
| 0:45 | 40 | **Whitney** (Michael on the gaps) | Cluster 3 — your own cluster: guards on + free-play | output → input → MCP via `/toggle` |
| 1:25 | 20 | **Whitney** (Michael on symmetry) | Trace re-leak trap | content-capture on/off; collector redaction |
| 1:45 | 15 | **Both** (Michael leads) | Regroup + governance map + self-assessment + Q&A | none |

Total: **120 minutes**.

### 0:00–0:10 — Intro + platform tour (Michael)

- While the room connects, tour the running IDP: Argo CD, Kyverno, Falco, Prometheus/Grafana/Tempo/Loki,
  cert-manager, External Secrets, Backstage. "You did not build this and you do not fully trust it. It
  is all in the repo. It is yours to take home and stand up with your own coding agent."
- Frame the two hours: turn an AI agent loose on this platform and watch what stops it.
- Public-safe 80/20 line: "most of what you would try is already handled; a thin slice is not, and that
  slice is the whole point." Do not preview which attacks leak.
- **HAND-OFF → Whitney:** "Let's take the guardrails off entirely and see what happens."

### 0:10–0:25 — Cluster 1: no guardrails, the burn (Whitney narrates, Michael on cost)

- Point the room at Cluster 1 via the chat UI only (no kubectl). Let them attack it. With 15 minutes,
  let several people drive and let it get genuinely wrecked.
- The minimal floor keeps it from dying in one prompt, so it burns rather than vanishing. When one
  dies, switch URLs: "that one's gone, here's two."
- **Michael, on the cost counter:** the bill climbed the whole time. Wasted tokens are a denial-of-service.
- **HAND-OFF:** "Same attack, on a platform with the controls a mature team already runs."

### 0:25–0:45 — Cluster 2: CNCF guardrails block it (Whitney narrates, Michael on controls)

- Same destructive attack against Cluster 2. Walk each wall with its distinct error: Kyverno admission
  message, RBAC Forbidden, Argo CD drift block with self-heal reverting the change.
- **Michael:** the damage was stopped, but the cost counter still moved. The request reached the model
  before admission rejected it. Kyverno is the last mile and the most expensive, because by then the
  tokens are already spent.
- Agent wanders → `beats/01-cncf-wall/fallback.kubectl.sh` for that step. Do not debug live.
- **HAND-OFF → Michael:** "Now your own cluster, where you turn on the guardrails built for agents."

### 0:45–1:25 — Cluster 3: your own cluster, guards on + free-play (Whitney narrates, Michael on the gaps)

Each attendee drives their own Cluster 3 (chat UI + terminal). An agent is already running on it. With
40 minutes there is room to demo each guard and let the room try to beat it.

1. **Output sanitization** — before: the agent reads the planted fake secret
   (`FAKE-PROD-DB-PASSWORD-sentinel-9f2a`) and returns it. Toggle on with
   `beats/02-sanitization/toggle-output-guard-on.sh` (runtime `/toggle`): redacted, sentinel gone. The
   same guard blocks a dangerous tool call with a human-in-the-loop stop.
2. **Input sanitization** — before: a destructive request reaches the model, cost ticks up. Toggle on
   with `toggle-input-guard-on.sh`: the block-list catches it before the model, and the cost counter
   flatlines. Security and cost together.
3. **MCP tool restriction** — the agent is wired to an untrusted MCP server whose poisoned tool
   description induces it to call a tool it should not, leaking `FAKE-MCP-EXFIL-sentinel-4c1d`. Toggle on
   with `beats/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh` (the kagent `toolNames` allowlist):
   the rogue tool is not exposed and the call cannot happen. LIVE or RECORDED per pre-flight.
4. **Free-play** — let the room try to defeat each guard on their own cluster. Whitney narrates the
   interesting ones on the trace view.
- Observability is the lens throughout: input, output, and tool calls on the dashboard.
- Model wanders → that beat's `fallback.*.sh` drives the request through the guard so the guardrail is
  what is proven, not the model's mood.
- **HAND-OFF → Whitney:** "One more — the thing you have been trusting all session."

### 1:25–1:45 — Trace re-leak trap (Whitney narrates, Michael on symmetry)

- Output sanitization is on, so the sentinel is blocked from the response. Turn on OTel content capture
  and re-run. The response is still clean, but the sentinel now sits inside the trace span. The
  observability you trusted is a second, unguarded sink.
- **Michael:** you guarded one door and left another open. The fix has to be symmetric.
- Apply the collector redaction processor, re-run: the sentinel is gone from the response and the span.
- Tie to the governance map: observability is a control surface, not just a viewer. Trace data is torn
  down at the end; no sentinel survives the room.

### 1:45–2:00 — Regroup + governance map + self-assessment + Q&A (both, Michael leads)

- Protect this segment. If running long, cut free-play first; never cut this.
- Walk `facilitation/governance-map.md`: each attack, the control that stops it, the layer it sits in,
  and whether existing tooling covers it. Land the 80/20.
- Point to `facilitation/self-assessment.md`: run it against your own platform.
- Close: the repo is theirs; the governance map and self-assessment are the takeaways. Hard stop at 4:20pm.

---

## Compressed 60-minute fallback (if the slot shrinks or you run very long)

| Time | Min | Owner | Segment |
|------|-----|-------|---------|
| 0:00 | 5  | Michael | Intro + platform |
| 0:05 | 10 | Whitney | Cluster 1 — the burn |
| 0:15 | 10 | Whitney/Michael | Cluster 2 — CNCF blocks, cost moves |
| 0:25 | 25 | Whitney/Michael | Cluster 3 — guards on (output → input → MCP) |
| 0:50 | 10 | Both | Regroup + governance map |

Drop the trace re-leak trap and free-play first; protect the regroup.

---

## Live-failure contingency ladder (both, any time)

1. Agent wanders on a step → run that step's `fallback.*.sh`. Do not debug the model live.
2. A Cluster 1 spare dies → switch to the next URL; that is the expected flow.
3. An attendee Cluster 3 gets wrecked → move them to an instructor Cluster 3.
4. Room can't get online at scale → single facilitator path, room watches.
5. Running long → cut free-play, then the trace re-leak trap. Never cut the regroup.

## Open decisions affecting this runbook

- Co-speaker split is the working split — confirm with Whitney; also confirm her schedule listing.
- Whether the trace re-leak trap is built live or kept as a narrated slide.
- Final Claude tier on Bedrock (haiku-4-5 verified) — affects per-attendee cost, not the script.
