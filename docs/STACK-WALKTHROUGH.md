<!-- ABOUTME: Beginning-to-end mental model of the Watch It Burn stack: every technology, its role, where -->
<!-- ABOUTME: it is wired in this repo, and what mechanism invokes what. For Michael, Whitney, and evaluators. -->

# Stack walkthrough: foundations out to the AI guardrails

This is the mental-model map of the actual stack, foundation up, simple to complex. It is grounded in
what this repo really deploys as of June 2026 (files cited inline), not a generic glossary. Where a
fact is confirmed against docs but not yet on a live cluster it is tagged **[verify-at-build]**.

## The picture (layers, bottom up)

1. **Cloud + cluster.** AWS EKS, one independent standalone cluster per attendee (take-home), provisioned
   with **Terraform** (`infra/terraform/`). All clusters share **one VPC** (`10.0.0.0/16`, two private `/18`
   subnets across two AZs), provisioned once up front. CNI is **VPC-CNI** (its NetworkPolicy feature enforces
   the default-deny). `infra/terraform/{lab-vpc,cluster,fleet}/`.
2. **Kubernetes + GitOps.** Each cluster runs its **own in-cluster Argo CD** (app-of-apps + sync-waves)
   that reconciles the cluster from Git, destination the local cluster `kubernetes.default.svc`. No hub,
   no central ArgoCD managing other clusters. `gitops/bootstrap/app-of-apps.yaml` (full) and
   `app-of-apps-burn.yaml` (Cluster 1, bare).
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
| Cluster | EKS + VPC-CNI | isolation, networking | `infra/terraform/` | independent per-attendee cluster (Terraform), shared VPC; CNI enforces NetworkPolicy |
| GitOps | Argo CD v3.4.4 | declarative reconcile + drift control | `gitops/` | in-cluster app-of-apps reconciling the local cluster; self-heal reverts out-of-band change |
| Admission | Kyverno v1.19.0 (chart 3.9.0, verified 2026-09-05) | block non-compliant workloads | `policies/kyverno/` | ClusterPolicy, rule-level `validate.failureAction` Audit to Enforce |
| Supply chain | Kyverno verifyImages (cosign) | require signed images | `policies/kyverno/verify-image-signatures.yaml` | `verifyImages` keyless attestor (Audit) [verify-at-build] |
| Runtime | Falco 0.44.1 | detect shell/exec, sentinel reads, exfil | `gitops/apps/falco.yaml` | eBPF syscall rules, agent-pod scoped |
| Network | NetworkPolicy | default-deny pod traffic | `policies/network-policies/` | enforced by VPC-CNI |
| Mesh | Istio 1.30.1 (ambient) | encrypted pod-to-pod (mTLS) + workload identity | `gitops/apps/istio.yaml`, `security/istio/` | PeerAuthentication STRICT; the mTLS certs ARE SPIFFE SVIDs |
| Secrets | External Secrets Operator | pull secrets from a store | `security/eso/` | ExternalSecret CRs; creds via EKS Pod Identity |
| Identity | scoped RBAC + EKS Pod Identity | least privilege; Bedrock creds | `gitops/ai-layer/resources.yaml` | tight ServiceAccount; Pod Identity for Bedrock (IRSA only for EBS CSI) |
| Agent | kagent 0.9.9 (v1alpha2) | the agent runtime | `gitops/ai-layer/resources.yaml` | `Agent` CRD, `declarative.modelConfig` + `tools[]` |
| Model | Bedrock Amazon Nova Pro (default; Claude tiers kept for the optional cost race) | the LLM | same | native `ModelConfig` provider: Bedrock, over a PrivateLink endpoint in the VPC |
| AI gateway | agentgateway v1.3.0 GA | fronts the workshop-mcp tool server (every real tool call passes through it); NOT the C7 control | `gitops/ai-layer/resources.yaml` (RemoteMCPServer url agentgateway.agent:3001) | `mcpAuthorization` is present but unexercised (#239); the tool allow-list that C7 flips is kagent `toolNames` |
| Guard glue | guard-proxy (stdlib) | input/output guards, cost meter, caps | `gitops/ai-layer/proxy.py` | A2A reverse proxy; runtime `/toggle` |
| Scanner | LLM Guard 0.3.16 | the actual scanning engine | `gitops/ai-layer/resources.yaml` | `/analyze/prompt` (PromptInjection), `/analyze/output` (Regex) |
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
6. The agent may call **tools / MCP servers**. The kagent **toolNames** allow-list on the Agent CR is
   the control (it is what Challenge 7 patches; an EMPTY list means every tool, measured 2026-09-05).
   agentgateway fronts the workshop-mcp server on the path but its **mcpAuthorization** is not used as
   a control (#239); evil-mcp is dialled directly on purpose. Mutating tools carry **requireApproval**
   (HITL), never exercised as a beat. kgateway is not installed (#245).
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
  reference swaps the model tier (**Nova Pro** is the workshop default; Haiku/Sonnet/Opus for the
  side-by-side cost comparison). Keep the guard-proxy's `MODEL_TIER` in step with it or the cost counter
  prices the wrong model.
- **`spec.declarative.systemMessage`** is the agent's brief. For the burn it is a chaos prompt ("probe
  and try to break the guardrails"). The cost-saver variant additionally tells the agent which
  guardrails exist so it does not waste tokens on already-blocked actions.
- **`spec.declarative.tools[]`** lists MCP servers with a `toolNames` allowlist (the MCP restriction)
  and `requireApproval` (the HITL gate). Omitting the allowlist exposes every tool, the Beat 3 footgun.
- **`spec.declarative.deployment.serviceAccountName`** binds the agent pod to a tight ServiceAccount;
  Bedrock credentials come from an **EKS Pod Identity** association on that SA, never from the repo.

So "building the agent" here means writing that one CR and letting kagent run it. There is no app to
compile; the controls live around it (guard-proxy, gateway, RBAC, the CNCF floor), which is the point.

## Naming clarifications (Whitney's exact questions)

- **"kgateway?"** No. It is **agentgateway** (the OSS Linux Foundation / Agentic AI Foundation project,
  v1.3.0 GA 2026-06-18). kgateway is a different, Envoy-based project; we do not use it.
- **"An Agent Gateway?"** Yes, **agentgateway** fronts the agent's A2A endpoint and its MCP traffic.
  But the input/output **content guards** are the **guard-proxy + LLM Guard**, not the gateway. The
  gateway's job is MCP tool authorization (and optionally a request-phase prompt-guard webhook).
- **"kmcp (part of kagent)?"** kagent provides the MCP wiring (`RemoteMCPServer` / `MCPServer` CRs and
  `tools[].mcpServer.toolNames`). Our MCP restriction is **kagent toolNames**; agentgateway authz is present but unused (#239).
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

- agentgateway `mcpAuthorization` enforcement on the OSS image with kagent in front: still unexercised
  (v1.3.0 is pinned; C7 uses kagent toolNames instead, #239).
- `requireApproval` runtime behavior: still unexercised as a beat.
- RESOLVED 2026-09-05: kagent token-usage fields (the cost meter caps at USD 0.10 live); LLM Guard
  verdict envelope (redaction and injection blocks measured); VPC-CNI NetworkPolicy enforcing (C1 block
  measured, and it is what broke LLM Guard's lazy model download, #241).
- The Datadog exporter against Whitney's account (API key + site); Kyverno `verifyImages` 1.18 schema.
