# PRD #33: Dashboards — OOTB Imports + Terraform Scaffold

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/33
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 7 child PRD
**Priority**: Medium
**Status**: M2 implemented (2026-06-27). `infra/terraform/dashboards/` scaffolded following the sibling-module convention; `terraform init` + `terraform validate` pass clean. On `main` and cherry-picked to all four whitney branches. M1 (OOTB dashboard UI verification for cert-manager / Kyverno / ArgoCD) remains a manual facilitator look at the Datadog UI — there is no public "list catalog dashboards" API to automate it against. Note: this PRD's acceptance text says "no automated test possible since the Datadog app key is not deployed in the cluster" — that reason is inaccurate (the app key IS synced in-cluster via ESO; see PRD #28 Decision Log 2026-06-27). The genuine constraint is the lack of a public dashboard-presence API, not a missing key.

---

## Step 0 — Read before starting

This PRD assumes all M1–M6 child PRDs are merged. In particular:

- **PRD #26** (Datadog Agent DaemonSet) must be complete — the cert-manager, Kyverno, and ArgoCD Agent checks must be `[OK]` on the live cluster before this PRD's Milestone 1 can pass.
- **PRD #27** (UST + Service Map) must be complete — all AI-layer UST is in place.
- Read `research/35-datadog-community-dashboards-2026.md` — the dashboard survey that confirmed which OOTB dashboards are importable and which are not.
- Read the meta-PRD #7 Milestone 7 Decision Log entries (D1a–D6, all dated 2026-06-25) — every import/skip and code decision is locked there. Do not re-open these decisions.

---

## Problem

Three Datadog OOTB dashboards (cert-manager, Kyverno, ArgoCD) are expected to auto-appear in
Datadog once the Datadog Agent checks are active, but their presence in the Datadog UI has never
been verified on a live cluster. Until verified, it is unknown whether any configuration gap
prevents them from appearing.

Additionally, the repo has no Terraform module for dashboard-as-code. Four custom/story dashboards
(Wasted Tokens Over Time, Model Tier Cost Race, Tool Call Heatmap, Guardrail Toggle Timeline) are
planned for dress rehearsal. Without a scaffold in place, there is no clear place to add them when
that time comes.

---

## Solution

1. **Verify the three OOTB dashboards appear** in the Datadog UI — cert-manager, Kyverno, and
   ArgoCD. All three Agent checks are confirmed `[OK]` and data is confirmed flowing; no code
   changes are expected. If a dashboard is missing, diagnose why the check is not producing the
   dashboard (configuration gap in the DatadogAgent CR or pod annotation) and fix it.

2. **Scaffold `infra/terraform/dashboards/`** — a standalone Terraform module following the
   existing sibling-module convention (`cluster/`, `lab-vpc/`). The module starts as a foundation
   with commented-out `datadog_dashboard_json` placeholder resources; custom dashboard definitions
   are deferred to dress rehearsal and will be committed to this module when built.

---

## Locked Decisions (do not re-open)

All from meta-PRD #7 Milestone 7 Decision Log (2026-06-25). Full reasoning is in that Decision Log.

| Decision | Value |
|---|---|
| Import rule | Import OOTB dashboard only if zero-work AND data confirmed flowing. An empty dashboard is worse than none. |
| cert-manager | Import the "Cert Manager Overview" OOTB dashboard — `cert_manager.*` metrics confirmed flowing on live cluster. Auto-installs when Agent check is active; no code work required. |
| Kyverno | Import OOTB Kyverno dashboard directly — `kyverno.*` metrics confirmed flowing via Agent Autodiscovery openmetrics check (OTLP path abandoned per D4; gRPC-Go dns resolver bug baked into Kyverno binary). No OTTL rename needed — Agent check emits `kyverno.*` dot-format names natively. |
| ArgoCD | Import OOTB ArgoCD dashboard — Agent `argocd` check confirmed `[OK]`; annotation in `infra/argocd-values.yaml` (the bootstrap-installed ArgoCD server config, not `gitops/argocd/values.yaml`). No code work required. Issue #32 is moot. |
| Istio | Skip. OOTB `istio_overview.json` is sidecar-only; our ztunnel ambient deployment emits L4 only and the dashboard renders empty. Import is gated on issue #25 (optional waypoint proxy) — handled entirely within that issue's scope if it is ever implemented. |
| ESO | Skip. No official Datadog integration; background component; not in workshop narrative. |
| Custom/story dashboards | All four deferred to dress rehearsal (Wasted Tokens Over Time, Model Tier Cost Race, Tool Call Heatmap, Guardrail Toggle Timeline). Cannot be validated without live LLM agent telemetry from a full workshop run. |
| Dashboard-as-code mechanism | Terraform `datadog_dashboard_json` resources in `infra/terraform/dashboards/`. OOTB dashboards that auto-install via Agent checks do not need Terraform resources — Datadog manages them automatically. |
| No custom Istio dashboard | No custom ztunnel/ambient dashboard of any kind. Istio work lives entirely in optional issue #25. |
| Kyverno OTLP | Abandoned. Both `tracing:` and `metering.config: grpc` blocks were removed from `gitops/apps/kyverno.yaml` in commit `8ed0a0c` (2026-06-25). Switched to Agent Autodiscovery openmetrics check. Do not re-enable OTLP for Kyverno. |

