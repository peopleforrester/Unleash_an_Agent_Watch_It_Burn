# PRD #22: Security Beats — guard-proxy Sanitization Tracing + Rogue MCP Tool-Call Chain

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/22
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 3 child PRD
**Priority**: High
**Status**: Not started

> **Note on `beats/` references:** The `beats/` directory naming is being aligned with the Rounds + Challenges vocabulary adopted June 2026 (C1–C7 challenges across three cumulative rounds). When implementing, update any `beats/` path references to the current challenge/round structure as you encounter them — no separate migration task is required.

---

## Problem

The workshop's two security-narrative beats are not yet observable in Datadog:

1. **Re-leak trap** (BUILD-SPEC §4): the guard-proxy sanitizes incoming prompts, but when OTel content capture is enabled, the original (unsanitized) prompt would appear in the trace — demonstrating that observability itself can become an exfil channel. This beat requires a `sanitize` span capturing before/after content, and a two-act demo: Act 1 shows the leak in Datadog LLM Observability; Act 2 applies Collector-side redaction to show the fix.

2. **Beat 3 — Rogue MCP tool-call chain** (excessive agency): the ADK agent calls an evil MCP tool by name. This requires confirming that ADK's native `execute_tool {gen_ai.tool.name}` spans surface the bad tool call in the Datadog APM waterfall.

guard-proxy currently has no OTel instrumentation. evil-mcp-shim is intentionally dark (decided 2026-06-24, meta-PRD Decision Log).

---

## Solution

1. Instrument guard-proxy (`agent/gateway/guard-proxy/proxy.py`) with an HTTP SERVER span on `do_POST` and a `sanitize` INTERNAL child span with `gen_ai.operation.name="chat"`, `gen_ai.input.messages` (original prompt), and `gen_ai.output.messages` (sanitized prompt). Content capture is gated on `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` — the proxy reads this env var explicitly (the env var does not govern hand-written spans automatically).
2. Add a Collector OTTL `transform` processor overlay for Act 2: replaces sentinel values on `sanitize` spans with `[DEMO-REDACTED]` before the Datadog export leg.
3. Add guard-proxy HTTP SERVER and `sanitize` INTERNAL span groups to the M2 Weaver registry (`registry check` in CI; `live-check` as documented manual acceptance step only).
4. Verify both beats end-to-end on a live cluster and write a demo runbook in `beats/`.

---

## Locked Decisions (do not re-open)

These were finalized in the M3 design conversation (2026-06-24). Read the meta-PRD #7 Decision Log for full reasoning.

