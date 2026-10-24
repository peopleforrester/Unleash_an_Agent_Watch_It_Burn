# Security

Kubernetes security resources organized by concern. All deployed via ArgoCD.

## Directory Structure

```
network-policies/
  → see ../policies/network-policies/

eso/
  cluster-secret-store.yaml   # ClusterSecretStore pointing to AWS Secrets Manager
  test-external-secret.yaml   # ExternalSecret syncing a test secret

falco/
  custom-rules.yaml      # 3 general rules (write to /etc, shell spawn, sensitive mount)
  eks-aware-rules.yaml   # 2 EKS-specific rules (IMDS access, NodePort creation)

cert-manager/
```

## Security Posture Summary

| Concern | Implementation | Guardrail |
|---------|---------------|-----------|
| Admission control | Kyverno (6 policies in `policies/kyverno/`) | #3, #4, #8 |
| Runtime detection | Falco eBPF + 5 custom rules | #3, #5 |
| Secret management | ESO + AWS Secrets Manager (no static creds) | #7 |
| Access control | The agent's scoped Role (`gitops/ai-layer/resources.yaml`) | #2 |
| Network isolation | NetworkPolicies (default-deny + allow rules) | #2 |
| TLS | cert-manager + Let's Encrypt (HTTP-01) | #7 |
| Auth | GitHub OIDC via ArgoCD Dex (no static passwords) | #7 |

See [docs/SECURITY.md](../docs/SECURITY.md) for the full security architecture.

See [docs/EIGHT-GUARDRAILS.md](../docs/EIGHT-GUARDRAILS.md) for guardrail framework details.
