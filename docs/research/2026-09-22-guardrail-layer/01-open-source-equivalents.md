# Is guard-proxy's job served by open source?

Research report. Verified 2026-09-22 against the GitHub API, project config schemas, vendor
documentation, PyPI, and the HuggingFace API. Every version, date, and status below comes from a
live source, cited inline. Items I could not verify are marked `?` and collected at the end rather
than guessed at.

Method note: this session's WebSearch budget was exhausted (50/50) before the research began, so
nothing here rests on a search-result summary. Everything is a direct fetch of a document, a JSON
schema, a registry record, or a repository.

---

## Executive summary

Three questions were put to this study. The answers:

1. **Does any single OSS project do content guards AND pre-call spend enforcement AND OTel gen_ai
   spans?** Yes, exactly one: **LiteLLM**. Every other candidate misses at least one leg.

2. **When a project scores "yes" on input scanning, does it actually scan, or does it just offer a
   socket?** Mostly the latter. **No gateway ships a local ML injection classifier.** LiteLLM is the
   only gateway that ships a local injection *ruleset* (regex/pattern based, MIT, in-process).
   agentgateway ships only generic regex plus remote services plus a webhook. The teammate who read
   agentgateway as "(b) or (c) only, no local classifier" is **correct**.

3. **Was the combined job unserved when guard-proxy was built?** Partly. agentgateway had content
   guards and fail-closed webhooks *before* guard-proxy's first commit, but had **no budgets of any
   kind** until 10 weeks after it. LiteLLM had all of it, including pre-call spend enforcement,
   seven weeks before guard-proxy's first commit.

**The honest verdict is in section (d).** The short form: the *spend-cap* half of this was genuinely
rare and, in agentgateway's case, did not exist yet. The *whole combination* did exist, in LiteLLM,
before guard-proxy was written.

---

## (a) Coverage matrix

Functions: **1** input scan · **2** output scan · **3** USD spend cap · **4** rate limit ·
**5** model tier switch · **6** fail closed · **7** OTel gen_ai with message content ·
**8** live prompt feed

`Y` yes · `N` no · `E` enterprise/paid only · `~` partial · `?` unverified

| Project | Type | License | Latest / last commit | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **LiteLLM** | proxy | MIT + proprietary `enterprise/` | v1.101.0 2026-09-15 | Y | Y | **Y pre-call** | Y | Y | **Y** | Y | N |
| **agentgateway** | proxy | Apache-2.0 | v1.5.0 2026-08-27 | Y | Y | **Y post-hoc** | Y | Y | **Y** | Y | N |
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
| **promptfoo** | test harness | MIT | 0.123.1 2026-09-18 | test-time only, not in the request path | | | | | | | |
| **garak** | scanner | Apache-2.0 | v0.17.0 2026-09-09 | test-time only, not in the request path | | | | | | | |
| **OpenLLMetry** (Traceloop) | SDK | Apache-2.0 | 0.62.3 2026-08-10 | N | N | N | N | N | N | Y | N |
| **OpenLIT** | SDK + platform | Apache-2.0 | 2.1.0 2026-09-10 | N | N | N | N | N | N | Y | N |
| **Langfuse** | platform | MIT + `ee/` | v4.41.0 2026-09-21 | N | N | N | N | N | N | Y | ~ |
| **Helicone** | platform | Apache-2.0 | v2025.08.21-1 2025-08-21 | N | N | ~ | Y | N | ? | Y | N |
| **Cloudflare AI Gateway** | SaaS | proprietary | n/a | not self-hostable by design (not verified live) | | | | | | | |

### The triad, isolated

| Candidate | Content guards | Pre-call spend | OTel gen_ai | Misses |
|---|---|---|---|---|
| **LiteLLM** | yes | **yes** | yes | **nothing** |
| agentgateway | yes | post-hoc only | yes | pre-call enforcement |
| Kong AI Gateway | yes | Enterprise only | yes | an OSS spend cap |
| Bifrost | enterprise/unverified | post-hoc | yes | verified OSS guards |
| Higress | Alibaba Cloud only | no | partial | spend, self-hosted detection |
| NeMo Guardrails | yes | no | no | spend, telemetry |
| Guardrails AI | yes | no | unverified | spend, telemetry |
| Portkey Gateway | yes | partial | Enterprise | OSS telemetry |
| TrustGate | no | no | partial | guards, spend |
| Agent Router | no | quota only | unverified | guards |

A combination is **not** required for the triad. It is required only for function 8, the live prompt
feed, which nothing in the ecosystem provides.

