# PRD #13: MVP Walking Skeleton — OTel Collector + Datadog Connected

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/13
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 1 child PRD
**Priority**: High
**Status**: Complete. M1-M4 live-verified on watch-it-burn-attendee-001 (PROGRESS.md 2026-06-25): datadog-secret created, datadog/connector wired, UST applied, Collector exporting metrics and traces to Datadog.

> **Note on `challenges/` references:** The `challenges/` directory naming follows the challenge vocabulary (C1 to C8; the June 2026 rounds are retired). When implementing, update any `challenges/` path references to the current challenge structure as you encounter them — no separate migration task is required.

---

## Problem

The workshop has no telemetry pipeline to Datadog. Without it, no beat can demonstrate traces, metrics, or alerts in the Datadog UI — the entire workshop observability story is blocked.

The current state of the repo:

- The OTel Collector (`gitops/apps/otel-collector.yaml`) is missing `datadog/connector`, which has been required since otelcol-contrib v0.95.0 for APM Trace Metrics.
- `gitops/ai-layer/resources.yaml` has incorrect UST values: `deployment.environment.name=watch-it-burn` (wrong — `watch-it-burn` is a project name, not an SDLC environment) and `service.version=CLUSTER_TIER` (wrong placeholder).
- No Datadog credentials (`datadog-secret`) exist on the cluster.
- The four AI-layer components (kagent, agentgateway, guard-proxy, evil-mcp-shim) have incomplete or incorrect OTel resource attributes.

---

## Solution

1. Create `datadog-secret` K8s secret with trial Datadog org credentials (US1, `datadoghq.com`).
2. Add `datadog/connector` to the OTel Collector config and wire it in the traces and metrics pipelines.
3. Apply the locked UST vocabulary to all four AI-layer components via `OTEL_RESOURCE_ATTRIBUTES`.
4. Confirm any metric or trace reaches Datadog after running a beat.

---

## Locked Decisions (do not re-open)

All decisions below were finalized in the Milestone 1 design conversation (2026-06-23) and are recorded in the meta-PRD #7 Decision Log. Read those entries before implementing.

