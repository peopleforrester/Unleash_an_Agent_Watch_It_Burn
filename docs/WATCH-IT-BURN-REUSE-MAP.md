# Watch It Burn, KubeAuto IDP Reuse Map

How the proven **kubeauto-ai-day** IDP (EKS, 27/27 components, 59 live tests, 2026-03) becomes the
Watch It Burn platform. Source: `~/repos/_archive/events/kubeauto-ai-day/`
(public: `github.com/peopleforrester/kubeauto-ai-day`). Watch It Burn is **also EKS**, so unlike the
GKE BurritoBot port this is **mostly COPY**, not ADAPT.

Legend: **COPY** as-is · **ADAPT** copy + change · **EXTEND** base + AI layer · **IGNORE** omit · **NEW** Watch-It-Burn only.

## Foundation (reused from KubeAuto), the 27-component IDP

| Area | Decision | Notes |
|---|---|---|
| `gitops/bootstrap/app-of-apps.yaml` | ADAPT | repoURL → WITB repo (done); trim child apps. |
| `gitops/apps/{kyverno,falco,falcosidekick,external-secrets,cert-manager,prometheus,loki,tempo,otel-collector,backstage}.yaml` | ADAPT | **All re-pinned to current GA 2026-06-18** (see VERSIONS.lock). |
| `gitops/apps/promtail.yaml` | **REPLACED** | Promtail EOL → `gitops/apps/alloy.yaml` (Grafana Alloy 1.10.0). |
| `gitops/apps/{namespaces,network-policies,rbac,resource-quotas,grafana-dashboards,kyverno-policies}.yaml` | COPY/ADAPT | In-repo paths; namespaces extended with AI namespaces. |
| `policies-idp/kyverno/*` (6 policies) | COPY | require-labels, restrict-image-registries, require-resource-limits, disallow-privileged, require-probes, require-networkpolicy. |
| `security/{rbac,falco,cert-manager,eso,quotas-pdbs}/*` | COPY | EKS-verified; ESO manifests use `external-secrets.io/v1` (GA). |
| `observability-idp/grafana/dashboards/*` | EXTEND | + GenAI trace-waterfall dashboard (input/output/tool calls). |
| `backstage/*` | COPY | Service catalog + templates (nice-to-have per Michael). |
| `gitops/manifests/{unicorn,hedgehog,spider,wombat,mantis-shrimp}-party` | **COPY (repurposed)** | The agent's **burn targets** ("delete the unicorn deployment"). |
| `gitops/manifests/ecom-*`, `sample-app`, `load-generator` | IGNORE | Prior-demo workloads; dropped. |
| Terraform / EKS infra | IGNORE | WITB uses its own `infra/` eksctl configs. |

## AI layer (NEW, Watch It Burn only; not in KubeAuto)

These already exist + are **live-verified**; they get wired into the app-of-apps as ArgoCD apps:

| Component | Source in repo | Role |
|---|---|---|
| kagent + Bedrock ModelConfig + scoped Agent | `agent/kagent-*.yaml`, `agent/rbac/` | the chaos agent (Claude on Bedrock) |
| guard-proxy (LLM Guard input/output + block-list + cost counter) | `agent/gateway/guard-proxy/` | AI guardrail inspection point (OSS, no AWS-native) |
| LLM Guard API server | `agent/gateway/llm-guard-service.yaml` | guard engine (OSS) |
| evil-MCP shim + RemoteMCPServer + `toolNames` | `beats/03-bad-mcp-excessive-agency/` | MCP tool-restriction beat |
| WITB policies: `minimal-floor`, `block-argocd-drift` | `platform/kyverno/policies/` | gradual-burn floor + GitOps-drift control |
| cost counter | `cost/`, guard-proxy `/cost` | wasted-token-DoS story |

## Three-cluster mapping (rev4)
- **Cluster 1 (burn):** foundation minus admission enforcement + `minimal-floor` only + the *-party burn targets + agent.
- **Cluster 2 (CNCF):** full foundation (Kyverno enforcing, RBAC, ArgoCD drift) + agent; no AI guardrails.
- **Cluster 3 (attendee):** full foundation + the entire AI layer; attendee toggles output → input → MCP guards.

## Version discipline
KubeAuto's pins were Feb/Mar 2026. **All re-pinned to current GA on 2026-06-18** (VERSIONS.lock).
Breaking bumps flagged: ESO v1→v2 (verify v1 CRDs still served), Loki v6→v7 (values review). Promtail
replaced by Alloy. Nothing ships on a stale or EOL version.
