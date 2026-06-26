# Decision Log and Verification Corrections

Two records in one place:

1. **Verification corrections** — claims we asserted (usually "X is absent / not working") that
   flipped, or whose evidence turned out invalid, once we searched properly. This section exists
   because we kept concluding absence from a narrow or truncated query. Read it before asserting a
   negative.
2. **Key decisions** — technical decisions and the *evidence* behind them, so a later session can
   trace why, not just what.

---

## Methodology rule (the lesson that created this file)

When a query returns "absent" / "not found" / "zero", that is evidence about the QUERY, not about
reality. Before asserting the thing does not exist or does not work:

- **Re-test with a targeted query**, not a broad `OR` or wildcard. An `OR` filter can silently
  under-match; a wildcard can be truncated.
- **Check for row-limit truncation.** If a result count exactly equals the page limit (e.g. 100 rows
  for a limit of 100), the result is truncated and proves nothing about anything past the cutoff.
- **Widen the time window** and **check alternate names / IDs** (a service may report under a
  different `service.name`, a secret under a different region, a file under a moved path).
- **Cite the exact query or command** as the evidence for the claim, positive OR negative. "Not
  there" with no cited query is not a finding.

Distinguish "my query did not match" from "the thing does not exist." Only the second is a finding,
and only after the steps above.

---

## Verification corrections

| Date | Claim asserted | Reality | What revealed it | Lesson |
|---|---|---|---|---|
| 2026-06-26 | guard-proxy OTel SDK "not injected" | It WAS injected (full `OTEL_*` env + `opentelemetry-auto-instrumentation-python` init container) | The jsonpath ran mid-rollout and read a transient pod; a robust dump of all container env on the settled pod showed the injection | Do not query during a rollout; read the settled pod; print all of a list, not one key |
| 2026-06-26 | guard-proxy spans "not in Datadog APM" | They WERE there (10 spans) | The filter `service:(guard-proxy OR agentgateway OR kagent)` returned only kagent; a broad search showed `guard-proxy: 10` | An `OR` filter can under-match; confirm with a single-service targeted query |
| 2026-06-26 | agentgateway "emits zero spans" (conclusion correct, first evidence INVALID) | Conclusion true, but the first search did not prove it | The broad `*` search was LIMIT-TRUNCATED: kagent 90 + guard-proxy 10 = the 100-row limit, leaving no room to even see agentgateway. Only a TARGETED `service:agentgateway` (= 0) plus `-service:kagent -service:guard-proxy` (= `{}`) actually confirmed it | A count that equals the page limit is a red flag; confirm negatives with a targeted query, never a truncated broad one |
| 2026-06-26 | agentgateway tracing key is bare top-level `tracing` (WRONG twice) | It is `config.tracing` (under the top-level `config` block). frontendPolicies.tracing crashes one way, bare `tracing` crashes another | The v1.3.0 JSON schema example literally showed `config:` then `tracing:`, and I dismissed the `config:` wrapper as illustrative. The live binary settled it: `Error: tracing: unknown field tracing, expected one of config, binds, frontendPolicies, ...` | Trust the schema example's nesting verbatim; when in doubt, the binary's own "expected one of ..." error enumerates the valid keys |

Add a row whenever a "not there / not working" assertion is later corrected, or whenever its first
evidence is found to be invalid even if the conclusion stood.

---

## Key decisions (with evidence)

