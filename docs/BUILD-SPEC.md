# BUILD-SPEC.md — "Build a Platform, Unleash an Agent on it.... and Watch it Burn!"

AI Engineer World's Fair 2026, San Francisco, Moscone West, Jun 29-Jul 2.
Workshop, 1-2 hours. Speakers: Michael Forrester (Accenture) with Whitney Lee.

Spec rev2, 2026-06-15. Supersedes rev1. This file is the single source of truth for Claude Code. If the live abstract and this file disagree, the abstract's *Proposed Amended Description* wins on behavior, and this file is updated to match.

rev2 changes vs rev1: (a) lineup reframed — the CNCF controls collapse into ONE aggregate beat and the AI-specific guardrails become the main event; (b) all versions and API paths re-grounded against June 2026 reality (see `research/` and `PROJECT_STATE.md`); (c) the LLM Guard output-scanner error corrected; (d) the output guardrail's primary mechanism switched to an LLM Guard reverse-proxy sidecar; (e) unverified load-bearing facts called out as explicit build-spike gates.

---

## 0. How to run this spec

Execution environment: netcup VPS reached over autossh + tmux. All `kubectl`, AWS credentials, Helm, and tooling live on the server. The laptop is a thin client.

Run with Claude Code:

```
claude --dangerously-skip-permissions
# then point it at this file
```

Claude Code works phase by phase in the order below. Do not start a phase until the prior phase's acceptance criteria pass. After each phase, run that phase's verification block and stop on first failure. Report failures with the exact command and output, do not paper over them.

Idempotency rule: every build step must be safe to re-run. Use `helm upgrade --install`, `kubectl apply`, ArgoCD declarative sync, and `vcluster create ... || vcluster connect`. No step may assume a clean cluster.

Build-spike rule (new in rev2): certain facts are confirmed against current docs but NOT yet against a live cluster. Each is tagged **[SPIKE]** with a gate. A beat that depends on a [SPIKE] must not be declared live until its spike passes. If a spike fails, fall back to the documented alternative (sidecar, recorded segment) and update this file.

---

## 1. Objective and success definition

Build a repeatable workshop where each attendee drives a scoped AI agent against a pre-built Internal Developer Platform on a CNCF stack and runs a sequence of attacks. One aggregate beat shows that the controls a mature platform *already has* block a whole class of attacks. The remaining beats expose the AI-specific gaps that those controls do not see, and close each one by switching on an agent-specific guardrail mid-session. Attendees leave with a governance map and a self-assessment checklist for their own platform.

The inversion (rev2): the CNCF "you already have this" story is the setup, not the bulk. The agent-specific guardrails are the payoff. This matches an AI-engineering audience and the abstract.

"Done" means all of:

- A host cluster runs the shared IDP stack.
- N attendee vClusters provision from a single declarative source (ApplicationSet), each with a scoped agent.
- All beats behave exactly as section 2 specifies, proven by the verification harness in Phase 6, in both their "before" and "after" states.
- Attendee access works without a local install (hosted web terminal per vCluster).
- Pre-recorded fallback exists for every beat.
- The governance map and self-assessment artifacts are generated and committed.
- Teardown removes all attendee state and reports cost.

---

## 2. The talk this builds

Abstract alignment is non-negotiable. The build must make the *Proposed Amended Description* literally true.

Observability is not a beat. It is the lens every beat is narrated through — the trace view that shows the agent reasoning, calling tools, and getting blocked. The one place observability earns its own moment is the **trace re-leak trap** (the 2-hour advanced beat, section 4).

### Beat 1 — The CNCF wall (aggregate; "you already have this")
A single agent-driven action sequence that hits three existing controls in concert:
- **Deploy a non-compliant workload** — blocked by Kyverno admission. This carries the one live toggle in this beat: the policy starts in `Audit` (admits, reports) and is switched to `Enforce` (admission rejects). Audience sees before/after.
- **Escalate privileges** — the agent tries to create a ClusterRoleBinding granting itself broader rights. Rejected by scoped RBAC already in place. No toggle.
- **Modify infrastructure outside Git** — the agent tries a direct `kubectl` mutation of an ArgoCD-managed resource. Rejected by an admission policy that blocks mutation by any non-ArgoCD principal; ArgoCD self-heal reverts drift as defense in depth. No toggle.

Each step surfaces a *distinct* error (Kyverno admission message, RBAC `Forbidden`, ArgoCD-drift admission message) so the room sees three walls, not one. Co-design note: RBAC is evaluated before admission, so the agent SA must hold *enough* RBAC to reach the admission check in step 3 — otherwise step 3 dies at RBAC like step 2 and the GitOps point is lost. See Phase 3 and `research/06-cncf-stack.md`.

