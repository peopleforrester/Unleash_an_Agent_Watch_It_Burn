<!-- ABOUTME: The operating contract + build punch-list for the final ~10-day push, with the render gate. -->
<!-- ABOUTME: Consolidates the external review with Michael's rulings; supersedes the review docs where they conflicted. -->

# Watch It Burn, build plan and operating contract

Compiled 2026-06-19, event ~10 days out. This is the working contract for the final build. Where the
two external review docs conflicted with each other or the repo, Michael's rulings below are
authoritative.

## Render gate (the working discipline)

A demo-critical step is DONE only when it renders, one of:
- a green assertion in `verify/run-all.sh` proving the relevant before/after, or
- a visible before/after on the live dashboard captured in a committed recording, or
- a committed asciinema/screen recording explicitly labeled `RECORDED` (for anything that genuinely
  cannot be made live in time).

Hard rules:
- Stop on first failure. No red or unproven step is left behind while building forward.
- No mocks or simulations presented as real. No hardcoded numbers on the cost counter.
- No `[SPIKE]` ships unresolved: resolve to a live render or downgrade to a labeled recording.
- Obviously-fake secrets only (`FAKE-...-sentinel-...`). Fail the build if any real-looking
  credential appears in a cluster, trace, recording, or repo.
- If a step needs a human decision, stop and ask Michael. Do not guess and build forward.

## Resolved decisions (2026-06-19 rulings)

1. **Cluster 1 has NO minimal floor.** It dies in one prompt; the facilitator rotates ~10 disposable
   C1 spares from the SSH session. No floor mechanism to build. (Reverses the earlier floor design.)
2. **Staged is abstract-truth.** The four attack objectives landing across the three clusters is what
   "abstract wins" means. The abstract's "everything is enforced" / "agent with cluster access"
   wording is reconciled to mean the governed clusters (C2/C3) and scoped access; `verify/run-all.sh`
   asserts the staged before/after, not a literal "everything enforced on every cluster."
3. **Trace re-leak trap is OPTIONAL**, not a primary beat. It sits in the optional tier and is cut
   after the model-tier closing demo, before free-play. It stays built as a recorded beat.
4. **Input guard: build BOTH the block-list and the classifier, wired as progressively-enablable
   layers.** The deterministic block-list is the cheap first stage; the DeBERTa classifier is a second
   stage toggled on as needed. Both built; not both-always-on.
5. **Fable 5 is unavailable** (access suspended). Dropped from the design; not a wildcard tier.
6. **Cost counter metering** is live at the guard-proxy from each Bedrock response's token-usage times
   per-tier price. Cost Explorer is post-hoc only (`cost-report.sh`); it lags too much to drive a live
   counter.

## Whitney feedback incorporated (2026-06-20)

From her Google Doc comments (Michael handles the substantive replies; these are the build changes):

- **Telemetry: Datadog primary, Grafana/Tempo/Prometheus secondary fallback.** Each attendee uses
  their own Datadog; the OTel collector exports to Datadog first (primary) and to prometheus/tempo as
  the analog fallback. Done in `gitops/apps/otel-collector.yaml` (datadog exporter, BYO `datadog-secret`).
- **Thesis: maintenance cost, not just spend.** Per-agent/per-app guardrails mean more to maintain and
  more to miss; doing it at the cluster abstraction layer is the win. Folded into BUILD-SPEC §1.
- **Thesis: prompt caching** for the capped-cost story. Folded into BUILD-SPEC §1.
- **Thesis: tell the agent what guardrails exist** in its system prompt so it does not burn tokens
  trying blocked actions (a cost saver). Folded into BUILD-SPEC §1.
- **Reveal-style structure:** the Cluster 1 platform tour is the guards-OFF / minimal-security view;
  the CNCF security projects are introduced WHEN they turn on at Cluster 2, not all upfront. Whitney
  presents some of them. Folded into `facilitation/runbook.md`.
- **ESO / S3 exfil "basketball" game:** a shared External Secrets Operator (AWS ESO; possibly Vault)
  holds one secret; attendees use system prompts to get the agent to exfiltrate it, then post it to a
  target S3 bucket. Captured as an optional challenge in the runbook + a difficulty spike.
- **Challenge ladder** (optional, evaluate difficulty per level): (1) exfiltrate data, (2) get the
  agent to reveal secrets, (3) break the cluster. Use funny Kubernetes secrets. In the runbook.
- **Partner-cluster breaking:** lower priority (restore burden); kept only as a possible LAST challenge.
- **Considered CNCF adds:** Harbor + image signing -> an image-verification Kyverno policy added now
  (`policies/kyverno/verify-image-signatures.yaml`); NetworkPolicy / Falco / ESO already present;
  **Istio service mesh (mTLS) is a planned addition** (spike), not yet built.

## Build punch-list (priority order, each with its render bar)

Repo-buildable here; live provisioning/verification is Michael's separate project.

