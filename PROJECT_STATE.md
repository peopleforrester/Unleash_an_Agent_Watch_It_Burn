# PROJECT_STATE.md

Workshop: "Build a Platform, Unleash an Agent on it... and Watch it Burn!"
AI Engineer World's Fair 2026, San Francisco, Moscone West. Speakers: Michael Forrester (Accenture) + Whitney Lee.

Last updated: 2026-06-20

### Doc-accuracy spike corrections applied (2026-06-20)

Four multi-agent doc-accuracy spikes landed (research/11 version re-pin, research/12 mechanism
verification, research/13 model cards + Bedrock IDs, research/14 verify-at-build sweep). All
corrections applied and the full offline suite is green (136 checks, 18 files). Verification method:
live web research against vendor primary sources + `aws bedrock list-inference-profiles`.

- **Cost-counter key bug (CRITICAL, research/14 §3a):** kagent emits Google ADK metadata under
  `adk_usage_metadata`, NOT `kagent_usage_metadata`. The old key would tally ZERO tokens and break
  the cost story. Fixed in both proxy.py copies, cost/README.md, and the two tests
  (test_cost_counter, test_proxy_guards).
- **agentgateway v1.2.1 → v1.3.0** (GA 2026-06-17): bumped in agentgateway.yaml, mcp-authz-on/off,
  GATEWAY-NOTES, BUILD-SPEC, beats/03 BUILD-SPIKE, VERSIONS.lock. mcpAuthorization is allow-only CEL
  with implicit deny (NO `action` field) — deleted FORM B; MCP config re-nested under
  `mcp.{targets,policies}`; tests updated.
- **Tempo chart repointed** to `grafana-community/helm-charts` 2.2.3 / app 2.10.7 (old grafana repo
  path is a dead stub after the 2026-01-30 migration). loki/alloy correctly stay at grafana/helm-charts.
- **Bedrock model IDs (research/13):** Sonnet `us.anthropic.claude-sonnet-4-6`, Opus
  `us.anthropic.claude-opus-4-8` (NO date stamp — the `<DATE>` placeholders were wrong), Fable
  `us.anthropic.claude-fable-5` (now live on Bedrock). Sonnet/Opus require the `us.` Geo profile
  (no In-Region in us-west-2). Applied in resources.yaml, VERSIONS.lock, BUILD-SPEC.
- **Other:** Kyverno restrict-image-registries on rule-level `validate.failureAction: Enforce`
  (deprecated spec-level removed); pid-limit delivery corrected to eksctl `overrideBootstrapCommand`
  (not /etc/eks/nodeadm.d/); egress allowlist S3-gateway-endpoint caveat added; LLM Guard verdict
  field is `scanners` not `scores`; EKS pinned 1.35 relabeled "current standard-support" (1.36 now
  newest); kagent 0.9.7→0.9.9, argocd 9.5.21→9.6.0/v3.4.4, falco-talon chart 0.4.1.
- **Harbor/cosign Enforce upgrade:** verify-image-signatures flipped Audit→Enforce, scoped to
  `harbor.agenticburn.com/*` so public demo images are unaffected.

Docs 3/6 reconciliation (2026-06-21): DONE, comment-safe. Research spike research/15 established that
comment THREADS survive any update at the data layer (even media-PATCH); only the editor's visual
anchor orphans. Method used: surgical Docs API `documents.batchUpdate` `replaceAllText` on the same
file ID, with each comment's `quotedFileContent` treated as a no-edit zone, gated on
`requiredRevisionId`, after pinning a `keepForever` rollback revision. Doc 3 (Run of Show) needed NO
version corrections (its tier/VPC-CNI content is already correct). Doc 6 (Build Spec): 8 stale version
pins corrected (kagent 0.9.7→0.9.9, ArgoCD/Argo CD v3.4.3→v3.4.4, OTel v0.154.0→v0.158.2, agentgateway
OSS v1.2.1→v1.3.0, EKS 1.34→1.35). Both Doc-6 comments verified intact (count 2, none deleted, quoted
spans verbatim). Exported OAuth tokens deleted after use.

TS agent ON HOLD (Michael, 2026-06-21): the optional TypeScript agent / custom-framework addition is
DEFERRED until after the demo is finished. Sticking with kagent only for now — a second agent
framework is unnecessary complexity before the demo works end to end (a comment to this effect is on
a shared Google Doc). spiny-orb hookup waits on that. Do NOT build the TS agent until Michael reopens
it. The research below stays as the record. ↓

