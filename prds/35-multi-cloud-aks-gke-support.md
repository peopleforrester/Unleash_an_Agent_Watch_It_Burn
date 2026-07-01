# PRD 35: Multi-cloud support (Azure AKS + GCP GKE)

Status: DRAFT, awaiting approval (Phase 1.3 gate)
Author: Michael Forrester
Created: 2026-06-30
Branch target: staging

## 1. Goal

Make the workshop platform provisionable on Azure AKS and GCP GKE in addition to
the current AWS EKS, so a run can be hosted on whichever cloud the venue or
account situation favors.

A fourth pluggable target, `local` (k3d or kind + Ollama), is included as a
developer and validation substrate, not an attendee-facing cloud. It lets the
cloud-neutral base and the per-cloud overlays be applied and converged offline
with no cloud spend, which turns the code-only validation of this pass into an
actual apply-and-converge check.

## 2. Locked scope decisions

These were decided up front and are not reopened here:

1. **Pluggable, one cloud per run.** A run picks AWS, Azure, or GCP at provision
   time and uses that single cloud end to end. This is three interchangeable
   backends, not simultaneous tri-cloud. No run spans clouds.
2. **Native model backend per cloud.** Amazon Bedrock on AWS, Azure OpenAI on
   Azure (serves GPT, not Claude), Vertex AI on GCP (serves Gemini, and Claude
   on Vertex). No cross-cloud model calls.
3. **Code-only validation this pass.** Write and refactor the AKS and GKE paths;
   validate with `terraform validate` / `plan`, lint, `kustomize build`, and the
   offline render-gate tests. No live Azure or GCP provisioning in this pass.
4. **A `local` dev/validation target, not a fourth attendee cloud.** k3d or kind
   plus an in-cluster Ollama model gives an offline, keyless convergence test of
   the base and overlays. It is a developer substrate for iterating without cloud
   spend, never a platform an attendee run is delivered on. Oracle/OKE as a fourth
   cloud is deferred (see §7).

## 3. Research that shapes the design (verified 2026-06-30)

Three live verification spikes were run before this plan. The findings below
are the load-bearing ones. Each changes the design away from a naive port.

### 3.1 kagent model auth is keyless on Bedrock AND both Vertex providers; only Azure OpenAI forces a per-cluster key

Verified against the kagent source on `main`, not the docs table. The docs
implied every non-Bedrock provider needs an `apiKeySecret`; the CRD schema and the
translator both contradict that. This correction reverses the GCP design from
"hardest cloud" to "cleanest cloud".

**CRD (`go/api/v1alpha2/modelconfig_types.go`).** `APIKeySecret` is
`json:"apiKeySecret,omitempty"` (line 395, optional). The only CEL rule touching
its presence is "apiKeySecretKey must be set if apiKeySecret is set (except for
Bedrock and SAPAICore)" (line 381), which fires *only when the secret is already
present*. **No XValidation makes `apiKeySecret` mandatory for any provider,**
including `GeminiVertexAI` and `AnthropicVertexAI`.

**Translator (`go/core/internal/controller/translator/agent/adk_api_translator.go`).**

- `GeminiVertexAI` (lines 600-634) and `AnthropicVertexAI` (645-672) always inject
  `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI`. The
  SA-JSON mount and `GOOGLE_APPLICATION_CREDENTIALS` are gated on `if
  model.Spec.APIKeySecret != ""`. Omit the secret and the Google GenAI SDK falls
  through to Application Default Credentials → GKE metadata server → **Workload
  Identity. Keyless works.**
- `Bedrock` (line 194): same `&& APIKeySecret != ""` guard → keyless via IRSA /
  Pod Identity, as today.
- `AzureOpenAI`: `if !model.Spec.APIKeyPassthrough { inject AZURE_OPENAI_API_KEY
  from a SecretKeyRef to APIKeySecret }`. **No `APIKeySecret != ""` guard and no
  managed-identity / ADC fallback exists.** Short of per-request A2A passthrough
  (not a fleet default) or a plaintext `AzureADToken` in the CR (expires ~1h, not
  fleet-viable), Azure OpenAI needs a real static API key wired per cluster.

Consequence, corrected:

