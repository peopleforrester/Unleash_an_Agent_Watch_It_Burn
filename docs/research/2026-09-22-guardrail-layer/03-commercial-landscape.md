# Commercial landscape for LLM runtime guardrails as a proxy or gateway

Research compiled 2026-09-22. Every claim below is either cited to a source fetched
during this session or explicitly listed as unverified in the final section.

"Spend" throughout means enforcing a USD budget, not merely reporting cost.
"In-cluster" means the enforcement data plane runs inside your own Kubernetes cluster.

Scope of the question: guard-proxy is a platform-injected reverse proxy between an
agent and its model endpoint that enforces input prompt-injection scanning, output
secret-leak scanning, a hard USD spend cap, rate limiting, fail-closed behavior, and
emits OpenTelemetry gen_ai telemetry.

---

## (a) Product table

### Commercial security vendors

| Product | Owner / status | Deployable in-cluster? | Input scan | Output scan | Enforces spend | OTel | Published price |
|---|---|---|---|---|---|---|---|
| Prisma AIRS | Palo Alto (bought Protect AI 2025-07-22; Portkey 2026-05-29) | No. API Intercept (SDK/API) plus Network Intercept; requires cloud-account onboarding | Yes | Yes | Plausibly via the Portkey gateway now, but not documented as a USD cap | Not documented | Token-based licensing (Feb 2026), funded from Software NGFW credits; quote-based |
| Lakera Guard / Check Point AI Security | Check Point (closed Oct 2025) | Yes. Helm chart, K8s, GPU via device plugin, /readyz /livez /startupz probes, air-gap capable | Yes | Yes | No | Not documented | Community $0 / 10k req per month; Enterprise quote |
| Cisco AI Defense | Cisco (Robust Intelligence, Oct 2024) | Hybrid. SaaS control plane plus on-prem gateway data plane over encrypted bidirectional gRPC/TLS, connection initiated from the data plane side | Yes | Yes | No | Not documented | Quote |
| Operant AI (AI Gatekeeper / 3D Runtime Defense) | Independent | Yes. Single helm install, Kubernetes-native, in-cluster | Yes | Yes | No | Not documented | Usage-based, per service deployment in cluster |
| Datadog AI Guard | Datadog | No. SaaS | Yes | Yes, plus tool-call decisions | No | Emits AI Guard traces auto-linked to APM and LLM Observability traces | Quote |
| HiddenLayer AIDR | Independent | Not publicly documented | Yes | Yes | No | SIEM/SOAR integrations; alerts mapped to MITRE ATLAS and OWASP LLM | Sales-led, none public |
| SentinelOne (Prompt Security) | SentinelOne (closed 2025-09-05) | No | Yes | Yes | No | n/a | Quote |
| Cato (Aim Security) | Cato Networks (Sept 2025) | No. SASE edge | Yes | Yes | No | n/a | Quote |
| F5 AI Guardrails (CalypsoAI) | F5 (closed 2025-09-29) | Inference-layer posture; in-cluster deployability not verified | Yes | Yes | No | Not documented | Quote |
| CrowdStrike AIDR (Pangea) | CrowdStrike (Sept 2025) | No. Falcon platform | Yes | Yes | No | n/a | Quote |
| Noma, Pillar, Zenity, Straiker, WitnessAI | Independent as far as checked | SaaS control plane. Pillar exposes a guardrail API that AI gateways call per request | Yes | Yes | No | Varies | Quote |

A blank or "not documented" in the OTel column means I did not find documentation, not
that the capability is proven absent.

### Gateways and open source

