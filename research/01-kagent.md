# Research Spike 01 — kagent (CNCF Sandbox agent framework)

Subject: kagent. Resolves BUILD-SPEC.md section 5 "Agent" + Phase 3 FLAGs.

## Verification Method

Web research against official kagent docs (kagent.dev/docs) and the kagent-dev/kagent
GitHub repo, dated **2026-06-15**. Where field names mattered (Bedrock, MCP, RBAC) the
claims were verified NOT from docs prose or tutorials but by pulling the **actual CRD
schemas from the published OCI Helm chart** on the build server:

```
helm show chart   oci://ghcr.io/kagent-dev/kagent/helm/kagent      --version 0.9.7
helm pull --untar oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds --version 0.9.7
```

CRD field names below are quoted from the live `0.9.7` CRD YAML, so they are authoritative
for that chart version. Doc-prose-only claims are marked as such. A source URL is given
beside each material claim.

---

## Verified

### 1. Current stable Helm chart version (spec said 0.7.7 from April 2026 — it MOVED)

The spec's `0.7.7` is stale. kagent has shipped the entire 0.8.x and 0.9.x lines since.

- Latest stable release as of 2026-06-15: **`v0.9.7`**, released 2026-06-11.
  (`gh release list --repo kagent-dev/kagent`; https://github.com/kagent-dev/kagent/releases)
- Recent tags: v0.9.7 (06-11), v0.9.6 (06-05), v0.9.5 (06-02), v0.9.4 (05-14),
  v0.9.3 (05-11), v0.9.2, v0.9.1, v0.9.0 (04-22).
- Helm chart version tracks the release tag. Confirmed live:
  `helm show chart … --version 0.9.7` returns `name: kagent`, `version: 0.9.7`
  (no separate appVersion). All bundled subcharts (k8s-agent, istio-agent, observability-agent,
  etc.) are pinned to `0.9.7`. The `kmcp` dependency subchart is `0.3.0`; `kagent-tools` is `0.2.1`.
- Install is a **two-chart** flow (CRDs first, then kagent), both as OCI artifacts on GHCR:
  - `oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds`
  - `oci://ghcr.io/kagent-dev/kagent/helm/kagent`
  (https://kagent.dev/docs/kagent/resources/helm ; package: https://github.com/orgs/kagent-dev/packages/container/package/kagent/helm/kagent)

IMPORTANT API-GROUP DRIFT: kagent renamed fields and bumped the API group around the
0.6→0.7 boundary, and the current CRDs now serve **both `kagent.dev/v1alpha1` and
`kagent.dev/v1alpha2`**. Bedrock support exists ONLY in `v1alpha2`. Any tutorial or
manifest written for ≤0.7 (including the spec's 0.7.7 assumption) will use the older
shape. Write all manifests against `kagent.dev/v1alpha2`.

### 2. AWS Bedrock model-provider config — EXACT field names (verified from CRD)

Bedrock is a **first-class native provider** in v1alpha2 (it was a feature request, issue
#183, now shipped — it is NOT an OpenAI-compat shim, despite some tutorials wiring it that
way via `provider: OpenAI` + a bedrock-runtime baseUrl). Use the native path.

Model wiring is two CRDs: a `ModelConfig` (the provider/credentials) that an `Agent`
references by name.

`ModelConfig` for native Bedrock (field names quoted from the 0.9.7 CRD
`kagent.dev_modelconfigs.yaml`, v1alpha2 schema):

```yaml
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: bedrock-claude
  namespace: <attendee-ns>
spec:
  provider: Bedrock                 # enum; v1alpha2 adds: Bedrock, SAPAICore (v1alpha1 has neither)
  model: us.anthropic.claude-sonnet-4-20250514-v1:0   # Bedrock model ID / inference profile
  bedrock:
    region: us-east-1               # ONLY required sub-field of the bedrock block
    # additionalModelRequestFields: {...}   # optional, forwarded as-is to Converse API
  # apiKeySecret: bedrock-credentials   # OPTIONAL — see auth note below
  # apiKeySecretKey: <key-in-secret>
```

Verified exact facts:
- `spec.provider` enum in **v1alpha2** is: `Anthropic, OpenAI, AzureOpenAI, Ollama, Gemini,
  GeminiVertexAI, AnthropicVertexAI, Bedrock, SAPAICore`. The **v1alpha1** enum stops at
  `AnthropicVertexAI` — no `Bedrock`. (CRD lines: v1alpha2 provider enum; v1alpha1 enum.)
- The Bedrock sub-block is literally `spec.bedrock`, with exactly two properties:
  `region` (string, **required**) and `additionalModelRequestFields` (free-form, for things
  like Claude extended thinking / top_k). There is NO `bedrock.accessKeyId`,
  `bedrock.profile`, or `bedrock.endpoint` field — credentials are handled outside the
  bedrock block.
- Credentials / auth (CRD descriptions, verbatim sense):
  - Preferred: omit `apiKeySecret` and let the agent pod use the **AWS credential chain**
    (IRSA / pod identity / instance role). This is the clean path on EKS.
  - Static keys: set `spec.apiKeySecret` (name of a Secret in the same namespace as the
    ModelConfig) containing `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.
  - `spec.apiKeyPassthrough` (bool) forwards a Bearer token from the incoming A2A request as
    the provider key; **mutually exclusive with `apiKeySecret`**. Not relevant for Bedrock.
- The Agent references the model by name: `spec.declarative.modelConfig` is a **string** =
  the name of a ModelConfig in the same namespace (default `"default-model-config"`).
  (CRD: agents v1alpha2 `modelConfig` description.)

Sources: https://kagent.dev/docs/kagent/supported-providers/amazon-bedrock ;
live CRD `kagent.dev_modelconfigs.yaml` @ chart 0.9.7 ;
https://github.com/kagent-dev/kagent/issues/183

### 3. MCP server consumption + tool allowlisting (the "excessive agency" beat)

kagent has SEVEN+ CRDs; the MCP-relevant ones are `mcpservers.kagent.dev` (in-cluster,
kagent-managed MCP server), `remotemcpservers.kagent.dev` (external MCP endpoint), and
`toolservers.kagent.dev`. An Agent attaches tools by **referencing** one of these.

Agent → MCP wiring (field names from 0.9.7 `kagent.dev_agents.yaml`, v1alpha2,
`spec.declarative.tools[]`):

```yaml
spec:
  declarative:
    tools:
      - type: McpServer              # ToolProviderType enum: McpServer | Agent  (maxItems: 20)
        mcpServer:
          name: mcp-website-fetcher  # required: name of the MCPServer/RemoteMCPServer
          kind: MCPServer            # or RemoteMCPServer
          apiGroup: kagent.dev
          toolNames:                 # ALLOWLIST — only these tools are exposed (maxItems: 50)
            - fetch
          requireApproval:           # PER-TOOL human-approval gate (maxItems: 50)
            - fetch                  # each entry MUST also appear in toolNames
          allowedHeaders:            # which A2A request headers propagate to MCP calls
            - x-tenant-id
```

**Two distinct authorization mechanisms exist, both per-agent, both verified in the CRD:**
1. `toolNames` — an explicit allowlist. If set, only the named tools from that MCP server
   are made available to the agent, even if the server exposes more. (Default-deny is NOT
   automatic: if `toolNames` is OMITTED, kagent exposes ALL tools the server advertises.
   This is the excessive-agency footgun — for the workshop, the "bad" config is leaving
   `toolNames` off; the "good" config is a tight allowlist.)
2. `requireApproval` — a per-tool human-in-the-loop gate. Listed tools pause execution and
   prompt the user before the call runs. A CEL validation enforces every `requireApproval`
   entry also be in `toolNames`.
   NOTE: `requireApproval` appears in the v1alpha2 CRD shipped in 0.9.7. It is newer than
   the spec's 0.7.7 assumption — verify it actually enforces at runtime in your build
   (CRD presence ≠ controller wiring; see Risks).

Header/auth propagation to MCP tools is controlled by `allowedHeaders`; Authorization
headers are NOT forwarded unless explicitly listed, and STS-generated tokens take precedence.

Sources: https://kagent.dev/docs/kagent/getting-started/first-mcp-tool ;
live CRD `kagent.dev_agents.yaml` @ 0.9.7 (tools[].mcpServer block).

### 4. Agent ServiceAccount / RBAC model (the scoping boundary for attacks 2 & 3)

The Agent CRD controls the pod's ServiceAccount directly via `spec.declarative.deployment`
(field names from 0.9.7 CRD, verbatim descriptions):

- `deployment.serviceAccountName` (string): "specifies the name of an existing
  ServiceAccount to use. If this field is set, the Agent controller will NOT create a
  ServiceAccount for the agent. Mutually exclusive with ServiceAccountConfig."
- `deployment.serviceAccountConfig` (labels/annotations): only usable when
  `serviceAccountName` is NOT set; the controller then auto-creates an SA named after the
  agent and applies these.

So the workshop's scoping model is standard k8s RBAC and fully under our control:
1. Pre-create a dedicated SA in the attendee namespace (e.g. `agent-sa`).
2. Bind a tight `Role` + `RoleBinding` granting exactly: create/get workloads in the ns,
   get/list the planted secret. Deny clusterrole/clusterrolebinding/role/rolebinding verbs.
3. Set `spec.declarative.deployment.serviceAccountName: agent-sa` so the controller binds
   the agent pod to OUR SA rather than minting its own.

This satisfies Phase 3 verification directly: `kubectl auth can-i … --as=system:serviceaccount:<ns>:agent-sa`.

Sources: https://kagent.dev/docs/kagent/resources/api-ref ;
live CRD `kagent.dev_agents.yaml` @ 0.9.7 (deployment.serviceAccountName/serviceAccountConfig).

---

## Unverified / Could not confirm

- **`requireApproval` runtime behavior.** Confirmed present in the 0.9.7 CRD schema and CEL
  validation. NOT confirmed end-to-end that the kagent controller actually pauses execution
  and surfaces an approval prompt through agentgateway / the serving path in 0.9.7. Treat as
  schema-present, runtime-unverified until tested in the build.
- **Bedrock + AWS credential-chain on EKS specifics.** The CRD shows the omit-`apiKeySecret`
  path uses the pod credential chain, implying IRSA/pod-identity works, but I did not verify
  the exact pod-identity annotation requirements or that Converse API + inference profiles
  behave on the chosen region. Confirm during Phase 3 with a live trivial prompt.
- **Whether the bundled `k8s-agent` etc. subcharts interfere with a custom scoped agent.**
  The 0.9.7 umbrella chart ships several opinionated agents. Need to confirm we can install
  kagent core + CRDs and define ONLY our scoped agent, disabling the bundled ones via Helm
  values (the spec wants one tightly-scoped agent, not a swarm).
- **Exact model ID availability.** `us.anthropic.claude-sonnet-4-20250514-v1:0` is the doc
  example; the actual enabled Bedrock model/region for Michael's AWS account must be
  confirmed at build (model access must be granted in the Bedrock console).
- **agentgateway integration version compatibility with kagent 0.9.7** — out of scope for
  this spike (separate FLAG in spec §5/§Phase 4), but note 0.9.7 is much newer than the
  spec baseline, so re-verify the gateway↔agent serving contract.

---

## Version strings for VERSIONS.lock

```
kagent_helm_chart      = 0.9.7        # oci://ghcr.io/kagent-dev/kagent/helm/kagent
kagent_crds_chart      = 0.9.7        # oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds
kagent_api_group       = kagent.dev/v1alpha2   # use v1alpha2 (Bedrock + requireApproval live here)
kagent_kmcp_subchart   = 0.3.0
kagent_tools_subchart  = 0.2.1
# Verified live via `helm show chart … --version 0.9.7` on 2026-06-15.
# Latest release tag at verification: v0.9.7 (2026-06-11). Pin exactly; Sandbox = breaking changes between minors.
```

---

## Risks for the build

1. **Version baseline is two minor lines stale (HIGH).** The spec is written against 0.7.7;
   current is 0.9.7. kagent is CNCF Sandbox and explicitly makes breaking CRD/API-group
   changes between minors (0.6→0.7 renamed fields and bumped the group; 0.8 and 0.9 followed).
   Every kagent manifest in the spec's repo layout (`agent/kagent-agent.yaml`) must be
   authored against `v1alpha2`, not copied from any pre-0.8 tutorial. Pin 0.9.7 hard.

2. **Bedrock is v1alpha2-only and field names differ from every OpenAI tutorial (HIGH —
   this was the spec's explicit FLAG).** The real path is `spec.provider: Bedrock` +
   `spec.bedrock.region`, credentials via AWS chain (no key) or `spec.apiKeySecret`. Do NOT
   use the `provider: OpenAI` + bedrock-runtime baseUrl shim that the DEV.to/Medium tutorials
   show — it is a compatibility hack, not the native provider. Bedrock model access must be
   granted in the AWS console for the chosen region or the agent will fail opaquely.

3. **Excessive-agency default is the footgun, which is good for the beat but must be set
   deliberately (MEDIUM).** Omitting `toolNames` exposes ALL of an MCP server's tools to the
   agent — that IS the "bad MCP server" demo. The fix (tight `toolNames` allowlist, optionally
   `requireApproval`) is per-agent and verified in the 0.9.7 CRD. Build both states explicitly.

4. **`requireApproval` runtime not yet proven (MEDIUM).** It is in the CRD but may not be
   fully wired through the serving path in 0.9.7. If the workshop wants to *demo* per-tool
   approval, test it live before relying on it; otherwise lean on `toolNames` allowlisting,
   which is the older and more certain mechanism.

5. **Bundled agent swarm in the umbrella chart (LOW-MEDIUM).** 0.9.7 ships several default
   agents (k8s, istio, observability, etc.). The workshop wants ONE scoped agent. Disable the
   extras via Helm values or the blast radius / SA story gets muddy; confirm the values keys.

6. **RBAC model is sound and fully ours (LOW).** `deployment.serviceAccountName` lets us bind
   the agent pod to a pre-created scoped SA, so Phase 3's `auto-deny clusterrolebinding` /
   `allow deployment in ns` outcomes are achievable with standard Role/RoleBinding. No kagent-
   specific obstacle here. Just ensure the controller's OWN SA (separate, for the controller)
   is not conflated with the agent pod SA.
