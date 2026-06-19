ABOUTME: Grounded research spike on agentgateway (Solo.io / Linux Foundation) for the
ABOUTME: "Watch It Burn" workshop, version, guardrail mechanism, MCP policy, fallback assessment.

# agentgateway, Research Spike (Phase 4 / Section 5 FLAG resolution)

## Verification Method

- Method: live web research against official agentgateway docs (`agentgateway.dev/docs`),
  the Solo.io Enterprise docs (`docs.solo.io/agentgateway`), and the GitHub release
  feed via the GitHub REST API. Dated **2026-06-15**.
- Version data was confirmed against the GitHub API directly (`api.github.com/repos/agentgateway/agentgateway/releases`)
  because a plain page fetch of the releases HTML mis-stated the years. The API JSON
  (`published_at`) is the source of truth used below.
- Each material claim carries its source URL inline. Where a doc page returned only an
  index/overview and not field-level detail, that is marked Unverified rather than guessed.

## Verified

### 1. Current stable version (as of 2026-06-15)

- **Latest stable OSS release: `v1.2.1`, published 2026-05-15.**
  Prior stable: `v1.2.0` (2026-05-14), `v1.1.0` (2026-04-09), `v1.0.1` (2026-03-20).
  Beta in flight: `v1.3.0-beta.1` (2026-06-12), `v1.3.0-alpha.1` (2026-05-23). Do NOT
  pin a v1.3.x prerelease for the workshop.
  Source: `https://api.github.com/repos/agentgateway/agentgateway/releases`
- The OSS project now lives under the **`agentgateway/agentgateway`** GitHub org (donated
  to the Linux Foundation; as of June 2026 it is a hosted initiative under the Agentic AI
  Foundation / AAIF). Source: `https://aaif.io/blog/use-agentgateway-to-mediate-mcp-and-llm-traffic-at-solo-io/`,
  `https://www.solo.io/blog/solo-contributes-agentgateway-linux-foundation`
- **Versioning caveat that matters for the build:** the OSS binary is on `1.x`. The
  Solo.io *Enterprise* product ("Solo Enterprise for agentgateway") is independently
  versioned `2.1.x / 2.2.x / 2.3.x`. Docs pages under `docs.solo.io/agentgateway/2.3.x/...`
  are the Enterprise distribution; docs under `agentgateway.dev/docs/standalone/latest/...`
  are the OSS standalone binary. They are NOT the same version line. Pin to the OSS
  standalone docs for a no-license build.

### 2. Mechanism, OUTPUT guardrail on the agent's response

The mechanism is a **native prompt-guard with a `webhook` action on the response phase**.
agentgateway calls an external HTTP webhook server with the LLM response body; the server
returns Pass / Mask / Reject. This is the path that calls out to an external service
(LLM Guard would be wrapped by such a server).

- Guardrails attach as **prompt guards** that run on the request phase, the response
  phase, or both. Source: `https://agentgateway.dev/docs/standalone/latest/llm/prompt-guards/overview/`
- Three guard types in OSS standalone: **regex**, **external moderation** (built-in
  OpenAI / Bedrock / Google moderation endpoints), and **custom webhook**.
  Source: same overview page.
- Webhook config (OSS standalone) sits under the LLM backend model's `guardrails`:
  ```yaml
  llm:
    models:
    - name: "*"
      provider: openAI          # backend must be a recognized LLM provider
      params:
        model: gpt-3.5-turbo
        apiKey: "$OPENAI_API_KEY"
      guardrails:
        request:
        - webhook:
            target:
              host: content-safety-webhook.example.com:8000
        response:
        - webhook:
            target:
              host: content-safety-webhook.example.com:8000
  ```
  Source: `https://agentgateway.dev/docs/standalone/latest/llm/prompt-guards/webhooks/`
  (field path `llm.models[].guardrails.response[].webhook.target.host`).