---

## (a2) THE DECIDING QUESTION: what does a "Y" on scanning actually mean?

This is the section that answers whether a project *does* the scan or merely *hosts* one.

Legend:
- **(a) LOCAL** — ships its own classifier or ruleset, runs in-process or in-cluster, no third party.
- **(b) REMOTE** — delegates to a remote, generally paid service.
- **(c) SOCKET** — a webhook or plugin interface; the operator supplies and runs the implementation.

Regex counts as (a), but is called out explicitly, because **a regex is not an injection
classifier**.

### Function 1, input injection scan

| Project | (a) local | (b) remote | (c) socket | What a `Y` really means |
|---|---|---|---|---|
| **LiteLLM** | **YES, injection-specific** | YES, ~50 vendors | YES | **Ships a local prompt-injection ruleset.** See below. |
| **agentgateway** | generic regex only | YES | YES | **Socket + remote.** No injection-specific local logic. |
| **Kong AI Gateway** | `ai-prompt-guard` regex | YES | YES | Local keyword/topic deny, remote for anything semantic |
| **Higress** | no | YES (Alibaba only) | no | **Remote only**, and requires an Alibaba Cloud account |
| **Portkey Gateway** | some basic checks | YES | YES | Mixed; most of the "50+ guardrails" are partner services |
| **NeMo Guardrails** | **YES** (Colang rules, local models) | optional | YES | Genuinely local, but it is a library, not a proxy |
| **Guardrails AI** | **YES** (Hub validators in-process) | some validators | YES | Genuinely local, but a library |
| **LLM Guard** | **YES, local ML classifier** | no | no | The real thing, and **archived** |
| **Invariant** | **YES** (local rule engine) | no | no | Local, but dormant since 2026-01-12 |
| **Rebuff** | YES (heuristics, canary) | LLM check | no | Archived 2024 |
| **Vigil** | YES (YARA, vectors, transformer) | no | no | Dormant since 2024 |
| **Prompt Guard 2 / Llama Guard 4 / Granite Guardian / ShieldGemma** | **YES, these ARE the classifiers** | no | no | Models. You host them yourself. |

**The finding that matters most here:**

> **No gateway ships a local ML prompt-injection classifier. Not one.**

The only category-(a) ML classifiers in the entire field are raw model weights and one archived
library (LLM Guard). Every gateway either calls a vendor API (b) or gives you a socket (c).

This means **guard-proxy's shape, a proxy calling a local DeBERTa sidecar, is the standard design,
not an anomaly.** Any gateway you adopted would host the *call* to your classifier; none would
replace the classifier. That part of guard-proxy is not redundant with anything.

**Two precise corrections within that:**

**agentgateway, confirming the teammate's reading.** Verified from `schema/config.json`, the
`RequestGuard` definition is a `oneOf` over exactly these six:

| Variant | Class |
|---|---|
| `regex` | (a) local, but generic pattern matching, not an injection classifier |
| `webhook` | (c) socket |
| `openAIModeration` | (b) remote, OpenAI |
| `bedrockGuardrails` | (b) remote, AWS |
| `googleModelArmor` | (b) remote, Google |
| `azureContentSafety` | (b) remote, Microsoft |

So the teammate is right. agentgateway's `Y` on function 1 means "has a place to plug one in, plus
generic regex." It does not detect prompt injection itself.

**LiteLLM, which is a genuine exception and was understated in my earlier draft.** The MIT tree
contains `litellm/proxy/guardrails/guardrail_hooks/litellm_content_filter/`, and it is fully local:
a grep of `content_filter.py` for `http_handler|httpx|requests\.|api_base` returns **0 matches**. It
ships `patterns.json` (38,785 bytes) plus a `categories/` directory whose files include, verbatim:

```
prompt_injection_data_exfiltration.yaml
prompt_injection_jailbreak.yaml
prompt_injection_malicious_code.yaml
prompt_injection_sql.yaml
prompt_injection_system_prompt.yaml
```

alongside `harm_*`, `bias_*`, `claims_*`, and `denied_*` categories, localized toxicity lists
(`harm_toxic_abuse_{au,de,es,fr}.json`), `policy_templates/`, and `guardrail_benchmarks/`.

So **LiteLLM is the only gateway that ships an injection-specific local ruleset in the OSS tree.**
It is pattern-based, not a transformer, so it is weaker than your DeBERTa classifier and would not
replace it. But it is category (a), it targets prompt injection by name, and it runs in-process with
no third party. That is a real difference from agentgateway and it belongs in the call.

### Function 2, output scan