| Product | License / host | In-cluster | Input/output guards | Enforces spend | OTel |
|---|---|---|---|---|---|
| LiteLLM | OSS, requires Postgres | Yes | Yes. Pre-call, post-call, during-call, logging-only; blocking supported. Integrations include Aporia, Lakera, Presidio, Bedrock, Azure Content Safety, Guardrails AI, OpenAI Moderation, DynamoAI, Javelin, Lasso, Pangea, Model Armor, AIM, Cato Networks, and a generic guardrail API used by Pillar Security | Yes. Hard USD budget per key, user, team, end-user, global. Open-source tier | Yes |
| Cloudflare AI Gateway | SaaS | No | Guardrails billed as Workers AI token inference | Yes. Spend limits, open beta, changelog 2026-06-05. 429 on breach, scoped by model, provider or custom metadata, 20 rules per gateway, all plans | Logs and Logpush |
| NeuralTrust TrustGate | OSS, Go, single static binary | Yes. Docker, Kubernetes or bare metal; on-prem with no external calls, air-gap capable | Yes, plus token rate limit, request size limits, semantic cache, MCP aggregation | Token rate limiting, not a USD cap | Not verified |
| Agent Router (formerly Envoy AI Gateway) | Apache 2.0. Agentic AI Foundation as of 2026-09-10 | Yes. Kubernetes-native, built on Envoy | Not advertised | Token-based rate limiting and quota-aware routing, no USD cap advertised | OpenTelemetry tracing with OpenInference compatibility, not the OTel gen_ai conventions |
| NVIDIA NeMo Guardrails | Apache 2.0 | Yes. Separate process or container beside vLLM, pointed at its OpenAI-compatible endpoint | Yes. Colang input and output rails | No | No |
| Guardrails AI | OSS plus Pro | Yes. Guard Server runs as a standalone HTTP service callable from any language | Yes | No | No |
| Arthur Engine | OSS, arthur-ai/arthur-engine | Yes | Yes. Real-time guardrails for PII, hallucination, prompt injection, toxicity | No | Monitoring |
| LLM Guard | MIT. ARCHIVED 2026-07-09 | Yes | Yes | No | No |
| kgateway | CNCF sandbox, Kubernetes Gateway API, originally Solo.io Gloo | Yes | Via the sibling agentgateway project; specifics not confirmed on the homepage | Not confirmed | Not confirmed |

---

## (b) Acquisition timeline, and what happened to the open source

| Date | Acquirer / target | Price | OSS fate |
|---|---|---|---|
| 2024-08-26 announced, Oct 2024 closed | Cisco / Robust Intelligence | Undisclosed | No significant OSS existed. Became Cisco AI Defense, announced Jan 2025, and Cisco Foundation AI |
| 2025-07-22 closed | Palo Alto / Protect AI | ~$700M reported, not verified here | Partly archived. llm-guard archived 2026-07-09, last update Jul 8 2026. rebuff archived, last touched 2024-08-07. Still public but stale: modelscan (Feb 18 2026), nbdefense (Feb 6 2025), vulnhuntr (Feb 6 2025), ai-exploits (Oct 23 2024). No fork found that picked up maintenance |
| 2025-08-05 agreed, 2025-09-05 closed | SentinelOne / Prompt Security | $159.3M fair value of total consideration per SentinelOne Form 10-Q. Press reported ~$250M | Kept alive. prompt-security/ps-fuzz (Prompt Fuzzer) still public, no archive banner found |
| 2025-09-11 announced, 2025-09-29 closed | F5 / CalypsoAI | $180M | None existed that I could identify. F5 launched AI Guardrails and AI Red Team on close |
| Sept 2025 | Cato Networks / Aim Security | ~$350M reported. Cato is private, no filing | None existed. Aim survives as a named guardrail integration in LiteLLM |
| Sept 2025 announced at Fal.Con, completed Sept 2025 | CrowdStrike / Pangea | ~$260M reported | None existed. Pangea survives as a named guardrail integration in LiteLLM |
| 2025-09-16 announced, Oct 2025 closed. XBRL tag in the filing reads 2025-10-22 | Check Point / Lakera | $187M net cash consideration, per Check Point Form 6-K exhibit filed 2025-12-02. The widely reported $300M is wrong | Kept alive and extended. Gandalf and the PINT prompt-injection benchmark continue. Lakera published a new open-source LLM-backend security benchmark on 2025-10-28, after the deal was announced |
| 2025 announced, close not verified | Tenable / Apex Security | >$105M reported, against $8.6M raised | None identified |
| 2026-05-29 closed | Palo Alto / Portkey | Undisclosed | Portkey was the leading independent AI gateway, described by Palo Alto as processing trillions of tokens per month. Folded into Prisma AIRS as a unified control plane |

