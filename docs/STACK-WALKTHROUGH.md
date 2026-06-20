<!-- ABOUTME: Beginning-to-end mental model of the Watch It Burn stack: every technology, its role, where -->
<!-- ABOUTME: it is wired in this repo, and what mechanism invokes what. For Michael, Whitney, and evaluators. -->

# Stack walkthrough: foundations out to the AI guardrails

This is the mental-model map of the actual stack, foundation up, simple to complex. It is grounded in
what this repo really deploys as of June 2026 (files cited inline), not a generic glossary. Where a
fact is confirmed against docs but not yet on a live cluster it is tagged **[verify-at-build]**.

## The picture (layers, bottom up)

1. **Cloud + cluster.** AWS EKS, one cluster per attendee, created with `eksctl`. CNI is **VPC-CNI**
   (its NetworkPolicy feature enforces the default-deny). `infra/*/cluster.yaml`.
2. **Kubernetes + GitOps.** **Argo CD** (app-of-apps + sync-waves) reconciles everything declaratively.
   `gitops/bootstrap/app-of-apps.yaml` (full) and `app-of-apps-burn.yaml` (Cluster 1, bare).
3. **CNCF security floor (the "80%").** Kyverno (admission), Falco (runtime), NetworkPolicy
   (default-deny), External Secrets Operator, cert-manager, scoped RBAC, cosign image signing.
4. **Agent runtime.** **kagent** (a CRD-defined agent) running **Claude on AWS Bedrock** via a native
   `ModelConfig`. `gitops/ai-layer/resources.yaml`.
5. **AI guardrails (the "20%").** The **guard-proxy** (input block-list + classifier, output redaction,
   cost meter, rate-limit/cost-cap), **LLM Guard** (the scanner engine), **agentgateway** (fronts A2A +
   MCP, MCP authorization), and kagent's **toolNames** allowlist + **requireApproval** HITL.
6. **Observability.** OTel Collector to **Datadog (primary)** and to **Tempo / Prometheus / Loki +
   Grafana (analog fallback)**. `gitops/apps/otel-collector.yaml`.
7. **Attendee surface.** Browser chat UI (`gitops/ai-layer/web/`) + a web terminal. No local install.

## Layer by layer: role, where it is wired, the mechanism

| Layer | Technology | Role | Where (file) | Mechanism |
|---|---|---|---|---|
| Cluster | EKS + VPC-CNI | isolation, networking | `infra/*/cluster.yaml` | per-attendee cluster; CNI enforces NetworkPolicy |
| GitOps | Argo CD v3.4.3 | declarative reconcile + drift control | `gitops/` | app-of-apps; self-heal reverts out-of-band change |
| Admission | Kyverno v1.18.1 | block non-compliant workloads | `policies/kyverno/` | ClusterPolicy, rule-level `validate.failureAction` Audit to Enforce |
| Supply chain | Kyverno verifyImages (cosign) | require signed images | `policies/kyverno/verify-image-signatures.yaml` | `verifyImages` keyless attestor (Audit) [verify-at-build] |
| Runtime | Falco 0.44.1 | detect shell/exec, sentinel reads, exfil | `gitops/apps/falco.yaml` | eBPF syscall rules, agent-pod scoped |
| Network | NetworkPolicy | default-deny pod traffic | `policies/network-policies/` | enforced by VPC-CNI |
| Mesh | Istio 1.30.1 (ambient) | encrypted pod-to-pod (mTLS) + workload identity | `gitops/apps/istio.yaml`, `security/istio/` | PeerAuthentication STRICT; the mTLS certs ARE SPIFFE SVIDs |
| Secrets | External Secrets Operator | pull secrets from a store | `security/eso/` | ExternalSecret CRs |
| Identity | scoped RBAC + IRSA | least privilege; Bedrock creds | `gitops/ai-layer/resources.yaml` | tight ServiceAccount; IRSA for Bedrock |
| Agent | kagent 0.9.7 (v1alpha2) | the agent runtime | `gitops/ai-layer/resources.yaml` | `Agent` CRD, `declarative.modelConfig` + `tools[]` |
| Model | Bedrock Claude (Haiku 4.5 default) | the LLM | same | native `ModelConfig` provider: Bedrock |
| AI gateway | agentgateway v1.3.0 GA | front A2A + MCP, MCP authz | `agent/gateway/` | `mcpAuthorization` CEL over `mcp.tool.name` [verify-at-build] |
| Guard glue | guard-proxy (stdlib) | input/output guards, cost meter, caps | `gitops/ai-layer/proxy.py` | A2A reverse proxy; runtime `/toggle` |
| Scanner | LLM Guard 0.3.16 | the actual scanning engine | `agent/gateway/` | `/analyze/prompt` (PromptInjection), `/analyze/output` (Regex) |
| Observability | OTel + Datadog + Grafana | the narration surface | `gitops/apps/otel-collector.yaml` | OTLP in; Datadog primary, Tempo/Prom fallback |

## The request path, end to end (a prompt's journey)

