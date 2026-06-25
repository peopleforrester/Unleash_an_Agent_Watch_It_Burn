# PRD #34: Per-Attendee Datadog Credential Injection

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/34
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 8 child PRD
**Priority**: High
**Status**: Not started

---

## Step 0 — Read before starting

This PRD assumes all M1–M7 child PRDs are merged. In particular:

- **PRD #13** (MVP walking skeleton) must be complete — `datadog-secret` consumers (`otel-collector.yaml`, `falcosidekick.yaml`) are already wired to read from the secret.
- **PRD #26** (Datadog Agent DaemonSet) must be complete — the DatadogAgent CR's `spec.global.credentials` reads from `datadog-secret` (two-key shape: `api-key` + `app-key`, established in M5 Decision 1(e)).
- Read the meta-PRD #7 Milestone 8 Decision Log entries (all dated 2026-06-24 and 2026-06-25) — the per-attendee org model and division of labor are locked there. Do not re-open these decisions.

**Locked decisions (do not re-open):**

| Decision | Value |
|---|---|
| Org model | Per-attendee trial org — each cluster reports to the attendee's own org from `pool.csv` (meta-PRD M8 Decision 5) |
| `datadog-secret` shape | Two keys: `api-key` and `app-key` (meta-PRD M5 Decision 1(e)) |
| Namespaces requiring `datadog-secret` | `monitoring` (OTel Collector + Falcosidekick), `security` (Falcosidekick), `datadog` (Datadog Operator / DatadogAgent CR) |
| Injection mechanism ownership | Michael — he owns designing and implementing how `pool.csv` entries flow into each cluster's `datadog-secret`; Whitney does not implement the injection mechanism |
| Cross-fleet visibility | Out of scope — each cluster reports only to its attendee's org; no dual-export to a shared facilitator org |
| `DD_SITE` | `datadoghq.com` (US1) — already hardcoded in `gitops/apps/otel-collector.yaml` |

---

## Problem

Each workshop cluster needs a `datadog-secret` Kubernetes Secret (containing `api-key` and `app-key`
for the attendee's Datadog trial org) in three namespaces: `monitoring`, `security`, and `datadog`.
Without this secret, the OTel Collector, Falcosidekick, and Datadog Agent DaemonSet all fail to
authenticate with Datadog — no telemetry flows and no Falco alerts appear.

There is no verified end-to-end confirmation that per-attendee credential injection creates this
secret correctly in all three namespaces on a live cluster.

---

## Milestones

### Milestone 1 — Implement per-attendee `datadog-secret` injection (Michael)

**Owner: Michael**

Design and implement the mechanism that injects `datadog-secret` into each cluster at spawn time,
using the attendee's credentials from `pool.csv`.

**Sub-questions Michael must answer as part of this milestone** (not pre-decided — Michael chooses):
- How do `pool.csv` entries flow into a store that the cluster can read from (e.g., AWS Secrets
  Manager, Terraform variable, fleet driver `kubectl apply`)?
- Which of the three mechanisms creates the secret across all three namespaces atomically:
  ESO `ExternalSecret` per namespace, Terraform resource in the cluster module, or fleet driver
  seeding from `pool.csv` at spawn time?
- How does the cluster know which attendee's row to use from `pool.csv`?

**Done when:**
- [ ] `datadog-secret` (containing `api-key` and `app-key`) is automatically created in the
  `monitoring`, `security`, and `datadog` namespaces when a cluster spawns for a given attendee
- [ ] The secret contents match that attendee's Datadog trial org credentials from `pool.csv`
- [ ] **CRITICAL: credentials are never printed to the terminal, committed to git, or logged**
- [ ] Michael has posted a comment on this issue describing the mechanism chosen
  (this comment is required before Milestone 2 can begin)

---

### Milestone 2 — Live cluster acceptance verification

**Owner: Whitney**

**Step 0: Milestone 1 must be complete** — Michael must have posted a comment on this issue
describing the injection mechanism before this milestone begins.

Verify on a live cluster that `datadog-secret` is present with the correct keys in all three
namespaces, and that each consumer is successfully using it.

**Verification steps:**

1. **Secret presence check** — for each of the three namespaces, confirm the secret exists with
   both keys:
   ```bash
   kubectl --context "$CONTEXT" get secret datadog-secret -n monitoring -o jsonpath='{.data}' | jq 'keys'
   kubectl --context "$CONTEXT" get secret datadog-secret -n security -o jsonpath='{.data}' | jq 'keys'
   kubectl --context "$CONTEXT" get secret datadog-secret -n datadog -o jsonpath='{.data}' | jq 'keys'
   ```
   Expected output for each: `["api-key", "app-key"]`

2. **OTel Collector** — confirm it started without credential errors:
   ```bash
   kubectl --context "$CONTEXT" logs -n monitoring -l app.kubernetes.io/name=opentelemetry-collector --tail=50 | grep -i "datadog\|auth\|error\|fail"
   ```

3. **Falcosidekick** — confirm the Datadog output is enabled and posting:
   ```bash
   kubectl --context "$CONTEXT" logs -n security -l app.kubernetes.io/name=falcosidekick --tail=50 | grep -i "datadog\|POST OK\|error\|fail"
   ```
   Expected: `Datadog - POST OK (202)` after a Falco alert fires.

4. **Datadog Agent** — confirm it authenticated successfully:
   ```bash
   kubectl --context "$CONTEXT" get datadogagent -n datadog -o jsonpath='{.status.conditions}'
   ```
   Expected: `Ready=True` with no credential error conditions.

5. **End-to-end smoke test** — confirm telemetry is reaching the attendee's Datadog trial org.
   Log into the trial org's Datadog UI and confirm at least one metric or trace has appeared.
   **Do not use Whitney's employee account** — verify in the attendee's actual trial org.

**Done when:**
- [ ] `datadog-secret` confirmed present with `["api-key", "app-key"]` in all three namespaces
  on a live cluster
- [ ] OTel Collector logs show no credential errors
- [ ] Falcosidekick logs show `POST OK (202)` after a Falco alert
- [ ] DatadogAgent CR status shows `Ready=True`
- [ ] At least one metric or trace visible in the attendee's Datadog trial org UI

---

## Acceptance Criteria

- [ ] Per-attendee `datadog-secret` injection mechanism implemented (Michael — Milestone 1)
- [ ] Mechanism documented in a comment on this issue (Michael — Milestone 1)
- [ ] `datadog-secret` confirmed present with both keys in `monitoring`, `security`, and `datadog`
  namespaces on a live cluster (Whitney — Milestone 2)
- [ ] All four consumers (OTel Collector, Falcosidekick, Datadog Agent, DatadogAgent CR) confirmed
  using credentials without errors
- [ ] At least one metric or trace visible in an attendee's Datadog trial org (end-to-end proof)
- [ ] PROGRESS.md updated

---

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-25 | Per-attendee trial org model (inherited from meta-PRD M8 Decision 5) | Each cluster reports to the attendee's own trial org from `pool.csv`. Not a shared org, not dual-export. Cross-fleet facilitator visibility is out of scope for now. |
| 2026-06-25 | Injection mechanism is Michael's responsibility | Michael owns designing and implementing per-cluster secret injection. Whitney does not implement or block on a specific mechanism choice. |
| 2026-06-25 | Verification is API/kubectl-based, not browser automation | Follows the M6 precedent: machine-verifiable assertions (kubectl + Datadog API) over Playwright. The one exception is the final smoke-test step (step 5), which requires a human to confirm a metric or trace is visible in the trial org UI — this cannot be automated without the attendee's app key, which is not in the cluster. |