### Two patterns

**The gateway layer and the security layer merged.** Palo Alto bought a content-security
company in July 2025 and a traffic-control company in May 2026. That combination is
precisely what guard-proxy implements in one component.

**OSS survival tracked whether the project was a funnel or a substitute.** Gandalf and
Prompt Fuzzer were lead generation and lived. LLM Guard and Rebuff competed with the
paid runtime product and were archived.

---

## (c) Verdict

**Served commercially for content, with a real and widening open-source gap at the
specific combination we built.**

1. **Nine acquisitions in roughly 24 months, seven inside a 13-month window** from
   2025-07-22 to 2026-05-29. The independent vendor category is being emptied.

2. **Spend enforcement and content enforcement live in different products.** Not one of
   the eleven commercial security vendors documents a hard USD cap. The three products
   that do enforce spend are gateways: Cloudflare AI Gateway, LiteLLM, and Portkey.
   Palo Alto buying Portkey in May 2026 is that convergence happening commercially.
   OWASP names the risk as LLM06 Unbounded Consumption, and the security vendors that
   map themselves to OWASP do not enforce against it.

3. **Self-hosting is the minority posture.** Of the commercial products, only Lakera
   Enterprise, Operant AI, and Cisco's on-prem data-plane gateway run inside your
   cluster, and Cisco still requires a SaaS control plane. Everything else is SaaS.

4. **The open-source floor dropped during the study window.** LLM Guard archived
   2026-07-09, Rebuff archived, and Guardrails AI reportedly ended hosted remote
   inferencing for OSS validators on 2026-08-06.

**Closest open-source analog: LiteLLM.** It self-hosts, enforces hard USD budgets in the
OSS tier, emits OTel, and supports blocking guardrails pre-call and post-call. Two
differences matter for the workshop. It requires Postgres for budgets to work at all.
And its guardrail catalog is largely a list of outbound calls to the SaaS APIs of the
companies in the acquisition table above, including Pangea, Aim, Cato, Lakera and
Pillar, so running LiteLLM with those enabled is not self-hosting the guardrail.

**Directly relevant to this repo.** The prompt-injection scanner this project depends on,
LLM Guard, was archived by its acquirer on 2026-07-09, twelve months after Palo Alto
completed the Protect AI deal. The code is MIT, still installs and still works, but
there will be no updates against new attack patterns. That is a genuine supply-chain
consideration for a security demo, and it is the consolidation story landing on our own
dependency list.

---

## (d) Standards and foundation efforts

| Effort | Produces | Specifics |
|---|---|---|
| OWASP GenAI Security Project | Taxonomy and guidance. No implementation | Top 10 for LLM, 2025 and 2026 editions. 2026 list: LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Excessive Agency, LLM04 Supply Chain, LLM05 Data and Model Poisoning, LLM06 Unbounded Consumption, LLM07 Misinformation, LLM08 Hidden Context Exposure, LLM09 Vector and Embedding Weaknesses, LLM10 Improper Output Handling. Unbounded Consumption was LLM10 in the 2025 list. Also publishes the AI Security Solutions Landscape guide |
| MITRE ATLAS | Taxonomy of adversary tactics and techniques. Referenced by Cisco and HiddenLayer mappings. NOT independently verified this session |
| CoSAI, an OASIS Open Project | Mostly taxonomy, with one piece of running code | Four workstreams: AI supply chain security, preparing defenders, AI risk governance, secure design patterns for agentic systems. MCP Security white paper and taxonomy, 2026-01-27. Agentic Identity and Access Management, and The Future of Agentic Security, following RSAC 2026 in May 2026. Cisco donated Project CodeGuard in Feb 2026, a model-agnostic secure-coding skills framework and ruleset, which is actual running code |
| AIUC | A certification scheme backed by insurance. Not a spec and not code | AIUC-1, developed with researchers from MIT, MITRE and Stanford. Six pillars: data and privacy, security, safety, reliability, accountability, society. Tests agent behavior against adversarial and operational scenarios, retested quarterly. Certified: ElevenLabs, UiPath, KPMG, Sierra |
| Linux Foundation / Agentic AI Foundation (AAIF) | Running code, plus one specification | AAIF formed Dec 2025. Hosts MCP, goose, AGENTS.md, A2A (backed by 150+ organizations), and Agent Router since 2026-09-10. Separately the LF took on TRACE in Aug 2026, a hardware-backed runtime attestation specification from AMD, Intel, Microsoft, OPAQUE and TII, binding runtime environment, software, policies, data classifications and tool usage into a portable verifiable artifact |
| CNCF | Running code | kgateway (sandbox project, Kubernetes Gateway API), agentgateway, OpenTelemetry (graduated), Falco, SPIFFE, Dapr. CNCF published a technical position in 2026 that agentic AI should be built on the existing cloud-native stack |
| OpenTelemetry GenAI semantic conventions | A specification, not yet stable | As of mid-July 2026 every gen_ai.* attribute, span, metric and event in the registry carries the "Development" stability badge; none is marked Stable. Moved out of the core semantic-conventions repo into a dedicated semantic-conventions-genai repo in v1.42.0 on 2026-06-12, with no tagged release as of 2026-07-16. Core attributes (operation name, provider, model, token usage) have been stable in shape since v1.37.0 |

