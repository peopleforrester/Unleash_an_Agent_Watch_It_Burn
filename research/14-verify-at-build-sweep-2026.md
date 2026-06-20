# Research 14: verify-at-build Doc-Accuracy Sweep (June 2026)

Doc-accuracy spike confirming or correcting the load-bearing config facts that carry
`# verify-at-build` flags in the repo, checked against current primary sources.

## Verification Method

- Method: live web research against official primary sources (vendor docs, GitHub
  release feeds, and project source repositories), dated **2026-06-20**.
- Each item below states CONFIRMED, CORRECTION, or account-specific, with the source URL.
- Field-level claims (schemas, JSON envelopes, API field names) were checked against the
  authoritative doc page or the project source where the doc page lacked field detail.
- This is research verification, NOT a live-cluster spike. Items still marked [SPIKE] in
  the YAML (runtime enforcement) are confirmed at the schema/doc level here, not at runtime.
- Flag inventory taken from:
  `grep -rn verify-at-build --include=*.yaml --include=*.md --include=*.py .`
  (87 occurrences across infra, gitops, agent/gateway, platform, policies, games, docs).

---

## 1. EKS AL2023 podPidsLimit delivery (infra/node-config/pid-limit-nodeadm.yaml)

### 1a. nodeadm schema + apiVersion + podPidsLimit key — CONFIRMED

- `apiVersion: node.eks.aws/v1alpha1`, `kind: NodeConfig` is correct and current.
- `spec.kubelet.config` is typed as a `KubeletConfiguration` (string-keyed object,
  RawExtension values) that nodeadm "merges with the defaults." Because it is the standard
  upstream `kubelet.config.k8s.io/v1beta1` KubeletConfiguration, `podPidsLimit` is a valid
  key (it is an upstream KubeletConfiguration field). The repo's
  `spec.kubelet.config.podPidsLimit: 1024` is schema-valid.
- Sources:
  https://awslabs.github.io/amazon-eks-ami/nodeadm/ ;
  https://awslabs.github.io/amazon-eks-ami/nodeadm/doc/api/ ;
  KubeletConfiguration reference https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/

### 1b. Delivery path for eksctl managed AL2023 — CORRECTION

The YAML comment (lines 6-8) says the NodeConfig is "delivered via the node group's
launch-template user-data (a drop-in under /etc/eks/nodeadm.d/, MIME-multipart)." The
`/etc/eks/nodeadm.d/` drop-in framing is not how eksctl delivers it.

- The premise is correct: eksctl managed AL2023 nodegroups do NOT accept
  `kubeletExtraConfig` (that field was AL2-only).
- The correct eksctl mechanism is `managedNodeGroups[].overrideBootstrapCommand`: you put
  the full `NodeConfig` YAML there, eksctl PREPENDS it to the launch-template userdata, and
  nodeadm MERGES it with the EKS-injected default NodeConfig. There is no manual
  `/etc/eks/nodeadm.d/` file authoring step for eksctl-managed nodes; nodeadm's
  multi-document merge is what combines configs.
- Recommended correction to the comment: "delivered via eksctl
  `managedNodeGroups[].overrideBootstrapCommand` (a NodeConfig that eksctl prepends to the
  launch-template userdata; nodeadm merges it with the EKS default NodeConfig)." Keep the
  AL2 `--pod-max-pids` / `--kubelet-extra-args` note as the AL2 equivalent.
- Sources:
  https://docs.aws.amazon.com/eks/latest/eksctl/node-bootstrapping.html ;
  https://awslabs.github.io/amazon-eks-ami/nodeadm/doc/examples/ (merging multiple config objects)

---

## 2. agentgateway mcpAuthorization on OSS v1.3.0 (agent/gateway/mcp-authz-on.yaml)

### 2a. CEL over mcp.tool.name — CONFIRMED

- `mcpAuthorization.rules` are CEL expressions evaluated per MCP method. CEL variables
  include `mcp.tool.name`, `mcp.tool.target`, `mcp.prompt.name`, `mcp.resource.name`, and
  JWT claims (`jwt.sub`, `jwt.<claim>`, `has(...)`). Rules OR together: any match allows.
- Source: https://agentgateway.dev/docs/standalone/latest/mcp/mcp-authz/

### 2b. action: Allow|Deny — CORRECTION (resolves the open SPIKE question)

- The OSS standalone mcpAuthorization model is **allow-only CEL with implicit deny. There
  is NO `action` field** on rules. A request is allowed if any rule matches; anything not
  matched is denied, and disallowed tools are filtered out of `list_tools`.
- Therefore FORM A in the YAML (allowlist of `mcp.tool.name == "..."` rules, implicit-deny)
  is the correct and only OSS form. FORM B (commented `expression:` + `action: Deny|Allow`)
  is NOT a valid OSS v1.3.0 schema and should be deleted, not kept as an alternative. The
  "spec references action: Allow|Deny" note appears to come from a Solo Enterprise (2.x)
  doc, not the OSS standalone line.
