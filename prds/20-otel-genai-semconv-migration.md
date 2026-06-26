# PRD #20: OTel GenAI Semconv Migration

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/20
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 2 child PRD
**Priority**: High
**Status**: In progress. M1-M5 implemented (M2/M3 SDK injection live-verified on attendee-001 2026-06-25; M4 agentgateway tracing resolved; M5 retired the custom `witb_*` counters for standard `gen_ai.client.cost`, commit f963550), per PROGRESS.md 2026-06-25. M6 Weaver registry in place; M7 build verification pending.

---

## Problem

The AI layer emits Michael's custom `witb_*` conventions. These are non-standard: `witb_cost_usd`, `witb_tokens_total`, `witb_requests_total` (all labeled `tier`) do not flow into Datadog LLM Observability, and the `invoke_agent → call_llm → execute_tool` waterfall, per-model token counts, and cost data are invisible in the Datadog Agent Observability UI.

Two additional gaps block the target state:
- The evil-mcp-shim is missing `apply_optimization` in `gitops/ai-layer/server.py` (issue #18, closed 2026-06-24) — the beats' OSError fallback branch needs the optimization string hardcoded directly in the server.
- agentgateway's OTel tracing endpoint is set only via an env var that is documented for the Kubernetes/Helm deployment path; the standalone OSS binary may require the config-file key `frontendPolicies.tracing.otlpEndpoint` instead.

---

## Solution

1. Add `apply_optimization` to `gitops/ai-layer/server.py` using a hardcoded fallback string (no relative file path — ConfigMap deployment drops them).
2. Create a single shared OTel Operator Instrumentation CRD for Python pods that sets the Collector endpoint, protocol, and semconv opt-in cluster-wide; per-pod UST stays in each workload's own env.
3. Enable kagent/ADK native gen_ai tracing via `otel.tracing.enabled: true` and `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY`.
4. Fix agentgateway tracing: verify whether the current env var produces traces; if not, add `frontendPolicies.tracing.otlpEndpoint` to the ConfigMap with explanatory comments.
5. Migrate `witb_*` counters: retire `witb_tokens_total`/`witb_requests_total`/`tier` label; keep `witb_cost_usd` with a `model` label carrying `gen_ai.request.model`.
6. Add a Weaver registry with the OTel semconv community dependency, `registry check` in CI, and a documented `live-check` acceptance step.

---

## Locked Decisions (do not re-open)

All decisions below were finalized in the Milestone 2 design conversation (2026-06-24) and are recorded in meta-PRD #7 Decision Log. Read those entries before implementing.

| Decision | Value |
|---|---|
| OTel Operator | Deployed (pre-decided 2026-06-24; overrides research/33 "No Operator" conclusion) |
| Custom app instrumentation pattern | OTel API no-op in image; Operator injects full SDK at pod startup; manual spans at runtime |
| Instrumentation CRD scope | Single shared CRD for all custom Python apps; per-pod env vars carry UST. Use one per app only if a concrete per-app need arises. |
| Instrumentation CRD env | `OTEL_EXPORTER_OTLP_PROTOCOL=grpc`; `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` |
| Collector endpoint (intent) | Verify the actual chart-generated Service name and namespace on the live cluster before wiring. Current manifests use `otel-collector-opentelemetry-collector.monitoring.svc.cluster.local`; issue #17 text used `otel-collector.observability.svc.cluster.local`. Reconcile at build; do not assume either. |
| kagent/ADK instrumentation | Config-only; `otel.tracing.enabled: true` in Helm values; native built-in OTel; no extra libraries |
| Content capture | `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` — NOT `true` (invalid config under `gen_ai_latest_experimental`; silently collects nothing) |
| agentgateway instrumentation | Config-only; native built-in OTel; verify env var produces traces first; only add `frontendPolicies.tracing.otlpEndpoint` if traces are absent |
| OpenLLMetry | Do NOT use — deprecated attribute lag (`gen_ai.prompt`/`gen_ai.completion` instead of `gen_ai.input.messages`/`gen_ai.output.messages`) |
| `witb_tokens_total` / `witb_requests_total` | Retire — redundant with `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` |
| `tier` label | Retire — replaced by `model` label on `witb_cost_usd` |
| `witb_cost_usd` | Keep — pre-computed USD for the demo cost-accumulation visual; `tier` label replaced by `model` label carrying `gen_ai.request.model` value. USD cost is not a standard gen_ai attribute; Datadog LLM Obs can also derive cost from token counts, but the pre-computed counter provides a more direct dashboard visual. |
| `witb_` namespace | Keep as-is — appropriate for a project-specific custom metric in a workshop demo repo; service identity comes from the Prometheus scrape target |
| Weaver CI | `registry check` in CI (static, no live stack needed); `live-check` as documented acceptance step on live cluster only (not a CI gate) |
| OTel semconv version | v1.37+ required for Datadog LLM Obs; `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` |
| guard-proxy OTel instrumentation | M3 scope — do NOT add OTel spans to proxy.py in this PRD. M2 only retires the `witb_*` Prometheus counters. |
| evil-mcp-shim OTel instrumentation | None (decided 2026-06-24, issue #18 Decision Log) — rogue tool calls are visible as the ADK agent's `execute_tool {gen_ai.tool.name}` spans |

---

## Milestones

### Milestone 1 — evil-mcp-shim: add `apply_optimization` to `gitops/ai-layer/server.py`

This is untracked work from issue #18 (closed 2026-06-24). The beats' OSError fallback branch relies on an `apply_optimization` function that must live directly in `gitops/ai-layer/server.py`. It cannot load the optimization string from a relative file path — ConfigMap deployment drops relative paths.

**Steps:**
1. Search for `apply_optimization` across the repository: `grep -r "apply_optimization" challenges/ gitops/`. Read the file that contains the call to identify the OSError fallback branch and the exact hardcoded fallback string `apply_optimization` must return.
2. Read `gitops/ai-layer/server.py` and find whether `apply_optimization` exists. If absent, add it using the hardcoded fallback string from step 1.
3. Do NOT add any OTel instrumentation to this file — the shim is intentionally dark (decided 2026-06-24, issue #18 Decision Log).

**Done when:**
- [ ] `apply_optimization` exists in `gitops/ai-layer/server.py` with a hardcoded fallback string (no relative file path)
- [ ] No OTel instrumentation added to the shim

---

### Milestone 2 — Shared OTel Instrumentation CRD for Python pods

Create the single shared Instrumentation CRD that the OTel Operator uses to inject the SDK into all custom Python pods. This sets cluster-wide constants; per-pod UST stays in each workload's own env.

**Steps:**
1. Determine the actual OTel Collector Service name and namespace on the live cluster. Run: `kubectl get svc -A --context <context> | grep -i otel-collector`. Do NOT assume either known candidate — record the actual resolved value.
2. Create a new dedicated file `gitops/ai-layer/instrumentation.yaml` for the Instrumentation CR (do not append it to `resources.yaml` — the Instrumentation CRD is a distinct resource type that belongs in its own file). Contents:
   ```yaml
   apiVersion: opentelemetry.io/v1alpha1
   kind: Instrumentation
   metadata:
     name: watch-it-burn-python
     namespace: agent
   spec:
     exporter:
       endpoint: http://<RESOLVED-SERVICE>.<RESOLVED-NAMESPACE>.svc.cluster.local:4317
     propagators: [tracecontext, baggage]
     sampler:
       type: parentbased_always_on
     env:
       - name: OTEL_EXPORTER_OTLP_PROTOCOL
         value: grpc
       - name: OTEL_SEMCONV_STABILITY_OPT_IN
         value: gen_ai_latest_experimental
   ```
3. Confirm the per-pod UST env vars (`OTEL_RESOURCE_ATTRIBUTES` with `service.name`, `service.version`, `deployment.environment.name=production`) already exist on kagent and agentgateway workloads in `gitops/ai-layer/resources.yaml` — the MVP PRD (#13) should have set them. Do not duplicate them in the Instrumentation CRD.
4. Add the injection annotation `instrumentation.opentelemetry.io/inject-python: "watch-it-burn-python"` to the pod template annotations on the kagent and agentgateway workloads.

**Done when:**
- [ ] Instrumentation CR exists with the verified Collector endpoint (actual Service name recorded in Decision Log below)
- [ ] kagent and agentgateway pod templates carry the injection annotation
- [ ] Per-pod UST env vars confirmed present (not duplicated in the CRD)

---

### Milestone 3 — Enable kagent/ADK gen_ai tracing

Enable native ADK tracing. Once on, ADK emits the full `invoke_agent → call_llm → execute_tool {gen_ai.tool.name}` waterfall with `gen_ai.request.model` and `gen_ai.usage.*` tokens natively — no instrumentation code to write.

**Steps:**
1. Find the kagent Helm values file (check `gitops/apps/` for the kagent ArgoCD Application values).
2. Add under the kagent chart values:
   ```yaml
   otel:
     tracing:
       enabled: true
   ```
3. Add to the kagent pod's env section in `gitops/ai-layer/resources.yaml`:
   ```yaml
   - name: OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT
     value: EVENT_ONLY
   ```
   The value is `EVENT_ONLY`, not `true`. Setting it to `true` is an invalid configuration under `gen_ai_latest_experimental` semconv and silently collects no content.
4. Do NOT add `OTEL_EXPORTER_OTLP_ENDPOINT` or `OTEL_EXPORTER_OTLP_PROTOCOL` to the pod env — these come from the Instrumentation CRD (Milestone 2).

**Done when:**
- [ ] `otel.tracing.enabled: true` in kagent Helm values
- [ ] `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` in kagent pod env (not `true`)

---

### Milestone 4 — agentgateway OTel config: verify then fix

The repo sets `OTEL_EXPORTER_OTLP_ENDPOINT` as an env var on agentgateway. That env var is documented only for the Kubernetes/Helm deployment path. The standalone OSS binary (what the repo runs) may require the config-file key `frontendPolicies.tracing.otlpEndpoint` instead. Verify before changing anything.

**Steps:**
1. Bump the agentgateway pin to v1.3.0 in `agent/gateway/agentgateway.yaml`.
2. **Before touching the tracing config**: run a workshop beat that triggers agentgateway and check whether agentgateway spans arrive at the Collector (`kubectl logs <otel-collector-pod> --context <context>` or the Collector debug exporter).
   - If spans appear: the env var works for the standalone binary. Record the finding. No config-file change needed.
   - If spans are absent: proceed to step 3.
3. Open the agentgateway ConfigMap (`agent/gateway/agentgateway.yaml`) and add the config-file key using the Collector endpoint resolved in Milestone 2:
   ```yaml
   frontendPolicies:
     tracing:
       otlpEndpoint: http://<RESOLVED-SERVICE>.<RESOLVED-NAMESPACE>.svc.cluster.local:4317
       randomSampling: true
   ```
4. Wherever the `OTEL_EXPORTER_OTLP_ENDPOINT` env var appears in the manifest AND wherever the `frontendPolicies.tracing` block appears, add these comments:
   ```yaml
   # OTEL_EXPORTER_OTLP_ENDPOINT is documented for the Kubernetes/Helm agentgateway
   # deployment path only. For the OSS standalone binary, tracing may require the
   # config-file key frontendPolicies.tracing.otlpEndpoint instead.
   # Verify-at-build: if traces are absent with only the env var, the standalone
   # binary does not honor it and the config file key is the correct activation path.
   ```
5. Confirm the `frontendPolicies.tracing.otlpEndpoint` key schema against the v1.3.0 agentgateway docs before setting the value. Check the agentgateway GitHub repository (https://github.com/agentgateway/agentgateway) for the v1.3.0 release notes and config reference — do not assume the key exists or accept the field name from training data alone.

**Done when:**
- [ ] agentgateway pin bumped to v1.3.0
- [ ] Verification run completed and result recorded (env var works OR config-file key added)
- [ ] Code comments explaining the env var vs config-file ambiguity present in the manifest

---

### Milestone 5 — Migrate `witb_*` Prometheus counters

Retire `witb_tokens_total`, `witb_requests_total`, and the `tier` label. Keep `witb_cost_usd` but add a `model` label. Do NOT add OTel spans to proxy.py — that is M3 scope.

**Touch-points:**
- `agent/gateway/guard-proxy/proxy.py`
- `gitops/ai-layer/proxy.py` (if it duplicates counter declarations)
- Grafana dashboard JSON (find in `gitops/` or `dashboards/`)
- `verify/test_observability.py`

**Steps:**
1. Read `agent/gateway/guard-proxy/proxy.py`. Find all `witb_` Prometheus counter declarations and every call site that increments them.
2. Remove `witb_tokens_total` and `witb_requests_total` counter declarations and all their increment calls. Do NOT remove `witb_cost_usd` — it is kept by design (see Locked Decisions).
3. For `witb_cost_usd`: remove only the `tier` label from the counter declaration and add a `model` label in its place. Do NOT change any other counter logic, increment frequency, or value calculation — only the label name changes. Update every call site to pass the model identifier as the `model` label value. The model identifier is the value of `gen_ai.request.model` — search the existing request-handling code in `proxy.py` for where the model name is extracted from the incoming request (look for header parsing, JSON body parsing, or request metadata fields) and pass that value.
4. Repeat steps 2-3 for `gitops/ai-layer/proxy.py` if that file has counter declarations.
5. Update `verify/test_observability.py`: remove assertions on `witb_tokens_total` and `witb_requests_total`; update `witb_cost_usd` assertions to use the `model` label instead of `tier`.
6. Update the Grafana dashboard JSON: remove panels querying `witb_tokens_total` and `witb_requests_total`; update the `witb_cost_usd` panel query to group by `model` label instead of `tier`.

**Done when:**
- [ ] `witb_tokens_total` and `witb_requests_total` removed from all touch-points
- [ ] `tier` label removed from `witb_cost_usd`; `model` label added with the model identifier value
- [ ] `verify/test_observability.py` updated and passing
- [ ] Grafana dashboard JSON updated

---

### Milestone 6 — Weaver registry and CI `registry check`

Create the Weaver registry referencing the OTel semconv community definitions and add the static `registry check` to CI.

**Before starting**: read `~/.claude/rules/weaver-gotchas.md` — there are known breaking changes in v0.22.1 that affect the registry manifest format and template auto-escaping defaults.

**Steps:**
1. Create `weaver/registry/` directory. Add `registry_manifest.yaml` declaring the OTel semconv community registry as a dependency (do not redefine community attributes locally):
   ```yaml
   dependencies:
     - name: otel
       registry_path: https://github.com/open-telemetry/semantic-conventions@v1.37.0[model]
   ```
2. Add span group entries for `guard-proxy` spans (pre-specified in meta-PRD #7 Decision Log, issue #19 entry; guard-proxy OTel code will be added in M3, but the registry can be defined now):
   - HTTP SERVER spans group: reference `http.request.method`, `url.scheme`, `url.path`, `http.response.status_code` via `ref:` to the community semconv entries.
   - `sanitize` INTERNAL child span group: reference `gen_ai.operation.name` (enum value `"chat"`), `gen_ai.input.messages`, `gen_ai.output.messages` via `ref:`.
3. Run `weaver registry check --registry weaver/registry/` locally to confirm the registry is valid before adding to CI.
4. Add the `registry check` to CI: look under `.github/workflows/` for an existing workflow where a lint/check step belongs (or create a new `weaver.yml` workflow if none fits). Before adding the check command, verify whether a weaver install step already exists in that workflow. If not, add an install step before the check: `cargo install weaver-checker` (or the equivalent documented install command for the version in use). Without a weaver install step, the check will fail with "command not found" on the first CI run. The check command is: `weaver registry check --registry weaver/registry/`.
5. Document the `live-check` acceptance step — add a comment in the CI workflow or a note in `docs/weaver-live-check.md`:
   > `live-check` is NOT a CI gate. Run it manually on the live cluster after M3 guard-proxy spans are implemented: `weaver registry live-check --registry weaver/registry/`

**Done when:**
- [ ] `weaver/registry/` exists with `registry_manifest.yaml` referencing OTel semconv v1.37.0
- [ ] guard-proxy span groups defined (HTTP SERVER + `sanitize` INTERNAL, per issue #19 spec)
- [ ] `weaver registry check` passes locally
- [ ] `registry check` runs in CI and passes
- [ ] `live-check` acceptance step documented

---

### Milestone 7 — Build verification

Confirm the full observability chain is working on the live cluster before this PRD is closed.

**Checklist (run each item against the live cluster):**
1. **Collector endpoint**: agentgateway and kagent traces arrive at the Collector (proves the Service name resolved in Milestone 2 is correct).
2. **kagent/ADK gen_ai waterfall**: run a beat that triggers the agent; confirm `invoke_agent → call_llm → execute_tool {gen_ai.tool.name}` spans appear in Datadog APM traces with `gen_ai.request.model` populated.
3. **Datadog LLM Observability routing**: confirm the waterfall appears in the Datadog **Agent Observability** (LLM Observability) traces page — not just plain APM. If absent, add a dedicated OTLP exporter in the Collector with `dd-otlp-source=llmobs` in the headers as the deterministic fallback (see meta-PRD #7 Decision Log, research/28 Q7 for the fallback spec).
4. **`gen_ai.request.model` on spans**: confirm the model identifier (e.g. `claude-sonnet-4-6`) appears on live `call_llm` spans.
5. **`witb_cost_usd{model=...}`**: confirm the counter appears in Datadog metrics with the `model` label populated and the `tier` label absent.
6. **Content capture**: run a beat with prompt content; confirm `gen_ai.input.messages` / `gen_ai.output.messages` appear on spans (proves `EVENT_ONLY` is working, not silently misconfigured).
7. **Weaver `live-check`**: run `weaver registry live-check --registry weaver/registry/` and confirm no advisories on emitted spans.

**Done when:**
- [ ] All 7 items confirmed on the live cluster
- [ ] LLM Observability routing confirmed (or `dd-otlp-source=llmobs` fallback implemented and confirmed)

---

## Decision Log

| Date | Decision | Reasoning |
|---|---|---|
| 2026-06-24 | Single shared Instrumentation CRD | Per-component CRDs add complexity without benefit. Per-pod env vars handle UST differentiation. Escalate only if a concrete per-app need arises. |
| 2026-06-24 | Config-only native OTel for kagent/ADK and agentgateway | Both components have built-in OTel emitting GenAI semconv natively. No extra libraries needed for M2. |
| 2026-06-24 | `EVENT_ONLY` for content capture | `true` is invalid under `gen_ai_latest_experimental` semconv and silently collects nothing. `EVENT_ONLY` is the correct value per research/28. |
| 2026-06-24 | Keep `witb_cost_usd`; retire `witb_tokens_total`/`witb_requests_total` | USD cost is not a standard gen_ai attribute. The pre-computed counter provides the demo's real-time cost-accumulation visual. Token counts are superseded by `gen_ai.usage.*`. |
| 2026-06-24 | Replace `tier` label with `model` on `witb_cost_usd` | `tier` was the old model-dimension label. `gen_ai.request.model` is the standard. The `model` label enables cost-by-model grouping. |
| 2026-06-24 | Keep `witb_` namespace | Appropriate for a project-specific custom metric in a workshop demo. Service identity comes from the Prometheus scrape target. Renaming adds churn without benefit. |
| 2026-06-24 | Weaver `registry check` in CI; `live-check` as acceptance step only | `registry check` is static (no live stack) and fast. `live-check` requires a running stack — appropriate as a build gate, not a CI gate. |
| 2026-06-24 | Verify agentgateway env var before adding config-file key | Undocumented ≠ non-functional. Check whether traces arrive before touching the config to avoid premature changes. |
| 2026-06-24 | guard-proxy OTel instrumentation deferred to M3 | M2 only retires `witb_*` counters from proxy.py. guard-proxy proxy spans (HTTP SERVER + `sanitize` INTERNAL child) are M3 scope per meta-PRD #7. |
| 2026-06-24 | evil-mcp-shim: no OTel instrumentation | Shim is intentionally dark. Rogue tool calls are visible as the ADK agent's `execute_tool {gen_ai.tool.name}` spans (issue #18 Decision Log). |
