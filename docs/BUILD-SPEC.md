# BUILD-SPEC.md — "Build a Platform, Unleash an Agent on it.... and Watch it Burn!"

AI Engineer World's Fair 2026, San Francisco, Moscone West, Jun 29-Jul 2.
Workshop, 2 hours — confirmed slot: Day 1 (Workshop Day), 2:20–4:20pm, Track 5.
Speakers: Michael Forrester (Accenture) with Whitney Lee (public schedule lists Michael solo; organizers emailed to add Whitney).

Spec rev4, 2026-06-17. Supersedes rev3. Single source of truth for Claude Code. If the live
abstract (`docs/ABSTRACT.md`) and this file disagree on behavior, the abstract wins and this file
is updated to match. The evolved design and decision log behind rev4 is `docs/DESIGN-DECISIONS.md`
(from the Michael+Whitney planning transcript). Live-verification status is in `PROJECT_STATE.md`.

> **rev4 CHANGE vs rev3:** the workshop is now a **2-hour (120-minute), three-cluster spectacle** with
> **cost / wasted-token DoS** as a central theme, not a single aggregate beat in a 90-minute slot.
> rev3's components are all live-verified on EKS and carried forward; the *structure* is new.

---

## 0. How to run this spec

Execution environment: netcup VPS over autossh + tmux; `kubectl`/`eksctl`/`helm`/`aws`/`docker` and
AWS creds live on the server (account <ACCOUNT_ID>, us-west-2). Laptop is a thin client.

The test cluster was torn down to $0 after rev3 verification; everything is reproducible from this
repo (`eksctl create cluster -f infra/test-cluster/cluster.yaml`, then bootstrap + the verified steps
in `PROJECT_STATE.md`). Idempotency rule unchanged: every step safe to re-run (`helm upgrade
--install`, `kubectl apply`, ArgoCD sync). Build-spike rule unchanged: facts confirmed against docs
but not yet a live cluster are tagged **[SPIKE]**; nothing live ships on an unproven assumption.

---

## 1. Objective and success definition

Run a 2-hour workshop where attendees watch an unguarded AI agent destroy a Kubernetes platform,
see the CNCF "80%" stop the same attack (while still burning money), then drive their **own** cluster
and switch on the **agent-specific** guardrails that close the remaining gap. Attendees leave with the
repo, a governance map, and a self-assessment of the failure modes their own platform misses.

"Done" means all of:

- A facilitator **burn-cluster fleet** exists: **3× Cluster 1** (no-guardrails) + **3× Cluster 2**
  (CNCF-only) + **2× instructor Cluster 3** (follow-along), plus a **per-attendee Cluster 3** (own
  cluster) with a few in reserve. Even Cluster 1 has a **minimal floor** so it can't be tanked in a
  single trivial prompt (it should burn over the demo, not instantly), and so follow-along attendees
  can't accidentally nuke the instructor clusters.
- The three-cluster run-of-show plays within the 2-hour slot, proven by the harness in Phase 6.
- A **live Bedrock cost counter** is visible and tells the wasted-token-DoS story.
- The agent-specific guardrails on Cluster 3 (output sanitization → input sanitization → MCP tool
  restriction) each toggle on and visibly change behavior.
- Attendee access is browser-based (chat UI + a web terminal); no local install.
- Pre-recorded fallback exists for every segment.
- Governance map + self-assessment generated and committed.
- Teardown removes all attendee + burn-cluster state and reports the real AWS cost.

---

## 2. The talk this builds — 2-hour run-of-show (120 min; authoritative minute-by-minute in facilitation/runbook.md)

Abstract-true mapping: the abstract's four attacker objectives — deploy a non-compliant workload,
escalate privileges, modify infra outside Git, exfiltrate via the agent's response — are realized as:
the first three are what the **CNCF 80%** blocks (Clusters 1→2); exfil + tool-abuse + bad-MCP are the
**agent-specific gap** closed on Cluster 3. "Some of you fail because governance catches it, some
succeed because it doesn't" is literally the three clusters.

Observability is the headline payoff, not just a lens: every segment is narrated on a live dashboard
showing the **input prompt, the output, and the tool calls**. "Even with no guardrails, seeing the
prompts and tool calls melts their brains."