---

## Milestones

### Milestone 1 — Verify OOTB dashboards appear in Datadog

**Step 0**: Confirm PRD #26 is merged and the three Agent checks are `[OK]` on the live cluster
before starting. Run `kubectl get datadogagent -n datadog` to confirm the Agent is running.

**What to do:**

1. Log into the Datadog UI and navigate to **Dashboards → Dashboard List**.
2. Confirm the following three dashboards appear (they auto-install when the Agent checks are
   active — no import step is needed):
   - "Cert Manager Overview" (from the `cert_manager` Agent check)
   - "Kyverno" (from the Kyverno Agent Autodiscovery openmetrics check)
   - "ArgoCD" (from the `argocd` Agent check)
3. For each dashboard: open it and confirm it renders with data (at least one non-empty widget).
   An empty dashboard means data is not flowing and does not count as a pass.

**If a dashboard is missing or empty:**

Diagnose by checking the Agent check status from a pod on the node:
```bash
kubectl exec -n datadog <agent-pod> -- agent check <check-name>
# e.g.: agent check cert_manager
#       agent check kyverno
#       agent check argocd
```

For Kyverno specifically: the check uses Autodiscovery via a pod annotation
(`ad.datadoghq.com/kyverno.checks`) on the kyverno admission controller pod. Confirm the
annotation is present and the pod has been restarted after the annotation was applied.

For ArgoCD: the annotation is in `infra/argocd-values.yaml` (the bootstrap ArgoCD config), not
`gitops/argocd/values.yaml`. Confirm that file's annotation is applied and the ArgoCD server pod
has the annotation.

Fix whatever configuration gap exists, redeploy, and re-verify.

**Done when:**
- [ ] "Cert Manager Overview" dashboard appears in the Datadog UI and renders with data
- [ ] "Kyverno" dashboard appears in the Datadog UI and renders with data
- [ ] "ArgoCD" dashboard appears in the Datadog UI and renders with data

---

### Milestone 2 — Scaffold `infra/terraform/dashboards/` module

**Step 0**: Read `infra/terraform/README.md` and skim `infra/terraform/cluster/main.tf` to
understand the sibling-module convention before writing any code. The `dashboards/` module must
follow the same structural patterns.

**What to do:**

Create `infra/terraform/dashboards/main.tf` as a standalone Terraform module — the same pattern
as `cluster/` and `lab-vpc/` (each is a self-contained module with its own `terraform {}` block,
no root module wiring). The module must:

1. Declare the Datadog provider with version constraint.
2. Include a commented-out `datadog_dashboard_json` resource block as a placeholder, with a
   comment explaining it is ready to receive custom dashboard JSON for dress rehearsal:

```hcl
# ABOUTME: Terraform module for Datadog dashboards as code.
# ABOUTME: Scaffolded in PRD #33; custom dashboards added at dress rehearsal.

terraform {
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = "~> 3.0"
    }
  }
}

provider "datadog" {
  # api_key and app_key read from DD_API_KEY and DD_APP_KEY env vars
}

# Placeholder: uncomment and populate at dress rehearsal for each custom dashboard.
# Each dashboard JSON file goes alongside this module (e.g., ./wasted-tokens.json).
#
# resource "datadog_dashboard_json" "wasted_tokens" {
#   dashboard = file("${path.module}/wasted-tokens.json")
# }
```

3. Run `terraform init` and `terraform validate` — both must pass with no errors.

**Do NOT:**
- Build any actual dashboard JSON files (custom dashboards are deferred to dress rehearsal per
  locked decision above)
- Wire this module into a root module — each module in `infra/terraform/` is standalone
- Add `variables.tf` or `outputs.tf` unless the module needs them (it does not at this stage)

**Done when:**
- [ ] `infra/terraform/dashboards/main.tf` exists
- [ ] `terraform init` passes with no errors
- [ ] `terraform validate` passes with no errors

---

## Acceptance Criteria

1. cert-manager, Kyverno, and ArgoCD OOTB dashboards appear in the Datadog UI and each renders
   with at least one non-empty widget (manual facilitator verification — no automated test possible
   since the Datadog app key is not deployed in the cluster per meta-PRD #7 Decision Log 2026-06-25)
2. `infra/terraform/dashboards/main.tf` exists and `terraform validate` passes

---

## Out of Scope

- Istio dashboard — any Istio dashboard work belongs to optional issue #25
- ESO dashboard — no official Datadog integration; skipped
- Custom story dashboards (Wasted Tokens Over Time, Model Tier Cost Race, Tool Call Heatmap,
  Guardrail Toggle Timeline) — all deferred to dress rehearsal
- Kyverno OTLP re-enabling — the OTLP path was abandoned due to a gRPC-Go dns resolver bug baked
  into the Kyverno binary; do not re-open this
- OOTB Falco and EKS dashboards — those auto-install as part of PRD #26 (Milestone 5) and are
  not in scope here

---

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-25 | All M7 design decisions locked in meta-PRD #7 | See meta-PRD #7 Milestone 7 Decision Log entries D1a–D6 (2026-06-25). This child PRD inherits all of them and does not re-litigate any. |
