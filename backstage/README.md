# Backstage

The developer portal (#244): every app on the cluster that is not infrastructure, which team owns it, and
its live pods. Public at `backstage-<cluster>.agenticburn.com` through the console's Host routing (#233);
everyone signs in as the guest user.

Deployed by `gitops/apps/backstage.yaml` on the attendee, full and admin profiles (not burn), which builds
this directory with kustomize:

```
kustomization.yaml     what deploys, plus two hashed ConfigMaps (catalog, app-config)
app-config.yaml        layered over the image's own app-config.yaml: catalog files, guest auth, k8s cluster
catalog/               the entities, one file per system, plus org.yaml (groups) and domains.yaml
k8s/backstage.yaml     Deployment + Service, image pinned by digest
k8s/postgres.yaml      disposable Postgres on an emptyDir, trust auth, NetworkPolicy: Backstage only
k8s/backstage-rbac.yaml  read-only ClusterRole for the Kubernetes plugin; no logs, ConfigMaps or Secrets
templates/, k8s/templated-test-svc.yaml  scaffolder material, not deployed
```

The image is built from `images/watch-it-burn-backstage/`; its README has the rebuild, sign and pin steps.
An unsigned image of ours is denied admission (`policies/kyverno/verify-image-signatures.yaml`).

## The catalog

Hex & Cauldron is the company in the workshop's story. Its teams own the systems: `burritobot-developers`
own the agent, workshop-mcp and the storefront; `platform-team` owns guard-proxy, LLM Guard and
agentgateway, which is the "one column is the developer's" table in the run-of-show as a real page.
`tool-vendor` owns evil-mcp, `customer-data-team` customer-stream and `party-planners` the five party apps.
`workshop-crew` sits outside the story and owns the terminal, the drift target, and the two external
systems, the provisioning app and the apex router.

Each Component finds its pods with `backstage.io/kubernetes-label-selector` and
`backstage.io/kubernetes-namespace`. `verify/test_backstage_catalog.py` checks every selector against the
labels the manifests put on each pod, so a new workload with no entity fails there.

## Adding an entity

Add it to the right file in `catalog/`. A new file must go in both `kustomization.yaml`
(`backstage-catalog`) and `catalog.locations` in `app-config.yaml`; the test fails if the two lists disagree.