1. **Observability + trace view (Phase 1).** Slim kube-prometheus-stack for the per-attendee node;
   OTel Collector to Tempo; Grafana trace view showing input / output / tool-call (gen_ai) spans.
   *Render:* all three span types visible live for one Cluster-3 run.
2. **Cluster fleet (Phase 2).** eksctl configs: 3x C1 (no guardrails, no floor, ~10 disposable
   spares), 3x C2 (CNCF-only), per-attendee C3 via ApplicationSet (cluster generator + sync-waves);
   3x instructor C3 only if the optional model-tier demo runs. *Render:* each provisions
   Synced/Healthy; C1 dies in one prompt and rotates; provision time + fleet cost recorded in SIZING.
3. **Cost counter (Phase 4c, headline `[SPIKE]`).** Meter tokens at the guard-proxy times per-tier
   price, per cluster, on screen. *Render:* climbs during C1, still moves on C2 (blocked but paid),
   flatlines when the input guard blocks pre-LLM.
   - **DONE (logic + render-gate test green):** real per-tier prices (Haiku/Sonnet/Opus, sourced
     2026-06-19, no hardcoded counter), `MODEL_TIER` per-cluster selection, Prometheus `/metrics`
     endpoint + scrape annotations so Grafana graphs the climbing counter, block-list path proven to
     flatline. Proof: `verify/test_cost_counter.py` (11 checks green).
   - **Remaining (needs a live cluster, provisioning project):** confirm kagent's real A2A usage
     field names (`promptTokenCount` / `candidatesTokenCount`) against a live response, and capture
     the live dashboard before/after (climb, flatline) as the recorded render.
4. **Input guard, two-stage progressive (Phase 4).** Block-list (deterministic) as stage 1; DeBERTa
   classifier as stage 2, toggled on as needed. *Render:* "delete" intent blocked before the LLM,
   counter flatlines; classifier stage catches a phrasing the block-list misses.
5. **Output tool-call block + HITL + notification (Phase 4).** Extend the verified output guard to
   intercept a dangerous `kubectl delete` tool call, hold for human-in-the-loop (kagent
   `requireApproval`), fire a notification. *Render:* the delete is stopped with a visible hold.
6. **MCP restriction finish (Phase 4b).** Complete BEFORE to AFTER via the kagent `toolNames`
   allowlist; build the clown-file to Argo variant. Call LIVE vs RECORDED for the room. *Render:*
   rogue tool reachable + leaks sentinel BEFORE, not exposed AFTER.
7. **Attendee access + chat UI (Phase 5/7).** Browser chat UI (chat-only on C1/C2; chat + web terminal
   on C3), QR/short links, one-page quickstart, per-segment `fallback.*.sh`. Optional system-prompt
   streaming carries its own content moderation before any public screen. *Render:* a cold browser
   reaches a C3, no local install.
8. **Verification harness (Phase 6).** `verify/run-all.sh` asserts the staged before/after across all
   three clusters, idempotent. *Render:* green and re-runnable.
9. **Recordings + teardown + cost (Phase 9).** asciinema per segment (the live-failure fallbacks);
   `teardown.sh` to $0; `cost-report.sh` pulls the real Cost Explorer total. *Render:* a recording per
   segment, teardown leaves $0, cost-report prints a real number.
10. **Takeaway artifacts (Phase 8).** `governance-map.md` + `self-assessment.md` ALREADY EXIST. Align
    the governance map to the cost-ladder framing (below); do not regenerate from scratch.

## Two gaps the external review missed (from the prior gap analysis)

- **Rate-limit the demo itself.** A room hammering the chaos agent can run up a real Bedrock bill or
  DDoS the demo. Add a hard per-cluster token/request cap on the burn + agent path. The cost demo
  cannot itself run away. Not in either review doc.
- **CNI.** The repo uses VPC-CNI, not Cilium. The `default-deny` NetworkPolicies need an enforcing
  CNI; decide VPC-CNI NetworkPolicy vs Cilium (+Hubble). Not in either review doc.

## Design consideration carried over

- **Cost-ladder framing.** Make "earlier equals cheaper" explicit: input (0 tokens) < tool scoping <
  output (post-LLM) < Kyverno admission (last and most expensive mile). Demo order stays
  drama-first (output exfil opens Cluster 3), but the governance map and Michael's narration present
  the cost gradient as the lesson.

## Cut order if the core does not all render in time

Protect the three-cluster spine and the regroup/governance map. Cut in this order:
1. Optional model-tier closing demo.
2. Trace re-leak trap.
3. Attendee free-play.
Never cut the regroup.

## Cross-doc reconciliations (apply, or attendee copy silently breaks)

- `runbook.md` (120 min) is the authoritative timing. Ignore Build-Spec inline minute markers if they
  drift.
- "Eight Guardrails Framework" never appears in attendee-facing copy.
- Never label the combined input guard "deterministic" in attendee copy once the classifier stage is
  in the path; the block-list stage is deterministic, the classifier is not. Internal note only.
