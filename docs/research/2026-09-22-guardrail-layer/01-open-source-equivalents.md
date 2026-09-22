# Is guard-proxy's job served by open source?

Research report, verified 2026-09-22 against the GitHub API, project config schemas, vendor
documentation, PyPI, and the HuggingFace API. Every version, date, and status below comes from a
live source, cited inline. Items I could not verify are marked `?` and collected in the final
section rather than guessed at.

One constraint on method: this session's WebSearch budget was already exhausted (50/50) before the
research began, so nothing here comes from a search-result summary. Everything is a direct fetch of
a document, a schema, a registry record, or a repository.

Two findings supplied by other agents on the team are folded in and independently corroborated
where noted, rather than re-derived from scratch:

1. LiteLLM enforces hard USD budgets in the OSS tier, pre-call, by reservation.
2. agentgateway v1.5.0 has USD and token budgets on an API key, charged post-hoc.

---

## The question, answered plainly

> Is there any open-source project that does BOTH content guards AND pre-call spend enforcement AND
> emits OTel gen_ai spans, or does every candidate miss at least one?

**Yes. One project clears all three: LiteLLM.** It is the only candidate of the 26 examined that
does input and output content guards, pre-call USD spend enforcement, and OpenTelemetry gen_ai
spans carrying message content, all in a self-hosted process under an OSS license.

Every other candidate misses at least one leg:

| Candidate | Content guards | Pre-call spend | OTel gen_ai | Misses |
|---|---|---|---|---|
| **LiteLLM** | yes | **yes (reservation)** | yes | nothing in this triad |
| agentgateway | yes | post-hoc only | yes | pre-call enforcement |
| Kong AI Gateway | yes | Enterprise only | yes | OSS spend cap |
| Bifrost | enterprise/unverified | post-hoc | yes | verified OSS guards |
| Higress | Alibaba Cloud only | no | partial | spend, self-hosted detection |
| NeMo Guardrails | yes | no | no | spend, telemetry |
| Guardrails AI | yes | no | unverified | spend, telemetry |
| Portkey Gateway | yes | partial | Enterprise | OSS telemetry |
| TrustGate | no | no | partial | guards, spend |
| Agent Router | no | quota only | unverified | guards |

So a combination is **not** required for the triad. It is required only for the eighth function,
the live prompt feed, which no project in the ecosystem provides.

---

## The verdict, stated directly

**The core of guard-proxy's job was served by a single open-source project before guard-proxy was
written, and that project is LiteLLM.**

The dates are the argument, and they are unambiguous:

| Event | Date | Source |
|---|---|---|
| LiteLLM pre-call budget reservation first commit | **2026-04-30** | `git log` on `litellm/proxy/spend_tracking/budget_reservation.py` via GitHub API |
| **guard-proxy first commit in this repo** | **2026-06-17** | `git log --reverse -- '*guard-proxy*'`, commit "Add A2A guard proxy (real output/input inspection point)" |
| agentgateway API-key scoped budgets (#3143) | 2026-08-25 | commit history on `schema/config.json` |

LiteLLM had pre-call USD spend enforcement seven weeks before guard-proxy's first commit, and had
had the guardrail framework and multi-provider routing for far longer. This is not a case of the
ecosystem catching up afterward. The capability was there.

That said, three qualifications are real and should not be dropped when this is repeated:

**One.** The eighth function, streaming prompts live to a feed the room watches, has no open-source
precedent anywhere in the 26 projects examined. It is workshop apparatus, not a product category,
and it was always going to be bespoke.

**Two.** I verified the *date* on LiteLLM's budget reservation. I did **not** date-verify when
LiteLLM's `gen_ai` semantic-convention OTel emission landed. It exists today. Whether it existed on
2026-06-17 is unverified, and that one leg of the triad therefore carries an unknown as of
guard-proxy's build date.

**Three.** LiteLLM would have imposed a Postgres dependency and a Python sidecar on a per-cluster
workshop fleet, and its guardrail-unreachable semantics are undocumented (see function 6 below).
Those are legitimate engineering reasons to have built something smaller and fully controlled. They
are reasons that hold up; "nothing like this existed" is not one.

**Honest framing for a talk.** The defensible claim is not that this was unserved. It is that the
*combination* is rare, that the spend-cap half of it is rare, and that the two ecosystems, content
guardrails and cost control, are almost entirely disjoint. That claim survives scrutiny. The
stronger claim does not.

---

## (a) Coverage matrix

Functions: **1** input scan · **2** output scan · **3** USD spend cap · **4** rate limit ·
**5** model tier switch · **6** fail closed · **7** OTel gen_ai with message content ·
**8** live prompt feed

`Y` yes · `N` no · `E` enterprise/paid only · `~` partial · `?` unverified

| Project | Type | License | Latest / last commit | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LiteLLM** | proxy | MIT + proprietary `enterprise/` | v1.101.0 2026-09-15 | Y | Y | **Y pre-call** | Y | Y | ~ | Y | N |
| **agentgateway** | proxy | Apache-2.0 | v1.5.0 2026-08-27 / 2026-09-22 | Y | Y | **Y post-hoc** | Y | Y | **Y** | Y | N |
| **Bifrost** (Maxim) | proxy | Apache-2.0 | framework/v1.7.2 2026-09-18 | ?E | ?E | Y | Y | Y | ? | Y | N |
| **Kong AI Gateway** | gateway | mixed OSS/EE | current | Y | Y | **E** | Y | Y | ? | Y | N |
| **Higress** | gateway | Apache-2.0 | v2.2.4 2026-08-13 | ~ | ~ | N | Y | Y | ? | ~ | N |
| **Agent Router** (ex-Envoy AI GW) | gateway | Apache-2.0 | v1.1.0 2026-08-21 | N | N | ~ | Y | Y | ? | ? | N |
| **TrustGate** (NeuralTrust) | gateway | Apache-2.0 | v0.61.0 2026-09-22 | N | N | N | Y | Y | ? | ~ | N |
| **Portkey Gateway** | proxy | MIT | v1.15.2 2026-01-12 / commit 2026-05-25 | Y | Y | ~ | Y | Y | ? | E | N |
| **NeMo Guardrails** | library + server | Apache-2.0 | v0.24.1 2026-09-16 | Y | Y | N | N | N | ? | N | N |
| **Guardrails AI** | library + server | Apache-2.0 | v0.11.0 2026-08-14 | Y | Y | N | N | N | ? | ? | N |
| **LLM Guard** | library | MIT | **ARCHIVED 2026-07-09** | Y | Y | N | N | N | N | N | N |
| **Invariant** | proxy + library | Apache-2.0 | last commit 2026-01-12 | Y | Y | N | N | N | ? | N | N |
| **Rebuff** | library | Apache-2.0 | **ARCHIVED**, 2024-01-25 | Y | N | N | N | N | N | N | N |
| **Vigil** | library | Apache-2.0 | dormant, 2024-01-31 | Y | N | N | N | N | N | N | N |
| **WhyLabs LangKit** | library | Apache-2.0 | dormant, 2024-11-22 | ~ | ~ | N | N | N | N | N | N |
| **BricksLLM** | proxy | MIT | dormant, 2025-01-05 | N | N | Y | Y | Y | ? | N | N |
| **Llama Prompt Guard 2 / Llama Guard 4** | model | Llama Community | 2025-04-29 | Y | ~ | N | N | N | N | N | N |
| **Granite Guardian 3.3** | model | Apache-2.0 | 2025-09-09 | Y | Y | N | N | N | N | N | N |
| **ShieldGemma** | model | Gemma Terms | 2024-08-28 | Y | Y | N | N | N | N | N | N |
| **promptfoo** | test harness | MIT | 0.123.1 2026-09-18 | test-time only, not runtime | | | | | | | |
| **garak** | scanner | Apache-2.0 | v0.17.0 2026-09-09 | test-time only, not runtime | | | | | | | |
| **OpenLLMetry** (Traceloop) | SDK | Apache-2.0 | 0.62.3 2026-08-10 | N | N | N | N | N | N | Y | N |
| **OpenLIT** | SDK + platform | Apache-2.0 | 2.1.0 2026-09-10 | N | N | N | N | N | N | Y | N |
| **Langfuse** | platform | MIT + `ee/` | v4.41.0 2026-09-21 | N | N | N | N | N | N | Y | ~ |
| **Helicone** | platform | Apache-2.0 | v2025.08.21-1 | N | N | ~ | Y | N | ? | Y | N |
| **Cloudflare AI Gateway** | SaaS | proprietary | n/a | not self-hostable by design (not verified live) | | | | | | | |

---

## (b) The closest single matches

### 1. LiteLLM, function by function

The team lead asked for the most careful treatment here, so this section goes through all eight and
is explicit about the misses.

**Classification:** self-hosted proxy, Python/FastAPI. MIT for the main tree; the `enterprise/`
directory carries a genuinely proprietary license (verified by reading
`enterprise/LICENSE.md` via the GitHub API) which forbids production use without a paid
subscription: *"This software ... may only be used in production, if you ... have agreed to, and
are in compliance with, the BerriAI Subscription Terms of Service."* v1.101.0 released 2026-09-15;
59,386 stars; pushed 2026-09-22.

**Function 1, input scanning: YES.**
Guardrail modes are `pre_call` ("Run before LLM call, on input"), `during_call` (parallel to the
LLM call, on input), `post_call`, and `logging_only`. The MIT tree at
`litellm/proxy/guardrails/guardrail_hooks/` carries 60+ integrations, enumerated live via the
GitHub API, including `bedrock_guardrails.py`, `presidio.py`, `lakera_ai.py`, `lakera_ai_v2.py`,
`guardrails_ai`, `promptguard`, `vigil_guard`, `llm_as_a_judge`, `semantic_guard`,
`litellm_content_filter`, `generic_guardrail_api`, and `custom_guardrail.py`.

Only five legacy hooks sit in the proprietary `enterprise/enterprise_hooks/` directory:
`aporia_ai`, `banned_keywords`, `blocked_user_list`, `google_text_moderation`, `openai_moderation`.
Two of those (`aporia_ai`, `openai`) also appear in the MIT tree, which suggests the enterprise
copies are vestigial. **The guardrail framework itself is MIT.** This corrects a common assumption
that LiteLLM guardrails are a paid feature.

*The miss within function 1:* no bundled classifier. LiteLLM is integration plumbing. Your DeBERTa
LLM Guard server would sit behind `generic_guardrail_api` or a `custom_guardrail`, exactly as it
sits behind guard-proxy today. LiteLLM replaces the proxy, not the scanner.

**Function 2, output scanning: YES, with a caveat.**
`post_call` mode is documented as running on "input & output", so the completion is in scope and a
guardrail can block on it.

*The miss within function 2:* regex-over-the-completion for planted secret sentinels is **not a
first-class configuration primitive**. There is no `ResponseGuard.regex` equivalent you declare in
YAML. You get there by writing a `custom_guardrail` (a Python class), or by using the
`banned_keywords` hook, which is Enterprise. For your specific secret-sentinel demo, this is the
single sharpest ergonomic gap versus agentgateway, which does expose declarative response regex.

**Function 3, USD spend cap: YES, and the strongest implementation found anywhere.**

This is the finding that reorders the report. LiteLLM enforces **pre-call, by reservation**: it
estimates the request's maximum cost, reserves it against the budget, and rejects before the
provider is called. After the response it swaps the reservation for actual cost.

Independently corroborated. `litellm/proxy/spend_tracking/budget_reservation.py` exists in the
**MIT tree** (not under `enterprise/`), alongside
`litellm/proxy/middleware/budget_reservation_release_middleware.py`. Reading its imports confirms
the mechanism: `count_input_tokens` and `count_input_tokens_for_model` for the estimate,
`select_tier_for_input` and `tier_rate` from `tiered_pricing` for the rate, `PrismaClient` for the
Postgres-backed counter, `should_throttle_budget_exceeded` for the admission decision, and
`HTTPException` for the rejection. 77 commits to the file; first commit **2026-04-30**.

- **OSS scopes:** global proxy, team, team member, internal user, virtual key, customer/end-user,
  per-provider.
- **Enterprise-only scopes:** per-model budgets and tag budgets.
- Budgets are denominated in USD, with `budget_duration` reset intervals (`30s`, `30m`, `30h`,
  `30d`). Without a duration they never reset.
- Over-budget requests fail with an authentication-class error.
- Per-request USD cost is tracked and returned in the `x-litellm-response-cost` response header.
  Basic spend tracking is OSS; spend *reports* (`/global/spend/report`), custom spend-log metadata,
  and tag-based spend are marked Enterprise.
- Works with AWS Bedrock.

*The misses within function 3:* it **requires Postgres**, which is a real operational weight for a
per-cluster workshop fleet. Per-model and tag budgets are paywalled. And the scope hierarchy is
key/team/user oriented rather than "per-cluster", so a cluster maps to a virtual key by convention
rather than by primitive.

**Function 4, rate limit: YES.**
RPM and TPM limits per key, team, user, or model. `token_rate_limit_type` selects whether TPM counts
total, input-only, or output-only tokens.

**Function 5, model tier switch: YES.**
Router with model aliases, weighted routing, and fallbacks. Config-driven, which is what you need
for a toggle.

**Function 6, fail closed: PARTIAL, and the distinction matters.**

Two different things are being asked here and LiteLLM answers them differently:

- *Budget enforcement fails closed by construction.* Because the reservation is taken pre-call
  against Postgres, a request that cannot reserve does not reach the provider. This is a stronger
  guarantee than any post-hoc design can give, including agentgateway's.
- *Guardrail-scanner-unreachable behavior is undocumented.* The guardrails quick-start says nothing
  about timeouts, fallback behavior, or failure modes, and a code search for `fail_on_error`-style
  options under `litellm/types/guardrails` returned **zero** hits. I am recording this as
  unverified, not as absent. But you cannot point at a documented default the way you can with
  agentgateway.

For a demo whose whole point is that the scanner being down must refuse rather than pass through,
this is the gap that would need the most work to close and verify.

**Function 7, OTel gen_ai telemetry: YES.**
Setting `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` emits spans following the latest
OpenTelemetry GenAI semantic conventions, rooted at `Received Proxy Server Request`. Message content
appears as both span attributes and events, with these exact names:

- `gen_ai.input.messages` (span attribute)
- `gen_ai.output.messages` (span attribute)
- `gen_ai.content.prompt` (per-message event)
- `gen_ai.content.completion` (per-choice event)

Capture is controlled by `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` with values
`NO_CONTENT`, `SPAN_ONLY`, `EVENT_ONLY`, `SPAN_AND_EVENT`, plus a global Python kill switch
`litellm.turn_off_message_logging=True`.

This matches the Datadog LLM Observability requirement recorded in this repo's own memory (content
panels read the JSON-string span attributes at priority 1). LiteLLM emits precisely those.