- **GCP is true secret-zero.** No per-cluster model Secret. The agent
  ServiceAccount stays un-annotated; the Vertex grant is project-level IAM (a
  single `principalSet://.../PROJECT_ID.svc.id.goog/...` binding covering every
  cluster), not a per-cluster manifest. **The byte-identical GitOps property is
  preserved on GCP.**
- **AWS is true secret-zero**, unchanged (IRSA / Pod Identity).
- **Azure is the only cloud that breaks byte-identical.** Each AKS cluster needs a
  Secret holding the Azure OpenAI key. Clean path: External Secrets Operator
  projects one central Azure OpenAI key from Key Vault into each cluster, with ESO
  itself authenticating keyless via Entra Workload Identity. The secret-zero
  problem moves to ESO, and only on Azure. See 3.5 for the ESO scaling cost.

### 3.2 Azure: the agent-to-model path is API-key + private endpoint, so the agent pod needs zero public egress

Earlier framing said Azure needs a public egress hole to
`login.microsoftonline.com:443` because Entra Workload Identity exchanges the
projected SA token there and it has no Private Link. That is true *for anything
that authenticates with workload identity*, but it does not apply to the
agent-to-model call, because per 3.1 kagent's Azure OpenAI path does not use
workload identity at all. It uses a static `AZURE_OPENAI_API_KEY`.

So the agent's egress on Azure is: the private Azure OpenAI endpoint NIC (a CIDR
inside the AKS subnet, reached via the `privatelink.openai.azure.com` DNS zone
with CoreDNS forwarding to Azure DNS `168.63.129.16`) plus DNS. **No public
`login.microsoftonline.com` hole for the model call.** This is the *cleanest* of
the three exfil demos: zero public egress on the agent pod, everything private.

The public AAD hole survives in exactly one place: **ESO** authenticates to Key
Vault with Entra Workload Identity, so ESO's pod (not the agent's) needs
`login.microsoftonline.com:443`. That egress is scoped to the ESO namespace, away
from the agent, and does not widen the agent's exfil surface. The teachable
contrast holds, just relocated: AWS creds come from link-local `169.254.170.23`;
Azure's one identity round-trip is confined to the ESO pod; the agent itself talks
only to a private endpoint.

### 3.3 GCP cannot separate Vertex from GCS at the pod NetworkPolicy layer

DNS routes `*.googleapis.com` to the `restricted.googleapis.com` VIP
(`199.36.153.4/30`). Both `aiplatform.googleapis.com` (Vertex, allow) and
`storage.googleapis.com` (GCS, the exfil target we want to deny) resolve to the
**same /30**. A pod-level NetworkPolicy operates at L3/L4 and cannot see SNI, so
it can only do "allow `199.36.153.4/30` tcp/443, deny `0.0.0.0/0`", which permits
both Vertex and GCS. The enforceable Vertex-yes / GCS-no control is **VPC Service
Controls with a "VPC accessible services" allowlist** (allow
`aiplatform.googleapis.com`, omit `storage.googleapis.com`), which is an
org/perimeter-level control, not a pod-level one. VPC-SC does not apply to the
metadata server, so workload identity keeps working.

**Do NOT present GKE `FQDNNetworkPolicy` as the block.** It is tempting because it
reads like "NetworkPolicy but by hostname," which would appear to separate Vertex
from GCS. It does not solve this: it is an ALPHA Cilium/GKE-Dataplane-V2 feature,
it enforces on DNS-resolved IPs (both hostnames still resolve to the same
`199.36.153.4/30`, so it cannot actually distinguish them once resolved), and
staking the workshop's headline lesson on an alpha feature that does not truly
enforce the boundary would be a fake lesson. The honest block is VPC-SC (or a
per-cluster SNI proxy, see §6 risk 1). If FQDNNetworkPolicy appears in the walkthrough at
all, it is as a "why this does not work" beat, never as the control.

Consequence: the "watch it burn" exfil lesson does not port cleanly. AWS expresses
it with a NetworkPolicy. Azure expresses it with a NetworkPolicy plus a required
public auth hole. GCP cannot express the GCS-block at the NetworkPolicy layer at
all and needs a VPC-SC perimeter. The GCP exfil lesson must be redesigned around
VPC-SC, and that setup time (org-level) must be budgeted. This is the single
biggest design divergence in the refactor.

### 3.4 Verified per-cloud facts (condensed)