- The external webhook server contract (the API LLM Guard's wrapper must speak):
  - `POST /request`, body `{ body: { messages: [{role, content}] } }`
  - `POST /response`, body `{ body: { choices: [{ message: {role, content} }] } }`
  - Action responses: `PassAction {reason?}`, `MaskAction {body, reason?}`,
    `RejectAction {body, status_code, reason?}`.
  - **RejectAction is available on `/request` but NOT on `/response`**, the response
    path can only Pass or **Mask**, not hard-reject. This directly affects the attack-4
    "blocked or redacted" claim: on the response the deterministic outcome is **redaction
    (mask), not a hard block**. Plan attendee copy around redaction.
  Source: `https://docs.solo.io/agentgateway/2.1.x/llm/guardrail-api/openapi-spec/`
  and the OpenAPI YAML at
  `https://raw.githubusercontent.com/solo-io/gloo-gateway-use-cases/refs/heads/main/ai-guardrail-webhook-server/docs/gloo-ai-gateway-guardrail-webhook-openapi.yaml`

It is therefore **NOT** Envoy `ext_proc` and **NOT** an in-process native scanner. It is
a webhook/transformation filter calling an external HTTP server. That external server is
where LLM Guard runs.

### 3. Mechanism, INPUT guardrail on the incoming request

Same prompt-guard system, **request phase**. Use `guardrails.request[].webhook` pointing
at the same (or a separate) LLM-Guard-backed webhook server, OR the native **regex** guard
for deterministic pattern blocks, OR **external moderation** for provider moderation.
Request-phase webhook supports `RejectAction` (hard block with a chosen `status_code`),
so prompt-injection scanning *can* hard-block on input.
Source: `https://agentgateway.dev/docs/standalone/latest/llm/prompt-guards/webhooks/`,
OpenAPI spec above.

### 4. MCP policy (the "bad MCP server / excessive agency" beat)

agentgateway has real, current MCP policy, this is a genuine strength, not vapor.

- **MCP authorization** via an `mcpAuthorization` policy whose `rules` are **CEL
  expressions** evaluated per MCP method invocation (`list_tools`, `call_tool`).
  Attachable at backend level (all MCP targets) or per individual target.
  Source: `https://agentgateway.dev/docs/standalone/latest/mcp/mcp-authz/`
- CEL variables include `mcp.tool.name`, `mcp.tool.target`, `mcp.prompt.name`,
  `mcp.resource.name`, and JWT claims (`jwt.sub`, `jwt.<claim>`, `has(...)`).
  Rules OR together; any match grants access.
  ```yaml
  policies:
    mcpAuthorization:
      rules:
        - 'mcp.tool.name == "echo"'
        - 'jwt.sub == "test-user" && mcp.tool.name == "add"'
        - '"admin" in jwt.roles'
  ```
- **Per-tool authorization and tool filtering both exist:** if a tool is not allowed,
  agentgateway **filters it out of `list_tools` responses**, so the agent never sees a
  tool it cannot call. That covers per-tool allowlisting and effectively tool filtering.
  Source: same page + `https://agentgateway.dev/blog/2025-08-12-mcp-authorization-following-the-spec/`
- **MCP server allowlisting:** done structurally via the `targets` list (only configured
  MCP servers are reachable) plus per-target `mcpAuthorization`.
- **MCP authentication:** OAuth 2.0 / JWT, agentgateway acts as resource server; built-in
  Keycloak and Auth0 IdP support. Source: `https://agentgateway.dev/docs/standalone/latest/mcp/mcp-authn/`

### 5. Fallback assessment, LLM Guard reverse-proxy sidecar on the response path

The spec's documented fallback (an LLM Guard reverse-proxy sidecar inspecting the agent
response) is **sound and, given the constraint below, likely the cleaner primary** for
this build. It does not depend on agentgateway recognizing the agent as an LLM provider,
does not inherit the response-phase no-Reject limitation, and keeps the deterministic
LLM Guard scanners (Secrets, Sensitive) exactly as Section 3 requires. It is a real
service (LLM Guard API server, MIT, Protect AI), not a mock.

## Unverified / Could not confirm (honest June 2026 gaps)

- **Exact OSS webhook timeout / failure-mode behavior** (fail-open vs fail-closed when the
  webhook server is down) was not confirmed from docs. Must be tested at build; a guardrail
  that fails open silently would violate Michael's "no silent fallback" rule.
