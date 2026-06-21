> **Provisioning is Terraform, not eksctl.** Burn clusters use the same
> `infra/terraform/cluster/` module as attendee clusters (provision with `fleet.sh`); they are
> differentiated only by which gitops profile is applied after creation (the burn app-of-apps).

*The facilitator cluster fleet for the three-cluster run-of-show (BUILD-SPEC §2/§5). Same Terraform
cluster module as attendees, differentiated by which bootstrap profile is applied after creation.*

# Burn-cluster fleet

| Role | Count | Bootstrap profile (what gets installed) | Purpose |
|---|---|---|---|
| **Cluster 1** (no guardrails) | **3 live + ~10 disposable spares** | NO admission at all (no Kyverno, no floor) + the agent + cost-meter proxy | Dies in one prompt; facilitator rotates spares from SSH as each dies ("URL one's gone, here's two"). Cost counter climbs. |
| **Cluster 2** (CNCF-only) | **3** | CNCF stack: ArgoCD + Kyverno (require-resource-limits, block-argocd-drift) + RBAC + Falco + floor + agent. No AI guardrails. | Blocks the destruction; cost still incurred. |
| **Instructor Cluster 3** | **3** (one per model tier; +1 if Fable returns) | Full Cluster-3 stack (CNCF + kagent + guard-proxy + LLM Guard + MCP wiring), each pinned to a tier (Haiku/Sonnet/Opus) | Side-by-side model-tier comparison; the Haiku one also serves as the follow-along so one attendee wrecking theirs doesn't break the demo. |
| **Attendee Cluster 3** | **N + reserve** | Full Cluster-3 stack, delivered by the ApplicationSet cluster generator | Each attendee's own; a few held in reserve. |

## Why no floor on Cluster 1
Cluster 1 carries NO admission control and no floor: a single destructive prompt kills it. That is the
point, the spectacle is the speed of death plus the climbing cost counter, not a gradual burn. The
facilitator rotates ~10 disposable spares from the SSH session as each dies. Follow-along happens on the
instructor Cluster 3s, which are protected by their full CNCF stack (not a floor).

## Provision (parallel) + rotate
```bash
# Cluster 1 spares
for id in c1-1 c1-2 c1-3; do
  CLUSTER_ID=$id envsubst < cluster.yaml | eksctl create cluster -f - &   # verify-at-build: envsubst availability
done; wait
# then per role, apply the matching bootstrap profile + default gp3 StorageClass (infra/gp3-storageclass.yaml)
```
Re-provision is ~15 min, so the 3× Cluster 1 are warm before doors open; when one dies the facilitator
switches to the next URL. Watch AWS EKS-cluster and EC2 vCPU quotas, the fleet (3+3+2 + N attendee)
can hit them. Tear the whole fleet down with `teardown/teardown.sh`.

## Sizing note
Cluster 1/2 are light (t3.large ×2). Instructor/attendee Cluster 3 runs the full stack incl. LLM Guard
(Regex-only), t3.large works in test; bump to t3.xlarge if Sensitive NER or heavier guards are added.
The 3 instructor Cluster 3s run side by side during the model-tier comparison; the frontier-tier one
(Opus) costs more per minute while running, which is expected (it is the cost story), but keep the
segment short and tear the fleet down right after.

## Deploy per role (which root app to apply)

Two deployment profiles, selected by `infra/deploy-full-idp.sh <profile>`:

| Role | Cluster(s) | Profile | Root app | Operated as |
|---|---|---|---|---|
| **Cluster 1** | 3 | `burn` | `gitops/bootstrap/app-of-apps-burn.yaml` | no enforcing policies; gets wrecked; cost counter via the guard-proxy |
| **Cluster 2** | 3 | `full` | `gitops/bootstrap/app-of-apps.yaml` | full IDP; **run with AI guards OFF** = the CNCF-only experience |
| **Instructor Cluster 3** | 3 (one per model tier; +1 if Fable returns) | `full` | `gitops/bootstrap/app-of-apps.yaml` | full IDP + AI layer; each pinned to a tier (Haiku/Sonnet/Opus) for the side-by-side comparison; the Haiku one doubles as the follow-along where guards are toggled |
| **Attendee Cluster 3** | N + reserve | `full` | `gitops/bootstrap/app-of-apps.yaml` | each attendee's own; they toggle guards |

C2 and C3 share the **full** deployment and differ only in operation (C2: guards stay off; C3: guards
get toggled on via the guard-proxy `/toggle`). A stricter C2 without the AI layer at all is a possible
refinement (split the ai-layer into agent-only + guards), flagged but not built.

Per role:
```bash
# Cluster 1 (each of the 3):
CLUSTER_ID=c1-1 envsubst < cluster.yaml | eksctl create cluster -f -
./../deploy-full-idp.sh burn        # then add agent Bedrock IRSA (see cluster3-setup.sh)
# Cluster 2 / instructor & attendee Cluster 3:
./../deploy-full-idp.sh full        # then add agent Bedrock IRSA
```
The agent's Bedrock IRSA is per-cluster (IAM, not GitOps) on every cluster that runs the agent.