| Seam | AWS (today) | Azure AKS | GCP GKE |
|---|---|---|---|
| Cluster TF | community EKS module | `azurerm_kubernetes_cluster`, `oidc_issuer_enabled=true` + `workload_identity_enabled=true` (both default false) | `terraform-google-modules/kubernetes-engine` 44.2.0, raw `workload_identity_config { workload_pool }` + node pool `workload_metadata_config { mode = GKE_METADATA }` |
| Provider pin | AWS provider | azurerm `~> 4.0` (4.79.0) | hashicorp/google `7.x` (7.38.0) |
| Workload identity | Pod Identity (keyless, un-annotated SA) | UAMI + federated credential; SA annotation `azure.workload.identity/client-id`; pod label `azure.workload.identity/use: "true"` | direct KSA principal IAM binding (no annotation) or GSA-impersonation fallback (annotation `iam.gke.io/gcp-service-account`) |
| Model auth | keyless (IRSA/Pod Identity) | **Static API key required** (kagent has no MI path); ESO projects one central key from Key Vault per cluster | **keyless / ADC** (Vertex via Workload Identity, project-level IAM binding); no per-cluster model Secret |
| Metadata addr | `169.254.169.254` (IMDS), creds `169.254.170.23/32` | agent: none (static API key); ESO only: token via `login.microsoftonline.com` | `169.254.169.254`; DPv2 egress tcp 80+8080 |
| Private model endpoint | Bedrock PrivateLink in-VPC `10.0.0.0/16:443` | Azure OpenAI Private Endpoint NIC in AKS subnet CIDR + DNS zone `privatelink.openai.azure.com` | `restricted.googleapis.com` `199.36.153.4/30` (shared VIP, see 3.3) |
| ESO backend | (current) | `provider.azurekv` authType WorkloadIdentity | `provider.gcpsm` auth.workloadIdentity |
| Ingress class | (current) | app-routing managed NGINX `webapprouting.kubernetes.azure.com` | annotation `kubernetes.io/ingress.class: gce` / `gce-internal` (ignores `spec.ingressClassName`) |
| Internal L4 | (current) | `service.beta.kubernetes.io/azure-load-balancer-internal: "true"` | `networking.gke.io/load-balancer-type: "Internal"` |
| Default StorageClass | (current) | `default` / `managed-csi` (`disk.csi.azure.com`), premium `managed-csi-premium` | `standard-rwo` (`pd.csi.storage.gke.io`), premium `premium-rwo` |
| Model tiers | Claude on Bedrock | GPT only: gpt-5-nano / gpt-5-mini / gpt-5.1 (4o + 4o-mini retired 2026-03-31) | Gemini 2.5 flash-lite / flash / pro (2.5 retires 2026-10-16; 3.x newer); Claude on Vertex via `anthropic_version: vertex-2023-10-16` |

### 3.5 ESO secret-zero scaling cost is Azure-only, and it is bounded by the FIC cap

Per 3.1, ESO carries the only per-cluster secret on the whole fleet, and only on
Azure. Its own auth is keyless (Entra Workload Identity), so no static credential
is stored anywhere. The cost is not a stored secret; it is the number of Azure
identity objects the fleet needs.

Azure caps **federated identity credentials (FICs) at 20 per user-assigned
managed identity (UAMI)**. One FIC binds one `(issuer, subject)` pair, and each
AKS cluster has its own OIDC issuer URL, so each cluster's ESO service account
needs its own FIC. At 250 clusters that is 250 FICs, which does not fit on one
UAMI. The fleet needs `⌈250 / 20⌉ = 13` UAMIs, each carrying up to 20 clusters'
FICs, all 13 granted the same Key Vault `get`/`list` secret permission on the one
central Azure OpenAI key.

Practical constraints for the Terraform:

- **FIC creation is serial per UAMI.** Azure rejects concurrent FIC writes against
  the same parent identity with a `409`. Terraform must not fan out FIC creation
  within a UAMI; serialize with explicit `depends_on` chaining inside each UAMI's
  FIC set. Across the 13 UAMIs the work still parallelizes.
- **azurerm `>= 3.40`** for the stable `azurerm_federated_identity_credential`
  resource.
- This is the single largest Azure-specific provisioning cost in the refactor, and
  it is entirely absent on AWS and GCP (both secret-zero, no per-cluster identity
  object). Budget it in the Azure milestone, not as a general fleet cost.

