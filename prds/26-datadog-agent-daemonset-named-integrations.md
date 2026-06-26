# PRD #26: Datadog Agent DaemonSet + Named Integrations ("Datadog Sees Everything")

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/26
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 5 child PRD
**Priority**: High
**Status**: Complete. M1-M4 deployed and live-verified on watch-it-burn-attendee-001 (PROGRESS.md 2026-06-25): all five named-integration checks `[OK]`, EKS/k8s metrics and Falco logs confirmed via the Datadog API. ArgoCD named integration is a documented gap (bootstrap-installed; the Kyverno policy blocks the live patch).

---

## Problem

The Datadog Agent DaemonSet does not yet run on workshop clusters. Without it:

- No EKS node/pod/container metrics in the Datadog infrastructure UI
- No container log collection (Log Explorer empty for non-AI components)
- No Agent Autodiscovery named integrations — ArgoCD, Falco, Istio ambient, and cert-manager produce no data in Datadog despite emitting metrics
- No OOTB Falco dashboard (alert log metrics), no OOTB ArgoCD dashboard
- The Falco Agent named integration path (individual alert logs → Log Explorer + aggregate metrics → OOTB Falco dashboard) is missing — Falcosidekick handles the Event Stream path (M4/PRD #23), but the Agent path is M5 scope
- Kyverno emits no traces or metrics to Datadog — its OTLP output is not yet enabled

The workshop's "Datadog sees everything" demo moment requires EKS infrastructure metrics, component logs, named integration dashboards (Falco, ArgoCD), and Kyverno policy-decision traces all arriving simultaneously.

---

## Solution

1. Deploy the **Datadog Operator** via ArgoCD (`gitops/apps/datadog-operator.yaml`, sync-wave `"3"`) rendering the `datadog/datadog-operator` Helm chart.
2. Deploy the **DatadogAgent CR** via ArgoCD (`gitops/apps/datadog-agent-cr.yaml`, sync-wave `"4"`) pointing to `gitops/manifests/datadog/`. The CR lives at `gitops/manifests/datadog/datadog-agent.yaml`.
3. Add `datadog` namespace to `gitops/apps/namespaces.yaml`.
4. Wire **named integrations** via pod annotations for Agent Autodiscovery: ArgoCD (`argocd` check), Falco (`falco` check), Istio ambient (`istio` check with `istio_mode: ambient` and `ztunnel_endpoint`), cert-manager (`cert_manager` check with `rename_labels` mapping `name` → `cert_name`).
5. Enable **Kyverno native OTLP** by setting `otelConfig: grpc` and `otelCollector: <in-cluster-collector-endpoint>` in `gitops/apps/kyverno.yaml` `helm.valuesObject`.
6. Create **`datadog-secret`** (one Secret with `api-key` and `app-key` keys) via ESO ExternalSecret in the `datadog` namespace.
7. Verify each wired integration produces the expected data in the Datadog UI per the acceptance checklist below.

---

## Locked Decisions (do not re-open)

These were finalized in the M5 design conversation (2026-06-24). Read the meta-PRD #7 Decision Log for full reasoning on each. Config uses **DatadogAgent CR `spec.features.*` keys** — NOT Helm `datadog.*` keys.

| Decision | Value |
|---|---|
| Install method | Datadog Operator (overrides research/32 Helm recommendation) |
| ArgoCD Application — Operator | `gitops/apps/datadog-operator.yaml`, sync-wave `"3"`, renders `datadog/datadog-operator` Helm chart |
| ArgoCD Application — CR | `gitops/apps/datadog-agent-cr.yaml`, sync-wave `"4"`, points to `gitops/manifests/datadog/` |
| DatadogAgent CR path | `gitops/manifests/datadog/datadog-agent.yaml` |
| Namespace | `datadog`; add to `gitops/apps/namespaces.yaml` |
| Log collection | `spec.features.logCollection.enabled: true`, `spec.features.logCollection.containerCollectAll: true` |
| APM feature | `spec.features.apm.enabled: false` — OTel traces reach APM via Collector path; Agent APM port unused |
| Prometheus scrape (Agent) | `spec.features.prometheusScrape.enabled: true` — several stack components are Prometheus-only |
| IAM | No AWS role on the Agent; if ever needed use EKS Pod Identity |
| Cluster Agent | Enabled, 1 replica, 200m CPU / 256Mi memory |
| `datadog-secret` shape | One Kubernetes Secret, two keys: `api-key` + `app-key`. Create via ESO ExternalSecret in `datadog` namespace. **CRITICAL: never print credentials to the terminal.** |
| `clusterName` | `watch-it-burn` in `spec.global.clusterName` |
| `k8s.node.name` | Auto-carried by Agent on EKS node telemetry — no extra config needed |
| Node Agent resources | 200m CPU / 256Mi memory |
| Process Agent resources | 100m CPU / 200Mi memory |
| Cluster Agent resources | 200m CPU / 256Mi memory |
| System Probe | OFF |
| Wire: ArgoCD | Agent `argocd` check via pod annotations; Prometheus-only; OOTB dashboard included |
| Wire: Kyverno | Native OTLP only (`otelConfig: grpc`); Agent `kyverno` Prometheus check SKIPPED (would duplicate metrics) |
| Wire: Falco | Agent `falco` check → alert logs (JSON per alert → Log Explorer) + aggregate Prometheus metrics → OOTB Falco dashboard; pre-decided M4 D2 |
| Wire: Istio ambient | Agent `istio` check, `istio_mode: ambient`, `ztunnel_endpoint` → L4 TCP metrics; L7/waypoint is optional issue #25 only |
| Wire: cert-manager | Agent `cert_manager` check + `rename_labels` mapping `name` → `cert_name` (research/18 + research/30 gotcha) |
| Collector path (no Agent check) | kagent, agentgateway, guard-proxy — already handled by OTel pipeline |
| Skip | KubeArmor (not deployed), ESO (generic OpenMetrics only), Backstage (no SDK), evil-mcp-shim (intentionally dark), customer-stream generator (emits nothing) |
| EKS + CloudWatch | Skip — no workshop narrative |
| L7/waypoint | Optional issue #25 — NOT M5 scope |

---

## Step 0: What to Read Before Starting Any Milestone

This PRD is executed by a fresh AI instance with no memory of the design conversation. Read all of the following before implementing:

1. **Meta-PRD #7 M5 Decision Log entries (D1–D9, 2026-06-24)** (`prds/7-observability-meta.md`) — full reasoning behind every locked decision above.
2. **`gitops/apps/`** — read all existing YAML files to understand naming conventions, sync-wave patterns, and Helm chart shapes before creating any new Application files. Existing patterns: `otel-collector.yaml`, `falcosidekick.yaml`, `kyverno.yaml`.
3. **`gitops/apps/namespaces.yaml`** — understand the existing namespace list before adding `datadog`.
4. **`research/24-datadog-agent-install-eks-2026.md`** — Agent sizing (§2) and EKS-specific install considerations.
5. **`research/30-per-component-telemetry-synthesis-2026.md`** — per-component telemetry questions for all 13 stack components; informs Autodiscovery annotation content.
6. **`research/18-datadog-integrations-stack-2026.md`** — named integration rows for ArgoCD, Falco, Istio ambient, cert-manager; verify current gotchas (especially `rename_labels` for cert-manager).
7. **`prds/23-falco-runtime-alerts-datadog.md`** — M4 Falco work already done; this PRD adds the Agent path only.
8. **`docs/BUILD-SPEC.md`** — the demo beats that depend on M5 data flowing.

**Do NOT** start implementing until you have read items 1–3.

---

## Milestones

### Milestone 1 — Foundation: Operator + namespace + datadog-secret

**Step 0:** Read `gitops/apps/` in full. Note the sync-wave numbering scheme (`argocd.argoproj.io/sync-wave` annotations). Note how existing Application files reference Helm charts vs. raw manifests. Read `gitops/apps/namespaces.yaml` in full.

**Steps:**

1. Add `datadog` to the namespace list in `gitops/apps/namespaces.yaml` (match the existing entry format exactly — same indentation, same field names).

2. Create `gitops/apps/datadog-operator.yaml` as an ArgoCD Application rendering the `datadog/datadog-operator` Helm chart. Set `argocd.argoproj.io/sync-wave: "3"`. Match the structure of a sibling Application file (e.g., `gitops/apps/kyverno.yaml`). Minimum Helm values: **pin the exact chart version at implementation time** (do not use `latest` or omit the version field — check `helm search repo datadog/datadog-operator` for the current stable version and hardcode it); `replicaCount: 1`; resource requests appropriate for the operator (not the Agent — the Agent's resources are in the CR).

   **Before writing this file:** Read all existing Application YAMLs in `gitops/apps/` and check their `repoURL` values. Confirm whether `https://helm.datadoghq.com` is already registered as an ArgoCD Helm repository. If no existing Application uses that URL, the Datadog Helm repo must be added to the ArgoCD repo config before this Application will sync. Do not assume the chart registry is available.

3. Create `gitops/manifests/datadog/` directory. Create `gitops/apps/datadog-agent-cr.yaml` as an ArgoCD Application pointing to `gitops/manifests/datadog/` (raw manifest path, not Helm). Set `argocd.argoproj.io/sync-wave: "4"` (must be higher than the Operator's wave so the Operator CRDs exist before the CR is applied).

4. Create `gitops/manifests/datadog/datadog-agent.yaml` as the `DatadogAgent` CR. Use `spec.features.*` keys throughout — **NOT** Helm `datadog.*` keys. Required fields:

   ```yaml
   apiVersion: datadoghq.com/v2alpha1
   kind: DatadogAgent
   metadata:
     name: datadog
     namespace: datadog
   spec:
     global:
       clusterName: watch-it-burn
       credentials:
         apiSecret:
           secretName: datadog-secret
           keyName: api-key
         appKeySecret:
           secretName: datadog-secret
           keyName: app-key
     features:
       logCollection:
         enabled: true
         containerCollectAll: true
       apm:
         enabled: false
       prometheusScrape:
         enabled: true
     override:
       nodeAgent:
         resources:
           requests:
             cpu: 200m
             memory: 256Mi
       processAgent:
         resources:
           requests:
             cpu: 100m
             memory: 200Mi
       clusterAgent:
         replicas: 1
         resources:
           requests:
             cpu: 200m
             memory: 256Mi
   ```

   **Secret dependency:** The DatadogAgent CR references `datadog-secret`, which is created by the ExternalSecret in Step 5. Both resources land in the same ArgoCD Application (sync-wave "4"), so ArgoCD applies them simultaneously. ESO processes the ExternalSecret asynchronously — the secret may not exist at the moment the Datadog Operator runs its first reconcile. This is expected: the Operator will requeue and succeed once ESO populates the secret. Do not treat the first reconcile failure as a bug. ESO itself runs at an earlier sync-wave, so ESO will be ready before the ExternalSecret is applied.

   **Verify field paths before committing** — do not use training data for CRD field names. Run against a cluster with the Operator installed:
   ```bash
   kubectl explain datadogagent.spec.features --api-version=datadoghq.com/v2alpha1 --context "$CONTEXT"
   kubectl explain datadogagent.spec.global --api-version=datadoghq.com/v2alpha1 --context "$CONTEXT"
   kubectl explain datadogagent.spec.override --api-version=datadoghq.com/v2alpha1 --context "$CONTEXT"
   ```
   If the Operator is not yet installed, read the CRD schema directly after Milestone 1 Step 2 is applied: `kubectl get crd datadogagents.datadoghq.com --context "$CONTEXT" -o yaml`. Do NOT commit field paths that cannot be verified against the actual schema.

5. Create the ESO ExternalSecret for `datadog-secret` in the `datadog` namespace. The secret must have two keys: `api-key` and `app-key`. **Before writing the ExternalSecret:** read all existing ExternalSecret manifests in `gitops/` and check the `secretStoreRef.kind` field — is it `SecretStore` (namespace-scoped) or `ClusterSecretStore` (cluster-wide)? If namespace-scoped, the existing `SecretStore` in `monitoring` or `security` namespaces does NOT apply to `datadog`; a new `SecretStore` must be created in the `datadog` namespace first. If `ClusterSecretStore`, no additional SecretStore is needed. Match the existing ExternalSecret structure exactly. **CRITICAL: never print credential values to the terminal** — pass via env vars only. Do not hardcode or echo any key values.

**Done when:**
- [ ] `gitops/apps/namespaces.yaml` includes `datadog`
- [ ] `gitops/apps/datadog-operator.yaml` exists with sync-wave `"3"`
- [ ] `gitops/apps/datadog-agent-cr.yaml` exists with sync-wave `"4"`, pointing to `gitops/manifests/datadog/`
- [ ] `gitops/manifests/datadog/datadog-agent.yaml` exists with all required `spec.features.*` fields, resource requests, and `clusterName: watch-it-burn`
- [ ] ESO ExternalSecret for `datadog-secret` exists in `datadog` namespace with `api-key` and `app-key` keys
- [ ] YAML is valid (no syntax errors); no credential values appear anywhere in any committed file

---

### Milestone 2 — Named integration annotations: ArgoCD, Falco, cert-manager, Istio ambient

**Step 0:** Read `research/30-per-component-telemetry-synthesis-2026.md` (all rows for ArgoCD, Falco, Istio ambient, cert-manager). Read `research/18-datadog-integrations-stack-2026.md` (named integration rows). Then read each target component's existing manifest in `gitops/apps/` before adding annotations.

**Context:** Agent Autodiscovery wires named integrations via pod annotations on the component's Deployment or DaemonSet. The annotations go on the pod template (`spec.template.metadata.annotations`), not on the top-level resource. The annotation key format is `ad.datadoghq.com/<container-name>.checks`.

**Steps:**

1. **ArgoCD (`argocd` check):** Add Autodiscovery annotations to the ArgoCD server Deployment (or the appropriate ArgoCD component that exposes Prometheus metrics). The `argocd` check scrapes ArgoCD's Prometheus `/metrics` endpoint. Annotation format (adapt port and container name to the actual ArgoCD deployment):

   ```yaml
   ad.datadoghq.com/argocd-server.checks: |
     {
       "argocd": {
         "instances": [
           {
             "url": "http://%%host%%:8083/metrics"
           }
         ]
       }
     }
   ```

   Verify the exact port ArgoCD exposes its Prometheus metrics on by reading the ArgoCD manifests before hardcoding.

2. **Falco (`falco` check):** Add Autodiscovery annotations to the Falco DaemonSet pod template. The `falco` check reads Falco's metrics endpoint (port 8765 by default — verify from the Falco manifest). Annotation format:

   ```yaml
   ad.datadoghq.com/falco.checks: |
     {
       "falco": {
         "instances": [
           {
             "url": "http://%%host%%:8765/metrics"
           }
         ]
       }
     }
   ```

3. **cert-manager (`cert_manager` check with `rename_labels`):** Add Autodiscovery annotations to the cert-manager controller Deployment. The cert-manager check requires `rename_labels` to map the `name` label → `cert_name` (without this, metrics are unlabeled and the dashboard is unreadable):

   ```yaml
   ad.datadoghq.com/cert-manager-controller.checks: |
     {
       "cert_manager": {
         "instances": [
           {
             "prometheus_url": "http://%%host%%:9402/metrics",
             "rename_labels": {
               "name": "cert_name"
             }
           }
         ]
       }
     }
   ```

   Verify the port and container name from the cert-manager manifests.

4. **Istio ambient (`istio` check, L4 only):** Add Autodiscovery annotations to the ztunnel DaemonSet pod template. Istio ambient mode requires `istio_mode: ambient` and a `ztunnel_endpoint`:

   ```yaml
   ad.datadoghq.com/istio-proxy.checks: |
     {
       "istio": {
         "instances": [
           {
             "istio_mesh_endpoint": "http://%%host%%:15020/stats/prometheus",
             "istio_mode": "ambient",
             "ztunnel_endpoint": "http://%%host%%:15020/stats/prometheus"
           }
         ]
       }
     }
   ```

   Verify the actual ztunnel DaemonSet name and port from the Istio manifests in `gitops/apps/`.

**Done when:**
- [ ] ArgoCD Deployment has `ad.datadoghq.com/argocd-server.checks` annotation on pod template
- [ ] Falco DaemonSet has `ad.datadoghq.com/falco.checks` annotation on pod template
- [ ] cert-manager Deployment has `ad.datadoghq.com/cert-manager-controller.checks` annotation with `rename_labels` on pod template
- [ ] Istio ztunnel DaemonSet has `ad.datadoghq.com/istio-proxy.checks` annotation with `istio_mode: ambient` on pod template
- [ ] All annotations are on the pod template (`spec.template.metadata.annotations`), not the top-level resource
- [ ] YAML is valid for all modified files

---

### Milestone 3 — Kyverno native OTLP

**Step 0:** Read `gitops/apps/kyverno.yaml` in full to understand the existing Helm values structure before modifying it. Read meta-PRD M5 D9 for the full rationale (Kyverno native OTLP, not Agent Prometheus check).

**Context:** Kyverno supports native OTLP output for both metrics and policy-decision traces. Enabling `otelConfig: grpc` sends Prometheus-format metrics AND policy-decision traces to the OTel Collector. The Agent `kyverno` Prometheus check is explicitly skipped (would duplicate metrics and add billing noise). This is a sender-side config change only — the Collector → Datadog routing is already established.

**Steps:**

1. In `gitops/apps/kyverno.yaml`, find the `helm.valuesObject` (or `values`) block. Add the following under the appropriate Kyverno component section (typically `admissionController` or at the top-level `config`):

   ```yaml
   config:
     otelConfig: grpc
     otelCollector: <in-cluster-otel-collector-service>.<namespace>.svc.cluster.local:<port>
   ```

   The collector endpoint value: read `gitops/apps/otel-collector.yaml` to find the exact Service name, namespace, and OTLP gRPC port (typically 4317). Do not guess the endpoint — read the manifest.

2. Verify no `kyverno` Prometheus check annotations are present on Kyverno pods. If any exist (from prior work), remove them — having both enabled would duplicate metrics.

**Done when:**
- [ ] `gitops/apps/kyverno.yaml` `helm.valuesObject` includes `otelConfig: grpc` and `otelCollector: <endpoint>`
- [ ] Collector endpoint resolves to the correct in-cluster Service (verified by reading `gitops/apps/otel-collector.yaml`)
- [ ] No `kyverno` Prometheus check Autodiscovery annotations present on Kyverno pods
- [ ] YAML is valid

---

### Milestone 4 — Verify-at-build: all integrations confirmed in Datadog UI

**Step 0:** This milestone requires a running cluster with the Datadog Operator, DatadogAgent CR, and all named integration annotations deployed (Milestones 1–3 must be complete). These are verify-at-build tasks — they cannot be validated without a live cluster. Michael owns cluster provisioning and the `datadog-secret`.

**Context:** Each integration has a specific Datadog UI location that proves it is working. Verify in this order: foundational (Agent running) → per-integration (each surface populated).

**Steps:**

1. **Confirm Agent DaemonSet is running.** Navigate to Datadog → Infrastructure → Host Map. The workshop cluster's nodes should appear. Each node should show EKS host metrics (CPU, memory, disk).

   ```bash
   kubectl get pods -n datadog -l app.kubernetes.io/name=datadog --context "$CONTEXT"
   ```

   All DaemonSet pods should be `Running`. If not, check `kubectl logs -n datadog <pod-name> --context "$CONTEXT"` for auth errors (usually means `datadog-secret` is missing or malformed — **do not print key values**).

2. **Confirm `datadog-secret` in `datadog` namespace.**

   ```bash
   kubectl get secret datadog-secret -n datadog --context "$CONTEXT"
   ```

   The secret must exist. If missing: create it via ESO ExternalSecret trigger or manually (Michael owns credentials). **Never print credential values.**

3. **ArgoCD integration:** Navigate to Datadog → Metrics Explorer. Query `argocd.app.info`. If the metric appears, the check is wired. Also check Dashboards → ArgoCD Overview (OOTB dashboard from the Datadog integration).

4. **Falco integration:** Navigate to Datadog → Dashboards → Falco Overview (OOTB dashboard). The dashboard should show rule match counts. Navigate to Datadog → Logs → search `source:falco`. Individual Falco alert logs (JSON format, one per rule match) should appear after running a Challenge beat.

   UI verification checklist (per M5 D4, pre-decided):
   - [ ] OOTB Falco dashboard renders with rule match counts after running C3 or C4
   - [ ] After running Challenge C3: `Shell or Exec In Workshop Agent Pod` (WARNING) appears as a log record in Log Explorer
   - [ ] After running Challenge C3: `Sensitive File Access` (NOTICE) appears as a log record in Log Explorer
   - [ ] After running Challenge C4: `Fork Bomb In Workload Container` (CRITICAL) appears as a log record in Log Explorer
   - [ ] After running Challenge C4: `Shell or Exec In Workshop Agent Pod` (WARNING) appears as a log record in Log Explorer

5. **cert-manager integration:** Navigate to Datadog → Metrics Explorer. Query `cert_manager.certificate.expiration_timestamp`. The `cert_name` label should be present (confirms `rename_labels` is working). If the label is absent, the `rename_labels` annotation is misconfigured — re-read the cert-manager annotation from Milestone 2.

6. **Istio ambient integration:** Navigate to Datadog → Metrics Explorer. Query `istio.mesh.request.count` or a ztunnel metric. If metrics appear with `cluster_name:watch-it-burn`, the L4 integration is wired.

7. **Kyverno OTLP:** Navigate to Datadog → APM → Traces. Search for service `kyverno`. Policy-decision traces from Kyverno admission webhooks should appear as spans. Also check Datadog → Metrics Explorer for Kyverno Prometheus metrics arriving via the Collector path.

8. **Record verification results.** Add a comment to GitHub issue #26 with the confirmation: "Verified [date]: all integrations confirmed in Datadog UI on cluster [name]." List each integration and its verification status.

**Done when:**
- [ ] Agent DaemonSet pods all `Running` in `datadog` namespace
- [ ] EKS node/pod/container metrics visible in Datadog Host Map
- [ ] ArgoCD check: `argocd.app.info` metric appears in Metrics Explorer
- [ ] Falco OOTB dashboard renders with rule match counts
- [ ] Falco log records: all 5 items in the UI verification checklist above
- [ ] cert-manager metrics appear with `cert_name` label (confirming `rename_labels`)
- [ ] Istio ambient L4 metrics appear in Metrics Explorer
- [ ] Kyverno policy-decision traces appear in APM Traces
- [ ] Results recorded on GitHub issue #26

---

## Acceptance Criteria

- [ ] `gitops/apps/namespaces.yaml` includes `datadog` namespace
- [ ] `gitops/apps/datadog-operator.yaml` exists (ArgoCD Application, sync-wave `"3"`)
- [ ] `gitops/apps/datadog-agent-cr.yaml` exists (ArgoCD Application, sync-wave `"4"`)
- [ ] `gitops/manifests/datadog/datadog-agent.yaml` exists: `clusterName: watch-it-burn`, `logCollection: true`, `apm: false`, `prometheusScrape: true`, all resource requests set
- [ ] ESO ExternalSecret for `datadog-secret` in `datadog` namespace; no credential values committed or printed
- [ ] Autodiscovery annotations on: ArgoCD (argocd check), Falco (falco check), cert-manager (cert_manager check + rename_labels), Istio ztunnel (istio check + istio_mode: ambient)
- [ ] `gitops/apps/kyverno.yaml` includes `otelConfig: grpc` and `otelCollector` endpoint
- [ ] On a live cluster: Agent DaemonSet running; EKS node metrics visible in Host Map
- [ ] On a live cluster: All 5 Falco log-record verification items confirmed (M4 pre-decided checklist)
- [ ] On a live cluster: ArgoCD, cert-manager (with cert_name label), Istio ambient L4, and Kyverno OTLP metrics/traces all confirmed
- [ ] PROGRESS.md updated

---

## Out of Scope

- **L7/waypoint proxy for Istio mTLS** — optional issue #25 only, not M5 scope. Do NOT modify ztunnel configuration beyond L4 annotations.
- **EKS + CloudWatch cross-account integration** — skipped (no workshop narrative, not per-attendee).
- **KubeArmor, ESO, Backstage, evil-mcp-shim, customer-stream generator** — skipped per M5 D4. Do not add Autodiscovery annotations for these.
- **Kyverno Agent Prometheus check** — explicitly skipped to avoid metric duplication. Do not add `kyverno` check annotations.
- **Custom dashboards** — M7 scope. Do not create any custom dashboard JSON files here.
- **Per-attendee `datadog-secret` provisioning** — M8 scope. M5 establishes the two-key secret shape; M8 handles scale-out.

---

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-24 | Inherited M5 D1 (compound): Operator install; two ArgoCD Applications; DatadogAgent CR `spec.features.*`; log ON, APM OFF, prometheusScrape ON; no IAM; Cluster Agent 1 replica; `datadog-secret` two-key shape via ESO; CRITICAL: never print credentials | See meta-PRD #7 Decision Log, M5 D1 (2026-06-24) |
| 2026-06-24 | Inherited M5 D5: `clusterName: watch-it-burn`; `k8s.node.name` auto-carried | See meta-PRD #7 Decision Log, M5 D5 (2026-06-24) |
| 2026-06-24 | Inherited M5 D4 (compound): Wire ArgoCD, Kyverno-OTLP-only, Falco, Istio-L4, cert-manager+rename_labels; Collector path for kagent/agentgateway/guard-proxy; Skip KubeArmor/ESO/Backstage/evil-mcp-shim/customer-stream | See meta-PRD #7 Decision Log, M5 D4 (2026-06-24) |
| 2026-06-24 | Inherited M5 D6: Istio ambient L4-only in M5; L7 mTLS = optional issue #25 | See meta-PRD #7 Decision Log, M5 D6 (2026-06-24) |
| 2026-06-24 | Inherited M5 D7: EKS + CloudWatch — skip | See meta-PRD #7 Decision Log, M5 D7 (2026-06-24) |
| 2026-06-24 | Inherited M5 D8: Node Agent 200m/256Mi, Process Agent 100m/200Mi, Cluster Agent 200m/256Mi; APM OFF; System Probe OFF | See meta-PRD #7 Decision Log, M5 D8 (2026-06-24) |
| 2026-06-24 | Inherited M5 D9: Kyverno `otelConfig: grpc`; Agent kyverno Prometheus check — skip | See meta-PRD #7 Decision Log, M5 D9 (2026-06-24) |
| 2026-06-24 | Inherited M4 D2: Wire both Falcosidekick (Event Stream, M4 done) and Agent named integration (Log Explorer + OOTB dashboard, this PRD) — additive, different Datadog surfaces | See meta-PRD #7 Decision Log, M4 D2 (2026-06-24). M4 wired Event Stream; this PRD adds the Agent log path only. |