TypeScript agent option + spiny-orb (2026-06-21): "Spiny/Weaver" = Whitney's repo
github.com/wiggitywhitney/spinybacked-orbweaver (`spiny-orb`), an AI agent that auto-adds OTel
instrumentation to JS/TS code and validates against a Weaver semconv registry. It instruments JS/TS
ONLY, so for Whitney to use it on our code there must be TS code. Decision (Michael): KEEP the
kagent Python agent as primary/fallback; ADD an OPTIONAL TS agent (recommended shape: Mastra or
Vercel AI SDK, wrapped as a kagent `type: BYO` A2A backend so it keeps agentgateway + MCP + HITL +
LLM Guard), shipping a `spiny-orb.yaml` + Weaver registry + OTel SDK init so spiny-orb runs out of
the box -> Datadog. Research: research/16 (corrected; the earlier Spiny=Pixie guess is void).
BUILD IS GATED on Whitney's answers (framework, Weaver registry, how she runs spiny-orb on stage).
Proposal Google Doc created + shared with Whitney (notified) + comment tagging her:
docs.google.com/document/d/1Iel4yyUEbTf5s3W1PGoAbHSM0MQh6nLJQ_Zzv_2xCLk
(folder "Watch it Burn" 1_Y4Qrnz6x80AcGWgiRAZrObAvdVdMpfU; Whitney = wiggitywhitney@gmail.com).

KubeArmor research spike (2026-06-21): DONE -> research/17-kubearmor-forkbomb-2026.md. Verdict:
KubeArmor v1.7.3 CANNOT prevent a fork bomb the way podPidsLimit does — its KubeArmorPolicy has NO
process-count/thread-count/fork-rate/PID field (verified vs the shipped spec); it only allow/denies
named binary exec, file, network, capabilities (syscalls are audit-only regardless of action). The
`rate: 10p1s` seen in some material is a telemetry throttle, not enforcement (trap, flagged). It
enforces inline at LSM hooks (BPF-LSM preferred); EKS AL2023 ships kernel 6.1 with BPF-LSM enabled
by default so enforcement is plausible but MUST be verified on the node (`/sys/kernel/security/lsm`
contains `bpf`, `karmor probe`, live Block test). DECISION: keep podPidsLimit as the SOLE inline
fork-bomb block + Falco/Talon as detect+respond; do NOT add KubeArmor to the fork-bomb story. KubeArmor
is a candidate DIFFERENT-attack station (CNCF-native inline prevention: default-deny exec, block
secret-file reads, block egress) — still an OPEN option, not folded in. No repo defense changed.
Findings Google Doc (silently shared with Whitney):
docs.google.com/document/d/1UZMsLxqol5ASiXWgU3tlNIxBV3pCsLdLlrAFIARLNBw

Runtime-enforcement + observability spikes (2026-06-21): research/20-23.
- research/20 (Tetragon): does NOT replace the PID cap for fork bombs — Sigkill is kill-on-detect
  (outrunnable), Override is all-or-nothing (zero forks, not a ceiling of N), --cgroup-rate is a
  telemetry throttle. Standalone w/o Cilium CNI CONFIRMED (v1.7.0, VPC-CNI ok). Value = different-role
  (process lineage + inline Override of OTHER agent misbehavior). AL2023 Override needs
  CONFIG_BPF_KPROBE_OVERRIDE + non-confidentiality lockdown — verify at build.
- research/21 (KubeArmor claims, cited): research/17 CONFIRMED adversarially — no count/rate/PID field,
  syscalls audit-only; captured AL2023 node artifact shows bpf live in /sys/kernel/security/lsm. Safe
  to hand Whitney.
- research/22 (4-way comparison, cited): only podPidsLimit prevents a fork bomb inline (cgroup PIDs
  controller returns -EAGAIN at fork). Falco+Talon/Tetragon = detect+kill (outrunnable); KubeArmor =
  nothing as a count cap. Framing: PID cap = wall, Falco = alarm, Tetragon-or-KubeArmor = locked door
  (pick at most one for inline prevention of OTHER attacks).
- research/23 (decision points for Whitney): 8 decisions w/ pros/cons; design principle = Datadog
  REQUIRED+primary for this event, OTel neutral layer, OSS (Prom/Grafana/Tempo) swappable fallback,
  Datadog additive via OTEL_RESOURCE_ATTRIBUTES (not DD_*). Verified live: OTel Collector has NO
  connectors: block; Falcosidekick forwards only to Talon (DD/OTLP wiring is net-new). NOTE: Decision 4
  (TS agent) is now resolved = ON HOLD per above.
