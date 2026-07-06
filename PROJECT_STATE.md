# Project State: Unleash_an_Agent_Watch_It_Burn

Phase: 1.3 Approve (PRD 35 sealed; entering Phase 2 M1)
Approved: 2026-07-03T19:59:22Z by Michael (sha256:5e110e425e70) — PRD 35 re-approval

## Lifecycle
- [x] 1.1 Research
- [x] 1.2 Plan
- [x] 1.3 Approve  ← PRD 35 sealed; entering Phase 2
- [ ] 2.1 Test
- [ ] 2.2 Implement
- [ ] 2.3 Verify
- [ ] 3.1 Stage
- [ ] 3.2 Confirm CI
- [ ] 3.3 Promote

## Contracts
- 2026-07-03T19:59:22Z · sha256:5e110e425e70 · PRD 35 multi-cloud (AKS + GKE) incl. §3.7 hardening parity + §4.6 cluster-shape parameterization. APPROVED, read-only; changes need /prd-amend.
- PRD 36 · multi-cloud attack -> control -> signal matrix (reference/acceptance spine; sibling of 35, no separate gate).
- PRD 37 · curl/wget missing from workshop-mcp image (open NOTE, small fixture fix).

## Current Plan
Active, Michael-prioritized 2026-07-05:
1. DONE (offline-verified; live-validate next cluster). Adopted Amazon Nova as the WORKSHOP DEFAULT (Michael: "Nova everywhere"). `bedrock-nova` ModelConfig (`us.amazon.nova-pro-v1:0`) added; Agent default flipped sonnet -> nova. Claude/haiku/opus tiers kept for an optional cost-race. Nova complies AND executes where Claude refuses and Llama/Mistral leak tool-calls-as-text.
2. DONE (offline-verified; live-validate next cluster). curl fixture (PRD 37): workshop-mcp startup command now `apt-get install -y curl` alongside the existing pip step, so run_shell can POST to the beacon.
4. IN PROGRESS. PRD 35 M1, sub-steps:
   - [x] IMDS `metadata_options` pin (§3.7-A) in cluster/main.tf — IMDSv2 required, hop_limit=1. terraform validate + fmt green. ON MAIN (f65c17d).
   - [x] §4.6 fleet.sh cluster-shape parameterization: size/type/disk passthrough, roster-as-data (roster.tsv + WIB_ROSTER_FILE/WIB_ROUNDS/WIB_PER_ROUND), cross-round concurrency default (WIB_SERIAL), WIB_DRY_RUN. LIVE-VALIDATED 2026-07-06 on watch-it-burn-r2-1: subset -> only r2-1, node came up m5.2xlarge (WIB_INSTANCE_TYPES -var list parsed), IMDS http_tokens=required/hop=1, and the Nova agent reached Bedrock at hop=1 (Pod Identity survives the pin). PROMOTED TO MAIN. §4.6-d (per-cluster tier -> Agent modelConfig patch) DEFERRED: tier column plumbed but not applied; Nova gitops default runs everywhere.
   - [~] AWS root relocation: infra/terraform/{lab-vpc,cluster} -> aws/{network,cluster} (git renames). All refs repointed: fleet.sh CLUSTER_DIR/LAB_VPC_DIR, verify/test_forkbomb_defense.py, teardown/teardown.sh, deploy-full-idp.sh, 3 external /tmp/witb-teardown scripts (+ canonical copies now in infra/terraform/aws/teardown/), .gitignore (path-neutral **/states/), and 15 doc/config files. Offline-verified: terraform validate at both new paths, fleet.sh dry-run finds the roots, forkbomb test passes, kustomize OK, M1 grep-gate returns zero stale refs outside history. LIVE-VALIDATED 2026-07-06: VPC applied from aws/network, watch-it-burn-r2-1 provisioned from aws/cluster via fleet.sh, IDP converged, Nova agent made a live Bedrock call. PROMOTED TO MAIN.
   - [ ] fleet.sh PROVIDER dispatch + providers/{aws,azure,gcp}.sh shims.
   §4.6 + the relocation are path-critical; validate on a live cluster before promoting main.
Parked: 3. open-weights/Llama via an OpenAI-compat proxy (needs a real build).
Open question: GCP VPC-SC (PRD 35 §6 risk 1 / PRD 36 §8 Q1), blocks M3 design only.

## Branch & Tests
- Branch: staging
- Working tree: clean
- Last CI: n/a (docs-only commits); sha 9309394

## Phase History
- 2026-07-05 init-state migrated the pre-lifecycle PROJECT_STATE.md to the lifecycle schema; deduced Phase 1.3 (PRD 35 approved, Phase 2 pending).
- 2026-07-05 2.2/2.3 items 1+2 implemented + offline-verified (Nova default + curl fixture); YAML + kustomize green; live-validation deferred to next cluster.
- 2026-07-06 2.2/2.3 M1 IMDS pin done (on main); §4.6 core (size passthrough + roster-as-data + concurrency default + dry-run) implemented + offline-verified (6 dry-run scenarios), on STAGING, held from main pending live provision. §4.6-d (tier patch) deferred.

## Audit log pointer
The detailed technical decision + verification audit trail lives in `docs/DECISION-LOG.md` (PRD 35 approval / amendment / re-approval, the model-refusal rerun evidence, the Nova A/B). `decisions.md` at repo root carries lifecycle phase-transition entries going forward.

---

# PROJECT_STATE.md (pre-lifecycle body, preserved)

