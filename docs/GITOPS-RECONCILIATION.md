<!-- ABOUTME: Records the "GitOps is canonical" decision and the platform/ to gitops/ reconciliation. -->
<!-- ABOUTME: Lists what was consolidated and the provisioning-side rewire still owed (separate project). -->

# GitOps reconciliation

## Decision

GitOps is the single source of truth. The canonical deployment is the app-of-apps:

```
gitops/bootstrap/app-of-apps.yaml  ->  gitops/apps/*.yaml  ->  { policies/, security/, gitops/, backstage/k8s, observability-idp/ }
```

ArgoCD owns every resource. Nothing the cluster needs at steady state is applied by an
imperative `kubectl apply`. The only legitimately-imperative bootstrap is IRSA/IAM (not
GitOps-able) and the ArgoCD install itself (`infra/deploy-full-idp.sh`).

## Background: there were two parallel models

The repo grew a second deployment model alongside the canonical one:

- **Model A (canonical):** `gitops/` app-of-apps, applied by `deploy-full-idp.sh`.
- **Model B (non-canonical):** a hub-spoke ApplicationSet under `platform/argocd/` plus
  imperative applies in `infra/cluster3-setup.sh` and `infra/bootstrap.sh`. Model B
  references its own duplicate component copies under `platform/`.

`platform/` is therefore a duplicate tree, not the source of truth.

## Done in this pass (manifests)

The canonical files were corrected by porting the better content out of `platform/`:

| File | What changed | Why |
|---|---|---|
| `policies/kyverno/require-resource-limits.yaml` | Replaced with the rule-level `validate.failureAction: Audit` version | The old canonical copy used the deprecated top-level `spec.validationFailureAction` and lacked the `/spec/rules/0/validate/failureAction` path that the Beat-1 toggle (`beats/01-cncf-wall/toggle-kyverno-enforce.sh`) patches. The live Audit to Enforce demo would have failed against it. |
| `gitops/apps/falco.yaml` | Added a `workshop-agent-rules.yaml` entry to `customRules` (shell/exec in agent pod, unexpected outbound, planted FAKE- sentinel reads) | The canonical Falco app had generic + EKS rules but none of the workshop agent-pod detections that lived only in `platform/falco/rules-workshop.yaml`. |

Byte-identical duplicates needed no port: `minimal-floor.yaml` and `block-argocd-drift.yaml`.

After this pass the canonical files carry the correct, workshop-aware content. The
`platform/` copies are now redundant (identical content) or superseded.

## Owed by the provisioning project (NOT done here)

Removing `platform/` is coupled to provisioning wiring, which is handled in a separate
project. Before `platform/` can be deleted, that project must:

1. Rewire the attendee-fleet ApplicationSet (`platform/argocd/appset-attendee.yaml` ->
   `platform/argocd/apps/child-apps.yaml`) to point at the canonical `gitops/` app-of-apps
   (or canonical component paths) instead of the `platform/` duplicates.
2. Change `infra/cluster3-setup.sh` and `infra/bootstrap.sh` to stop imperatively applying
   `platform/kyverno/policies/*` and the `platform/argocd/*` set, and let ArgoCD own those
   resources through the canonical app-of-apps. Keep only IRSA/IAM imperative.
3. Then delete the `platform/` tree:
   `platform/{argocd, falco, kyverno, observability}`.

Until then, `platform/` stays in place so Model B does not break, but it is non-canonical.
If a policy needs to change, change the canonical copy under `policies/` or `security/` or
`gitops/apps/`, never the `platform/` copy.

## Open item flagged separately

`agent/kagent-modelconfig-bedrock.yaml` declares `claude-sonnet-4-6` while `BUILD-SPEC.md`
pins `claude-haiku-4-5`. Pick one before any slide quotes a model-card number. Not part of
this reconciliation.
