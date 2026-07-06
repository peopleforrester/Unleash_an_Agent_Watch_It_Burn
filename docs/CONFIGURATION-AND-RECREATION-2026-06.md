# Configuration and Recreation Reference (verified 2026-06-26)

ABOUTME: Authoritative June-2026 configuration of the whole workshop stack, with version-currency
ABOUTME: verification, AWS best-practice findings, spec-coverage audit, and a from-scratch rebuild order.

This is the single document to read before recreating or restarting the platform. Every version and
best-practice claim below was verified against a live source dated 2026, not from training data, per
the recency-verification discipline. Where a claim is load-bearing, the source is cited inline. The
verification corrections and key decisions also live in `docs/DECISION-LOG.md`.

Scope of the AWS account at verification time: profile `accen-dev`, region `us-west-2`, EKS 1.35.

---

## 1. Recreation order (the rebuild runbook)

The platform rebuilds from code in this order. Nothing below depends on any AWS resource that the
fleet teardown leaves behind; a clean account rebuilds end to end.

1. **Shared lab VPC.** `infra/terraform/aws/network/` (`terraform init && terraform apply`). One VPC
   (10.0.0.0/16), two /18 private subnets, a single shared NAT, and the Bedrock interface VPC
   endpoint (added 2026-06-26, see §5). Outputs `vpc_id`, `private_subnet_ids`, `bedrock_vpce_id`.
2. **Clusters.** `infra/terraform/fleet/fleet.sh up <N>` for attendee clusters or
   `fleet.sh instructors up <round>` for the nine instructor clusters. Each attaches to the shared
   VPC subnets. Cluster terraform is `infra/terraform/aws/cluster/main.tf` (EKS 1.35, managed addons,
   EKS Pod Identity for agent/ESO/LB-controller, IRSA only for the EBS CSI driver).
3. **IDP bootstrap.** `infra/setup-instructor-cluster.sh <cluster> <round>` (or `deploy-full-idp.sh`
   directly). `burn` profile selects `gitops/bootstrap/app-of-apps-burn.yaml` (R1: agent + cost proxy
   only); `full` selects `gitops/bootstrap/app-of-apps.yaml` (R2/R3: the whole CNCF + AI stack).
4. **Round state.** R1 is burn-as-is. R2/R3 wait for the Kyverno policy to sync, then
   `challenges/01-cncf-wall/toggle-kyverno-enforce.sh` flips Audit to Enforce. R3 additionally lets
   the attendee flip the AI guards live: output guard, then input blocklist/classifier, then MCP
   authorization.
