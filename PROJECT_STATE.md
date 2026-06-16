# PROJECT_STATE.md

Workshop: "Build a Platform, Unleash an Agent on it... and Watch it Burn!"
AI Engineer World's Fair 2026, San Francisco, Moscone West. Speakers: Michael Forrester (Accenture) + Whitney Lee.

Last updated: 2026-06-15

## Current plan summary

Spec-driven build of a repeatable workshop: attendees drive a scoped AI agent
against a pre-built IDP on a CNCF stack and run attacks; some are blocked by
controls they should already have, the rest expose AI-specific gaps.

### Scope reframe (decided 2026-06-15, supersedes BUILD-SPEC rev1 §2)

Invert the original 80/20. The CNCF controls collapse into ONE aggregate beat;
the AI-specific guardrails become the main event.

Confirmed lineup:
1. **CNCF wall (aggregate)** — agent tries deploy-noncompliant → privilege-escalation
   → infra-outside-Git; Kyverno admission + scoped RBAC + ArgoCD drift block all
   three in concert. Keeps the Kyverno Audit→Enforce live toggle.
2. **Input + output sanitization** — prompt injection in, secret/PII exfil out.
3. **Excessive agency via a bad MCP server** — untrusted MCP server induces the
   agent to over-reach; control = MCP tool authorization/allowlisting at the gateway.
- **Observability** is NOT a standalone beat — it is the lens every beat is narrated
  through (the trace view), plus the **trace re-leak trap** as the 2-hour advanced beat.

### ARCHITECTURE DECISION (2026-06-16) — supersedes BUILD-SPEC §3 rev1/rev2

Isolation model changed from vCluster-per-attendee to **separate EKS cluster per
attendee, hub-and-spoke**. Hub EKS cluster = ArgoCD + Grafana/Tempo. Each attendee =
own spoke EKS cluster, registered to hub ArgoCD, which delivers the IDP stack via an
ApplicationSet cluster generator. vCluster removed. LLM Guard per-spoke, output-`Regex`-only
by default. Cost + AWS quotas scale linearly with N. BUILD-SPEC carries a rev3 banner;
full section-by-section reconciliation of the spec is still pending.

## Task checklist

- [x] Initialize repo, write BUILD-SPEC rev1 to docs/, create GitHub repo (private).
- [x] Research spike (6 parallel) grounding every beat against June 2026 reality →
      research/01..06. Verification method: web research vs official docs, dated 2026-06-15.
- [x] Write BUILD-SPEC rev2 — scope reframe + all research corrections applied
      (docs/BUILD-SPEC.md). Bad-MCP beat planned LIVE, gated on Phase 4b build-spike.
- [x] **Declarative build wave complete (on `staging`, commit 6d31e5c).** Every
      buildable-without-a-cluster artifact authored + static-validated (shell syntax,
      YAML parse, py_compile): Kyverno policies, scoped agent RBAC + kagent v1alpha2
      Bedrock manifests, agentgateway + LLM Guard configs + all toggles, all three
      beats with deterministic fallbacks, ArgoCD ApplicationSet + hub/spoke eksctl
      configs, verify harness, observability/Falco, teardown/cost, facilitation. All
      carry verify-at-build flags. NOTHING verified on a live cluster.
- [ ] **NEXT — needs Michael + a live cluster (Track B):** (1) attendee count N +
      ceiling; (2) confirm AWS account <ACCOUNT_ID> / user nwuser is the right place to
      spend; (3) go-ahead to provision real EKS (cost scales with N); (4) install
      eksctl + docker + asciinema on the VPS (may need sudo). Then: bootstrap hub,
      provision spokes, run Phase 4b spikes, fill VERSIONS.lock, record fallbacks,
      merge `staging` → `main` only after verify/run-all.sh passes.
- [ ] Resolve build placeholders surfaced by the build wave: egress-proxy sidecar
      image (agent/gateway/llm-guard-sidecar.yaml), Bedrock model id + region, LLM Guard
      image digest (laiyer/llm-guard-api:0.3.16), region (us-west-2 placeholder).

## Research corrections that MUST flow into rev2 (source of truth: research/*.md)

- **Versions stale across the board.** kagent `0.7.7`→**`0.9.7`** (author against
  CRD `v1alpha2`, not v1alpha1). vCluster `v0.29`→**`v0.34.3`**. Kyverno **`v1.18.1`**
  (BREAKING: `spec.validationFailureAction` → rule-level `validate.failureAction` —
  this is the attack-1 toggle). Argo CD **`v3.4.3`**, Falco **`0.44.1`**,
  kube-prometheus-stack chart **`86.2.3`**, OTel Collector **`v0.154.0`**.
- **kagent Bedrock path RESOLVED** (was a FLAG): native `ModelConfig` with
  `spec.provider: Bedrock`, `spec.model`, `spec.bedrock.region`; creds via AWS chain.
  NOT the OpenAI-baseURL shim tutorials show. Agent refs it via `spec.declarative.modelConfig`.