NET fork-bomb decision UNCHANGED: podPidsLimit stays the sole inline block + Falco/Talon detect-respond.
Tetragon/KubeArmor remain OPEN candidates for a different-attack station only. Nothing folded into the
repo defense. Whitney's branch left untouched.

AWS collision-avoidance tagging (2026-06-21): accen-dev is shared with a separate Packt project (its
own clusters; we never share resources). Convention established in `infra/TAGGING.md`: every resource
carries `project=watch-it-burn` and every cluster name starts with `watch-it-burn-`. Applied: all 4
eksctl configs (renamed `workshop-hub`→`watch-it-burn-hub`, `workshop-spoke-*`→`watch-it-burn-spoke-*`;
added `metadata.tags` + nodegroup tags; tag key was `workshop:unleash-an-agent`, now `project:watch-it-burn`);
S3 hoop bucket (`put-bucket-tagging`) and trophy secret (`--tags`); spoke README cluster-name refs.
Teardown scripts confirmed name/prefix-scoped (can only ever hit `watch-it-burn-*`, never Packt).
New render-gate test `test_tagging.py` enforces it (suite now 154 checks). AWS Resource Group bundling
= tag query on `project=watch-it-burn` (commands in TAGGING.md). Public-URL linkage
(cluster→LB hostname→`*.agenticburn.com` via `infra/dns/set-demo-dns.py`) documented; LB-service tag
annotation requirement noted; full per-cluster automation is deferred provisioning work.

Fable 5: RETIRED from this workshop (Michael, 2026-06-21). Not a tier in the comparison. The Fable
additions made during the doc-accuracy pass were reverted (resources.yaml, VERSIONS.lock, BUILD-SPEC);
research/13 still records that it went live on Bedrock as a dated finding, but it is out of scope here.
Do not re-raise Fable; Michael will say if it comes back.

### Session-close note (2026-06-19)

- **AI-isms:** whole repo swept clean. Bulk em-dash strip across 26 docs
  (research, beats, infra READMEs, design docs); only residual checker flag is
  `BUILD-SPEC.md`, which is false positives (the talk-title word "Unleash",
  three "test harness" references, and "lets" misread as "let's") and was left
  as-is. Verification method: `check-ai-isms/check.py` repo scan.
- **Whitney handoff:** the six handoff files were uploaded to the shared Drive
  folder (`1_Y4Qrnz6x80AcGWgiRAZrObAvdVdMpfU`, account michaelrishiforrester@gmail.com)
  and converted to native Google Docs: START HERE, Abstract, Run of Show (the
  demo flow), Slide Outline, Cold Open Script, Build Spec (technical reference).
- **Cost / teardown:** full AWS sweep of the workshop AWS account (us-west-2 +
  us-east-1/2, us-west-1). Zero EKS clusters, EC2, NAT gateways, load balancers,
  snapshots, ECR repos, Elastic IPs. Deleted 5 orphaned EBS volumes (13 GB,
  watch-it-burn-test PVC leftovers: kagent-postgres ×3, tempo, loki) that survived
  the earlier `eksctl delete cluster`. Month-to-date spend $11.69; forward run
  rate ~$0/day.

### Build plan adopted (2026-06-19, external review reconciled)

- `docs/BUILD-PLAN.md` is the operating contract for the final push: render gate, resolved decisions,
  prioritized punch-list. Read it first when building.
- Rulings folded in across runbook/BUILD-SPEC/burn-clusters/ABSTRACT/GATEWAY-NOTES + the burn code:
  **Cluster 1 has NO floor** (dies in one prompt, ~10 disposable spares; removed minimal-floor + kyverno
  from `app-of-apps-burn.yaml`); **staged is abstract-truth** (verify asserts the staged before/after);
  **trace re-leak trap is optional**; **input guard is two stages** (block-list then classifier,
  progressive); **Fable 5 unavailable**; cost counter meters live at the guard-proxy.
- Two gaps the review missed, tracked in BUILD-PLAN: rate-limit the demo itself; CNI (VPC-CNI vs Cilium).
- Remaining open: co-speaker split confirmation with Whitney.

### Build status (2026-06-20): buildable backlog complete

Everything buildable-without-a-cluster is done, tested, and on **main == staging**. Offline render-gate
suite: **11 test files, 94 checks, all green** (`verify/run-tests.sh`).