### 3.6 Local target: keyless Ollama model, but NetworkPolicy needs a real CNI

The `local` target runs the platform on k3d or kind on a developer machine. It
exists to converge the base + overlays offline, so two facts govern it.

**Model path is keyless and offline via kagent's first-class Ollama provider.**
Verified against the kagent source on `main` (commit `20b19c72`, release tag
`v0.10.0-beta2`), 2026-07-01, the same way 3.1 was verified before being relied on.

- **Provider enum.** `Ollama` is a first-class value of the `ModelProvider` enum
  (`go/api/v1alpha2/modelconfig_types.go`, kubebuilder enum:
  `Anthropic;OpenAI;AzureOpenAI;Ollama;Gemini;GeminiVertexAI;AnthropicVertexAI;Bedrock;SAPAICore`).
- **Config struct** (`OllamaConfig`, same file): two optional fields only,
  `host` (`json:"host,omitempty"`) and `options` (`json:"options,omitempty"`, a
  `map[string]string`). Wired into the spec as `ollama *OllamaConfig`. The model
  NAME is NOT in this struct; it is the shared top-level required `spec.model`
  field.
- **No secret.** `apiKeySecret` / `apiKeySecretKey` are both optional and the
  Ollama translator path
  (`go/core/internal/controller/translator/agent/adk_api_translator.go`) never
  reads them. It injects exactly one env var, `OLLAMA_API_BASE` = the host
  (auto-prefixed `http://` if no scheme), and creates no SecretKeyRef, volume, or
  credential of any kind. Keyless and offline-capable is confirmed at the source,
  and it does NOT need the OpenAI-compatible-endpoint workaround.

Minimal valid keyless local ModelConfig (used by the `local` overlay, 4.3):

```yaml
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: ollama-local
  namespace: kagent
spec:
  provider: Ollama
  model: llama3.2                        # top-level spec.model = the Ollama model tag
  ollama:
    host: http://ollama.ollama.svc:11434 # already schemed; translator leaves as-is
  # no apiKeySecret / apiKeySecretKey needed
```

**NetworkPolicy enforcement requires Calico or Cilium.** The exfil lesson IS
NetworkPolicy, and the default CNIs do not enforce it: kind's kindnet and
k3s/k3d's default flannel both ignore NetworkPolicy objects. The local target must
install Calico or Cilium so `default-deny` plus the egress allowlist actually
bite. Without it the headline "watch it burn" lesson silently no-ops, which is
worse than not running it. This is a hard requirement on the local bootstrap, not
a nicety.

**Falco and Datadog are the two components that degrade locally.** Falco wants
eBPF and kernel access (works on a Linux host with privileged mounts, the touchy
piece of the local stack); Datadog needs a key and public egress. Everything else
(ArgoCD, kagent + Ollama, Kyverno, NetworkPolicy, ESO, the app, the ttyd shells)
runs offline. The local target is for iterating the GitOps and guardrail surface,
not for reproducing the cloud IAM, private endpoints, or the cloud exfil target,
which have no local equivalent.

## 4. Architecture

The refactor introduces a cloud-provider seam at four layers. The design keeps a
single cloud-neutral GitOps base and pushes per-cloud differences into overlays
and provider shims.

### 4.1 Terraform: provider-partitioned roots

Today: `infra/terraform/lab-vpc` and the EKS root live at fixed paths.

Target layout:

**Decided (Michael, 2026-07-01): symmetric layout.** All three clouds get
parallel roots; the current `lab-vpc` and EKS roots move under `aws/`.

```
infra/terraform/
  aws/    network/   cluster/    # moved from current lab-vpc + cluster roots
  azure/  network/   cluster/
  gcp/    network/   cluster/
```

The `local` target is not Terraform. It lives at `infra/local/` (k3d or kind
cluster config, the Calico or Cilium install, and a bootstrap script), dispatched
through the same `fleet.sh` provider seam (4.2).

The move breaks every hardcoded reference to the old paths. All of these are
updated in the same milestone (M1) that performs the move, so the AWS path is
never left dangling:

