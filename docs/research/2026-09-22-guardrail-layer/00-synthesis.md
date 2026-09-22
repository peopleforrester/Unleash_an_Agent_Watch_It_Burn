# Is the guardrail layer a unique problem? Four research passes, one answer

2026-09-22. Michael asked whether guard-proxy solves something the industry has not solved: whether
an open-source equivalent exists, whether the functions could live somewhere else in the chain owned
by something that already exists, what the commercial analogs are, and what forking LLM Guard would
actually cost.

Four research passes ran in parallel. Their full reports sit beside this file and every claim in them
carries a source and a date. This is the synthesis, and where it corrects something this repo already
said, it says so.

| | Report |
|---|---|
| 01 | Open-source equivalents, 26 projects, function-by-function |
| 02 | Where the functions could live: seven layers, six functions |
| 03 | The commercial landscape and the acquisition record |
| 04 | What a fork costs, measured, and how to break the Hugging Face dependency |

## The answer

**No, and the honest version is better material than the claim we were making.**

guard-proxy does eight jobs. Seven of them are served somewhere in open source, and the core
combination was served by a single project, LiteLLM, seven weeks before guard-proxy's first commit.
What is genuinely unowned is narrower and more interesting than "nobody does this".

## The timeline that settles it

Every date verified against a primary source.