The UST values (`deployment.environment.name`, `service.name`, `service.version`) have moved since 2026-06-23. Each of those rows gives the value the manifests carry now, then the earlier value and when it changed. `verify/test_observability.py` holds the manifests to these values, and `verify/test_prd13_ust.py` holds this table and the Milestone 3 and 4 criteria to the manifests (#590).

| Decision | Value |
|---|---|
| Datadog site | `datadoghq.com` (US1) |
| `deployment.environment.name` | `burritobot-kubecon-na-26` (all components; was `production` until 2026-10-27, when telemetry moved to Whitney's shared Datadog sandbox org and this tag became what keeps BurritoBot's data separate there, #629) |
| OTel attribute name | `deployment.environment.name` — NOT the deprecated `deployment.environment` |
| `service.name` for kagent | `burritobot-agent` (was `kagent` until the 2026-09-06 rename to one BurritoBot service family, #265) |
| `service.name` for agentgateway | `burritobot-gateway` (was `agentgateway` until the 2026-09-06 rename, #265) |
| `service.name` for guard-proxy | `burritobot` (the root span's service, which Datadog names the Agent Observability application after; was `guard-proxy` until the 2026-09-06 rename, #265) |
| `service.name` for evil-mcp-shim | `burritobot-evil-mcp` (was `evil-mcp-shim` until the 2026-09-06 rename, #265) |
| `service.version` for kagent | `v0.10.1` (the kagent chart `gitops/bootstrap/apps/kagent.yaml` pins; was `v0.9.9` until the 2026-09-10 chart bump, #586) |
| `service.version` for agentgateway | `v1.7.0` (the image tag `gitops/ai-layer/agentgateway.yaml` runs; image and span version moved from v1.5.0 together on 2026-10-30, #698; v1.5.0 came on 2026-09-10 and its span version on 2026-10-24, #495; `v1.3.0` before that) |
| `service.version` for guard-proxy | `1.0.0` |
| `service.version` for evil-mcp-shim | `1.0.0` |
| UST path | `OTEL_RESOURCE_ATTRIBUTES` — NOT `DD_SERVICE`/`DD_ENV`/`DD_VERSION` (those are ignored on the OTel path) |
| `datadog/connector` | Required — compute_stats_by_span_kind: true; add as exporter in traces pipeline + receiver in metrics pipeline |
| `datadog.prometheusScrape.enabled` | Must remain absent/false — turning it on creates double metrics and billing spikes |
| `datadog-secret` | Does NOT pre-exist; must be created. Mechanism (kubectl vs ESO) decided at implementation time when Whitney provides the access command. **NEVER print credentials to the terminal.** |
| MVP telemetry acceptance | Any metric or trace visible in Datadog after running a beat |

---

## Milestones

### Milestone 1 — Create `datadog-secret` K8s secret

**Before starting**: Ask Whitney for the command to access the trial Datadog org credentials. Do NOT proceed until she provides it. Do NOT print the API key, app key, or any credential value to the terminal.

**Steps**:
1. Determine the target cluster context and namespace. Use an explicit `--context` on every `kubectl` command (see `CLAUDE.md` Kube-context safety rules — no exceptions).
2. Read `gitops/apps/otel-collector.yaml` and find every `secretKeyRef` that references `datadog-secret`. The field names listed there (e.g., `key: api-key`, `key: app-key`) are the exact field names the secret must contain. Write them down — the `kubectl create secret` command in step 4 must use these exact keys.
3. Ask Whitney for the credential access command if not already provided this session.
4. Create the secret using the field names discovered in step 2:
   ```bash
   kubectl create secret generic datadog-secret \
     --from-literal=<key1>=<value1> \
     --from-literal=<key2>=<value2> \
     -n <namespace> --context <context>
   ```
   Replace `<key1>`, `<key2>` with the exact names from step 2. Populate values from the credentials Whitney provides. Never store or print the values in any file or terminal output.
5. Verify the secret exists: `kubectl get secret datadog-secret -n <namespace> --context <context>` (show metadata only — do not show the decoded values). `bash verify/datadog-secret-fields.sh <context>` does this for all three namespaces that read the secret (`datadog`, `monitoring`, `security`), checks every key a `gitops/` reference names, and prints key names only (#594).

**Done when:**
- [ ] `datadog-secret` K8s secret exists in the target namespace
- [ ] Verification command confirms the secret fields are present (not the values)

---

### Milestone 2 — Add `datadog/connector` to OTel Collector config

**File to edit**: `gitops/apps/otel-collector.yaml`

**Context**: The `spanmetrics` connector already exists with `add_resource_attributes: true`. Do NOT remove or modify it. Add `datadog/connector` alongside it.

**Steps**:
1. Read `gitops/apps/otel-collector.yaml` to understand the current pipeline structure.
2. Add `datadog/connector` to the `connectors:` block (keep the existing `spanmetrics` entry unchanged):
   ```yaml
   connectors:
     spanmetrics:
       add_resource_attributes: true   # existing — do NOT remove or modify
     datadog/connector:
       traces:
         compute_stats_by_span_kind: true
   ```
3. Add `datadog/connector` as an exporter in the traces pipeline. The pipelines block should look like this after the change:
   ```yaml
   service:
     pipelines:
       traces:
         receivers: [otlp]                        # keep existing
         exporters: [datadog, spanmetrics, datadog/connector]  # add datadog/connector
       metrics:
         receivers: [spanmetrics, datadog/connector]           # add datadog/connector
         exporters: [datadog]                     # keep existing
   ```
   Read the existing `service.pipelines` section in `gitops/apps/otel-collector.yaml` and add `datadog/connector` in the two places shown above. Do NOT remove any existing receiver, processor, or exporter entries.
4. Verify `datadog.prometheusScrape.enabled` is absent or explicitly false in the Datadog Exporter config. Do NOT set it to true.
5. Commit and let ArgoCD reconcile. Confirm the Collector pod restarts cleanly.

**Reference config** (working example from this machine): `~/Documents/Repositories/spinybacked-orbweaver-eval/evaluation/is/otelcol-config.yaml` — the `datadog/connector` wiring there is confirmed working.

**Done when:**
- [ ] `datadog/connector` present in `gitops/apps/otel-collector.yaml` under `connectors:`
- [ ] `datadog/connector` wired as exporter in the traces pipeline
- [ ] `datadog/connector` wired as receiver in the metrics pipeline
- [ ] OTel Collector pod running cleanly after the update (no CrashLoopBackOff)
- [ ] `datadog.prometheusScrape.enabled` is absent or false

---

### Milestone 3 — Apply locked UST vocabulary to all four AI-layer components

**Goal**: Every AI-layer pod emits `service.name`, `service.version`, and `deployment.environment.name=burritobot-kubecon-na-26` via `OTEL_RESOURCE_ATTRIBUTES`. The values are locked in the Decisions table above — do not modify them.

**Steps**:
1. Read `gitops/ai-layer/resources.yaml` to see the current `OTEL_RESOURCE_ATTRIBUTES` setting. Replace any incorrect values:
   - Change `deployment.environment.name=watch-it-burn` → the locked `deployment.environment.name` in the Decisions table
   - Change `service.version=CLUSTER_TIER` → the correct per-component value
   - Confirm `service.name` is set to the locked value for each component
2. Check `gitops/ai-layer/agentgateway.yaml` for `OTEL_RESOURCE_ATTRIBUTES`. Add or correct to the locked values for `agentgateway`.
3. Check the guard-proxy deployment manifest (in `agent/gateway/guard-proxy/` or referenced from `gitops/ai-layer/`). Add or correct `OTEL_RESOURCE_ATTRIBUTES` for `guard-proxy`.
4. Check the evil-mcp-shim container spec in `gitops/ai-layer/resources.yaml`. Add or correct `OTEL_RESOURCE_ATTRIBUTES` for `evil-mcp-shim`. (The deployed pod is defined there, not in `challenges/` — see issue #18 Decision Log.)
5. If a single `OTEL_RESOURCE_ATTRIBUTES` in `resources.yaml` applies to ALL four components (and thus cannot have per-component `service.name`/`service.version`), each component needs its own env var override in its own deployment manifest. Check whether the current structure supports per-component values — if not, split them out.
6. Commit and let ArgoCD reconcile. Confirm all four pods restart cleanly.

**Done when:**
- [ ] kagent pod has `service.name=burritobot-agent`, `service.version=v0.10.1`, `deployment.environment.name=burritobot-kubecon-na-26`
- [ ] agentgateway pod has `service.name=burritobot-gateway`, `service.version=v1.7.0`, `deployment.environment.name=burritobot-kubecon-na-26`
- [ ] guard-proxy pod has `service.name=burritobot`, `service.version=1.0.0`, `deployment.environment.name=burritobot-kubecon-na-26`
- [ ] evil-mcp-shim pod has `service.name=burritobot-evil-mcp`, `service.version=1.0.0`, `deployment.environment.name=burritobot-kubecon-na-26`
- [ ] No component uses `deployment.environment` (deprecated) — all use `deployment.environment.name`
- [ ] No component has `CLUSTER_TIER` or `watch-it-burn` in its `OTEL_RESOURCE_ATTRIBUTES`

---

### Milestone 4 — End-to-end verification: telemetry reaches Datadog

**Steps**:
1. Run a beat (any beat — the simplest one available).
2. Open the Datadog UI for the trial org (`datadoghq.com`).
3. Confirm at least one of the following is visible:
   - A trace from any of the four AI-layer components in APM
   - A metric from any of the four AI-layer components in Metrics Explorer
4. If nothing appears after 5 minutes, check the OTel Collector logs: `kubectl logs -n <namespace> -l app=otel-collector --context <context>` — look for export errors or authentication failures.
5. Report the specific signal seen (service name, metric name, or trace ID) to confirm end-to-end.

**Done when:**
- [ ] At least one metric or trace from an AI-layer component is visible in the Datadog UI
- [ ] The service name visible in Datadog matches one of the locked values (`burritobot`, `burritobot-gateway`, `burritobot-agent`, or `burritobot-evil-mcp`). When M4 was verified on 2026-06-25 the names were guard-proxy, agentgateway, kagent and evil-mcp-shim; #265 renamed them on 2026-09-06.

---

## Acceptance Criteria

- [ ] `datadog-secret` K8s secret exists in the target namespace (never committed to the repo)
- [ ] OTel Collector running with `datadog/connector` wired in traces and metrics pipelines
- [ ] All four AI-layer components emitting UST-tagged telemetry (`service.name`, `service.version=<locked>`, `deployment.environment.name=burritobot-kubecon-na-26`)
- [ ] At least one metric or trace from the AI-layer appears in Datadog after running a beat
- [ ] `PROGRESS.md` updated

---

## Risks

| Risk | Mitigation |
|---|---|
| Trial Datadog org on wrong site | `datadoghq.com` confirmed (US1, San Francisco workshop). `DD_SITE` already hardcoded correctly in Collector config. |
| OTel Collector config invalid after adding `datadog/connector` | Reference working config at `spinybacked-orbweaver-eval/evaluation/is/otelcol-config.yaml`. Check Collector pod logs after reconcile. |
| Per-component `OTEL_RESOURCE_ATTRIBUTES` not possible from a single manifest | See Milestone 3 step 5 — split into per-component env overrides if the current structure is monolithic. |
| Credentials leak | Whitney provides credential access command at implementation time. Never print values. Use `kubectl create secret` directly. |
| `datadog.prometheusScrape.enabled` accidentally set true | Results in double metrics and billing spikes. Verify it is absent/false in the Exporter config before committing. |

---

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-23 | All decisions deferred to meta-PRD #7 Decision Log | This child PRD records outcomes only. Full rationale for each decision (UST vocabulary, datadog/connector requirement, DD_SITE, credential handling) is in the meta-PRD #7 Decision Log entries dated 2026-06-23. Read those before implementing. |
| 2026-10-28 | The UST rows carry the current values, each with the value it replaced and when (#590) | The manifests moved under the locked values: the service names to the burritobot-* family (#265), agentgateway's span version to v1.5.0 (#495) and the env to burritobot-kubecon-na-26 (#629). #586 had already updated the kagent version row in place, and a test holds it, so the other rows follow the same pattern instead of being left as a record. `verify/test_prd13_ust.py` fails when the table or the milestone criteria drift from the manifests. |
