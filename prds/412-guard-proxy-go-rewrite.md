# PRD #412: guard-proxy, rewritten in Go as a product

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/412
**Code lives in**: https://github.com/peopleforrester/guard-proxy-agenticburn (submodule at
`gitops/ai-layer/guard-proxy/`, #411)
**Status**: **Awaiting approval (lifecycle 1.3).** No Go code until this plan is approved.
**Decided by Michael, 2026-10-05**: rewrite in Go, because it is expected to become a product and Go's
libraries suit it better than Rust's; fold in what LiteLLM does better.

---

## Problem

guard-proxy is 1,076 lines of dependency-free Python on `http.server`. It works, it is tuned against
live attacker behavior across two deliveries, and it is the wrong foundation for a product:

- `ThreadingHTTPServer` is thread-per-connection with no backpressure, keep-alive tuning, graceful
  shutdown or limits. Acceptable for one workshop cluster, not for a proxy in front of a paid API.
- It is delivered as a ConfigMap mounted into a stock Python image, so there is no artifact to sign,
  scan, pin or retain.
- Its spend cap meters **after** the response, so it can only block the next request. A single
  expensive request is unbounded.
- Its guards are hardwired: one LLM Guard endpoint for input, one regex for output.
- Its 21 environment variables overlap (`BUDGET_CAP_USD` and `COST_CAP_USD`, `INPUT_GUARD` and
  `INPUT_CLASSIFIER`), and a typo in a name silently disables a guard.

## What to fold in, and from where

The 2026-09-22 research (`docs/research/2026-09-22-guardrail-layer/`) compared guard-proxy with 26
projects. Two of them do things better, and those things are the scope of this rewrite beyond parity.

### From LiteLLM

| Capability | LiteLLM | guard-proxy today |
|---|---|---|
| **Pre-call budget reservation** | Estimates the request's maximum cost, reserves it, rejects before the provider is called, reconciles after. MIT, `litellm/proxy/spend_tracking/budget_reservation.py`, first commit 2026-04-30 | Post-hoc. Blocks the next request only |
| **Budget scopes** | global, team, team member, user, virtual key, end-user, per-provider, with `budget_duration` resets | per-session and per-cluster |
| **Token-aware rate limits** | RPM and TPM per key, team, user or model; input, output or total | RPM, cluster-wide |
| **Routing** | aliases, weighted routing, provider fallbacks | one `MODEL_TIER` switch |
| **Pluggable guardrails** | `pre_call`, `during_call`, `post_call`, `logging_only` modes; a generic guardrail API | hardwired |
| **Per-request cost** | `x-litellm-response-cost` response header | `/cost` endpoint only |
| **OTel content capture modes** | `NO_CONTENT` / `SPAN_ONLY` / `EVENT_ONLY` / `SPAN_AND_EVENT` | one on/off toggle |
| **Streaming responses** | handled | guards work on a complete body |

### From agentgateway

| Capability | agentgateway v1.5.0 |
|---|---|
| **Declarative response regex** | built-in patterns (`ssn`, `creditCard`, `phoneNumber`, `email`, `caSin`) plus custom, with `mask` or `reject` |
| **Inspection beyond prompt and completion** | guards can scope to `toolArgs` and `toolOutput`, which is where agentic injection actually lands |
| **A streaming guard mode** | for streamed responses and realtime websockets |

### Where the rewrite should beat both

LiteLLM's reservation can still overshoot when a request sets no `max_tokens`, because there is no
output ceiling to reserve against; the research flagged this, and LiteLLM documents no no-overshoot
guarantee. guard-proxy can close that hole outright: **cap `max_tokens` at the proxy**, so the
reservation is a true upper bound rather than an estimate. A spend cap that cannot be exceeded by a
single request is the product claim neither competitor can make.

### What guard-proxy keeps that nobody else has

- **No database.** LiteLLM's budgets need Postgres. This must run fifty times over on attendee
  clusters, so budget state stays in-process or in a small embedded store.
- **The live prompt feed** (`/prompts`), with no precedent in any of the 26 projects.
- **Live toggles** (`/toggle`, `/guards`, `/controls`) that the workshop flips mid-session.
- **Fail closed by default**, explicitly. LiteLLM also defaults to fail-closed; keep parity.
- **Platform-injected placement.** It applies to every workload without the developer opting in.

## What Go gives, and what it does not

Verified 2026-10-05 against proxy.golang.org, go.dev and the GitHub API.

| Need | Choice | Version | Note |
|---|---|---|---|
| Language | Go | 1.27.1 | latest stable |
| Reverse proxy, HTTP server | `net/http`, `net/http/httputil` | stdlib | real backpressure, timeouts, graceful shutdown |
| Tracing | `go.opentelemetry.io/otel` + `sdk` + `otlptracegrpc` | v1.47.0 (2026-10-02) | |
| Rate limiting | `golang.org/x/time/rate` | v0.16.0 | token bucket |
| Metrics | `github.com/prometheus/client_golang` | v1.24.1 | |
| Config | `go.yaml.in/yaml/v3` | v3.0.5 (2026-07-26) | **not** `gopkg.in/yaml.v3`: `go-yaml/yaml` was archived, last pushed 2025-04-01 |
| Token counting, Claude on Bedrock | `aws-sdk-go-v2/service/bedrockruntime` `CountTokens` | v1.63.1 (2026-09-24) | exact pre-call input count, through the Bedrock endpoint the agent already uses |
| Token counting, OpenAI models | `github.com/pkoukk/tiktoken-go` | v0.1.8 (2025-09-10) | OpenAI tokenizers only; last release a year old |