| Project | (a) local | (b) remote | (c) socket | What a `Y` really means |
|---|---|---|---|---|
| **agentgateway** | **YES, declarative regex** | YES | YES | **`ResponseGuard.regex` is a first-class local primitive.** Exactly right for secret sentinels. |
| **LiteLLM** | YES (content filter on `post_call`) | YES | YES | Local, but **arbitrary regex over the completion needs Python**, not one line of YAML |
| **Kong AI Gateway** | no | YES (`ai-semantic-response-guard` needs embeddings) | YES | Remote-dependent |
| **Higress** | no | YES (Alibaba only) | no | Remote only; `checkResponse` with configurable JSONPaths incl. streaming deltas |
| **NeMo Guardrails** | **YES** (output rails) | optional | YES | Local, library |
| **Guardrails AI** | **YES** (output guards) | some | YES | Local, library |
| **LLM Guard** | **YES** (local secret/regex scanners) | no | no | Archived |
| **Granite Guardian / ShieldGemma** | **YES** | no | no | Models, self-hosted |

`ResponseGuard` in agentgateway is a `oneOf` over `regex`, `webhook`, `bedrockGuardrails`,
`googleModelArmor`, `azureContentSafety`. Note it drops `openAIModeration` relative to the request
side.

**For your specific planted-secret-sentinel check, agentgateway is ergonomically better than
LiteLLM.** `ResponseGuard.regex` is declarative config. LiteLLM gets you there through a
`custom_guardrail` Python subclass or the Enterprise-only `banned_keywords` hook.

---

## (b) THE TIMING FACT, nailed down

The teammate flagged this as possibly the single most important fact in the study. Here it is with
every field verified through the GitHub API.

### agentgateway budgets: PR #3143

| Field | Value |
|---|---|
| Title | **Add API-key scoped budgets for LLM traffic** |
| PR number | **#3143** |
| State | closed, **merged: true** |
| Merged at | **2026-08-25T00:47:39Z** |
| Merge commit | `67906b4bb9dd4359f0ee3ec4cf1fa215953dc683` |
| Base branch | `main` |

### Which release first contains it

Verified by ancestry comparison against release tags, not by inference from dates:

| Comparison | API result | Meaning |
|---|---|---|
| `v1.4.0...67906b4` | `status=ahead, ahead_by=263, behind_by=0` | commit is **ahead** of v1.4.0, so **NOT in v1.4.0** |
| `v1.5.0...67906b4` | `status=behind, ahead_by=0, behind_by=22` | commit is **behind** v1.5.0, so **v1.5.0 CONTAINS it** |

Release timeline around it:

| Tag | Published |
|---|---|
| v1.3.0 | 2026-06-18 |
| v1.3.1 | 2026-06-22 |
| v1.4.0 | 2026-07-27 |
| v1.4.1 | 2026-07-29 |
| **v1.5.0-beta.1** | **2026-08-25** |
| **v1.5.0** | **2026-08-27** |
| v1.6.0-alpha.1 | 2026-09-14 |

**Answers to the three sub-questions, plainly:**

- **PR number:** #3143.
- **Merge date:** 2026-08-25T00:47:39Z, into `main`.
- **First release containing it:** **v1.5.0-beta.1 (2026-08-25)**, then stable in **v1.5.0
  (2026-08-27)**.
- **Does v1.5.0, the version we run, contain it?** **Yes.** Confirmed by ancestry
  (`v1.5.0...67906b4` returns `behind_by=22`, meaning the tag is 22 commits ahead of it).
- **Was it in anything earlier?** **No.** Not in v1.4.1 (2026-07-29) or any prior release.
  agentgateway had **no budget capability of any kind** before 2026-08-25.

### Set against guard-proxy's own history

From `git log --reverse -- '*guard-proxy*'` in this repo:

| Event | Date |
|---|---|
| LiteLLM pre-call budget reservation, first commit | **2026-04-30** |
| agentgateway webhook `failureMode` (fail-closed), PR #1946 | **2026-06-09** |
| **guard-proxy first commit** ("Add A2A guard proxy (real output/input inspection point)") | **2026-06-17** |
| agentgateway release current on that date | v1.3.0-beta.1 (2026-06-12); v1.3.0 shipped 2026-06-18 |
| agentgateway budgets merged | **2026-08-25**, 10 weeks later |

So the airtight version of the claim is **narrower than "the job was unserved," and it is still a
real finding**:

