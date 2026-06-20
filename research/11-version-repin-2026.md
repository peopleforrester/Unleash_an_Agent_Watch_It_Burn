# 11 - Version Repin Audit (June 2026)

## Verification Method

All version numbers below were verified against primary sources on 2026-06-20:
GitHub Releases pages and the GitHub API, raw `Chart.yaml` files on each chart's
main branch (the authoritative chart-to-app mapping), Artifact Hub, and official
vendor docs. Training data was NOT trusted for any version string. Where the
WebFetch summarizer returned suspicious release dates (it repeatedly misread 2026
timestamps as 2024/2025), those dates were discarded rather than cited, and the
version numbers were re-confirmed from raw `Chart.yaml` or the GitHub Releases API.

Repo pins were read from `VERSIONS.lock` and from `targetRevision` fields across
`gitops/apps/*.yaml`.

Primary sources consulted:

- https://github.com/istio/istio/releases
- https://github.com/falcosecurity/charts (Chart.yaml at tags falco-9.1.0, falcosidekick-0.14.0, falco-talon-0.4.1)
- https://github.com/falcosecurity/falco-talon/releases
- https://github.com/cert-manager/cert-manager/releases
- https://github.com/kyverno/kyverno/releases
- https://artifacthub.io/packages/helm/kyverno/kyverno
- https://raw.githubusercontent.com/prometheus-community/helm-charts/main/charts/kube-prometheus-stack/Chart.yaml
- https://raw.githubusercontent.com/open-telemetry/opentelemetry-helm-charts/main/charts/opentelemetry-collector/Chart.yaml
- https://raw.githubusercontent.com/grafana/helm-charts/main/charts/tempo/README.md (migration notice)
- https://raw.githubusercontent.com/grafana-community/helm-charts/main/charts/tempo/Chart.yaml
- https://artifacthub.io/packages/helm/grafana-community/tempo
- https://grafana.com/docs/tempo/latest/release-notes/v3-0/
- https://raw.githubusercontent.com/grafana/loki/main/production/helm/loki/Chart.yaml
- https://raw.githubusercontent.com/grafana/alloy/main/operations/helm/charts/alloy/Chart.yaml
- https://github.com/grafana/alloy/releases
- https://github.com/agentgateway/agentgateway/releases
- https://agentgateway.dev/blog/2026-06-17-agentgateway-v1.3.0/
- https://github.com/kagent-dev/kagent/releases
- https://github.com/protectai/llm-guard/tags
- https://hub.docker.com/r/laiyer/llm-guard-api/tags
- https://github.com/argoproj/argo-cd/releases
- https://github.com/argoproj/argo-helm/releases
- https://github.com/external-secrets/external-secrets/releases
- https://github.com/backstage/backstage/releases
- https://github.com/backstage/charts/tags
- https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html
- https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-eks-distro-kubernetes-version-1-36/

## Reconciliation Table