Two things Go does **not** give, and the plan has to own them:

- **No gen_ai semantic-convention constants.** The newest semconv package in otel-go v1.47.0
  (`semconv/v1.43.0`) contains **zero** `gen_ai.*` attributes and no `genaiconv` package. Checked
  with a positive control: `http.request.method` appears nine times in the same file. This matches
  the research: the gen_ai conventions moved to their own repository, which has no tagged release.
  So the attribute names come from this repo's own `weaver/registry/guard-proxy-spans.yaml`, which is
  already the span contract and already checked in CI, generated into Go constants rather than typed
  by hand.
- **No tokenizer for Claude in Go.** `CountTokens` covers Bedrock with an API call per request; that
  adds latency and is the main design trade-off below.

## Architecture

One static binary, built into a signed, digest-pinned image, replacing the ConfigMap delivery.

```
request ─▶ listener ─▶ identity ─▶ rate limit ─▶ budget RESERVE ─▶ input guards ─▶ upstream
                                     (RPM+TPM)    (fail closed)     (pre_call)       │
response ◀─ telemetry ◀─ budget RECONCILE ◀─ output guards ◀─────────────────────────┘
           (gen_ai spans)  (actual cost)       (post_call, streaming-aware)
```

- **Guards are a Go interface.** Implementations: the LLM Guard API client (today's input guard),
  declarative regex (today's output guard, with agentgateway's built-ins), and Bedrock
  `ApplyGuardrail` as a remote option. Each declares the phases it runs in.
- **Budgets are scoped.** Per cluster, per session, per identity, each with a window. State lives in
  the process. Whether it must survive a restart is an open question below.
- **Config is one YAML file, validated at start.** An unknown key fails startup instead of silently
  disabling a guard. The current environment variables map onto it for one release so the workshop
  manifests keep working.
- **Live toggles stay**, as an authenticated admin API, because the workshop depends on them.

## The safety net: a black-box conformance suite, written first

The existing Python tests import `proxy.py` as a module and test its internals, so none of them can
run against a Go binary. Rewriting without a shared contract would mean trusting that the Go version
behaves like the tuned Python one.

So the **first deliverable is an HTTP conformance suite** that treats the proxy as a black box:
real requests in, observed responses and telemetry out, covering every guard, every endpoint, every
toggle, fail-closed, and the spend cap. It is written against the **Python** implementation first and
must pass there, which proves it captures today's behavior. The Go implementation then has to pass
the same suite. This is the TDD gate for the whole rewrite.

## Milestones

| # | Deliverable | Done when |
|---|---|---|
| M0 | Conformance suite against the Python proxy | passes against `proxy.py`; every guard, endpoint, toggle and failure mode covered |
| M1 | Go skeleton: listener, upstream proxying, config validation, health | conformance passes for the pass-through cases |
| M2 | Guards at parity: LLM Guard input, regex output, fail closed | conformance passes for every guard case |
| M3 | Budgets: reservation with a capped `max_tokens`, scopes, `CountTokens` | a single request cannot exceed the cap, proven by a test that tries |
| M4 | Rate limits (RPM and TPM), routing, toggles, the prompt feed | full conformance passes |
| M5 | Telemetry: gen_ai spans from weaver-generated constants, content-capture modes | Datadog LLM Observability shows input and output, as it does today |
| M6 | Image: signed with cosign 2.x, digest-pinned, ConfigMap delivery retired | `verify/sign-images.sh --check` passes; workshop deploys the image |
| M7 | Live validation on a cluster | all eight challenges pass attack, fix, re-attack |

M0 through M2 is the minimum to replace the Python in the workshop. M3 is the product claim.

## Open questions

1. **Per-request `CountTokens` adds a round trip to Bedrock before every call.** Accept the latency for
   an exact count, or count with a conservative byte-based over-estimate and accept a looser bound?
   Either way the request is refused when the estimate cannot be produced. No silent fallback.
   `[Answer]:`
2. **Must budget state survive a restart?** In-process is simplest and matches fifty disposable
   clusters. A product will want persistence, which means an embedded store, not Postgres.
   `[Answer]:`
3. **Product boundary.** Is the workshop apparatus (live prompt feed, `/controls`) part of the product,
   or a build tag that only the workshop enables? `[Answer]:`
4. **Keep the ConfigMap fast-edit loop for workshop days?** It lets a fix reach a live cluster in
   seconds, and a compiled binary loses it. `[Answer]:`
5. **License for the product.** The repo is MIT today. A product may want something else, and that
   choice is easier before outside contributions arrive. `[Answer]:`

## Out of scope

- Replacing LLM Guard's classifier. guard-proxy calls a scanner; which scanner is a separate question.
- Multi-tenant SaaS hosting. This is a platform-injected, in-cluster proxy.
- Agent frameworks. guard-proxy stays below the framework, which is what makes it platform-injected
  rather than developer-shipped.
