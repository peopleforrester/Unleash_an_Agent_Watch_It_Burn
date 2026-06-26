# PRD #28: Platform Component Unified Service Tagging

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/28
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 6 platform component UST child PRD (backlog)
**Priority**: Medium
**Status**: Implemented (2026-06-27). UST pod annotations added to all five platform components, gated by a deterministic static check in `verify/test_observability.py` (green). On `main` and cherry-picked to all four whitney branches. The live "appears in the Datadog service catalog with `env:production`" confirmation is a manual facilitator Software Catalog UI step (see Decision Log 2026-06-27) — there is no automatable public API for it.

---

## Problem

The Datadog Service Map currently shows only the AI layer components (`guard-proxy`, `agentgateway`, `kagent`, `evil-mcp-shim`) once PRD #27 is implemented. The third-party platform components — ArgoCD, Kyverno, Falco, cert-manager, Istio ambient — are absent from the Service Map because they lack `tags.datadoghq.com/*` pod annotations. Without these annotations, the Datadog Agent cannot correlate their metrics and logs under a named service, and the Service Map cannot draw topology edges to or from them.

Scope: platform components only. AI-layer components (`guard-proxy`, `agentgateway`, `kagent`, `evil-mcp-shim`) already have correct UST values from PRD #27 and earlier milestones — do NOT change them here.

---

## Solution

Add `tags.datadoghq.com/service`, `tags.datadoghq.com/version`, and `tags.datadoghq.com/env` pod annotations to each platform component's Helm values in `gitops/apps/`. One milestone per component, each following the same iterate loop: implement annotations → deploy → assert component appears in the Datadog service catalog (`GET /api/v1/services`) with `env:production` → iterate until passing.

---

## Locked Decisions (do not re-open)

