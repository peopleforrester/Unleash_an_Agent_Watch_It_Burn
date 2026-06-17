*The facilitator cluster fleet for the three-cluster run-of-show (BUILD-SPEC §2/§5). Same eksctl
shape (`cluster.yaml`), differentiated by which bootstrap profile is applied after creation.*

# Burn-cluster fleet

| Role | Count | Bootstrap profile (what gets installed) | Purpose |
|---|---|---|---|
| **Cluster 1** (no guardrails) | **3** | `minimal-floor` ONLY (platform/kyverno/policies/minimal-floor.yaml) + the agent | Burns over the segment; rotated as each dies ("URL one's gone, here's two"). Cost counter climbs. |
| **Cluster 2** (CNCF-only) | **3** | CNCF stack: ArgoCD + Kyverno (require-resource-limits, block-argocd-drift) + RBAC + Falco + floor + agent. No AI guardrails. | Blocks the destruction; cost still incurred. |
| **Instructor Cluster 3** | **2** | Full Cluster-3 stack (CNCF + kagent + guard-proxy + LLM Guard + MCP wiring) | Follow-along copies so one attendee wrecking theirs doesn't break the demo. |
| **Attendee Cluster 3** | **N + reserve** | Full Cluster-3 stack, delivered by the ApplicationSet cluster generator | Each attendee's own; a few held in reserve. |

## Why the minimal floor on Cluster 1
Even Cluster 1 carries `minimal-floor` so it can't be killed by one trivial prompt — it should burn
*gradually* over the segment (delete demo workloads = visible burn) while the control plane, ArgoCD,
and the agent itself survive long enough to keep the spectacle running. The same floor protects the
instructor follow-along clusters from accidental destruction.

## Provision (parallel) + rotate
```bash
# Cluster 1 spares
for id in c1-1 c1-2 c1-3; do
  CLUSTER_ID=$id envsubst < cluster.yaml | eksctl create cluster -f - &   # verify-at-build: envsubst availability
done; wait
# then per role, apply the matching bootstrap profile + default gp3 StorageClass (infra/gp3-storageclass.yaml)
```
Re-provision is ~15 min, so the 3× Cluster 1 are warm before doors open; when one dies the facilitator
switches to the next URL. Watch AWS EKS-cluster and EC2 vCPU quotas — the fleet (3+3+2 + N attendee)
can hit them. Tear the whole fleet down with `teardown/teardown.sh`.

## Sizing note
Cluster 1/2 are light (t3.large ×2). Instructor/attendee Cluster 3 runs the full stack incl. LLM Guard
(Regex-only) — t3.large works in test; bump to t3.xlarge if Sensitive NER or heavier guards are added.
