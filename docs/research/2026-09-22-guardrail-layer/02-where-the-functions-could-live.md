# Where Could guard-proxy's Functions Live Instead? A Layer-by-Layer Map

Research date: **2026-09-22**. Every claim below is dated and carries the URL or command it came
from. Claims I could not verify are listed in their own section at the end and are also flagged
inline. Nothing here is stated from model memory.

The six functions under examination, as guard-proxy implements them today:

1. Input prompt-injection scanning
2. Output secret-leak scanning
3. Hard USD spend cap
4. Rate limiting
5. Fail-closed behavior
6. OpenTelemetry gen_ai telemetry

The distinction that governs the whole analysis is the repo's own, from
`docs/RUN-OF-SHOW-2026-08.md`: the split that matters is **developer-shipped** (inside the model or
the developer's container) versus **platform-injected** (deployed and controlled by the platform
team). A capability existing somewhere is not the same as the platform being able to compel it.

---

## 0. Headline correction to the repo's existing spike

`docs/spike-guardrail-layer-2026-09-21.md` states that the cost cap is "Not a gateway feature."
**That is wrong as of agentgateway v1.5.0.**

From the vendored schema at
`/home/michael/repos/talks/Unleash_an_Agent_Watch_It_Burn/verify/schemas/agentgateway-v1.5.0-config.json`:

```
BudgetLimitUnit:      enum ["USD", "Tokens"]
BudgetExceededAction: enum ["Audit", "Block"]
Budget.description:   "Usage is charged after an LLM response when the provider reports the
                       tokens or cost required by the configured unit. Requests with unavailable
                       usage are logged but cannot be charged or blocked retroactively."
```

`Budget` attaches to `LocalAPIKey`. Confirmed against the live docs
(<https://agentgateway.dev/docs/standalone/latest/documentation/llm/cost-controls/budget-limits/per-key.md>,
fetched 2026-09-22): USD or token caps, rolling epoch-aligned window, `Block` returns HTTP 429.

The limitation that survives the correction is the important part, and it is answered exactly in
Follow-up A below: the budget is charged after the response completes, so it blocks request N+1 and
never request N.

A second, larger correction arrives with LiteLLM in section 5.

---

## 0.5 Reconciliation: does agentgateway ship a local injection classifier?

Two agents on this task scored the same cell differently. The other agent scored agentgateway **Y**
on input injection scanning. I described its only self-hosted option as a webhook, a socket rather
than an implementation. **Both statements are correct under different readings of Y**, and the
disagreement is resolvable from the schema without ambiguity.

### The answer

**agentgateway v1.5.0 ships no local injection classifier of its own.** Its request guard is
limited to regex, plus a webhook socket, plus four remote services.

### The evidence

`RequestGuard` in `verify/schemas/agentgateway-v1.5.0-config.json` is a closed `oneOf` with exactly
six variants, and `unevaluatedProperties: false` means the list is exhaustive:

| Variant | Where the work happens | Is it an injection classifier? |
|---|---|---|
| `regex` (`RegexRules`) | **local**, in-process | **No.** Pattern matching, not classification |
| `webhook` (`Webhook`) | wherever you point it | **No.** A socket. You supply the classifier |
| `openAIModeration` | remote, OpenAI | **No.** 13 harm categories, no injection category |
| `bedrockGuardrails` | remote, AWS | **Yes**, via the `PROMPT_ATTACK` content filter |
| `googleModelArmor` | remote, Google | **Yes**, prompt injection and jailbreak detection |
| `azureContentSafety` | remote, Microsoft | **Yes**, `detectJailbreak` / `DetectJailbreakConfig` |

`ResponseGuard` has five variants, the same set minus `openAIModeration`.

The built-in `regex` patterns are five: `ssn`, `creditCard`, `phoneNumber`, `email`, `caSin`. Action
is `mask` or reject. Useful for secret-leak scanning. Not an injection detector by any reading.

### The negative, tested rather than assumed

Searching the entire 370,467-byte schema for local-classifier vocabulary:

```
'classifier': 0    'deberta': 0     'onnx': 0        'transformer': 0
'llm-guard': 0     'llmguard': 0    'model_path': 0  'local model': 0
'sentence': 0
```

Four terms did return hits, and **every one resolves to something unrelated**, which I checked
rather than waving at:

- **`jailbreak` (7)**: all inside `AzureContentSafety` and `DetectJailbreakConfig`, which configure
  the **remote** Microsoft service. Not a local capability.