*Unverified:* when this landed. It works today; I did not date it.

**Function 8, live prompt feed: NO.** Nothing in LiteLLM streams prompts to a room-facing feed.

**LiteLLM scorecard: 6 clear yes, 1 partial (6), 1 no (8).**

### 2. agentgateway, the closest by feature shape

Apache-2.0, Linux Foundation, v1.5.0 released 2026-08-27, pushed 2026-09-22, 4,975 stars, created
2025-03-18. Rust.

Verified from its own `schema/config.json` (311 definitions), which is better evidence than a
README:

- `PromptGuard` splits into `request` and `response` arrays. `RequestGuard` accepts
  `regex | webhook | openAIModeration | bedrockGuardrails | googleModelArmor | azureContentSafety`.
  `ResponseGuard` accepts the same minus moderation. **Declarative regex over the completion is a
  first-class primitive**, which maps onto your secret-sentinel check exactly and is the one thing
  it does more cleanly than LiteLLM.
- `BudgetLimitUnit` is an enum of exactly `['USD', 'Tokens']`. `BudgetExceededAction` is
  `['Audit', 'Block']`. `BudgetWindow.rolling` takes `1h`, `24h`, `30d`.
- `WebhookFailureMode` documents: *"Defaults to `failClosed`. When failing closed, the error is
  propagated and the LLM request is rejected. When failing open, the request is allowed through
  despite the webhook failure."* `RemoteRateLimitFailureMode` also defaults to `FailClosed`. This is
  **the only project examined that ships fail-closed as the documented default.**
