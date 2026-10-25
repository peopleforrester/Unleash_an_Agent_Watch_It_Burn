*Purpose: the confirmed gateway/guardrail mechanisms for the workshop, input guard, output sidecar, MCP authz, plus the [SPIKE]s and the fallback decisions, grounded in `the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` and `the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)`.*

# Gateway & Guardrail Notes

Architecture context: separate EKS cluster per attendee (independent, take-home). Everything below runs in each
attendee's spoke. agentgateway OSS **v1.5.0** fronts the kagent agent's A2A serving endpoint and
its MCP tool traffic. LLM Guard (Protect AI, MIT) runs in API-server mode per spoke,
**output-`Regex`-only by default** to keep each spoke node small.

All field paths and config syntax here are grounded in the research notes (build strictly from the
OSS standalone docs at `agentgateway.dev/docs/standalone/latest`, NOT the Solo Enterprise 2.x docs).
Every load-bearing config fact carries a `# verify-at-build` comment in the YAML it lives in.

---

## CONFIRMED mechanisms

### 1. Input guard, TWO STAGES enabled progressively (ruling 2026-06-19; CAN hard-reject)
The input guard has two stages, built and toggled progressively (see `docs/BUILD-PLAN.md`):
- **Stage 1, deterministic block-list (default, cheapest):** the guard-proxy matches a block-list
  (e.g. "delete" intent) and hard-rejects **before** the LLM, so zero tokens are spent and the cost
  counter flatlines. This stage IS deterministic.
- **Stage 2, classifier (toggle on as needed):** guard-proxy sends the prompt to LLM Guard's input
  **`PromptInjection`** scanner, DeBERTa (`ProtectAI/deberta-v3-base-prompt-injection-v2`), and
  hard-rejects a flagged prompt before it reaches the agent. It is not an agentgateway request-phase
  webhook: agentgateway prompt-guards attach only to `llm.models[]` LLM-provider backends, not to the
  A2A backend (header of `gitops/ai-layer/agentgateway.yaml`). This stage is **model-based, NOT
  deterministic**, never call the combined guard "deterministic" in attendee copy once stage 2 is in
  the path (spec §3).
- **Files:** guard-proxy and LLM Guard (Deployments `guard-proxy`, `llm-guard`, ConfigMap
  `llm-guard-scanners`) in `gitops/ai-layer/resources.yaml`; proxy source is the
  `gitops/ai-layer/guard-proxy` submodule. Toggles are runtime flips of guard-proxy's `/toggle`:
  `challenges/02-sanitization/toggle-input-guard-on.sh` (stage 1, `input_blocklist`) and
  `toggle-input-classifier-on.sh` (stage 2, `input_classifier`), each with `--off`. The pre-gitops
  `gateway/input-guard-{on,off}.yaml` agentgateway overlays were never applied and were deleted in #546.

### 2. Output exfil guard, LLM Guard reverse-proxy SIDECAR (PRIMARY; hard block)
- **What:** a reverse-proxy sidecar in front of the agent's serving container. It captures the
  agent response, calls LLM Guard **`POST /analyze/output`**, and acts on the verdict:
  - `is_valid == false` → **BLOCK** (hard error; raw body never leaves)
  - `is_valid == true` → forward **`sanitized_output`** (redacted) → **REDACT**
  (`the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §Verdict semantics.)
- **LLM Guard side:** output **`Regex`** scanner ONLY by default, the provably **model-free**
  control, matching the sentinel formats (`FAKE-PROD-DB-PASSWORD-sentinel-9f2a`,
  `FAKE-MCP-EXFIL-sentinel-4c1d`). There is **no `Secrets` OUTPUT scanner**, `Secrets` is
  input-only; the rev1 spec naming was wrong (`the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §Risks.1).
- **Why sidecar is PRIMARY (not the native agentgateway response webhook):** the native response
  webhook can only **Mask, not Reject**, and is documented only for recognized LLM-provider backends
  returning OpenAI chat-completion bodies, **unverified** against a kagent A2A endpoint. The sidecar
  removes both unknowns and gives the hard block the "blocked" copy needs.
  (`the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §2/§5.)
- **As deployed:** the reverse proxy is guard-proxy, its own Deployment in front of agentgateway
  (`AGENT_URL` = `agentgateway:3000`), not a sidecar in the agent pod. One proxy carries both the
  input stages and this output guard.
- **Files:** guard-proxy and LLM Guard in `gitops/ai-layer/resources.yaml` (output `Regex` patterns in
  ConfigMap `llm-guard-scanners`); toggle `challenges/02-sanitization/toggle-output-guard-on.sh`
  (guard-proxy `/toggle?output=`, `--off` to disable). The pre-gitops `gateway/llm-guard-sidecar.yaml`,
  `gateway/llm-guard-service.yaml` and `gateway/output-guard-{on,off}.yaml` were never applied and
  were deleted in #546.
- **Fail-closed:** `PROXY_FAIL_CLOSED=true`, if LLM Guard is unreachable the sidecar blocks, never
  passes the raw response (Michael's no-silent-fallback rule; `the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §Risks.4).