### Do the foundations produce running code for runtime LLM guardrails?

**No. They produce running code adjacent to the problem, and stop short of the guardrail
function itself.**

- **AAIF** hosts Agent Router, which is real, Apache 2.0, Kubernetes-native running code
  for AI traffic. It does routing, provider auth, MCP gateway and authorization,
  token-based rate limiting, quota-aware routing, and tracing. It does **not** do prompt
  guards, content safety, or USD spend caps, and neither appears on its stated roadmap.
  **This is the sharpest data point available for the gap:** the one foundation-hosted,
  Kubernetes-native AI gateway shipped a 1.0 and joined a Linux Foundation body without
  the two controls guard-proxy exists to demonstrate.
- **CNCF** ships kgateway, agentgateway, OpenTelemetry, Falco and SPIFFE. That is
  transport, policy plumbing, telemetry, runtime detection and workload identity. No
  input prompt-injection scanning, no output secret-leak scanning, no spend cap.
- **Linux Foundation TRACE** is a specification for attesting what ran, not code that
  enforces what may run.
- **OWASP, MITRE ATLAS and AIUC** produce a taxonomy, a taxonomy, and a certification
  scheme respectively. None ships an implementation.

Net: the foundations cover transport, identity, attestation and telemetry. The guardrail
content layer and the spend layer are where they stop and the commercial vendors start.

---

## (e) Pricing, verified

| Vendor | What is published |
|---|---|
| Lakera | Community $0 per month, up to 10,000 requests per month, 8,000-token maximum prompt size. Enterprise is quote-only and is the tier that covers self-hosted and private-cloud deployment |
| Prisma AIRS | Token-based licensing introduced Feb 2026. Credit usage calculated in monthly tokens measured in billions, where one token equals four characters. Funded from Software NGFW (FW-Flex) credits. Otherwise quote-based |
| Cloudflare AI Gateway | The gateway itself is free. Chargeable: logs beyond quota, Logpush overage, guardrails billed as Workers AI token-based inference, and an optional 5% fee on credits purchased through Unified Billing. Workers Paid plan required for the 1,000,000-log tier. Spend limits capped at 20 rules per gateway |
| Operant AI | Usage-based, priced per service deployment inside a Kubernetes cluster |
| Guardrails AI Pro | ~$50,000 per 12 months, per an AWS Marketplace listing priced per user. Secondary source, not confirmed on Marketplace directly. The main marketing site publishes no rate as of Sept 2026 |
| LiteLLM, NeMo Guardrails, TrustGate, Agent Router, Arthur Engine, LLM Guard | Free and open source. LiteLLM and Guardrails AI have paid enterprise tiers |
| Quote-only, nothing published | HiddenLayer, Cisco AI Defense, SentinelOne, Cato, F5, CrowdStrike, Noma, Pillar, Zenity, Straiker, WitnessAI |