- `examples/datadog/standalone/config-content.yaml` sets, verbatim:
  ```yaml
  gen_ai.input.messages: llm.prompt
  gen_ai.output.messages: llm.completion.map(c, {"role":"assistant", "content":c})
  ```
  targeting Datadog Agent Observability, which Datadog also calls LLM Observability. Same attribute
  names, same destination, same product as your stack.
- Metric `agentgateway_gen_ai_client_cost_usd_total` (counter, unit `usd`) exists.

**The decisive gap: budgets are post-hoc.** The schema's own words: *"Usage is charged after an LLM
response when the provider reports the tokens or cost required by the configured unit. Requests with
unavailable usage are logged but cannot be charged or blocked retroactively."* The cap blocks the
next request, not the one that crosses the line. For a denial-of-wallet demo this is a meaningful
difference from LiteLLM's reservation model: a single very expensive request can still land.

Other gaps: no bundled classifier (bring your own behind `webhook`); budget is scoped to a
standalone API key rather than a cluster; content capture is opt-in and the example file is headed
`# Synthetic content capture ONLY. Do not use with private prompts without redaction.`; no live feed.

**agentgateway scorecard: 7 of 8, with function 3 weaker than LiteLLM's.**

### 3. Kong AI Gateway, gated where it counts

`ai-prompt-guard`, `ai-semantic-prompt-guard`, `ai-semantic-response-guard`,
`ai-azure-content-safety`, `ai-aws-guardrails`, plus OpenTelemetry span attributes for AI traffic.
Good coverage on 1, 2, 4, 5, 7.