### 3. MCP authorization, agentgateway `mcpAuthorization` CEL rules + `targets` allowlist
- **What:** CEL rules over `mcp.tool.name` (and `mcp.tool.target`, `jwt.*`), evaluated per MCP method
  (`list_tools`, `call_tool`). Rules OR together; any match grants access. Disallowed tools are
  **auto-filtered out of `list_tools`**, so the agent never sees a tool it cannot call. Server
  allowlisting is structural via the `targets` list. (`the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §4.)
- **Beat-3 control is NOT this.** The `evil-mcp` RemoteMCPServer dials evil-mcp-shim direct, not
  through agentgateway, so `mcpAuthorization` never sees the rogue tools. C7's deployed control is the
  kagent `toolNames` allowlist on the Agent's `evil-mcp` entry, patched by
  `challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh`: OFF = `get_weather,
  read_internal_config, apply_optimization` (the "before", the sentinel `FAKE-MCP-EXFIL-sentinel-4c1d`
  leaks), ON = `get_weather` only (the "after"). Routing evil-mcp through the gateway instead is weighed
  in `docs/research/2026-10-24-agentgateway-evaluation.md` (#239).
- **No native human-in-the-loop.** MCP policy is allow/deny/filter via CEL only, do NOT promise HITL;
  narrate it as a gap if the talk needs it. (`the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §"Unverified".)
- **Files:** `gitops/ai-layer/agentgateway.yaml`. The pre-gitops `gateway/agentgateway.yaml` and
  `gateway/mcp-authz-{on,off}.yaml` overlays were never applied and were deleted in #479.

---

## The [SPIKE]s (load-bearing unknowns, gate before declaring live)

1. **[SPIKE] MCP authz enforcement on the OSS build (v1.5.0) with kagent in front** (Phase 4b, gates **beat 3
   LIVE**). The single most load-bearing unknown. Whether `mcpAuthorization` Deny/allowlist actually
   enforces on the Apache OSS build with a kagent agent fronted is unconfirmed.
   - PASS → beat 3 ships live with the toggle.
   - FAIL → beat 3 demotes to a **recorded segment + governance-map row**; the recording is built
     regardless. Record the result in `challenges/03-bad-mcp-excessive-agency/BUILD-SPIKE.md`.

2. **[SPIKE] Does the agentgateway prompt-guard fire for a kagent A2A (JSON-RPC) backend**, not just
   for a recognized chat-completions LLM provider? Every documented guardrail example attaches
   `guardrails` under `llm.models[]` with a recognized provider and assumes OpenAI-format bodies.
   - Affects the **input** request-phase webhook (whether it triggers at all) and is the reason the
     **output** guard uses the sidecar instead of the native response webhook. Test the input path
     early; the output path already sidesteps it. (`the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §"Unverified".)

3. **[SPIKE] (documented alternative) native output response-phase webhook.** Kept as the *documented
   alternative* to the sidecar, NOT primary. Two known limits: it can only **Mask, not Reject**, and
   it is unverified against an A2A backend. Re-test once the A2A-backend question (#2) is resolved; if
   it fires, it is the more elegant "the gateway itself sees the response" story, but frame the
   beat-2 "after" as **redact**, reserve "block" for the sidecar. (`the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §5.)

4. **[SPIKE] webhook fail-open vs fail-closed.** OSS webhook failure-mode behavior (what happens when
   the LLM Guard wrapper is down) was not confirmed from docs. A silent fail-open re-leaks the secret
   and violates the no-silent-fallback rule. Confirm agentgateway fails closed, or wrap so it does.
   The sidecar enforces this with `PROXY_FAIL_CLOSED=true`. (`the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)` §Risks.4.)

---

## Fallback / pin decisions (resolved at build time)

- **Output guard mechanism:** SIDECAR is PRIMARY (hard block, A2A-agnostic). Native agentgateway
  response webhook is the documented ALTERNATIVE and is [SPIKE]'d (#3 above), it can Mask not Reject.
- **LLM Guard output scanners:** `Regex`-only by default (model-free, matches the sentinels).
  `Sensitive` (NER + regex PII) is **opt-in / OFF by default**, enabling it loads the NER model and
  breaks the per-spoke RAM budget (>=16 GB docs default at full load; `the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`)`
  §Risks.5). Decision recorded against `infra/SIZING.md`.
- **LLM Guard image namespace:** `laiyer/llm-guard-api` is authoritative, `protectai/llm-guard-api`
  does NOT exist on Docker Hub (404 confirmed 2026-06-16). `laiyer/` is somewhat stale (latest tag
  `0.3.16`) but it is the only published image. **Pin a `@sha256` digest, not `:latest`** (no GitHub
  releases exist). Also pin the PyPI `llm-guard` version. → `VERSIONS.lock`.
- **agentgateway version:** OSS **v1.5.0** (released 2026-08-27; moved from v1.3.0 on 2026-09-10).
  It deploys as the plain manifest `gitops/ai-layer/agentgateway.yaml` (ServiceAccount, Deployment,
  Service, ConfigMap), not a Helm chart, with the image pinned by tag and digest (#415) and recorded in
  `VERSIONS.lock`. Build strictly from the OSS standalone docs (the Enterprise 2.x docs drift). The
  committed config is validated offline against the vendored v1.5.0 schema
  (`verify/test_agentgateway_config.py`); MCP config nests under `mcp.{targets,policies}` and mcpAuthorization is
  allow-only CEL with implicit deny (no `action` field) — the research spikes (removed 2026-08-30; recover with `git log --diff-filter=D -- research/`) §2.
- **Egress-proxy image:** a real thin reverse proxy (NOT a mock) calling `/analyze/output`. Resolved
  as guard-proxy: `proxy.py` on the digest-pinned `watch-it-burn:python-3.12-slim` image in
  `gitops/ai-layer/resources.yaml` (baking `proxy.py` into the image is #411/#412).
- **Default toggle states at workshop start:** input-guard OFF, output-guard OFF, mcp-authz OFF
  (default Allow). Each beat flips its toggle on for the "after".
