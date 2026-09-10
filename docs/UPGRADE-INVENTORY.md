<!-- ABOUTME: Dated inventory of every pinned component and its latest GA, with the chart-vs-app version -->
<!-- ABOUTME: split called out, so an upgrade targets the APPLICATION version rather than whatever the chart ships. -->
# Upgrade inventory

Measured 2026-09-10 against live sources: Helm repository `index.yaml` files, the GitHub releases API,
PyPI, and `aws eks describe-cluster-versions`. Not from recollection. Re-run `/tmp` vercheck or the
commands in "How this was measured" before acting; these numbers rot.

**The chart version is not the app version.** Several charts number independently of the thing they
install (opentelemetry-collector chart 0.172.1 ships collector 0.159.0; kube-prometheus-stack 90.0.0
ships Prometheus Operator v0.93.1). Where the goal is "latest GA of the software", the appVersion
column is the one that matters, and the image tag can be overridden past whatever the chart pins.

## Helm-managed

| Chart | Pinned | Latest chart | Latest appVersion | Status |
|---|---|---|---|---|
| alloy | 1.10.0 | 1.12.1 | v1.19.2 | behind |
| argo-cd | 9.6.0 | 10.8.4 | v3.5.2 | behind (major) |
| backstage | 2.8.2 | 2.10.0 | - | behind |
| istio base / cni / istiod / ztunnel | 1.30.1 | 1.30.4 | 1.30.4 | behind (patch) |
| cert-manager | v1.20.3 | v1.21.1 | v1.21.1 | behind |
| datadog-operator | 2.23.2 | 2.26.0 | 1.30.0 | behind |
| external-secrets | 2.6.0 | 2.10.0 | v2.10.0 | behind |
| falco | 9.1.0 | 9.1.0 | 0.44.1 | current |
| falco-talon | 0.4.1 | 0.4.2 | 0.3.0 | behind (patch) |
| falcosidekick | 0.14.0 | 0.14.0 | 2.31.1 | current |
| kube-prometheus-stack | 86.2.3 | 90.0.0 | v0.93.1 | behind (4 majors) |
| kubearmor-operator | 1.7.4 | v1.7.4 | v1.7.4 | current |
| kyverno | 3.9.0 | 3.9.1 | v1.19.1 | behind (patch) |
| loki | 7.0.0 | 7.3.0 | 3.6.12 | behind |
| opentelemetry-collector | 0.158.2 | 0.172.1 | 0.159.0 | behind |
| opentelemetry-operator | 0.117.0 | 0.122.0 | 0.158.0 | behind |
| tempo | 2.2.3 | see note | 2.9.0 | UNVERIFIED |

`tempo` is pinned from `grafana-community.github.io`; the index queried was `grafana.github.io`, so its
row is not a like-for-like comparison. Verify against the repo the Application actually names before
acting on it.

## Not Helm-managed

| Component | Pinned | Latest GA | Source |
|---|---|---|---|
| kagent / kagent-crds | 0.9.9 | **0.10.1** (2026-09-08) | GitHub releases |
| agentgateway | v1.3.0 | **v1.5.0** (2026-08-27) | GitHub releases |
| LLM Guard | 0.3.16 | 0.3.16 | PyPI, already current |
| EKS control plane | 1.35 | **1.36** available | `aws eks describe-cluster-versions` |
| autoinstrumentation-python | 0.63b1 | check upstream | not yet measured |
| Our own images (web-terminal, workshop-mcp, sample-app) | rolling | base images: debian bookworm-slim, python 3.12-slim | rebuild to pick up CVE fixes |

**agentgateway has two version lines.** Releases are v1.x, but the Kubernetes documentation is served
under a `2.2.x` path. Those were not reconciled here; do not assume v1.5.0 and "2.2.x" refer to the same
thing until the distribution question is settled.

## How this was measured

```bash
# charts: pull the repo index and take the highest non-prerelease entry, with its appVersion
curl -s <repo>/index.yaml | yq '.entries.<chart>[0] | {version, appVersion}'
# releases
curl -s https://api.github.com/repos/<org>/<repo>/releases/latest | jq -r .tag_name
# eks
aws eks describe-cluster-versions --region us-west-2 \
  --query 'clusterVersions[?status==`STANDARD_SUPPORT`].clusterVersion'
```
