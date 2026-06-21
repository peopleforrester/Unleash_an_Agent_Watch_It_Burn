*Node sizing and cost as a function of cluster count N, per-cluster resource budget, the LLM Guard Regex-only default, AWS service-quota note, and the Phase-2 provision-time TODO. Build-facing.*

# SIZING, Nodes, Cost, and the LLM Guard Footprint Decision

Architecture (BUILD-SPEC rev4): **independent, standalone EKS cluster per student.** Each student gets their own take-home EKS cluster running its **own in-cluster ArgoCD** that reconciles itself from Git (`gitops/bootstrap/app-of-apps.yaml`, whose destination is the local cluster `kubernetes.default.svc`). There is no hub cluster and no central ArgoCD managing other clusters. The facilitator/presenter cluster and the demo burn clusters are simply more independent clusters of the same shape. All clusters share **one VPC** (provisioned once up front); cost and the binding AWS service quota scale with the cluster count, but networking does not, because the VPC and subnets are shared.

Rationale for independent clusters (not hub-and-spoke):

- **Take-home portability.** A hub-managed cluster goes inert the moment it is detached from its hub; a self-reconciling cluster keeps working when the student takes it home. This matches the sister Packt repo (one cluster per student, in-cluster ArgoCD).
- **Blast-radius isolation.** This is a chaos lab; an attendee wrecking their own cluster cannot touch anyone else's, and there is no shared control plane to take down.
- **No ArgoCD sharding.** A single central ArgoCD past the ~20-30 clusters-per-instance guidance would need sharding; for a 2-hour event with per-attendee clusters, self-reconciliation sidesteps that entirely.

`N` = cluster count. **Default working number = 25 attendee clusters.** The hard ceiling is an **open decision owned by Michael** (BUILD-SPEC §10.1); it drives total node count, total cost, AWS quota headroom, and the parallel provisioning window. Do not assume a ceiling; get it from Michael before provisioning at scale.

## The shared VPC (one, up front)

One VPC (`10.0.0.0/16`) is provisioned **once** for the whole fleet, before any cluster:

- Two shared private `/18` subnets across two AZs. **All clusters share those two private subnets.**
- Small public `/24`s for NAT / ingress.
- Cluster configs reference the **existing** VPC id + subnet ids; they do not each create a VPC.

IP math: about 9,000 pod IPs at 60 clusters in a `/16` is roughly 14 percent utilization, so VPC-CNI prefix delegation is not needed. Independent VPCs are only warranted for hard isolation or compliance, which a fake-data lab does not need. Source: `research/25-eks-quotas-shared-vpc-topology-2026.md`.

## Per-cluster resource budget (one student cluster)

Each cluster runs the full per-student stack:

- Its own in-cluster ArgoCD, Kyverno (admission webhooks), Falco (runtime, needs real node/kernel access), kagent agent + its ServiceAccount, agentgateway, the LLM Guard service/sidecar, the synthetic bad MCP server, the planted fake secrets, and a web-terminal pod.
- Falco and the per-cluster admission webhooks are a real part of why this is a real cluster and not namespace-tenancy.

**The dominant per-cluster variable is the LLM Guard footprint**, see the decision below. With LLM Guard in **Regex-only** mode, the per-cluster stack is modest and fits a small node group per cluster. With the `Sensitive` NER model loaded, RAM jumps materially (see below) and per-cluster node sizing must grow accordingly.

## Node sizing, T3 burstable by default

**Decision: T3 burstable, `t3.xlarge` default in unlimited credit mode.** This is a 2-hour intermittent lab, not production. Start conservative; measure one live cluster (`kubectl top` plus CloudWatch `CPUCreditBalance`) before pinning the fleet; scale only if a real 2-hour run actually chokes.

Cost delta to weigh (one node times 60 clusters times 3 hours, compute only):

- `t3.xlarge` about 30 dollars baseline.
- `m6i.xlarge` plus 15 percent.
- `2xlarge` plus 100 to 131 percent.

M-series is a **measured fallback only, never the starting point.** Source: `research/24-datadog-hybrid-impl-sizing-2026.md`.

Pin the exact per-cluster CPU/RAM requests into the cluster Helm values at build, after measuring a real cluster in Phase 2. Until measured, size conservatively and treat the numbers as estimates.