But `ai-rate-limiting-advanced`, the only plugin carrying the `cost` strategy, is explicitly
**`tier: ai_gateway_enterprise`**: *"This plugin is only available as part of our AI Gateway
Enterprise offering."* Its cost formula is
`(prompt_tokens x input_cost + completion_tokens x output_cost) / 1,000,000`. Function 3 is behind a
paywall, so Kong is out for an OSS answer.

---

## (c) Smallest OSS combination for all eight

Since LiteLLM already clears the triad, the combination question reduces to covering function 8 and
hardening function 6.

**Option A, fewest moving parts (recommended if rebuilding):**

1. **LiteLLM** covers 1, 2, 3 (pre-call), 4, 5, 7, and the budget half of 6. Requires Postgres.
2. **A prompt-injection classifier served over HTTP** behind `generic_guardrail_api`, covering the
   detection half of function 1. Your existing DeBERTa server, or
   `meta-llama/Llama-Prompt-Guard-2-86M`, or `ibm-granite/granite-guardian-3.3-8b`.
3. **Glue:** a `custom_guardrail` subclass (tens of lines of Python) providing declarative regex
   over the completion for the secret sentinels, an explicit fail-closed wrapper around the scanner
   call, and an OTLP consumer that tails the span stream into the room feed.

**Option B, if fail-closed-by-default and declarative response regex matter more than pre-call
enforcement:**

1. **agentgateway** covers 1 (enforcement), 2, 3 (post-hoc), 4, 5, 6, 7.
2. **Same classifier** behind its `webhook` guard, which already defaults to `failClosed`.
3. **Glue:** an OTLP or CEL access-log consumer for the feed. No Postgres.

Option B needs less glue and gives a stronger fail-closed story out of the box. Option A gives the
stronger spend story. Neither provides the live feed, and no third project would.

**The irreducible bespoke piece in both: function 8.** Roughly the same amount of code either way.

---

## (d) Two findings you did not ask for but should have

### Your LLM Guard dependency is archived

- `protectai/llm-guard` was **archived 2026-07-09**. The notice reads: *"THIS PROJECT HAS BEEN
  ARCHIVED. This project and its associated models on Hugging Face are no longer under active
  development or maintained."*
- Last PyPI release is **0.3.16, 2025-05-19**. Sixteen months old.
- `protectai/rebuff`, same org, also archived (last commit 2024-01-25). Protect AI was acquired by
  Palo Alto Networks.
- **No credible successor fork.** The most-starred fork of llm-guard has 2 stars.
- The weights survive independently: `protectai/deberta-v3-base-prompt-injection-v2` is still on
  HuggingFace, modified 2026-07-09, with **839,512 downloads in 30 days**. Heavily used, formally
  unmaintained.

Practical read: the DeBERTa weights are fine to keep running and are not disappearing. The
`llm-guard` Python package is the part that will rot. Both Option A and Option B above would let you
replace the package with a thin server of your own while keeping the model. Llama Prompt Guard 2
86M is the maintained alternative if you want off the model as well.