---

## (f) LiteLLM hard USD budgets, in detail

Sources, all fetched **2026-09-22**. These documentation pages are unversioned and carry
no publication date, so the fetch date is the only date I can attest.

- https://docs.litellm.ai/docs/proxy/users
- https://docs.litellm.ai/docs/proxy/virtual_keys
- https://docs.litellm.ai/docs/proxy/cost_tracking
- https://docs.litellm.ai/docs/proxy/provider_budget_routing

**Scopes in the open-source tier:** global proxy (max_budget in config), team, team
member, internal user, virtual key, customer/end-user, agent (tpm/rpm plus per-session
caps), and per-provider via router_settings.provider_budget_config with budget_limit and
time_period. All five scopes named in the brief (key, user, team, end-user, global) are
open source.

**Enterprise-only:** virtual key per-model budgets, internal user per-model budgets, and
tag budgets. Also enterprise, but reporting rather than enforcement: the
/global/spend/report endpoint and custom spend-log metadata.

**Enforcement is PRE-call, by reservation.** LiteLLM estimates the request's maximum cost
from the request body and the model cost map, reserves that amount against the applicable
budget, and rejects the request before sending it to the provider if the reservation would
exceed the budget. After the response arrives it replaces the reservation with the actual
cost. A breach surfaces at the authentication stage as:

    Authentication Error, ExceededTokenBudget: Current spend for token: 7.2e-05; Max Budget for Token: 2e-07

Team and end-user breaches surface as ExceededBudget variants. A provider-budget breach
returns HTTP 429 with "No deployments available - crossed budget for provider".

**Overshoot, and where the flag belongs.** The reservation design closes the concurrency
race, because parallel in-flight requests each reserve up front rather than all reading a
stale counter. **The documentation does not state a no-overshoot guarantee anywhere I
found, and the conclusion that a single request can still exceed the cap is my inference
from the documented mechanism, not a documented statement.** The mechanism admits
overshoot whenever actual cost lands above the pre-call estimate, for example when
max_tokens is unset, when reasoning tokens are billed, or when provider tier pricing is
only resolvable from response metadata.

**What Postgres stores.** Budgets do not function without it. LiteLLM_SpendLogs holds API
key hash, user, team ID, request tags, model, API base URL, spend in USD, prompt,
completion and total token counts, and metadata including fallback attempts and original
model group. LiteLLM_VerificationTokenTable, LiteLLM_UserTable and LiteLLM_TeamTable hold
the budget counters. Connection is via DATABASE_URL.

**Bedrock.** Budgets work with a Bedrock backend at the key, user, team, end-user and
global scopes. Cost tracking for Bedrock is explicitly documented, including automatic
Bedrock service-tier cost adjustment applied when the response includes tier metadata, and
budget enforcement runs off the same centralized model cost map, so it is provider
agnostic. Caveat: the provider-budget page gives no Bedrock example and states only that
provider names must be litellm provider names, so Bedrock at the provider-budget scope
specifically is unconfirmed.

---

## (g) Agent Router, formerly Envoy AI Gateway: confirmed

Announcement: https://theagentrouter.ai/blog/envoy-ai-gateway-is-now-agent-router
Post dated **2026-09-09**. Quoted text: "On 10 September, Agent Router, previously Envoy
AI Gateway, officially joins the Agentic AI Foundation." The two dates are the post date
and the effective date. Fetched 2026-09-22.

**What moved:** the product name; the repository to theagentrouter/agent-router, with
github.com/envoyproxy/ai-gateway redirecting; the website, with
aigateway.envoyproxy.io returning a 301 to theagentrouter.ai; and the community chat to a
new Agent Router Discord.

**What did not move:** "Same maintainers, same release cadence, same Apache 2.0 license."
The CRDs APIGatewayRoute, AIServiceBackend and BackendSecurityPolicy keep their names, as
does the aigateway.envoyproxy.io API group. The CLI stays aigw. The namespace stays
envoy-ai-gateway-system. "Envoy stays underneath." No migration is required.