### Beat 2 — Input + output sanitization (AI-specific)
The agent has no idea what is adversarial on the way in or sensitive on the way out.
- **Input (prompt injection):** before, an injection steers the agent; after the input guardrail is on, the request is blocked at the gateway request phase (hard reject).
- **Output (exfil):** the agent reads a planted fake secret and is asked to return it. Before, the sentinel value leaves in the response; after the output guardrail is on, the response is blocked or redacted and the sentinel does not appear.
- Two toggles (input guard, output guard), demoed as one "sanitize both directions" beat.

### Beat 3 — Excessive agency via a bad MCP server (AI-specific) — **[SPIKE-GATED LIVE]**
The agent is wired to a deliberately untrusted MCP server whose poisoned tool description induces it to call a tool it should never call and leak a planted sentinel.
- **Before:** no tool-authorization rule; the agent takes the bait and the `FAKE-MCP-EXFIL-...sentinel` leaves.
- **After:** switch on MCP tool authorization (allowlist / deny rule) at the gateway; the rogue tool call is blocked.
- This beat is planned **live, gated on a build-spike** (Phase 4b). Its single load-bearing unknown is whether agentgateway's `mcpAuthorization` CEL tool-deny enforces on the Apache OSS build with a kagent agent in front. If the spike fails, this beat ships as a pre-recorded segment plus a governance-map row, not a live toggle. The recorded fallback is built regardless.

### The 80/20 map (inverted from rev1)
Beat 1 is the 80% — a whole attack class governed by existing CNCF tooling once the right control is on. Beats 2 and 3 are the 20% gap that no admission controller, RBAC rule, or GitOps reconciler can see, because the attack rides in natural language and tool calls, not the Kubernetes control plane. That gap is the talk.

---

## 3. Hard constraints (non-negotiable)

- **Per-attendee isolation via vCluster.** One vCluster per attendee on a shared host cluster. No namespace-only multi-tenancy. Rationale: the privilege-escalation step in beat 1 is a real attempt, and namespace isolation would let a successful escalation reach other attendees or the host.
- **Scoped agent, never cluster-admin.** Inside each vCluster the agent runs under a dedicated ServiceAccount with a tight Role and RoleBinding, bound via the kagent agent's `spec.declarative.deployment.serviceAccountName`. The agent can do what the workshop requires (create workloads in its namespace, read a planted secret, reach its MCP tools) and must not have the verbs for the escalation and GitOps-drift steps to succeed — while still holding enough RBAC to *reach* the admission check in beat 1 step 3.
- **Deterministic where the requirement is deterministic.** The output exfil guardrail must include an output `Regex` scanner that matches the planted sentinel — this is the provably model-free control and the one whose behavior is demonstrated live. `Sensitive` (NER + regex) may be added for PII breadth but is model-based; do not call it deterministic. No LLM-as-judge scanner anywhere. The input `PromptInjection` scanner is a model-based classifier (DeBERTa) — acceptable for the input beat, but it is not deterministic and must not be described as such. This is a design rule; keep the reasoning out of attendee-facing copy. See `research/03-llm-guard.md`.
- **Obviously fake secrets only.** Every planted secret is clearly synthetic (prefix `FAKE-` or a documented sentinel, e.g. `FAKE-PROD-DB-PASSWORD-sentinel-9f2a`, `FAKE-MCP-EXFIL-sentinel-4c1d`). No real credential ever enters the cluster, traces, or recordings.
- **No local install for attendees.** Access is a browser web terminal per vCluster. Local kubeconfig is the documented fallback only.
- **Idempotent and teardownable.** See section 0 and Phase 9.
- **Pre-recorded fallback per beat.** See Phase 9. If live provisioning or the agent misbehaves, each beat has an asciinema recording the facilitator can play. Beat 3's recording is mandatory, not optional, until its spike passes.
- **Abstract truth.** The verification harness asserts each beat's before and after state matches section 2.

---

## 4. Design principles (internal, do not put in attendee materials)