| Component | Repo pin | Current GA | Action |
|---|---|---|---|
| Istio (ambient) | 1.30.1 | 1.30.1 (1.30 is newest stable minor; no 1.31 GA) | None. Current. |
| Falco (chart / app) | chart 9.1.0 / app 0.44.1 | chart 9.1.0 / app 0.44.1 | None. Current. |
| Falcosidekick (chart / app) | chart 0.14.0 / app 2.31.1 | chart 0.14.0 / app 2.31.1 | None. Current. |
| Falco Talon (chart / app) | chart UNKNOWN / app v0.3.0 | chart 0.4.1 / app v0.3.0 | Repin chart to 0.4.1 (appVersion is still v0.3.0). Resolves the UNKNOWN. |
| cert-manager | chart v1.20.2 | v1.20.2 (v1.21 only at alpha) | None. Current. |
| Kyverno (chart / app) | chart 3.8.1 / app v1.18.1 | chart 3.8.1 / app v1.18.1 | None. Current. |
| agentgateway | OSS v1.2.1 | v1.3.0 (GA 2026-06-18) | Bump to v1.3.0. Repo note ("v1.3.0 GA") is correct; v1.2.1 pin is two minors stale. Verify OCI chart tag with `helm pull oci://cr.agentgateway.dev/charts/agentgateway --version v1.3.0`. |
| kagent (chart / app) | chart 0.9.7 | chart 0.9.9 / app v0.9.9 (2026-06-17) | Bump to 0.9.9 (one patch). CRD group kagent.dev/v1alpha2 is still current; no change. |
| LLM Guard (llm-guard-api) | laiyer/llm-guard-api:0.3.16 | 0.3.16 | None. Current. Image namespace still `laiyer/`; no `protectai/` image repo exists. Effectively unmaintained but at latest. |
| Argo CD (chart / app) | chart 9.5.21 / app v3.4.3 | chart 9.6.0 / app v3.4.4 (2026-06-18) | Bump app to v3.4.4. Chart 9.6.0 bundles v3.4.4 plus Gateway API ListenerSet; 9.5.22 bumps app only. Choose per feature need. |
| kube-prometheus-stack (chart / app) | chart 86.2.3 / app v0.91.0 | chart 86.3.2 / app v0.91.0 | Optional minor chart bump to 86.3.2. App (Prometheus Operator) unchanged. |
| OTel Collector (chart / app) | chart 0.158.2 / app 0.153.0 | chart 0.158.2 / app 0.153.0 | None. Current. (Note: VERSIONS.lock "Component versions" block still lists 0.154.0; the gitops pin and "IDP foundation" block at 0.158.2 are correct. Reconcile the stale line.) |
| Tempo (chart / app) | chart 1.24.4 / app 2.9.0 @ grafana.github.io/helm-charts | chart 2.2.3 / app 2.10.7 @ grafana-community/helm-charts | REPOINT REPO. The grafana/helm-charts tempo chart was migrated to grafana-community/helm-charts on 2026-01-30; the old path is now a dead stub. Current pin will stop receiving updates. Also note: Tempo app 3.0 is GA but is tracked by the tempo-distributed chart, not the single-binary chart. |
| Loki (chart / app) | chart 7.0.0 / app 3.6.7 | chart 7.1.0 / app 3.6.8 | Optional minor/patch bump to 7.1.0. Still within the v7 major already absorbed. |
| Grafana Alloy (chart / app) | chart 1.10.0 / app v1.17.0 | chart 1.10.0 / app v1.17.0 | None. Current. |
| cert-manager (dup row) | see above | see above | see above |
| External Secrets Operator (chart / app) | chart 2.6.0 / app v2.6.0 | chart 2.6.0 / app v2.6.0 (2026-06-07) | None. Current. v2.x still serves external-secrets.io/v1; the v1->v2 jump was a renumber, not an API rename. Manifests using external-secrets.io/v1 are safe. |
| Backstage (chart / app) | chart 2.8.2 | chart backstage-2.8.2 / upstream app v1.52.0 | None. Chart current. |
| EKS Kubernetes | 1.35 | Standard support 1.33-1.36; newest/default-recommended 1.36 (EKS 1.36 released 2026-06-02) | Optional. 1.35 is valid on standard support through 2027-03-27. Relabel the pin from "default/newest" to "current standard-support"; 1.36 now holds newest/recommended. |

## Notes

- The agentgateway v1.3.0 GA claim in the repo note is TRUE and confirmed (release 2026-06-18); the v1.2.1 pin in VERSIONS.lock is stale.
- The single largest correctness issue is Tempo: the chart source repository moved.
  A `targetRevision: "1.24.4"` against `https://grafana.github.io/helm-charts` will
  no longer resolve to a maintained chart. This needs a repoURL change, not just a
  version bump.
- External Secrets v1->v2 API safety concern is resolved: no API-group rename
  occurred. The only relevant hard break was the earlier v0.17.0 removal of
  external-secrets.io/v1beta1.
- VERSIONS.lock contains an internal inconsistency for the OTel Collector: the
  "Component versions" block reads v0.154.0 while the gitops pin and "IDP foundation"
  block read 0.158.2. The 0.158.2 pin matches current GA.