1. **External teardown scripts** in `/tmp/witb-teardown/` (`sgwipe.sh`,
   `clean-sgs-and-destroy.sh`, `sweep-account.sh`) hardcode
   `TFDIR=".../infra/terraform/lab-vpc"`. These live outside the repo; M1 updates
   them in place (with a timestamped backup first, per the no-destructive rule)
   and additionally copies canonical versions into the repo under
   `infra/terraform/aws/teardown/` so the path coupling is version-controlled
   going forward.
2. **`verify/test_forkbomb_defense.py:9`** reads
   `infra/terraform/cluster/main.tf` → repoint to `infra/terraform/aws/cluster/main.tf`.
3. **`fleet.sh`** and `deploy-full-idp.sh` internal path assumptions → routed
   through the provider shim (4.2), which owns the per-cloud root path.
4. **Docs** (~10 files: `MASTER-RECREATION-SPEC.md`, `FULL-RUN-PLAN-2026-06-29.md`,
   `CONFIGURATION-AND-RECREATION-2026-06.md`, `STACK-WALKTHROUGH.md`,
   `BUILD-SPEC.md`, `DECISION-LOG.md`, `TAGGING.md`, `READINESS-CHECKLIST.md`,
   `GO-LIVE-CHECKLIST.md`, `PROJECT_STATE.md`) reference the old paths. Accuracy
   only, not load-bearing; swept in M1's doc pass.

M1's gate includes a `grep -rn "terraform/lab-vpc\|terraform/cluster"` sweep
returning zero stale references outside historical log entries.

### 4.2 fleet.sh: provider dispatch

`fleet.sh` gains a `PROVIDER` variable (aws|azure|gcp|local) and dispatches to
`providers/{aws,azure,gcp,local}.sh` shims implementing a common contract:
`provision_network`, `provision_cluster`, `write_kubeconfig` (always isolated
file, never `~/.kube/config`), `cluster_context_name`, `teardown`. The same
contract covers `deploy-full-idp.sh` and the harvest/cost scripts. The `local`
shim implements the same contract against k3d or kind (Calico/Cilium install
included) instead of Terraform: `provision_network` is a no-op and
`provision_cluster` stands up the local cluster.

### 4.3 GitOps: cloud-neutral base + per-provider overlays

Keep `gitops/` base cloud-neutral. Add Kustomize overlays
`overlays/{aws,azure,gcp,local}` patching the five declarative seams:

1. ingress class / LB annotations
2. ESO SecretStore backend
3. StorageClass name
4. `ModelConfig` provider block (and, **on Azure only**, the model-credential
   Secret reference plus the ESO ExternalSecret that fills it from Key Vault; AWS
   and GCP are keyless per 3.1 and add no Secret here)
5. egress NetworkPolicy CIDRs

The `local` overlay carries a keyless Ollama `ModelConfig` pointing at the
in-cluster Ollama Service, ingress as NodePort, StorageClass `local-path`, and no
ESO backend (nothing to project). It exists to prove the base + overlay seams
converge offline, not to reproduce a cloud's IAM or private endpoints.

### 4.4 Exfil egress policies: re-derived per cloud

`policies/network-policies/per-namespace/*-egress-allowlist.yaml` is the deepest
AWS coupling. Per cloud:

- **AWS** (unchanged): allow Bedrock PrivateLink CIDR + creds link-local + IMDS +
  DNS; deny internet and S3.
- **Azure:** the **agent** namespace allows only the private Azure OpenAI endpoint
  CIDR + DNS, deny the rest. No public `login.microsoftonline.com` hole (the agent
  uses a static API key, per 3.1/3.2), which makes this the cleanest exfil demo.
  The public `login.microsoftonline.com:443` allowance lives in the **ESO**
  namespace policy only, because ESO authenticates to Key Vault with Workload
  Identity.
- **GCP:** allow `199.36.153.4/30` tcp/443 + metadata `169.254.169.254` (DPv2 tcp
  80+8080) + kube-dns; deny internet. **The GCS-block is NOT here.** It is a
  VPC-SC perimeter with an accessible-services allowlist provisioned in
  `infra/terraform/gcp/network`. The GCP exfil lesson is redesigned around it.
- **local:** allow the in-cluster Ollama Service + kube-dns, deny internet. There
  is no cloud model endpoint or cloud exfil target to express, so the local policy
  exercises the default-deny-plus-allowlist shape only. This is why the CNI must be
  Calico or Cilium (3.6): under kindnet or flannel this policy is silently ignored.