**Features in 1.0** (release announcement dated 2026-06-23): one OpenAI-compatible API
across 16 providers; provider authentication via BackendSecurityPolicy covering API keys
and AWS, Azure and GCP identity; an MCP gateway with tool routing and authorization;
multimodal image, audio and video input; token-based rate limiting and quota-aware
routing; and token-aware metrics with OpenTelemetry tracing that is OpenInference
compatible, which is not the same thing as the OTel gen_ai semantic conventions.

**Prompt guards and spend controls: absent from the product and absent from the roadmap.**
The stated roadmap is a dedicated MCPBackend CRD, deeper MCP authorization across tools,
resources and prompts, fuller quota-aware routing that steers around rate-limited
providers, and expanded multimodal and provider translation. There is no dedicated roadmap
post; that list comes from the 1.0 announcement, which describes the roadmap as
community-driven.

---

## (h) Could not verify

- MITRE ATLAS. Not checked directly this session; referenced only through vendor mappings.
- Protect AI purchase price, reported at roughly $700M.
- Cato Networks / Aim Security at ~$350M. Cato is private and files nothing.
- CrowdStrike / Pangea at ~$260M, and the exact completion date. Press plus a CrowdStrike
  social post support "completed September 2025" but I did not confirm from CrowdStrike IR.
- Tenable / Apex Security: whether it closed, and on what date. Only the intent
  announcement and the >$105M press figure were verified.
- Alphabet / Wiz at $32B, finalized March 2026. Secondary blog only, and peripheral to
  the runtime-guardrail question.
- Guardrails AI Pro at ~$50,000 per 12 months, and the reported 2026-08-06 end of hosted
  remote inferencing for open-source validators. Both from secondary sources.
- The SaaS-only characterization of Noma, Pillar, Zenity, Straiker and WitnessAI. This
  came from a comparison blog rather than vendor documentation.
- **Whether Noma, Pillar, Zenity, Straiker, WitnessAI, HiddenLayer, Operant or Arthur have
  been acquired.** The session web-search budget was exhausted before an exhaustive sweep
  could run. Treat "still independent" as not-yet-contradicted rather than confirmed.
- F5 AI Guardrails in-cluster deployability.
- NeuralTrust TrustGate OpenTelemetry support.
- kgateway and agentgateway specifics for prompt guards, PII masking, token rate limiting
  and cost controls. The documentation URLs I tried returned 404 and the homepage does not
  detail them.
- OTel emission for most commercial vendors. A blank in the product table means
  undocumented, not proven absent.
- Prisma AIRS spend enforcement post-Portkey. The capability is plausible given what
  Portkey did independently, but no Palo Alto documentation confirms a USD cap.

### Corrections to assumptions in the original brief

- **LLM Guard was archived 2026-07-09, not 2026-07-08.** The GitHub banner reads
  "This repository was archived by the owner on Jul 9, 2026. It is now read-only."
  Jul 8 2026 is the last-updated date shown on the organization's repository listing.
- **Portkey is no longer an independent gateway.** Palo Alto Networks completed its
  acquisition on 2026-05-29 and is folding it into Prisma AIRS.
- **Envoy AI Gateway no longer exists under that name.** It became Agent Router under the
  Agentic AI Foundation effective 2026-09-10.
- **Check Point paid $187M for Lakera, not the widely reported $300M.** Source is Check
  Point's own Form 6-K exhibit filed 2025-12-02.
- **SentinelOne paid $159.3M for Prompt Security**, per its Form 10-Q, not the $250M in
  the announcement coverage.

---

## Sources

All fetched or searched 2026-09-22.

