# Two spikes on the guardrail layer (2026-09-21)

Both questions came from an outside ask relayed by Michael and are tracked as #406:

1. Does guard-proxy still have a reason to exist now that agentgateway ships prompt guards?
2. Should we open source a fork of LLM Guard?

Evidence is dated and cited. Where a claim comes from a schema or an API, the command is given so it
can be re-run rather than believed.

## Spike 1: agentgateway's prompt guards versus guard-proxy

### What agentgateway v1.5.0 actually ships

Read from `verify/schemas/agentgateway-v1.5.0-config.json`, the upstream schema for the exact image
tag we run (vendored 2026-09-21, unmodified):

| Hook | Variants |
|---|---|
| `promptGuard.request` | `regex`, `webhook`, `openAIModeration`, `bedrockGuardrails`, `googleModelArmor`, `azureContentSafety` |
| `promptGuard.response` | `regex`, `webhook`, `bedrockGuardrails`, `googleModelArmor`, `azureContentSafety` |

Two details that decide the question:

- **The regex guard's built-in patterns are five**: `ssn`, `creditCard`, `phoneNumber`, `email`,
  `caSin`. Everything else is a pattern you write. Action is `mask` or reject.
- **The inspection scope is wider than ours**: `systemPrompt`, `messages`, `toolOutput`, `toolArgs`.
  guard-proxy sees the prompt and the completion. It does not see tool arguments or tool results.

### What guard-proxy does that this does not cover

| guard-proxy does | agentgateway equivalent |
|---|---|
| Output regex over the planted sentinel patterns | `promptGuard.response.regex` with the same patterns. **Covered.** |
| Input prompt-injection classification (DeBERTa, local, model-based) | No local classifier. The four managed options are all remote third-party services; `webhook` is the only self-hosted path, and the thing a webhook would call is LLM Guard. **Not covered.** |
| The cost cap that ends Challenge 4 (`COST_CAP_USD`, live toggle) | **Correction, 2026-09-22: this line said "not a gateway feature" and was wrong.** agentgateway v1.5.0 has `Budget` on an API key, `BudgetLimitUnit: [USD, Tokens]`, `BudgetExceededAction: [Audit, Block]`, over a rolling window. Verified in the vendored schema. What survives is the limitation both share, below. |
| `MODEL_TIER`, `RATE_LIMIT_RPM`, `PROXY_FAIL_CLOSED` as live demo toggles | Not gateway features. |
| `STREAM_PROMPTS`, the live prompt feed the room watches | Not a gateway feature. |
| The span attributes the Datadog recipe reads | agentgateway emits its own spans; these are ours. |

### The spend cap, corrected

Both implementations meter AFTER the response and refuse the NEXT request. agentgateway's own schema
says so: "Usage is charged after an LLM response when the provider reports the tokens or cost required
by the configured unit. Requests with unavailable usage are logged but cannot be charged or blocked
retroactively." `proxy.py` does the same thing: spend crosses `BUDGET_CAP_USD`, and further requests
are refused before the model is called.

So neither stops the request that crosses the line, and neither bounds a single very expensive request.
The honest difference between them is scope, not capability: ours is per session and per cluster, the
gateway's is per API key. Spend enforcement is therefore NOT a reason to keep guard-proxy. The input
classifier is.

### Finding

The gateway can take over the **output** guard outright, and cannot take over the **input** guard
without either a remote paid service or a webhook pointed back at the thing it was supposed to replace.
Everything else guard-proxy does is workshop machinery the gateway has no opinion about.

There is also an argument for keeping both that is not about coverage. The workshop's thesis is about
where a control lives, and two guards at two different layers, one in the gateway and one in an
injected proxy, is a better demonstration of that than either alone.

### Recommendation

Keep guard-proxy. Separately, and only if the inference bind (#394) goes live, add
`promptGuard.response.regex` on the Bedrock route with the sentinel patterns, as a second independent
control rather than a replacement. That is a small config change and it makes the "defense at two
layers" point concrete instead of narrated.

What should change now is not the code but the claim: agentgateway ships prompt guards, they attach to
`llm.models[]` backends, and the reason we do not lean on them for input is that the only self-hosted
option is a webhook to a classifier we would still have to run.

## Spike 2: a fork of LLM Guard

### The question has changed since it was asked

`protectai/llm-guard` is **archived**. Verified 2026-09-21:

```bash
gh api repos/protectai/llm-guard --jq '"archived=\(.archived) pushed=\(.pushed_at)"'
# archived=true pushed=2026-07-08T23:58:40Z
gh api repos/protectai/llm-guard/commits --jq '.[0].commit.message'
# Archiving Project (#355)
```

The last functional commit is 2025-09-03; the archiving commit on 2026-07-08 adds five lines to the
README and nothing else. The latest tag is v0.3.16, which is the version we run.

The README's own warning covers more than the code:

> **THIS PROJECT HAS BEEN ARCHIVED.** This project and its associated models on Hugging Face are no
> longer under active development or maintained.

That second clause is the one that matters to us. Our input guard is
`ProtectAI/deberta-v3-base-prompt-injection-v2`, pulled from the same unmaintained Hugging Face org at
image build time.

At archive: 3,209 stars, 461 forks, 38 open issues. MIT licensed, so a fork carries no legal friction.

### What we already have

`images/llm-guard/Dockerfile` builds
`ghcr.io/peopleforrester/watch-it-burn:llm-guard-0.3.16-offline.2`: the upstream API server with the
classifier baked in as a local directory and Hugging Face forced offline, because a cluster running
Challenge 1's default-deny egress cannot reach the Hub on its first scan (#241).

That is not a fork of the library. It is a packaging of it, and it is the thing people actually hit:
the upstream image cannot start a scan without network access to a model host.

### Finding

Two different commitments are being conflated under the word "fork".

- **Publishing the offline image** is nearly free. The Dockerfile exists, the image is built and
  pushed, the weights are already inside it, and the reason it exists is a problem anyone running LLM
  Guard behind a default-deny policy has. It also insures us against the Hugging Face repo going away,
  which the README says is now possible.
- **Forking the library** means owning scanner code, the model choices behind it, and the expectation
  of a maintained security tool with three thousand stars behind its name. Nothing in this workshop
  needs that, and a half-maintained security fork is worse for the people who adopt it than no fork.

### Recommendation

Publish the image and the Dockerfile with a short README saying exactly what it is: upstream v0.3.16,
archived by Protect AI in July, packaged to run offline. Do not fork the library. If somebody wants
the library maintained, the honest answer is that it needs a maintainer, not a mirror.

Worth stating on stage either way: the guardrail layer is the one layer of this stack with no
foundation behind it, and the most widely used open tool in it was archived two months before this
workshop ran. That is the point the governance table in `STACK-WALKTHROUGH.md` makes, with a date on it.