Suggested shape (the runbook holds the authoritative 2-hour timing) (confirm split with Whitney; Michael = architecture/security/cost thesis,
Whitney = attack narration/observability/attendee experience; hand-offs explicit in `runbook.md`):

- **0–5 — Intro + the IDP is already built.** While attendees connect, show the pre-provisioned IDP
  (ArgoCD, Kyverno, Falco, observability). "This is all in the repo — it's yours, take it home, feed it
  to your coding agent, it deploys a near-production platform."
- **5–15 — Cluster 1, no guardrails (the burn).** Attendees attack via the chat UI only (no kubectl).
  The agent deletes workloads; the cluster dies over the segment (a minimal floor stops a one-shot
  instant kill). The **cost counter** climbs — "wasted tokens are the new DoS." Run 3 instances:
  "here's URL one… someone destroyed it… here's URL two…"
- **15–25 — Cluster 2, CNCF 80% (blocked, but it cost you).** Same attack; Kyverno admission / scoped
  RBAC / ArgoCD-drift block it — no blast radius, the agent can only read. **But the cost counter still
  moved** — "Kyverno is the last mile and the *most expensive*; you already burned GPU + API by the
  time admission denied it."
- **25–50 — Cluster 3, your own cluster + AI guardrails you switch on.** Always-on kagent agent (chaos
  system prompt). Attendees turn guardrails on, in order, watching the dashboard:
  - **Output sanitization** — blocks the dangerous tool call (`kubectl delete`) downstream; human-in-the
    -loop escalation + notification. Catches the badly-scoped-agent mistake.
  - **Input sanitization** — a small **classifier + block-list** catches "delete" intent *before the
    LLM* → the cost counter stops moving. Security **and** cost.
  - **MCP tool restriction** — a malicious/misconfigured MCP server (the "cloud-native clown file" that
    drops a manifest Argo would pick up) is blocked by MCP allowlist / registry / gateway.
  - Threaded through: **AI gateway + caching** for the cost story; "old problems — proxies, firewalls,
    metering, rate limiting — don't change because AI is in the loop."
- **50–60 — Regroup + takeaways.** The governance map (control × layer × CNCF-covers-vs-agent-gap) and
  the self-assessment. Protect this segment; if running long, cut attendee free-play, never the map.

Gamification (optional, time-permitting): stream attendees' system prompts on a side screen — "screen
goes black, someone won" — with sanitization to keep it within code of conduct.

---

## 3. Hard constraints (non-negotiable)

- **Isolation via separate EKS clusters.** Per-attendee Cluster 3 = own EKS cluster (+ a few reserve).
  Facilitator fleet: 3× Cluster 1, 3× Cluster 2, 2× instructor Cluster 3. No vCluster, no namespace-only
  tenancy (rationale unchanged: real privilege-escalation + Falco + admission webhooks + CRDs are cleaner
  on real clusters).
- **A minimal restriction floor on every cluster** so none can be tanked by a single trivial prompt —
  Cluster 1 should burn *over the segment* as a spectacle, not vanish instantly, and follow-along
  attendees must not be able to accidentally destroy the instructor clusters.
- **Scoped agent, never cluster-admin.** kagent runs under a tight ServiceAccount
  (`spec.declarative.deployment.serviceAccountName`); enough RBAC to *reach* admission for the CNCF
  demo, never enough for escalation/GitOps-drift to succeed.