5. **Credential distribution.** `lab-distribution/` (Railway-hosted) maps each attendee to a cluster
   URL plus Datadog and AWS keys; `lab-distribution/scripts/distribute_datadog_keys.py` writes the
   per-cluster `watch-it-burn/datadog` secret that ESO fans out to the `monitoring`, `security`, and
   `datadog` namespaces. The attendee Datadog pool (the AI Engineer World's Fair orgs) is staged in
   Secrets Manager as `watch-it-burn/datadog-pool` + `watch-it-burn/datadog-pool-2` (split because one
   secret caps at 64 KB; `merge_pool.py` reads both). Whitney's two admin orgs are separate:
   `watch-it-burn/datadog` (instructor, r1/r2/r3) and `watch-it-burn/datadog-admin-attendee` (the
   attendee cluster, repointed on the `whitney-attendee` branch so its metrics stay separate).

6. **Per-account AWS quotas (recreation prerequisite, us-west-2).** At 50-60 clusters per account these
   bind, all adjustable: EC2 vCPU "Running On-Demand Standard" (L-1216C47) -> 800; Application Load
   Balancers per Region (L-53DA6B97) -> 100; Network Load Balancers per Region (L-69A177A2) -> 100 (each
   full cluster is 1 ALB + 1 NLB, default 50 each). Elastic IPs need NO increase: ALB IPs are
   AWS-managed and don't count; only the one shared-VPC NAT counts (1 of 5). Verified 2026-06-26
   (see `docs/DECISION-LOG.md` and `docs/GO-LIVE-CHECKLIST.md`).

Teardown is `fleet.sh down <names|all>` for clusters; the shared VPC is destroyed separately with
`terraform -chdir=infra/terraform/aws/network destroy`. The cluster teardown does NOT remove the
`console` Classic ELB or its security group (see §5); those leak and must be cleaned by hand until the
load-balancer fix lands.

---

## 2. Full technology stack (as configured)

Every distinct technology and the file that configures it. Versions are the repo's current pins.

| Layer | Technology | Version (pinned) | Config file |
|---|---|---|---|
| Cloud | EKS | 1.35 | `infra/terraform/aws/cluster/main.tf` |
| Cloud | Terraform | >= 1.10 (run 1.15.x) | `infra/terraform/{aws/network,aws/cluster,fleet}/` |
| Network | VPC-CNI (native NetworkPolicy) | EKS addon, `enableNetworkPolicy=true` | `cluster/main.tf` |
| Identity | EKS Pod Identity | agent + ESO + LB-controller roles | `cluster/main.tf` (eks-pod-identity module) |
| Identity | IRSA | EBS CSI driver only | EKS addon |
| GitOps | Argo CD | v3.4.x (chart 9.6.0) | `gitops/bootstrap/app-of-apps*.yaml` |
| Admission | Kyverno | chart 3.8.1 / app 1.18.1 | `gitops/apps/kyverno.yaml`, `policies/kyverno/` |
| Mesh | Istio (ambient) | 1.30.1 | `gitops/apps/istio.yaml` |
| TLS | cert-manager | v1.20.2 | `gitops/apps/cert-manager.yaml` |
| Secrets | External Secrets Operator | chart 2.6.0 / app v2.6.0 | `gitops/apps/external-secrets.yaml` |
| Secrets | AWS Secrets Manager | prefix `watch-it-burn/*` | `cluster/main.tf` (ESO Pod Identity scope) |
| Runtime sec | Falco | chart 9.1.0 / app 0.44.x, `modern_ebpf` | `gitops/apps/falco.yaml` |
| Runtime sec | Falcosidekick | chart 0.14.0 / app 2.31.1 | `gitops/apps/falcosidekick.yaml` |
| Runtime sec | Falco Talon | chart 0.4.1 / app 0.3.0 | `gitops/apps/falco-talon.yaml` |
| Network sec | NetworkPolicy | default-deny + per-namespace allowlists | `policies/network-policies/` |
| Agent | kagent (ADK) | OCI 0.9.9, CRD kagent.dev/v1alpha2 | `gitops/ai-layer/resources.yaml` |
| Agent | AWS Bedrock / Claude | Haiku 4.5 / Sonnet 4.6 / Opus 4.8 (`us.` profiles) | `gitops/ai-layer/resources.yaml`, `VERSIONS.lock` |
| Agent | agentgateway | OSS v1.3.0 (`cr.agentgateway.dev`) | `gitops/ai-layer/agentgateway.yaml` |
| Guard | LLM Guard | `laiyer/llm-guard-api:0.3.16` | `gitops/ai-layer/resources.yaml` |
| Guard | guard-proxy | custom Python stdlib | `gitops/ai-layer/proxy.py` |
| MCP | workshop-mcp + evil-mcp-shim | custom FastMCP | `gitops/ai-layer/{workshop-mcp-server,server}.py` |
| Telemetry | OTel Collector (contrib) | chart 0.158.2 / image 0.15x | `gitops/apps/otel-collector.yaml` |
| Telemetry | OTel Operator (auto-instr) | chart 0.117.0 | `gitops/apps/otel-operator.yaml` |
| Telemetry | OTel Weaver (span contract) | registry check in CI | `weaver/registry/` |
| Backend | Datadog Operator + Agent | chart 2.23.2 / app 1.27.1, CR v2alpha1 | `gitops/apps/datadog-operator.yaml`, `gitops/manifests/datadog/` |
| Backend | kube-prometheus-stack | chart 86.2.3 | `gitops/apps/prometheus.yaml` |
| Backend | Grafana Tempo | chart 2.2.3 | `gitops/apps/tempo.yaml` |
| Backend | Grafana Alloy + Loki | chart 1.10.0 / 7.0.0 | `gitops/apps/{alloy,loki}.yaml` |
| Portal | Backstage | chart 2.8.2 | `gitops/apps/backstage.yaml` |
| Hosting | Railway + Caddy | walkthrough decks, apex, distributor | `railway/`, `lab-distribution/` |
| DNS | Namecheap (`agenticburn.com`) | A-record automation | `infra/dns/set-demo-dns.py` |

---

## 3. June-2026 recency verdicts and corrections

Every pin was checked against a live dated source. The stack is current. Two substantive corrections
and a short list of optional patch bumps. No version regressions anywhere.

### Substantive corrections (do these)

1. **OTel Collector connector key rename.** The connector type was renamed `spanmetrics` to
   `span_metrics` (snake_case). The old name still works but is deprecated and will be removed in a
   future contrib release. Rename the connector block and both pipeline references in
   `gitops/apps/otel-collector.yaml`. Source: spanmetrics connector README, accessed 2026-06-26.
2. **Kyverno failure-action field.** Two policies (`disallow-privileged.yaml`, `require-labels.yaml`)
   still use the policy-level `spec.validationFailureAction`, deprecated since Kyverno **1.13** (not
   1.18, which is what the inline comment says). Standardize on the rule-level
   `spec.rules[].validate.failureAction` used by the other policies, and fix the version comment.
   Source: Kyverno policy-settings docs, accessed 2026-06-26.
3. **GenAI semconv attribute rename.** The current OpenTelemetry GenAI semantic conventions use
   `gen_ai.provider.name` (required), not `gen_ai.system`. `proxy.py` does not emit `gen_ai.system`,
   but the BUILD-SPEC attribute list and any kagent/ADK auto-instrumentation that still uses the old
   key should move to `gen_ai.provider.name`. Source: semantic-conventions-genai, accessed 2026-06-26.

### Verified current, no change

- **Bedrock model IDs (the most recency-sensitive item).** Haiku
  `us.anthropic.claude-haiku-4-5-20251001-v1:0`, Sonnet `us.anthropic.claude-sonnet-4-6`, Opus
  `us.anthropic.claude-opus-4-8` are all ACTIVE and current. They match Anthropic's own Claude-Code-on-
  Bedrock defaults byte for byte, including the asymmetry where only Haiku carries the dated
  `-20251001-v1:0` suffix. The `us.` cross-region inference-profile prefix is required (Opus and Sonnet
  4.6 are not available as in-region IDs in us-west-2). No deprecation, no newer default supersedes
  them. Sources: code.claude.com/docs/en/amazon-bedrock and the Anthropic model catalog, 2026-06.
- **`gen_ai.client.token.usage`** is still the standard token metric (attributes `gen_ai.token.type`
  input/output, `gen_ai.request.model`); it remains spec-experimental ("Development"). There is still
  **no** standard monetary metric, so `gen_ai.client.cost` is a legitimate project extension under the
  standard `gen_ai.` namespace, correctly NOT invented as a `witb_*` tree. It will not be auto-
  recognized by backends the way the token metric is.
- **EKS Pod Identity** for agent/ESO/LB-controller is the 2026-recommended workload-identity pattern;
  the repo is already on it. IRSA for the EBS CSI driver only is acceptable.
- **Bedrock interface endpoint** `com.amazonaws.us-west-2.bedrock-runtime` is the correct service name
  for InvokeModel/Converse; private DNS on is correct. Source: Bedrock VPC interface-endpoints docs.
- **Native VPC-CNI NetworkPolicy** (≥ v1.14.0-eksbuild.3; ≥ v1.21.0 for AdminNetworkPolicy) is the
  right enforcement choice for this single-node-per-attendee lab; no Calico/Cilium needed.
- **ESO** is on `external-secrets.io/v1` (GA). `v1beta1` is no longer served since app v0.17.0;
  pinning it would be a regression. The repo is correct.
- **Datadog** Operator chart 2.23.2 / app 1.27.1 is the current GA-on-GA pair (do NOT move to the
  2.24-dev / 1.28-rc line). CR `datadoghq.com/v2alpha1` is current. UST `deployment.environment.name`
  (not the deprecated bare `deployment.environment`) is correct and needs Agent >= 7.58 / Exporter
  >= 0.110.
- **datadog/connector + spanmetrics** dual-connector is the current APM-trace-metrics pattern (the
  Datadog exporter now skips APM stats by default).
- **Kyverno** chart 3.8.1 / app 1.18.1 is current and carries the 2026-05 SSRF CVE patches.
  `ClusterPolicy` (kyverno.io/v1) is supported now but on a path to removal around v1.20 (~Oct 2026)
  in favor of the CEL `ValidatingPolicy` types; fine for the workshop.
- **Falco** 0.44.x with `modern_ebpf` is current; do not reintroduce the legacy `ebpf` driver or gRPC
  outputs (removed in 0.44.0). **Falco Talon** is correctly pinned but is incubating and its app has
  been stalled at v0.3.0 since 2026-02; treat as a slow-moving dependency.
- **Argo CD** v3.x app-of-apps + sync-waves is current best practice; latest stable is v3.4.4 (the
  repo references v3.4.3, a one-patch bump that includes an RBAC regression fix).

### Optional patch bumps (no breaking changes)

- agentgateway v1.3.0 to **v1.3.1** (2026-06-22). Config schema and `mcpAuthorization` CEL semantics
  unchanged.
- kagent 0.9.9 to **v0.9.10** (2026-06-24).
- OTel Collector chart 0.158.2 to 0.159.0; Argo CD reference v3.4.3 to v3.4.4.

---

## 4. AWS best-practice findings

### 4.1 The Classic ELB (root cause and fix)

The two Classic ELBs the teardown left orphaned are the **`console` Service** in
`gitops/ai-layer/resources.yaml`. It is a bare `type: LoadBalancer` Service with no
`aws-load-balancer-type` annotation and no `loadBalancerClass`, so it is reconciled by the legacy
in-tree AWS cloud provider, which provisions a **Classic Load Balancer by default**. One per cluster,
two destroyed clusters, two orphans. Source: EKS load-balancing docs, accessed 2026-06-26.

The deeper half of the same gap: the **AWS Load Balancer Controller is never installed.** The IAM Pod
Identity role exists (`cluster/main.tf`, `aws_lb_controller_pod_identity`) but nothing consumes it.
Two consequences: (a) the `console` Service falls to the in-tree provider and gets a Classic ELB, and
(b) the five ALB `Ingress` objects for the party apps (`ingressClassName: alb`) are inert, so
`hedgehog/unicorn/spider/wombat/mantis-shrimp.agenticburn.com` are unreachable through their Ingress
hosts. This is a live functional gap, not just a cleanup nuisance.

**Fix (one change closes both):**
1. Add an Argo CD Application that Helm-installs the AWS Load Balancer Controller, service account
   `aws-load-balancer-controller` in `kube-system` to bind the existing Pod Identity association. Pin
   controller v2.13.x / chart ~1.14.x (the AWS-documented line; v3.x exists but only matters if you
   adopt the Kubernetes Gateway API, which this workshop does not). Verify the exact version at deploy.
2. Make the `console` Service explicit:
   ```yaml
   service.beta.kubernetes.io/aws-load-balancer-type: external
   service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
   service.beta.kubernetes.io/aws-load-balancer-scheme: internet-facing
   ```
   This gives an NLB targeting pod IPs (the current AWS-recommended L4 pattern) instead of a Classic
   ELB, and installing the controller simultaneously activates the five dead ALB Ingresses.

No-controller stopgap: adding `aws-load-balancer-type: nlb` to the `console` Service makes the in-tree
provider build an NLB instead of a CLB, but it does not fix the dead ALB Ingresses. Since the IAM is
already wired and the party apps need ALBs, install the controller.

### 4.2 Other AWS items (all current, kept for the record)

- **vpc-cni addon** should be pinned to an explicit version >= v1.21.0 across the fleet so native
  NetworkPolicy enforcement is guaranteed identical everywhere (currently relies on the default).
- **coredns / kube-proxy / eks-pod-identity-agent** addons are unpinned (`{}`); explicit pins improve
  fleet reproducibility.
- **EKS 1.35** is in standard support (1.36 went GA on EKS 2026-06-02). The 1.35 pin is a sensible
  fixed-date-event choice, valid through ~2027-03. Not a regression.
- **Single shared NAT** is the correct cost/availability trade for a disposable lab. A fully-private
  ECR pull path is impossible here without an S3 endpoint, which the exfil control deliberately
  forbids (ECR layers live in S3), so image pulls traverse the NAT by design. Keep the single NAT.

---

## 5. The C1 exfil control (added 2026-06-26)

Recorded here because it spans terraform and gitops and must be recreated as a unit.

- **`infra/terraform/aws/network/main.tf`**: a Bedrock interface VPC endpoint (`aws_vpc_endpoint`
  `bedrock_runtime`, private DNS on) plus a security group allowing 443 from the VPC CIDR. The agent
  now reaches Bedrock by an in-VPC ENI. There is deliberately NO S3 endpoint, so S3 stays public.
- **`policies/network-policies/per-namespace/agent-*.yaml`**: four egress-only NetworkPolicies on the
  `agent` namespace (in-VPC 443 allowlist, DNS, OTLP to monitoring, intra-namespace). The AI layer
  runs in `agent`, not `apps`, which is why the apps-only policies left a hole. Selecting agent pods
  with an egress policy makes them default-deny-egress; S3 PutObject to the public internet has no
  allow and is denied while Bedrock and the in-namespace chain still work.

The two halves must land together: without the VPC endpoint, the default-deny-egress would break the
agent's Bedrock calls. The live re-test (Bedrock works, S3 denied) runs on the next provision.

---

## 6. Spec completeness: rounds, challenges, builds, demos

### Rounds (all three covered in spec and code)

Cumulative model, same install, different enabled controls. R1 `burn` = agent + cost proxy only, no
production guardrails. R2 `full` = the full CNCF stack enforcing (Kyverno Enforce, Falco+Talon,
NetworkPolicy default-deny, Istio mTLS, ESO, RBAC, cert-manager), AI guards off. R3 = R2 plus the
attendee toggling the AI guards live (output, then input, then MCP). Documented in `docs/BUILD-SPEC.md`,
`docs/BUILD-PLAN.md`, `facilitation/runbook.md`, and the `railway/rounds-walkthrough/` deck. Selector
is `infra/deploy-full-idp.sh` (`app-of-apps.yaml` vs `app-of-apps-burn.yaml`).

### Challenges (C1 to C7)

| # | Name | Defense | Toggle | Packaged? |
|---|---|---|---|---|
| C1 | Customer-data exfil to S3 | NetworkPolicy default-deny egress + Istio mTLS | deploy-time | substrate built; **no beat.md runbook** |
| C2 | Deploy a villain app | Kyverno registry allowlist (Enforce) | `01-cncf-wall/toggle-kyverno-enforce.sh` | yes |
| C3 | Find the planted secret | Falco sensitive-file rule + ESO | always-on R2/R3 | bait file + breadcrumbs exist; **no setup script / runbook** |
| C4 | Fork bomb | per-pod PID limit + Falco+Talon terminate | terraform node config | defense built; **no facilitator runbook** |
| C5 | Output: secret/PII in reply | guard-proxy output Regex guard | `02-sanitization/toggle-output-guard-on.sh` | yes |
| C6 | Input: block before the model | blocklist then DeBERTa classifier | `02-sanitization/toggle-input-{guard,classifier}-on.sh` | yes |
| C7 | Rogue MCP / excessive agency | agentgateway mcpAuthorization + kagent toolNames | `03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh` | yes (toggle is the pre-gateway overlay, see gaps) |

Every challenge has code. None is spec-only. The rounds-walkthrough deck is the canonical C1 to C7
mapping and matches the implementation.

### Top gaps to close in the spec (from the audit)

1. **PRD status headers are stale.** PRDs #13/#20/#22/#23/#26/#27/#28/#33/#34 say "Status: Not
   started" while PROGRESS.md records live verification. Anyone reading a PRD header would conclude the
   work has not begun. Update the headers.
2. **AWS Load Balancer Controller never installed** (see §4.1). Party-app Ingresses are dead and the
   console gets a Classic ELB. Highest-impact functional gap.
3. **C1, C3, C4 are not packaged as attendee/facilitator runbooks** (no `beat.md`-style file, and C3
   has no script that plants the bait file). The substrate exists; the delivery wrapper does not.
4. **R1 PID-cap divergence.** The spec says R1 nodes have no PID cap, but `cluster/main.tf` defaults
   `pod_pids_limit = 1024` for all clusters and `fleet.sh` does not override it for burn clusters. R1
   still lacks Falco+Talon to kill the offending pod, so C4 still degrades the node, but the "no cap"
   claim is not true as implemented. Decide: change the spec or pass `pod_pids_limit=0` for burn.
5. **Model-tier ModelConfigs are commented out.** `resources.yaml` ships Haiku as default with the
   Sonnet/Opus `ModelConfig` blocks commented. The three instructor Cluster-3s (haiku/sonnet/opus)
   need a committed per-cluster override mechanism, or they all deploy Haiku. Note: the workshop
   default was set to Sonnet 4.6; reconcile this file with that decision.
6. **kagent RemoteMCPServer bypasses agentgateway.** The agent dials `workshop-mcp:8000` directly, so
   agentgateway's `mcpAuthorization` never runs on real tool calls and the C7 live toggle is not
   enforced on the true path. Repoint `RemoteMCPServer.url` at `agentgateway.agent:3001/mcp`, or
   accept the kagent `toolNames` allowlist as the actual mechanism (see the MCP-path note in the
   decision log). The `toggle-mcp-authz-on.sh` script applies a pre-agentgateway overlay and needs a
   rewrite either way.
7. **Implemented-but-unspecced:** `games/eso-s3-exfil/`, `games/villain-apps/`, Grafana Alloy, Loki,
   the Datadog ESO fan-out manifest, `infra/setup-instructor-cluster.sh`, and the BurritoBot narrative
   frame all exist in code without a PRD or BUILD-SPEC entry. Add brief spec entries so the inventory
   is complete.
8. **Specced-but-unbuilt:** the live cost-counter front-end widget (`/cost` endpoint exists, no UI),
   the `infra/terraform/dashboards/` module and the four custom Datadog story dashboards (PRD #33),
   Harbor as an Argo CD app (only `infra/harbor/` scripts exist; `verify-image-signatures` is Audit,
   not Enforce), and the pre-recorded asciinema fallbacks (deferred).

---

## 7. Prioritized action list

### Landed in the 2026-06-26 code pass (no live cluster, no multi-account)

- **Console Classic ELB stopgapped.** `gitops/ai-layer/resources.yaml` console Service now carries
  `aws-load-balancer-type: nlb`, so the in-tree provider builds an NLB instead of a Classic ELB. No
  controller needed. The full controller install (ip-target NLB + activating the party ALB Ingresses)
  is still open: it needs per-cluster `clusterName` wiring and a live NLB-provisions check.
- **R1 PID cap fixed to match the spec.** `fleet.sh` now passes `pod_pids_limit=-1` for Round-1 burn
  clusters (no cap, so the fork bomb lands), keeping 1024 for R2/R3/attendees. `cluster/main.tf`
  documents the `-1` semantics.
- **C7 toggle repaired.** `toggle-mcp-authz-on.sh` was applying a broken `ATTENDEE_NAMESPACE` overlay
  with the wrong agentgateway schema. It now patches the in-path control, the kagent Agent `toolNames`
  allowlist, and `gitops/apps/ai-layer.yaml` gained an `ignoreDifferences` on the Agent's tools so
  selfHeal does not revert the live toggle. The gateway-enforced path (repoint through agentgateway)
  is left documented, pending a live spike.
- **Kyverno version comments corrected** (rule-level `validate.failureAction` since 1.13, not 1.18).

### Deliberately deferred (need a live cluster or gitops restructuring)

- Repointing kagent MCP through agentgateway (would break MCP entirely if the listener path is wrong;
  needs a live spike).
- The OTel `spanmetrics` to `span_metrics` rename (the pinned contrib image supports the current key;
  the rename only matters when bumping the image, and renaming blind risks the collector).
- Per-instructor-cluster ModelConfig override (a runtime patch is reverted by ArgoCD selfHeal; needs a
  kustomize overlay per tier, and the tier demo is optional anyway).
- The AWS Load Balancer Controller install, the Kyverno field migration, and the live re-validations.

### Full list

| # | Priority | Action | Where |
|---|---|---|---|
| 1 | P0 | Install AWS Load Balancer Controller; annotate `console` for NLB | new `gitops/apps/aws-load-balancer-controller.yaml`, `gitops/ai-layer/resources.yaml` |
| 2 | P0 | Update stale PRD status headers to match PROGRESS.md | `prds/*.md` |
| 3 | P1 | Decide and fix the R1 PID-cap divergence | `infra/terraform/aws/cluster/main.tf`, `fleet/fleet.sh` |
| 4 | P1 | Commit per-instructor-cluster ModelConfig overrides (Sonnet/Opus); set workshop default to Sonnet | `gitops/ai-layer/resources.yaml` |
| 5 | P1 | Repoint kagent RemoteMCPServer through agentgateway, or ratify toolNames as the mechanism; rewrite the C7 toggle | `gitops/ai-layer/resources.yaml`, `challenges/03-bad-mcp-excessive-agency/` |
| 6 | P2 | Package C1/C3/C4 runbooks + the C3 bait-file setup script | `challenges/c1-exfil-s3/`, `c3-secret-grep/`, `c4-fork-bomb/` |
| 7 | P2 | Rename OTel connector `spanmetrics` to `span_metrics` | `gitops/apps/otel-collector.yaml` |
| 8 | P2 | Standardize Kyverno on rule-level `validate.failureAction`; fix the 1.18 to 1.13 comment | `policies/kyverno/` |
| 9 | P2 | Pin vpc-cni >= v1.21.0 and the other managed addons | `infra/terraform/aws/cluster/main.tf` |
| 10 | P3 | Patch bumps: agentgateway 1.3.1, kagent 0.9.10, OTel chart 0.159.0, Argo CD v3.4.4 | respective files |
| 11 | P3 | Rename `gen_ai.system` to `gen_ai.provider.name` where emitted | BUILD-SPEC, ADK auto-instr |
| 12 | P3 | Add spec entries for the implemented-but-unspecced items | `prds/`, `docs/BUILD-SPEC.md` |