- **Whether OSS `v1.2.1` response-phase guardrails work against a non-LLM-provider backend.**
  Every documented guardrail example attaches `guardrails` under `llm.models[]` with a
  recognized `provider` (openAI/bedrock/google) and assumes OpenAI-format chat-completion
  bodies (`choices[].message.content`). I could NOT confirm that pointing agentgateway at a
  **kagent A2A agent serving endpoint** (which is A2A/JSON-RPC, not an OpenAI chat-completions
  LLM backend) will trigger the response prompt-guard. This is the single biggest open
  question for Phase 4 and must be tested before building on it.
- **Mask granularity / format** on `/response` (does Mask preserve the rest of the message,
  what masking token), not confirmed from docs; verify with the LLM Guard `Secrets`/`Sensitive`
  scanner output at build.
- **MCP human-in-the-loop / approval workflow:** not found in current docs. MCP policy is
  allow/deny/filter via CEL, evaluated automatically. No documented interactive approval
  step. Treat HITL as NOT a native agentgateway feature as of 2026-06-15.
- agentgateway Helm chart version for the OSS standalone-in-Kubernetes install was not
  pinned here (releases are binary/container tags on the `1.x` line). Pin the chart at build
  and record in `VERSIONS.lock`.

## Recommended mechanism

- **Input guard:** agentgateway native prompt-guard, **request phase**, `webhook` action
  pointing at the LLM-Guard-backed webhook server (RejectAction supported → hard block on
  prompt-injection). Use native `regex` as a fast deterministic first layer if desired.
  This one is low-risk and idiomatic.

- **Output guard (attack 4):** **Pin the LLM Guard reverse-proxy sidecar on the agent
  response path as the PRIMARY mechanism**, not the agentgateway response-phase webhook.
  Rationale: (a) the build places the inspection point in front of a **kagent A2A agent
  endpoint**, and agentgateway's response guardrails are documented only for recognized
  LLM-provider backends returning OpenAI chat-completion bodies, unverified against an A2A
  agent; (b) the response-phase webhook **cannot Reject, only Mask**, the "blocked"
  half of the attack-4 claim is not natively achievable on the response, only redaction.
  A reverse-proxy sidecar removes both unknowns and keeps the deterministic Secrets/Sensitive
  scanners. Keep the agentgateway response-phase webhook as the documented *alternative* in
  `GATEWAY-NOTES.md`, and re-test it once the A2A-backend question is resolved, if it works,
  it is the more elegant story for the talk ("the gateway itself sees the response").
  Either way, frame the attack-4 "after" state as **redact-or-block**, and if you need a
  hard block, the sidecar can return an error rather than mask.

- **MCP policy:** use agentgateway's native **`mcpAuthorization` CEL rules + `targets`
  allowlist** for the bad-MCP/excessive-agency beat. This is real, current, and well
  documented. Per-tool allowlisting + automatic filtering from `list_tools` is the headline
  demo. Do NOT promise human-in-the-loop approval, it is not native; if the talk needs
  HITL, narrate it as an explicit gap / future control.

## Risks for the build

1. **Backend-type mismatch (highest).** agentgateway response guardrails are documented for
   LLM-provider backends, but the agent is a kagent A2A endpoint. The native output guard may
   simply not fire. Mitigation: the reverse-proxy sidecar (primary above). Test the native
   path early; do not let Phase 4 depend on an unverified assumption.
2. **Response phase cannot hard-Reject (only Mask).** Attack-4 attendee copy must say
   "redacted" if using the native path; reserve "blocked" for the sidecar. Avoid a claim the
   mechanism can't deliver.
3. **OSS vs Enterprise doc drift.** Easy to copy a `2.3.x` Enterprise config into a `1.2.1`
   OSS binary and have field names not match. Build strictly from
   `agentgateway.dev/docs/standalone/latest`; record the exact OSS version in `VERSIONS.lock`.
4. **Webhook fail-open behavior unknown.** If the webhook/LLM Guard server is down,
   confirm agentgateway fails closed (or wrap so it does), a silent fail-open re-leaks the
   secret and violates the no-silent-fallback rule.
5. **v1.3.0 churn.** v1.3 is in beta as of 2026-06-12; guardrail/MCP config fields may move.
   Pin v1.2.1 (stable) and do not chase the beta before the event.