Acquisitions and filings
- https://www.paloaltonetworks.com/company/press/2025/palo-alto-networks-completes-acquisition-of-protect-ai
- https://www.paloaltonetworks.com/company/press/2026/palo-alto-networks-completes-acquisition-of-portkey-to-secure-ai-agents
- https://www.paloaltonetworks.com/company/press/2026/palo-alto-networks-to-acquire-portkey-to-secure-the-rise-of-ai-agents
- https://www.sec.gov/Archives/edgar/data/1015922/000117891325003986/exhibit_99-3.htm  (Check Point 6-K, Lakera $187M)
- https://www.sec.gov/Archives/edgar/data/1015922/000117891325003986/exhibit_99-2.htm  (XBRL tag dated 2025-10-22)
- https://www.checkpoint.com/press-releases/check-point-acquires-lakera-to-deliver-end-to-end-ai-security-for-enterprises/
- https://investors.sentinelone.com/press-releases/news-details/2025/SentinelOne-to-Acquire-Prompt-Security-to-Advance-GenAI-Security-and-Agent-Security-Strategy/default.aspx
- https://www.f5.com/company/news/press-releases/f5-to-acquire-calypsoai-to-bring-advanced-ai-guardrails-to-large-enterprises
- https://www.catonetworks.com/news/cato-acquires-aim-security-to-extend-sase-leadership-and-secure-enterprise-ai-transformation/
- https://www.crowdstrike.com/en-us/press-releases/crowdstrike-to-acquire-pangea-to-secure-every-layer-of-enterprise-ai/
- https://www.tenable.com/press-releases/tenable-announces-intent-to-acquire-apex-security-to-expand-exposure-management-across-the-ai-attack-surface
- https://blogs.cisco.com/news/fortifying-the-future-of-security-for-ai-cisco-announces-intent-to-acquire-robust-intelligence

Open-source project status
- https://github.com/protectai/llm-guard
- https://github.com/orgs/protectai/repositories?type=all
- https://github.com/prompt-security/ps-fuzz
- https://github.com/lakeraai/dsec-gandalf
- https://github.com/arthur-ai/arthur-engine
- https://github.com/NVIDIA-NeMo/Guardrails
- https://github.com/NeuralTrust/TrustGate
- https://github.com/envoyproxy/ai-gateway  (redirects to theagentrouter/agent-router)

Product documentation
- https://docs.lakera.ai/docs/deploy-to-k8s
- https://docs.lakera.ai/docs/selfhosting
- https://docs.lakera.ai/docs/gpu-support
- https://platform.lakera.ai/pricing
- https://docs.paloaltonetworks.com/ai-runtime-security/activation-and-onboarding/activate-your-ai-runtime-security-license
- https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/UCS_CVDs/AI_defense_on_Cisco_AI_PODs_reference_architecture.html
- https://www.globenewswire.com/news-release/2025/04/16/3062605/0/en/Operant-AI-Announces-AI-Gatekeeper-to-Supercharge-Runtime-Protection-for-AI-Agents-and-AI-Applications.html
- https://docs.datadoghq.com/security/ai_guard/
- https://hiddenlayer.com/aidr/
- https://developers.cloudflare.com/ai-gateway/features/spend-limits/
- https://developers.cloudflare.com/changelog/post/2026-06-05-spend-limits/
- https://developers.cloudflare.com/ai-gateway/reference/pricing/
- https://docs.litellm.ai/docs/proxy/users
- https://docs.litellm.ai/docs/proxy/virtual_keys
- https://docs.litellm.ai/docs/proxy/cost_tracking
- https://docs.litellm.ai/docs/proxy/provider_budget_routing
- https://docs.litellm.ai/docs/proxy/guardrails/quick_start
- https://theagentrouter.ai/docs/
- https://theagentrouter.ai/blog/envoy-ai-gateway-is-now-agent-router
- https://theagentrouter.ai/blog/v1.0-release-announcement
- https://kgateway.dev/

Standards and foundations
- https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/
- https://genai.owasp.org/llm-top-10/
- https://www.oasis-open.org/2026/01/27/coalition-for-secure-ai-releases-extensive-taxonomy-for-model-context-protocol-security/
- https://www.oasis-open.org/2026/05/06/coalition-for-secure-ai-unveils-new-agentic-identity-and-security-research-following-high-profile-sessions-at-rsac-2026/
- https://www.coalitionforsecureai.org/
- https://aiuc.com/
- https://www.helpnetsecurity.com/2026/08/26/the-linux-foundation-trace-ai-agent-security/
- https://www.cncf.io/blog/2026/03/23/cloud-native-agentic-standards/
- https://opentelemetry.io/blog/2026/genai-observability/