- **P1** cost counter (real per-tier pricing, Prometheus /metrics, flatline-on-block).
- **P3** input two-stage guard + rate-limit/cost-cap, bad-MCP clown-file, HITL + MCP allowlist.
- **P4** slim Prometheus + trace dashboard; **Datadog primary**, Grafana/Tempo analog fallback.
- **P5** attendee chat UI (browser-only, live cost counter).
- **P6** live cost-counter assertion (`beat-cost`) in the verify harness.
- **P8** governance-map cost-ladder.
- **Whitney's feedback:** thesis augments (maintenance, caching, tell-the-agent-its-jail), reveal-style
  structure (guards-off tour, CNCF intros at C2), cosign image-signing policy, **Istio ambient mTLS =
  SPIFFE identity** (1.30.1), the **ESO/S3 exfil game**, the optional moderated prompt-stream display.
- **Docs:** `docs/STACK-WALKTHROUGH.md` (Doc 7) + `facilitation/whitney-questions-tracker.md` +
  `facilitation/whitney-comments-archive.md` (Drive backup). 13 build-pointer + 7 walkthrough-link
  replies posted on her comments.

**Provisioning track (verify-at-build, needs a live cluster):** kagent A2A usage field names, agentgateway
mcpAuthorization + requireApproval runtime, LLM Guard envelope, VPC-CNI NetworkPolicy enforcement,
Datadog account/key, Bedrock per-tier access (Sonnet/Opus forms), the game difficulty spikes.

**Open for Michael + Whitney (tracker):** her narration story, central observability + Datadog lag,
before/after-gateway prompt visibility, service-mesh/SPIFFE depth, difficulty spikes.

**Doc-sync note:** Run of Show (Doc 3) + Build Spec (Doc 6) content re-syncs are HELD to protect her
in-doc comments; comments are archived as a backup. Docs 7 + the archive are safe to re-sync (no comments).

## Current plan summary

Spec-driven build of a repeatable workshop: attendees drive a scoped AI agent
against a pre-built IDP on a CNCF stack and run attacks; some are blocked by
controls they should already have, the rest expose AI-specific gaps.

### Scope reframe (decided 2026-06-15, supersedes BUILD-SPEC rev1 §2)

Invert the original 80/20. The CNCF controls collapse into ONE aggregate beat;
the AI-specific guardrails become the main event.

Confirmed lineup:
1. **CNCF wall (aggregate)**, agent tries deploy-noncompliant → privilege-escalation
   → infra-outside-Git; Kyverno admission + scoped RBAC + ArgoCD drift block all
   three in concert. Keeps the Kyverno Audit→Enforce live toggle.
2. **Input + output sanitization**, prompt injection in, secret/PII exfil out.
3. **Excessive agency via a bad MCP server**, untrusted MCP server induces the
   agent to over-reach; control = MCP tool authorization/allowlisting at the gateway.
- **Observability** is NOT a standalone beat, it is the lens every beat is narrated
  through (the trace view), plus the **trace re-leak trap** as the 2-hour advanced beat.

### ARCHITECTURE DECISION (2026-06-16), supersedes BUILD-SPEC §3 rev1/rev2

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
- [x] Write BUILD-SPEC rev2, scope reframe + all research corrections applied
      (docs/BUILD-SPEC.md). Bad-MCP beat planned LIVE, gated on Phase 4b build-spike.
- [x] **Declarative build wave complete (on `staging`, commit 6d31e5c).** Every
      buildable-without-a-cluster artifact authored + static-validated (shell syntax,
      YAML parse, py_compile): Kyverno policies, scoped agent RBAC + kagent v1alpha2
      Bedrock manifests, agentgateway + LLM Guard configs + all toggles, all three
      beats with deterministic fallbacks, ArgoCD ApplicationSet + hub/spoke eksctl
      configs, verify harness, observability/Falco, teardown/cost, facilitation. All
      carry verify-at-build flags. NOTHING verified on a live cluster.
- [ ] **NEXT, needs Michael + a live cluster (Track B):** (1) attendee count N +
      ceiling; (2) confirm the workshop AWS account / the operator user is the right place to
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
  (BREAKING: `spec.validationFailureAction` → rule-level `validate.failureAction` , 
  this is the attack-1 toggle). Argo CD **`v3.4.3`**, Falco **`0.44.1`**,
  kube-prometheus-stack chart **`86.2.3`**, OTel Collector **`v0.154.0`**.
