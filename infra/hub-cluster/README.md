*Purpose: stand up the small hub EKS cluster that runs ArgoCD and the facilitator's Grafana/Tempo, then bootstrap the hub stack.*

# Hub cluster

The hub is a single small EKS cluster. It runs **no attendee workloads** — only:

- **ArgoCD** (`v3.4.3`) — the GitOps control plane every spoke registers to.
- **kube-prometheus-stack** (chart `86.2.3`) — Grafana + Prometheus.
- **Tempo** — the shared trace backend. Per-spoke OTel collectors forward traces here.

Spokes (one EKS cluster per attendee) are created from
`../spoke-cluster/cluster.yaml` and registered to this hub's ArgoCD with
`argocd cluster add` (see that README). The hub's `attendee-spokes`
ApplicationSet then pushes the per-attendee stack into every registered spoke.

## Provider abstraction

EKS is the default and lives entirely in `cluster.yaml`. To change provider, swap
this one file for a GKE/AKS equivalent — nothing else in the repo hardcodes EKS.

## Create

```bash
# 1. Create the hub control plane (verify-at-build: re-pin `version` in cluster.yaml first).
eksctl create cluster -f infra/hub-cluster/cluster.yaml

# 2. Confirm reachability.
kubectl get nodes        # expect 2 Ready nodes

# 3. Install the hub stack (ArgoCD + Grafana + Tempo), idempotent.
infra/bootstrap.sh

# 4. Apply the ArgoCD project + ApplicationSet (these select spokes by label).
kubectl apply -f platform/argocd/appproject-workshop.yaml
kubectl apply -f platform/argocd/appset-attendee.yaml
```

After spokes are registered (next), the ApplicationSet's cluster generator picks
them up automatically — no edit here per attendee.

## Sizing

Two `m6i.large` nodes carry ArgoCD + Grafana/Prometheus + Tempo comfortably for the
event. The hub does **not** scale with N attendees — only the spoke fleet does. See
`../SIZING.md` for the per-spoke footprint and the N-driven quota math.

## Teardown

```bash
eksctl delete cluster -f infra/hub-cluster/cluster.yaml
```

Tear down spokes first (they reference the hub); see `teardown/`.