> On 2026-06-17, when guard-proxy was first committed, agentgateway already had request and
> response guards and a fail-closed webhook mode, but had **no spend control whatsoever**. Its USD
> budget feature was merged 2026-08-25 and first shipped in v1.5.0-beta.1 that same day, ten weeks
> after guard-proxy began. **LiteLLM, however, had had pre-call USD budget reservation since
> 2026-04-30**, seven weeks before guard-proxy started.

Do not say "nobody did this." Say "the Rust gateway we would reach for today could not do the spend
half until five weeks ago, and the one project that could was a Python proxy with a Postgres
dependency." That survives scrutiny.

### agentgateway guardrail feature history, for completeness

| Date | Commit |
|---|---|
| 2025-08-06 | configurable region and add guardrails support (#265) |
| 2025-08-15 | guardrails: add openai moderation endpoint (#321) |
| 2025-10-28 | Add headers to guardrails rejection response (#572) |
| 2025-12-15 | llm: consistent req and resp guardrail syntax (#733) |
| 2025-12-17 | Guardrail Metrics (#697) |
| 2026-02-11 | Add more provider guardrail support (#918) |
| **2026-06-09** | **feat(llm): add failureMode to webhook guardrails (#1946)** |
| 2026-07-22 | feat(llm): configurable webhook guardrail headers and path via CEL |
| 2026-08-19 | promptGuard: opt-in tool call coverage with scope (#3000) |
| **2026-08-25** | **Add API-key scoped budgets for LLM traffic (#3143)** |
| 2026-08-26 | feat(llm): add detect-only mode to Bedrock Guardrails (#2349) |
| 2026-09-15 | promptGuard: give the webhook target the same `policies` slot as extAuthz |

---

## (c) FAIL-CLOSED, resolved for both

My earlier draft marked this `?` for LiteLLM. That was wrong, and it was wrong for an instructive
reason: I searched `litellm/types/guardrails` for `fail_on_error`-style options, got zero hits, and
recorded a negative from a query that was too narrow. The options are not in the types package; they
are parameters on the guardrail hook. Re-tested against the hook itself, the answer is clear.

### LiteLLM: fails closed by default, and it is configurable

Evidence from `litellm/proxy/guardrails/guardrail_hooks/generic_guardrail_api/`, the hook you would
use for a custom scanner such as your DeBERTa server:

`__init__.py`:
```python
unreachable_fallback=getattr(litellm_params, "unreachable_fallback", "fail_closed"),
fail_on_error=getattr(litellm_params, "fail_on_error", True),
```

`generic_guardrail_api.py`:
```python
unreachable_fallback: Literal["fail_closed", "fail_open"] = "fail_closed",
fail_on_error: bool | None = True,
...
unreachable_fail_open: Final = is_unreachable and self.unreachable_fallback == "fail_open"
if unreachable_fail_open or not self.fail_on_error:
    return self._fail_open_passthrough(...)
verbose_proxy_logger.error("Generic Guardrail API: failed to make request: %s", str(error))
raise Exception(f"Generic Guardrail API failed: {error}")
```

- **Unreachable backend: the request FAILS.** The default is `unreachable_fallback="fail_closed"`.
- **Setting or default?** Default. Fail-open is opt-in, via `unreachable_fallback: fail_open` or
  `fail_on_error: false` in `litellm_params`.
- **Framework level:** `ProxyLogging.pre_call_hook` in `litellm/proxy/utils.py` re-raises rather
  than swallowing (`except Exception:` ... `raise`), and the parallel hook runner collects results
  with `return_exceptions=True` then re-raises the first blocking exception. So an exception from
  any guardrail propagates and rejects the request.
- **Caveat worth keeping:** `unreachable_fallback` is a parameter of *this* hook. There is no single
  global proxy-wide fail-closed switch covering all 60+ integrations, and I did not audit whether
  every vendor integration honors the same convention. For a custom scanner, which is your case, the
  default is fail-closed and it is explicit in the source.
- **Budget enforcement fails closed by construction**, separately and more strongly: the reservation
  is taken pre-call against Postgres, so a request that cannot reserve never reaches the provider.

### agentgateway: fails closed by default, documented in the schema

From `schema/config.json`, quoted verbatim:

> **`WebhookFailureMode`** — "Defines how the proxy behaves when a webhook guardrail is unreachable
> or returns an error. Defaults to `failClosed`. When failing closed, the error is propagated and
> the LLM request is rejected. When failing open, the request is allowed through despite the webhook
> failure."

> **`RemoteRateLimitFailureMode`** — "Defines how the proxy behaves when the remote rate limit
> service is unavailable or returns an error. Defaults to `FailClosed`. When failing closed, a 500
> Internal Server Error is [returned]."

- **Unreachable backend: the request FAILS.**
- **Setting or default?** Default, on both the guardrail webhook and the remote rate limiter.
  `failOpen` is the opt-in.
- This landed in PR #1946 on **2026-06-09**.

**Both projects default to fail-closed.** agentgateway states it in a published schema; LiteLLM
states it in source defaults. agentgateway's is the more auditable of the two because it is
per-guard config surface rather than a per-integration Python default.

---

## (d) Verdict

**The core of guard-proxy's job was served by a single open-source project before guard-proxy was
written, and that project is LiteLLM.** agentgateway, the one most people would reach for today,
could not have done the spend half until ten weeks later.

What is genuinely true, and defensible from a stage:

1. **The spend-cap function is rare.** Across 26 projects, a USD hard cap that refuses requests
   exists in four: LiteLLM (pre-call, OSS), agentgateway (post-hoc, OSS, since 2026-08-25), Bifrost
   (OSS), and Kong (Enterprise only). **Every dedicated guardrail project has zero spend control:**
   NeMo Guardrails, Guardrails AI, LLM Guard, Rebuff, Vigil, Invariant, LangKit, and every
   classifier model. The guardrail ecosystem and the cost-control ecosystem are almost disjoint, and
   only the gateways sit in both.
2. **No gateway ships a local ML injection classifier.** The sidecar shape guard-proxy uses is the
   standard answer, not a workaround.
3. **Fail-closed is rare as a documented default.** Only LiteLLM and agentgateway have it; the rest
   of the field is undocumented on this.
4. **The live prompt feed (function 8) is unserved everywhere.** That was always going to be
   bespoke.

What is **not** defensible, and should be dropped:

- "Nothing open source does this." LiteLLM did, before you started.
- "The ecosystem caught up only recently." True of agentgateway specifically, and worth saying that
  way. Not true of the field.

**Suggested framing.** Lead with the disjointness of the two ecosystems and the absence of any local
classifier in any gateway. That is the interesting, true, and verifiable claim. Then note that the
Rust gateway most teams would pick today gained USD budgets five weeks ago, in v1.5.0, which is the
version you run. Convergence on the same design is a stronger point than primacy would have been,
and you do not have to overstate anything to make it.

---

## (e) The candidates in detail

### LiteLLM, function by function

Self-hosted proxy, Python/FastAPI. MIT for the main tree; `enterprise/` carries a genuinely
proprietary license, verified by reading `enterprise/LICENSE.md`: *"This software ... may only be
used in production, if you ... have agreed to, and are in compliance with, the BerriAI Subscription
Terms of Service."* v1.101.0 released 2026-09-15; 59,386 stars; pushed 2026-09-22.

**1. Input scanning: YES, (a) + (b) + (c).** Modes are `pre_call` ("before LLM call, on input"),
`during_call` (parallel), `post_call`, `logging_only`. The MIT tree at
`litellm/proxy/guardrails/guardrail_hooks/` holds 60+ integrations, enumerated live, including
`bedrock_guardrails.py`, `presidio.py`, `lakera_ai.py`, `lakera_ai_v2.py`, `guardrails_ai`,
`promptguard`, `vigil_guard`, `llm_as_a_judge`, `semantic_guard`, `litellm_content_filter`,
`generic_guardrail_api`, `custom_guardrail.py`. Only five legacy hooks are in proprietary
`enterprise/enterprise_hooks/`: `aporia_ai`, `banned_keywords`, `blocked_user_list`,
`google_text_moderation`, `openai_moderation`. Two of those also appear in the MIT tree, so the
enterprise copies look vestigial. **The guardrail framework is MIT.**
*Miss:* no local ML classifier. The local `litellm_content_filter` is pattern-based.

**2. Output scanning: YES, (a) + (b) + (c).** `post_call` runs on "input & output".
*Miss:* declarative regex over the completion is not a config primitive. Arbitrary secret sentinels
need a `custom_guardrail` subclass, or the Enterprise `banned_keywords` hook.

**3. USD spend cap: YES, pre-call, the strongest implementation found anywhere.**
Corroborated independently. `litellm/proxy/spend_tracking/budget_reservation.py` is in the **MIT
tree**, with `litellm/proxy/middleware/budget_reservation_release_middleware.py`. Its imports
confirm the mechanism: `count_input_tokens` / `count_input_tokens_for_model` for the estimate,
`select_tier_for_input` and `tier_rate` from `tiered_pricing` for the rate, `PrismaClient` for the
Postgres counter, `should_throttle_budget_exceeded` for admission, `HTTPException` for rejection.
77 commits to the file; first commit **2026-04-30**.
- OSS scopes: global proxy, team, team member, internal user, virtual key, customer/end-user,
  per-provider.
- Enterprise scopes: per-model, tag.
- USD-denominated, with `budget_duration` resets (`30s`, `30m`, `30h`, `30d`). No duration means no
  reset. Over-budget requests fail with an auth-class error. Per-request cost in the
  `x-litellm-response-cost` header. Works with Bedrock.
- Basic spend tracking is OSS; `/global/spend/report`, custom spend-log metadata, and tag-based
  spend are Enterprise.
*Misses:* **requires Postgres**; per-model and tag budgets paywalled; scopes are key/team/user
oriented, so "per cluster" is a convention over a virtual key rather than a primitive.

**4. Rate limit: YES.** RPM and TPM per key, team, user, or model. `token_rate_limit_type` selects
total, input-only, or output-only.

**5. Model tier switch: YES.** Router with aliases, weighted routing, fallbacks. Config-driven.

**6. Fail closed: YES by default.** Resolved above. `unreachable_fallback="fail_closed"` and
`fail_on_error=True` are the defaults on the generic guardrail hook; `ProxyLogging.pre_call_hook`
re-raises. Budget enforcement fails closed by construction.

**7. OTel gen_ai: YES.** `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` emits spans
following the latest GenAI conventions, rooted at `Received Proxy Server Request`. Exact attribute
names: `gen_ai.input.messages`, `gen_ai.output.messages` (span attributes),
`gen_ai.content.prompt`, `gen_ai.content.completion` (events). Capture controlled by
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` with `NO_CONTENT` / `SPAN_ONLY` / `EVENT_ONLY`
/ `SPAN_AND_EVENT`, plus the global kill switch `litellm.turn_off_message_logging=True`.
This matches the Datadog LLM Observability requirement in this repo's memory, which reads the
JSON-string span attributes at priority 1.
*Unverified:* when this landed. It works today; I did not date it.

**8. Live prompt feed: NO.**

**Scorecard: 7 yes, 1 no.**

### agentgateway

Apache-2.0, Linux Foundation, v1.5.0 released 2026-08-27, pushed 2026-09-22, 4,975 stars, created
2025-03-18. Rust. Verified from `schema/config.json` (311 definitions), better evidence than a README.

- `PromptGuard` splits into `request` and `response` arrays, plus a `streaming` mode for streaming
  responses and realtime websocket messages.
- `BudgetLimitUnit` is an enum of exactly `['USD', 'Tokens']`. `BudgetExceededAction` is
  `['Audit', 'Block']`. `BudgetWindow.rolling` takes `1h`, `24h`, `30d`.
- `examples/datadog/standalone/config-content.yaml` sets, verbatim:
  ```yaml
  gen_ai.input.messages: llm.prompt
  gen_ai.output.messages: llm.completion.map(c, {"role":"assistant", "content":c})
  ```
  targeting Datadog Agent Observability, which Datadog also calls LLM Observability. Same attribute
  names, same destination, same product as your stack. The file is headed
  `# Synthetic content capture ONLY. Do not use with private prompts without redaction.`
- Metric `agentgateway_gen_ai_client_cost_usd_total` (counter, unit `usd`).

**The decisive gap is that budgets are post-hoc.** The schema's own words: *"Usage is charged after
an LLM response when the provider reports the tokens or cost required by the configured unit.
Requests with unavailable usage are logged but cannot be charged or blocked retroactively."* The cap
blocks the next request, not the one that crosses the line. For a denial-of-wallet demo, a single
very expensive request can still land. LiteLLM's reservation model does not have this hole.

Other gaps: no local injection classifier (section a2); budget scoped to a standalone API key rather
than a cluster; content capture opt-in; no live feed.

### Kong AI Gateway

`ai-prompt-guard`, `ai-semantic-prompt-guard`, `ai-semantic-response-guard`,
`ai-azure-content-safety`, `ai-aws-guardrails`, plus OTel span attributes for AI traffic. Good on
1, 2, 4, 5, 7.

But `ai-rate-limiting-advanced`, the only plugin with a `cost` strategy, is explicitly
**`tier: ai_gateway_enterprise`**: *"This plugin is only available as part of our AI Gateway
Enterprise offering."* Its formula is
`(prompt_tokens x input_cost + completion_tokens x output_cost) / 1,000,000`. Function 3 is
paywalled, so Kong is out for an OSS answer.

### The rest of the field

**Dormant or dead, do not build on these:** Rebuff (archived 2024-01-25), Vigil (2024-01-31),
WhyLabs LangKit (2024-11-22), BricksLLM (2025-01-05, and it was the notable OSS spend-cap gateway),
Invariant (2026-01-12, despite a README reading as actively maintained; the API disagrees with the
prose), Portkey Gateway (last release v1.15.2 on 2026-01-12, last commit 2026-05-25).

**Test-time, not runtime:** promptfoo (0.123.1, 2026-09-18) is "Test your prompts, agents, and RAGs.
Red teaming/pentesting/vulnerability scanning for AI." garak (v0.17.0, 2026-09-09) is "the LLM
vulnerability scanner." Both valuable, neither in the request path.

**Observability only, no enforcement:** OpenLLMetry (0.62.3, 2026-08-10), OpenLIT (2.1.0,
2026-09-10), Langfuse (v4.41.0, 2026-09-21), Helicone (last release 2025-08-21).

**Higress caveat:** `ai-security-guard` does check both request and response (`checkRequest`,
`checkResponse`, configurable JSONPaths including streaming deltas, `denyCode`, `denyMessage`), but
it requires Alibaba Cloud `accessKey` and `secretKey` and calls Aliyun content moderation. The
detection is **not self-hostable**. `ai-quota` and `ai-token-ratelimit` handle token and request
quotas, not USD.

**TrustGate credibility gap, flagged rather than resolved:** its README claims production readiness,
ISO 27001, and Gartner recognition. The repo has **10 stars**, was created 2026-05-26, and shipped
v0.61.0 on 2026-09-22. Genuinely active, essentially unadopted, and the documentation lists rate
limiting, token rate limiting, routing with fallback, OTLP export, semantic caching, and
request-size guards, but **no** prompt-injection or content guardrails.

**Current guard models, via the HuggingFace API** (the PurpleLlama README is stale, still describing
Llama Guard 3):

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

## (f) Smallest OSS combination for all eight

LiteLLM already clears the triad, so the combination question reduces to function 8 and hardening
the scanner path.

**Option A, strongest spend story:**

1. **LiteLLM** covers 1, 2, 3 (pre-call), 4, 5, 6, 7. Requires Postgres.
2. **A classifier behind `generic_guardrail_api`** for the ML half of function 1: your existing
   DeBERTa server, or `meta-llama/Llama-Prompt-Guard-2-86M`, or
   `ibm-granite/granite-guardian-3.3-8b`. Fail-closed is already the default on that hook.
3. **Glue:** a `custom_guardrail` subclass for declarative regex over the completion (secret
   sentinels), and an OTLP consumer tailing the span stream into the room feed.

**Option B, cleanest config surface, no Postgres:**

1. **agentgateway** covers 1 (enforcement), 2 (including declarative response regex), 3 (post-hoc),
   4, 5, 6, 7.
2. **Same classifier** behind its `webhook` guard, which defaults to `failClosed`.
3. **Glue:** an OTLP or CEL access-log consumer for the feed.

Option B needs less glue and gives the better secret-sentinel ergonomics. Option A gives the better
spend story, which for a denial-of-wallet demo is the function that actually matters. **If the
denial-of-wallet beat is load-bearing in the workshop, Option A is the correct pick**, because
agentgateway cannot block the request that blows the budget.

The irreducible bespoke piece in both is function 8, and it is roughly the same amount of code
either way.

---

## (g) Two findings you did not ask for

### Your LLM Guard dependency is archived

- `protectai/llm-guard` was **archived 2026-07-09**: *"THIS PROJECT HAS BEEN ARCHIVED. This project
  and its associated models on Hugging Face are no longer under active development or maintained."*
- Last PyPI release **0.3.16, 2025-05-19**. Sixteen months old.
- `protectai/rebuff`, same org, also archived. Protect AI was acquired by Palo Alto Networks.
- **No credible successor fork.** The most-starred fork has 2 stars.
- The weights survive: `protectai/deberta-v3-base-prompt-injection-v2` is still on HuggingFace,
  modified 2026-07-09, **839,512 downloads in 30 days**. Heavily used, formally unmaintained.

This bears on the repo's offline-model-directory fix (#241): that workaround is now pinned to an
archived upstream. Practical read: the weights are fine and are not disappearing; the Python package
is what will rot. Both options above let you replace the package while keeping the model.

It also sharpens section (a2). LLM Guard was the only OSS library that gave you a category-(a) local
ML injection classifier behind a clean API. Its archiving means that layer of the stack now has **no
maintained OSS implementation at all**, only raw model weights you host yourself.

### Two projects changed identity

- **`envoyproxy/ai-gateway` no longer exists under that name.** It redirects to
  `theagentrouter/agent-router`: *"Envoy AI Gateway is now Agent Router, an Agentic AI Foundation
  project. Same code, same maintainers, same release cadence and Apache 2.0 license."* Any slide
  citing "Envoy AI Gateway" is citing a dead name.
- **Langfuse is now copyright ClickHouse, Inc.** Its LICENSE reads
  `Copyright (c) 2023-2026 ClickHouse, Inc.`, MIT with an `ee/` carve-out. Its new `ai-gateway/`
  Rust service is a capture relay for `POST /openai/v1/responses` that uploads generations over
  OTLP. No guards, no budgets.

Other redirects, for accuracy: `NVIDIA/NeMo-Guardrails` to `NVIDIA-NeMo/Guardrails`,
`katanemo/archgw` to `katanemo/plano`, `alibaba/higress` to `higress-group/higress`,
`langdb/ai-gateway` to `vllora/vllora`.

---

## (h) What I could not verify

- **When LiteLLM's `gen_ai` semantic-convention OTel emission landed.** It exists today; I did not
  date it. This is the one leg of the triad whose availability on 2026-06-17 is unknown, so the
  timing argument in (d) is softer on telemetry than on budgets and guards.
- **Whether every LiteLLM vendor integration honors `unreachable_fallback`.** Verified for
  `generic_guardrail_api`, which is the relevant one for a custom scanner. Not audited across all
  60+.
- **Bifrost's guardrails in the Apache-2.0 build.** Its README calls guardrails "an enterprise
  capability" without stating what the OSS build includes.
- **Cloudflare AI Gateway.** Not fetched. Known by design to be SaaS-only, not confirmed live.
- **Lakera's OSS components** and **Arthur Shield.** Not reached before the search budget ran out.
- **kgateway, Gateway API Inference Extension, vLLM built-ins, OpenWebUI pipelines.** Classified
  from repository descriptions and release metadata only, not feature-verified. None is positioned
  as a content-guard product; GIE is inference routing, OpenWebUI pipelines is a plugin framework
  for a chat UI.
- **Higress `ai-quota`** USD versus token semantics. `ai-security-guard` was read in full;
  `ai-quota` only from the plugin index.
- **guard-proxy's own internals.** I dated its first commit (2026-06-17) and know its paths
  (`agent/gateway/guard-proxy/proxy.py`, `guard-proxy.yaml`,
  `weaver/registry/guard-proxy-spans.yaml`) but did not read the implementation to compare function
  by function. Coverage claims above are about the candidates, not about guard-proxy's code.

### One correction to my own earlier draft

I initially recorded LiteLLM's fail-closed behavior as unverified on the strength of a code search
over `litellm/types/guardrails` that returned zero hits. The options live on the guardrail hook's
parameters, not in the types package. The negative came from a query too narrow to support it. The
resolved answer is in section (c): **LiteLLM defaults to fail-closed.**

---

## Sources

All fetched or queried 2026-09-22.

- agentgateway: https://github.com/agentgateway/agentgateway
- agentgateway config schema: https://github.com/agentgateway/agentgateway/blob/main/schema/config.json
- agentgateway PR #3143: https://github.com/agentgateway/agentgateway/pull/3143
- agentgateway Datadog example: https://github.com/agentgateway/agentgateway/tree/main/examples/datadog/standalone
- LiteLLM guardrails: https://docs.litellm.ai/docs/proxy/guardrails/quick_start
- LiteLLM budgets: https://docs.litellm.ai/docs/proxy/users
- LiteLLM cost tracking: https://docs.litellm.ai/docs/proxy/cost_tracking
- LiteLLM OTel: https://docs.litellm.ai/docs/observability/opentelemetry_integration
- LiteLLM enterprise license: https://github.com/BerriAI/litellm/blob/main/enterprise/LICENSE.md
- LiteLLM budget reservation: https://github.com/BerriAI/litellm/blob/main/litellm/proxy/spend_tracking/budget_reservation.py
- LiteLLM generic guardrail API: https://github.com/BerriAI/litellm/tree/main/litellm/proxy/guardrails/guardrail_hooks/generic_guardrail_api
- LiteLLM local content filter: https://github.com/BerriAI/litellm/tree/main/litellm/proxy/guardrails/guardrail_hooks/litellm_content_filter
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