- **Deterministic where the requirement is deterministic.** The output exfil guard's sentinel match is
  an LLM-Guard **`Regex`** scanner (provably model-free; live-verified). The input guard is a
  **classifier + block-list** (model-based; that's acceptable and is the cost-saving point) — never
  described as deterministic in attendee copy. No LLM-as-judge.
- **Obviously fake secrets only.** `FAKE-…-sentinel-…` everywhere; no real credential in any cluster,
  trace, recording, or repo.
- **Cost is instrumented, not estimated.** A live Bedrock cost counter is part of the demo; the real
  number comes from `teardown/cost-report.sh` (Cost Explorer), never a hardcoded figure.
- **No local install for attendees.** Browser chat UI + web terminal. Local kubeconfig is fallback only.
- **Pre-recorded fallback per segment.** Agents wander and clusters die; each segment has a recording.
- **Idempotent + teardownable.** §0 and Phase 9.
- **Abstract truth.** The harness asserts each segment's before/after matches §2.

---

## 4. Design principles (internal — keep out of attendee copy)

- The guardrail layer is deterministic where it can be (output Regex) and model-based where it must be
  (input classifier); the agent is the probabilistic actor. The line is a payoff, not a slide.
- The cost angle is the fresh hook: input sanitization is *cheaper* security because it stops spend
  before the LLM; Kyverno is correct but is the *most expensive* mile. Wasted tokens are a DoS vector.
- Observability is the brain-melter — show input, output, and **tool calls** live. Tool calls are
  first-class in OTel GenAI semconv, which is what makes the rogue MCP call visible.
- OTel content capture is itself an exfil channel (the re-leak trap) — off by default; advanced beat.
- The agent's nondeterminism is a hazard for live demo: every segment has a deterministic fallback so
  the lesson lands even when the model wanders.

---

## 5. Architecture

Versions are live-verified on EKS as of 2026-06-17 (`PROJECT_STATE.md`, `VERSIONS.lock`).

### Cluster topology
- **Per-attendee Cluster 3** — own EKS cluster: full IDP (ArgoCD, Kyverno, Falco, observability) +
  always-on kagent agent + the guard layer + the (initially open) MCP wiring. Attendee drives via chat
  UI and kubectl.
- **Facilitator Cluster 1 (no guardrails) ×3** — only a minimal floor (so it burns over the segment,
  not in one shot); the agent destroys it. Re-provision is ~15 min, so the 3 are pre-provisioned and
  rotated ("URL one's gone, here's two").
- **Facilitator Cluster 2 (CNCF-only) ×3** — Kyverno + RBAC + ArgoCD drift, no AI guardrails; blocks the
  destruction, still shows cost.
- **Instructor Cluster 3 ×2** — follow-along copies of the attendee cluster so a single attendee
  wrecking theirs doesn't break the demonstration.
- Delivery: ArgoCD ApplicationSet (cluster generator) + **sync-waves** order components by dependency.
  **Crossplane was tried and removed** — eksctl/Terraform provisions, ArgoCD takes over.

### Verified component stack (live on EKS)
- **kagent** chart `0.9.7`, CRDs `kagent.dev/v1alpha2`. Agent answers via A2A; per-agent
  `tools[].mcpServer.toolNames` allowlist is the MCP-restriction control. `oci://ghcr.io/kagent-dev/kagent/helm/kagent`.
- **Model: AWS Bedrock**, `us.anthropic.claude-haiku-4-5-20251001-v1:0` (inference profile; base ids
  reject on-demand). Use-case form + model agreements submitted on the account. ModelConfig
  `spec.provider: Bedrock`, `spec.bedrock.region`. Creds via IRSA on the agent SA.
- **Output guard:** LLM Guard (API-server, `laiyer/llm-guard-api:0.3.16`, output `Regex` matching the
  sentinels) behind a small **A2A-aware guard proxy** in front of the agent Service (kagent owns the
  agent pod, so the inspection point is a proxy, not an in-pod sidecar). Live-verified block/redact.
- **Input guard:** request-phase check in the same proxy — a cheap **block-list** (deterministic,
  catches disallowed intent like `delete` *before the LLM* → the cost-saving guard), optionally backed
  by a small classifier. Implementation preference (Michael): the **kagent / CNCF-native** path, not a
  bespoke vLLM→Bedrock classifier; reuse the verified guard-proxy + LLM Guard (open-source) engine.
  Only reach for a separate classifier model if the block-list proves insufficient.
- **MCP restriction:** kagent `toolNames` allowlist (native, confirmed) as primary; MCP
  registry/gateway/AI-gateway as the enterprise story. The malicious MCP shim (`evil-mcp-shim`) is the
  "clown file → Argo" demo.
- **Platform:** ArgoCD `v3.4.3`, Kyverno `v1.18.1` (rule-level `validate.failureAction`), Falco
  `0.44.1`, kube-prometheus-stack `86.2.3`, OTel Collector `v0.154.0` → Tempo/Grafana. EBS CSI driver +
  default gp3 StorageClass are required on every cluster (EKS ships neither).

### Cost metering + AI gateway
- A **live Bedrock cost counter** (per cluster) surfaced on the demo UI — drives the wasted-token-DoS
  story. **[SPIKE]** the exact source (Bedrock invocation logging / token-usage metadata → counter).
- AI gateway + response caching + rate limiting on Cluster 3 for the "old problems still apply" beat.

### Why this shape
Clusters 1→2 are the Kubernetes control plane (the 80%, governed by Kyverno/RBAC/admission). Cluster 3's
guardrails live where the control plane can't see — the agent's response, its tool calls, and its MCP
tools — and the cost counter makes the economic argument the control plane can't make. That is the
80/20 split made physical, with money as the third axis.

---

## 6. Version pinning

Live-verified pins (2026-06-17): kagent chart `0.9.7` / CRD `v1alpha2`; Argo CD `v3.4.3`; Kyverno app
`v1.18.1` / chart `3.8.1`; Falco `0.44.1`; kube-prometheus-stack `86.2.3`; OTel Collector `v0.154.0`;
agentgateway OSS `v1.2.1` (`oci://cr.agentgateway.dev/charts/agentgateway`); LLM Guard
`laiyer/llm-guard-api:0.3.16` (pin a digest); EKS `1.34`; aws-ebs-csi-driver addon + gp3 default SC;
Bedrock model `us.anthropic.claude-haiku-4-5-20251001-v1:0`. vCluster is removed. `VERSIONS.lock` is
authoritative; re-confirm at build.

---

## 7. Repository structure

Existing tree stands (`platform/`, `agent/` incl. `agent/gateway/guard-proxy/`, `beats/`, `verify/`,
`infra/` with `test-cluster/`+`hub-cluster/`+`spoke-cluster/`, `facilitation/`, `research/`, `docs/`,
`teardown/`). rev4 additions to create:
```
  infra/burn-clusters/        # Cluster 1 (no-guardrails) + Cluster 2 (CNCF-only) eksctl configs + spares
  cost/                       # live Bedrock cost-counter service + dashboard wiring
  agent/guard-proxy/          # the verified A2A guard proxy (input classifier + output Regex)
  ui/                         # attendee chat UI + the system-prompt streaming display
```
(`beats/` is recast: Cluster-3 guardrail steps = output-sanitization, input-sanitization, mcp-restriction.)

---

## 8. Build phases

Re-sequenced for rev4. ✅ = already verified live (rev3); reuse, don't rebuild.

- **Phase 0 — Tooling + reproduce base cluster.** ✅ eksctl/helm/kubectl/aws/docker confirmed; cluster
  config + bootstrap + EBS-CSI/gp3 verified. Re-provision a base cluster from `infra/test-cluster/`.
- **Phase 1 — IDP stack.** ✅ ArgoCD/Kyverno/Falco verified; kube-prometheus + OTel→Tempo to finish
  (rev3 kps install wedged — redo lighter, focus Tempo+Grafana trace view).
- **Phase 2 — Cluster fleet.** Build the burn clusters (1 no-guardrails, 2 CNCF-only) + ~10 disposable
  Cluster-1 spares + per-attendee Cluster-3 ApplicationSet (cluster generator, sync-waves). Record
  per-cluster provision time + the fleet cost.
- **Phase 3 — Scoped agent.** ✅ kagent v1alpha2 + Bedrock (haiku-4-5) + scoped RBAC + IRSA verified.
  Re-apply; confirm the chaos system prompt; capture the gen_ai/tool-call spans for the dashboard.
- **Phase 4 — Guard layer.** ✅ output Regex + guard proxy verified. **NEW:** build the input
  **classifier + block-list** (cost-saving) and the output **tool-call block + HITL + notification**;
  resolve the kagent+vLLM→Bedrock-classifier **[SPIKE]**.
- **Phase 4b — MCP restriction.** 🔄 evil-mcp-shim + RemoteMCPServer deployed, tools discovered. Finish:
  BEFORE (rogue tool reachable, leaks) → AFTER (`toolNames` allowlist excludes it). Record the
  before/after; build the "clown file → Argo" variant.
- **Phase 4c — Cost counter.** NEW: live Bedrock spend counter per cluster + on-screen display;
  resolve the metering **[SPIKE]**.
- **Phase 5 — The run-of-show.** Wire the three-cluster flow; write the chat UI + (optional)
  system-prompt streaming; deterministic fallback per segment.
- **Phase 6 — Verification harness.** `verify/run-all.sh` asserts §2 before/after for Cluster 1 (burns +
  cost moves), Cluster 2 (blocked + cost moves), Cluster 3 (each guard toggles correctly). Idempotent.
- **Phase 7 — Attendee access.** Browser chat UI + web terminal per Cluster 3; QR/short links; one-page
  `quickstart.md`.
- **Phase 8 — Facilitation.** 2-hour `runbook.md` (named hand-offs), `slides-outline.md`,
  `governance-map.md`, `self-assessment.md`. No banned/proprietary terms in attendee copy.
- **Phase 9 — Recordings, teardown, cost.** asciinema per segment; `teardown.sh` removes attendee +
  burn-cluster + trace state; `cost-report.sh` reports the real spend.

Each phase: verify block, stop on first failure (carry the rev3 verify blocks forward).

---

## 9. Definition of Done

- [ ] Three-cluster run-of-show plays within the 2-hour slot; `verify/run-all.sh` green and idempotent.
- [ ] Cluster 1 burns + cost counter moves; Cluster 2 blocks + cost still moves; Cluster 3 guards each
      toggle (output → input → MCP) with visible before/after.
- [ ] ~10 disposable Cluster-1 spares + N attendee Cluster-3s provision in time (recorded in SIZING).
- [ ] Live Bedrock cost counter working; real run cost from `cost-report.sh`.
- [ ] Browser access, no local install; recording per segment.
- [ ] Governance map + self-assessment committed; `VERSIONS.lock` complete.
- [ ] No real secret anywhere.

---

## 10. Decisions

Resolved 2026-06-17 (Michael):
- **Model:** Claude on Bedrock (haiku-4-5 verified working; confirm final Claude tier).
- **Guardrail impl:** kagent / CNCF-native preferred — NOT a bespoke vLLM→Bedrock classifier.
- **Backstage:** nice-to-have (include if time/feasibility allow).
- **External red-team:** No.
- **Fleet:** 3× Cluster 1, 3× Cluster 2, 2× instructor Cluster 3, per-attendee Cluster 3 + a few reserve.
- **Minimal restriction floor** on all clusters (no one-shot trivial kill; protect follow-along clusters).

Still open:
1. Final Claude tier (haiku-4-5 vs a larger Claude) — sophistication vs per-attendee cost.
2. Co-speaker split with Whitney — confirm the §2 division.
3. OTel re-leak advanced beat — build it or keep slide-only.
4. The exact "minimal floor" mechanism (RBAC/quota/admission) that lets Cluster 1 burn gradually
   without instant one-prompt destruction.

---

## 11. Honest risk register

1. **Cost of the fleet.** The facilitator fleet (3 + 3 + 2 = 8 clusters) + N attendee clusters (+reserve)
   + Bedrock spend during deliberate abuse is real money. Pre-provision, cap, and watch
   `cost-report.sh`. (The talk *weaponizes* this cost as the lesson — but we still pay it.)
2. **Bedrock model gating.** Anthropic use-case form is account-wide and was submitted; new accounts or
   opt-in regions need it again, with ~15-min propagation. Base model ids reject on-demand — always use
   `us.*` inference profiles. Verified working with haiku-4-5.
3. **Disposable-cluster provisioning at scale.** ~15 min/cluster + AWS EKS/EC2 quotas. Pre-provision the
   burn stack before doors; a wrecked cluster's replacement must already be warm.
4. **Attendee access at scale over Moscone WiFi.** Browser chat UI + web terminal entry point; QR/links;
   facilitator-driven single path if the room can't get online.
5. **Agent prompt reliability.** Deterministic fallbacks per segment; the guard lesson is independent of
   whether the model takes the bait.
6. **The new pieces are unbuilt:** cost counter, input classifier (vLLM→Bedrock), tool-call HITL, the
   three-cluster orchestration, system-prompt streaming — each carries a [SPIKE]. The *components*
   (CNCF block, kagent+Bedrock, output/input guard via proxy, MCP toolNames) are live-verified.
7. **Time:** 2 hours across three clusters leaves room (incl. free-play + the trace re-leak trap), but the regroup is still the part to protect. Protect the governance
   map; cut free-play first.

Note: keep attendee-facing files clear of banned/non-public terms; the deterministic-guardrail and
cost theses are talk payoffs, not slides.
