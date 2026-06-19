<!-- ABOUTME: Grounded research spike on the CNCF "wall" stack versions and controls for the workshop. -->
<!-- ABOUTME: Resolves June 2026 stable versions, the ArgoCD-drift control, Kyverno toggle, and aggregate-attack feasibility. -->

# CNCF "Wall" Stack, Research Spike

Subject: the existing CNCF controls (admission + RBAC + GitOps-drift) that the revised
talk aggregates into ONE beat blocking an agent in concert. Covers attacks 1, 2, 3 of
the BUILD-SPEC (Kyverno admission, scoped RBAC, ArgoCD-drift admission block).

## Verification Method

Web research, dated 2026-06-15. Each material claim carries its source URL inline.
Sources are official GitHub release pages, project docs (kyverno.io, argo-cd.readthedocs.io,
vcluster.com), and Artifact Hub. Version numbers were resolved against current
release pages, NOT training data. No live cluster was used; this is a desk spike.

## Pinned versions

These are the latest STABLE (non-rc, non-prerelease) versions as of 2026-06-15, suitable
for `VERSIONS.lock`. Note: the BUILD-SPEC's v0.29 vCluster reference (April 2026) is now
five minor releases stale.

| Project | Version (lock string) | Source URL | Breaking-change note |
|---|---|---|---|
| vCluster | `v0.34.3` (CLI/distro tag; Helm chart `0.34.3`) | https://github.com/loft-sh/vcluster/releases | Spec says v0.29 line. Now v0.34.x, the v0.30→v0.34 span introduced the "vCluster Standalone" multi-tenancy foundation (see vcluster.com blog) and config-schema evolution across minors. **Verify `vcluster.yaml` schema and `vcluster create` flags against v0.34 docs before reusing any v0.29-era config.** v0.34.3 (Jun 10) is newer than v0.34.2 (Jun 8); v0.35.0 is still rc as of this date. |
| Kyverno | app `v1.18.1`, Helm chart `kyverno` `3.8.1` | https://kyverno.io/docs/installation/releases/ , https://artifacthub.io/packages/helm/kyverno/kyverno | **BREAKING for policy authoring:** `spec.validationFailureAction` (spec-level) is deprecated; current field is `validate.failureAction` at the RULE level. v1.18 supports k8s v1.33–v1.35. Note `kyverno-policies` chart is at `3.8.1-rc.2` (the bundled best-practice policies chart is still rc, author policies directly rather than depending on that chart). A CVE (CVE-2026-22039) is referenced against the kyverno Go module, confirm the pinned patch is not affected before build. |
| Argo CD | `v3.4.3` | https://github.com/argoproj/argo-cd/releases | Latest stable May 28, 2026. 3.4 series note: the first 3.4 release was named `v3.4.1`, not `3.4.0`. 3.3 line (`v3.3.11`) is still patched if a more conservative pin is wanted. Major v3.x changed default resource-tracking and RBAC defaults vs 2.x, relevant to the drift control below. |
| Falco | `0.44.1` | https://github.com/falcosecurity/falco/releases | Stable Jun 11, 2026 (0.44.0 was May 26; 0.44.1 adds "disable BPF iterators" support + fixes). Driver/eBPF compatibility is the usual gotcha, match the Falco driver to the host kernel on EKS nodes. Falco is defense-in-depth here, not one of the three blocking controls. |
| kube-prometheus-stack | chart `86.2.3` (Prometheus + Grafana + Alertmanager + operator) | https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack | Latest chart on Artifact Hub. CRD-upgrade caveat persists: kube-prometheus-stack does NOT auto-upgrade its CRDs on `helm upgrade`, apply CRDs out-of-band when crossing major chart versions. |
| OpenTelemetry Collector | `v0.154.0` | https://github.com/open-telemetry/opentelemetry-collector-releases/releases | Latest Jun 9, 2026. v0.154.0 deprecates the JMX receiver (irrelevant here). For GenAI traces, use the contrib distro; confirm the OTel GenAI semantic-convention version against current docs at build (conventions are still evolving). |

## ArgoCD drift control

The spec's `block-argocd-drift.yaml` is correctly modeled as a **Kyverno `ClusterPolicy`
validate rule with a `deny` block**, not a bespoke webhook. The current best-practice shape:

- **Match** on resources that carry an ArgoCD tracking identifier. ArgoCD's current
  (v3.x) recommended tracking method for production is **annotation+label**, the
  annotation `argocd.argoproj.io/tracking-id` is the source of truth, with the legacy
  label `app.kubernetes.io/instance` also present. Match on presence of the tracking-id
  annotation (or the instance label) to scope the policy to ArgoCD-managed objects.
  Source: https://kyverno.io/docs/policy-types/cluster-policy/match-exclude/ ,
  resource-tracking docs (oneuptime, 2026-01-30).
- **Deny** when `request.operation` is `UPDATE` or `DELETE`. This mirrors the official
  Kyverno "Block Updates and Deletes" sample policy, which uses `kyverno.io/v1`
  `ClusterPolicy`, a `validate.deny` with `conditions` checking the operation, and
  matches protected resources by label. Source:
  https://kyverno.io/policies/other/block-updates-deletes/block-updates-deletes/
- **Exclude** the ArgoCD application-controller principal so legitimate syncs pass.
  Exclude on `subjects`/`serviceAccounts` (e.g. `system:serviceaccount:argocd:argocd-application-controller`)
  or, in vCluster context, the controller identity that actually drives sync. The
  official sample excludes by `clusterRoles: [cluster-admin]`; for this build the exclusion
  must be the ArgoCD controller SA, since the whole point is "anyone but ArgoCD is denied."
- **`background: false` is REQUIRED.** Any rule that consults `userInfo`/subjects (which
  the exclude does) is only evaluated at admission, not in background scans. Source:
  https://kyverno.io/docs/policy-types/cluster-policy/validate/

**Self-heal as defense-in-depth (confirmed current):** set `syncPolicy.automated.selfHeal: true`
on the Application. Without `selfHeal`, ArgoCD auto-syncs on Git changes but does NOT revert
manual cluster drift. With it, out-of-band changes are reverted within the sync interval
(default ~3 min). Source: https://argo-cd.readthedocs.io/en/stable/ , self-healing docs
(oneuptime, 2026-01-25). The talk beat is: admission BLOCKS the drift outright; self-heal
is the second layer that would have reverted it anyway.

## Kyverno toggle

Current syntax for a `require-resource-limits` validate rule (verified against current docs):

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-limits
spec:
  rules:
    - name: check-container-resources
      match:
        any:
          - resources:
              kinds: [Pod]
      validate:
        failureAction: Enforce      # <-- toggle lives HERE (rule-level), Audit | Enforce
        message: 'All containers must have CPU and memory resource limits defined.'
        pattern:
          spec:
            containers:
              - name: '*'
                resources:
                  limits:
                    memory: '?*'
                    cpu: '?*'