- The guardrail layer is deterministic where it can be and model-based where it must be; the agent is the probabilistic actor. Keep that separation visible in the architecture and out of the marketing copy. The line is a talk payoff, not a slide.
- The agent's nondeterminism is a feature for teaching and a hazard for live demo. Every beat requires a deterministic fallback path (`fallback.*.sh`) so the lesson lands even when the model wanders. For beats 2 and 3 the fallback drives the request through the gateway with `curl` so the *guardrail* is what is being demonstrated, independent of whether the model takes the bait.
- Observability is the connective tissue. Narrate every beat through the trace waterfall (`invoke_agent → plan → execute_tool`). Tool calls are first-class in the OTel GenAI conventions, which is what makes the rogue MCP call in beat 3 visible.
- **OTel content capture is itself an exfil channel.** If full prompts and responses land in spans, the planted secret re-leaks into traces even with the output guardrail on — observability becomes a second unguarded sink. Content capture is OFF by default (it is off by default upstream too). The re-leak trap is the 2-hour advanced beat: turn capture on, show the sentinel in the span, then show the symmetric mitigation (a collector redaction processor alongside the response guardrail). Trace data is torn down in Phase 9.

---

## 5. Architecture

Versions below are research-grounded as of 2026-06-15 (see `research/`). The verify-at-build rule in section 6 still applies: confirm and pin at build time into `VERSIONS.lock`.