This bears directly on the repo's existing note about the offline model directory fix (#241): that
workaround is now pinned to an archived upstream.

### Two projects changed identity

- **`envoyproxy/ai-gateway` no longer exists under that name.** It redirects to
  `theagentrouter/agent-router`. Its README: *"Envoy AI Gateway is now Agent Router, an Agentic AI
  Foundation project. Same code, same maintainers, same release cadence and Apache 2.0 license."*
  Any slide or doc citing "Envoy AI Gateway" is now citing a dead name.
- **Langfuse is now copyright ClickHouse, Inc.** Its LICENSE reads
  `Copyright (c) 2023-2026 ClickHouse, Inc.`, MIT with an `ee/` carve-out. It has also grown an
  `ai-gateway/` Rust service, but that is a capture relay for `POST /openai/v1/responses` that
  uploads generations over OTLP. No guards, no budgets.

Other redirects encountered, for accuracy in any write-up: `NVIDIA/NeMo-Guardrails` to
`NVIDIA-NeMo/Guardrails`, `katanemo/archgw` to `katanemo/plano`, `alibaba/higress` to
`higress-group/higress`, `langdb/ai-gateway` to `vllora/vllora`.

---

## Notes on the rest of the field

**Spend caps really are the rare function, as suspected.** Across 26 projects, a USD-denominated
hard cap that refuses requests exists in exactly four: LiteLLM (pre-call, OSS), agentgateway
(post-hoc, OSS), Bifrost (OSS, guardrails unverified), and Kong (Enterprise only). Every dedicated
guardrail project has **zero** spend-control capability: NeMo Guardrails, Guardrails AI, LLM Guard,
Rebuff, Vigil, Invariant, LangKit, and all the classifier models. The guardrail ecosystem and the
cost-control ecosystem are almost entirely disjoint, and only the gateways sit in both. That is the
genuinely defensible version of the "nobody does this" claim.

**Fail-closed is rarer still.** Only agentgateway documents it as a default anywhere in the field.

**Dormant or dead, do not build on these:** Rebuff (archived, 2024-01-25), Vigil (2024-01-31),
WhyLabs LangKit (2024-11-22), BricksLLM (2025-01-05, and it was the notable OSS spend-cap gateway),
Invariant (2026-01-12, despite a README that reads as actively maintained; the API disagrees with
the prose), Portkey Gateway (last release v1.15.2 on 2026-01-12, last commit 2026-05-25, so roughly
four months without a commit and eight without a release).

**Test-time, not runtime:** promptfoo (0.123.1, 2026-09-18) describes itself as "Test your prompts,
agents, and RAGs. Red teaming/pentesting/vulnerability scanning for AI." garak (v0.17.0, 2026-09-09)
is "the LLM vulnerability scanner." Both are valuable and neither sits in the request path.

**Observability only, no enforcement:** OpenLLMetry (0.62.3, 2026-08-10), OpenLIT (2.1.0,
2026-09-10), Langfuse (v4.41.0, 2026-09-21), Helicone (Apache-2.0, last release 2025-08-21).

**Higress caveat worth recording:** its `ai-security-guard` plugin does check both request and
response (`checkRequest`, `checkResponse`, with configurable JSONPaths including streaming deltas),
but it requires Alibaba Cloud `accessKey` and `secretKey` and calls Aliyun content moderation. The
detection is **not** self-hostable. `ai-quota` and `ai-token-ratelimit` handle token and request
quotas, not USD.

**TrustGate credibility gap, flagged rather than resolved:** the README claims production readiness,
ISO 27001, and Gartner recognition. The repo has **10 stars**, was created 2026-05-26, and shipped
v0.61.0 on 2026-09-22. Genuinely active, essentially unadopted, and the documentation page I read
lists rate limiting, token rate limiting, routing with fallback, OTLP export, semantic caching, and
request-size guards, but **no** prompt-injection or content guardrails.

**Current guard models, verified via the HuggingFace API** (the PurpleLlama README is stale, still
describing Llama Guard 3):

