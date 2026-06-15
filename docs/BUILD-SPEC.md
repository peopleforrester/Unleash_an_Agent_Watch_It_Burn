# BUILD-SPEC.md — "Build a Platform, Unleash an Agent on it.... and Watch it Burn!"

AI Engineer World's Fair 2026, San Francisco, Moscone West, Jun 29-Jul 2.
Workshop, 1-2 hours. Speakers: Michael Forrester (Accenture) with Whitney Lee.

Spec rev1, 2026-06-09. This file is the single source of truth for Claude Code. If the live abstract and this file disagree, the abstract's *Proposed Amended Description* wins on behavior, and this file is updated to match.

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

---

## 1. Objective and success definition

Build a repeatable workshop where each attendee drives a scoped AI agent against a pre-built Internal Developer Platform and runs four attacks. Two attacks are blocked by controls already in place. Two are blocked only after a guardrail is switched on mid-session, and one of those two stays open until an agent-specific control is added. Attendees leave with a governance map and a self-assessment checklist for their own platform.

"Done" means all of:

- A host cluster runs the shared IDP stack.
- N attendee vClusters provision from a single declarative source (ApplicationSet), each with a scoped agent.
- All four attacks behave exactly as section 5 specifies, proven by the verification harness in Phase 6, in both their "before" and "after" states.
- Attendee access works without a local install (hosted web terminal per vCluster).
- Pre-recorded fallback exists for every attack.
- The governance map and self-assessment artifacts are generated and committed.
- Teardown removes all attendee state and reports cost.

---

## 2. The talk this builds

Abstract alignment is non-negotiable. The build must make the *Proposed Amended Description* literally true.

The four attacks and their intended outcomes:

1. Deploy a non-compliant workload. Runs first because nothing stops it yet. Switch on the Kyverno policy, run again, admission rejects it. (Live toggle.)
2. Escalate privileges. Rejected by a control already in place: the agent's scoped RBAC inside its vCluster denies the verbs needed to create cluster-scoped bindings.
3. Modify infrastructure outside Git. Rejected by a control already in place: an admission policy blocks mutation of ArgoCD-managed resources by anyone other than the ArgoCD service account. ArgoCD self-heal is defense in depth.
4. Exfiltrate data through the agent's own response. Works first because no existing tool inspects what the agent says back. Switch on the agent-specific output guardrail, run the same attempt, it gets blocked. (Live toggle.)

The 80/20 map: attacks 1, 2, 3 are governed by existing CNCF tooling once the right control is on, that is the 80%. Attack 4 is the 20% gap, closed only by agent-specific output inspection.

---

## 3. Hard constraints (non-negotiable)

- **Per-attendee isolation via vCluster.** One vCluster per attendee on a shared host cluster. No namespace-only multi-tenancy. Rationale: attack 2 is a real privilege-escalation attempt, and namespace isolation would let a successful escalation reach other attendees or the host.
- **Scoped agent, never cluster-admin.** Inside each vCluster the agent runs under a dedicated ServiceAccount with a tight Role and RoleBinding. The agent can do what attacks 1 and 4 require (create workloads in its namespace, read a planted secret) and must not have the verbs for attacks 2 and 3 to succeed.
- **Deterministic guardrails for deterministic requirements.** The exfil output guardrail uses LLM Guard's deterministic scanners (Secrets via detect-secrets entropy plus regex, and Sensitive via NER and regex). It must not use any LLM-as-judge scanner. This is a design rule. Do not surface the reasoning in attendee-facing copy.
- **Obviously fake secrets only.** Every planted secret is clearly synthetic (prefix `FAKE-` or a documented sentinel). No real credential ever enters the cluster, traces, or recordings.
- **No local install for attendees.** Access is a browser web terminal per vCluster. Local kubeconfig is the documented fallback only.
- **Idempotent and teardownable.** See section 0 and Phase 9.
- **Pre-recorded fallback per attack.** See Phase 9. If live provisioning or the agent misbehaves, each attack has an asciinema recording the facilitator can play.
- **Abstract truth.** The verification harness asserts each attack's before and after state matches section 2.

---

## 4. Design principles (internal, do not put in attendee materials)

- The guardrail layer is deterministic. The agent is the probabilistic actor. Keep that separation visible in the architecture and invisible in the marketing copy. The line itself is a talk payoff, not a slide.
- The agent's nondeterminism is a feature for teaching and a hazard for live demo. Section 5 requires a deterministic fallback path so the lesson lands even when the model wanders.
- OTel content capture is itself an exfil channel. If full prompts and responses land in spans, the planted secret re-leaks into traces. This is the advanced beat in the 2-hour version, and a trap to avoid by default.