Workshop: "Build a Platform, Unleash an Agent on it... and Watch it Burn!"
AI Engineer World's Fair 2026, San Francisco, Moscone West. Speakers: Michael Forrester (Accenture) + Whitney Lee.

Last updated: 2026-06-24

### AGENTGATEWAY IN + AI-LAYER CANONICAL RECONCILIATION (2026-06-24)

Michael decided (AskUserQuestion): agentgateway is IN — it should be deployed. Acted on that plus the
earlier "gitops/ai-layer/ is canonical, agent/gateway/ is the synced source mirror" decision.

- **agentgateway staged canonical** (`gitops/ai-layer/agentgateway.yaml`, commit b64e7ea): ported from
  agent/gateway/agentgateway.yaml; namespace left to the kustomization (agent), service FQDNs
  ATTENDEE_NAMESPACE→agent, v1.3.0 OTel tracing expressed in the config file (research/29), UST env
  kept. INTENTIONALLY NOT in kustomization.yaml resources, so it does not auto-deploy/crash-loop live
  clusters before 5 verify-at-build blockers resolve on a real cluster (image digest, v1.3.0 config
  schema, llm-guard-webhook dependency, tracing-key alignment, Beat-3 mcp-authz control). Header
  documents all five. kustomize build of the ai-layer bundle confirmed clean (file correctly excluded).
- **Reconciliation** (commit 7b7c270): added OTEL_RESOURCE_ATTRIBUTES (Datadog UST) to the gitops
  guard-proxy Deployment so it matches kagent + agentgateway (DD Agent reads it for log tagging now;
  OTLP endpoint env arrives with the deferred guard-proxy OTel SDK work, research/33 M3). Repointed
  verify/test_observability.py UST asserts at the canonical gitops copies (select Deployment by name).
  Repointed docs (STACK-WALKTHROUGH AI-gateway + LLM-Guard cells, BUILD-SPEC §7 stale create-line,
  cost/README) to gitops. Added RECONCILIATION headers to the Beat-3 mcp-authz toggle manifests +
  script flagging two latent traps (the overlay rewrites the whole config.yaml so it drops tracing +
  the request promptGuard unless it carries the full canonical config; ATTENDEE_NAMESPACE must resolve
  to `agent`); bodies left unchanged pending the existing beat-3 mcpAuthorization-enforcement SPIKE.