- **kagent MCP controls exist:** `spec.declarative.tools[].mcpServer` + per-agent
  `toolNames` allowlist (omitting = ALL tools exposed = the excessive-agency footgun)
  and `requireApproval` per-tool gate. RBAC via `spec.declarative.deployment.serviceAccountName`.
- **LLM Guard SPEC ERROR:** there is **no "Secrets" OUTPUT scanner** — `Secrets` is
  input-only. Spec §5 and Phase 4 are wrong. Output exfil guardrail must use
  `Sensitive` (NER+regex, model-based) and/or output `Regex` (deterministic). For a
  provably model-free match on the FAKE-...-sentinel, use output `Regex`.
- **Determinism constraint (§3) needs correction:** only output `Regex` is truly
  deterministic; `Sensitive` loads an NER model; input `PromptInjection` is a DeBERTa
  classifier (model-based). Keep the "no LLM-as-judge" rule; stop claiming Secrets/Sensitive
  are both deterministic output scanners.
- **agentgateway output guard:** native prompt-guard response webhook can only **Mask,
  not Reject**, and is unverified against a kagent A2A endpoint → **pin the LLM Guard
  reverse-proxy sidecar as PRIMARY** for the output guardrail; keep gateway webhook as
  documented alternative. Input guard (request phase) CAN hard-block. agentgateway
  version **`v1.2.1`** (do not pin v1.3.0 beta).
- **MCP control:** agentgateway `mcpAuthorization` CEL rules over `mcp.tool.name` +
  `targets` server allowlist is the demoable control. No native human-in-the-loop.
- **OTel GenAI:** all semconv is `Development` (nothing Stable). Tool calls are
  first-class (`execute_tool` / `gen_ai.tool.name`). Content capture OFF by default;
  re-leak trap is real. Backend: Grafana Tempo + Grafana.

## LIVE VERIFICATION LOG (test cluster watch-it-burn-test, us-west-2, EKS 1.34.8)

- 2026-06-17 **Beat 1 PASS** — `verify/beat-01.sh` green against the live cluster:
  non-compliant workload admits in Audit / rejects in Enforce; ClusterRoleBinding
  forbidden by RBAC; out-of-band drift denied by admission. Fixed two real bugs:
  block-argocd-drift must exclude system SAs/nodes/admins; drift test must patch the
  main resource (not /scale).
- 2026-06-17 **kagent + Bedrock PASS** — agent (v1alpha2, Bedrock ModelConfig,
  us.anthropic.claude-sonnet-4-6, IRSA creds) answered a prompt over A2A end to end.
- Infra fixes landed: EBS CSI driver + default gp3 SC (EKS ships neither); IRSA for
  agent-sa -> Bedrock. Deleted kagent's default agent fleet (broken default OpenAI config).
- DEFERRED: kube-prometheus-stack install wedged on the test cluster; redo (lighter,
  Tempo+Grafana focus) at the observability step.

## Verification method

Research-based for unbuilt parts; LIVE-on-EKS for Beat 1 and the agent (above). "Verified" in research notes = confirmed against
current docs, not against a running build.

## Unverified, load-bearing — build-spike BEFORE committing as live

1. **agentgateway `mcpAuthorization` CEL tool-deny actually enforces on the Apache OSS
   build with a kagent A2A agent in front.** If it doesn't, the bad-MCP beat ships as a
   recorded segment + governance-map row, not a live toggle. (research/04)
2. **agentgateway native response webhook fires for a kagent A2A endpoint** — moot if
   sidecar is primary, but verify before relying on the gateway path. (research/02)
3. **kagent emits `gen_ai.*` / `execute_tool` spans and the content-capture flag name** —
   the trace narration depends on it. (research/05)
4. **ArgoCD application-controller SA identity INSIDE the vCluster** for the drift-policy
   exclude; wrong exclude either deadlocks self-heal or lets attack 3 through. (research/06)
5. **kagent `requireApproval` runtime enforcement** through the serving path. (research/01)
6. RAM: `Sensitive` NER model per-vCluster likely breaks the 1.5–2.5 GB/vCluster budget —
   use a shared LLM Guard service or output-`Regex`-only. (research/03)

## Branch / repo status

- Repo: github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn (private, SSH).
- Prose/spec/research repo today → commits go directly to `main` (per updated branch rule).
  Flip to staging→main flow once real build code (Terraform/Helm/scripts) lands.
- `staging` branch exists at the initial commit; currently unused.

## Open decisions still owned by Michael (BUILD-SPEC §10)

Attendee count + ceiling; access model; co-speaker split; 90 vs 120 min; host provider
(EKS default); whether to build the OTel re-leak advanced beat or keep it slide-only.