| Model | Last modified | Downloads / 30d |
|---|---|---|
| `meta-llama/Llama-Guard-4-12B` | 2025-04-29 | 45,307 |
| `meta-llama/Llama-Prompt-Guard-2-86M` | 2025-04-29 | 113,206 |
| `meta-llama/Llama-Prompt-Guard-2-22M` | 2025-04-29 | 12,584 |
| `meta-llama/Prompt-Guard-86M` | 2025-11-12 | 4,214,023 |
| `ibm-granite/granite-guardian-3.3-8b` | 2025-09-09 | 96,095 |
| `google/shieldgemma-2b` | 2024-08-28 | 11,566 |
| `protectai/deberta-v3-base-prompt-injection-v2` | 2026-07-09 | 839,512 |

---

## What I could not verify

Flagged rather than guessed, per the standing rule:

- **When LiteLLM's `gen_ai` semantic-convention OTel emission landed.** It exists today; I did not
  date it. This is the one leg of the triad whose availability on 2026-06-17 is unknown, and the
  verdict's timing argument is correspondingly softer on that dimension than on budgets.
- **LiteLLM's guardrail-unreachable failure semantics.** Docs silent; code search under
  `litellm/types/guardrails` returned zero hits for `fail_on_error`-style options.
- **Bifrost's guardrails in the Apache-2.0 build.** Its README calls guardrails "an enterprise
  capability" without stating what the OSS build includes.
- **Cloudflare AI Gateway.** Not fetched. Known by design to be SaaS-only, not self-hostable, but
  not confirmed live in this session.
- **Lakera's OSS components** and **Arthur Shield.** Not reached before the search budget ran out.
- **kgateway, Gateway API Inference Extension, vLLM built-ins, OpenWebUI pipelines.** Classified
  from repository descriptions and release metadata only, not feature-verified. None is positioned
  as a content-guard product; GIE is inference routing, OpenWebUI pipelines is a plugin framework
  for a chat UI.
- **Higress `ai-quota`** USD versus token semantics. `ai-security-guard` was read in full;
  `ai-quota` only from the plugin index.
- **guard-proxy's own design intent.** I dated its first commit in this repo (2026-06-17) but did
  not read `agent/gateway/guard-proxy/proxy.py` to compare implementation details function by
  function. The coverage claims above are about the candidates, not about guard-proxy's internals.

---

## Sources

All fetched or queried 2026-09-22.

- agentgateway: https://github.com/agentgateway/agentgateway
- agentgateway config schema: https://github.com/agentgateway/agentgateway/blob/main/schema/config.json
- agentgateway Datadog example: https://github.com/agentgateway/agentgateway/tree/main/examples/datadog/standalone
- LiteLLM guardrails: https://docs.litellm.ai/docs/proxy/guardrails/quick_start
- LiteLLM budgets: https://docs.litellm.ai/docs/proxy/users
- LiteLLM cost tracking: https://docs.litellm.ai/docs/proxy/cost_tracking
- LiteLLM OTel: https://docs.litellm.ai/docs/observability/opentelemetry_integration
- LiteLLM enterprise license: https://github.com/BerriAI/litellm/blob/main/enterprise/LICENSE.md
- LiteLLM budget reservation: https://github.com/BerriAI/litellm/blob/main/litellm/proxy/spend_tracking/budget_reservation.py
- LLM Guard (archived): https://github.com/protectai/llm-guard
- Agent Router (ex-Envoy AI Gateway): https://github.com/theagentrouter/agent-router
- Bifrost: https://github.com/maximhq/bifrost
- TrustGate: https://github.com/NeuralTrust/TrustGate
- Kong AI Gateway: https://developer.konghq.com/ai-gateway/
- Kong ai-rate-limiting-advanced: https://developer.konghq.com/plugins/ai-rate-limiting-advanced/
- NeMo Guardrails: https://docs.nvidia.com/nemo/guardrails/latest/index.html
- Guardrails AI: https://www.guardrailsai.com/docs
- PurpleLlama: https://github.com/meta-llama/PurpleLlama
- Invariant: https://github.com/invariantlabs-ai/invariant
- Portkey Gateway: https://github.com/Portkey-AI/gateway
- Higress ai-security-guard: https://github.com/higress-group/higress/blob/main/plugins/wasm-go/extensions/ai-security-guard/README_EN.md
- Langfuse license: https://github.com/langfuse/langfuse/blob/main/LICENSE
- PyPI llm-guard: https://pypi.org/pypi/llm-guard/json
- HuggingFace model API: https://huggingface.co/api/models/
