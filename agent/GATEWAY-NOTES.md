*Purpose: the confirmed gateway/guardrail mechanisms for the workshop — input guard, output sidecar, MCP authz — plus the [SPIKE]s and the fallback decisions, grounded in `research/02-agentgateway.md` and `research/03-llm-guard.md`.*

# Gateway & Guardrail Notes

Architecture context: separate EKS spoke cluster per attendee. Everything below runs in each
attendee's spoke. agentgateway OSS **v1.2.1** fronts the kagent agent's A2A serving endpoint and
its MCP tool traffic. LLM Guard (Protect AI, MIT) runs in API-server mode per spoke,
**output-`Regex`-only by default** to keep each spoke node small.

All field paths and config syntax here are grounded in the research notes (build strictly from the
OSS standalone docs at `agentgateway.dev/docs/standalone/latest`, NOT the Solo Enterprise 2.x docs).
Every load-bearing config fact carries a `# verify-at-build` comment in the YAML it lives in.

---

## CONFIRMED mechanisms

### 1. Input guard — agentgateway request-phase prompt-guard webhook (CAN hard-reject)
- **What:** agentgateway's native prompt-guard, **request phase**, `webhook` action, pointing at an
  LLM-Guard-backed wrapper. The request phase supports **`RejectAction`** (hard block + chosen
  `status_code`), so a prompt-injection request is **rejected at the gateway before it reaches the
  agent**. (`research/02-agentgateway.md` §3.)
- **LLM Guard side:** input **`PromptInjection`** scanner — DeBERTa classifier
  (`ProtectAI/deberta-v3-base-prompt-injection-v2`). **Model-based, NOT deterministic** — never
  describe it as a rule engine in attendee copy (spec §3).
- **Files:** baseline in `gateway/agentgateway.yaml`; toggles
  `gateway/input-guard-off.yaml` (default) / `gateway/input-guard-on.yaml`.
- **Verdict wiring:** the wrapper calls LLM Guard `/analyze/prompt`; flagged → `RejectAction 403`.

### 2. Output exfil guard — LLM Guard reverse-proxy SIDECAR (PRIMARY; hard block)
- **What:** a reverse-proxy sidecar in front of the agent's serving container. It captures the
  agent response, calls LLM Guard **`POST /analyze/output`**, and acts on the verdict:
  - `is_valid == false` → **BLOCK** (hard error; raw body never leaves)
  - `is_valid == true` → forward **`sanitized_output`** (redacted) → **REDACT**
  (`research/03-llm-guard.md` §Verdict semantics.)
- **LLM Guard side:** output **`Regex`** scanner ONLY by default — the provably **model-free**
  control, matching the sentinel formats (`FAKE-PROD-DB-PASSWORD-sentinel-9f2a`,
  `FAKE-MCP-EXFIL-sentinel-4c1d`). There is **no `Secrets` OUTPUT scanner** — `Secrets` is
  input-only; the rev1 spec naming was wrong (`research/03-llm-guard.md` §Risks.1).
- **Why sidecar is PRIMARY (not the native agentgateway response webhook):** the native response
  webhook can only **Mask, not Reject**, and is documented only for recognized LLM-provider backends
  returning OpenAI chat-completion bodies — **unverified** against a kagent A2A endpoint. The sidecar
  removes both unknowns and gives the hard block the "blocked" copy needs.
  (`research/02-agentgateway.md` §2/§5.)
- **Files:** `gateway/llm-guard-sidecar.yaml` (authoritative sidecar spec);
  toggles `gateway/output-guard-off.yaml` (default) / `gateway/output-guard-on.yaml`.