### 4.5 Tooling and docs

- VTT/provisioning image gains `az` and `gcloud` alongside `aws`.
- `ATTRIBUTION.md`: add Azure OpenAI, Vertex AI, AKS, GKE, the Azure/Google
  Terraform providers and the GKE module; keep Bedrock and EKS.

## 5. Milestones

Each milestone is independently mergeable to staging and ends green on the
offline gates (`terraform validate`/`plan`, `kustomize build`, `verify/*` render
tests, lint).

- **M1 Provider seam scaffolding + AWS root relocation.** Move current
  `lab-vpc` + `cluster` roots under `infra/terraform/aws/{network,cluster}`;
  update the teardown scripts (backup first), `verify/test_forkbomb_defense.py`,
  and the doc references per 4.1. `fleet.sh` PROVIDER dispatch + empty
  `providers/{azure,gcp}.sh` shims with the AWS shim extracted from current code.
  No behavior change for AWS beyond the path move. Gate: `terraform validate`
  clean at the new AWS paths; offline verify suite green; `grep` sweep for stale
  `terraform/lab-vpc`/`terraform/cluster` refs returns zero outside log history;
  shims `terraform fmt` clean.
- **M2 Azure Terraform.** `infra/terraform/azure/{network,cluster}` with AKS,
  OIDC + workload identity enabled, Azure OpenAI private endpoint + DNS zone, UAMI
  + federated credential. Gate: `terraform validate` + `plan` against a real
  subscription read (plan only, no apply).
- **M3 GCP Terraform.** `infra/terraform/gcp/{network,cluster}` with GKE,
  workload pool, GKE_METADATA node pool, restricted.googleapis.com routing, **and
  the VPC-SC perimeter + accessible-services allowlist** (3.3). Gate: `terraform
  validate` + `plan`.
- **M4 GitOps overlays.** `overlays/{azure,gcp}` patching the five seams,
  including the **Azure-only** ESO ExternalSecret + ModelConfig Secret wiring (3.1);
  AWS and GCP overlays carry a keyless ModelConfig with no model Secret. Gate:
  `kustomize build` clean for all three overlays; render tests pass.
- **M5 Egress policies per cloud.** Azure and GCP egress allowlists per 4.4. Gate:
  policy lint + render tests; documented divergence (Azure public auth hole, GCP
  VPC-SC) captured in the policy headers.
- **M6 Model backends.** Per-cloud `ModelConfig` provider blocks with verified
  model IDs and the three-tier mapping. Gate: render tests; version-recency note
  inline (Azure 4o retirement, Gemini 2.5 retirement date).
- **M7 Tooling + docs.** `az`/`gcloud` in the image; `ATTRIBUTION.md`; walkthrough
  notes on the per-cloud exfil-lesson differences. Gate: image builds; ai-isms
  clean on changed docs.
- **M8 Local dev/validation target.** `infra/local/` (k3d or kind config, the
  Calico or Cilium install, a bootstrap script), the `providers/local.sh` shim, and
  the `overlays/local` overlay (keyless Ollama ModelConfig, NodePort ingress,
  `local-path` StorageClass, no ESO). This slots after M1 and gives the later
  overlay milestones (M4 to M6) an offline substrate: their overlays can be applied
  and converged with a real `kubectl apply` on the local cluster, not just rendered.
  Falco and Datadog degrade locally (3.6) and are out of the local convergence gate.
  Gate: local cluster stands up; base + `overlays/local` apply and converge; a
  NetworkPolicy enforcement check confirms the CNI actually blocks a denied egress
  (the guard against the kindnet/flannel silent no-op).

## 6. Risks and open questions

1. **GCP exfil lesson redesign (highest).** VPC-SC is org/perimeter-level. The
   workshop's per-attendee-org model and the perimeter setup need design before
   M3. **Open (Michael checking, 2026-07-01): likely org-level.** Does the
   workshop have org-level GCP access to stand up a perimeter? Two resolutions:
   (a) **org-level VPC-SC** with a "VPC accessible services" allowlist (the clean
   Vertex-yes/GCS-no lesson, per 3.3); or (b) if org access is unavailable, a
   **per-cluster SNI proxy** (Squid or an Istio egress gateway that filters on the
   TLS SNI, allowing `aiplatform.googleapis.com` and denying
   `storage.googleapis.com`) provisioned inside each cluster's own perimeter. The
   SNI-proxy path keeps the lesson intact without org access, at the cost of a
   per-cluster proxy pod; without either, the GCP exfil lesson degrades to "deny
   internet" only. This is the one open question that blocks M3 design.
