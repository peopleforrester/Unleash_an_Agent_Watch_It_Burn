*Node sizing and cost as a function of attendee count N, per-spoke resource budget, the LLM Guard Regex-only default, AWS service-quota note, and the Phase-2 provision-time TODO. Build-facing.*

# SIZING — Nodes, Cost, and the LLM Guard Footprint Decision

Architecture (BUILD-SPEC rev3): **separate EKS cluster per attendee, hub-and-spoke.** A small **hub** cluster runs ArgoCD + the facilitator's Grafana/Tempo. Each attendee gets a **spoke** EKS cluster, registered to the hub ArgoCD, delivered the full IDP stack via an ApplicationSet cluster generator. Cost and AWS service quotas scale **linearly with N**.

`N` = attendee count. **Default N = 25.** The hard ceiling is an **open decision owned by Michael** (BUILD-SPEC §10.1) — it drives total node count, total cost, AWS quota headroom, and the parallel provisioning window. Do not assume a ceiling; get it from Michael before provisioning at scale.

## The hub cluster (one, shared)

Runs once for the whole room:

- ArgoCD (GitOps control + per-spoke app delivery via cluster generator).
- Grafana + Tempo (the facilitator trace lens) + Prometheus.

Hub sizing is **independent of N** in compute terms but its ArgoCD load grows with the number of registered spokes (more Applications to reconcile). Size the hub for steady reconciliation of N spokes, not for attendee workload. A small managed node group (2–3 general-purpose nodes) is the starting point; confirm against ArgoCD reconciliation load for the chosen ceiling at build.

## Per-spoke resource budget (one attendee cluster)

Each spoke runs the full per-attendee stack:

- Kyverno (admission webhooks), Falco (runtime, needs real node/kernel access), kagent agent + its ServiceAccount, agentgateway, the LLM Guard service/sidecar, the synthetic bad MCP server, the planted fake secrets, and a web-terminal pod.
- Falco and the per-cluster admission webhooks are a real part of why this is a real cluster and not namespace-tenancy.

**The dominant per-spoke variable is the LLM Guard footprint** — see the decision below. With LLM Guard in **Regex-only** mode, the per-spoke stack is modest and fits a small node group per spoke. With the `Sensitive` NER model loaded, RAM jumps materially (see below) and per-spoke node sizing must grow accordingly.

Pin the exact per-spoke CPU/RAM requests into the spoke Helm values at build, after measuring a real spoke in Phase 2. Until measured, size conservatively and treat the numbers as estimates.

## The LLM Guard footprint decision — Regex-only by default

**Decision: LLM Guard runs per-spoke, output `Regex` scanner only, by default.** `Sensitive` (NER + regex) is **opt-in**, not on by default.

Why this is the default:

- The output **`Regex`** scanner is fully pattern-based — no model loads. It matches the planted `FAKE-...-sentinel` shapes. This is the control demonstrated live and it keeps each spoke node small.
- The **`Sensitive`** scanner adds PII breadth but loads an **NER model**. Per research, the LLM Guard API server recommends **≥16 GB RAM** with model-backed scanners loaded; that does not fit a small per-spoke budget when multiplied across N spokes. Loading the NER model per spoke is the line item that breaks linear cost at scale.

**RAM cost of opting in:** turning on `Sensitive` loads the NER model into each spoke's LLM Guard instance. Across N spokes that is N× the model's resident footprint. If `Sensitive` is wanted for PII breadth, the options are: (a) accept the larger per-spoke node and the N× RAM cost; (b) enable `lazy_load` + `low_cpu_mem_usage` to defer/trim the load; or (c) run a single shared LLM Guard service the spoke gateways call, instead of one per spoke, so the model loads once. Decide before recording the beats.

Note on the input beat: input `PromptInjection` is a DeBERTa classifier (model-based) and carries its own footprint where the input guard runs. Account for it separately from the output `Regex` default.

## Cost as a function of N

Cost is **linear in N** (one managed control plane + node group per spoke) plus a fixed hub cost:

```
total_cost ≈ hub_cost + N × (per_spoke_control_plane + per_spoke_nodes + per_spoke_overhead)
```

- **EKS control plane:** each spoke is a managed EKS cluster, so each carries its own per-cluster control-plane charge. This is a real fixed per-attendee line item and the reason N matters for cost, not just compute.
- **Spoke nodes:** the per-spoke node cost depends directly on the LLM Guard decision above — Regex-only keeps nodes small; `Sensitive` per-spoke pushes node size (and cost) up.
- **Hub:** fixed, does not scale with N (subject to ArgoCD reconciliation load).
- **Runtime window:** cost accrues while clusters run. Pre-provision before doors, tear down promptly after (Phase 9). `teardown/cost-report.sh` reports the real AWS spend after the run for Accenture expensing — **no dollar estimate is asserted here**; the script reports the actual number.

The practical knobs: N (and its ceiling), per-spoke node size (driven by the LLM Guard decision), and how long the clusters run.

## AWS service-quota note

N managed EKS clusters means N× several AWS resources, and the default account quotas will bind before compute does. **Before provisioning at the chosen ceiling**, check and raise as needed:

- **EKS clusters per region** (default account limits are low relative to a large N — this is the most likely binding quota).
- VPCs per region (or a shared-VPC design), Elastic IPs / NAT gateways, subnets.
- EC2 instance vCPU quotas for the chosen instance family, across N spokes' node groups.
- Any per-region limits on managed node groups.

File quota-increase requests **well ahead of the event** — AWS approval is not instant. Treat the EKS-clusters-per-region quota as the first thing to confirm once the ceiling is set.

## Open items

- **Hard ceiling for N** — open decision owned by Michael (BUILD-SPEC §10.1). Default working number is 25; the ceiling drives node count, cost, quota requests, and provisioning parallelism.
- **Median provision time per spoke — Phase-2 TODO.** Not yet measured. BUILD-SPEC Phase 2 records the median provision time for a parallel set; that number lands here once measured on real EKS spokes. Until then, the parallel pre-provision window before doors is unknown — measure it in Phase 2 and update this file.
- **`Sensitive` opt-in decision** — whether to accept the N× NER RAM cost, trim it with lazy-load, or run a shared LLM Guard service. Decide before recording.
