# GitOps

ArgoCD-managed Kubernetes resources using the app-of-apps pattern.

## Directory Structure

```
bootstrap/               # The root chart, lab-bootstrap: one Helm chart for every profile (#609)
  Chart.yaml
  values.yaml            # revision: "" (the commit, or branch, every Unleashed source is read at)
  values-attendee.yaml   # apps: the attendee profile's list
  values-burn.yaml       # apps: the burn (community) profile's list
  values-admin.yaml      # apps: the admin profile's list
  values-full.yaml       # apps: the full (instructor) profile's list
  values-local-inference.yaml  # apps: full's list plus vllm-qwen3, one demo cluster only (#394)
  templates/
    apps.yaml            # renders each listed apps/<name>.yaml, its Unleashed sources at .Values.revision
    ghcr-kagent-oci.yaml # the credential-free OCI Helm repository Secret kagent's chart needs
  apps/                  # the ArgoCD Application manifests, one or more per file. What each is, and
                         # what the sister platform runs that we do not, is ../platform-baseline.yaml

argocd/
  values.yaml            # ArgoCD Helm chart values

manifests/               # Raw Kubernetes manifests for demo apps
  demo-app-unicorn/         # Deployment, Service, Ingress
  ecom-frontend/         # Deployment, Service, Ingress
  ecom-api/              # Deployment, Service
  ecom-worker/           # Deployment, Service
  load-generator/        # Deployment

namespaces/
  namespaces.yaml        # Namespace definitions with PSS labels
```

## App-of-Apps Pattern

Every cluster has one root Application, `lab-bootstrap`, sourcing the `gitops/bootstrap` chart with its
profile's `values-<profile>.yaml` and the Helm parameter `revision`. `lab-platform.yaml` at the repo root
presents four of the profiles to lab-platform, whose labctl creates the root at a pinned 40-digit commit with
`revision` set to that commit. `infra/deploy-full-idp.sh <profile>` applies the same root at `staging` with
`revision=staging`, so clusters it builds follow `staging`. It also builds the fifth, `local-inference`, which
lab-platform.yaml leaves out so that only one demo cluster ever carries its model server:

```bash
bash infra/deploy-full-idp.sh attendee   # or burn, admin, full, local-inference
```

After this, ArgoCD manages everything. No more `kubectl apply` is needed.

The chart renders the Applications its values file lists from `bootstrap/apps/`. Each child app points to
either a Helm chart at one exact version or a directory in this repo at `{{ .Values.revision }}`. A profile
is an explicit list: adding an app to a profile is one line in its values file, and a name with no file
fails the render. Nothing the chart renders sources `gitops/bootstrap` itself, so `lab-bootstrap` is the only
root. Prometheus' own `{{ ... }}` alert text is escaped in `apps/prometheus.yaml`, because the chart renders
each app file as a template.

## Sync Wave Ordering

Negative waves are infrastructure prerequisites. Positive waves are applications.
Gaps between groups are reserved for future components.

| Wave | Resources |
|------|-----------|
| -10  | Namespaces |
| -5   | Kyverno (CRD provider) |
| -4   | Kyverno policies, NetworkPolicies, ESO operator |
| -3   | Falco, ESO resources (ClusterSecretStore + ExternalSecrets) |
| -2   | Falcosidekick |
| 1    | Prometheus (kube-prometheus-stack), cert-manager |
| 2    | OTel Collector, cert-manager ClusterIssuers |
| 3    | Grafana dashboards, Tempo |
| 5    | Sample app, Backstage resources (RBAC, catalog) |
| 6    | Backstage |
| 7    | Demo apps (Unicorn Party, E-commerce frontend/API/worker) |
| 8    | Load generator |

## Adding a New Application

1. Create the Kubernetes manifests or identify the Helm chart
2. Create a new `gitops/bootstrap/apps/<name>.yaml` ArgoCD Application manifest; a source in this repo says
   `targetRevision: "{{ .Values.revision }}"`, a chart one exact version
3. Set the appropriate sync wave annotation
4. Add `<name>` to the `apps` list of each profile that should install it (`gitops/bootstrap/values-<profile>.yaml`)
5. Give it an entry in `platform-baseline.yaml` at the repo root; `verify/test_platform_baseline.py` fails on an
   Application file no entry claims
6. Commit and push. Clusters following `staging` pick it up; a lab-platform event takes it at its next pin

See [ADR-002](../docs/adr/ADR-002-gitops-engine.md) for the ArgoCD selection rationale.