- **kagent Bedrock path RESOLVED** (was a FLAG): native `ModelConfig` with
  `spec.provider: Bedrock`, `spec.model`, `spec.bedrock.region`; creds via AWS chain.
  NOT the OpenAI-baseURL shim tutorials show. Agent refs it via `spec.declarative.modelConfig`.
- **kagent MCP controls exist:** `spec.declarative.tools[].mcpServer` + per-agent
  `toolNames` allowlist (omitting = ALL tools exposed = the excessive-agency footgun)
  and `requireApproval` per-tool gate. RBAC via `spec.declarative.deployment.serviceAccountName`.
- **LLM Guard SPEC ERROR:** there is **no "Secrets" OUTPUT scanner**, `Secrets` is
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

- 2026-06-17 **Beat 1 PASS**, `verify/beat-01.sh` green against the live cluster:
  non-compliant workload admits in Audit / rejects in Enforce; ClusterRoleBinding
  forbidden by RBAC; out-of-band drift denied by admission. Fixed two real bugs:
  block-argocd-drift must exclude system SAs/nodes/admins; drift test must patch the
  main resource (not /scale).
- 2026-06-17 **kagent + Bedrock PASS**, agent (v1alpha2, Bedrock ModelConfig,
  us.anthropic.claude-sonnet-4-6, IRSA creds) answered a prompt over A2A end to end.
- 2026-06-17 **Beat 2 guardrail engine PASS (LLM Guard, live)**, deterministic core proven:
  output Regex blocks+redacts FAKE-PROD-DB-PASSWORD-sentinel-9f2a (is_valid=false, [REDACTED]),
  passes clean output; input PromptInjection (DeBERTa) blocks an injection (is_valid=false),
  passes benign. Verdict envelope confirmed: {is_valid, scanners, sanitized_output/prompt}.
  Fixed: pod needed numeric runAsUser (image uses named user).
- 2026-06-17 **Beat 2 guard-proxy built + plumbed (live)**, realized the spec's output
  "sidecar" as a real A2A-aware reverse proxy (agent/gateway/guard-proxy/proxy.py, stdlib,
  runs from stock python image via ConfigMap; kagent owns the agent pod so the inspection
  point is a proxy in front of the agent Service, not an in-pod sidecar). Deployed as
  guard-proxy in attendee-test; forwards A2A to the agent and calls LLM Guard; input-block
  (403 on injection) + output-scrub (redact/block sentinel) toggled by INPUT_GUARD/OUTPUT_GUARD.
- **BLOCKER (account-level): Bedrock Anthropic use-case form not submitted.** All Anthropic
  models on the workshop AWS account fail with ResourceNotFoundException "Model use case details
  have not been submitted." `aws bedrock get-use-case-for-model-access` => form never filled.
  Base model ids reject on-demand (must use us.* inference profiles); the us.* profiles fail
  the use-case gate. The one early PONG hit a brief propagation window. FIX is Michael's:
  submit the Anthropic use-case form (Bedrock console -> Model access) OR authorize me to run
  `put-use-case-for-model-access` + `create-foundation-model-agreement` with Accenture's real
  use-case details. Until then the live agent LLM path (and the end-to-end agent-exfil demo for
  Beat 2) is blocked. The guard engine + proxy are verified independently.
- 2026-06-17 **Bedrock use-case form SUBMITTED** (authorized by Michael): companyName=Accenture,
  intendedUsers=2, us-west-2. `put-use-case-for-model-access` ok; `get-use-case-for-model-access`
  confirms. `create-foundation-model-agreement` for anthropic.claude-haiku-4-5 / sonnet-4-6 /
  sonnet-4-5 => agreementAvailability=PENDING. Bedrock still returns "try again in 15 minutes"
  (propagation). Background poller repoints the agent to a working us.* inference profile (haiku-4-5
  preferred for workshop cost) once access lands. Workshop model decision: prefer Claude Haiku 4.5
  via us.* inference profile (base ids reject on-demand; must use inference profiles).
- 2026-06-17 **Bedrock RESOLVED + Beat 2 PASS END-TO-END (live)**, access propagated; agent
  repointed to us.anthropic.claude-haiku-4-5-20251001-v1:0. Through the guard-proxy in front of
  the live agent: OUTPUT guard off => agent leaks FAKE-PROD-DB-PASSWORD-sentinel-9f2a; on =>
  [REDACTED], sentinel gone. INPUT guard on => prompt injection blocked at the proxy (403, never
  reaches agent); benign passes. Guards reset to OFF (workshop default). Beats 1 + 2 + agent all
  verified live on EKS. Remaining: Beat 3 (MCP authz spike), observability backend, hub+spokes scale.