| Decision | Value |
|---|---|
| Tag names | `tags.datadoghq.com/service`, `tags.datadoghq.com/version`, `tags.datadoghq.com/env` |
| `env` value for all components | `production` (locked in M1 Decision Log, 2026-06-23) |
| `service` value per component | Component's natural lowercase name (e.g., `argocd`, `kyverno`, `falco`, `cert-manager`, `istio`) |
| `version` value per component | Component's actual deployed software version from `VERSIONS.lock` or Helm chart values |
| Annotation placement | Pod template (`spec.template.metadata.annotations`) in each Helm values file — NOT top-level resource metadata |
| Component list | ArgoCD, Kyverno, Falco, cert-manager, Istio ambient; add any others identified in `research/30-per-component-telemetry-synthesis-2026.md` |
| AI-layer components | Do NOT modify — already correct from PRD #27 and earlier milestones |
| Acceptance method | `GET /api/v1/service_dependencies` (Datadog API) — no browser automation |
| Verification script | Extend `verify/test_datadog_service_map.py` (from PRD #27) per component |
| Deployment prerequisite | PRD #27 must be merged to main before this PRD begins |

---

## Step 0: What to Read Before Starting Any Milestone

This PRD is executed by a fresh AI instance with no memory of the design conversation. Read all of the following before implementing:

1. **PRD #7 M6 Decision Log entries (2026-06-25)** (`prds/7-observability-meta.md`) — Decision Log entries 591, 598, 599, 603 explain the scope, milestone-per-component pattern, and why this PRD is separate from PRD #27.
2. **PRD #27** (`prds/27-ai-layer-ust-service-map-correlation.md`) — must be merged to main before this PRD starts. Read its Decision Log for the UST locked values that also apply here (`deployment.environment.name=production`, `service.name` naming convention).
3. **`research/30-per-component-telemetry-synthesis-2026.md`** — the per-component telemetry synthesis for all 13 stack components. Read the rows for ArgoCD, Kyverno, Falco, cert-manager, and Istio ambient to understand what telemetry each emits and what Helm values files to modify.
4. **`gitops/apps/`** — read all existing Application YAML files before modifying any. Note how each component's Helm values are specified (`helm.valuesObject` vs. `helm.parameters` vs. a `values.yaml` file reference). Match the existing pattern for each component.
5. **`verify/test_datadog_service_map.py`** (from PRD #27) — the script to extend per component. Read it in full before adding new assertions.

**Do NOT start implementing until you have read items 1 and 4.**

---

## Milestone Working Pattern

Every milestone for every component follows this iterate loop:

1. **Implement** — add `tags.datadoghq.com/*` annotations to the component's pod template in `gitops/apps/`
2. **Deploy** — push, ArgoCD sync (or `kubectl apply`)
3. **Check** — query `GET /api/v1/services` and confirm the component appears with `env:production`
4. **Diagnose** — if missing, inspect whether the Agent is picking up the annotations (`kubectl describe pod <component-pod> --context "$CONTEXT"` — check `tags.datadoghq.com/*` labels are visible); check Agent logs for autodiscovery events
5. **Adjust and re-check** — fix the annotation placement or value and re-deploy

The milestone is not done until the API check passes. Expect multiple deploy-check-adjust cycles per component.

**Annotation path lookup (applies to all milestones):**

Before adding annotations, determine which YAML path the Helm chart uses. The two common patterns are:

```yaml
# Pattern A: global — applies to all component pods
global:
  podAnnotations:
    tags.datadoghq.com/service: <name>
    tags.datadoghq.com/env: production
    tags.datadoghq.com/version: "<version>"

# Pattern B: per-component — only applies to that deployment/daemonset
server:
  podAnnotations:
    tags.datadoghq.com/service: <name>
    tags.datadoghq.com/env: production
    tags.datadoghq.com/version: "<version>"
```

Run `helm show values <chart>/<component>` or read the existing `helm.valuesObject` in `gitops/apps/` to determine which pattern is in use. Do NOT write annotations at the top-level resource metadata — they must be on the pod template (`spec.template.metadata.annotations`).

**Version lookup (applies to all milestones):**

Check `VERSIONS.lock` at the repo root for the component's deployed version. If `VERSIONS.lock` does not exist, check the existing Helm values in `gitops/apps/<component>.yaml` for a `version:` or `tag:` field — use that value. Do NOT invent or guess a version number.

---

## Milestones

> **Order:** ArgoCD first (lowest complexity, no instrumentation gaps), then Kyverno (OTLP-only, confirm edge via Collector path), then Falco, cert-manager, Istio ambient. Skip any component that `research/30` identifies as not emitting service-identifiable telemetry.

### Milestone 1 — ArgoCD UST annotations

**Step 0:** Read `gitops/apps/` for the ArgoCD Application YAML. Read `research/30-per-component-telemetry-synthesis-2026.md` for the ArgoCD row.

**Steps:**

1. In the ArgoCD Helm values (under `gitops/apps/argocd.yaml` or equivalent), add pod annotations to the ArgoCD server's pod template:

   ```yaml
   # Under helm.valuesObject (or values.yaml equivalent) for the argocd-server deployment:
   server:
     podAnnotations:
       tags.datadoghq.com/service: argocd
       tags.datadoghq.com/env: production
       tags.datadoghq.com/version: "<argocd-version-from-VERSIONS.lock>"
   ```

   **Before writing:** verify the exact path in the ArgoCD Helm chart for pod annotations on the server, repo-server, and application-controller components. The chart may use `global.podAnnotations` for all components, or per-component `podAnnotations` keys. Read the ArgoCD chart schema or a `helm show values` output before committing.

2. Deploy and verify: `GET /api/v1/services` must return `argocd` with `env:production`; `GET /api/v1/service_dependencies` must return ArgoCD with expected edges (if ArgoCD calls any other service).

3. Add an assertion to `verify/test_datadog_service_map.py`:

   ```python
   def test_argocd_service_map():
       """Assert ArgoCD appears in Datadog with env:production."""
       r = requests.get(f"https://api.{DD_SITE}/api/v1/services", headers=HEADERS)
       r.raise_for_status()
       services = r.json().get("data", [])
       assert any(
           s["attributes"]["service_name"] == "argocd"
           and s["attributes"].get("env") == "production"
           for s in services
       ), "argocd not found in Datadog services with env:production"
       print("✓ ArgoCD service present in Datadog with env:production")
   ```

**Done when:**
- [ ] ArgoCD pod templates carry `tags.datadoghq.com/service=argocd`, `env=production`, and `version=<actual-version>` annotations
- [ ] `argocd` appears in `GET /api/v1/services` with `env:production`
- [ ] `verify/test_datadog_service_map.py` assertion for ArgoCD passes

---

### Milestone 2 — Kyverno UST annotations

**Step 0:** Read the Kyverno Application YAML in `gitops/apps/kyverno.yaml`. Note: Kyverno now uses the Datadog Agent Autodiscovery openmetrics check (M5 D9 superseded by meta-PRD D4 2026-06-25; OTLP tracing/metrics blocks removed in commit `8ed0a0c`). The `admissionController.podAnnotations` block already exists with the Autodiscovery annotation `ad.datadoghq.com/kyverno.checks` — UST annotations must be ADDED to that existing block, not replace it.

**Steps:**

1. In `gitops/apps/kyverno.yaml`, add UST annotations to the existing `admissionController.podAnnotations` block (merge, do not replace the Autodiscovery annotation already there), and add `podAnnotations` to the background controller and cleanup controller pod templates. Kyverno's Helm chart uses per-component keys — use the annotation path lookup from the Milestone Working Pattern to verify. Example shape:

   ```yaml
   admissionController:
     podAnnotations:
       tags.datadoghq.com/service: kyverno
       tags.datadoghq.com/env: production
       tags.datadoghq.com/version: "<kyverno-version>"
   backgroundController:
     podAnnotations:
       tags.datadoghq.com/service: kyverno
       tags.datadoghq.com/env: production
       tags.datadoghq.com/version: "<kyverno-version>"
   cleanupController:
     podAnnotations:
       tags.datadoghq.com/service: kyverno
       tags.datadoghq.com/env: production
       tags.datadoghq.com/version: "<kyverno-version>"
   ```

   Look up the version using the version lookup procedure from the Milestone Working Pattern. Do NOT leave placeholder text in the committed YAML.

2. Deploy and verify: `GET /api/v1/services` must return `kyverno` with `env:production`.

3. Add an assertion to `verify/test_datadog_service_map.py` following the same shape as the ArgoCD assertion in Milestone 1, with `service_name == "kyverno"`.

**Done when:**
- [ ] Kyverno pod templates carry UST annotations with `service=kyverno`, `env=production`, `version=<actual-version>`
- [ ] `kyverno` appears in `GET /api/v1/services` with `env:production`
- [ ] `verify/test_datadog_service_map.py` assertion for Kyverno passes

---

### Milestone 3 — Falco UST annotations

**Step 0:** Read `gitops/apps/falco.yaml`. Falco runs as a DaemonSet — annotations go on the DaemonSet pod template. Read the Falco row in `research/30-per-component-telemetry-synthesis-2026.md` for the exact annotation path in the Falco Helm chart.

**Steps:**

1. In `gitops/apps/falco.yaml`, add pod annotations to Falco's DaemonSet pod template. Falco's Helm chart typically uses a top-level `podAnnotations` key — verify using the annotation path lookup from the Milestone Working Pattern. Example shape:

   ```yaml
   podAnnotations:
     tags.datadoghq.com/service: falco
     tags.datadoghq.com/env: production
     tags.datadoghq.com/version: "<falco-version>"
   ```

   Look up the version using the version lookup procedure from the Milestone Working Pattern. Do NOT leave placeholder text in the committed YAML.

2. Deploy and verify: `GET /api/v1/services` must return `falco` with `env:production`.

3. Add an assertion to `verify/test_datadog_service_map.py` following the same shape as the ArgoCD assertion in Milestone 1, with `service_name == "falco"`.

**Done when:**
- [ ] Falco DaemonSet pod template carries UST annotations with `service=falco`, `env=production`, `version=<actual-version>`
- [ ] `falco` appears in Datadog services with `env:production`
- [ ] `verify/test_datadog_service_map.py` assertion for Falco passes

---

### Milestone 4 — cert-manager UST annotations

**Step 0:** Read the cert-manager Application YAML in `gitops/apps/`. Note the `rename_labels: {name: cert_name}` gotcha from M5 Decision 4 — this is on the Autodiscovery annotation, not the UST annotation. UST annotations are separate pod labels and do not interact with the Autodiscovery rename.

**Steps:**

1. In `gitops/apps/cert-manager.yaml` (or equivalent), add pod annotations to cert-manager's controller Deployment pod template. cert-manager's Helm chart typically uses a top-level `podAnnotations` key — verify using the annotation path lookup from the Milestone Working Pattern. Example shape:

   ```yaml
   podAnnotations:
     tags.datadoghq.com/service: cert-manager
     tags.datadoghq.com/env: production
     tags.datadoghq.com/version: "<cert-manager-version>"
   ```

   If cert-manager deploys multiple components (controller, cainjector, webhook), annotate all three — each runs in its own pod. Look up the version using the version lookup procedure from the Milestone Working Pattern. Do NOT leave placeholder text in the committed YAML.

2. Deploy and verify: `GET /api/v1/services` must return `cert-manager` with `env:production`.

3. Add an assertion to `verify/test_datadog_service_map.py` following the same shape as the ArgoCD assertion in Milestone 1, with `service_name == "cert-manager"`.

**Done when:**
- [ ] cert-manager controller pod template carries UST annotations with `service=cert-manager`, `env=production`, `version=<actual-version>`
- [ ] `cert-manager` appears in Datadog services with `env:production`
- [ ] `verify/test_datadog_service_map.py` assertion for cert-manager passes

---

### Milestone 5 — Istio ambient UST annotations

**Step 0:** Read the Istio/ztunnel Application YAML in `gitops/apps/`. Istio ambient uses L4-only ztunnel telemetry (M5 Decision 6). Note that the OOTB Istio Datadog dashboard is sidecar-oriented and will render sparse for ambient; UST annotations here are for the Service Map edge, not the dashboard.

**Steps:**

1. In `gitops/apps/istio.yaml` (or equivalent), add pod annotations to ztunnel's DaemonSet pod template. If istiod is present as a separate Deployment, annotate it too. Istio's Helm chart typically uses per-component `podAnnotations` keys — verify using the annotation path lookup from the Milestone Working Pattern. Example shape:

   ```yaml
   # ztunnel DaemonSet pod template:
   ztunnel:
     podAnnotations:
       tags.datadoghq.com/service: istio
       tags.datadoghq.com/env: production
       tags.datadoghq.com/version: "<istio-version>"

   # istiod Deployment pod template (if present):
   pilot:
     podAnnotations:
       tags.datadoghq.com/service: istio
       tags.datadoghq.com/env: production
       tags.datadoghq.com/version: "<istio-version>"
   ```

   Look up the version using the version lookup procedure from the Milestone Working Pattern. Do NOT leave placeholder text in the committed YAML.

2. Deploy and verify: `GET /api/v1/services` must return `istio` with `env:production`.

3. Add an assertion to `verify/test_datadog_service_map.py` following the same shape as the ArgoCD assertion in Milestone 1, with `service_name == "istio"` matching the locked decision in the Locked Decisions table.

**Done when:**
- [ ] ztunnel (and istiod if present) pod templates carry UST annotations with `service=istio`, `env=production`, `version=<actual-version>`
- [ ] `istio` appears in Datadog services with `env:production`
- [ ] `verify/test_datadog_service_map.py` assertion for Istio passes

---

### Milestone 6 — Final acceptance gate

**Steps:**

1. Run `verify/test_datadog_service_map.py` end-to-end — this script asserts both the AI layer Service Map edges (from PRD #27) and all platform component service presence assertions added in Milestones 1–5. All assertions must pass.

2. Confirm no AI-layer UST values were changed: run `git diff origin/main -- gitops/ai-layer/ agent/gateway/` and verify no `OTEL_RESOURCE_ATTRIBUTES` changes are present.

**Done when:**
- [ ] `verify/test_datadog_service_map.py` passes for all AI-layer edges (PRD #27) and all platform component service presence checks (this PRD)
- [ ] No AI-layer UST values changed in this PRD's diff

---

## Acceptance Criteria

- [ ] All five platform components (ArgoCD, Kyverno, Falco, cert-manager, Istio ambient) appear in `GET /api/v1/services` with `env:production`
- [ ] `verify/test_datadog_service_map.py` passes the full suite (AI layer edges + platform component service presence)
- [ ] No AI-layer component UST values changed

---

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-25 | Platform component UST is a separate PRD from AI layer UST (PRD #27) | M6's AI layer work (agentgateway fix, guard-proxy CLIENT span, Service Map verify) is the critical path. Platform component UST extends the Service Map but is not required for the workshop's AI-layer story beats. Separating the PRDs lets Michael implement PRD #27 immediately without waiting for all platform component annotations to be worked out. Inherited from PRD #7 M6 Decision Log entry 603 (2026-06-25). |
| 2026-06-25 | One milestone per component with iterate loop | Machine-verifiable acceptance (API-based) per component; expect multiple deploy-check-adjust cycles. Inherited from PRD #7 M6 Decision Log entries 591 and 599 (2026-06-25). |
| 2026-06-25 | Acceptance via `GET /api/v1/service_dependencies` and `GET /api/v1/services` — no browser automation | Consistent with PRD #27 M6 Decision 5. Datadog's Service Map renders as canvas/SVG; API assertions are machine-verifiable and repeatable. |
| 2026-06-27 | Deterministic acceptance is the static annotation gate, NOT a live `GET /api/v1/services` assertion. Live catalog presence is a manual facilitator UI step. | Verified against the live Datadog API docs (2026-06-27): `GET /api/v1/services` is not a documented public endpoint, and the documented `GET /api/v2/services/definitions` lists only services that have a registered `service.datadog.yaml` definition — our components are discovered purely from UST telemetry tags (no definition file) and so never appear there. There is no stable public API to assert "telemetry-discovered service X is present with `env:production`"; that lives in the Software Catalog UI. Shipping a live assertion against `/api/v1/services` would fail even when UST works correctly. The runnable gate is therefore the static check in `verify/test_observability.py` (asserts all five components carry `tags.datadoghq.com/{service,env,version}` with `env=production` and the real version); the live confirmation is a facilitator opening Software Catalog and confirming the five components show `env:production`. Source: https://docs.datadoghq.com/api/latest/service-definition/ and https://docs.datadoghq.com/getting_started/tagging/unified_service_tagging/. |