## The LLM Guard footprint decision, Regex-only by default

**Decision: LLM Guard runs per-cluster, output `Regex` scanner only, by default.** `Sensitive` (NER + regex) is **opt-in**, not on by default.

Why this is the default:

- The output **`Regex`** scanner is fully pattern-based, no model loads. It matches the planted `FAKE-...-sentinel` shapes. This is the control demonstrated live and it keeps each node small.
- The **`Sensitive`** scanner adds PII breadth but loads an **NER model**. Per research, the LLM Guard API server recommends **≥16 GB RAM** with model-backed scanners loaded; that does not fit a small per-cluster budget when multiplied across N clusters. Loading the NER model per cluster is the line item that breaks linear cost at scale.

**RAM cost of opting in:** turning on `Sensitive` loads the NER model into each cluster's LLM Guard instance. Across N clusters that is N× the model's resident footprint. If `Sensitive` is wanted for PII breadth, the options are: (a) accept the larger per-cluster node and the N× RAM cost; (b) enable `lazy_load` + `low_cpu_mem_usage` to defer/trim the load; or (c) run a single shared LLM Guard service the cluster gateways call, instead of one per cluster, so the model loads once. Decide before recording the beats.

Note on the input beat: input `PromptInjection` is a DeBERTa classifier (model-based) and carries its own footprint where the input guard runs. Account for it separately from the output `Regex` default.

## Cost as a function of N

Cost is **linear in N** (one managed control plane + node group per cluster); the VPC is a fixed, shared cost that does not scale with N:

```
total_cost ≈ shared_vpc_cost + N × (per_cluster_control_plane + per_cluster_nodes + per_cluster_overhead)
```

- **EKS control plane:** each cluster is a managed EKS cluster, so each carries its own per-cluster control-plane charge. This is a real fixed per-attendee line item and the reason N matters for cost, not just compute.
- **Cluster nodes:** the per-cluster node cost depends directly on the T3 sizing and LLM Guard decisions above; `t3.xlarge` unlimited keeps nodes small, `Sensitive` per-cluster pushes node size (and cost) up.
- **Shared VPC:** fixed, does not scale with N (one VPC, two private subnets, NAT for the fleet).
- **Runtime window:** cost accrues while clusters run. Pre-provision before doors, tear down promptly after (Phase 9). `teardown/cost-report.sh` reports the real AWS spend after the run for Accenture expensing, **no dollar estimate is asserted here**; the script reports the actual number.

The practical knobs: N (and its ceiling), per-cluster node size (driven by the T3 / LLM Guard decisions), and how long the clusters run.

## AWS service-quota note

N managed EKS clusters means N× a few AWS resources, and the right quota will bind before compute does. **Before provisioning at the chosen ceiling**, check and raise as needed:

- **EKS clusters per region:** the default is **100**, so 60 fits with no increase. Confirm the combined usage with the Packt project stays under 100.
- **EC2 On-Demand Standard vCPU** (quota code **L-1216C47A**): this is the real quota to request. Target about **1,000 vCPU** for an all-`t3.xlarge` fleet.
- With a **shared VPC**, the VPC-per-region, Elastic IP, and NAT quotas are moot (one VPC, shared subnets).

File quota-increase requests **well ahead of the event**; AWS approval is not instant. Treat the EC2 vCPU quota as the first thing to confirm once the ceiling is set. Source: `research/25-eks-quotas-shared-vpc-topology-2026.md`.

## Open items

- **Hard ceiling for N**, open decision owned by Michael (BUILD-SPEC §10.1). Default working number is 25; the ceiling drives node count, cost, quota requests, and provisioning parallelism.
- **Median provision time per cluster, Phase-2 TODO.** Not yet measured. BUILD-SPEC Phase 2 records the median provision time for a parallel set; that number lands here once measured on real EKS clusters. Until then, the parallel pre-provision window before doors is unknown, measure it in Phase 2 and update this file.
- **T3 fleet validation**, whether a real 2-hour run on `t3.xlarge` unlimited holds up, or whether the measured fallback to M-series is needed. Measure one live cluster (`kubectl top` + `CPUCreditBalance`) before pinning the fleet.
- **`Sensitive` opt-in decision**, whether to accept the N× NER RAM cost, trim it with lazy-load, or run a shared LLM Guard service. Decide before recording.