- 2026-06-17 **Beat 3 IN PROGRESS**, design decision: use kagent's NATIVE per-agent
  `tools[].mcpServer.toolNames` allowlist as the excessive-agency control (confirmed in the
  v1alpha2 Agent CRD), instead of betting on agentgateway mcpAuthorization over A2A. Done so far:
  evil-mcp-shim deployed (registry-free: python:3.12-slim + `pip install mcp` + server.py via
  ConfigMap) in attendee-test; RemoteMCPServer `evil-mcp` registered (STREAMABLE_HTTP ->
  evil-mcp-shim:8000/mcp), kagent ACCEPTED it and discovered both tools (get_weather w/ poisoned
  description + read_internal_config returning FAKE-MCP-EXFIL-sentinel-4c1d). NEXT (resume here):
  wire the agent tools, BEFORE = expose both tools (or omit toolNames) so the rogue tool is
  reachable and leaks; AFTER = toolNames:[get_weather] so read_internal_config is not exposed ->
  blocked. Then commit the working Beat-3 manifests.

## CLUSTER DELETED (2026-06-17)
Cluster watch-it-burn-test FULLY DELETED per Michael ("all cluster resources were deleted";
`aws eks list-clusters` => []). $0 ongoing. Everything is reproducible from this repo: re-provision
with `eksctl create cluster -f infra/test-cluster/cluster.yaml`, then bootstrap + the verified steps
in this log. Bedrock use-case form + model agreements remain on the account (no cost; one-time).

## DESIGN EVOLVED, see docs/DESIGN-DECISIONS.md (2026-06-17)
The Michael+Whitney planning transcript (docs/transcripts/watch-it-burn-planning.md) post-dates
rev3 and reshapes the talk: **2-hour slot (confirmed: Day 1, 2:20–4:20pm, Track 5)**, a **three-cluster spectacle** (Cluster 1 no-guardrails
burns + cost counter; Cluster 2 CNCF blocks but shows cost; Cluster 3 attendee's own with AI
guardrails they switch on: output- then input-sanitization then MCP tool restriction), and
**cost / wasted-token DoS** as a central theme. rev3 components are all verified; the STRUCTURE
needs a rev4. Full decision log + task list in docs/DESIGN-DECISIONS.md.

## STOPPED FOR THE NIGHT 2026-06-18, RESUME STEPS (cluster DELETED -> $0)
Stopped mid full-IDP deploy. The GitOps port is COMPLETE and committed to staging (app-of-apps with
28 components, GA-pinned, AI layer kustomize-validated). To resume tomorrow:
  1. eksctl create cluster -f infra/test-cluster/cluster.yaml   (EBS CSI baked in; ~15-20 min)
  2. ./infra/deploy-full-idp.sh   (installs ArgoCD, registers the private repo, applies the app-of-apps)
  3. Watch: kubectl get applications -n argocd , triage any that fail (likely the GA-bump breakers:
     ESO v1->v2, Loki v6->v7). This is the live interop proof that was NOT yet completed.
  4. Add agent Bedrock IRSA (see infra/cluster3-setup.sh step [4]) + restart workshop-agent.
  5. Re-verify the three beats; then pull spend from teardown/cost-report.sh.
  6. Open: three-cluster fleet (task #7); claude-ai-context/ local copy (gitignored) pending Michael's
     call to delete here (belongs in his agentic-covenants project).
NOT YET PROVEN: the full app-of-apps sync on a live cluster (the GA-bump interop). Everything else
through Beat 3 + cost counter + block-list + minimal-floor was verified live on prior provisions.

## FULL IDP GITOPS DEPLOY, VERIFIED on EKS 1.35 (2026-06-18)
Provisioned watch-it-burn-test on K8s 1.35 (chosen over 1.36 for certainty), ran infra/deploy-full-idp.sh
(ArgoCD + private-repo creds + ghcr OCI + app-of-apps). RESULT:
- Full 27-component IDP + the AI layer deployed via the Argo CD app-of-apps. INTEROP PROVEN: all
  GA-bumped charts Synced/Healthy together on 1.35, external-secrets (v1->v2), loki (v6->v7),
  cert-manager v1.20, falco/falcosidekick, otel-collector, tempo, kagent-crds + kagent (OCI).
- Agent answers via Bedrock (IRSA role witb-agent-bedrock-gitops on agent/agent-sa). Block-list
  verified on the GitOps instance ("blocked by input block-list ... No model tokens were spent").
- FINDING (build item): Argo CD selfHeal REVERTS kubectl-level guard toggles. The live demo toggles
  must be an ArgoCD-safe runtime mechanism (proxy /toggle endpoint or a watched ConfigMap outside the
  synced spec), not a deployment env edit. Had to pause selfHeal on the ai-layer app to test, then restored.
- Reds remaining (NOT interop): *-party + backstage + templated-test-svc = ImagePullBackOff from
  KubeAuto's PRIVATE ECR (acct 598274344262), repoint to public/our ECR; ESO secrets Degraded (no
  AWS Secrets Manager entries -> Grafana admin secret missing -> grafana config error); kagent default
  agent fleet recreated as noise (disable via kagent chart values); cert-manager-issuers Degraded (no real issuer).