1. Attendee types in the **chat UI** (`web/`), which POSTs an A2A `message/send` to the **guard-proxy**.
2. **guard-proxy input guard, stage 1:** the deterministic **block-list** rejects destructive intent
   here, before any model call, so **zero Bedrock tokens** are spent (the cost counter flatlines).
3. **guard-proxy input guard, stage 2:** the **LLM Guard PromptInjection** classifier (DeBERTa) runs
   if enabled, still pre-LLM. Model-based, not deterministic.
4. **guard-proxy caps:** rate-limit + cost-cap reject before spend if the room is hammering the agent.
5. Allowed requests forward to the **kagent agent**, which calls **Bedrock**. Tokens are spent; kagent
   reports usage back, and the proxy **meters cost** from it (the live counter).
6. The agent may call **tools / MCP servers**. **agentgateway mcpAuthorization** (primary, live-toggle)
   and kagent **toolNames** allowlist (committed backstop) decide which tools are reachable; mutating
   tools carry **requireApproval** (HITL).
7. The response returns through the **guard-proxy output guard**: LLM Guard **Regex** redacts/blocks the
   planted `FAKE-` sentinels before the reply reaches the browser.
8. Every step emits OTel spans/metrics to the collector, which exports to **Datadog (primary)** and
   Tempo/Prometheus (fallback). The cost counter is scraped by Prometheus and graphed in Grafana.

The CNCF floor (Kyverno admission, RBAC, Argo CD drift, Falco) sits underneath all of this and is what
blocks the agent from harming the platform itself, regardless of the AI guardrails.

## How the agent itself is built

The agent is not custom code; it is a **kagent `Agent` custom resource** (v1alpha2), reconciled by the
kagent controller into a running Deployment. The whole agent is declarative, in
`gitops/ai-layer/resources.yaml`:

- **`spec.declarative.modelConfig`** points at a `ModelConfig` (provider Bedrock, Claude). Swapping the
  reference swaps the model tier (Haiku default; Sonnet/Opus for the side-by-side comparison).
- **`spec.declarative.systemMessage`** is the agent's brief. For the burn it is a chaos prompt ("probe
  and try to break the guardrails"). The cost-saver variant additionally tells the agent which
  guardrails exist so it does not waste tokens on already-blocked actions.
- **`spec.declarative.tools[]`** lists MCP servers with a `toolNames` allowlist (the MCP restriction)
  and `requireApproval` (the HITL gate). Omitting the allowlist exposes every tool, the Beat 3 footgun.
- **`spec.declarative.deployment.serviceAccountName`** binds the agent pod to a tight ServiceAccount;
  Bedrock credentials come from IRSA on that SA, never from the repo.

So "building the agent" here means writing that one CR and letting kagent run it. There is no app to
compile; the controls live around it (guard-proxy, gateway, RBAC, the CNCF floor), which is the point.

## Naming clarifications (Whitney's exact questions)

- **"kgateway?"** No. It is **agentgateway** (the OSS Linux Foundation / Agentic AI Foundation project,
  v1.3.0 GA 2026-06-18). kgateway is a different, Envoy-based project; we do not use it.
- **"An Agent Gateway?"** Yes, **agentgateway** fronts the agent's A2A endpoint and its MCP traffic.
  But the input/output **content guards** are the **guard-proxy + LLM Guard**, not the gateway. The
  gateway's job is MCP tool authorization (and optionally a request-phase prompt-guard webhook).
- **"kmcp (part of kagent)?"** kagent provides the MCP wiring (`RemoteMCPServer` / `MCPServer` CRs and
  `tools[].mcpServer.toolNames`). Our MCP restriction is **kagent toolNames + agentgateway authz**.
- **"Can we configure these at the platform level?"** Yes, and that is the thesis: the guardrails live
  at the cluster abstraction layer, so they apply to every workload, not per-app.
- **SPIFFE/SPIRE?** We get workload identity from **Istio**: its mTLS certificates ARE SPIFFE
  identities (`spiffe://cluster.local/ns/<ns>/sa/<sa>`), so adding Istio (ambient, STRICT mTLS)
  delivers the SPIFFE identity layer. A standalone SPIRE deployment stays narrated (it is the same
  identity model, more than we need live for a 2-hour workshop).
- **"What is the trace re-leak trap?"** Output sanitization scrubs the sentinel from the reply, but if
  OTel content-capture is on, the sentinel lands in the trace span. Observability becomes a second,
  unguarded exfil sink; the fix is symmetric collector-side redaction.

## Honest unknowns ([verify-at-build], the live-confirmation list)

- agentgateway `mcpAuthorization` enforcement on the OSS image with kagent in front (re-pin v1.3.0).
- kagent A2A token-usage field names that the cost meter parses; `requireApproval` runtime behavior.
- LLM Guard verdict envelope on the live image; VPC-CNI NetworkPolicy actually enforcing.
- The Datadog exporter against Whitney's account (API key + site); Kyverno `verifyImages` 1.18 schema.