### Host cluster
- EKS on AWS (Michael's credentials are on the server). GKE or AKS are acceptable swaps; keep the provider abstraction in Terraform or eksctl config so the choice is one variable.
- Node group sized for N attendee vClusters. Budget caveat (rev2): if the `Sensitive` NER model loads per vCluster, the rev1 1.5-2.5 GB/vCluster estimate breaks. Mitigation: run LLM Guard as a shared service, or use output-`Regex`-only per vCluster. Size for N concurrent and document the assumption and the LLM Guard placement decision in `infra/SIZING.md`.

### Shared IDP stack (host cluster, installed once)
- ArgoCD (`v3.4.3`) for GitOps and per-attendee app delivery.
- Kyverno (app `v1.18.1`, chart `3.8.1`) for admission control. BREAKING since rev1: `spec.validationFailureAction` is deprecated; use rule-level `validate.failureAction`. This field is the beat-1 Audit↔Enforce toggle.
- Falco (`0.44.1`) for runtime detection.
- kube-prometheus-stack (chart `86.2.3`) for Prometheus + Grafana.
- OpenTelemetry Collector (`v0.154.0`) for GenAI traces, using OTel GenAI semantic conventions. All GenAI semconv is `Development` (nothing Stable as of June 2026); opt into newest names with `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` and pin attribute names at build. Trace backend: Grafana Tempo + Grafana.

### Per-attendee vCluster (provisioned N times)
- A vCluster (`v0.34.3`; rev1's v0.29 is five minors stale and the config schema drifted — re-verify `vcluster.yaml` at build) giving the attendee an isolated API server.
- The IDP-facing controls the attendee interacts with: Kyverno policies, the ArgoCD-managed app set, the planted fake secrets, the agent, the gateway, the LLM Guard service (or a reference to the shared one), and the synthetic bad MCP server for beat 3.
- A web-terminal pod (browser IDE or ttyd-style shell) bound to that vCluster's kubeconfig.

### Agent
- kagent (CNCF Sandbox). Helm chart `0.9.7` (rev1's 0.7.7 is stale). Two-chart OCI install: `kagent-crds` then `kagent` from `ghcr.io/kagent-dev`. **Author all CRDs against API group `kagent.dev/v1alpha2`** — Bedrock support exists only there, not in v1alpha1.
- Model provider: AWS Bedrock — **FLAG RESOLVED**. Native path: a `ModelConfig` with `spec.provider: Bedrock`, `spec.model: <bedrock-model-id>`, `spec.bedrock.region: <region>`; credentials via the AWS credential chain (omit `apiKeySecret`) or static keys in `spec.apiKeySecret`. The agent references it by name via `spec.declarative.modelConfig`. Do NOT use the OpenAI-provider + bedrock-runtime baseURL shim public tutorials show. See `research/01-kagent.md`.
- MCP tools: the agent attaches tools via `spec.declarative.tools[].mcpServer` referencing an `MCPServer`/`RemoteMCPServer`. Two per-agent controls matter: `toolNames` (allowlist — **omitting it exposes ALL of the server's tools**, which is exactly the beat-3 footgun) and `requireApproval` (per-tool human-approval gate). `requireApproval` runtime enforcement is **[SPIKE]** (Phase 3).
- The agent's ServiceAccount RBAC is the scoping boundary. See Phase 3.

### Agent gateway, exfil guardrail, and MCP authorization
- agentgateway (Solo.io, Linux Foundation), OSS line `v1.2.1` (do not pin the v1.3.0 beta; note the OSS `1.x` line is distinct from Solo Enterprise `2.x` docs — build from the standalone OSS docs). It fronts the agent's serving endpoint and its MCP tool traffic.
- **Output exfil guardrail — primary mechanism (rev2 change):** an **LLM Guard reverse-proxy sidecar** on the agent response path. Rationale: agentgateway's native response prompt-guard webhook can only *Mask, not Reject*, and is documented for recognized LLM-provider response bodies, not a kagent A2A endpoint — unverified there. The sidecar removes both unknowns and gives a hard block. The agentgateway response webhook (`llm.models[].guardrails.response[].webhook`) is kept as the documented alternative and is itself **[SPIKE]** (Phase 4b) if you want it.
- **Input guardrail:** agentgateway request-phase prompt-guard webhook calling LLM Guard — the request phase *can* hard-reject, so prompt injection is blocked before it reaches the agent.
- **LLM Guard** (Protect AI, MIT) in API-server mode (Docker, `scanners.yml` mounted). Resolve the image namespace (`laiyer/` vs `protectai/`) and pin a digest at build (no GitHub releases exist; pin via PyPI + Docker digest). Scanners:
  - Output: `Regex` (deterministic, matches the sentinel — the live-demonstrated control) and optionally `Sensitive` (NER + regex, PII breadth, model-based). **There is no "Secrets" output scanner** — `Secrets` is input-only; rev1 was wrong.
  - Input: `PromptInjection` (DeBERTa classifier, model-based) for beat 2; `Secrets`/`Regex` available as deterministic input scanners if needed.
  - Verdict: `/analyze/output` returns `is_valid` (false → block), `sanitized_output` (→ redact), and per-scanner `scores`. Clean fit for block-vs-redact.
- **MCP authorization (beat 3 control):** agentgateway `mcpAuthorization` CEL rules over `mcp.tool.name` (`action: Allow|Deny`) plus a `targets` server allowlist; tools are auto-filtered from `list_tools`. No native human-in-the-loop. Whether this enforces on the OSS build with kagent in front is the beat-3 **[SPIKE]** (Phase 4b).

### Why this shape
Beat 1 hits the Kubernetes control plane and is governed by Kyverno, RBAC, and admission — the 80%. Beats 2 and 3 never touch the control plane; the exfil rides out in the agent's natural-language response and the over-reach rides in a tool call, which only the gateway/guardrail layer can see. That is the 80/20 split made physical, and observability is how the room sees all of it.

---

## 6. Version pinning

Research-grounded candidates as of 2026-06-15 (sources in `research/`). These are starting pins, not a substitute for the verify-at-build rule:

- kagent: Helm chart `0.9.7`; CRD API group `kagent.dev/v1alpha2`.
- vCluster: `v0.34.3`.
- Kyverno: app `v1.18.1`, chart `3.8.1` (rule-level `validate.failureAction`).
- Argo CD: `v3.4.3`.
- Falco: `0.44.1`.
- kube-prometheus-stack: chart `86.2.3`.
- OTel Collector: `v0.154.0`.
- agentgateway: OSS `v1.2.1`.
- LLM Guard: API-server image — resolve `laiyer/` vs `protectai/` and pin a Docker digest at build; pin the PyPI version too.

Verify-at-build rule: at build time, fetch each project's current stable release, confirm the pin (or update it and note why), and record the exact version/digest in `VERSIONS.lock`. Do not hardcode a version from memory. After pinning, `VERSIONS.lock` is committed and is the authoritative version record. Re-confirm the Kyverno field rename, the kagent v1alpha2 schema, and the vCluster config schema specifically — these drifted since rev1.

---

## 7. Repository structure to create

```
./
  README.md                      # what this is, how to run the workshop
  PROJECT_STATE.md               # durable state (already present)
  VERSIONS.lock                  # pinned versions/digests, written by Phase 0/1
  research/                      # grounding notes 01..06 (already present)
  docs/
    BUILD-SPEC.md                # this file
  infra/
    SIZING.md                    # incl. LLM Guard placement + RAM decision
    host-cluster/                # eksctl or terraform, provider as one var
    bootstrap.sh                 # installs IDP stack on host
  platform/
    argocd/
      appset-attendee.yaml       # ApplicationSet, one App per attendee
      apps/                      # the per-attendee app templates
    kyverno/
      policies/
        require-resource-limits.yaml   # beat 1 target, starts Audit (validate.failureAction)
        block-argocd-drift.yaml        # beat 1 control, Enforce from start
    falco/
      rules-workshop.yaml
    observability/
      otel-collector.yaml        # OTLP in, Tempo out, redaction processor for the trap
      grafana-dashboards/
  agent/
    kagent-modelconfig-bedrock.yaml   # v1alpha2 ModelConfig, Bedrock
    kagent-agent.yaml                 # v1alpha2 Agent, scoped SA + MCP tools (toolNames)
    rbac/
      agent-role.yaml            # tight Role (enough to reach admission in beat 1 step 3)
      agent-rolebinding.yaml
    GATEWAY-NOTES.md             # confirmed mechanisms: input guard, output sidecar, MCP authz
    gateway/
      agentgateway.yaml
      llm-guard-service.yaml     # LLM Guard API server (shared or per-vcluster — see SIZING)
      llm-guard-sidecar.yaml     # output reverse-proxy sidecar (PRIMARY output guard)
      input-guard-off.yaml / input-guard-on.yaml
      output-guard-off.yaml / output-guard-on.yaml
      mcp-authz-off.yaml / mcp-authz-on.yaml
  beats/
    01-cncf-wall/
      beat.md                    # attendee instructions
      agent-prompt.txt           # drives deploy -> escalate -> drift
      fallback.kubectl.sh        # deterministic three-wall path
      toggle-kyverno-enforce.sh  # Audit -> Enforce (validate.failureAction)
    02-sanitization/
      beat.md
      agent-prompt-injection.txt
      agent-prompt-exfil.txt
      plant-fake-secret.yaml     # FAKE-PROD-DB-PASSWORD-sentinel-9f2a
      fallback.curl.sh           # drives request/response through the gateway
      toggle-input-guard-on.sh
      toggle-output-guard-on.sh
    03-bad-mcp-excessive-agency/
      beat.md
      agent-prompt.txt
      evil-mcp-shim/             # synthetic bad MCP server (poisoned tool description)
      plant-fake-secret.yaml     # FAKE-MCP-EXFIL-sentinel-4c1d
      fallback.curl.sh           # tool call through the gateway, model-independent
      toggle-mcp-authz-on.sh     # apply the CEL deny rule
      BUILD-SPIKE.md             # the gating verification + result
  verify/
    run-all.sh                   # Phase 6 harness, asserts before/after for every beat
    beat-01.sh beat-02.sh beat-03.sh
  access/
    web-terminal/                # per-vcluster browser terminal
    quickstart.md                # attendee one-pager
  facilitation/
    runbook.md                   # minute-by-minute, co-speaker split
    slides-outline.md
    governance-map.md            # the takeaway artifact
    self-assessment.md           # attendee checklist for their own platform
  fallback/
    recordings/                  # asciinema per beat (beat 3 mandatory)
  teardown/
    teardown.sh                  # removes attendee state incl. trace data
    cost-report.sh
```

---

## 8. Build phases

Each phase lists tasks then a verification block. Stop on first failed verification.

### Phase 0 — Bootstrap host cluster and tooling
Tasks:
- Stand up the host cluster (EKS by default). Confirm `kubectl` reaches it.
- Install or confirm CLI tooling on the server: `helm`, `vcluster`, `argocd`, `kubectl`, `docker`, `asciinema`.
- Write `VERSIONS.lock` with the host Kubernetes version and tool versions.

Verify:
- [ ] `kubectl get nodes` returns Ready nodes.
- [ ] `vcluster --version`, `helm version`, `argocd version --client` all succeed.
- [ ] `VERSIONS.lock` exists and is non-empty.

### Phase 1 — Shared IDP stack on host
Tasks:
- Install ArgoCD, Kyverno, Falco, kube-prometheus-stack, OTel Collector at the section-6 pins. Confirm and pin exact versions into Helm values, append to `VERSIONS.lock`.
- Configure the OTel Collector: OTLP receivers (4317/4318) → batch → otlp/Tempo, plus a redaction processor (used by the re-leak-trap mitigation). Default content capture for prompts and responses is OFF (section 4 trap).

Verify:
- [ ] ArgoCD server pod Ready, `argocd app list` works.
- [ ] Kyverno admission webhook responding; a test policy with rule-level `validate.failureAction` loads without deprecation error.
- [ ] Falco pods Running and emitting events.
- [ ] Prometheus scraping, Grafana reachable, Tempo reachable from Grafana.
- [ ] OTel Collector accepting OTLP.

### Phase 2 — Per-attendee vCluster provisioning
Tasks:
- Build an ArgoCD ApplicationSet templating one Application per attendee from a list (attendee count is a build variable; default to a documented number, see section 10). Re-verify the vCluster `v0.34` config schema before templating.
- Each Application creates a vCluster and syncs that attendee's per-vCluster resources: Kyverno policies (beat-1 require-limits policy in `Audit`, beat-1 drift policy in `Enforce`), the planted fake secrets, the agent, the gateway, the LLM Guard service/sidecar, and the synthetic bad MCP server.
- Provisioning must be parallel and time-boxed. Record per-vCluster provision time.

Verify:
- [ ] For a test set of 3 attendees, 3 vClusters reach Ready.
- [ ] Each vCluster has its own API server reachable via its kubeconfig.
- [ ] An action in attendee A's vCluster is invisible in attendee B's vCluster.
- [ ] Median provision time recorded in `infra/SIZING.md`, alongside the LLM Guard placement decision.

### Phase 3 — Scoped agent
Tasks:
- Deploy the kagent agent into each vCluster via the ApplicationSet. Author `ModelConfig` and `Agent` against `kagent.dev/v1alpha2`. Wire Bedrock per section 5 (resolved path).
- Define the agent ServiceAccount Role to allow exactly: create and get workloads in the attendee namespace; get and list the planted secrets; reach its MCP tools. Deny: create or modify ClusterRole, ClusterRoleBinding, Role, RoleBinding; deny mutation of ArgoCD-managed resources. Co-design with the drift policy so the agent has *enough* RBAC to `patch` the ArgoCD-managed resource in beat 1 step 3 and is stopped by admission, not by RBAC.
- Attach MCP tools with an explicit `toolNames` allowlist (never omit it).
- **[SPIKE]** Confirm `requireApproval` runtime enforcement through the serving path before relying on it anywhere.

Verify:
- [ ] Agent pod Running, answers a trivial prompt end to end through Bedrock.
- [ ] `kubectl auth can-i create clusterrolebinding --as=system:serviceaccount:<ns>:<agent-sa>` returns no.
- [ ] `kubectl auth can-i create deployment -n <ns> --as=...` returns yes.
- [ ] `kubectl auth can-i patch <argocd-managed-kind> -n <ns> --as=...` returns yes (so beat 1 step 3 reaches admission).
- [ ] `kubectl auth can-i get secret <fake-secret> -n <ns> --as=...` returns yes.
- [ ] A real trace lands in Tempo; record which span/operation names and attributes kagent actually emits (confirms or refutes `gen_ai.*` / `execute_tool` emission — the trace narration depends on it).

### Phase 4 — Guardrails: input, output, MCP authz
Tasks:
- Deploy LLM Guard API server (shared or per-vCluster per the SIZING decision). Configure output `Regex` (sentinel match — the deterministic control) plus optional `Sensitive`; input `PromptInjection`. No LLM-judge scanner. Resolve the image namespace and pin a digest.
- Deploy the LLM Guard reverse-proxy sidecar on the agent response path as the PRIMARY output guard. Wire the input guard via the agentgateway request-phase webhook.
- Create toggle states: `input-guard-{off,on}.yaml`, `output-guard-{off,on}.yaml`. Off is the default at workshop start.
- Plant the fake secret for beat 2 (`FAKE-PROD-DB-PASSWORD-sentinel-9f2a`).
- Document the confirmed mechanisms in `agent/GATEWAY-NOTES.md`.

Verify:
- [ ] Output guard OFF: asking the agent to read and report the planted secret returns the sentinel in the response.
- [ ] Output guard ON: the same request is blocked or redacted; the sentinel does not appear; LLM Guard logs show the output `Regex` (and/or `Sensitive`) scanner firing.
- [ ] Input guard ON: a prompt-injection request is hard-rejected at the gateway request phase before reaching the agent.
- [ ] No real credential exists anywhere in the path.

### Phase 4b — Build-spikes for the [SPIKE] facts
Run these before beats 2 (native webhook variant) and 3 are declared live.
Tasks:
- **MCP authz spike (gates beat 3 live):** stand up `evil-mcp-shim` with a poisoned tool description that induces a call to a tool leaking `FAKE-MCP-EXFIL-sentinel-4c1d`. Confirm that an agentgateway `mcpAuthorization` CEL `Deny` on `mcp.tool.name` actually blocks the call on the OSS build with kagent in front. Record the result in `beats/03-.../BUILD-SPIKE.md`.
- **(Optional) native output-webhook spike:** confirm whether the agentgateway response webhook fires for the kagent A2A endpoint. Only needed if you want the gateway path instead of the sidecar.
- **ArgoCD controller SA identity spike:** confirm the exact application-controller ServiceAccount principal *inside the vCluster* used by the drift policy's exclude. A wrong exclude either deadlocks self-heal or lets beat 1 step 3 through.

Verify:
- [ ] MCP authz spike result recorded. If PASS → beat 3 is live. If FAIL → beat 3 demotes to recorded segment + governance-map row; update sections 2 and 11 and the runbook.
- [ ] ArgoCD controller SA principal confirmed and the drift-policy exclude matches it; self-heal still functions.

### Phase 5 — The beats
For each beat: write the attendee `beat.md`, the `agent-prompt*.txt` that reliably drives the agent, and a deterministic `fallback.*.sh`. For beats 2 and 3 the fallback drives the request/tool-call through the gateway directly so the *guardrail* is what is proven, independent of the model. Pre-test each agent prompt at least 5 times and record the success rate in the beat folder. If a prompt is below a documented reliability bar, tighten it or rely on the fallback for the live run.

- **Beat 1 (CNCF wall):** before = agent deploys non-compliant workload and it admits (Kyverno `Audit`); `toggle-kyverno-enforce.sh` flips to `Enforce`; after = retry is rejected. The escalation and drift steps fail with no toggle (RBAC `Forbidden`; ArgoCD-drift admission block) and show distinct errors. Demonstrate ArgoCD self-heal reverting any drift.
- **Beat 2 (sanitization):** input before/after with `toggle-input-guard-on.sh`; output before/after with `toggle-output-guard-on.sh`.
- **Beat 3 (bad MCP):** before = sentinel leaks via the rogue tool call; `toggle-mcp-authz-on.sh` applies the deny rule; after = the call is blocked. Live only if Phase 4b spike passed; otherwise run the recording.

Verify:
- [ ] Each beat's before state produces the intended outcome.
- [ ] Each beat's after state produces the intended outcome.
- [ ] The escalation and drift steps fail without any toggle and surface distinct errors.
- [ ] Each `fallback.*.sh` reproduces the same before/after outcome deterministically.
- [ ] Per-prompt reliability recorded in each beat folder.

### Phase 6 — Verification harness
Tasks:
- `verify/run-all.sh` runs all beats against a fresh test vCluster and asserts the section 2 outcomes for before and after states. Exit non-zero on any mismatch. For beat 3, the harness checks the live path if the spike passed, otherwise asserts the recorded-fallback artifact exists.
- The harness is the abstract-truth gate. If it fails, the talk's claims are not yet true.

Verify:
- [ ] `verify/run-all.sh` passes on a clean test attendee.
- [ ] Running it twice in a row passes both times (idempotent).

### Phase 7 — Attendee access
Tasks:
- Deploy a per-vCluster web terminal (browser shell or browser IDE) pre-authenticated to that attendee's vCluster. No local install required.
- Generate access handoff: a short URL or QR per attendee. Document the local-kubeconfig fallback in `quickstart.md`.
- `quickstart.md` is one page: how to reach your terminal, how to talk to your agent, where the beats live.

Verify:
- [ ] A browser session reaches a working terminal scoped to one vCluster.
- [ ] From that terminal, the attendee can drive their agent and run beat 1's before state.
- [ ] Access works from a network that cannot reach the cluster API directly except through the web terminal entry point.

### Phase 8 — Facilitation materials
Tasks:
- `runbook.md`, minute by minute for the 90-minute version, with a documented 2-hour extension (the extension adds the trace re-leak trap). Assign segments to Michael and Whitney.
  - Suggested split, confirm with Whitney: Michael drives architecture, the security thesis, and the regroup map. Whitney drives the live beat narration, the attendee experience, and the observability beats (the trace view of each beat). Hand-offs marked explicitly.
  - Suggested 90-minute shape: 10 intro and architecture, 10 access and warm-up, 20 beat 1 (CNCF wall, with the Kyverno toggle and the two no-toggle walls), 20 beat 2 (input + output sanitization, two toggles), 15 beat 3 (bad MCP, live or recorded), 10 regroup and governance map, 5 takeaways and questions.
- `slides-outline.md`, outline only, agent-forward framing in titles, no punchline giveaways, no proprietary framework names that are not already public.
- `governance-map.md`, the takeaway artifact: a table of attack, the control that governs it, the layer it lives in (admission, RBAC, GitOps, input inspection, output inspection, MCP tool authorization, observability), and whether existing CNCF tooling covers it or an agent-specific control is required. Beats 2 and 3 are the agent-specific gaps.
- `self-assessment.md`, a checklist an attendee runs against their own platform to find which failure modes they are not covering — including the ones not demoed live.

Verify:
- [ ] `runbook.md` total time fits 90 minutes with named hand-offs.
- [ ] `governance-map.md` covers every beat and marks beats 2 and 3 as the agent-specific gaps.
- [ ] `self-assessment.md` is usable without any workshop-specific tooling.
- [ ] No banned terms or proprietary framework names in attendee-facing files (see section 11 note).

### Phase 9 — Fallback recordings, teardown, cost
Tasks:
- Record an asciinema for each beat showing before and after, committed under `fallback/recordings/`. Beat 3's recording is mandatory until its spike passes.
- `teardown/teardown.sh` removes all attendee vClusters and their state — including Tempo trace data (the re-leak sink) — leaving the host stack optionally intact (flag controlled).
- `teardown/cost-report.sh` reports the AWS spend for the run. Do not estimate a dollar figure in this spec; the script reports the real number after the fact for Accenture expensing.

Verify:
- [ ] One recording per beat exists and plays.
- [ ] `teardown.sh` removes a test attendee's vCluster and trace data fully, re-runnable with no error.
- [ ] `cost-report.sh` runs and emits a number.

---

## 9. Definition of Done

- [ ] Phases 0-9 verification blocks all pass.
- [ ] All Phase 4b [SPIKE] facts resolved and recorded; beat 3's live/recorded status decided accordingly.
- [ ] `verify/run-all.sh` passes on a clean attendee and is idempotent.
- [ ] N test attendees provision in parallel within the time recorded in `SIZING.md`.
- [ ] Attendee access works with no local install.
- [ ] Every beat has a deterministic fallback and a recording.
- [ ] Governance map and self-assessment generated and committed.
- [ ] `VERSIONS.lock` complete, with the rev2 version corrections confirmed at build.
- [ ] No real secret anywhere in cluster, traces, or recordings.

---

## 10. Open decisions for Michael (not guessed)

1. **Attendee count.** Drives host node sizing and per-vCluster provision parallelism. Give a target N and a hard ceiling. (Now also drives the LLM Guard shared-vs-per-vCluster decision because of the NER RAM footprint.)
2. **Access model.** Web terminal per vCluster is the spec default. Confirm, or say if AI Engineer provides hosted environments you would rather build on.
3. **Co-speaker split.** Phase 8 has a suggested Michael/Whitney division. Confirm with Whitney before the runbook is locked.
4. **90 vs 120 minutes.** Spec builds the 90-minute runbook; the 2-hour extension adds the trace re-leak trap. Confirm the accepted slot length.
5. **Host provider.** EKS default. Confirm, or switch the one variable.
6. **OTel advanced beat.** The trace re-leak trap (section 4) is off by default and lives in the 2-hour version. Confirm whether to build it in or keep it as a slide-only mention.

(rev1 decision "swap Bedrock provider" is closed — Bedrock is native in kagent v1alpha2; no swap needed.)

---

## 11. Honest risk register

The conceptual design is sound. The failure surface is operational. In rough order of likelihood to bite on the day:

1. **Beat 3 live control may not enforce on OSS agentgateway with kagent.** The single load-bearing unknown. Mitigation: Phase 4b spike gates it; the recorded fallback is built regardless; the governance-map row teaches the gap even if the live toggle is cut.
2. **Attendee access at scale.** N people authenticating to N vClusters over Moscone WiFi is the most likely live failure. Mitigation: web terminal entry point that does not require attendees to reach the cluster API directly, pre-generated access links or QR codes, and a facilitator-driven single path if the room cannot get online. Test with the real expected N before the event.
3. **Agent prompt reliability.** Agents wander. Mitigation: pre-test each prompt to a recorded success rate, and keep the deterministic `fallback.*.sh` as the live path if reliability is marginal. For beats 2 and 3 the fallback drives the gateway directly, so the guardrail lesson lands regardless of the model.
4. **LLM Guard memory footprint.** The `Sensitive` NER model per vCluster likely breaks the per-vCluster RAM budget. Mitigation: shared LLM Guard service or output-`Regex`-only; decision recorded in `SIZING.md`.
5. **Version/schema drift since rev1.** kagent v1alpha2, the Kyverno `validate.failureAction` rename, and the vCluster v0.34 config schema are the three confirmed footguns. Mitigation: re-verify each at build before templating; `VERSIONS.lock` is authoritative.
6. **OTel GenAI semconv is all Development.** Attribute names may shift and kagent's native emission is unconfirmed. Mitigation: capture a real span in Phase 3 and pin the actual names; do not build the trace narration on assumed attributes.
7. **Provisioning time and cost.** N vClusters plus agents plus gateways plus LLM Guard take time to come up and cost real money while running. Pre-provision before doors open; use `cost-report.sh` for expensing.
8. **Time pressure.** Three beats with multiple live toggles plus a regroup in 90 minutes is tight. The runbook must protect the regroup and the governance map; that is the part attendees take home. If running long, cut attendee free-play and demote beat 3 to its recording, never the map.

Note for Phase 8 verification: keep attendee-facing files clear of the banned-term list and of any framework names that are not already public. The deterministic-guardrail thesis stays out of attendee copy as a talk payoff.