- **Verification:** all 19 verify/*.py render-gate tests PASS; lab-distribution 13 tests PASS. Both
  commits pushed staging→main (origin/main == 7b7c270). Whitney coordination still owed on the
  agentgateway tracing config (research/29) + her PRD pointer; the 5 blockers are live-cluster items.

### WALKTHROUGH REFRAMED -> LIVE-DELIVERY RUN-OF-SHOW (2026-06-23, Michael correction)

Michael: the walkthrough deck modeled the WRONG thing. It was a foundation-up architecture/stack
study; but "the walkthrough" = how we actually run the lab with students (open cold, tell them they
already have a cluster, leap into attacking it). A deck that opens on Terraform is backwards for the
session. DECISION (AskUserQuestion): REPLACE the stack-study deck entirely (not keep both).
Rebuilt tech-walkthrough/index.html as the run-of-show in delivery order, sourced from
facilitation/runbook.md + cold-open-script.md + governance-map.md: open cold (agent-deleted-my-cluster
hook -> production stakes) -> promise + "you have a cluster, leap in" -> trace dashboard -> three-cluster
spine (C1 burns + cost counter / C2 CNCF blocks but bill moved / C3 your cluster, toggle output->input->MCP
+ free-play) -> optional trace re-leak -> governance map + cost ladder -> take it home. 14 slides.
Facilitator detail (timing, owners M/W, /toggle scripts, hand-offs, fallbacks) in SPEAKER NOTES;
controls introduced WHEN they turn on (runbook reveal discipline), not as an opening lecture. Dropped
mermaid (HTML three-column spine + HTML tables for map/ladder = robust). READMEs updated. Live again
at walkthrough.agenticburn.com (HTTP 200). Commit 8b3f61b. The prior foundation-up arc is retired.

### WALKTHROUGH DECK REDESIGN + DOC SYNC (2026-06-22)

- **Deck redesigned** (`tech-walkthrough/index.html`): was a dense 26-slide component
  inventory; now a 17-slide TEACHING ARC — stakes -> one mental model -> the five attacks
  (each try/stop/already-have) -> verdict -> the four layers (now motivated) -> takeaway.
  All build-reference detail (versions, repo paths, mechanisms) moved into reveal.js SPEAKER
  NOTES so slides stay lean and carry no internal-structure surface. Packt refs scrubbed.
  Mermaid fix: render diagrams BEFORE reveal.initialize() (hidden slides collapse a diagram
  to zero width); node labels shortened/stacked to avoid clipping. All 4 diagrams verified
  full-size + clean via puppeteer. LIVE again at walkthrough.agenticburn.com (HTTP 200,
  PORT=80 persisted). Committed 659570b.
- **Doc sync check (Michael asked):** the eksctl->Terraform + IRSA->Pod Identity changes had
  NOT propagated into PROSE (the 06-21 doc pass fixed topology only). Fixed in repo (commit
  8183a00): BUILD-SPEC.md, STACK-WALKTHROUGH.md, TECH-STATUS.md, BUILD-PLAN.md — provisioning
  eksctl/test-cluster.yaml -> Terraform fleet; agent identity IRSA -> EKS Pod Identity (IRSA
  scoped to EBS CSI); two stale walkthrough version pins (Argo CD v3.4.4, kagent 0.9.9).
- **Google Docs synced (comment-safe, Michael approved):** Doc 6 (Build Spec, 2 Whitney
  comments) + Doc 7 (Stack Walkthrough, 0 comments) updated via Docs API replaceAllText after
  pinning keepForever rollback revisions (Doc6 rev14, Doc7 rev5). Confirmed none of my target
  strings overlapped Whitney's quoted comment spans ("Architecture", "kube-prometheus+OTel...").
  Verified post-edit: residual stale = CLEAN, Doc6 still has its 2 comments. Docs 1/2/3/4/5
  were already clean (Doc3 "spoke" was "spoken copy"). Token minted in-process from gog keyring
  (jwcrypto decrypt -> refresh); never written to disk or printed.

### READINESS PUNCH-LIST (2026-06-22, Michael's triage)

Platform is built + live-validated (all beats, Terraform provisioning, rebrand). Remaining:

1. **Build+push images** to `peopleforrester/watch-it-burn` (backstage + sample-app). DO. (Assess
   buildability: no Backstage app source in-repo; either build one, use the public chart, or drop
   backstage. The sample-app image likewise needs source/a Dockerfile.)
2. **Pre-recordings / demo resilience.** DEFERRED (Michael).
3. **60-cluster fleet dry-run.** DEFERRED 1-2 days until the EC2 vCPU quota lands; Michael emailed
   the lab team. (One attendee cluster already validated clean end-to-end.)
4. **Lab distribution** (`lab-distribution/`). DO, but needs ARCHITECTURE DECISIONS first: Railway
   deploy + attach to `provisioning.agenticburn.com`, and wire it differently than the KCD distributor
   because it must also drive Datadog distribution wiring plus per-attendee cluster + URL access (not
   just key handout). Design pass needed before build.
5. **ESO -> EKS Pod Identity.** DO NOW (modern June-2026 convention; agent + LB controller already use
   it). Drop the IRSA role annotation; bind platform:external-secrets via a pod-identity association.
   Also wire the Grafana admin secret. (EBS CSI still IRSA from the Packt template - optional consistency
   switch, on a validated path, deferred.)
6. **Burn-cluster (Cluster 1, no-floor) profile** never live-tested. DO.
7. **Datadog** - Whitney, tomorrow (account/keys/Agent/dashboards). OTel side wired + waiting.
8. **Co-speaker division of labor** - to be figured out with Whitney.
9. **Whitney's open questions** (`facilitation/whitney-questions-tracker.md`) - review later.
10. **TS agent / spiny-orb** - HOLD (deferred until after the demo).

### NEW ASKS + RESOLVED DECISIONS (2026-06-22)

- **Images DONE:** backstage + sample-app built and pushed to ghcr.io/peopleforrester/watch-it-burn
  (package set PUBLIC by Michael; anonymous pull confirmed). Manifests repointed docker.io->ghcr.io.
  Backstage = freshly scaffolded app, source at images/watch-it-burn-backstage/ (reproducible build via
  node:22 container). k8s/argocd Backstage plugins not yet wired into the base image (follow-up).
- **ESO -> Pod Identity DONE** (PR #4 merged): TF association + stale IRSA annotation removed.
- **DNS = Namecheap.** agenticburn.com is at Namecheap (use ~/.claude/rules/tools/namecheap-api.md;
  read-then-merge setHosts so existing records are never clobbered; mutations are deploy-time).
- **Lab distribution (next):** Datadog = per-attendee trial org (one trial org per attendee from `pool.csv`);
  cluster access = per-cluster IAM creds (current pool.csv model). Rework: drop the KodeKloud /browser
  path, extend pool schema with url + datadog_url, show them on the success page, Railway deploy at
  provisioning.agenticburn.com (Namecheap CNAME at deploy once Railway gives the target).
- **NEW - update all READMEs** across the repo (post-rebrand + Terraform + ghcr accuracy pass).
- **NEW - walkthrough.agenticburn.com technical walkthrough:** a reveal.js (or similar) slide deck covering
  EVERY component foundation->up, clear + visual, so Michael + Whitney can study the whole stack.
  Host at walkthrough.agenticburn.com.

### TERRAFORM LIVE-VALIDATED on attendee-001 (2026-06-22)

Stood up the Terraform stack end to end and ran the full verify harness. The eksctl->Terraform
conversion is PROVEN on real infra. Sequence: terraform apply lab-vpc (shared VPC) -> fleet.sh up
watch-it-burn-attendee-001 (1x t3.2xlarge) -> deploy-full-idp.sh -> full verify -> teardown to $0.

RIGHT-SIZING (Michael's question, answered with data): the full IDP fits ONE t3.2xlarge easily -
46 pods, CPU requests 3045m (38% of 7.9 vCPU), memory 5946Mi (19% of 30 GiB). The old 6x t3.large
gate cluster was ~4x overprovisioned (an arbitrary number, never measured). t3.2xlarge default stands,
now data-validated. NOTE: node ROOT disk is the real single-node constraint, not CPU/mem (see #16).

FULL VERIFY PASS on the Terraform cluster (identical behavior to the eksctl runs):
- beat-cost PASS: cost $0->$0.0019 then flatlines on block-list. This PROVES the agent reaches Bedrock
  via EKS POD IDENTITY with real token spend - the headline verify-at-build flag of the conversion
  (Pod Identity, not IRSA; no SA annotation, no per-cluster OIDC trust). GREEN.
- beat-02 PASS: all 4 sanitization states (input classifier blocks injection; output guard -> [REDACTED]).
- PID cap: pod-cgroup pids.max=1024 read from the node (Terraform cloudinit_pre_nodeadm delivered it).
- Falco->Talon PASS: CRITICAL "Fork bomb detected" -> rule "Fork Bomb Response" -> kubernetes:terminate
  -> pod terminated in 4s.

FIVE bugs caught by the live apply that terraform validate/plan CANNOT catch (all fixed+committed):
- #14 agent Bedrock Pod Identity role name overran the IAM name_prefix 38-char cap -> shortened to
  <cluster>-bedrock.
- #15 fleet.sh swallowed backgrounded apply/destroy exit codes (false "success" on a failed apply)
  -> record per-cluster failures, exit non-zero.
- #16 disk_size=80 SILENTLY IGNORED: cloudinit_pre_nodeadm forces a custom launch template, under
  which the module ignores disk_size -> node fell back to AL2023 default 20 GiB -> DiskPressure ->
  pods Pending. FIX: set root volume via block_device_mappings (node_disk_size default 100 GiB).
  (This also affects Packt's template - same disk_size+cloudinit combo.)
- #17 node ROLL wedges on a single-node cluster: the IDP PDBs (minAvailable:1) make a drain
  unsatisfiable -> PodEvictionFailure. FIX: force_update_version=true on the node group. Fresh
  provisions never roll, so the event path is unaffected; this only bites config changes.
- #18 deploy-full-idp.sh ArgoCD helm --wait hangs in pending-install on EKS -> dropped --wait, wait
  on core components explicitly. Also beat-cost.sh needed the raw_decode fix for the kubectl run --rm
  "pod deleted" stdout line (same as beat-02).
OPERATIONAL LESSON: do NOT manually terminate an MNG-managed node or rapidly re-pin scaling - it sent
the ASG into destructive oscillation (had to pin min=3 to stop it). Let Terraform own node rolls
(force_update_version handles the PDB wedge). Fresh provision is clean (the first apply gave 1 clean node).
Branches reconciled: merged another session's observability commits; staging==main==62f8956.

### PROVISIONING CONVERTED eksctl -> TERRAFORM (Michael directive, 2026-06-21)

Michael's call, non-negotiable: drop eksctl, provision with Terraform. Rationale = the standard across
his workshop repos AND multi-cloud portability (GKE next month, AKS the month after); eksctl is EKS-only
and would be a from-scratch rewrite per cloud. Decisions (via AskUserQuestion): per-attendee ISOLATED
state (fan-out), and EKS-now with a portable seam (GKE/AKS later = swap just the cluster module).

Research spike (3 parallel agents) read the reference repos. WINNER = the Packt sister repo
(`~/repos/events/Packt-agentic-devops/scripts/provision/`): a `lab-vpc/` shared root + a parameterized
`cluster/` root + a `fleet.sh` driver doing per-attendee isolated state (`-state=states/<name>.tfstate`)
in a parallel pool (MAX_PARALLEL). KCD-Texas confirmed secondary patterns (workspaces, enableNetworkPolicy);
KubeAuto is single-cluster (not a fleet). I MODELED ours directly on Packt.

Built `infra/terraform/` (all `terraform validate` clean; offline suite 164 green):
- `lab-vpc/main.tf` - shared VPC (10.0.0.0/16, two /18 private, one shared NAT, role-only subnet tags),
  VPC module ~>5.0, provider ~>6.0. Replaces the README-only `infra/shared-vpc/` stub (there was NO
  shared-infra IaC before; the test cluster made its own throwaway VPC).
- `cluster/main.tf` - one independent attendee EKS cluster, EKS module ~>21.0 (API: name,
  kubernetes_version 1.35, addons{}, eks_managed_node_groups, enable_irsa). Takes vpc_id +
  private_subnet_ids as inputs (shares the lab VPC). EBS CSI via IRSA; AWS LBC via Pod Identity.
  THREE Watch-It-Burn deltas vs Packt: (1) podPidsLimit=1024 in cloudinit_pre_nodeadm NodeConfig
  (fork-bomb cap; Packt only sets maxPods); (2) enableNetworkPolicy="true" on vpc-cni (egress beat);
  (3) Bedrock via EKS Pod Identity association for agent:agent-sa (fleet-safe: no SA annotation in
  gitops, no 60 OIDC trusts; eks-pod-identity-agent addon feeds the AWS SDK chain kagent uses).
- `fleet/fleet.sh` - up/down/status, per-attendee state, MAX_PARALLEL pool, `assert_ours` refuses any
  non-watch-it-burn name (cannot touch co-tenant Packt). `fleet/cleanup-log-groups.sh` sweeps orphaned
  EKS log groups (create_cloudwatch_log_group=false for idempotent reprovision). `infra/terraform/README.md`.
- Node default 1x t3.2xlarge (Packt's validated single-node AI-platform shape), parameterized.
  verify-at-build: confirm the full IDP fits the attendee node (validated live on 6x t3.large); bump if Pending.
REMOVED eksctl: infra/{test-cluster,node-config,attendee-cluster/cluster.yaml,burn-clusters/cluster.yaml,
bootstrap.sh,cluster3-setup.sh}. Rewrote teardown/teardown.sh to delegate to the Terraform fleet
(prefix-scoped). Re-pointed render-gate tests (test_tagging/test_egress/test_forkbomb_defense) at the
Terraform instead of the deleted eksctl YAML; same safety properties asserted (podPidsLimit in cloudinit,
enableNetworkPolicy on vpc-cni, project=watch-it-burn default_tags, fleet name-refusal). Docs updated
(shared-vpc/attendee/burn READMEs, TAGGING.md, deploy-full-idp.sh note). All AWS-LAYER live validations
from earlier this session (B2/PID/fork-bomb) still hold; they were Kubernetes-layer and are unaffected by
the provisioning swap. NOT YET DONE: a live `terraform apply` of a cluster (the prior live validation was
on the eksctl cluster, now torn down); the GCP/AKS module variants (seam is ready, deferred per decision).

### LIVE VALIDATION SESSION 2026-06-21 (watch-it-burn-test, 6x t3.large, accen-dev/us-west-2)

Ran the remaining live validations (Michael's plan: B2, PID limit, fork bomb) on a fresh cluster with
the full IDP deployed via the app-of-apps. ALL PASS. Isolated kubeconfig /tmp/watch-it-burn-test.kubeconfig,
explicit --context per command, ephemeral curl pods (NO port-forward, per Michael). Caught + fixed 4 more
real bugs; all on staging+main with render-gate guards. Offline suite now 172 checks, green.

- **Deploy gotcha (recurring):** ArgoCD helm install hangs in pending-install with `--wait` (zero pods,
  >15min). FIX (same as prior): uninstall the stuck release, reinstall WITHOUT `--wait`, then apply repo
  creds + app-of-apps; ArgoCD syncs the rest. (deploy-full-idp.sh still uses --wait; left as-is, the
  manual recovery is fast and documented here.)
- **#8b agent IRSA flag:** `eksctl create iamserviceaccount` does NOT accept `--kubeconfig` (only `create
  cluster` does); it reads the exported KUBECONFIG. Re-ran without the flag -> role witb-agent-bedrock
  created + agent-sa annotated; ServerSideApply on ai-layer let the role-arn annotation coexist with ArgoCD.
- **B2 sanitization PASS (live, 4 states):** rewrote beat-02.sh to drive the live guard-proxy via ephemeral
  curl pods (old beat-02 called fallback.curl.sh with a mismatched contract needing an external host:port).
  INPUT off->injection reaches agent; INPUT classifier on->403 at proxy; OUTPUT off->sentinel leaks;
  OUTPUT on->[REDACTED]. Two harness subtleties fixed: scope output assertions to the AGENT output (not
  the user-echo in history), and raw_decode the response (kubectl run --rm appends "pod ... deleted" to stdout).
- **PID-limit fork-bomb block PASS (live):** definitive node-level read of the pod cgroup
  `pids.max=1024` (kubepods-burstable-pod<uid>.slice); behavioral: a real fork bomb hits
  `sh: can't fork: Resource temporarily unavailable` at the cap and all 6 nodes stay Ready. The
  in-CONTAINER `pids.max=9289` is the cgroup-namespaced container view, NOT the enforced pod cap (the
  prior "9289 looks unapplied" reading was this misread; configz + node cgroup are authoritative = 1024).
- **Falco->Talon fork-bomb response PASS (live):** terminated the offending pod in ~4s. Caught 3 bugs:
  - **#9 Falco rule shadowing:** the generic "Exec Into Pod Detected" (custom-rules.yaml) matched the
    fork-bomb entry-shell execve first (Falco fires only the FIRST matching rule per event; rules.d loads
    alphabetically). Renamed the fork-bomb rules file to `00-workshop-forkbomb-rules.yaml` so it wins.
  - **#10 Talon rules not loaded:** key was top-level `rulesOverride` but the chart key is
    `config.rulesOverride` (top-level ignored -> chart default action with no match -> "0 rules loaded").
    AND the v0.3.0 schema needs SEPARATE `- action:` and `- rule:` (match+actions) entries; an action with
    an embedded `match:` is invalid. Fixed both -> "1 rule(s) loaded", rule "Fork Bomb Response".
  - **#11 Falcosidekick->Talon NXDOMAIN:** sidekick (ns security) addressed Talon as `http://falco-talon:2803`
    which resolves only in 'security'; Talon's Service is in 'falco'. Fixed to the cross-namespace FQDN
    `falco-talon.falco.svc.cluster.local:2803` -> "Talon - POST OK (200)".
  Render-gate checks added for all three (rule-file sort order, config.rulesOverride + v0.3.0 schema, FQDN).
- Minor (non-blocking): the 2 Talon replicas log a transient NATS leader-election i/o timeout (port 4222);
  the acting replica still terminated the pod. Consider single-replica or NATS svc check as a follow-up.
- Known-degraded apps (do NOT block the beats): cert-manager-issuers (no real issuer), eso-resources
  (no AWS SM entries), istio-base (CRD timing), *-party burn targets (private-ECR ImagePullBackOff).
- Commits on staging->main: beat-02 ephemeral-curl rewrite; falco rule precedence (00- prefix); Talon
  routing (config.rulesOverride + cross-ns FQDN); Talon v0.3.0 schema. Cluster torn down after -> $0.


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
  GATEWAY-NOTES, BUILD-SPEC, challenges/03 BUILD-SPIKE, VERSIONS.lock. mcpAuthorization is allow-only CEL
  with implicit deny (NO `action` field) - deleted FORM B; MCP config re-nested under
  `mcp.{targets,policies}`; tests updated.
- **Tempo chart repointed** to `grafana-community/helm-charts` 2.2.3 / app 2.10.7 (old grafana repo
  path is a dead stub after the 2026-01-30 migration). loki/alloy correctly stay at grafana/helm-charts.
- **Bedrock model IDs (research/13):** Sonnet `us.anthropic.claude-sonnet-4-6`, Opus
  `us.anthropic.claude-opus-4-8` (NO date stamp - the `<DATE>` placeholders were wrong), Fable
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

Google Drive reorganized (2026-06-21): top level trimmed to the core 7 (1 START HERE ... 7 Walkthrough)
plus 3 subfolders. "Decisions" (8 Challenges, 9 Control rationale, 10 Tech status, TS-agent proposal,
KubeArmor/Falco doc, Readiness Checklist). "Research Spikes" (Whitney's 4 spike docs + a new index doc
pointing to repo research/11-27). "Archive" (Comment Archive backup + older versions). Docs 3/6/7 updated in place to the new architecture, comment-safe (banners removed after):
Doc 7 (0 comments) full-rewritten from repo docs/STACK-WALKTHROUGH.md via media-PATCH; Doc 6 (2 comments)
surgically edited via Docs API replaceAllText on its 4 real stale lines (ApplicationSet/cluster-generator
-> in-cluster ArgoCD app-of-apps; deleted-tree + hub-cluster/spoke-cluster refs -> attendee-cluster/
burn-clusters/shared-vpc), the 2 comments untouched/intact; Doc 3 (18 comments) needed NO body edits
(its demo-flow is topology-neutral). All comments verified intact (Doc6 2, Doc3 18). Verified: 0 residual
stale terms in Doc 6, Doc 7 carries the shared-VPC/independent content.

PHASE-GATE SESSION CLOSED (2026-06-21): Michael's 4-step plan complete. (1) Agent gates validated:
beat-cost PASS live (cost counter moves on real spend, flatlines on block-list; #8 kagent_usage_metadata
key fix confirmed). (2) Teardown + clean reprovision: fresh watch-it-burn-test came up with all fixes baked
in. (3) #5 egress VALIDATED CLEAN on the fresh cluster (enableNetworkPolicy from create): S3 BLOCKED, DNS OK.
(4) Teardown complete - 0 clusters, 0 watch-it-burn EC2, nothing billing; lab-distribution/ pulled in
(adapted KCD distributor, code only, no PII/creds). Net: 8 real issues caught+fixed before the event
(#1 Falco syntax, #2 workshop-mcp built, #3 CONTEXT export, #4 selfHeal ignoreDifferences, #5 enableNetworkPolicy,
#7 A2A messageId, #8 cost-counter key; #6 harness ephemeral-curl-pod still OPEN - validations used
port-forward, harness needs a port-forward refactor). REMAINING live-validation (next cluster): beat-02
output-redaction, beat-03 mcp-authz (needs agentgateway deployed), PID-limit fork bomb (needs a nodegroup
with overrideBootstrapCommand). Offline suite 166 green.

LIVE PHASE-GATE RUN (2026-06-21, watch-it-burn-test, 6x t3.large, accen-dev/us-west-2, isolated
kubeconfig /tmp/watch-it-burn-test.kubeconfig). Full IDP deployed via app-of-apps. The run caught
6 real issues; commits pushed to staging+main:
- #1 Falco rule k8s.pod.label.app -> k8s.pod.label[app] (was crashlooping). FIXED+validated.
- #2 agent referenced workshop-mcp RemoteMCPServer that was never deployed -> agent could not compile.
  BUILT the good workshop-mcp shim (gitops/ai-layer/workshop-mcp-server.py + Deployment/Service/
  RemoteMCPServer, mirrors evil-mcp-shim; tools list_pods/apply_manifest/get_secret). Agent now
  Accepted=True Ready=True, pod Running. FIXED+validated.
- #3 beats didn't export CONTEXT to toggle subscripts. FIXED.
- #4 ArgoCD selfHeal reverted live toggles -> added ignoreDifferences (kyverno-policies failureAction;
  ai-layer guard-proxy env). FIXED+validated (beat-1 Enforce toggle now sticks).
- #5 vpc-cni addon lacked enableNetworkPolicy -> egress/default-deny inert. Added configurationValues
  enableNetworkPolicy=true to test/attendee/burn configs + render-gate check. FIXED in config; live
  retrofit on the running cluster stuck in addon UPDATING >15min (no errors) -> validate on a FRESH
  cluster (config applies at create).
- #6 OPEN: verify harness (beat-cost/02/03) uses an ephemeral `kubectl run ... curlimages/curl` helper
  that times out ("timed out waiting for the condition") on this cluster -> beat-cost/02/03 can't
  complete. Agent + wiring confirmed correct (AGENT_URL -> workshop-agent.agent:8080). Needs a harness
  fix (helper-pod path) to run the agent gates.
AGENT GATES VALIDATED LIVE (2026-06-21, post-fixes): beat-cost PASS - benign request moved the cost counter 0.0->$0.001588 (1164 tokens) and a block-listed destructive request flatlined it (pre-LLM, 0 tokens). Confirms #8 (live kagent 0.9.9 key is result.metadata.kagent_usage_metadata, NOT adk_; research/14 was wrong - record_usage now accepts both, kagent first) and #7 (A2A message/send needs params.message.messageId). Agent compiles, answers via Bedrock Haiku, calls the workshop-mcp list_pods tool. #6 (harness ephemeral curl-pod times out) still OPEN - validations done via kubectl port-forward; harness needs a port-forward refactor. beat-02 output-redaction + beat-03 mcp-authz (needs agentgateway) = remaining live items.

GATES PASS: Kyverno Audit->Enforce toggle (beat-1, post-#4), RBAC escalation FORBIDDEN, image-registry
villain block (Enforce), require-probes/labels/limits admission. NOT TESTABLE here: PID-limit fork bomb
(test-cluster has no overrideBootstrapCommand; unsafe without the cap). Offline suite 166 green.
Cluster STILL UP (~$0.50/hr). Teardown: teardown/teardown.sh --prefix watch-it-burn-test --yes.

QUEUE (Michael): pull a copy of portfolio/lab-provisionin-website (Flask pool-based key/lab distributor:
app.py, pool.csv, pool.db, railway.json) into this repo's provisioning for our own use.

ARCHITECTURE REVISED (Michael approved, 2026-06-21): dropped hub-and-spoke -> INDEPENDENT per-attendee
clusters. Each attendee gets their own standalone EKS cluster (take-home) running its OWN in-cluster
ArgoCD reconciling itself from gitops/bootstrap/app-of-apps.yaml (destination kubernetes.default.svc).
No hub, no central control plane. Matches the Packt sister repo. Networking: ONE shared VPC
(10.0.0.0/16, two /18 private subnets across 2 AZs); all clusters share it (NOT one VPC each). T3
burstable (t3.xlarge, unlimited mode), conservative start. Changes made: deleted platform/argocd/
(appset-attendee generator + appproject + duplicate apps tree) and infra/hub-cluster/; renamed
infra/spoke-cluster -> infra/attendee-cluster; cluster name watch-it-burn-spoke-* -> watch-it-burn-attendee-*;
added vpc.id/subnets refs + infra/shared-vpc/README.md; rewrote teardown.sh (prefix-scoped, no hub, no
Tempo-wipe); rewrote attendee README + bootstrap.sh wording; prose docs (BUILD-SPEC/STACK-WALKTHROUGH/
TECH-STATUS/SIZING/README) updated by a scoped subagent; GITOPS-RECONCILIATION marked resolved; tests
updated (163 green). Quotas (research/25): EKS clusters default 100 (60 fits); the ask is EC2 vCPU
L-1216C47A ~1000. STILL OWED (separate pass): the platform/ duplicate tree (observability, kyverno) is
partly referenced (falco rules) and needs its own reconciliation; Google Docs 1/3/6/7/10 still describe
hub-and-spoke and need the comment-safe update.

Datadog path SETTLED = HYBRID (Michael, 2026-06-21): OTel Collector stays the neutral primary (wired);
add a Datadog Agent DaemonSet for EKS infra auto-discovery + named integrations. Datadog stays swappable
(drop the Agent + the collector's datadog exporter to run OSS-only). DIVISION OF LABOR: Whitney owns the
Datadog account, API keys, Agent install, and dashboards (we do NOT have keys yet, and that is her piece);
we own the OTel-side wiring (done), the manifest annotations for named integrations, and consuming the
datadog-secret. Next-level implementation + node sizing in research/24.

Observability wiring DONE (2026-06-21, path-independent): (1) OTel Collector spanmetrics connector with
add_resource_attributes:true wired into traces-exporters + metrics-receivers (so span metrics carry UST
tags for Datadog correlation; this was the missing connectors block); (2) UST via OTEL_RESOURCE_ATTRIBUTES
(service.name + service.version=CLUSTER_TIER + deployment.environment.name=watch-it-burn) on guard-proxy,
agentgateway, and the kagent Agent deployment.env (kagent env support is verify-at-build); (3) Falcosidekick
native Datadog output via DATADOG_APIKEY from the shared datadog-secret (env overrides yaml; no key in repo;
additive/swappable, Talon path preserved). Datadog stays swappable per the principle (drop the datadog
exporter + these blocks to run OSS-only). test_observability.py extended (+9 checks; suite 163). TECH-STATUS.md
refreshed (was stale at 15 files/118 checks; now 19/163, done items un-stale, research-spike inventory +
parked/deferred section added). verify-at-build carried: datadog-secret must exist in security ns too; set
DD_SITE/DATADOG_HOST to Whitney's account; confirm collector Service name + kagent deployment.env + chart extraEnv.

TS agent ON HOLD (Michael, 2026-06-21): the optional TypeScript agent / custom-framework addition is
DEFERRED until after the demo is finished. Sticking with kagent only for now - a second agent
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
Proposal Google Doc created + shared with co-presenter (notified) + comment tagging her
(in the shared "Watch it Burn" Drive folder; doc + folder IDs and co-presenter email held
out of the repo).

KubeArmor research spike (2026-06-21): DONE -> research/17-kubearmor-forkbomb-2026.md. Verdict:
KubeArmor v1.7.3 CANNOT prevent a fork bomb the way podPidsLimit does - its KubeArmorPolicy has NO
process-count/thread-count/fork-rate/PID field (verified vs the shipped spec); it only allow/denies
named binary exec, file, network, capabilities (syscalls are audit-only regardless of action). The
`rate: 10p1s` seen in some material is a telemetry throttle, not enforcement (trap, flagged). It
enforces inline at LSM hooks (BPF-LSM preferred); EKS AL2023 ships kernel 6.1 with BPF-LSM enabled
by default so enforcement is plausible but MUST be verified on the node (`/sys/kernel/security/lsm`
contains `bpf`, `karmor probe`, live Block test). DECISION: keep podPidsLimit as the SOLE inline
fork-bomb block + Falco/Talon as detect+respond; do NOT add KubeArmor to the fork-bomb story. KubeArmor
is a candidate DIFFERENT-attack station (CNCF-native inline prevention: default-deny exec, block
secret-file reads, block egress) - still an OPEN option, not folded in. No repo defense changed.
Findings Google Doc shared with the co-presenter (doc ID held out of the repo).

Runtime-enforcement + observability spikes (2026-06-21): research/20-23.
- research/20 (Tetragon): does NOT replace the PID cap for fork bombs - Sigkill is kill-on-detect
  (outrunnable), Override is all-or-nothing (zero forks, not a ceiling of N), --cgroup-rate is a
  telemetry throttle. Standalone w/o Cilium CNI CONFIRMED (v1.7.0, VPC-CNI ok). Value = different-role
  (process lineage + inline Override of OTHER agent misbehavior). AL2023 Override needs
  CONFIG_BPF_KPROBE_OVERRIDE + non-confidentiality lockdown - verify at build.
- research/21 (KubeArmor claims, cited): research/17 CONFIRMED adversarially - no count/rate/PID field,
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
- **Co-presenter handoff:** the six handoff files were uploaded to the shared Drive
  folder (folder ID and Drive account held out of the repo)
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
  KubeAuto's PRIVATE ECR (account ID held out of the repo), repoint to public/our ECR; ESO secrets Degraded (no
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

## SESSION 2026-06-25: PRD #20 / #22 milestones + LIVE two-act verification

Cluster `watch-it-burn-attendee-001` (EKS 1.35, us-west-2) was up for this session and is STILL UP
(~$0.50/hr; teardown is manual per Michael). All apps Synced/Healthy; guard-proxy capture back to the
NO_CONTENT default; otel-collector back to Act 1 (no redaction). Repo is clean on `staging`.

Shipped to staging this session (all CI green; weaver workflow is the first repo-root GH Action):
- **#20 M6 Weaver registry** (`weaver/registry/`): manifest.yaml (new >=0.22.1 format: manifest.yaml +
  schema_url) pinning OTel semconv v1.37.0; guard-proxy span groups (HTTP SERVER + sanitize INTERNAL).
  `.github/workflows/weaver-registry-check.yml` (pinned, sha-verified weaver 0.24.2). docs/weaver-live-check.md.
  Installed weaver 0.24.2 locally (was 0.21.2, too old for the v1.37.0 schema).
- **#22 M3**: aligned the span groups to the authored contract (url.scheme Recommended, url.path
  Recommended, SPAN_ONLY live-check comment).
- **#22 M4 two-act re-leak, VERIFIED LIVE** (the previously-unresolved content-capture item):
  - Arming mechanism confirmed: `kubectl set env` SPAN_ONLY on the proxy survives selfHeal via the
    ai-layer ignoreDifferences on `select(.name=="proxy")|.env`; the proxy re-reads it at module load.
  - Act 1: sentinel visible in gen_ai.input/output.messages (trace 97d2eef...). THE LEAK.
  - Act 2: Collector OTTL redact_sentinel -> [DEMO-REDACTED] (trace 20211b7a...). Must go through Git:
    kyverno `block-argocd-drift` REJECTS live ConfigMap edits, so Act 2 is a GitOps toggle (commit/revert).
  - Teardown: NO_CONTENT -> op=chat, no content attrs (trace 69565ab1...).
  - Beat 3: ADK emits `execute_tool {gen_ai.tool.name}` natively (verified `execute_tool list_pods`);
    rogue induction is probabilistic on Haiku (0/4 runs) -> fallback.curl.sh is the deterministic path.
  - Runbook: `challenges/03-bad-mcp-excessive-agency/OBSERVABILITY-RUNBOOK.md`.
- **#20 M7 build verification** (`docs/prd20-m7-build-verification.md`): 5/7 pass. gen_ai.request.model
  on call_llm/chat/generate_content; content capture on/off; weaver live-check PASSES on REAL emitted
  spans (only stability:development advisories). Found OTLP/JSON int64-as-string gotcha (documented).

## Open decisions / items owed (2026-06-25)

- **#20 M7 item 5 (witb_cost_usd scrape) — NEEDS MICHAEL'S CALL.** The metric is shaped correctly
  (model label, no tier) and on the proxy /metrics, but nothing scrapes it: no ServiceMonitor (kube-
  prometheus-stack ignores pod annotations), and the Collector does not scrape the proxy. Prometheus has
  0 series -> the Grafana cost panel is EMPTY. The PRIMARY cost visual (web console -> /cost JSON) works.
  Decision: ServiceMonitor (-> Grafana) vs Collector prometheus scrape_config (-> Datadog). Not wired
  either way (no fallback added without permission).
- **#20 M4 agentgateway tracing — deferred.** agentgateway is staged (`gitops/ai-layer/agentgateway.yaml`)
  but NOT in the kustomization (5 verify-at-build blockers); its trace leg was out of scope this run.
- **Datadog LLM-Observability panel render** (#22 M4 / #20 M7 item 3) — facilitator UI check on Whitney's
  org; no Datadog Application key is in-cluster for programmatic confirmation.
- Cluster is still UP; tear down manually when done with live work.