```

Source: https://kyverno.io/docs/policy-types/cluster-policy/validate/

**The attack-1 live toggle:** flip `spec.rules[].validate.failureAction` between `Audit`
and `Enforce`.
- `Audit` → non-compliant resource is admitted; a violation is recorded in a
  `PolicyReport`/`ClusterPolicyReport`. (Workshop start state for attack 1.)
- `Enforce` → admission webhook BLOCKS creation/update with the policy's `message`.

The `toggle-on.sh` is a single `kubectl patch`/`kubectl apply` flipping that one field.
**Important deprecation:** do NOT use the spec-level `spec.validationFailureAction`, it is
deprecated in current Kyverno. Use rule-level `validate.failureAction`. This is the most
likely place a memory-based build would write stale YAML.

## Aggregate attack feasibility

**Verdict: FEASIBLE.** A single agent-driven action sequence can cleanly demonstrate all
three controls in one narrative beat, provided the sequence is ordered correctly and each
denial returns a visibly distinct error. The three controls live in different planes and do
not interfere with each other:

1. **Deploy non-compliant workload** → Kyverno admission. Blocked by the validating webhook
   (assuming attack-1 policy is in `Enforce`; for the aggregate beat it would be Enforce).
   Error origin: admission webhook, Kyverno message.
2. **Privilege escalation via ClusterRoleBinding** → scoped RBAC. Blocked by the agent SA's
   Role lacking `create clusterrolebinding`. Error origin: API-server authorization
   (`Forbidden`, RBAC), BEFORE any admission webhook fires.
3. **Out-of-band `kubectl apply` to an ArgoCD-managed resource** → Kyverno drift policy.
   Blocked by the `block-argocd-drift` validate/deny rule because the agent SA is not the
   ArgoCD controller SA. Error origin: admission webhook, drift-policy message.

**Sequencing / ordering gotchas:**

- **RBAC precedes admission in the request lifecycle.** Authorization (RBAC) runs BEFORE
  admission webhooks. So step 2 fails with an RBAC `Forbidden` and the Kyverno webhook is
  never consulted for it, that is correct and on-message (RBAC is the wall, not admission),
  but the narration must not claim "Kyverno blocked the escalation." Keep the attribution
  per-step: RBAC for step 2, Kyverno for steps 1 and 3.
- **Step 3 depends on the agent SA having `update`/`patch` permission on the target kind but
  NOT being the ArgoCD principal.** If the agent SA lacks RBAC to touch the resource at all,
  step 3 fails at RBAC (like step 2) and never reaches the drift admission policy, the beat
  collapses to "RBAC blocked everything," losing the GitOps-drift point. **Design the agent
  Role so it CAN `patch` the namespaced resource type by RBAC, so the request reaches
  admission and is rejected by the drift policy on principal/label grounds.** This is the
  single most important RBAC-vs-admission tuning point for the aggregate beat.
- **The drift policy's `deny` must key on the principal (exclude ArgoCD controller SA), not
  on the label alone**, otherwise ArgoCD's own self-heal sync would also be denied,
  deadlocking the resource. Exclude the controller SA explicitly; `background: false`.
- **Distinct, legible errors.** For the live beat, each step should surface a clearly
  different rejection (RBAC `Forbidden` vs two different Kyverno messages) so the audience
  sees three controls, not one. Pre-stage the agent prompts so the model attempts the three
  actions in order and the terminal shows three distinct denials.
- **Attack-1 policy state in the aggregate beat:** if the aggregate beat is meant to show
  all three controls already-on, attack 1's Kyverno policy must be in `Enforce` for this
  beat, which is in tension with attack 1's standalone "start in Audit, toggle to Enforce"
  story. Reconcile: either run the toggle first, or use a separate always-Enforce policy
  (e.g. disallow-privileged or latest-tag) for the aggregate workload step so the
  attack-1 toggle narrative stays intact.

## Unverified / Could not confirm

- **Exact ArgoCD application-controller ServiceAccount name inside a vCluster context.**
  On a standard install it is `argocd-application-controller` in the `argocd` namespace, but
  how ArgoCD-driven syncs present their identity to a per-attendee vCluster's API server
  (host SA vs synced SA) was not verified against vCluster v0.34 docs. Must confirm the
  actual `request.userInfo.username` seen at admission inside the vCluster before writing the
  exclude block, guessing this will silently break either the block or self-heal.
- **CVE-2026-22039 (Kyverno) details and affected version range**, saw the reference
  (gitlab advisory DB) but did not open it. Confirm v1.18.1 is patched.
- **OTel GenAI semantic-convention version** pinning, not resolved here (out of this
  spike's three-control scope; flagged for the observability research track).
- **vCluster v0.29→v0.34 config-schema breaking changes**, confirmed the version jump and
  the Standalone-foundation change exists, but did not enumerate field-level breaking changes
  in `vcluster.yaml`. Read the v0.34 upgrade notes before porting any v0.29 config.
- **kyverno-policies chart at 3.8.1-rc.2**, the bundled policies chart is pre-release;
  could not confirm a stable 3.8.1 of that specific chart. Author the two workshop policies
  directly rather than depending on it.

## Risks for the build

1. **Stale version anchors in the spec.** vCluster is 5 minors past the spec's v0.29; the
   spec's "verify at build" rule must actually be exercised. Pin from this table, not memory.
2. **Kyverno field deprecation.** Writing `spec.validationFailureAction` (the pre-1.18
   pattern most tutorials and training data still show) will produce policies that don't
   toggle as expected. Use rule-level `validate.failureAction`. High-likelihood footgun.
3. **RBAC over-restriction collapses the aggregate beat (step 3).** If the agent SA can't
   reach the ArgoCD-managed resource via RBAC, the drift admission policy never fires and the
   GitOps point is lost. The agent Role and the drift policy must be co-designed.
4. **Drift-policy principal identity inside vCluster is unverified.** The exclude must match
   the real admission-time username; a wrong guess either blocks ArgoCD self-heal (deadlock)
   or lets the agent through (attack 3 fails to block). Verify on a live vCluster early.
5. **CRD-upgrade hazards.** kube-prometheus-stack does not auto-upgrade CRDs; Kyverno and
   ArgoCD CRD versions must match their pinned charts. Cross-version helm upgrades need
   explicit CRD handling or admission/controllers misbehave.
6. **Falco driver/kernel mismatch on EKS nodes**, not a blocking control but a likely
   "pods CrashLoopBackOff at bootstrap" surprise; pin the matching driver.