| Date | Decision | Evidence |
|---|---|---|
| 2026-06-26 | agentgateway v1.3.0 image registry is `cr.agentgateway.dev`, not `ghcr.io` | GitHub releases API; kubelet event "Successfully pulled image cr.agentgateway.dev/agentgateway:v1.3.0" on `1002` |
| 2026-06-26 | agentgateway config-file key `frontendPolicies.tracing.otlpEndpoint` is rejected by the v1.3.0 binary | Pod crash log: `Error: frontendPolicies.tracing: no variant of enum SimpleLocalBackend found`. The OTLP **env** path also yields nothing: targeted `service:agentgateway` = 0 spans on the live cluster. Correct tracing schema is unresolved. |
| 2026-06-26 | agentgateway guardrails do not attach to a non-LLM A2A backend; guarding stays on guard-proxy | Official v1.3.0 standalone docs document guardrails only under `llm.models[]` with a recognized provider |
| 2026-06-26 | Bedrock model IDs ACTIVE in accen-dev/us-west-2: haiku-4-5, sonnet-4-6, opus-4-8 | `aws bedrock list-inference-profiles` (all three returned ACTIVE) |
| 2026-06-26 | Workshop default model is Sonnet 4.6 (`bedrock-sonnet`) | Live on `1002`: `agent.spec.declarative.modelConfig = bedrock-sonnet`; requests return ~981-token Sonnet replies |
| 2026-06-26 | guard-proxy -> agentgateway hop works end-to-end | `1002`: A2A `message/send` through guard-proxy returns a real Bedrock reply; the guard-proxy `agent.forward` CLIENT span targets `http://agentgateway.agent.svc.cluster.local:3000/` (cited from the spans API) |
| 2026-06-26 | Cost metric is `gen_ai.client.cost` (gen_ai namespace), NOT a custom `witb_cost_usd` tree. Tokens use the standard `gen_ai.client.token.usage`. | OTel GenAI metrics spec (`semantic-conventions-genai`) defines `gen_ai.client.token.usage` and NO monetary metric, so cost is a project suffix under the standard tree. `gen_ai.client.token.usage` is already in Datadog (metric search). Removed the witb_cost_usd Prometheus `/metrics` endpoint + scrape annotation; emit `gen_ai.client.cost` via OTLP (same pipeline as the spans). |

| 2026-06-26 | The two orphaned Classic ELBs are the `console` Service, and the AWS Load Balancer Controller is never installed | `gitops/ai-layer/resources.yaml` `console` is a bare `type: LoadBalancer` (no `aws-load-balancer-type` annotation, no `loadBalancerClass`), so the legacy in-tree cloud provider builds a Classic ELB (one per cluster). The LB-controller IAM Pod Identity role exists in `cluster/main.tf` but no chart consumes it, so the 5 party-app ALB Ingresses are also inert. Source: EKS load-balancing docs, 2026-06-26. Fix in `docs/CONFIGURATION-AND-RECREATION-2026-06.md` §4.1 |
| 2026-06-26 | The whole stack is version-current for June 2026; Bedrock model IDs verified ACTIVE, no regressions | Per-technology recency sweep (see `docs/CONFIGURATION-AND-RECREATION-2026-06.md` §3). Bedrock Haiku 4.5 / Sonnet 4.6 / Opus 4.8 `us.` profiles match Anthropic's Claude-Code-on-Bedrock defaults byte-for-byte (code.claude.com/docs/en/amazon-bedrock). Two real corrections only: OTel `spanmetrics`→`span_metrics` rename, Kyverno policy-level `validationFailureAction` deprecated since 1.13 (not 1.18). `gen_ai.system`→`gen_ai.provider.name` semconv rename |
| 2026-06-26 | Full demo teardown in AWS completed and verified clean | `aws eks list-clusters`=[]; lab VPC `vpc-084f...` destroyed (terraform: 19 resources); NAT `nat-0b3a...` state=`deleted`; default SG `InvalidGroup.NotFound`; 2 orphaned classic ELBs + their k8s-elb SGs deleted by hand (in-tree provider leaked them). Only remnants: 3 cluster-encryption KMS keys in `PendingDeletion` (auto-delete 2026-07-22/26, not billed) |
| 2026-06-26 | Clusters re-provisioned after the teardown for Whitney's hands-on access | `aws eks list-clusters` now returns 5 ACTIVE: `watch-it-burn-whitney-r1/r2/r3/att` + `watch-it-burn-attendee-001`, all in the shared `watch-it-burn-lab-vpc`. The "teardown verified clean" row above still stands for that earlier point in time; this is a deliberate re-provision, not a contradiction |
| 2026-06-26 | Datadog trial keys expired; rotated to the AI Engineer World's Fair pool | Whitney reported expiry. New pool pulled from the Drive doc (`gog drive download`, 298 valid orgs across pools -01/-02). Instructor org `ai-eng-wf-062626-01-001`, admin-attendee `...-01-002`. Rotated in Secrets Manager (`watch-it-burn/datadog` + `/datadog-admin-attendee`), Railway env (14 vars + redeploy, verified bundle shows new orgs), and live clusters r2/r3/att (ESO force-sync + agent restart). r1 = burn cluster, no Datadog agent |
| 2026-06-26 | Attendee cluster reports to its OWN Datadog org, separate from instructor | `whitney-attendee` branch: the 3 datadog ESO ExternalSecrets pull `watch-it-burn/datadog-admin-attendee` (org `...-01-002`); r2/r3 keep `watch-it-burn/datadog` (org `...-01-001`). Verified live: attendee `datadog-secret` api-key tail `79de0a`. An ArgoCD hard-refresh was required because selfHeal reverted the live patch until the cluster synced the branch commit |
| 2026-06-26 | The ~300-org Datadog pool is split across Secrets Manager secrets | A single secret caps at 64 KB; the 298-org pool is 79 KB. Split into `watch-it-burn/datadog-pool` (149) + `/datadog-pool-2` (149); `merge_pool.py` now reads a comma-separated list and concatenates. Validated 296 attendee + 2 admins excluded, no leaks/blanks. Authoritative copies in `~/secrets/datadog/` |
| 2026-06-26 | Railway provisioning auto-deploy fixed (Railpack, not Nixpacks) | The recurring "Deploy failed" was a stale 389 KB GitHub-source snapshot, not config. Settings are correct: root `lab-distribution`, branch `main`, watch path `/lab-distribution/**`, builder Railpack (Nixpacks is deprecated, global rule added). A fresh source rebuild at the same sha (`afc2e44`) succeeded and is the live deploy |
| 2026-06-26 | At 50-60 clusters/account the provisioning wall is ELB-per-Region (50), NOT Elastic IPs | EIPs are not a blocker: internet-facing ALB IPs are AWS-managed (the ALB `LoadBalancerAddresses` is empty), so only the one shared-VPC NAT gateway counts (1 of 5) — proven by 9 EIPs existing in accen-dev under a quota of 5. The real wall: each full cluster = 1 internet-facing ALB + 1 internal NLB (measured 4 + 4 for 4 clusters). `Application Load Balancers per Region` (L-53DA6B97) and `Network Load Balancers per Region` (L-69A177A2) both default to 50 and are adjustable (AWS ELB quota docs, verified 2026-06-26). 60 clusters/account = 60 of each -> over the limit. Request 100 each per account, plus EC2 vCPU 800 (L-1216C47); no EIP increase |