- **Fail-closed:** `PROXY_FAIL_CLOSED=true` — if LLM Guard is unreachable the sidecar blocks, never
  passes the raw response (Michael's no-silent-fallback rule; `research/02-agentgateway.md` §Risks.4).

### 3. MCP authorization — agentgateway `mcpAuthorization` CEL rules + `targets` allowlist
- **What:** CEL rules over `mcp.tool.name` (and `mcp.tool.target`, `jwt.*`), evaluated per MCP method
  (`list_tools`, `call_tool`). Rules OR together; any match grants access. Disallowed tools are
  **auto-filtered out of `list_tools`**, so the agent never sees a tool it cannot call. Server
  allowlisting is structural via the `targets` list. (`research/02-agentgateway.md` §4.)
- **Beat-3 control:** baseline = **default Allow** (`mcp-authz-off.yaml`, the "before") so the rogue
  tool **`read_internal_config`** is reachable and leaks `FAKE-MCP-EXFIL-sentinel-4c1d`. The "after"
  (`mcp-authz-on.yaml`) denies the rogue tool (allow-only-with-implicit-deny, or explicit
  `action: Deny`) and confines authz to the `workshop-mcp` target.
- **No native human-in-the-loop.** MCP policy is allow/deny/filter via CEL only — do NOT promise HITL;
  narrate it as a gap if the talk needs it. (`research/02-agentgateway.md` §"Unverified".)
- **Files:** baseline in `gateway/agentgateway.yaml`; toggles
  `gateway/mcp-authz-off.yaml` (default) / `gateway/mcp-authz-on.yaml`.

---

## The [SPIKE]s (load-bearing unknowns — gate before declaring live)

1. **[SPIKE] MCP authz enforcement on OSS v1.2.1 with kagent in front** (Phase 4b, gates **beat 3
   LIVE**). The single most load-bearing unknown. Whether `mcpAuthorization` Deny/allowlist actually
   enforces on the Apache OSS build with a kagent agent fronted is unconfirmed.
   - PASS → beat 3 ships live with the toggle.
   - FAIL → beat 3 demotes to a **recorded segment + governance-map row**; the recording is built
     regardless. Record the result in `beats/03-bad-mcp-excessive-agency/BUILD-SPIKE.md`.

2. **[SPIKE] Does the agentgateway prompt-guard fire for a kagent A2A (JSON-RPC) backend** — not just
   for a recognized chat-completions LLM provider? Every documented guardrail example attaches
   `guardrails` under `llm.models[]` with a recognized provider and assumes OpenAI-format bodies.
   - Affects the **input** request-phase webhook (whether it triggers at all) and is the reason the
     **output** guard uses the sidecar instead of the native response webhook. Test the input path
     early; the output path already sidesteps it. (`research/02-agentgateway.md` §"Unverified".)

3. **[SPIKE] (documented alternative) native output response-phase webhook.** Kept as the *documented
   alternative* to the sidecar, NOT primary. Two known limits: it can only **Mask, not Reject**, and
   it is unverified against an A2A backend. Re-test once the A2A-backend question (#2) is resolved; if
   it fires, it is the more elegant "the gateway itself sees the response" story — but frame the
   beat-2 "after" as **redact**, reserve "block" for the sidecar. (`research/02-agentgateway.md` §5.)

4. **[SPIKE] webhook fail-open vs fail-closed.** OSS webhook failure-mode behavior (what happens when
   the LLM Guard wrapper is down) was not confirmed from docs. A silent fail-open re-leaks the secret
   and violates the no-silent-fallback rule. Confirm agentgateway fails closed, or wrap so it does.
   The sidecar enforces this with `PROXY_FAIL_CLOSED=true`. (`research/02-agentgateway.md` §Risks.4.)

---

## Fallback / pin decisions (resolved at build time)

- **Output guard mechanism:** SIDECAR is PRIMARY (hard block, A2A-agnostic). Native agentgateway
  response webhook is the documented ALTERNATIVE and is [SPIKE]'d (#3 above) — it can Mask not Reject.
- **LLM Guard output scanners:** `Regex`-only by default (model-free, matches the sentinels).
  `Sensitive` (NER + regex PII) is **opt-in / OFF by default** — enabling it loads the NER model and
  breaks the per-spoke RAM budget (>=16 GB docs default at full load; `research/03-llm-guard.md`
  §Risks.5). Decision recorded against `infra/SIZING.md`.
- **LLM Guard image namespace:** `laiyer/llm-guard-api` is authoritative — `protectai/llm-guard-api`
  does NOT exist on Docker Hub (404 confirmed 2026-06-16). `laiyer/` is somewhat stale (latest tag
  `0.3.16`) but it is the only published image. **Pin a `@sha256` digest, not `:latest`** (no GitHub
  releases exist). Also pin the PyPI `llm-guard` version. → `VERSIONS.lock`.
- **agentgateway version:** OSS **v1.2.1** (stable). Do NOT pin the v1.3.0 beta. Install is a
  two-chart OCI Helm install (`agentgateway-crds` then `agentgateway` from
  `oci://cr.agentgateway.dev/charts/`); pin the resolved chart version + container digest in
  `VERSIONS.lock`. Build strictly from the OSS standalone docs (the Enterprise 2.x docs drift).
- **Egress-proxy sidecar image:** a real thin reverse proxy (NOT a mock) calling `/analyze/output`.
  It is a `PLACEHOLDER_EGRESS_PROXY_IMAGE` until built and pinned — ship no placeholder to the event.
- **Default toggle states at workshop start:** input-guard OFF, output-guard OFF, mcp-authz OFF
  (default Allow). Each beat flips its toggle on for the "after".