- Source: https://agentgateway.dev/docs/standalone/latest/mcp/mcp-authz/

### 2c. targets-allowlist field path — CORRECTION

- The doc schema attaches mcpAuthorization under `mcp.policies.mcpAuthorization` (backend
  level) or `mcp.targets[].policies.mcpAuthorization` (per target). MCP server allowlisting
  is structural via the `mcp.targets[]` list. The repo's mcp-authz-on.yaml puts `targets:`
  at the LISTENER level and `policies.mcpAuthorization` at the top level of `config.yaml`,
  which does not match the documented `mcp.{targets,policies}` nesting. Confirm and re-nest
  against the OSS standalone config schema at build.
- Source: https://agentgateway.dev/docs/standalone/latest/mcp/mcp-authz/

### 2d. Version drift — CORRECTION (repo-wide, affects all agentgateway YAML)

- **agentgateway v1.3.0 shipped GA on 2026-06-17** (blog: "Agentgateway v1.3.0: LLM
  Consumption, Reimagined"). The repo's research 02 (dated 2026-06-15) and every
  agentgateway YAML comment still call v1.3.0 a beta/prerelease and pin `v1.2.1`
  ("do NOT pin a v1.3.x prerelease", agentgateway.yaml lines 12, 59). docs/STACK-WALKTHROUGH.md
  already says "v1.3.0 GA" and is now correct; the YAML pins and "beta" warnings are stale.
  Decide at build whether to move the pin to v1.3.0 GA and re-verify the guardrail/MCP field
  paths against the v1.3.0 standalone docs (they may have moved between 1.2.1 and 1.3.0).
- Sources:
  https://agentgateway.dev/blog/2026-06-17-agentgateway-v1.3.0/ ;
  https://github.com/agentgateway/agentgateway/releases

---

## 3. kagent A2A usage fields + requireApproval runtime (kagent 0.9.7)

### 3a. Token field names — CORRECTION (this is a real parsing bug)

- The token COUNT field names are correct: `promptTokenCount`, `candidatesTokenCount`,
  `totalTokenCount` (Gemini/ADK camelCase). CONFIRMED in the kagent A2A example output.
- The CONTAINER key is wrong. kagent passes Google ADK's metadata through under
  **`adk_usage_metadata`**, NOT `kagent_usage_metadata`. The kagent "bring your own ADK
  agent" doc shows the A2A response metadata as
  `"adk_usage_metadata": { "promptTokenCount": 415, "candidatesTokenCount": 15, "totalTokenCount": 430 }`.
- Impact: `agent/gateway/guard-proxy/proxy.py` `record_usage()` (lines 129, 131) looks up
  `kagent_usage_metadata` in both the `result.metadata` and the
  `result.status.message.metadata` fallback path. Against a real kagent ADK agent it will
  find neither key and silently tally ZERO tokens, breaking the cost counter ("wasted tokens
  are the new DoS" story). cost/README.md line 8 and PROJECT_STATE.md likewise assert
  `kagent_usage_metadata` was "confirmed live 2026-06-17" — that confirmation does not match
  the published ADK metadata key.
- Correction: parse `adk_usage_metadata` (keep a fallback to `kagent_usage_metadata` only if
  a build-time live capture proves kagent re-keys it; the published docs show ADK's key).
  Re-verify the exact key against a live A2A response at build before the event.
- Sources:
  https://kagent.dev/docs/kagent/examples/a2a-byo (shows `adk_usage_metadata` + the three
  TokenCount fields) ;
  https://github.com/google/adk-python/issues/311 (ADK usage_metadata token fields)

### 3b. requireApproval runtime (kagent 0.9.7) — account-specific / still [SPIKE]

- `requireApproval` (per-tool HITL gate, subset of `toolNames`, CEL-validated) is PRESENT in
  the 0.9.7 v1alpha2 Agent CRD. That part is CONFIRMED (research 01, pulled from the live
  CRD). The kagent-agent.yaml comment (lines 10-11) correctly states runtime enforcement
  through the serving path is unverified.
- I could not confirm from public docs that the kagent 0.9.7 controller actually pauses
  execution and surfaces an approval prompt through the A2A/agentgateway serving path. This
  remains a true build-time live SPIKE; the YAML's "do not rely on it until verified" stance
  is the correct posture. No correction needed, the flag is honest.
- Source: https://kagent.dev/docs/kagent/getting-started/first-mcp-tool ;
  live CRD `kagent.dev_agents.yaml` @ chart 0.9.7 (per research 01)

---

## 4. LLM Guard verdict envelope on the API-server image — CONFIRMED

- The llm-guard-api FastAPI server response models are, from source
  (`llm_guard_api/app/schemas.py`):
  - AnalyzePromptResponse: `is_valid: bool`, `scanners: Dict[str, float]`, `sanitized_prompt: str`
  - AnalyzeOutputResponse: `is_valid: bool`, `scanners: Dict[str, float]`, `sanitized_output: str`
- The repo's usage is correct: proxy.py reads `verdict.get("is_valid", True)` and
  `verdict.get("sanitized_output")`; PROJECT_STATE.md describes the envelope as
  `{is_valid, scanners, sanitized_output/prompt}`. All match.
- Minor doc nit: llm-guard-service.yaml line 36 says "confirm the verdict envelope
  (is_valid / sanitized_output / scores)". The per-scanner field is named **`scanners`**
  (a Dict[str, float] of risk scores), not `scores`. Update the comment to `scanners`.
- Note the `/analyze/*` endpoints (which proxy.py calls) APPLY redaction and return
  `sanitized_*`; the `/scan/*` endpoints only validate. proxy.py correctly uses `/analyze/*`.
- Sources:
  https://protectai.github.io/llm-guard/api/deployment/ ;
  source schema https://github.com/protectai/llm-guard (llm_guard_api/app/schemas.py)

---

## 5. Datadog OTel exporter keys (gitops/apps/otel-collector.yaml) — CONFIRMED

- The Datadog exporter config keys are correct: `datadog.api.key` and `datadog.api.site`,
  with `${env:DD_API_KEY}` / `${env:DD_SITE}` env-substitution syntax. Default site is
  `datadoghq.com`.
- DD_SITE valid values are accurate. Full current set: `datadoghq.com` (US1, default),
  `us3.datadoghq.com`, `us5.datadoghq.com`, `datadoghq.eu` (EU1), `ap1.datadoghq.com`,
  `ddog-gov.com` (US1-FED). The repo's example list (datadoghq.com, us5.datadoghq.com,
  datadoghq.eu) is a correct subset.
- account-specific: the actual `DD_SITE` and the `datadog-secret` key must come from
  Whitney's Datadog account at build (the YAML already flags this). The hardcoded
  `DD_SITE: "datadoghq.com"` default at line 109 is a sane placeholder but MUST be set to
  the real account site.
- Sources:
  https://docs.datadoghq.com/opentelemetry/setup/collector_exporter/install/ ;
  https://docs.datadoghq.com/agent/troubleshooting/site/

---

## 6. VPC-CNI NetworkPolicy enforcement on EKS — CONFIRMED

- The Amazon VPC CNI natively enforces Kubernetes NetworkPolicy (GA since Aug 2023). The
  Network Policy Controller runs in the EKS control plane (auto-installed for clusters at
  k8s 1.25+) and the aws-network-policy-agent DaemonSet enforces on each node via eBPF.
- Enablement: set `enableNetworkPolicy: true` on the VPC CNI addon (equivalently the addon
  ConfigMap / Helm value `enable-network-policy-controller: "true"`). Pods selected by at
  least one NetworkPolicy have their traffic restricted; unselected pods are unrestricted.
- The repo's claim (docs/STACK-WALKTHROUGH.md lines 12-13, 31, 36: "CNI is VPC-CNI, its
  NetworkPolicy feature enforces the default-deny") is accurate. The one build action is to
  ensure the VPC CNI addon has NetworkPolicy enablement turned ON in the cluster.yaml addon
  config; default-deny will not enforce otherwise. 2025 added an enhanced tier (cluster-wide
  Admin-tier policy CRD) on top of standard NetworkPolicy; not required for this workshop.
- Sources:
  https://aws.amazon.com/blogs/containers/amazon-vpc-cni-now-supports-kubernetes-network-policies/ ;
  https://docs.aws.amazon.com/eks/latest/userguide/network-policies-troubleshooting.html ;
  https://github.com/aws/aws-network-policy-agent ;
  https://aws.amazon.com/blogs/containers/amazon-eks-introduces-enhanced-network-policy-capabilities/

---

## Summary table

| # | Item | Verdict |
|---|------|---------|
| 1a | nodeadm schema + apiVersion + podPidsLimit key | CONFIRMED |
| 1b | eksctl AL2023 delivery path | CORRECTION (overrideBootstrapCommand, not /etc/eks/nodeadm.d/) |
| 2a | mcpAuthorization CEL over mcp.tool.name | CONFIRMED |
| 2b | action: Allow|Deny field | CORRECTION (allow-only implicit-deny; no action field; delete FORM B) |
| 2c | targets-allowlist field path | CORRECTION (re-nest under mcp.targets / mcp.policies) |
| 2d | agentgateway version | CORRECTION (v1.3.0 GA 2026-06-17; YAML "beta"/v1.2.1 pins stale) |
| 3a | kagent A2A token field container | CORRECTION (adk_usage_metadata, not kagent_usage_metadata; proxy.py bug) |
| 3b | requireApproval runtime | account-specific / still a live SPIKE (flag honest) |
| 4 | LLM Guard verdict envelope | CONFIRMED (minor: field is `scanners`, not `scores`) |
| 5 | Datadog OTel exporter keys + DD_SITE | CONFIRMED (account-specific site value) |
| 6 | VPC-CNI NetworkPolicy enforcement | CONFIRMED (must enable on the addon) |