Add a row for each load-bearing decision with the command or query that backs it.

---

## Live validation findings (1002, 2026-06-26)

Exercising the rounds/challenges on `1002` surfaced real bugs (this is why we validate live):

| Finding | Evidence | Status |
|---|---|---|
| Output + input guard toggles work | `/guards` flipped `output:true`, `input_blocklist:true`; a blocklisted prompt returned 403 | OK |
| Kyverno Audit->Enforce toggle works | `failureAction: Enforce` after the toggle | OK |
| **Guard toggles rejected under Kyverno Enforce** | the toggle's `kubectl run` curl pod failed `require-resource-limits` ("CPU and memory limits required") | **FIXED**: toggles now `exec` the guard-proxy (no new pod); verified working under Enforce |
| **C1 egress defense in the wrong namespace** | NetworkPolicies deployed to ns `apps`; the AI layer runs in ns `agent`; egress from `agent` is ALLOWED even under R2 | **FIXED IN CODE (live-test deferred)**: added a Bedrock interface VPC endpoint (`infra/terraform/lab-vpc/main.tf`, private DNS on) so Bedrock is an in-VPC IP, plus four egress-only `agent`-ns policies (`policies/network-policies/per-namespace/agent-*.yaml`): in-VPC 443 allowlist + DNS + OTLP + intra-namespace. S3 PutObject has no endpoint, egresses to the public internet, and is denied. Built after the 1002 teardown, so it stands up on the NEXT provision; live Bedrock-still-works + S3-denied re-test happens then. The two halves MUST land together: without the VPCe the default-deny-egress would break the agent's Bedrock calls. |
| **MCP authz toggle broken** | `toggle-mcp-authz-on.sh` applies `agent/gateway/mcp-authz-on.yaml` -> `Error: namespaces "ATTENDEE_NAMESPACE" not found`; it is the pre-agentgateway overlay | **OPEN**: rework to flip agentgateway `mcpAuthorization` (the deployed mechanism), or the kagent `toolNames` allowlist |
