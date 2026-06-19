*Purpose: app-of-apps layout that the hub ApplicationSet renders once per registered spoke; each child Application syncs one real component of the per-attendee workshop stack.*

# Per-spoke app-of-apps

The hub `attendee-spokes` ApplicationSet (`../appset-attendee.yaml`) creates one
Application per registered spoke, all pointing here (`platform/argocd/apps`). This
directory is a Kustomization whose resources are themselves ArgoCD `Application`
objects, the standard app-of-apps pattern. Each child Application targets the
**same spoke** (it inherits the destination via the parent's `destination.server`,
which the children re-state with the in-cluster reference because they are created
*on the hub* but sync content *into the spoke* the parent selected).

> Architecture note (rev3): there is **no vCluster**. Each attendee is a separate
> EKS **spoke** cluster registered to the **hub** ArgoCD. The hub renders these
> Applications; the spoke runs the workloads.

## Children and the real paths they sync

| Child Application      | Path                                | Beat / role |
|------------------------|-------------------------------------|-------------|
| `kyverno-policies`     | `platform/kyverno/policies`         | Beat 1, require-resource-limits (Audit start), block-argocd-drift (Enforce) |
| `falco`                | `platform/falco`                    | Runtime detection (defense-in-depth) |
| `observability`        | `platform/observability`           | Per-spoke OTel collector → forwards traces to the **hub** Tempo |
| `agent`                | `agent`                             | kagent Agent + Bedrock ModelConfig + scoped RBAC |
| `gateway`              | `agent/gateway`                     | agentgateway + LLM Guard (Regex-only by default) |
| `beats`                | `beats`                             | planted fake secrets + the ArgoCD-managed sample app for beat 1 |

## Why a child per component

- Each component shows as its own ArgoCD Application, so the facilitator can see
  health/sync per layer in the hub UI during the live run.
- `block-argocd-drift` + `selfHeal` only mean something if there is an
  ArgoCD-managed resource to drift. The **sample app under `beats/`** is that
  resource: beat 1 step 3 patches it out-of-band, admission rejects the patch, and
  if anything slips through, self-heal reverts it.

## verify-at-build

- Confirm the hub repo URL / `targetRevision` matches the real remote before the event.
- Confirm each child path exists and renders (`kubectl kustomize <path>` or
  `argocd app create --dry-run`). Component dirs `platform/falco`,
  `platform/observability`, `agent/gateway`, and `beats` may still be in progress
  per Phase 4/5, children for not-yet-built paths are marked with
  `# verify-at-build` in `child-apps.yaml` and should stay disabled until their
  content lands, rather than syncing an empty/invalid path.