2. **Teardown script paths (4.1).** Symmetric move touches the three out-of-repo
   teardown scripts; M1 backs them up and updates them in the same change, and
   copies canonical versions into `infra/terraform/aws/teardown/`.
3. **Azure ESO identity-object scaling (3.1, 3.5).** Azure-only: it is the one
   cloud with a per-cluster model Secret, and the cost is the FIC-per-UAMI cap, not
   the Secret itself. 250 clusters need 250 ESO FICs; at 20 FICs/UAMI that is 13
   UAMIs, one central Key Vault key, serial FIC creation per UAMI (409 on
   concurrent writes), azurerm `>= 3.40`. AWS and GCP are secret-zero and carry no
   equivalent cost. This is bounded and understood, not open; it is engineering
   work budgeted into the Azure milestone.
4. **Version drift.** Azure gpt-4o retired; Gemini 2.5 retires 2026-10-16. Pin to
   current tiers and add a recency note; do not pin to a retiring model.
5. **No live validation this pass** (locked scope). M2/M3 plans are validated by
   `plan` only; first real apply is a later, separately-approved pass.
6. **Local CNI and observability (3.6).** The local target needs Calico or Cilium
   or the NetworkPolicy lesson silently no-ops, and Falco/Datadog degrade offline.
   Both are known and handled in M8 (Calico/Cilium is a hard bootstrap requirement
   with an enforcement check; Falco/Datadog are out of the local gate), so this is
   not open, it is scoped work.

## 7. Out of scope

- Simultaneous multi-cloud in one run.
- Claude on Azure (Azure OpenAI serves GPT only).
- Live Azure/GCP provisioning and end-to-end fleet runs.
- The `local` target as an attendee-facing platform. It is a developer and
  validation substrate only; attendee runs are always on a real cloud.
- **Oracle Cloud (OKE) as a fourth cloud, deferred.** Two independent
  verification spikes against Oracle primary docs and the kagent source
  (2026-07-01) confirm the deferral. Three facts stack against adding OKE now:
  1. **No native kagent OCI provider.** The `ModelProvider` enum has nine values,
     none Oracle (per 3.6). The only path in is bolting kagent's OpenAI provider
     onto a custom `BaseURL` pointed at OCI's OpenAI-compatible endpoint
     (`https://inference.generativeai.${region}.oci.oraclecloud.com/openai/v1`),
     which exists but authenticates with OCI IAM request-signing or the
     six-month-old (2026-01-21) OCI GenAI bearer "API keys," not the OpenAI keys
     kagent expects. A shim, not an integration.
  2. **No Claude on OCI GenAI.** Oracle's pretrained-models catalog (checked
     2026-07-01) serves Cohere Command A, Google Gemini 2.5, Meta Llama 4/3.3,
     OpenAI gpt-oss, and xAI Grok. Anthropic Claude is not listed anywhere in the
     chat catalog. (The "Anthropic Adapter" in search results belongs to Oracle
     Integration/OIC, a separate SaaS connector, not the OCI GenAI service.) A
     fourth cloud would run the same lesson against Grok/Llama/Gemini, breaking
     Claude parity with the other three clouds and diluting the point.
  3. **Auth model does not fit.** OKE Workload Identity (enhanced clusters) is the
     native keyless path, but kagent's ModelConfig has no OCI signer, so a kagent
     pod would fall back to a static OCI GenAI API-key Secret per cluster, the
     opposite of the secret-zero property AWS and GCP give for free.

  Net: a bespoke auth shim multiplied across the fleet, and abandoning Claude, for
  a logo on a slide. The full evidence and citations are in
  `docs/DECISION-LOG.md`. Revisit only if kagent ships a first-class OCI provider
  or Anthropic Claude lands on the OCI GenAI model list, or a venue or account
  specifically requires Oracle.

## 8. Housekeeping note

PROJECT_STATE.md predates the lifecycle schema. `/init-state` migration is flagged
mandatory before non-trivial source work and will be run at the start of Phase 2,
once this plan is approved.