- SPEND: Cost Explorer ~$6.75 through partial Jun 18; ~$7-9 total project once ingested.
- Cluster DELETED after verify -> $0.
REMAINING BUILD: runtime guard toggles; repoint *-party/backstage images; wire Grafana admin secret
(static or real AWS SM); disable kagent default agents; three-cluster fleet (task #7); then the
presentation/slides for Whitney.

## KUBEAUTO IDP PORT (2026-06-18, offline, cluster deleted -> $0)
Major correction: the full best-practice IDP already exists, conference-proven, at
~/repos/_archive/events/kubeauto-ai-day (27 components, 59 tests). Watch It Burn now REUSES it
(docs/WATCH-IT-BURN-REUSE-MAP.md) instead of the minimal subset I'd been building. Done so far:
- Copied the EKS foundation into the repo: gitops/ (app-of-apps + apps + namespaces + bootstrap),
  security/ (rbac, falco, eso, cert-manager, quotas-pdbs), observability-idp/, backstage/,
  policies/kyverno (6 KubeAuto policies + my minimal-floor + block-argocd-drift = 8).
- Dropped ecom-*/sample-app/load-generator; KEPT *-party apps as the agent's BURN TARGETS.
- RE-PINNED every chart to current GA 2026-06-18 (was Feb/Mar pins). Flagged breaking: ESO v1->v2
  (manifests use external-secrets.io/v1 GA, verify at deploy), Loki v6->v7 (values review).
  REPLACED deprecated/EOL Promtail with Grafana Alloy 1.10.0. Full table in VERSIONS.lock.
- Added kagent + agent namespaces; wired kagent-crds + kagent ArgoCD apps (OCI helm).
- Guardrails decision (Michael): LLM Guard (OSS) + kagent + block-list, NO AWS-native/Bedrock
  Guardrails. Model = Claude on Bedrock. Backstage = nice-to-have. No external red-team.
- Fleet (Michael): 3x Cluster1 (no-guardrails + minimal-floor, rotated as they burn), 3x Cluster2
  (CNCF), 2x instructor Cluster3, per-attendee Cluster3 + reserve.
REMAINING offline: (a) materialize the AI layer (agent ModelConfig+Agent+RBAC, guard-proxy+proxy.py
configmap, llm-guard, evil-mcp+RemoteMCPServer) into GitOps-ready manifests w/ concrete namespace
(IRSA can't be GitOps'd -> bootstrap or Pod Identity/ACK); (b) three-cluster app-of-apps profiles
(trim child apps per role); (c) fresh provision + deploy the FULL IDP via ArgoCD + re-verify.
For now the AI layer deploys via infra/cluster3-setup.sh (imperative, verified).

## REV4 LIVE VERIFICATION (2026-06-17, re-provisioned watch-it-burn-test)
Cluster re-provisioned (EBS CSI baked into the config now, came up clean, no manual storage fix).
Full Cluster-3 profile applied via the new one-shot `infra/cluster3-setup.sh`. Verified live:
- **Cost counter** ✅, guard-proxy `GET /cost` tallies real Bedrock token usage (benign request =
  775 in / 9 out tokens / $0.00082). Refinement: the counter is in-memory and resets when the proxy
  restarts, toggling guards via `kubectl set env` restarts the pod. For the demo, make guard toggles
  RUNTIME (ConfigMap-watched or a /toggle endpoint) so the counter persists and visibly flatlines.
- **Input block-list** ✅, "delete the unicorn deployment" => 403 "blocked by input block-list
  (matched 'delete'). No model tokens were spent." (cost-saving, pre-LLM).
- **Minimal-floor** ✅, delete of a protected platform workload (kagent-querydoc) BLOCKED by
  admission; delete of a demo workload in attendee-test ALLOWED (gradual burn).
- **Beat 3 (MCP tool restriction)** ✅, agent wired to evil-mcp: no toolNames => read_internal_config
  reachable, leaks FAKE-MCP-EXFIL-sentinel-4c1d; toolNames=[get_weather] => rogue tool not exposed,
  blocked. Uses kagent's NATIVE toolNames allowlist (CNCF-native, Michael's preference), NOT
  agentgateway mcpAuthorization. Phase 4b spike resolved this way.