| Date | Event |
|---|---|
| 2025-07-22 | Palo Alto Networks completes its acquisition of Protect AI |
| **2026-04-30** | **LiteLLM's pre-call budget reservation lands**, in the MIT tree |
| **2026-06-17** | **guard-proxy's first commit here** (`db3ed42`) |
| 2026-07-08 / 09 | Protect AI archives LLM Guard. Last push 2026-07-08T23:58:40Z; the banner reads Jul 9 |
| **2026-08-25** | agentgateway merges API-key scoped budgets (PR #3143) |
| 2026-08-27 | agentgateway v1.5.0 ships them. v1.4.1's schema has no `Budget`; v1.5.0's does. Ancestry checked: commit `67906b4` is not in v1.4.0 and is 22 behind v1.5.0, so v1.5.0 contains it |
| 2026-09-08 | We run Portland |
| 2026-09-10 | Envoy AI Gateway becomes Agent Router and joins AAIF |

LiteLLM had a **stronger** spend cap than ours before we wrote ours. It estimates the request's
maximum cost, reserves it, and rejects before the provider is called. guard-proxy and agentgateway
both charge after the response and block the next request, which means neither bounds a single
expensive call. The reservation code is at `litellm/proxy/spend_tracking/budget_reservation.py`, 62 KB,
outside the `enterprise/` directory, and LiteLLM's LICENSE puts everything outside that directory
under MIT.

## The coverage, function by function

guard-proxy's eight jobs against the field:

| # | Function | Served in open source? | By whom |
|---|---|---|---|
| 1 | Input injection scanning | **Partly** | Every proxy and gateway offers a socket or a remote service. **Nobody ships a local classifier.** |
| 2 | Output secret-leak scanning | Yes | agentgateway's declarative response regex is the cleanest. LiteLLM needs a Python class |
| 3 | Hard USD spend cap | Yes, once | LiteLLM, pre-call. agentgateway post-hoc. Kong Enterprise only |
| 4 | Rate limiting | Yes | Least contested cell in the study |
| 5 | Model tier switch | Yes | Every proxy and gateway |
| 6 | Fail closed | Yes | LiteLLM's `generic_guardrail_api` defaults to `unreachable_fallback="fail_closed"` with `fail_on_error=True`; per-policy in agentgateway. An earlier pass recorded this as undocumented from a search that was too narrow |
| 7 | OTel gen_ai spans with content | Yes | LiteLLM, agentgateway, Kong 2.0+ Enterprise |
| 8 | Live prompt feed | **No** | No precedent in any of the 26 projects |

## What is genuinely unowned

Three things, stated precisely, because the loose version does not survive a room with phones out.

**1. A spend cap enforced BEFORE the spend has exactly one home, and that home is a purpose-built
proxy.** Not the model provider: no provider guardrail has a budget. Not the mesh, the serving layer,
admission, or observability. LiteLLM does it correctly, which means the question was never "does this
exist" but "write one or adopt one".

**2. Platform-injected input scanning with a self-hosted ML classifier has no owner.** agentgateway's
`RequestGuard` is a closed `oneOf` with six variants: regex (local, but pattern matching is not
classification), a webhook (a socket you must fill), and four remote paid services. Searching its
entire 370 KB schema for `classifier`, `deberta`, `onnx`, `transformer`, `model_path` returns zero.

One exception, found on a second pass and worth stating precisely rather than glossing: **LiteLLM
ships a local filter** at `litellm/proxy/guardrails/guardrail_hooks/litellm_content_filter/`, MIT,
with zero HTTP calls (grep for `http_handler|httpx|requests\.|api_base` returns 0), a 38 KB
`patterns.json`, and category files named `prompt_injection_jailbreak.yaml`,
`prompt_injection_data_exfiltration.yaml`, `prompt_injection_sql.yaml`,
`prompt_injection_system_prompt.yaml`, `prompt_injection_malicious_code.yaml`.

That is local and it is injection-specific, and it is **pattern-based, not an ML classifier**. So the
accurate claim is narrower: no gateway or proxy ships a local ML classifier, which makes guard-proxy's
sidecar-plus-model shape standard rather than a workaround. The turnkey ML options are all remote,
which means egress from a default-deny cluster and a per-request fee, and the most widely used open
tool behind that socket was archived two months before this workshop ran.

**3. A room-visible live prompt feed has no precedent anywhere.** That one is workshop apparatus, not
a product category, and was always going to be bespoke.

## The sentence that carries the talk

From report 02, and it is the strongest thing to come out of this study:

> Every managed guardrail blocks on content policy, never on volume. A benign prompt repeated ten
> thousand times passes Bedrock Guardrails, Model Armor, Prompt Shields and OpenAI moderation in full,
> and bills every time.

Denial of wallet is not a content-safety problem, and the entire content-safety industry is aimed
elsewhere. That is why Challenge 4 has no vendor answer, and it is checkable by anyone in the room.

A second finding of the same shape, and it is the platform-injected thesis restated by someone who
was not trying to prove it:

> All three provider guards are callable standalone against any model, so "the provider could own
> input scanning" is true on capability and false on control. A standalone API is something the
> application chooses to call, and nothing makes it call it.

Only admission control can compel a control to be present. That is the argument the workshop makes,
and the research reached it independently.

## The standard has no word for money

The OpenTelemetry gen_ai semantic conventions moved to their own repo (`semantic-conventions-genai`,
created 2026-05-05, no tagged releases). 48 registry attributes, every one at `Development` status:

```
grep -ciE "token"                              registry.yaml metrics.yaml  -> 72
grep -ciE "cost|usd|spend|budget|price|dollar" registry.yaml metrics.yaml  ->  0
```

Token usage is deep: input, output, reasoning, cache read and write, text, image and audio splits.
Cost is derivable with a price table you supply and is not observable. A spend cap cannot be expressed
in OTel vocabulary at all. Message content capture is `Opt-In`, the weakest requirement level in the
spec, and typed `any`.

## The commercial picture

**Nine acquisitions in about 24 months, seven inside a 13-month window.** Prices from the acquirers'
own filings where they exist, which is not what the press reported:

| Closed | Deal | Price | The open source afterwards |
|---|---|---|---|
| Oct 2024 | Cisco / Robust Intelligence | undisclosed | none existed |
| 2025-07-22 | Palo Alto / Protect AI | ~$700M, press only | **llm-guard archived** 2026-07-08, 11.5 months after the deal closed; modelscan, nbdefense, vulnhuntr, ai-exploits left public and stale. `rebuff` is also archived but its last commit is 2024-01-25, eighteen months before the deal, so it is weak support for the pattern. GitHub returns `archived_at: null` for both, so the archive action itself cannot be dated or attributed |
| 2025-09-05 | SentinelOne / Prompt Security | **$159.3M** per its 10-Q, not the reported $250M | kept alive (Prompt Fuzzer) |
| 2025-09-29 | F5 / CalypsoAI | $180M | none existed |
| Sept 2025 | Cato / Aim Security | ~$350M, press only | none existed |
| Sept 2025 | CrowdStrike / Pangea | ~$260M, press only | none existed |
| Oct 2025 | Check Point / Lakera | **$187M** per its 6-K, not the reported $300M | kept alive and extended (Gandalf, PINT) |
| 2025 | Tenable / Apex Security | >$105M, press only | none existed |
| 2026-05-29 | Palo Alto / Portkey | undisclosed | folding into Prisma AIRS |

The pattern: **open source survived where it was lead generation and was archived where it substituted
for the paid runtime product.** LLM Guard is the strong case for it. `rebuff` was already abandoned
before its acquirer arrived, so it should not be cited as a second example.

Two structural facts underneath that. **Spend and content enforcement live in different products**:
not one of the eleven commercial security vendors documents a hard USD cap, and the three products
that enforce spend are gateways (Cloudflare AI Gateway, LiteLLM, Portkey). Palo Alto buying Portkey is
that convergence happening commercially. And **self-hosting is the minority posture**: only Lakera
Enterprise, Operant AI and Cisco's data plane run in your cluster, and Cisco still needs a SaaS
control plane.

## The foundations produce taxonomy, not guards

| Body | What it actually produces |
|---|---|
| OWASP GenAI | A taxonomy. Names LLM06 Unbounded Consumption and ships nothing that enforces against it |
| MITRE ATLAS | A taxonomy (not independently verified this session) |
| CoSAI | Papers, plus one ruleset donated by Cisco |
| AIUC | A certification scheme backed by insurance |
| AAIF | Running code: MCP, goose, AGENTS.md, agentgateway, A2A, **Agent Router** |
| CNCF | Running code: kgateway, OpenTelemetry, Falco, SPIFFE, Dapr |
| LF TRACE | A specification for attesting what ran, not code that enforces what may run |

The sharpest data point available for the gap: **Agent Router shipped a 1.0 and joined a Linux
Foundation body with no prompt guards and no spend controls, neither shipped nor on its roadmap.** The
foundation that now owns the routing layer has taken no position on the guard layer.

A trap worth knowing before someone corrects the governance table from the wrong page: agentgateway
appears in the **CNCF landscape** under Network / Gateway, with a `repo_url` and no `project:` field.
The landscape maps the ecosystem; it is not a list of CNCF projects. `aaif.io/projects` is the
authority.

## What forking LLM Guard would cost, measured

| | |
|---|---|
| Direct dependencies | 12, resolving to 98 packages, 119 with the onnxruntime extra, **15 of them NVIDIA CUDA wheels** |
| Exact `==` pins among 13 direct requirements | **7.** Every security bump is a source change and a release, not a lockfile refresh |
| Advisories against llm-guard itself | **zero.** All exposure is inherited |
| What a fork inherits | **12 open issues and 26 open pull requests**, not the 38 issues GitHub's count implies |
| Keeping it SAFE | 44 to 96 hours in year one, then ~7 h/month. Roughly $20k then $13k/year |
| Keeping it ALIVE | ~64 h/month, about 0.4 FTE. Its own peak was 0.75 to 1.0 FTE |
| Forks above 2 stars, 14 months on | **none** |

And the cost nobody inherits: the classifier is a fine-tune over seven datasets, so refreshing it
against new injection techniques is an ML workload with no relationship to the software maintenance
above. **A perfectly maintained fork still ages**, because the Python can be current while the
detector is not.

Verdict from report 04: do not fork. Pin what we have by digest, stop building from upstream, and
re-evaluate the control rather than the library.

## What this means for our decisions

**Decision A (give the offline image a home): still yes, and the size question has a one-flag answer.**
The image is **4,211 MB compressed across 15 layers**. Measured composition: **roughly 78% of it is
CUDA**, on nodes that have no GPU. `llm_guard/transformers_helpers.py` selects
`CUDAExecutionProvider` only when a GPU is present and takes the CPU branch every time on a
t3.2xlarge, so those wheels are never loaded or linked.

Four dependency resolutions run 2026-09-22 with `uv pip compile`:

| Stack | Packages | NVIDIA wheels | Wheel payload |
|---|---|---|---|
| what we ship today | 119 | 15 | **3,549 MB** |
| same, plus `--extra-index-url https://download.pytorch.org/whl/cpu` | 100 | **0** | **399 MB** |
| optimum + transformers + onnxruntime, no llm-guard | 29 | 0 | 241 MB |
| onnxruntime + tokenizers + numpy, direct ONNX | 18 | 0 | 59 MB |

**One index flag removes 3,150 MB, 89% of the dependency payload, and changes no llm-guard source.**
It is a build argument in `images/llm-guard/Dockerfile`, not a fork. Estimated image afterwards:
**~1,050 to 1,250 MB**, approximate because it is derived from measured wheel sizes rather than a
built image.

The minimal rebuild (direct ONNX, no optimum, no torch, no presidio or spaCy) saves only about another
150 MB, because once CUDA is gone the 750 MB model dominates, and it costs a fork plus a rewrite of
the scanner loading path. Not worth it.

Sequencing: do the CPU-index change and the model mirror from report 04 in the SAME rebuild. Both
touch the same Dockerfile and both need one image build and one fleet redeploy. (#413, #414)

**Decision B (fork and maintain): the deferral is now costed and the answer is no.** $13k/year
forever for a library we do not own, no institution behind it, no fork above two stars, and a detector
that ages regardless. (#416)

**Decision C (mirror): yes, and it is now the load-bearing move**, not the consolation prize. Rank 1
recommendation is an OCI artifact in our own GHCR namespace, digest-pinned and cosign-signed. Note
that **four of the eight candidate mirroring projects have themselves changed organizations**,
including `iterative/dvc` to `treeverse/dvc`: pin by a URL that survives a redirect and never hardcode
an org name. (#414, #416)

**guard-proxy: the language question is the second question.** Before Python versus Rust or Go, answer
whether it should exist at all or be LiteLLM plus our classifier plus a thin shim. Rewriting it in
another language doubles down on the part that was never the hard part. The arguments for keeping it
are real (1,076 lines with zero dependencies against LiteLLM's Postgres and Python surface per
cluster, and the live feed has no precedent) but they are engineering arguments, not scarcity
arguments. Fail-closed is no longer among them: LiteLLM defaults to it. (#412)

## Claims that survive scrutiny, and claims that do not

**Do not say:** nothing like this existed, or we built this because there was no alternative. LiteLLM
is one search away and predates us.

**Do say**, all checkable:

- The content-guardrail ecosystem and the cost-control ecosystem are almost entirely disjoint, and
  LiteLLM is the only open-source project that spans both.
- Every managed guardrail blocks on content, never on volume, so denial of wallet has no vendor answer.
- OpenTelemetry's AI conventions define 48 attributes and not one of them is money.
- No proxy or gateway ships a local ML classifier. LiteLLM ships a local pattern-based filter with
  injection categories; everything stronger is delegated, and the tool most of them delegate to was
  archived on 2026-07-08, two months before this workshop ran.
- A provider-side guard is something an application chooses to call. Only admission control can make
  a control present whether or not the developer wanted it.
- Nine acquisitions in 24 months, and the open source survived exactly where it was marketing.

## What remains unverified

Carried forward rather than smoothed over:

- Whether LiteLLM emitted OTel `gen_ai` spans as of 2026-06-17. It does today; the date is unverified,
  so one leg of the "it was already served" claim has an unknown at our build date.
- Whether a single LiteLLM request can overshoot its reserved estimate (no `max_tokens`, reasoning
  tokens, tier pricing resolved at response time). The reservation design closes the concurrency race;
  no no-overshoot guarantee is documented, and the report flags its own reading as inference.
- MITRE ATLAS was never checked directly.
- Deal values for Protect AI, Aim, Pangea and Apex are press-only.
- "Still independent" for Noma, Pillar, Zenity, Straiker, WitnessAI, HiddenLayer, Operant and Arthur
  is not-yet-contradicted rather than confirmed; the search budget ran out.