| Decision | Value |
|---|---|
| OTel SDK delivery for guard-proxy | Inherited from M2 (PRD #20 Decision Log): OTel Operator injects full SDK at pod startup; guard-proxy image carries only `opentelemetry-api` (no-op until Operator injects) |
| guard-proxy instrumentation pattern | Manual OTel API spans; no auto-instrumentation library; no OpenLLMetry |
| `sanitize` span kind | INTERNAL (an internal operation within the request handler, not a new inbound request) |
| `gen_ai.operation.name` value | `"chat"` — NOT `"sanitize"` or any descriptive custom value. Datadog classifies spans as `llm` kind (rendering the Input/Output panel) only for `generate_content`, `chat`, `text_completion`, `completion`. A custom value silently disables the panel. |
| `gen_ai.input.messages` = | Original prompt (before sanitization), JSON per OTel messages schema: `[{"role":"user","parts":[{"type":"text","content":"<the prompt>"}]}]` |
| `gen_ai.output.messages` = | Sanitized prompt (after sanitization), same schema |
| Content capture default | OFF (`NO_CONTENT`). Proxy reads `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` explicitly at module load. The env var is specific to `opentelemetry-util-genai` and contrib instrumentations — it does NOT govern hand-written SDK spans automatically (research/31 Q3). |
| Content capture enum handling | Proxy treats `SPAN_ONLY`, `EVENT_ONLY`, `SPAN_AND_EVENT` as "capture enabled". Proxy treats `NO_CONTENT`, unset, or `true` (invalid enum value) as "no capture". `=true` must NOT enable capture — it is an invalid value that the ADK path also rejects. |
| Re-leak trap teardown | Two-act beat (Option C). Act 1: arm content capture (`SPAN_ONLY`), run beat, original prompt visible in Datadog LLM Observability. Act 2: apply Collector OTTL transform overlay, re-run beat, Datadog shows `[DEMO-REDACTED]`. Env var flipped to `NO_CONTENT` after Act 2. |
| Collector redaction mechanism | OTTL `transform` processor (value replacement). NOT `redactionprocessor` (which deletes the attribute — demo needs the key to remain visible with the redacted placeholder). |
| Datadog SDS role | Defense-in-depth backstop post-ingest only. SDS scans manual spans by content but acts server-side after ingest; the secret has already left the network. SDS does not replace Collector-side redaction for the re-leak trap (research/31 Q5 Part B). |
| Beat 3 rogue tool-call | ADK-native `execute_tool {gen_ai.tool.name}` spans from kagent/caller side only. evil-mcp-shim stays dark. Tool result capture is verify-at-build. |
| Weaver live-check | Manual acceptance step only — NOT a CI gate. `registry check` in CI is the CI gate. |

---

## Step 0: What to Read Before Starting Any Milestone

This PRD is executed by a fresh AI instance with no memory of the design conversation. Read all of the following before implementing:

1. **PRD #20 Decision Log** (`prds/20-otel-genai-semconv-migration.md`, Locked Decisions table) — M3 inherits the OTel Operator delivery, shared Python Instrumentation CRD, and SDK bootstrap. Do not re-decide these.
2. **`research/31-guard-proxy-sanitization-tracing-2026.md`** — Issue #12 output. Contains the full before/after capture pattern, the `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` library-scoping proof, Datadog's span-kind classification requirements, and the Collector-vs-SDS redaction analysis. Every implementation decision in this PRD traces back to findings in this file.
3. **`research/05-otel-genai-observability.md`** — Re-leak trap design and the four re-leak controls.
4. **Issue #19** — Pre-drafted guard-proxy instrumentation spec (try/except import guard pattern, HTTP SERVER span shape, `sanitize` child span attributes). The Milestone 1 implementation must match this spec.
5. **`agent/gateway/guard-proxy/proxy.py`** — Read the full file before editing. Understand the `do_POST` handler, the block-list and LLM Guard paths, and where `text` (original prompt) and `output_scrub` (sanitized output) are held in scope.
6. **`gitops/apps/otel-collector.yaml`** — Read the full Collector config before adding the OTTL transform. Understand the existing pipeline shape, processor order, and export legs.

---

## Milestones

### Milestone 1 — guard-proxy: HTTP SERVER span + sanitize INTERNAL child span

**Step 0:** Read all files listed in the "Step 0: What to Read Before Starting" section above. Do not edit `proxy.py` until you have read it in full AND read `research/31` in full.

**Steps:**

1. Read `agent/gateway/guard-proxy/proxy.py` in full. Identify: where `do_POST` is defined; where the original prompt `text` is extracted; where `output_scrub` (sanitized output) is produced; the existing import block.

2. At the top of `proxy.py` (after existing imports), add a `try/except ImportError` guard for the OTel API. This keeps the file runnable when the Operator has not yet injected the SDK:
   ```python
   try:
       from opentelemetry import trace
       from opentelemetry.trace import SpanKind
       from opentelemetry.propagate import extract, inject
       _OTEL_AVAILABLE = True
   except ImportError:
       _OTEL_AVAILABLE = False
   ```
   `SpanKind` is required for Step 4 (`SpanKind.SERVER`). It must be inside the same try/except — if the OTel SDK is absent, `SpanKind` is also absent.

3. Immediately after the import guard, add the content capture gate (read once at module load, not per-request):
   ```python
   import os as _os
   _CAPTURE_MODE = _os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "NO_CONTENT").upper()
   _CAPTURE_CONTENT = _CAPTURE_MODE in ("SPAN_ONLY", "EVENT_ONLY", "SPAN_AND_EVENT")
   # "true" is NOT a valid enum value — do not treat it as enabling capture
   ```

4. In `do_POST`, if `_OTEL_AVAILABLE` is True, create an HTTP SERVER span using `trace.get_tracer(__name__).start_as_current_span(...)`. Before creating the span, call `extract(request.headers)` to propagate incoming trace context from agentgateway (so the proxy span joins the upstream trace). Use `SpanKind.SERVER`. Set `http.request.method`, `url.path`, and `http.response.status_code` as span attributes.

5. Inside the HTTP SERVER span, create a `sanitize` INTERNAL child span that wraps the sanitization logic (block-list check + LLM Guard path + forwarding decision). Set these attributes on the sanitize span:
   - `gen_ai.operation.name`: `"chat"` (required; see Locked Decisions)
   - If `_CAPTURE_CONTENT` is True:
     - `gen_ai.input.messages`: `json.dumps([{"role": "user", "parts": [{"type": "text", "content": original_text}]}])`
     - `gen_ai.output.messages`: `json.dumps([{"role": "user", "parts": [{"type": "text", "content": sanitized_text}]}])`
   - Where `original_text` is the prompt before any guard runs and `sanitized_text` is the output after sanitization.
   - `json` is a Python stdlib module. If it is not already imported in `proxy.py`, add `import json` to the stdlib imports at the top of the file.

6. When forwarding the request to kagent, call `inject(forward_headers)` to propagate the active trace context, so kagent's ADK spans join the same trace.

7. Do not add `witb.*` custom attributes in this milestone. Keep the span shape to the semconv-defined attributes only.

**Done when:**
- [ ] `proxy.py` has try/except import guard for `opentelemetry.trace` and `opentelemetry.propagate`
- [ ] `_CAPTURE_CONTENT` gate reads `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`; `true` does NOT enable capture
- [ ] HTTP SERVER span wraps `do_POST` with extracted upstream trace context
- [ ] `sanitize` INTERNAL child span sets `gen_ai.operation.name="chat"`
- [ ] When `_CAPTURE_CONTENT` is True, `gen_ai.input.messages` (original) and `gen_ai.output.messages` (sanitized) are set as JSON strings per OTel messages schema
- [ ] `inject()` called on forward headers to propagate trace context to kagent

---

### Milestone 2 — Collector OTTL transform overlay for Act 2 (re-leak trap fix)

**Step 0:** Read `gitops/apps/otel-collector.yaml` in full before adding any config. Understand the existing processor block and pipeline shape. Milestone 1 must be deployed and Act 1 verified (leak visible in Datadog) before this milestone adds value.

Act 2 of the re-leak-trap beat is: the instructor applies this OTTL overlay, re-runs the beat, and Datadog now shows `[DEMO-REDACTED]` instead of the sentinel — demonstrating that the Collector boundary prevents the leak from reaching the observability platform.

**Steps:**

1. Read `gitops/apps/otel-collector.yaml` in full. Identify: the `processors:` block; the `service.pipelines.traces` processor list; the Datadog exporter key.

2. Create `gitops/apps/otel-collector-act2-overlay.yaml`. Before choosing the file format, check `gitops/apps/` for any existing overlay or patch files — if a pattern exists, follow it. If no overlay pattern exists, write this as a **complete standalone Collector config** (not a patch fragment): copy the full content of `otel-collector.yaml`, add the `transform/redact_sentinel` processor definition to the `processors:` block, and add it to the traces pipeline before the Datadog exporter. The instructor applies this with `kubectl apply -f` replacing the base config for Act 2, and removes it to return to Act 1. It adds a `transform/redact_sentinel` processor to the traces pipeline, positioned before the Datadog exporter and after span-sampling processors (if any). The transform:
   - Targets spans where `attributes["gen_ai.operation.name"] == "chat"` AND `IsString(attributes["gen_ai.input.messages"])`
   - Sets `attributes["gen_ai.input.messages"] = "[DEMO-REDACTED]"` (string replacement, not deletion)
   - Sets `attributes["gen_ai.output.messages"] = "[DEMO-REDACTED]"` (same)
   - Does NOT modify any other spans

3. Add a comment block in `otel-collector.yaml` (near the top of the processors section) explaining the two-act beat and referencing the overlay file:
   ```yaml
   # Re-leak-trap beat (Act 2): apply otel-collector-act2-overlay.yaml to replace
   # sanitize span content with [DEMO-REDACTED] before Datadog export.
   # Act 1 (baseline): this file only — original prompt visible in Datadog LLM Observability.
   # See prds/22-security-beats-observability.md for the full runbook.
   ```

4. Do NOT modify the base `otel-collector.yaml` pipeline — the overlay is the Act 2 toggle.

**Done when:**
- [ ] `gitops/apps/otel-collector-act2-overlay.yaml` exists with `transform/redact_sentinel` processor
- [ ] Processor replaces (not deletes) `gen_ai.input.messages` and `gen_ai.output.messages` with `"[DEMO-REDACTED]"` on matching spans
- [ ] Processor does not affect non-`sanitize` spans
- [ ] Comment in `otel-collector.yaml` references the overlay and explains the two-act structure

---

### Milestone 3 — Add guard-proxy span groups to the M2 Weaver registry

**Step 0:** Read the Weaver registry files created in PRD #20 before editing. Do not create a new registry; extend the existing one. Locate it by reading `prds/20-otel-genai-semconv-migration.md` to find the registry path.

**Steps:**

1. Locate the Weaver registry from PRD #20. Read its `registry_manifest.yaml` and existing group definition files to understand naming conventions and structure.

2. Add a span group definition for guard-proxy **HTTP SERVER spans** with the service name `guard-proxy`. Include attributes: `http.request.method` (Required), `url.path` (Recommended), `url.scheme` (Recommended), `http.response.status_code` (Required). Reference the OTel HTTP semconv dependency already in the registry for these attribute definitions.

3. Add a span group definition for guard-proxy **`sanitize` INTERNAL spans** with the service name `guard-proxy`. Include attributes:
   - `gen_ai.operation.name` (Required, value `"chat"`)
   - `gen_ai.input.messages` (Opt-In — only present when content capture is enabled)
   - `gen_ai.output.messages` (Opt-In — only present when content capture is enabled)

4. Run `weaver registry check` locally to confirm the registry is valid. Fix any errors before committing.

5. Update the CI step (if it exists from PRD #20) to include the new span groups. If PRD #20 added a `registry check` step to a GitHub Actions workflow, it covers the full registry automatically — no change needed.

6. Add a comment to the `sanitize` span group definition explaining the `live-check` acceptance step: run `weaver registry live-check` against a cluster where a beat has been executed with `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY` to validate the `gen_ai.input/output.messages` attributes are present and conform to schema. This is manual only — not a CI gate.

**Done when:**
- [ ] guard-proxy HTTP SERVER span group added to Weaver registry
- [ ] guard-proxy `sanitize` INTERNAL span group added with `gen_ai.operation.name`, `gen_ai.input.messages` (Opt-In), `gen_ai.output.messages` (Opt-In)
- [ ] `weaver registry check` passes locally and in CI
- [ ] `live-check` acceptance step documented in a comment on the `sanitize` span group

---

### Milestone 4 — End-to-end verification + two-act demo runbook

**Step 0:** Milestones 1, 2, and 3 must be complete and deployed to a live cluster before this milestone begins. Read the Locked Decisions table above (especially the two-act beat description) before writing the runbook.

**Steps:**

1. **Verify Beat 3 rogue tool-call chain.** Run the excessive-agency beat (`beats/03-bad-mcp-excessive-agency/`). Confirm in Datadog APM that the trace waterfall shows `invoke_agent → chat → execute_tool {tool_name}` where `{tool_name}` is the evil MCP tool name. If ADK emits tool results natively in `gen_ai.output.messages` on the `execute_tool` span, note it in the runbook as a bonus. If not, note "tool result not captured — caller-side tool name only" as the accepted state.

2. **Verify Collector → LLM Observability routing of `sanitize` spans.** Confirm that `sanitize` spans with `gen_ai.operation.name="chat"` appear in Datadog LLM Observability (not just APM). This is the open item from `research/28` Q7. If routing fails via the contrib `datadog` exporter, fall back to a dedicated OTLP exporter with `dd-otlp-source=llmobs` header and document the fallback in this PRD's Decision Log.

3. **Run Act 1.** Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY` on the guard-proxy Deployment. Run a prompt that passes through the sanitization path. Confirm:
   - The `sanitize` span appears in Datadog LLM Observability
   - `gen_ai.input.messages` shows the original (unsanitized) prompt text
   - `gen_ai.output.messages` shows the sanitized prompt text

4. **Run Act 2.** Apply `gitops/apps/otel-collector-act2-overlay.yaml`. Run the same prompt again. Confirm:
   - The `sanitize` span now shows `gen_ai.input.messages = "[DEMO-REDACTED]"` in Datadog
   - `gen_ai.output.messages = "[DEMO-REDACTED]"` as well
   - The span key is still present (not deleted)

5. **Teardown.** Remove `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` from the guard-proxy Deployment (or set to `NO_CONTENT`). Confirm that subsequent spans do not carry content.

6. **Write the demo runbook.** Before creating the file, read the `beats/03-bad-mcp-excessive-agency/` directory to understand what files exist and match their naming conventions. Create an `OBSERVABILITY-RUNBOOK.md` (or the closest matching existing convention) covering:
   - Beat 3: what the attendee sees in Datadog APM (no instructor action required; ADK emits natively)
   - Re-leak-trap beat: Act 1 kubectl commands, expected Datadog view, Act 2 kubectl apply command, expected Datadog view, teardown commands
   - Verify-at-build findings: whether ADK captured tool results, whether Collector → LLM-Obs routing required the fallback OTLP exporter

**Done when:**
- [ ] Beat 3 `execute_tool {tool_name}` waterfall confirmed in Datadog APM; tool result capture status documented
- [ ] Collector → LLM-Obs routing confirmed for `sanitize` spans (or fallback documented in Decision Log)
- [ ] Act 1 confirmed: original prompt visible in Datadog LLM Observability on the `sanitize` span
- [ ] Act 2 confirmed: `[DEMO-REDACTED]` visible in Datadog after overlay applied
- [ ] Teardown confirmed: `NO_CONTENT` stops content capture on subsequent spans
- [ ] Demo runbook written and committed in `beats/03-bad-mcp-excessive-agency/`

---

## Acceptance Criteria

- [ ] before/after sanitization visible in Datadog LLM Observability as a two-act demo (Act 1: sentinel visible; Act 2: `[DEMO-REDACTED]`)
- [ ] rogue MCP tool-call chain (`execute_tool {bad_tool_name}`) visible as a waterfall in Datadog APM traces
- [ ] Weaver `live-check` passes for guard-proxy HTTP SERVER and `sanitize` INTERNAL span groups (manual step; not a CI gate)
- [ ] `weaver registry check` passes in CI (static validation, no live cluster needed)
- [ ] Verify-at-build item documented: whether ADK natively captures tool results in `gen_ai.output.messages` on `execute_tool` spans
- [ ] Verify-at-build item documented: whether Collector → LLM-Obs routing works via contrib `datadog` exporter natively, or requires fallback OTLP exporter
- [ ] PROGRESS.md updated

---

## Decision Log

| Date | Decision | Reasoning |
|---|---|---|
| 2026-06-24 | `sanitize` span uses `gen_ai.operation.name="chat"` | Datadog classifies spans as `llm` kind (rendering Input/Output panel) only for `generate_content`, `chat`, `text_completion`, `completion`. A descriptive value like `"sanitize"` silently disables the panel; the before/after messages would not appear in LLM Observability. research/31 Q5 confirmed `"chat"` is in the documented list. |
| 2026-06-24 | Content capture gated on env var read explicitly in proxy.py (M3 Decision 2, Option A) | `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` is specific to `opentelemetry-util-genai` and contrib instrumentations — it does NOT govern raw hand-written SDK spans (research/31 Q3, REFUTED as stated). Proxy must read the env var itself. Default `NO_CONTENT` matches the rest of the stack's off-by-default discipline and BUILD-SPEC §4 ("off by default; advanced beat"). |
| 2026-06-24 | `true` value for `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` must NOT enable capture | `true` is an invalid enum value on both the ADK path (silently collects nothing) and the proxy path. Treating it as enabling capture would create a footgun. The valid enum values are `NO_CONTENT` (default), `SPAN_ONLY`, `EVENT_ONLY`, `SPAN_AND_EVENT`. |
| 2026-06-24 | Beat 3: ADK-native execute_tool spans only; shim stays dark (M3 Decision 3, Option A) | evil-mcp-shim is intentionally dark (meta-PRD Decision Log 2026-06-24). `execute_tool {gen_ai.tool.name}` from the kagent/ADK caller side names the bad tool and is sufficient for the Beat 3 waterfall narrative. Tool result capture adds a non-semconv custom attribute and instrumentation risk; it is a verify-at-build item. |
| 2026-06-24 | Two-act re-leak-trap beat (M3 Decision 4, Option C) | Option A (env var flip only) violates research/05 re-leak control #4 — the sentinel persists in Datadog. Option B (Collector redacts before demo) kills the narrative — attendees cannot see the leak if it is already redacted. Option C is the pedagogical point: show the leak exists (Act 1), then show it is preventable at the Collector boundary (Act 2). |
| 2026-06-24 | OTTL `transform` processor (not `redactionprocessor`) for Act 2 | `redactionprocessor` deletes attributes. The demo requires the attribute key to remain visible on the span (showing `[DEMO-REDACTED]`) so Datadog confirms the redaction happened. `transform` processor allows value replacement. |
| 2026-06-24 | Act 2 config in a separate overlay file (not base otel-collector.yaml) | The base config represents Act 1 state (content flows unredacted to Datadog). The overlay is the Act 2 toggle. Keeping them separate prevents accidental Act 2 startup state and makes the instructor's apply/remove action explicit and reversible. |