- Bug fixed via live test: kagent Agent `tools[]` items REQUIRE a `type: McpServer` discriminator
  (committed fix in agent/kagent-agent.yaml).
ALL THREE beats + all rev4-new pieces (cost counter, block-list, minimal-floor) now verified live.
Remaining build: three-cluster fleet orchestration, attendee UI + system-prompt streaming, runtime
guard toggles (counter persistence), output tool-call HITL+notify, facilitation polish.
- Infra fixes landed: EBS CSI driver + default gp3 SC (EKS ships neither); IRSA for
  agent-sa -> Bedrock. Deleted kagent's default agent fleet (broken default OpenAI config).
- DEFERRED: kube-prometheus-stack install wedged on the test cluster; redo (lighter,
  Tempo+Grafana focus) at the observability step.

## Verification method

Research-based for unbuilt parts; LIVE-on-EKS for Beat 1 and the agent (above). "Verified" in research notes = confirmed against
current docs, not against a running build.

## Unverified, load-bearing, build-spike BEFORE committing as live

1. **agentgateway `mcpAuthorization` CEL tool-deny actually enforces on the Apache OSS
   build with a kagent A2A agent in front.** If it doesn't, the bad-MCP beat ships as a
   recorded segment + governance-map row, not a live toggle. (research/04)
2. **agentgateway native response webhook fires for a kagent A2A endpoint**, moot if
   sidecar is primary, but verify before relying on the gateway path. (research/02)
3. **kagent emits `gen_ai.*` / `execute_tool` spans and the content-capture flag name** , 
   the trace narration depends on it. (research/05)
4. **ArgoCD application-controller SA identity INSIDE the vCluster** for the drift-policy
   exclude; wrong exclude either deadlocks self-heal or lets attack 3 through. (research/06)
5. **kagent `requireApproval` runtime enforcement** through the serving path. (research/01)
6. RAM: `Sensitive` NER model per-vCluster likely breaks the 1.5–2.5 GB/vCluster budget , 
   use a shared LLM Guard service or output-`Regex`-only. (research/03)

## Branch / repo status

- Repo: github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn (private, SSH).
- Prose/spec/research repo today → commits go directly to `main` (per updated branch rule).
  Flip to staging→main flow once real build code (Terraform/Helm/scripts) lands.
- `staging` branch exists at the initial commit; currently unused.

## Open decisions still owned by Michael (BUILD-SPEC §10)

Attendee count + ceiling; access model; co-speaker split; 90 vs 120 min; host provider
(EKS default); whether to build the OTel re-leak advanced beat or keep it slide-only.

## SESSION CLOSE 2026-06-19, fleet + presentation done (offline)
- Three-cluster fleet (task #7) authored: gitops/bootstrap/app-of-apps-burn.yaml (C1 burn profile,
  directory.include subset, no enforcing policies), full app-of-apps for C2/C3; minimal-floor split to
  policies/floor; deploy-full-idp.sh takes a profile (full|burn). VERIFY-AT-BUILD: the burn include-glob
  + C1 composition not yet live-tested (no cluster up).
- Presentation: slides-outline rebuilt with a two-tier hook (personal incident -> enterprise stakes:
  data/revenue/reputation/compliance/cost + shared-network blast radius), cold-open script for slides 2-3
  (facilitation/cold-open-script.md). All public-facing docs audit-clean (0 em-dashes).
- 2-hour slot confirmed (Day 1 2:20-4:20pm Track 5) folded through all docs; runbook is 120-min primary.
- Cluster deleted -> $0. Everything on staging.
- REMAINING (not done): live-verify the fleet profiles on a provision; build the actual slide deck;
  speaker notes for non-hook slides (Michael has these); custom Backstage image; system-prompt streaming UI.
