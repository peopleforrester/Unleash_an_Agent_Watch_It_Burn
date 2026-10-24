# Policies

Kyverno admission policies and Kubernetes NetworkPolicies. Deployed via ArgoCD.

The Kyverno policies are CEL `ValidatingPolicy` resources (`policies.kyverno.io/v1`), plus one
`ImageValidatingPolicy` for signatures; the deprecated `ClusterPolicy` type is no longer used (#206).
List them with `kubectl get validatingpolicy,imagevalidatingpolicy`. Their behaviour is checked against
the Kyverno v1.19.0 CLI by `verify/test_kyverno_cel_policies.py`.

## Kyverno Policies

All policies enforce in the `apps` namespace only. System namespaces
(`kube-system`, `argocd`, `monitoring`, `backstage`, `kyverno`, `falco`,
`external-secrets`, `cert-manager`) are excluded to avoid blocking
platform components.

| Policy | What It Enforces | Mode | Guardrail |
|--------|-----------------|------|-----------|
| `disallow-privileged.yaml` | No privileged containers or privilege escalation | Enforce | #3 |
| `require-labels.yaml` | `app.kubernetes.io/name` and `app.kubernetes.io/version` required | Enforce | #4 |
| `require-probes.yaml` | Liveness and readiness probes required | Enforce | #4 |
| `require-resource-limits.yaml` | CPU and memory limits required | Enforce | #2 |
| `require-networkpolicy.yaml` | At least one NetworkPolicy per namespace | Audit | #4 |
| `restrict-image-registries.yaml` | Images from ECR, GHCR, registry.k8s.io, Docker Hub only | Enforce | #8 |

See [ADR-003](../docs/adr/ADR-003-policy-engine.md) for Kyverno selection rationale.

## NetworkPolicies

Default-deny with explicit allow rules, scoped to the `apps` namespace.

```
network-policies/
  default-deny.yaml                          # Deny all ingress + egress in apps
  per-namespace/
    apps-allow-dns.yaml                      # Allow DNS resolution (port 53)
    apps-allow-ingress.yaml                  # Allow ingress from ALB
    apps-allow-intra-namespace.yaml          # Allow pod-to-pod within apps
    apps-allow-otel-egress.yaml              # Allow egress to OTel Collector
```

Traffic flow: ALB → apps pods (ingress) → DNS + OTel (egress). All other
egress is denied. Cross-namespace traffic to monitoring is allowed via the
OTel egress policy.
