# PRD #27: AI Layer UST, Service Map & Log-Trace Correlation

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/27
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 6 AI layer child PRD
**Priority**: High
**Status**: M1-M5 implemented and locally verified (2026-06-25); live-cluster acceptance pending (needs agentgateway deployed + a test workload). See Decision Log for the two implementation deviations.

---

## Problem

After Milestones 1–5, the AI layer emits OTel GenAI semconv telemetry through the Collector to Datadog, but two workshop story gaps remain:

1. **Service Map does not render the expected topology.** The `guard-proxy → agentgateway → kagent → Bedrock` chain requires CLIENT spans with `peer.service` set correctly. agentgateway's `service.version` and `deployment.environment.name` are stale placeholders from the pre-M1 era, breaking UST alignment. guard-proxy emits no CLIENT span at all, so the `guard-proxy → agentgateway` edge is absent from the Service Map.

2. **Log-trace correlation pivots don't work.** "View related logs" from a trace and "View trace in APM" from a log both require `trace_id`/`span_id` fields in log records. guard-proxy currently emits zero log output — `log_message` returns `None` (suppresses BaseHTTPRequestHandler access log); there is no `logging` call, no `print()`, no `sys.stderr` anywhere in `proxy.py`. Without structured JSON logs with trace context, neither pivot direction works.

Scope: AI layer only — `agent/gateway/` and `gitops/ai-layer/` only. Platform component UST (third-party Helm charts) is a separate follow-on PRD.

---

## Solution

1. Fix the two stale UST values in `agent/gateway/agentgateway.yaml` so agentgateway's telemetry aligns with the locked M1 vocabulary.
2. Add a guard-proxy outbound CLIENT span wrapping the HTTP call to agentgateway, with `peer.service="agentgateway"` set at span creation, and add structured JSON logging with OTel trace context injected on guard decision events.
3. Add an OTTL `transform` processor in the Collector as a fallback to set `peer.service` on agentgateway→kagent and kagent→Bedrock CLIENT spans if those components don't emit it natively (verify-at-build).
4. Add the guard-proxy CLIENT span group definition to the Weaver registry; run `weaver registry check` locally before merge; run `weaver live-check` as the terminal acceptance step on a live cluster.
5. Write `verify/test_datadog_service_map.py` asserting Service Map edges via `GET /api/v1/service_dependencies` and both log-trace pivot directions via the Datadog logs/APM APIs.

---

## Locked Decisions (do not re-open)

These were finalized in the M6 design conversation (2026-06-25). Read PRD #7 M6 Decision Log for full reasoning.

| Decision | Value |
|---|---|
| agentgateway `service.version` | `v1.3.0` (was `CLUSTER_TIER`) |
| agentgateway `deployment.environment.name` | `production` (was `watch-it-burn`) |
| guard-proxy CLIENT span `peer.service` | Set in `proxy.py` code at span creation — `"agentgateway"` |
| agentgateway/kagent `peer.service` | OTTL transform processor as fallback; verify-at-build if already native |
| guard-proxy log-trace correlation mechanism | stdlib `logging` + JSON formatter to stdout; extract `trace_id`/`span_id` from `opentelemetry.trace.get_current_span().get_span_context()` |
| Guard decision events to log | Blocklist hit, classifier block, output scrub fired, agent forward error |
| Datadog field name recognition | `trace_id` and `span_id` (OTel-standard) — Datadog auto-recognizes these; no remapping config needed |
| OTel SDK delivery | OTel Operator (M2 Decision 2); `proxy.py` carries only `opentelemetry-api` imports; SDK injected at pod startup |
| `gen_ai.operation.name="chat"` on sanitize span | Already decided in M3/PRD #22 — do NOT change |
| Service Map acceptance | Binary via `GET /api/v1/service_dependencies` — no browser automation |
| Weaver `registry check` | CI gate (runs on every push) |
| Weaver `live-check` | Manual terminal acceptance step — NOT a CI gate |
| Scope | AI layer only (`agent/gateway/`, `gitops/ai-layer/`) — no platform component manifests |
| `deployment.environment.name` attribute name | `deployment.environment.name` (OTel semconv v1.27.0+ — NOT the deprecated `deployment.environment`) |
| UST values for other AI-layer components | Already correct from M1/M2 — do NOT change kagent, guard-proxy, evil-mcp-shim UST values |