---

## 5. Architecture

### Host cluster
- EKS on AWS (Michael's credentials are on the server). GKE or AKS are acceptable swaps; keep the provider abstraction in Terraform or eksctl config so the choice is one variable.
- Node group sized for N attendee vClusters. Each vCluster control plane plus an agent plus a gateway plus an LLM Guard service is roughly 1.5-2.5 GB RAM and a fraction of a core when idle. Size for N concurrent and document the assumption in `infra/SIZING.md`.

### Shared IDP stack (host cluster, installed once)
- ArgoCD for GitOps and per-attendee app delivery.
- Kyverno for admission control.
- Falco for runtime detection.
- Prometheus plus Grafana for metrics.
- OpenTelemetry Collector for GenAI traces, using OTel GenAI semantic conventions.

### Per-attendee vCluster (provisioned N times)
- A vCluster (v0.29 line as of April 2026, verify at build) giving the attendee an isolated API server.
- The IDP-facing controls the attendee interacts with: Kyverno policies, the ArgoCD-managed app set, the planted fake secret, the agent, the gateway, the LLM Guard service.
- A web-terminal pod (browser IDE or ttyd-style shell) bound to that vCluster's kubeconfig.

### Agent
- kagent (CNCF Sandbox). Helm chart `0.7.7` as of April 2026, verify at build. CRD-driven agent definition.
- Model provider: AWS Bedrock. FLAG: public kagent tutorials use OpenAI. Confirm the Bedrock model-config path in kagent at build time before wiring it. Do not assume the field names.
- The agent's ServiceAccount RBAC is the scoping boundary. See Phase 3.

### Agent output gateway and exfil guardrail
- agentgateway (Solo.io, Linux Foundation) in front of the agent's serving endpoint, so the agent's response to the user passes through an inspection point.
- LLM Guard running in API server mode (Docker image, MIT, Protect AI) as a service in the vCluster. Output scanners: Secrets and Sensitive, both deterministic.
- Toggle: the agentgateway output guardrail filter is enabled or disabled. Off, the secret leaves in the response. On, the response is blocked or redacted.
- FLAG: the exact agentgateway filter mechanism (external processing vs native plugin) may have moved since January. Confirm against current agentgateway docs at build time and pin the working mechanism in `agent/GATEWAY-NOTES.md`.

### Why this shape
Attacks 1, 2, 3 hit the Kubernetes control plane and are governed by Kyverno, RBAC, and admission. Attack 4 never touches the control plane; it rides out in the agent's natural-language response, which only the output gateway can see. That is the 80/20 split made physical.

---

## 6. Version pinning

Verified current as of this spec date:

- kagent Helm chart: `0.7.7` (April 2026 reference).
- vCluster: `v0.29` line (April 2026).
- LLM Guard: current main, MIT, Secrets and Sensitive output scanners present.

Verify-at-build rule for everything else (ArgoCD, Kyverno, Falco, Prometheus stack, OTel Collector, agentgateway): fetch the project's latest stable release at build time, pin the exact version into the Helm values or manifest, and record it in `VERSIONS.lock`. Do not hardcode a version from memory. After pinning, `VERSIONS.lock` is committed and is the authoritative version record.

---

## 7. Repository structure to create

```
watch-it-burn/
  README.md                      # what this is, how to run the workshop
  VERSIONS.lock                  # pinned versions, written by Phase 0/1
  infra/
    SIZING.md
    host-cluster/                # eksctl or terraform, provider as one var
    bootstrap.sh                 # installs IDP stack on host
  platform/
    argocd/
      appset-attendee.yaml       # ApplicationSet, one App per attendee
      apps/                      # the per-attendee app templates
    kyverno/
      policies/
        require-resource-limits.yaml   # attack 1 target, starts Audit/absent
        block-argocd-drift.yaml        # attack 3 control, Enforce from start
    falco/
      rules-workshop.yaml
    observability/
      otel-collector.yaml
      grafana-dashboards/
  agent/
    kagent-agent.yaml            # CRD, scoped ServiceAccount reference
    rbac/
      agent-role.yaml            # tight Role
      agent-rolebinding.yaml
    GATEWAY-NOTES.md             # confirmed agentgateway filter mechanism
    gateway/
      agentgateway.yaml
      llm-guard-service.yaml     # LLM Guard API server
      guardrail-filter-off.yaml  # toggle state: off
      guardrail-filter-on.yaml   # toggle state: on
  attacks/
    01-noncompliant-workload/
      attack.md                  # attendee instructions
      agent-prompt.txt           # the prompt that drives the agent
      fallback.kubectl.sh        # deterministic path if agent wanders
      toggle-on.sh               # switch Kyverno policy to Enforce
    02-privilege-escalation/
      attack.md
      agent-prompt.txt
      fallback.kubectl.sh
    03-infra-outside-git/
      attack.md
      agent-prompt.txt
      fallback.kubectl.sh
    04-exfil-through-response/
      attack.md
      agent-prompt.txt
      fallback.kubectl.sh
      plant-fake-secret.yaml
      toggle-on.sh               # enable agentgateway output guardrail
  verify/
    run-all.sh                   # Phase 6 harness, asserts before/after
    attack-01.sh ... attack-04.sh
  access/
    web-terminal/                # per-vcluster browser terminal
    quickstart.md                # attendee one-pager
  facilitation/
    runbook.md                   # minute-by-minute, co-speaker split
    slides-outline.md
    governance-map.md            # the takeaway artifact
    self-assessment.md           # attendee checklist for their own platform
  fallback/
    recordings/                  # asciinema per attack
  teardown/
    teardown.sh
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
- Install ArgoCD, Kyverno, Falco, Prometheus plus Grafana, OTel Collector. Pin each version into Helm values, append to `VERSIONS.lock`.
- Configure the OTel Collector to receive GenAI traces and export to a backend reachable from Grafana or Tempo. Default content capture for prompts and responses is OFF (see section 4 trap).

Verify:
- [ ] ArgoCD server pod Ready, `argocd app list` works.
- [ ] Kyverno admission webhook responding.
- [ ] Falco pods Running and emitting events.
- [ ] Prometheus scraping, Grafana reachable.
- [ ] OTel Collector accepting OTLP.

### Phase 2 — Per-attendee vCluster provisioning
Tasks:
- Build an ArgoCD ApplicationSet that templates one Application per attendee from a list (attendee count is a build variable, default to a documented number, see section 10).
- Each Application creates a vCluster and syncs that attendee's per-vCluster resources: Kyverno policies (attack-1 policy in Audit or absent, attack-3 policy in Enforce), the planted fake secret resource (created in Phase 4 wiring but referenced here), the agent, the gateway, and the LLM Guard service.
- Provisioning must be parallel and time-boxed. Record per-vCluster provision time.

Verify:
- [ ] For a test set of 3 attendees, 3 vClusters reach Ready.
- [ ] Each vCluster has its own API server reachable via its kubeconfig.
- [ ] An action in attendee A's vCluster is invisible in attendee B's vCluster.
- [ ] Median provision time recorded in `infra/SIZING.md`.

### Phase 3 — Scoped agent
Tasks:
- Deploy the kagent agent into each vCluster via the ApplicationSet.
- Define the agent ServiceAccount Role to allow exactly: create and get workloads in the attendee namespace, get and list the planted secret. Deny: create or modify ClusterRole, ClusterRoleBinding, Role, RoleBinding; deny mutation of ArgoCD-managed resources.
- Wire the model provider to Bedrock. Resolve the FLAG in section 5 first: confirm the kagent Bedrock config path, then pin it.

Verify:
- [ ] Agent pod Running, answers a trivial prompt end to end through Bedrock.
- [ ] `kubectl auth can-i create clusterrolebinding --as=system:serviceaccount:<ns>:<agent-sa>` returns no.
- [ ] `kubectl auth can-i create deployment -n <ns> --as=...` returns yes.
- [ ] `kubectl auth can-i get secret <fake-secret> -n <ns> --as=...` returns yes.

### Phase 4 — Output gateway and exfil guardrail
Tasks:
- Deploy LLM Guard API server as a service in each vCluster. Configure Secrets and Sensitive output scanners. No LLM-judge scanner.
- Deploy agentgateway in front of the agent endpoint. Implement the output guardrail filter that calls LLM Guard on the agent's response. Confirm the filter mechanism (section 5 FLAG) and document it in `agent/GATEWAY-NOTES.md`.
- Create two toggle states: `guardrail-filter-off.yaml` and `guardrail-filter-on.yaml`. Off is the default at workshop start.
- Plant the fake secret (`attacks/04-.../plant-fake-secret.yaml`) with a documented sentinel value, for example `FAKE-PROD-DB-PASSWORD-sentinel-9f2a`.

Verify:
- [ ] With the filter off, asking the agent to read and report the planted secret returns the sentinel value in the response.
- [ ] With the filter on, the same request returns a blocked or redacted response, and the sentinel value does not appear.
- [ ] LLM Guard logs show the Secrets or Sensitive scanner firing on the on case.
- [ ] No real credential exists anywhere in the path.

### Phase 5 — The four attacks
For each attack: write the attendee `attack.md`, the `agent-prompt.txt` that reliably drives the agent, and a `fallback.kubectl.sh` deterministic path. Pre-test each prompt at least 5 times and record the success rate in the attack folder. If an agent prompt is below a documented reliability bar, tighten it or rely on the fallback path for the live run.

Attack 1, non-compliant workload:
- Target policy: `require-resource-limits.yaml` (or a privileged-pod or latest-tag rule), starting absent or in Audit.
- Before: agent deploys the workload, it admits.
- `toggle-on.sh` switches the Kyverno policy to Enforce.
- After: agent retries, admission rejects with a clear Kyverno message.

Attack 2, privilege escalation:
- Agent attempts to create a ClusterRoleBinding granting itself broader rights, or to bind to an admin role.
- Outcome: RBAC denies it. No toggle. This is a control already in place.

Attack 3, infra outside Git:
- Agent attempts a direct `kubectl apply` change to an ArgoCD-managed resource, bypassing Git.
- Outcome: the `block-argocd-drift.yaml` admission policy rejects mutation by a non-ArgoCD principal. Show ArgoCD self-heal reverting any drift as defense in depth. No toggle.

Attack 4, exfil through response:
- Agent reads the planted fake secret and is asked to summarize or return it to the user.
- Before: the sentinel value leaves in the response (filter off).
- `toggle-on.sh` enables the agentgateway output guardrail.
- After: the same attempt is blocked or redacted.

Verify:
- [ ] Each attack's before state produces the intended outcome.
- [ ] Each attack's after state (where applicable) produces the intended outcome.
- [ ] Attacks 2 and 3 fail without any toggle.
- [ ] Each `fallback.kubectl.sh` reproduces the same before/after outcome deterministically.
- [ ] Per-prompt reliability recorded in each attack folder.

### Phase 6 — Verification harness
Tasks:
- `verify/run-all.sh` runs all four attacks against a fresh test vCluster and asserts the section 2 outcomes for before and after states. Exit non-zero on any mismatch.
- The harness is the abstract-truth gate. If it fails, the talk's claims are not yet true.

Verify:
- [ ] `verify/run-all.sh` passes on a clean test attendee.
- [ ] Running it twice in a row passes both times (idempotent).

### Phase 7 — Attendee access
Tasks:
- Deploy a per-vCluster web terminal (browser shell or browser IDE) pre-authenticated to that attendee's vCluster. No local install required.
- Generate access handoff: a short URL or QR per attendee. Document the local-kubeconfig fallback in `quickstart.md`.
- `quickstart.md` is one page: how to reach your terminal, how to talk to your agent, where the four attacks live.

Verify:
- [ ] A browser session reaches a working terminal scoped to one vCluster.
- [ ] From that terminal, the attendee can drive their agent and run attack 1 before state.
- [ ] Access works from a network that cannot reach the cluster API directly except through the web terminal entry point.

### Phase 8 — Facilitation materials
Tasks:
- `runbook.md`, minute by minute for the 90-minute version, with a documented 2-hour extension. Assign segments to Michael and Whitney.
  - Suggested split, confirm with Whitney: Michael drives architecture, the security thesis, and the regroup map. Whitney drives the live attack narration, the attendee experience, and the observability beats (the data view of each attack). Hand-offs marked explicitly in the runbook.
  - Suggested 90-minute shape: 10 intro and architecture, 10 access and warm-up, 15 attack 1 with toggle, 10 attack 2, 10 attack 3, 15 attack 4 with toggle, 15 regroup and governance map, 5 takeaways and questions.
- `slides-outline.md`, outline only, agent-forward framing in titles, no punchline giveaways, no proprietary framework names that are not already public.
- `governance-map.md`, the takeaway artifact: a table of attack, the control that governs it, the layer it lives in (admission, RBAC, GitOps, output inspection), and whether existing CNCF tooling covers it or an agent-specific control is required.
- `self-assessment.md`, a checklist an attendee runs against their own platform to find which of the four failure modes they are not covering.

Verify:
- [ ] `runbook.md` total time fits 90 minutes with named hand-offs.
- [ ] `governance-map.md` covers all four attacks and marks attack 4 as the agent-specific gap.
- [ ] `self-assessment.md` is usable without any workshop-specific tooling.
- [ ] No banned terms or proprietary framework names in attendee-facing files (see section 11 note).

### Phase 9 — Fallback recordings, teardown, cost
Tasks:
- Record an asciinema for each attack showing before and after, committed under `fallback/recordings/`. These are the demo-failure safety net.
- `teardown/teardown.sh` removes all attendee vClusters and their state, leaving the host stack optionally intact (flag controlled).
- `teardown/cost-report.sh` reports the AWS spend for the run. Do not estimate a dollar figure in this spec; the script reports the real number after the fact for Accenture expensing.

Verify:
- [ ] One recording per attack exists and plays.
- [ ] `teardown.sh` removes a test attendee's vCluster fully, re-runnable with no error.
- [ ] `cost-report.sh` runs and emits a number.

---

## 9. Definition of Done

- [ ] Phases 0-9 verification blocks all pass.
- [ ] `verify/run-all.sh` passes on a clean attendee and is idempotent.
- [ ] N test attendees provision in parallel within the time recorded in `SIZING.md`.
- [ ] Attendee access works with no local install.
- [ ] Every attack has a deterministic fallback and a recording.
- [ ] Governance map and self-assessment generated and committed.
- [ ] `VERSIONS.lock` complete.
- [ ] No real secret anywhere in cluster, traces, or recordings.

---

## 10. Open decisions for Michael (not guessed)

1. **Attendee count.** Drives host node sizing and per-vCluster provision parallelism. AI Engineer workshop rooms vary. Give a target N and a hard ceiling.
2. **Access model.** Web terminal per vCluster is the spec default. Confirm, or say if AI Engineer provides hosted environments you would rather build on.
3. **Co-speaker split.** Phase 8 has a suggested Michael/Whitney division. Confirm with Whitney before the runbook is locked.
4. **90 vs 120 minutes.** Spec builds the 90-minute runbook with a 2-hour extension. Confirm the accepted slot length.
5. **Host provider.** EKS default. Confirm, or switch the one variable.
6. **OTel advanced beat.** The trace-re-leak teaching beat (section 4) is off by default and lives in the 2-hour version. Confirm whether to build it in or keep it as a slide-only mention.

---

## 11. Honest risk register

The conceptual design is sound. The failure surface is operational. In rough order of likelihood to bite on the day:

1. **Attendee access at scale.** N people authenticating to N vClusters over Moscone WiFi is the single most likely live failure. Mitigation: web terminal entry point that does not require attendees to reach the cluster API directly, pre-generated access links or QR codes, and a facilitator-driven single path if the room cannot get online. Test with the real expected N before the event.
2. **Agent prompt reliability.** Agents wander. A prompt that worked yesterday may not produce the attack today. Mitigation: pre-test each prompt to a recorded success rate, and keep the deterministic `fallback.kubectl.sh` as the live path if reliability is marginal. The lesson is about the guardrail, which is deterministic, so a deterministic fallback does not weaken the point.
3. **agentgateway output-filter mechanism drift.** The exact way to run an output guardrail in front of the agent may have changed since January. Resolve the FLAG in Phase 4 early; if the current mechanism is awkward, an LLM Guard reverse-proxy sidecar on the agent response path is an acceptable substitute, documented in `GATEWAY-NOTES.md`.
4. **kagent Bedrock config.** Tutorials use OpenAI. Confirm Bedrock works in kagent before building anything else on top of the agent. If Bedrock support is rough, decide early whether to swap the provider for the workshop.
5. **Provisioning time and cost.** N vClusters plus agents plus gateways take time to come up and cost real money while running. Pre-provision before doors open, and use `cost-report.sh` for expensing. Accenture covers it; the point is to know the number, not to be surprised by it.
6. **Time pressure.** Four attacks with two live toggles plus a regroup in 90 minutes is tight. The runbook must protect the regroup and the governance map; that is the part attendees actually take home. If running long, cut attendee free-play, not the map.

Note for Phase 8 verification: keep attendee-facing files clear of the banned-term list and of any framework names that are not already public. The deterministic-guardrail thesis stays out of attendee copy as a talk payoff.