- **`inject` (5)**: all fault-injection and credential injection. `FilterOrPolicy` ("Inject
  artificial latency before forwarding requests"), `DelayPolicy`, `BackendAuthCredential` ("An
  additional credential to inject on the backend request"), `LocalMcpAuthentication`.
- **`embedding` (3)**: `RouteType` `"OpenAI /embeddings"` and `ProviderFormat` `"embeddings"`. These
  are upstream route shapes, not a semantic-similarity guard. agentgateway has **no** equivalent of
  Kong's AI Semantic Prompt Guard.
- **`huggingface` (1)**: a `ProviderPreset`, meaning an upstream LLM backend you can route traffic
  **to**. Not a locally loaded model.

### Why both scores were defensible, and which one to use

- Read as *"can agentgateway enforce input injection scanning today?"* the answer is **yes**. Three
  of its four managed integrations do detect injection, and configuring one is a config change.
  That is the other agent's **Y**, and it is correct.
- Read as *"does agentgateway let you run injection scanning in your own cluster, without egress to
  a paid third party?"* the answer is **no**. The only self-hosted path is `webhook`, and the thing
  you point it at is the classifier you were trying to avoid running.

**For our decision the second reading is the operative one**, for two reasons specific to this
workshop. Challenge 1 puts the cluster under default-deny egress, so a remote guard is not merely a
cost, it is a policy violation that has already broken this stack once (issue #241, fixed by baking
the model into an offline image). And the whole thesis is about platform-injected controls, which a
per-request call to a vendor's paid API sits awkwardly inside.

So the honest matrix cell is **"Y, but only by calling out to a paid third party, or by pointing a
webhook at a classifier you run yourself."** The gateway supplies the **hook**, not the **judgment**.
That is the same shape as the ext_proc finding at the mesh layer in section 4, and it is the single
most repeated pattern in this whole report: several layers offer an excellent place to put an
injection guard, and none of them offer the guard.

This matters more, not less, because the most widely used open classifier for that socket was
archived on 2026-07-08. Full detail in section 11 under input injection scanning.

---

## 1. The OpenTelemetry gen_ai semantic conventions

### Where they now live

The conventions **moved out of the main semantic-conventions repo**. The old page at
<https://opentelemetry.io/docs/specs/semconv/gen-ai/> (fetched 2026-09-22) now carries only a
notice that they have been relocated and are no longer maintained there.

Current home: <https://github.com/open-telemetry/semantic-conventions-genai>

```bash
gh api repos/open-telemetry/semantic-conventions-genai \
   --jq '"created=\(.created_at) pushed=\(.pushed_at) stars=\(.stargazers_count)"'
# created=2026-05-05T03:08:44Z  pushed=2026-09-22T07:40:45Z  stars=386

gh api repos/open-telemetry/semantic-conventions-genai/tags --jq '.[0:8][] | .name'
# (empty: NO tags)

gh api repos/open-telemetry/semantic-conventions-genai/releases
# (empty: NO releases)
```

A four-month-old repository with no tagged release is carrying the vocabulary that every AI
observability vendor is aligning to.

### Stability status: Development, across the board

From `docs/gen-ai/gen-ai-spans.md` (1380 lines, fetched from `main` 2026-09-22):

```
line 7:  **Status**: [Development][DocumentStatus]
line 44: **Status:** ![Development](.../badge/-development-blue)
```

Every `gen_ai.*` attribute carries the `Development` badge. The only `Stable` badges in the
document belong to **borrowed core attributes** (`error.type`, `server.port`, `server.address`),
pinned to core semantic-conventions v1.44.0. Nothing gen_ai-specific is stable.

### What the 48 registry attributes cover

`model/gen-ai/registry.yaml` is 1053 lines and defines 48 attributes
(`grep -cE "^\s+- id:" registry.yaml` → 48). They group as:

| Group | Attributes |
|---|---|
| Operation identity | `gen_ai.operation.name` (**Required**), `gen_ai.provider.name` (**Required**) |
| Model identity | `gen_ai.request.model`, `gen_ai.response.model` |
| Sampling parameters | `temperature`, `top_p`, `top_k`, `max_tokens`, `seed`, `stop_sequences`, `frequency_penalty`, `presence_penalty`, `reasoning.level`, `request.stream`, `request.choice.count` |
| Conversation identity | `gen_ai.conversation.id`, `gen_ai.conversation.compacted` |
| Prompt-template identity | `gen_ai.prompt.name`, `gen_ai.prompt.version` |
| Output shape | `gen_ai.output.type` (`text`, `json`, `image`) |
| Token usage | see below |
| Content | see below |

### Token usage is deep and granular

All `Recommended`, all `Development`:

```
gen_ai.usage.input_tokens
gen_ai.usage.output_tokens
gen_ai.usage.reasoning.output_tokens
gen_ai.usage.cache_read.input_tokens
gen_ai.usage.cache_write.input_tokens
gen_ai.usage.text.input_tokens        gen_ai.usage.text.output_tokens
gen_ai.usage.text.cache_read.input_tokens
gen_ai.usage.image.input_tokens       gen_ai.usage.image.output_tokens
gen_ai.usage.image.cache_read.input_tokens
gen_ai.usage.audio.input_tokens       gen_ai.usage.audio.output_tokens
gen_ai.usage.audio.cache_read.input_tokens
```

The spec defines the nesting rules too, for example "[23] `gen_ai.usage.cache_read.input_tokens`:
The value SHOULD be included in `gen_ai.usage.input_tokens`."

### Content capture: Opt-In, type `any`

Three attributes carry prompt and completion content, all at requirement level **`Opt-In`**, the
weakest level in the specification, and all typed `any`:

```
gen_ai.input.messages        Opt-In   any   "The chat history provided to the model as an input."
gen_ai.output.messages       Opt-In   any   "Messages returned by the model where each message
                                             represents a specific model response."
gen_ai.system_instructions   Opt-In   any   "The system message or instructions provided to the
                                             GenAI model separately from the chat history."
```

The `model/gen-ai/` directory also carries JSON schemas for related payloads:

```
gen-ai-input-messages.json        gen-ai-output-messages.json
gen-ai-system-instructions.json   gen-ai-tool-call-arguments.json
gen-ai-tool-call-result.json      gen-ai-tool-definitions.json
gen-ai-retrieval-documents.json   gen-ai-memory-records.json
```

### Can a cost be derived from any metric? Only with a price table you supply

**The conventions define no cost, spend, USD, budget, or price attribute or metric anywhere.**
Verified with a grep proven to work on the same files:

```bash
curl -sL https://raw.githubusercontent.com/open-telemetry/semantic-conventions-genai/main/model/gen-ai/registry.yaml -o reg.yaml
curl -sL https://raw.githubusercontent.com/open-telemetry/semantic-conventions-genai/main/model/gen-ai/metrics.yaml  -o met.yaml

grep -ciE "token" reg.yaml                                          # 72   <- proves grep matches
grep -niE "cost|usd|spend|budget|price|dollar" reg.yaml met.yaml    # 0 hits
wc -l reg.yaml met.yaml                                             # 1053, 240
```

Cost is derivable arithmetically (tokens times your own price table) but is not observable as a
standard signal. **A spend cap cannot be expressed in OTel vocabulary at all.** Nothing in the
standard tells a collector what a token costs.

---

## 2. Layer 1: the model provider

### AWS Bedrock Guardrails

Source: <https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-how.html> (fetched 2026-09-22)

Policy types: content filters, denied topics, sensitive information filters, word filters, image
content filters. **No budget, no rate limit, no spend concept anywhere in the policy list.**

Evaluation order, quoted:

> The input is evaluated against the configured policies specified in the guardrail. Furthermore,
> for improved latency, the input is evaluated in parallel for each configured policy.
> If the input evaluation results in a guardrail intervention, a configured *blocked message*
> response is returned and the foundation model inference is discarded.

Billing, quoted:

> If a guardrail blocks the input prompt, you're charged for the guardrail evaluation. There are no
> charges for foundation model inference calls.
> If a guardrail blocks the model response, you're charged for guardrail's evaluation of the input
> prompt and the model response. In this case, you're charged for the foundation model inference
> calls, in addition to the model response that was generated before the guardrail's evaluation.

**So yes, Bedrock sees the request before inference is billed.** You still pay for the guardrail
evaluation itself on every request, blocked or not.

**Bedrock does detect prompt injection.** From the `ApplyGuardrail` API reference
(<https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html>,
fetched 2026-09-22), the `contentPolicy.filters` type enum is:

```
"type": "INSULTS | HATE | SEXUAL | VIOLENCE | MISCONDUCT | PROMPT_ATTACK"
"confidence":    "NONE" | "LOW" | "MEDIUM" | "HIGH"
"filterStrength":"NONE" | "LOW" | "MEDIUM" | "HIGH"
```

`PROMPT_ATTACK` is the injection filter.

Pricing: $0.15 per 1,000 text units (a text unit is up to 1,000 characters), per search results
citing <https://aws.amazon.com/bedrock/pricing/>. **Not directly fetched. See unverified list.**

### OpenAI moderation endpoint

Source: <https://developers.openai.com/api/docs/guides/moderation> (fetched 2026-09-22)

- **Free.** Quoted: "The moderation endpoint is free to use."
- Current model `omni-moderation-latest`, text and images.
- 13 categories: harassment, harassment/threatening, hate, hate/threatening, illicit,
  illicit/violent, self-harm, self-harm/intent, self-harm/instructions, sexual, sexual/minors,
  violence, violence/graphic.
- **No prompt-injection or jailbreak category.** The page does not address injection at all.

This is the significant negative: the one free managed moderation service does not cover the attack
class the workshop is about.

### Google Model Armor

Source: <https://docs.cloud.google.com/model-armor/overview> (fetched 2026-09-22)

- **GA**, with image screening in Preview.
- Detects: prompt injection and jailbreak, sensitive data (via Sensitive Data Protection),
  malicious URLs, responsible-AI categories (hate, harassment, dangerous, sexually explicit).
- Standalone REST API: `SanitizeUserPrompt` and `SanitizeModelResponse`.
- **No spend cap or budget capability documented.**

Pricing: $0.10 per million tokens after 2M free tokens per project per month, per search results.
**Not directly fetched. See unverified list.**

### Azure AI Content Safety / Prompt Shields

Source: <https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection>
(fetched 2026-09-22, page `ms.date` 2026-08-28, `updated_at` 2026-09-18)

- Detects **user prompt attacks** (direct injection and jailbreak) and **document attacks**
  (indirect injection in third-party content).
- Subtypes for user prompt attacks: attempt to change system rules, embedding a conversation
  mockup, role-play, encoding attacks.
- Subtypes for document attacks add: manipulated content, access to system infrastructure,
  information gathering, availability, fraud, malware.
- In Microsoft Foundry it attaches at intervention points: **user input** and **tool response**.
- **Spotlighting (Preview)**: base64-encodes documents to mark them lower-trust. Off by default,
  Chat Completions only. Its own doc notes it **increases** token count and so can increase model
  cost. A safety feature that raises the bill is worth naming on stage.
- **No spend cap.**

Pricing: the official page (<https://azure.microsoft.com/en-us/pricing/details/cognitive-services/content-safety/>,
fetched 2026-09-22) renders **`$- per 1,000 text records`**, an unpopulated placeholder. The free
F0 tier of **5,000 text records per month, including Prompt Shields**, is official and confirmed.
The $0.38 per 1,000 records figure circulating in third-party blogs is **unverified**.

### The provider-layer verdict on denial-of-wallet

Bedrock blocks before inference billing, and that is real. But it, Model Armor, Prompt Shields and
OpenAI moderation all block on **content policy, never on volume**. A benign prompt repeated ten
thousand times passes every one of them in full and bills every time. None of the four has a spend
cap, a budget, or a rate limit. Bedrock is the most honest case and it still charges a guardrail
evaluation fee for each request it blocks.

---

## 3. Layer 2: the API gateway / AI gateway

### agentgateway v1.5.0 (released 2026-08-27; v1.6.0-alpha.1 on 2026-09-14)

```bash
gh api repos/agentgateway/agentgateway --jq '"stars=\(.stargazers_count) pushed=\(.pushed_at)"'
# stars=4975  pushed=2026-09-22T08:36:14Z
```

Evidence is the vendored upstream schema for the exact image tag the repo runs,
`verify/schemas/agentgateway-v1.5.0-config.json` (370,467 bytes), plus the live docs.

**Prompt guards.**

| Hook | Variants |
|---|---|
| `promptGuard.request` | `regex`, `webhook`, `openAIModeration`, `bedrockGuardrails`, `googleModelArmor`, `azureContentSafety` |
| `promptGuard.response` | `regex`, `webhook`, `bedrockGuardrails`, `googleModelArmor`, `azureContentSafety` |

Built-in regex patterns are five: `ssn`, `creditCard`, `phoneNumber`, `email`, `caSin`. Action is
`mask` or reject. Inspection scope is `systemPrompt`, `messages`, `toolOutput`, `toolArgs`, which is
**wider than guard-proxy's**, since guard-proxy sees the prompt and completion but not tool
arguments or tool results.

**MCP guardrails.** `McpGuardrails` takes an ordered list of `Processor` entries; "the first to
reject a request short-circuits the chain," and processors may run request side, response side, or
both.

**Budget.** Attaches to `LocalAPIKey`, unit `USD` or `Tokens`, rolling epoch-aligned window,
`onBudgetExceeded` of `Audit` or `Block` (HTTP 429). Full mechanics in Follow-up A.
Documented constraints: USD budgets require a pricing catalog entry for every model the key uses or
they "charge nothing" with no error; a database configuration field is mandatory or budgets refuse
to operate; windows align to the Unix epoch, not to the key's first request.

**Rate limiting.** `RateLimitType` is `requests` or `tokens`, with local and global (remote)
backends and `RemoteRateLimitFailureMode`. A documented trap from
<https://agentgateway.dev/docs/kubernetes/latest/documentation/llm/cost-controls/budget-limits.md>
(fetched 2026-09-22): for **local** rate limiting "the `tokens` field is request count, not LLM
token count," limits apply "per agentgateway instance," and local limiting "only supports
`Seconds`, `Minutes`, and `Hours` units. For daily budgets, use global rate limiting."

**Telemetry.** Source:
<https://agentgateway.dev/docs/kubernetes/latest/documentation/observability/traces/attribute-reference.md>
(fetched 2026-09-22). It emits exactly six gen_ai attributes:

```
gen_ai.operation.name   gen_ai.provider.name
gen_ai.request.model    gen_ai.response.model
gen_ai.usage.input_tokens   gen_ai.usage.output_tokens
```

plus MCP attributes (`mcp.method.name`, `mcp.target`, `mcp.session.id`, `mcp.resource.type`,
`mcp.resource.uri`, `gen_ai.tool.name`, `mcp.error.code`, `mcp.error.message`). The docs state the
gen_ai attributes "follow the OTel semantic conventions for generative AI spans."

**No message content. No cost attribute.** So adopting agentgateway for telemetry loses the live
prompt feed.

### Agent Router, formerly Envoy AI Gateway

**The project was renamed.** Verified 2026-09-22:

```bash
gh api repos/envoyproxy/ai-gateway --jq '.full_name'
# theagentrouter/agent-router
gh api repos/envoyproxy/ai-gateway --jq '"stars=\(.stargazers_count) pushed=\(.pushed_at)"'
# stars=2129  pushed=2026-09-21T16:52:20Z
gh api repos/envoyproxy/ai-gateway/releases --jq '.[0:3][] | "\(.tag_name) \(.published_at)"'
# v1.1.0      2026-08-21T18:23:16Z
# v1.0.0      2026-06-23T15:32:39Z
# v0.7.0      2026-06-06T20:59:58Z
```

Its docs (<https://theagentrouter.ai/docs/latest/capabilities/observability/tracing/>, fetched
2026-09-22) state: "Formerly Envoy AI Gateway, now an Agentic AI Foundation project. Same code,
same maintainers."

Tracing: OpenInference conventions by default, which capture full request and response content.
GenAI conventions via `AI_GATEWAY_TRACING_SEMCONV=gen_ai`, with content **opt-in** behind
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`. The docs explain the opt-in as being
because content "routinely contains sensitive data." Message content is "currently mapped for chat
completions and Anthropic messages."

v1.1.0 added token counting across providers, per-request upstream credentials, stream idle timeout
with failover, MCP hostname routing, CEL backend selection, optional OpenTelemetry GenAI tracing,
and HTTP CONNECT egress. Token-based rate limiting is a documented capability.

**Prompt guards: not found in its docs.** Absence is not proven; see unverified list.

### Kong AI Gateway

See Follow-up B for the full answer. Summary: AI Gateway **2.0+** required for gen_ai OTel
attributes; it **does** emit `gen_ai.input.messages` and `gen_ai.output.messages`; the cost-capable
rate limiter is **Enterprise-only**.

### Gateway API Inference Extension

```bash
gh api repos/kubernetes-sigs/gateway-api-inference-extension/releases \
   --jq '.[0:4][] | "\(.tag_name) \(.published_at) prerelease=\(.prerelease)"'
# v1.6.2 2026-09-17T20:18:39Z  prerelease=false
# v1.6.1 2026-09-11T23:41:33Z  prerelease=false
# v1.6.0 2026-08-17T17:39:38Z  prerelease=false
# v1.5.0 2026-04-19T18:13:38Z  prerelease=false
```

Source: <https://gateway-api-inference-extension.sigs.k8s.io/> (fetched 2026-09-22). Scope is
routing and load balancing only. An `InferencePool` bundles an **Endpoint Picker (EPP)** that tracks
KV-cache utilization, queue length and active LoRA adapters and routes to the optimal replica.
**No content guards, no prompt scanning, no spend caps.**

One architecturally important detail: **the EPP MUST implement the Envoy external processing
(ext_proc) service protocol.** So the component does sit in the request-body path. Its job is simply
endpoint selection, not inspection. The hook exists; nobody is using it for guarding.

### kgateway, Higress, APISIX, Solo Gloo

```bash
gh api repos/kgateway-dev/kgateway --jq '"stars=\(.stargazers_count) pushed=\(.pushed_at)"'
# stars=5691  pushed=2026-09-22T04:52:05Z
# v2.4.5 2026-09-16T18:19:57Z
```

kgateway's documentation URLs returned HTTP 404 on two attempts (`kgateway.dev/docs/latest/ai/` and
`kgateway.dev/docs/ai/`). Higress, APISIX and Solo Gloo were **not examined this session**. See
unverified list.

---

## 4. Layer 3: service mesh and eBPF

### Istio

Source: <https://istio.io/latest/docs/reference/config/security/authorization-policy/> (fetched
2026-09-22).

An `AuthorizationPolicy` can match on:

| Category | Fields |
|---|---|
| Operation | `hosts`, `ports`, `methods`, `paths` (exact, prefix, suffix, URI template) |
| Request | headers, JWT claims |
| Source | `principals`, `requestPrincipals`, `namespaces`, `serviceAccounts`, `ipBlocks`, `remoteIpBlocks`, `trustDomains` |

**There is no ability to match on HTTP request or response body content.** Not in ambient mode, not
with a waypoint, not in sidecar mode. A waypoint runs a full Envoy and can enforce rich L7
authorization, but the policy language has no body primitive.

**The escape hatch is ext_proc, and it changes the answer.** The Envoy external processing filter
(<https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_proc_filter>)
routes headers, **bodies** and trailers to an external gRPC service, with `request_body_mode:
BUFFERED` capturing the full body. It reaches Istio through `EnvoyFilter`.

The precise statement for the talk: **the mesh can carry a body-inspecting filter, but it cannot be
one.** ext_proc is a socket. The thing on the other end that understands prompts, classifies
injection and counts dollars is a service you write. That service is guard-proxy wearing a different
deployment model.

### Cilium

Cilium's L7 policy can match HTTP methods, URL paths, request headers, gRPC calls expressed as HTTP
POST paths, and Kafka topics. It reconstructs enough of the request to evaluate those rules.
**HTTP request body payload inspection is not among its L7 primitives.** Sources: Cilium L7 policy
documentation and <https://docs.cilium.io/en/stable/observability/visibility/>. This is
documented-by-absence in the rule schema rather than by an explicit denial, so treat it as strong
but not quoted.

### Tetragon

Kernel and syscall-level events. It has no notion of an LLM request or response body. Note the repo's
own record: Tetragon was **retired from this stack on 2026-08-30**.

---

## 5. Layer 4: the serving layer

### vLLM v0.30.0 (released 2026-09-22)

```bash
gh api -X GET search/code -f q='repo:vllm-project/vllm guardrail' --jq '.total_count'   # 2
gh api -X GET search/code -f q='repo:vllm-project/vllm guardrail' --jq '.items[].path'
# vllm/models/inkling/amd/sconv_swa_attn.py
# vllm/models/inkling/nvidia/sconv_swa_attn.py
```

Both hits are attention-kernel files with unrelated variable naming. **vLLM ships no content
guardrails and no spend cap.** It does have resource budgets (reasoning-token limits, `max_tokens`,
context limits), which bound compute, not dollars and not content.

### KServe v0.20.0 (2026-08-06), v0.21.0-rc0 (2026-09-10)

```bash
gh api -X GET search/code -f q='repo:kserve/kserve guardrail' --jq '.items[].path'
# python/autogluonserver/README.md     (unrelated)
```

### Ray Serve

```bash
gh api -X GET search/code -f q='repo:ray-project/ray guardrail path:python/ray/llm' --jq '.total_count'
# 0
```

### llm-d v0.9.0 (2026-08-17)

```bash
gh api repos/llm-d/llm-d --jq '"stars=\(.stargazers_count) pushed=\(.pushed_at)"'
# stars=4619  pushed=2026-09-22T10:07:22Z
```

Built on the Gateway API Inference Extension and its EPP. Scope is inference performance.

### TGI

Not examined this session. See unverified list.

**Serving-layer verdict:** no content guards, no spend caps, anywhere. The serving boundary enforces
resource limits, which is a different function with a similar-sounding name.

---

## 6. LiteLLM: the proxy layer, and the one pre-call USD cap

This is the most consequential addition to the analysis, because it is the only implementation found
that enforces a dollar cap **before** the provider call.

```bash
gh api repos/BerriAI/litellm --jq '"stars=\(.stargazers_count) pushed=\(.pushed_at) license=\(.license.spdx_id)"'
# stars=59386  pushed=2026-09-22T11:39:43Z  license=NOASSERTION
gh api repos/BerriAI/litellm/releases --jq '.[0:3][] | "\(.tag_name) \(.published_at)"'
# v1.103.0-rc.1   2026-09-20T07:10:47Z
# v1.103.0-dev.2  2026-09-18T02:42:04Z
# v1.103.0-dev.1  2026-09-16T02:56:03Z
```

Its own GitHub description, read 2026-09-22: "The fastest, litest AI Gateway. Rust core with Python
SDK. Call 100+ LLM APIs in OpenAI (or native) format with cost tracking, guardrails, load balancing,
and logging."

### The budget mechanism, verified

Source: <https://docs.litellm.ai/docs/proxy/users> (fetched 2026-09-22). Quoted from the docs:

> LiteLLM estimates the request's maximum cost from the request body and the model's pricing.

> [It] temporarily reserves that amount against the applicable budget.

> [If the reservation would exceed the budget,] LiteLLM rejects the request before sending it to
> the provider.

> After the response is priced, LiteLLM replaces the reservation with the actual cost.

That is **reserve, gate, call, reconcile**. It is a genuinely different mechanism from
agentgateway's **check-accumulated, call, charge-after**, and it is the difference between a
tripwire and a ceiling.

The docs also carry the escape hatch and its warning: budget reservation **can be disabled** as a
temporary mitigation, and doing so "can allow concurrent requests to exceed a configured budget."
That sentence is itself evidence that reservation is what prevents concurrent overshoot.

### Which layer does LiteLLM belong to?

**It is a purpose-built LLM proxy, and that is the point, not a quibble.** LiteLLM is not a service
mesh, not a Kubernetes gateway implementation, not an agent framework, and not an observability
backend. It is a dedicated process that sits between the caller and the model endpoint and
understands LLM request semantics. Structurally it occupies **exactly the position guard-proxy
occupies**. It calls itself an "AI Gateway," and in the matrix below I place it in the gateway row
with that qualifier, because treating it as a distinct layer would be a naming distinction rather
than an architectural one.

The honest conclusion this forces: **the pre-call USD spend cap is not unownable. It is unowned by
every layer except a purpose-built LLM proxy, and LiteLLM is one.** The function has a natural home;
that home is the same shape as guard-proxy. The argument for guard-proxy's existence is therefore
not "nobody can do this," it is "only a component in this position can do this, and here is what it
costs to put one there."

One caveat: LiteLLM's GitHub license reports `NOASSERTION`, and LiteLLM ships an open core with a
paid enterprise tier. **Whether pre-call budget reservation is in the free tier or the enterprise
tier was not verified.** See unverified list. This matters a great deal to the recommendation and
should be closed before the claim is made from a stage.

---

## 7. Layer 5: the agent framework (developer-shipped unless a CRD makes it otherwise)

### kagent v1.0.0-alpha1 (2026-09-18), v0.10.1 (2026-09-08)

```bash
gh api repos/kagent-dev/kagent --jq '"stars=\(.stargazers_count) pushed=\(.pushed_at)"'
# stars=3812  pushed=2026-09-22T11:17:41Z
```

A code search for "guardrail" returns 14 hits, concentrated in Bedrock files. Reading the source
(fetched from `main` 2026-09-22):

`go/api/v1alpha3/modelconfig_types.go`:

```go
// +optional
Guardrail *BedrockGuardrailConfig `json:"guardrail,omitempty"`

type BedrockGuardrailConfig struct {
    // Identifier is the guardrail ID or full ARN.
    // +required
    Identifier string `json:"identifier"`
    // Version is the guardrail version: a numeric version (e.g. "1") or "DRAFT".
    // +required
    Version string `json:"version"`
}
```

`go/adk/pkg/models/bedrock.go`:

```go
func bedrockGuardrailConfig(c *BedrockConfig) *types.GuardrailConfiguration { ... }
func bedrockGuardrailStreamConfig(c *BedrockConfig) *types.GuardrailStreamConfiguration {
    ...
    StreamProcessingMode: types.GuardrailStreamProcessingModeSync,
}
// line 820: case types.StopReasonGuardrailIntervened, types.StopReasonContentFiltered:
```

**kagent has no native guardrail engine, no scanner, and no budget.** It passes a
`guardrailIdentifier` and version through to Bedrock's `Converse` and `ConverseStream`.

The interesting nuance: because the field lives in a **CRD**, a platform team that owns `ModelConfig`
resources can set it, and Kyverno can require it. This is the one agent-framework guard that is
**platform-settable rather than developer-shipped**. It buys nothing on any non-Bedrock model.

### OpenAI Agents SDK

Source: <https://openai.github.io/openai-agents-python/guardrails/> plus the repo's issue tracker.

Three guardrail types: input guardrails validate user prompts, output guardrails validate agent
responses, tool guardrails wrap function calls before and after execution. The mechanism is a
**tripwire**: a `@input_guardrail` decorator returning `GuardrailFunctionOutput` with
`tripwire_triggered`. With `run_in_parallel=False` the guardrail completes before the agent starts,
so a triggered tripwire "prevents token consumption and tool execution."

This is **developer-shipped**: decorators in application code, deployed with the app, invisible to
the platform, removable by the developer in one line.

And it is fragile in a way worth quoting on stage. Open issue **`openai/openai-agents-python` #4854:
"Guardrails fail open when tripwire_triggered is not a bool."** A guard that fails open on a type
error is the argument against the entire layer, filed by the framework's own users.

### LangChain/LangGraph callbacks, LlamaIndex, Google ADK, CrewAI, AutoGen, Semantic Kernel filters

All are in-process hooks in application code and are therefore **developer-shipped by construction**.
I did **not** verify each individually this session. See unverified list.

### MCP-level interception

agentgateway's `McpGuardrails` (ordered `Processor` chain, first-to-reject short-circuits, request
and response side) is verified from the schema. This is gateway-level MCP interception, and it is
platform-injected rather than developer-shipped.

---

## 8. Layer 6: admission and policy

Kyverno and OPA/Gatekeeper act at the Kubernetes API admission phase, after authentication and
authorization but **before the object is persisted**. They see Kubernetes objects. They never see
runtime LLM traffic, tokens, prompts, or dollars.

**Zero of the six functions are expressible as admission policy in their enforcement sense.**

What admission genuinely owns is the **guarantee that the enforcing component exists**:

- require the injection label or the sidecar on every matching Pod
- deny a Pod that lacks the proxy
- require a kagent `ModelConfig` to carry a `guardrail.identifier`
- constrain the guard image to a registry allow-list
- require resource limits

The repo already does this via its enforce-floor (registry allow-list plus limits). This is the
mechanism that converts "developer-shipped" into "platform-injected," and it is the single most
defensible cell in the whole matrix: admission is how you make a control non-optional, and nothing
else in Kubernetes can do that.

---

## 9. Layer 7: observability

| Project | Open source | Captures content | Enforces | gen_ai semconv |
|---|---|---|---|---|
| OTel gen_ai semconv | yes, the standard | defines `Opt-In` attributes | no | it is the convention |
| OpenLLMetry (Traceloop) | yes | yes, with a Privacy section for "Prompts, Completions and Embeddings" | **no**, described as "non-intrusive" | engages with GenAI conventions |
| Datadog LLM Observability | **no**, proprietary | yes, input and output on spans | **no**, detection only | yes, "natively supports OpenTelemetry GenAI Semantic Conventions" |
| Langfuse | not verified | not verified | not verified | not verified |

Datadog (<https://docs.datadoghq.com/llm_observability/>, fetched 2026-09-22) automatically scans
and redacts sensitive data and detects threats including prompt injection, but the documentation
frames this as **detection and visibility, not blocking**. Critically, its redaction protects the
**telemetry copy**, not the response delivered to the caller.

**Who is standardizing prompt and completion capture?** OpenTelemetry, at `Development` status, with
no tagged release, and at the weakest possible requirement level (`Opt-In`). Vendors are
implementing ahead of the standard: Kong emits the content attributes today, Agent Router emits them
behind an env var, Datadog aligns natively, and agentgateway emits none.

---

## 10. The function-by-layer matrix

Legend: **Y** shipping today, **P** partial or constrained, **N** not possible at that layer,
**(D)** developer-shipped rather than platform-injected. Open source unless marked ✕.

| | 1. Model provider | 2. Gateway / proxy | 3. Mesh + eBPF | 4. Serving | 5. Agent framework | 6. Admission | 7. Observability |
|---|---|---|---|---|---|---|---|
| **Input injection scan** | **Y** Bedrock `PROMPT_ATTACK`; Model Armor (GA); Azure Prompt Shields ✕. **N** OpenAI moderation (no injection category) | **Y\*** agentgateway, but **no local classifier**: regex is not a classifier, `webhook` is a socket, and the 3 managed integrations that do detect injection are all remote and paid. Kong AI Prompt Guard and Semantic Prompt Guard ✕. See section 0.5 | **N** no body primitive in policy; **P** only via ext_proc to an external service you write | **N** vLLM 0 real hits, KServe 0, Ray 0 | **P(D)** OpenAI Agents SDK tripwires; kagent only by delegating to Bedrock | **N** cannot see traffic | **P** Datadog detects, does not block ✕ |
| **Output secret-leak scan** | **Y** Bedrock sensitive-information filters; Model Armor SDP | **Y** agentgateway `promptGuard.response.regex` (5 built-ins) | **N** / **P** same ext_proc caveat | **N** | **P(D)** output guardrails | **N** | **P** redacts the telemetry copy only ✕ |
| **Hard USD spend cap** | **N** no provider guardrail has a budget | **Y (pre-call)** LiteLLM reservation; **P (post-hoc)** agentgateway per-key USD; **P** Kong cost strategy ✕ Enterprise | **N** | **N** vLLM reasoning-token budgets bound compute, not dollars | **N** | **N** | **N** no cost attribute exists in the standard |
| **Rate limiting** | **P** account-level quotas, not per-workload | **Y** agentgateway `requests\|tokens` local + global; Agent Router token limits; Kong ✕; LiteLLM TPM/RPM | **P** connection and request-rate only, token-blind | **N** | **N** | **N** | **N** |
| **Fail-closed** | **Y** inherent: block means no inference | **P** `RemoteRateLimitFailureMode` per policy; agentgateway budgets refuse to run without a DB | **P** fails closed on mTLS, blind to content | **N** | **P(D)** and demonstrably fragile, issue #4854 | **Y** the one thing admission does well | **N** |
| **OTel gen_ai spans** | **N** | **Y** agentgateway 6 attributes, no content, no cost; Agent Router content opt-in; Kong 2.0+ emits `input.messages` / `output.messages` ✕ | **N** HTTP spans only, no gen_ai | **P** token counts | **P(D)** SDK tracing | **N** | **Y** OpenLLMetry, Datadog ✕, and the standard itself |

---

## 11. Section (b): the strongest argument each way, per function

**Input injection scanning.**
*For moving to the gateway:* one enforcement point for every workload, expressed as config rather
than code, and a strictly wider inspection scope than a model-endpoint proxy has. agentgateway sees
`systemPrompt`, `messages`, `toolOutput` and `toolArgs`. Tool arguments and tool results are where
agentic injection actually lands, and a proxy on the model endpoint never sees them.
*Against:* the only self-hosted option is `webhook`, which is a socket, not an implementation. The
thing behind that socket is LLM Guard, which Protect AI **archived on 2026-07-08**
(`gh api repos/protectai/llm-guard` → `archived=true pushed=2026-07-08T23:58:40Z`, latest tag
v0.3.16, last functional commit 2025-09-03). The four turnkey options are all remote paid third
parties. The function relocates; the classifier problem does not.

**Output secret-leak scanning.**
*For:* genuinely covered. `promptGuard.response.regex` with the same sentinel patterns is a config
change, and this is the cleanest hand-off in the whole matrix.
*Against:* provider-side output filtering runs after inference, so the tokens that generated the
secret are already billed. Datadog's redaction protects the telemetry copy, not the response the
caller receives. And the gateway's five built-in patterns will not cover a workshop's planted
sentinels without custom patterns anyway.

**Hard USD spend cap.**
*For moving it out:* LiteLLM already does this correctly, pre-call, with reservation. If a dollar
ceiling is the requirement, a proxy that reserves before calling is strictly better than one that
charges after, and building it yourself repeats solved work.
*Against:* agentgateway's version is post-hoc, per-API-key, silently fail-open on a missing catalog
entry, and requires a database. Kong's is Enterprise-only. LiteLLM's tier split is unverified. So
"move it to the gateway" is correct only if the gateway is LiteLLM, which is itself a purpose-built
LLM proxy occupying the same position.

**Rate limiting.**
*For:* the least contested cell in the matrix. Token-aware limiting needs the token count, and the
gateway has it. `RateLimitType` is `requests` or `tokens` with local and global backends.
*Against:* gateway limits are per-route and, for local limiting, per-instance. An attacker fanning
across routes or landing on different replicas gets N times the budget. agentgateway's own docs warn
that the local limiter's `tokens` field is a request count, not an LLM token count, which is a trap
that reads as protection and is not.

**Fail-closed.**
*For admission owning the guarantee:* Kyverno can make the proxy's presence non-optional. No
framework guard can do that, and no gateway can guarantee traffic was not routed around it.
*Against framework-level:* `openai/openai-agents-python` issue #4854, "Guardrails fail open when
tripwire_triggered is not a bool." A developer-shipped guard that fails open on a type error is the
case against the layer, filed by the framework's own users.

**OTel gen_ai telemetry.**
*For moving out:* Kong 2.0+ emits full message content; Agent Router emits it behind an env var;
Datadog aligns natively. The instrumentation problem is being solved by people whose job it is.
*Against:* agentgateway emits six gen_ai attributes and no content at all, so a gateway-only
telemetry story loses the live prompt feed entirely. The convention is at `Development` status with
zero tagged releases, so anything built on it tracks a moving target and content capture is `Opt-In`
by design, meaning no implementer is obliged to provide it.

---

## 12. Section (c): which functions have no natural owner

This section is revised by the LiteLLM finding. The original claim was too strong.

**1. A hard USD spend cap enforced before the spend: one owner, and it is a purpose-built LLM proxy.**
Not the provider (no guardrail has a budget). Not the mesh, the serving layer, admission, or
observability (the standard has no word for cost). Among gateways, agentgateway's is post-hoc and
Kong's is Enterprise-only. **LiteLLM does it correctly, pre-call, by reserving the estimated maximum
cost and rejecting before the provider call.** LiteLLM is a dedicated LLM proxy, structurally the
same position as guard-proxy. So the accurate statement is: *this function has exactly one viable
home in the chain, and that home is a purpose-built proxy. The question is whether to write one or
adopt one.*

The deeper point survives intact and is the better thing to say on stage: **every managed guardrail
blocks on content policy, never on volume.** A benign prompt repeated ten thousand times passes
Bedrock, Model Armor, Prompt Shields and OpenAI moderation in full and bills every time. Denial of
wallet is not a content-safety problem, and the entire content-safety industry is aimed elsewhere.

**2. Platform-injected input scanning with a self-hosted classifier: no owner.** The gateway offers
a webhook, which is a socket. The most widely used open tool behind it (3,209 stars, 461 forks at
archive) was archived two months before this workshop runs. Every turnkey alternative is a remote
paid third party, which means egress from a default-deny cluster and a per-request fee.

**3. A live, room-visible prompt feed: no owner.** `STREAM_PROMPTS` has no equivalent anywhere.
Content capture is `Opt-In` in the standard, absent from agentgateway, env-var-gated in Agent Router,
and present in Kong only at 2.0+ and only in the Enterprise tier.

**A control that has to be compelled rather than chosen: only admission, and only for presence.**
All three provider guards are callable standalone against any model, so "the provider could own input
scanning" is true on capability. It is false on control. A standalone API is something the
application **chooses** to call, and nothing makes it call. That is developer-shipped by
construction, and it is the same gap issue #4854 demonstrates. The only layers that can compel are
the gateway (if all egress is genuinely forced through it) and admission (which compels the
component's presence but knows nothing about what it does).

---

## 13. Follow-up A: agentgateway budget behavior, answered exactly

Read from source: `agentgateway/crates/agentgateway/src/http/budget/mod.rs`, `main` branch, 769
lines, read 2026-09-22 via
`https://raw.githubusercontent.com/agentgateway/agentgateway/main/crates/agentgateway/src/http/budget/mod.rs`.
Related files located by code search: `budget/status.rs`, `budget/database.rs`,
`crates/agentgateway/src/http/apikey.rs`, `crates/llm/src/model_catalog.rs`,
`crates/agentgateway/tests/tests/llm.rs`.

The order of operations is **check, serve, charge**.

### The check, at admission

Doc comment, line 420:

> Refreshes each matched counter before a request, logs exceeded budgets, and returns the first
> exceeded budget configured to block. Audit-only budgets never block the request.

The comparison itself, line 442:

```rust
let exceeded = used >= budget.limit.amount.decimal();
```

`used` is the **already-accumulated counter**. Nothing about the in-flight request enters the
comparison: not its prompt size, not its `max_tokens`, not its model's price. There is no estimate
and no reservation.

### Question 1: the first request, when no usage has been recorded

`used` is 0, or a preloaded database row. For any non-zero limit, `0 >= limit` is **false**, so the
request is **admitted unconditionally**, no matter how expensive it will turn out to be. The first
request against a fresh key can never be blocked by a budget.

### Question 2: can a single request exceed the cap by an unbounded amount?

**Yes. Unbounded.** The cap is a tripwire on accumulated history, not a ceiling on the current
request. With a $1 cap and a single request costing $400 (maximum context, maximum output, most
expensive model), you are billed $400 and blocked starting at request two.

Worst-case overshoot is the full cost of one maximally expensive call, **multiplied by replica
count**. Counters are per-instance in memory with deferred database flushes (`counter.pending`, a
flush mutex described at line 269 as serializing "periodic, shutdown, and manually requested
flushes"). N replicas each admit one overshooting request before any of them observes the charge.

### Question 3: when the provider does not report usage

`settle()`, line 482:

```rust
let charged = match budget.limit.unit {
    BudgetLimitUnit::Usd    => response.cost.as_ref().map(|cost| cost.total()),
    BudgetLimitUnit::Tokens => response.total_tokens.map(Decimal::from),
};
let Some(charged) = charged else {
    tracing::debug!(
        target: "budget",
        api_key = budgets.api_key,
        budget = budget.name,
        limit_unit = budget.limit.unit.as_str(),
        "API key budget could not be charged because usage was unavailable"
    );
    continue;
};
```

`continue` skips the counter increment entirely. The counter never advances, so `check()` never
trips, so spend is **unbounded and permanent**, not merely delayed. The only signal is a
**`tracing::debug!`** line. Not `warn!`. Not `error!`. On a default log level it is invisible.

This path fires in two distinct situations:

1. The provider omits usage reporting on the response.
2. A **USD** budget's model is missing from the pricing catalog, because `response.cost` is then
   `None`. The per-key documentation confirms this independently: a USD budget without a catalog
   entry for a model "charges nothing" and reports no error.

Compare the successful path, which does emit a log, also at `debug!`:

```rust
counter.refresh(now);
counter.amount  += charged;
counter.pending += charged;
counter.updated_at = now;
```

And note the documented caveat about cached tokens from
<https://agentgateway.dev/docs/kubernetes/latest/documentation/llm/cost-controls/budget-limits.md>:
"a cache-heavy request against those providers debits more than their reported input count."

### Verdict, and the contrast that decides the call

agentgateway's budget is a **post-incident circuit breaker**, not a spend ceiling. It answers "stop
the bleeding tomorrow," never "do not let this request cost more than $0.10." Against denial of
wallet it bounds the number of expensive requests to one per replica per window, and to no bound at
all when usage reporting is absent or the pricing catalog is incomplete.

Side by side, on the three questions that matter:

| | agentgateway v1.5.0 | LiteLLM |
|---|---|---|
| Mechanism | check accumulated, serve, charge after | **estimate max cost, reserve, gate, call, reconcile** |
| First request against a fresh budget | always admitted, `0 >= limit` is false | **gated**, the reservation is checked before the provider call |
| Single-request overshoot | **unbounded**, the full cost of one maximal call | bounded by the estimate, which is computed from the request body and the model's pricing |
| Provider reports no usage | counter never advances, spend is unbounded and permanent, `debug!` only | the reservation was already taken before the call |
| Concurrency | per-instance counters with deferred flushes, so N replicas each admit one overshoot | reservation is what prevents concurrent overshoot, per its own docs |
| Evidence | `budget/mod.rs` lines 420, 442, 482, read 2026-09-22 | <https://docs.litellm.ai/docs/proxy/users>, fetched 2026-09-22 |

LiteLLM's own escape-hatch warning is the clearest confirmation that the mechanism is what does the
work: reservation can be disabled, and disabling it "can allow concurrent requests to exceed a
configured budget."

**LiteLLM's reserve-then-gate is the correct shape for this function. agentgateway's is not.** If a
hard dollar ceiling is a requirement rather than a preference, agentgateway's budget does not
satisfy it at any configuration, and no amount of tuning the window or the limit changes that,
because the defect is in the order of operations rather than in the parameters.

The one open item before acting on this is LiteLLM's tier placement, listed first in section 16.

---

## 14. Follow-up B: Kong

**Version.** AI Gateway **2.0 or higher** is required for the gen_ai OpenTelemetry attributes, per
<https://developer.konghq.com/ai-gateway/llm-open-telemetry/> (fetched 2026-09-22). The current
architecture is **AI Gateway 2.x**, an entity-based model that replaced the v1 plugin-centric one
(<https://developer.konghq.com/ai-gateway/>, fetched 2026-09-22).

**Content capture: yes, and Kong says so plainly.** Kong emits `gen_ai.input.messages` and
`gen_ai.output.messages`, with this warning quoted from the page:

> gen_ai.input.messages and gen_ai.output.messages may contain prompts, model outputs, PII, secrets,
> or credentials.

The page directs you to review "tracing, retention, access-control, and redaction requirements
before enabling or exporting payload-related tracing data." The word "enabling" implies opt-in, but
**I did not find the specific flag that gates it**, so treat opt-in as probable rather than
confirmed. Kong also emits request details (operation name, provider, model, max tokens,
temperature), response metadata (response id, model name, finish reasons), token usage, and tool-call
attributes.

**OSS versus Enterprise: Enterprise.** From
<https://developer.konghq.com/plugins/ai-rate-limiting-advanced/> (fetched 2026-09-22), quoted
verbatim:

> **AI Gateway Enterprise:** This plugin is only available as part of our AI Gateway Enterprise
> offering.

The AI Gateway overview assumes a Konnect deployment throughout ("managed through Konnect with data
planes running in your environment") and never describes an OSS path. The overview page does **not**
enumerate tiers for AI Prompt Guard, AI Semantic Prompt Guard, or LLM OpenTelemetry tracing
individually, so their exact tier placement is unverified; only the rate limiter is confirmed
Enterprise.

**Does Kong OSS enforce a USD spend cap? No.** Cost-based limiting exists and it is that same
Enterprise plugin. The `cost` strategy (v3.8+) computes:

```
(prompt_tokens × input_cost + completion_tokens × output_cost) / 1,000,000
```

with costs defined per 1 million tokens "in whatever unit suits your use case, whether US dollars,
cents, or internal billing credits."

**The comparison that matters.** Kong's cost cap is richer than agentgateway's and is licensed.
agentgateway's is free and post-hoc. LiteLLM's is pre-call, and its tier is unverified. As of
2026-09-22 I found **no confirmed free, open-source, pre-call USD ceiling** other than LiteLLM's,
whose tier placement is the open question.

---

## 15. Follow-up C: can each provider guard traffic bound for a different vendor's model?

**All three: yes.**

### AWS Bedrock Guardrails: yes, explicitly

Source: <https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html>
(fetched 2026-09-22). Quoted:

> You can use the `ApplyGuardrail` API to assess any text using your pre-configured Amazon Bedrock
> Guardrails, without invoking the foundation models.

> **Decoupled from foundation models**: `ApplyGuardrail` API is decoupled from foundational models.
> You can now use Guardrails without invoking Foundation Models.

> **Flexible deployment**: You can integrate the `ApplyGuardrail` API anywhere in your application
> flow to validate data before processing or serving results to the user.

The call shape:

```
POST /guardrail/{guardrailIdentifier}/version/{guardrailVersion}/apply
{ "source": "INPUT" | "OUTPUT", "content": [{ "text": { "text": "string" } }] }
```

Response returns `action: "GUARDRAIL_INTERVENED" | "NONE"`, per-policy `assessments`, and a `usage`
block of policy units processed (`topicPolicyUnits`, `contentPolicyUnits`, `wordPolicyUnits`,
`sensitiveInformationPolicyUnits`, `sensitiveInformationPolicyFreeUnits`,
`contextualGroundingPolicyUnits`). `outputScope: FULL` returns non-detected entries too, though it
does not apply to word filters or sensitive-information regexes.

### Google Model Armor: yes, and multicloud is the stated design

Source: <https://docs.cloud.google.com/model-armor/overview> (fetched 2026-09-22). Quoted:

> Whether you are deploying AI in Google Cloud or other cloud providers, Model Armor can help you
> prevent malicious input, verify content safety, protect sensitive data, maintain compliance, and
> enforce your AI safety and security policies consistently across your AI applications.

Two paths exist: the standalone REST API (`SanitizeUserPrompt`, `SanitizeModelResponse`) and
integrations including Vertex AI, Apigee, LangChain, and Agent Gateway. GA, with image screening in
Preview. The docs describe the service generically as protecting "an LLM" and do **not** name
specific third-party vendors, so "supports OpenAI and Anthropic specifically" is inference, not
quotation.

### Azure Prompt Shields: yes, via the standalone Content Safety API

Source: <https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection>
(fetched 2026-09-22). The page distinguishes two configuration paths. Inside Microsoft Foundry,
Prompt Shields attaches to model deployments and agents at defined intervention points. Separately,
quoted:

> The standalone Azure AI Content Safety API analyzes a `userPrompt` and up to five `documents`. The
> response reports `attackDetected` for the prompt and each document.

That call is text in, verdict out, with no model binding, so it guards traffic to anything.

### The consequence for the thesis

All three are callable standalone against any model, so "the provider could own input scanning" is
**true on capability and false on control**. A standalone API is something the application **chooses**
to call, and nothing compels it. That is developer-shipped by construction, and it is the same gap
issue #4854 demonstrates in a different costume. The only layers that can compel the call are a
proxy or gateway that all traffic is forced through, and admission, which can compel the proxy's
presence. None of the three providers can compel anything, and none of them can cap a dollar.

---

## 16. What I could not verify

Listed plainly. Anything here should not be asserted from a stage without closing it first.

**Pricing**

- **Azure Prompt Shields per-unit price.** Microsoft's own pricing page renders `$- per 1,000 text
  records`, an unpopulated placeholder, and directs users to the pricing calculator or a sales quote.
  The **$0.38 per 1,000 records** figure comes from third-party blogs only. The **F0 free tier of
  5,000 text records per month including Prompt Shields is official and confirmed.**
- **Bedrock $0.15 per 1,000 text units** and **Model Armor $0.10 per million tokens after 2M free
  per project per month**: taken from search summaries that cited the vendor pricing pages. I did not
  fetch `aws.amazon.com/bedrock/pricing` or Google's pricing page directly.

**LiteLLM**

- **Whether pre-call budget reservation is in the free open-source tier or the paid enterprise
  tier.** GitHub reports the license as `NOASSERTION`; LiteLLM ships an open core with a commercial
  enterprise offering. This is the single most decision-relevant open item in the report.

**Gateways not examined**

- **kgateway**: documentation URLs returned HTTP 404 twice (`/docs/latest/ai/` and `/docs/ai/`).
  Only v2.4.5 (2026-09-16), 5,691 stars established, via the GitHub API.
- **Higress, APISIX, Solo Gloo**: not examined at all this session.
- **Agent Router prompt guards**: searches returned nothing on this topic. **Absence is not proven.**
- **Kong tier placement** for AI Prompt Guard, AI Semantic Prompt Guard, and LLM OpenTelemetry
  tracing individually. Only AI Rate Limiting Advanced is confirmed Enterprise.
- **Kong content-capture opt-in flag**: the warning wording implies opt-in; I did not find the flag.

**Frameworks and backends not examined**

- **LangChain/LangGraph callbacks, LlamaIndex, Google ADK, CrewAI, AutoGen, Semantic Kernel filters,
  Langfuse, TGI.** Their developer-shipped character follows from being in-process hooks in
  application code, but I did not read their documentation this session.

**Method limitations**

- The **vLLM, KServe and Ray Serve negatives** rest on single GitHub code-search queries executed
  before the API rate-limited me (`gh api rate_limit` showed the code-search bucket at 10 per minute).
  The vLLM result is the strongest of the three: both "guardrail" hits resolve to
  `vllm/models/inkling/{amd,nvidia}/sconv_swa_attn.py`, attention kernels with unrelated variable
  naming. KServe's single hit is an unrelated autogluon README. Ray returned zero.
- The **Cilium body-inspection negative** is documented-by-absence in its L7 rule schema rather than
  an explicit vendor denial.
- **WebSearch budget was exhausted at 50 of 50 calls** partway through this session. Everything after
  that point was verified via WebFetch against primary documentation and the GitHub API, which is a
  stronger method, but it means some breadth questions (Higress, APISIX, Gloo) went unasked rather
  than being asked and answered negatively.

---

## 17. Source index, with fetch dates

All fetched or executed **2026-09-22**.

| Source | URL or command |
|---|---|
| Bedrock Guardrails mechanics and billing | <https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-how.html> |
| Bedrock ApplyGuardrail API | <https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-independent-api.html> |
| OpenAI moderation guide | <https://developers.openai.com/api/docs/guides/moderation> |
| Google Model Armor overview | <https://docs.cloud.google.com/model-armor/overview> |
| Azure Prompt Shields concepts | <https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection> |
| Azure Content Safety pricing | <https://azure.microsoft.com/en-us/pricing/details/cognitive-services/content-safety/> |
| OTel GenAI semconv repo | <https://github.com/open-telemetry/semantic-conventions-genai> |
| OTel gen_ai spans spec | <https://raw.githubusercontent.com/open-telemetry/semantic-conventions-genai/main/docs/gen-ai/gen-ai-spans.md> |
| OTel gen_ai registry and metrics | `.../main/model/gen-ai/registry.yaml`, `.../model/gen-ai/metrics.yaml` |
| OTel relocation notice | <https://opentelemetry.io/docs/specs/semconv/gen-ai/> |
| agentgateway doc index | <https://agentgateway.dev/docs/llms.txt> |
| agentgateway per-key budgets | <https://agentgateway.dev/docs/standalone/latest/documentation/llm/cost-controls/budget-limits/per-key.md> |
| agentgateway budget limits | <https://agentgateway.dev/docs/kubernetes/latest/documentation/llm/cost-controls/budget-limits.md> |
| agentgateway span attributes | <https://agentgateway.dev/docs/kubernetes/latest/documentation/observability/traces/attribute-reference.md> |
| agentgateway budget source | <https://raw.githubusercontent.com/agentgateway/agentgateway/main/crates/agentgateway/src/http/budget/mod.rs> |
| agentgateway vendored schema | `verify/schemas/agentgateway-v1.5.0-config.json` (in-repo) |
| Agent Router tracing | <https://theagentrouter.ai/docs/latest/capabilities/observability/tracing/> |
| Agent Router rename | `gh api repos/envoyproxy/ai-gateway --jq '.full_name'` → `theagentrouter/agent-router` |
| Kong gen_ai OTel attributes | <https://developer.konghq.com/ai-gateway/llm-open-telemetry/> |
| Kong AI Gateway overview | <https://developer.konghq.com/ai-gateway/> |
| Kong AI Rate Limiting Advanced | <https://developer.konghq.com/plugins/ai-rate-limiting-advanced/> |
| LiteLLM budgets | <https://docs.litellm.ai/docs/proxy/users> |
| LiteLLM repo facts | `gh api repos/BerriAI/litellm` |
| Istio AuthorizationPolicy reference | <https://istio.io/latest/docs/reference/config/security/authorization-policy/> |
| Envoy ext_proc filter | <https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_proc_filter> |
| Cilium L7 visibility | <https://docs.cilium.io/en/stable/observability/visibility/> |
| Gateway API Inference Extension | <https://gateway-api-inference-extension.sigs.k8s.io/> |
| OpenAI Agents SDK guardrails | <https://openai.github.io/openai-agents-python/guardrails/> |
| OpenAI Agents SDK fail-open issue | <https://github.com/openai/openai-agents-python/issues/4854> |
| kagent Bedrock guardrail source | `.../kagent-dev/kagent/main/go/adk/pkg/models/bedrock.go`, `.../go/api/v1alpha3/modelconfig_types.go` |
| LLM Guard archive status | `gh api repos/protectai/llm-guard` → `archived=true pushed=2026-07-08T23:58:40Z` |
| OpenLLMetry | <https://www.traceloop.com/docs/openllmetry/introduction> |
| Datadog LLM Observability | <https://docs.datadoghq.com/llm_observability/> |
| Kyverno admission model | <https://kyverno.io/docs/introduction/how-kyverno-works/> |

Release states read from the GitHub API on 2026-09-22: agentgateway v1.5.0 (2026-08-27) and
v1.6.0-alpha.1 (2026-09-14); Agent Router v1.1.0 (2026-08-21); Gateway API Inference Extension
v1.6.2 (2026-09-17); kgateway v2.4.5 (2026-09-16); kagent v1.0.0-alpha1 (2026-09-18) and v0.10.1
(2026-09-08); llm-d v0.9.0 (2026-08-17); vLLM v0.30.0 (2026-09-22); KServe v0.20.0 (2026-08-06) and
v0.21.0-rc0 (2026-09-10); LiteLLM v1.103.0-rc.1 (2026-09-20).