---

## Step 0: What to Read Before Starting Any Milestone

This PRD is executed by a fresh AI instance with no memory of the design conversation. Read all of the following before implementing:

1. **PRD #7 M6 Decision Log entries (2026-06-25)** (`prds/7-observability-meta.md`) — full reasoning behind every locked decision above.
2. **PRD #20 Decision Log** (`prds/20-otel-genai-semconv-migration.md`) — OTel Operator Instrumentation CRD shape; single shared `watch-it-burn-python` CRD for all custom Python pods; UST env vars go on each workload's pod spec (NOT in the CRD).
3. **PRD #22 Decision Log** (`prds/22-security-beats-observability.md`) — existing Weaver registry structure; guard-proxy HTTP SERVER and `sanitize` INTERNAL span groups already defined; use these as the template for the new CLIENT span group.
4. **PRD #26** (`prds/26-datadog-agent-daemonset-named-integrations.md`) — Datadog Agent DaemonSet is deployed; `datadog-secret` shape confirmed (`api-key` + `app-key`).
5. **`agent/gateway/agentgateway.yaml`** — read in full; locate the stale UST values to fix.
6. **`agent/gateway/guard-proxy/proxy.py`** — read in full; locate the outbound HTTP call to agentgateway (the CLIENT span wraps this call); note the current import structure and the `log_message` method that suppresses all log output.
7. **`gitops/apps/otel-collector.yaml`** — read in full; understand the existing pipeline shape before placing the OTTL `transform` processor.
8. **`weaver/registry/`** — read all existing group definition files; follow their naming and structure conventions exactly when adding the CLIENT span group.
9. **`verify/test_observability.py`** — read in full; match its style (DD_API_KEY/DD_APP_KEY from env, Python `requests`, assertion patterns) when writing `verify/test_datadog_service_map.py`.
10. **`gitops/ai-layer/resources.yaml`** — read to confirm current UST values on kagent, guard-proxy, evil-mcp-shim (these should NOT change in this PRD).

**Do NOT start implementing until you have read items 1, 5, 6, and 7.**

---

## Milestone Working Pattern

Every milestone follows this iterate loop:

1. **Implement** — make the code/config change
2. **Deploy** — `git commit`, push, ArgoCD sync (or `kubectl apply` for the relevant resources)
3. **Check Datadog** — query the Datadog API (see each milestone's verification step) or use the Datadog MCP tool if available in session
4. **Diagnose** — if the expected result is not present, inspect span attributes via `GET /api/v1/traces` or the Datadog MCP `search_datadog_spans` tool; check `peer.service`, span kind, and resource attributes
5. **Adjust** — fix the config or code based on what the API returned
6. **Re-check** — repeat from step 3 until the check passes

The acceptance script (`verify/test_datadog_service_map.py`) is the final gate, not the first check. Expect multiple deploy-check-adjust cycles per milestone.

---

## Milestones

> **Deployment model:** Each milestone may be committed and deployed independently — Michael should deploy and verify each milestone before starting the next (this is the iterate loop). A single PR containing all five milestones is also acceptable; the "Done when" checklists are per-milestone regardless.

### Milestone 1 — Fix agentgateway UST stale values

**Step 0:** Read `agent/gateway/agentgateway.yaml` in full. Locate all `OTEL_RESOURCE_ATTRIBUTES` env var entries. Note the current values for `service.version` and `deployment.environment.name`.

**Context:** agentgateway.yaml was written before M1 locked UST vocabulary. Two values are stale placeholders that break Datadog UST alignment:
- `service.version=CLUSTER_TIER` — `CLUSTER_TIER` is not a version; correct value is `v1.3.0` (agentgateway GA release, locked in M1 Decision Log 2026-06-23)
- `deployment.environment.name=watch-it-burn` — `watch-it-burn` is the project name, not an SDLC env; correct value is `production` (all stack components use `production`, locked in M1 Decision Log 2026-06-23)

**Steps:**

1. In `agent/gateway/agentgateway.yaml`, find the `OTEL_RESOURCE_ATTRIBUTES` env var value and replace `service.version=CLUSTER_TIER` with `service.version=v1.3.0` and `deployment.environment.name=watch-it-burn` with `deployment.environment.name=production`. The full attribute string format is a comma-separated list: `service.name=agentgateway,service.version=v1.3.0,deployment.environment.name=production,...` — preserve all other attributes exactly.

   **Do NOT change** any other component's UST values in `gitops/ai-layer/resources.yaml` or elsewhere — this milestone touches `agent/gateway/agentgateway.yaml` only.

2. Deploy the change to the cluster.

3. Verify: wait ~2 minutes for telemetry to flow, then query `GET /api/v1/services` or use the Datadog MCP `search_datadog_services` tool. Confirm `agentgateway` appears with `env:production` and `version:v1.3.0` tags. If the service does not appear within 5 minutes, check whether agentgateway pods have restarted and whether the Collector is forwarding spans.

**Done when:**
- [x] `agent/gateway/agentgateway.yaml` has `service.version=v1.3.0` and `deployment.environment.name=production` in `OTEL_RESOURCE_ATTRIBUTES`
- [x] No other UST values changed in this PR
- [ ] agentgateway appears in Datadog with `env:production` and `version:v1.3.0` (verified via Datadog API or MCP). LIVE: pending agentgateway deploy

---

### Milestone 2 — Add guard-proxy CLIENT span and structured JSON logging

**Step 0:** Read `agent/gateway/guard-proxy/proxy.py` in full. Note: (1) where the outbound HTTP call to agentgateway is made — this is the call the CLIENT span wraps; (2) the `log_message` method override that suppresses all log output; (3) the existing import structure to follow.

**Context:** Two proxy.py changes are combined in this milestone because they share OTel span-context extraction:
- The CLIENT span records the outbound call to agentgateway and sets `peer.service="agentgateway"` — this creates the `guard-proxy → agentgateway` edge in the Service Map.
- Structured JSON logging records guard decision events with `trace_id`/`span_id` fields injected from the active span context — this enables both log-trace pivot directions.

The OTel SDK is already injected at pod startup by the OTel Operator (M2 Decision 2). `proxy.py` should import only from `opentelemetry-api` (`opentelemetry.trace`, `opentelemetry.context`) — do NOT add SDK or exporter imports.

**Import constraint:** `proxy.py` must import ONLY from `opentelemetry.api` packages — specifically `opentelemetry.trace` and `opentelemetry.trace.SpanKind`. Do NOT import from `opentelemetry.sdk.*`, `opentelemetry.exporter.*`, or any exporter package. The OTel Operator injects the full SDK at pod startup via PYTHONPATH — importing SDK packages directly would break when the Operator is absent (e.g., local testing). Place all OTel imports at module level once; Steps 1 and 2 both reference the same `trace` import.

**Steps:**

1. **CLIENT span:** In the method that makes the outbound HTTP request to agentgateway, wrap the call with an OTel CLIENT span:

   ```python
   from opentelemetry import trace
   from opentelemetry.trace import SpanKind

   tracer = trace.get_tracer(__name__)

   # Inside the method that calls agentgateway:
   with tracer.start_as_current_span(
       "HTTP POST",
       kind=SpanKind.CLIENT,
       attributes={
           "http.request.method": "POST",
           "url.full": agentgateway_url,   # the full URL being called
           "peer.service": "agentgateway",
       }
   ) as span:
       response = <existing http call here>
       span.set_attribute("http.response.status_code", response.status)
   ```

   Adapt the attribute values to match what the existing code already has. Use OTel stable HTTP semconv attribute names (`http.request.method`, `url.full`, `http.response.status_code`) — these are in `@opentelemetry/semantic-conventions` stable tier. Replace `<existing http call here>` with the actual call from `proxy.py`. Do NOT leave any placeholder comments in the final file.

2. **Structured JSON logging:** Add a JSON logging setup at module level:

   ```python
   import logging
   import json

   class _JsonFormatter(logging.Formatter):
       def format(self, record):
           span = trace.get_current_span()
           ctx = span.get_span_context()
           entry = {
               "level": record.levelname,
               "msg": record.getMessage(),
               "logger": record.name,
           }
           if ctx.is_valid:
               entry["trace_id"] = format(ctx.trace_id, "032x")
               entry["span_id"] = format(ctx.span_id, "016x")
           return json.dumps(entry)

   _handler = logging.StreamHandler()
   _handler.setFormatter(_JsonFormatter())
   logger = logging.getLogger("guard_proxy")
   logger.addHandler(_handler)
   logger.setLevel(logging.INFO)
   ```

   Replace the existing `log_message` method override (which returns `None` / suppresses output) with a pass-through or remove the override entirely — the `logger` above writes to stdout, which the Datadog Agent's container log pipeline will collect.

3. **Add logger calls at guard decision events:**

   ```python
   # Blocklist hit:
   logger.info("blocklist hit", extra={"event": "blocklist_hit", "matched_term": term})
   # Classifier block:
   logger.info("classifier block", extra={"event": "classifier_block", "score": score})
   # Output scrub fired:
   logger.info("output scrub fired", extra={"event": "output_scrub"})
   # Forward error:
   logger.error("forward error", extra={"event": "forward_error", "status": status_code})
   ```

   Include these fields in the JSON formatter's `format` method by iterating `record.__dict__` for extra fields. Adapt the exact field names to whatever the existing guard code uses.

4. Deploy the updated `proxy.py`. Wait ~2 minutes, then:
   - Verify the CLIENT span: use Datadog MCP `search_datadog_spans` to find a recent `guard-proxy` span with `span.kind=client` and `peer.service=agentgateway`. If not found, check that the Operator has injected the SDK (look for `OTEL_EXPORTER_OTLP_ENDPOINT` in the pod's env via `kubectl describe pod`).
   - Verify the logs: check the Datadog logs API or Log Explorer for `guard-proxy` service log records containing `trace_id` and `span_id` fields.

**Done when:**
- [x] `proxy.py` contains a CLIENT span wrapping the outbound agentgateway call with `peer.service` (derived to `agentgateway` in target topology, see Decision Log), `http.request.method`, `url.full`, `http.response.status_code`
- [x] `proxy.py` contains `logging` + JSON formatter that injects `trace_id`/`span_id` from the active span context
- [x] Four guard decision events (blocklist hit, classifier block, output scrub, forward error) emit log records
- [ ] Datadog shows guard-proxy CLIENT spans with `peer.service=agentgateway` (verified via Datadog MCP or API). LIVE: pending agentgateway deploy
- [ ] Datadog shows guard-proxy log records with `trace_id` and `span_id` fields (verified via logs API or Log Explorer). LIVE

---

### Milestone 3 — OTTL peer.service fallback for third-party component spans

**Step 0:** Read `gitops/apps/otel-collector.yaml` in full. Note the existing `processors:` block — especially any existing `transform` or `resource` processors and how they are referenced in pipeline definitions. Read the spans flowing from agentgateway and kagent to understand their current attribute set.

**Context:** The Service Map needs `guard-proxy → agentgateway → kagent → Bedrock`. Milestone 2 gives us the `guard-proxy → agentgateway` edge. The `agentgateway → kagent` and `kagent → Bedrock` edges require CLIENT spans from those components with `peer.service` set. agentgateway and kagent are third-party components (not directly editable here) — the OTTL `transform` processor in the Collector is the fallback mechanism to set `peer.service` if they don't already emit it.

**Verify-at-build first:** Before adding OTTL rules, check whether agentgateway and kagent already set `peer.service` on their CLIENT spans. Use Datadog MCP `search_datadog_spans` to find a recent CLIENT span from agentgateway or kagent and inspect its attributes. If `peer.service` is already present and correct on both, skip the OTTL rules for that component (the rule is not needed). Only add OTTL rules for components where `peer.service` is absent.

**Steps:**

1. **Check native peer.service emission:**

   ```bash
   # Use the Datadog MCP search_datadog_spans tool or query:
   # Filter: service:agentgateway, span.kind:client
   # Check attribute: peer.service
   ```

   Record what you find: present (skip) or absent (add OTTL rule).

2. **Add OTTL transform processor (only for components where peer.service is absent):**

   In `gitops/apps/otel-collector.yaml`, add a `transform` processor entry under `processors:`:

   ```yaml
   processors:
     # ... existing processors ...
     transform/set_peer_service:
       trace_statements:
         - context: span
           # Set peer.service on agentgateway CLIENT spans calling kagent
           # Adjust the condition to match the actual span name/attributes emitted by agentgateway
           statements:
             - set(attributes["peer.service"], "kagent") where attributes["peer.service"] == nil and resource.attributes["service.name"] == "agentgateway" and kind == SPAN_KIND_CLIENT
             - set(attributes["peer.service"], "Bedrock") where attributes["peer.service"] == nil and resource.attributes["service.name"] == "kagent" and kind == SPAN_KIND_CLIENT and IsMatch(attributes["url.full"], ".*bedrock.*")
   ```

   **Important:** Verify the exact span name, service name, and URL pattern by inspecting real spans before writing the condition. Do not hardcode assumptions from training data — use `search_datadog_spans` to inspect actual attribute values. The condition must be narrow enough to avoid setting `peer.service` on spans where it is already correct.

   **OTTL syntax:** Before writing the statements, search `otel-collector.yaml` for any existing `transform` processor to confirm which OTTL functions are in use. If none exists, verify that `IsMatch` is available in otelcol-contrib 0.158.2 by checking the [OTTL functions list](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/pkg/ottl/ottlfuncs). If `IsMatch` is unavailable, replace it with a string equality check on a known attribute (e.g., `attributes["url.full"] == "https://kagent.agent.svc.cluster.local/..."`). Do NOT commit an OTTL statement whose functions are unverified — a bad transform processor silently drops all spans in the pipeline.

3. Add `transform/set_peer_service` to the `traces` pipeline's `processors` list in the `service.pipelines` section of `otel-collector.yaml`. Place it after any existing attribute processors and before the exporter.

4. Deploy and verify: use `search_datadog_spans` to find CLIENT spans from agentgateway and kagent and confirm `peer.service` is now set correctly on each.

**Done when:**
- [x] OTTL rules added (or skipped with documented reason) for agentgateway→kagent and kagent→Bedrock `peer.service` (agentgateway→kagent added; kagent→Bedrock deliberately deferred to Datadog auto-inference, see Decision Log)
- [x] If rules were added, `transform/set_peer_service` is referenced in the traces pipeline
- [x] `otel-collector.yaml` YAML is valid
- [ ] agentgateway CLIENT spans show `peer.service=kagent` in Datadog (verified via MCP or span attributes). LIVE: pending agentgateway deploy
- [ ] kagent CLIENT spans show `peer.service=Bedrock` (or `peer.service` is already correct natively). LIVE / verify-at-build (Bedrock expected external-only)

---

### Milestone 4 — Weaver registry: guard-proxy CLIENT span group

**Step 0:** Read all existing `.yaml` files in `weaver/registry/` to understand the group definition format, naming convention, and how existing groups reference OTel community semconv via the `dependencies:` import. The HTTP SERVER and `sanitize` INTERNAL groups from PRD #22 are the closest templates for this CLIENT span group.

**Context:** The Weaver registry grows incrementally — every PRD that introduces new span groups extends the registry in the same PR (Decision Log 2026-06-25 in PRD #7). This milestone adds one new group: guard-proxy's outbound CLIENT span to agentgateway.

`peer.service` itself is defined in the upstream OTel semconv registry (available via the `dependencies:` import) — no local definition needed for that attribute. The local group definition declares which attributes guard-proxy's CLIENT span is expected to carry.

**Steps:**

1. Add a new group definition file (or extend the existing guard-proxy registry file) for the `guard-proxy.egress` (or equivalent name matching the existing naming pattern) CLIENT span group. The group must declare:
   - `http.request.method` (OTel stable HTTP semconv)
   - `url.full` (OTel stable HTTP semconv)
   - `http.response.status_code` (OTel stable HTTP semconv)
   - `peer.service` (OTel stable resource semconv — references the upstream dependency, no local definition needed)

   Follow the naming and structure of the existing guard-proxy groups exactly.

2. Run `weaver registry check` locally:

   ```bash
   ~/.cargo/bin/weaver registry check -r weaver/registry/
   ```

   Fix any schema errors before proceeding. The check must pass with zero errors.

3. Commit this milestone's changes alongside the Milestone 2 proxy.py changes (or as a separate commit — either is fine).

4. **Terminal acceptance (live-check):** After deploying the full stack to a live cluster and running a test workload, run:

   ```bash
   ~/.cargo/bin/weaver registry live-check --format json -r weaver/registry/ --endpoint http://localhost:4318
   ```

   (Port-forward the Collector's OTLP HTTP receiver to localhost:4318 first.) The live-check is the final human-in-the-loop validation — it is NOT a CI gate. Run it as the last acceptance step before closing this PRD.

**Done when:**
- [x] Weaver registry contains a group definition for guard-proxy's CLIENT span with `http.request.method`, `url.full`, `http.response.status_code`, and `peer.service` (`span.witb.guard_proxy.egress`)
- [x] `weaver registry check` passes locally with zero errors
- [ ] `weaver live-check` run as the terminal acceptance step on a live cluster (result documented, see Acceptance Criteria). LIVE

---

### Milestone 5 — Service Map + log-trace correlation verification script

**Step 0:** Read `verify/test_observability.py` in full to match its style: how it imports `requests`, reads `DD_API_KEY`/`DD_APP_KEY` from environment, constructs Datadog API URLs, makes assertions, and handles errors. The new script follows the same pattern.

**Context:** This milestone writes `verify/test_datadog_service_map.py` — a Python script that asserts three things using the Datadog API:
1. Service Map edges: `GET /api/v1/service_dependencies` returns the expected `guard-proxy → agentgateway → kagent → Bedrock` topology (or 3 internal edges if Bedrock is external-only — verify-at-build what the live cluster actually returns).
2. Log-trace forward pivot: querying logs with a known `trace_id` returns ≥1 result.
3. Log-trace reverse pivot: querying APM for a known trace returns associated logs.

The `trace_id` used for assertions 2 and 3 is harvested from a recent live cluster run (call `search_datadog_spans` to find a recent guard-proxy span and extract its `trace_id`).

**Steps:**

1. Write `verify/test_datadog_service_map.py` with three test functions:

   ```python
   # ABOUTME: Verifies Datadog Service Map edges and log-trace correlation for the AI layer.

   import os, sys, requests

   DD_API_KEY = os.environ["DD_API_KEY"]
   DD_APP_KEY = os.environ["DD_APP_KEY"]
   DD_SITE = "datadoghq.com"
   HEADERS = {"DD-API-KEY": DD_API_KEY, "DD-APPLICATION-KEY": DD_APP_KEY}

   EXPECTED_EDGES = [
       ("guard-proxy", "agentgateway"),
       ("agentgateway", "kagent"),
       # ("kagent", "Bedrock"),  # verify-at-build: Bedrock may appear as external-only
   ]

   def test_service_map_edges():
       """Assert all expected service dependency edges are present."""
       r = requests.get(
           f"https://api.{DD_SITE}/api/v1/service_dependencies",
           headers=HEADERS,
           params={"start": ..., "end": ...},  # last 30 minutes
       )
       r.raise_for_status()
       deps = r.json()
       # deps is a dict: {service_name: [downstream_service, ...]}
       for caller, callee in EXPECTED_EDGES:
           assert callee in deps.get(caller, []), f"Missing edge: {caller} → {callee}"
       print("✓ Service Map edges verified")

   def test_log_trace_forward_pivot(trace_id: str):
       """Assert querying logs by trace_id returns ≥1 result."""
       r = requests.post(
           f"https://api.{DD_SITE}/api/v2/logs/events/search",
           headers=HEADERS,
           json={"filter": {"query": f"trace_id:{trace_id}"}, "page": {"limit": 1}},
       )
       r.raise_for_status()
       count = len(r.json().get("data", []))
       assert count >= 1, f"No logs found for trace_id {trace_id}"
       print(f"✓ Forward pivot: {count} log record(s) found for trace {trace_id}")

   def test_log_trace_reverse_pivot(trace_id: str):
       """Assert querying APM for a trace returns associated logs."""
       r = requests.get(
           f"https://api.{DD_SITE}/api/v1/trace/{trace_id}",
           headers=HEADERS,
       )
       r.raise_for_status()
       # The trace exists — confirm guard-proxy spans are present
       spans = r.json().get("spans", [])
       assert any(s.get("service") == "guard-proxy" for s in spans), \
           f"No guard-proxy span found in trace {trace_id}"
       print(f"✓ Reverse pivot: guard-proxy span confirmed in trace {trace_id}")

   if __name__ == "__main__":
       test_service_map_edges()
       # Provide a trace_id from a recent live run as a CLI argument
       if len(sys.argv) > 1:
           tid = sys.argv[1]
           test_log_trace_forward_pivot(tid)
           test_log_trace_reverse_pivot(tid)
       print("All checks passed.")
   ```

   Adapt the API endpoint paths and response shapes to match the actual Datadog API behavior observed on the live cluster — do not assume the shape above is exact. Verify API v1 vs v2 endpoint availability with `DD_API_KEY`/`DD_APP_KEY` in hand.

2. For the Bedrock edge: run the script against the live cluster and check whether `kagent → Bedrock` appears in `GET /api/v1/service_dependencies`. If it does, add `("kagent", "Bedrock")` to `EXPECTED_EDGES`. If Bedrock appears as an external-only node (i.e., present in the response but as an inferred dependency, not a named service), 3 internal edges (`guard-proxy→agentgateway→kagent`) is acceptable — document which edges the live cluster emits in this PRD's Decision Log.

3. Run the script end-to-end against a live cluster. Address any assertion failures using the iterate loop from the Milestone Working Pattern.

**Done when:**
- [x] `verify/test_datadog_service_map.py` exists with ABOUTME header (stdlib urllib; wiring confirmed via a dummy-key 401)
- [ ] Script passes against the live cluster for all expected Service Map edges. LIVE
- [ ] Script passes for both log-trace pivot directions with a real `trace_id` from a live run. LIVE
- [x] Bedrock edge decision documented (3 internal edges acceptable if Bedrock is external-only), see Decision Log

---

## Acceptance Criteria

- [ ] `verify/test_datadog_service_map.py` passes: all expected Service Map edges confirmed via `GET /api/v1/service_dependencies` (at minimum: `guard-proxy→agentgateway`, `agentgateway→kagent`; `kagent→Bedrock` if the live cluster emits it as a named service)
- [ ] Forward log-trace pivot passes: logs API returns ≥1 result for a known `trace_id` from a guard-proxy request
- [ ] Reverse log-trace pivot passes: APM API returns a trace containing a guard-proxy span for the same `trace_id`
- [ ] `weaver registry check` passes locally (zero errors)
- [ ] `weaver live-check` run as terminal acceptance step on a live cluster; result documented in Decision Log below

---

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-25 | agentgateway UST stale values: fix `service.version` and `deployment.environment.name` | Values were placeholder text (`CLUSTER_TIER`, `watch-it-burn`) set before M1 locked the UST vocabulary. `v1.3.0` is the agentgateway GA release version; `production` is the locked SDLC environment value for all stack components (M1 Decision Log, 2026-06-23). Inherited from PRD #7 M6 Decision Log entry 603. |
| 2026-06-25 | guard-proxy CLIENT span uses `peer.service="agentgateway"` set in code at span creation | The attribute travels with the span through any pipeline — no maintenance debt from Collector-side host-matching rules. One line of cost since the CLIENT span is written anyway. Inherited from PRD #7 M6 Decision 3 (2026-06-25). |
| 2026-06-25 | JSON logging uses OTel-standard field names `trace_id`/`span_id` — no Datadog remapping config needed | Datadog natively recognizes both `dd.trace_id`/`dd.span_id` (dd-trace SDK) and `trace_id`/`span_id` (OTel-standard) in the log pipeline. Using OTel-standard names avoids the 64-bit decimal conversion required by the dd-trace SDK path. Inherited from PRD #7 M6 Decision 4 (2026-06-25) and `~/.claude/rules/datadog-log-trace-gotchas.md`. |
| 2026-06-25 | Service Map acceptance is binary via Datadog API — no browser/Playwright automation | Datadog's Service Map renders as canvas/SVG; browser selectors are brittle and require managing session cookies. `GET /api/v1/service_dependencies` returns the topology graph programmatically, making assertions machine-verifiable. Inherited from PRD #7 M6 Decision Log 2026-06-25. |
| 2026-06-25 | Weaver `registry check` in CI; `live-check` as manual terminal acceptance step only | `registry check` validates schema statically — no live stack needed; runs in CI. `live-check` requires a running span stream from a live cluster and is the human-in-the-loop final gate. Inherited from PRD #7 M2 Decision 6 (2026-06-24). |
| 2026-06-25 (impl) | **Deviation:** guard-proxy CLIENT `peer.service` is **derived from `AGENT_URL`'s host** in code, not hardcoded to the literal `"agentgateway"`. | The locked decision's intent is that `peer.service` names the real downstream hop, which is `agentgateway` in the target topology. agentgateway is currently staged-not-deployed (deferred PRD #20 M4), so guard-proxy forwards straight to the kagent agent. A hardcoded `"agentgateway"` would emit a CLIENT span claiming a peer that receives no call, drawing a Service Map edge to a node with no server spans and losing the real edge. Deriving from `AGENT_URL` reduces to exactly `"agentgateway"` once `AGENT_URL` fronts agentgateway (identical to the locked value in the deployed state) and stays correct in the interim. `PEER_SERVICE` env var overrides if the host label is ever wrong. Surfaced to Michael for awareness. |
| 2026-06-25 (impl) | kagent→Bedrock `peer.service` is **not** forced by the M3 OTTL transform; left to Datadog AWS auto-inference. | kagent reaches Bedrock via the AWS SDK; Datadog auto-infers that external dependency from the `aws-api` spans. Stamping `peer.service="bedrock"` would risk a duplicate node next to Datadog's inferred one. The PRD already permits 3 internal edges when Bedrock is external-only (M5). The transform carries the Bedrock statement commented with a verify-at-build note to enable only if live inspection shows Bedrock is NOT auto-inferred. |
| 2026-06-25 (impl) | OTTL `transform/set_peer_service` uses `error_mode: ignore`. | A runtime statement error then becomes a harmless no-op (`peer.service` simply stays unset) instead of dropping spans from the traces pipeline, the failure mode the PRD warns about. |
