<!-- ABOUTME: Facilitator runbook for Beat 1 (the platform "wall": admission, RBAC, GitOps, egress).
     ABOUTME: Egress (C1 S3 exfil) verified live on a whitney cluster 2026-06-26; attendee copy is beat.md. -->

# Facilitator runbook, Beat 1 (the wall you already built)

Four platform controls catch a careless/compromised agent. Three are always on (no toggle); one
(admission) is flipped live so attendees see before/after.

## The controls

| Control | Catches | State |
|---|---|---|
| Kyverno admission (`require-resource-limits`) | a deploy with no resource limits | Audit by default; **toggle to Enforce live** |
| RBAC (the agent's scoped Role) | the agent binding itself cluster-admin | always on |
| `block-argocd-drift` (Kyverno) | direct edits to GitOps-managed resources | always on (Enforce) |
| NetworkPolicy default-deny egress + allowlist | exfil of data to the public internet / S3 | always on in R2/R3; absent in R1 (burn) |

## The one live toggle (admission Audit -> Enforce)

```bash
export CONTEXT=<kube-context>
CONTEXT="$CONTEXT" challenges/01-cncf-wall/toggle-kyverno-enforce.sh           # Audit -> Enforce
CONTEXT="$CONTEXT" challenges/01-cncf-wall/toggle-kyverno-enforce.sh --audit   # reverse
```

Idempotent. Before Enforce the no-limits deploy is admitted (Audit only logs); after, admission rejects
it with a policy message naming `require-resource-limits`.

## The egress wall (C1, exfil to S3) — verified live

In R2/R3 the agent namespace runs default-deny egress plus an allow-list scoped to the `workshop-agent`
pod: in-VPC `10.0.0.0/16:443` (which reaches Bedrock via its **PrivateLink VPC endpoint**), DNS, the OTel
collector, the Pod-Identity endpoint, and intra-namespace. **Bedrock works; a push to S3 (public IP, no
VPC endpoint) is denied.** No toggle, it ships with the R2/R3 gitops. R1 (burn) has none of these policies,
so the same exfil succeeds, that is the before/after across rounds.

Verify from the agent pod (CONNECT to Bedrock, DENIED to S3):

```bash
GP=$(kubectl --context "$CONTEXT" -n agent get pod -l app.kubernetes.io/name=workshop-agent -o jsonpath='{.items[0].metadata.name}')
kubectl --context "$CONTEXT" -n agent exec "$GP" -c kagent -- python3 -c '
import socket
def probe(h,p=443,t=6):
    try:
        s=socket.create_connection((h,p),timeout=t); ip=s.getpeername()[0]; s.close(); return "CONNECT "+ip
    except Exception as e: return "DENIED("+type(e).__name__+")"
print("bedrock:", probe("bedrock-runtime.us-west-2.amazonaws.com"))   # CONNECT 10.0.x.x (in-VPC)
print("s3     :", probe("s3.us-west-2.amazonaws.com"))                # DENIED(TimeoutError)
'
```

Confirmed 2026-06-26 on `watch-it-burn-whitney-r3`: bedrock `CONNECT 10.0.16.75`, S3 `DENIED(TimeoutError)`.

## Gotchas

- The egress allow-list is scoped to `app.kubernetes.io/name: workshop-agent`. A stale-eBPF window can let
  an already-running pod through after a policy change; a fresh pod always enforces. If a re-test is
  ambiguous, delete the agent pod and retry.
- `block-argocd-drift` rejects `kubectl edit`/`patch`/`rollout restart` of ArgoCD-managed resources by a
  non-ArgoCD principal. To restart a managed workload during troubleshooting, delete its **pod** (the
  controller recreates it) rather than patching the Deployment.
