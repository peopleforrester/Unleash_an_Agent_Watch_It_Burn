<!-- ABOUTME: Hybrid Datadog Agent + OTel Collector implementation spec, per-node sizing budget, and -->
<!-- ABOUTME: attendee-Datadog-at-scale design for the Watch-It-Burn workshop. Build-facing. -->

# 24. Datadog Hybrid Implementation + Node Sizing (build spec)

## Verification Method

- **Approach:** Web research dated 2026-06-21, plus direct reads of the live repo at
  `/home/michael/repos/events/Unleash_an_Agent_Watch_It_Burn`. Every external resource-default,
  annotation shape, instance spec, T3 credit behavior, and Datadog recommendation below is cited
  to a primary source (Datadog docs, AWS EC2 docs, the Datadog/Falco Helm chart values, AWS
  instance pages). Repo facts (current instance pins, the OTel Collector exporters, the
  per-component resource requests already in the manifests, the `datadog-secret` consumption) are
  read directly from files and marked CONFIRMED in-repo. Items needing a live cluster are marked
  UNCERTAIN and pushed to the verify-at-build checklist.
- **Companion spikes:** `research/23-observability-decision-points-2026.md` (the hybrid/swappable
  decision this doc implements), `research/05-otel-genai-observability.md` (GenAI semconv),
  `infra/SIZING.md` (the measure-then-pin rule, LLM Guard footprint, linear-in-N cost).
- **Primary sources used (full list at the end of each section):** Datadog Helm chart
  `values.yaml`, Datadog OTel/DDOT docs, Datadog hostname-mapping docs, Datadog ArgoCD /
  cert-manager / Kyverno integration docs, Falco Helm chart `values.yaml`, AWS EC2 burstable
  (T3 credit) docs, AWS M6i/M7i instance pages.

## The principle this implements (restated)

**HYBRID and SWAPPABLE.** The OpenTelemetry Collector (DaemonSet, contrib `0.158.2`, Datadog
exporter primary + `prometheusremotewrite` + `otlp/tempo` fallback) stays the **neutral
instrumentation layer**. We ADD a Datadog Agent DaemonSet **for EKS infra auto-discovery and
named integrations only**. Datadog must stay removable: deleting the Datadog exporter from the
Collector and disabling the Datadog Agent app leaves a fully working OSS stack
(OTel -> Prometheus/Grafana/Tempo). Datadog is **additive, never load-bearing**. Whitney owns the
Datadog account, API/app keys, the Agent install, and dashboards; we own the OTel-side wiring
(done), the manifest annotations, and consuming `datadog-secret`.

## Cluster topology is UNDER REVIEW (read before the sizing section)

The earlier hub-and-spoke model (central ArgoCD on a hub managing per-attendee spokes) is **no
longer assumed**. The likely model is **independent per-student clusters**: each student gets their
own **standalone** Kubernetes cluster from the ground up, take-home, with **no central ArgoCD
managing them**. This doc sizes for that standalone case. Concretely:

- "Spoke" / "hub" language below is retained only where it quotes existing repo files; the sizing
  recommendation is framed for **one standalone full-stack cluster**, replicated ~60-70 times.
- With no hub, there is **no central ArgoCD to size**, and the **ArgoCD named-integration
  annotations (section 1.3) apply only if a per-student cluster runs its own ArgoCD** (or are moot
  if students apply manifests directly). Everything else in the Datadog implementation and the
  attendee-account sections is **unaffected** by topology.
- The Datadog Agent footprint is computed **per standalone cluster** (one node Agent DaemonSet +
  one Cluster Agent per cluster), which is identical to the per-spoke footprint; the change is
  framing, not numbers.

---

# 1. HYBRID IMPLEMENTATION SPEC (our side)

## 1.1 Datadog Agent install shape: standalone Agent ALONGSIDE OTel, not DDOT

Two candidate shapes:

- **Standalone Datadog Agent DaemonSet next to our existing OTel Collector** (the node Agent does
  infra/host/container metrics + container logs + named integrations; the OTel Collector keeps
  doing OTLP app traces/metrics/logs + spanmetrics).
- **DDOT** = the Datadog Distribution of the OTel Collector, an OTel Collector **embedded inside
  the Datadog Agent (v7.65+)**, enabled by one flag and deployable as a DaemonSet. Datadog calls
  DDOT "the recommended approach" for OTel-to-Datadog and offers Fleet Automation to manage it
  ([Datadog DDOT blog, 2025](https://www.datadoghq.com/blog/datadog-distribution-otel-collector/);
  [DDOT Collector docs](https://docs.datadoghq.com/opentelemetry/setup/ddot_collector/);
  [Install DDOT as a DaemonSet](https://docs.datadoghq.com/opentelemetry/setup/ddot_collector/install/)).

**The tradeoff.** DDOT collapses "two DaemonSets" into one Agent that embeds a curated Collector,
which is operationally tidy. But DDOT makes the *node collector itself a Datadog-distributed
binary*. If DDOT is the only collector, "remove Datadog in one line" is no longer true: the OTLP
ingest path is now inside the Datadog Agent, and ripping Datadog out means re-standing-up a
neutral Collector. That directly fights the swappable principle. Running DDOT *and* our contrib
Collector means two collectors on every node, which is worse on footprint at 60-70 clusters and
buys nothing.

**Recommendation (CONFIRMED design choice, consistent with research/23 Decision 1).**

- **Every standalone full-stack cluster:** keep the **standalone contrib OTel Collector as the neutral
  layer**, and run the **standalone Datadog Agent DaemonSet alongside it for infra only**. This
  preserves one-line swappability: the Collector's `datadog` exporter is one of three sinks, and
  the Datadog Agent is a separate ArgoCD app gated behind a flag (`datadog.agent.enabled`). Remove
  both seams -> OSS stack still works.
- **DDOT is acceptable ONLY on the facilitator/instructor cluster (instructor Cluster 3)** if
  Whitney wants the richest single-agent Datadog demo there, because C3 is not part of the
  swappable per-attendee fleet and is the on-stage model-tier comparison node. Even there it is
  optional; the standalone-alongside shape works on C3 too.
- Do **not** make DDOT the fleet-wide collector. Do not adopt full Datadog.

## 1.2 Coexistence rules (Agent + OTel Collector on the same node)

The two collectors must not double-count or duplicate the host. Rules:

1. **`datadog.prometheusScrape.enabled` stays `false`.** Prometheus-format app metrics are already
   scraped/ingested through the OTel pipeline (and the guard-proxy `/metrics` is consumed by our
   Prometheus). Turning on Datadog's cluster-wide Prometheus autoscrape would double-collect those
   series and inflate custom-metric billing. The Datadog Agent's Prometheus/OpenMetrics scraping
   is opt-in per workload via Autodiscovery annotations (section 1.3), which is the targeted path
   we want, not a blanket scrape
   ([Kubernetes Prometheus and OpenMetrics collection](https://docs.datadoghq.com/containers/kubernetes/prometheus/);
   [Kubernetes and Integrations](https://docs.datadoghq.com/containers/kubernetes/integrations/)).

2. **Hostname alignment via `k8s.node.name` (+ cluster name) so Datadog sees ONE host, not two.**
   When a host is ingested by both the Datadog Agent and an OTLP path without an aligned hostname,
   Datadog lists it twice (one entry with the OTel logo, one from the Agent). The Datadog exporter
   computes the Kubernetes hostname as **`<k8s.node.name>-<cluster name>`** when both are present,
   or the node name alone if only `k8s.node.name` is present; cluster name comes from
   `k8s.cluster.name` first
   ([Mapping OTel semconv to hostnames](https://docs.datadoghq.com/opentelemetry/mapping/hostname/);
   [Hostname and Tagging](https://docs.datadoghq.com/opentelemetry/collector_exporter/hostname_tagging/)).
   **Action:** ensure the OTel Collector resource attributes carry `k8s.node.name` and
   `k8s.cluster.name` (via `k8sattributes` + `resourcedetection` processors), and set the Datadog
   Agent's cluster name to the same value, so both paths resolve to the identical host string. The
   repo already upserts `cluster.name=watch-it-burn` in the Collector `resource` processor; the
   missing piece is `k8s.node.name` on the host-identifying telemetry and a matching
   `clusterName`/`DD_CLUSTER_NAME` on the Agent. UNCERTAIN until verified live that the resulting
   host strings match exactly.

3. **Ownership split (who emits what):**
   - **Datadog Agent (node DaemonSet + Cluster Agent):** node/infra metrics, container metrics,
     kube-state/control-plane metrics, container/pod logs, live container view, and the
     **named integrations** via Autodiscovery (section 1.3).
   - **OTel Collector (DaemonSet):** OTLP **app/agent traces, metrics, logs** (GenAI semconv),
     the guard-proxy RED/cost metrics, and **spanmetrics** (the `spanmetrics` connector already in
     the manifest). App telemetry never goes through the Datadog Agent; infra telemetry never goes
     through the Collector. No overlap -> no duplication.
   This split is the standard "Agent for infra, Collector for OTLP" coexistence pattern
   ([OpenTelemetry in Datadog](https://docs.datadoghq.com/opentelemetry/);
   [Datadog Agent OTLP/OTel setup](https://docs.datadoghq.com/opentelemetry/setup/agent/)).

4. **One API key, two consumers.** Both the Collector's `datadog` exporter and the Datadog Agent
   read the same `datadog-secret` (key `api-key`) and the same `DD_SITE`. No second key.

## 1.3 Named-integration pod annotations to pre-bake

Pre-baking Autodiscovery annotations on our platform components means every attendee gets the
named Datadog integration "for free" the moment the Datadog Agent is enabled, with zero attendee
action. Datadog Autodiscovery v2 (Agent v7.36+) uses a single
`ad.datadoghq.com/<container-name>.checks` annotation whose value is a JSON object keyed by the
check name; v1 splits it across `.check_names` / `.init_configs` / `.instances`
([Kubernetes and Integrations](https://docs.datadoghq.com/containers/kubernetes/integrations/);
[Basic Agent Autodiscovery](https://docs.datadoghq.com/getting_started/containers/autodiscovery/)).
`%%host%%` is the Autodiscovery template variable for the container IP.

The named-integration components in our stack and their exact annotation shapes:

### ArgoCD (hub): named `argocd` integration

ArgoCD ships a dedicated Datadog check with per-component endpoint keys (NOT a generic
`openmetrics_endpoint`). Annotate each ArgoCD component pod with its own container-name key
([Datadog ArgoCD integration](https://docs.datadoghq.com/integrations/argocd/);
[Monitor ArgoCD with Datadog](https://www.datadoghq.com/blog/argo-cd-datadog/)):

```yaml
# application-controller pod
ad.datadoghq.com/argocd-application-controller.checks: |
  {"argocd": {"init_config": {}, "instances": [{"app_controller_endpoint": "http://%%host%%:8082/metrics"}]}}
# api server pod
ad.datadoghq.com/argocd-server.checks: |
  {"argocd": {"init_config": {}, "instances": [{"api_server_endpoint": "http://%%host%%:8083/metrics"}]}}
# repo server pod
ad.datadoghq.com/argocd-repo-server.checks: |
  {"argocd": {"init_config": {}, "instances": [{"repo_server_endpoint": "http://%%host%%:8084/metrics"}]}}
```

These go on the **hub** (ArgoCD runs once on the hub). The Datadog Agent must be present on the hub
to consume them; if Datadog is enabled only on student clusters, ArgoCD metrics route via the OSS Prometheus
path instead and these annotations are simply inert.

### cert-manager: named `cert_manager` integration

cert-manager exposes Prometheus metrics on port **9402**. Datadog's cert-manager integration is in
the Agent package; annotate the controller pod
([Datadog cert-manager integration](https://docs.datadoghq.com/integrations/cert-manager/)):

```yaml
ad.datadoghq.com/cert-manager.checks: |
  {"cert_manager": {"init_config": {}, "instances": [{"openmetrics_endpoint": "http://%%host%%:9402/metrics"}]}}
```

(`cert-manager` is the container name in the controller pod; adjust if our chart names it
differently. The legacy v1 form is
`ad.datadoghq.com/cert-manager.check_names: '["cert_manager"]'` +
`.init_configs: '[{}]'` + `.instances` with the same `openmetrics_endpoint`.)

### Kyverno: named `kyverno` integration

Each Kyverno controller exposes Prometheus metrics on **port 8000** at `/metrics`. Datadog ships a
`kyverno` check ([Datadog Kyverno integration](https://docs.datadoghq.com/integrations/kyverno/);
[Kyverno monitoring docs](https://kyverno.io/docs/monitoring/);
[integrations-core/kyverno](https://github.com/DataDog/integrations-core/tree/master/kyverno)):

```yaml
ad.datadoghq.com/kyverno.checks: |
  {"kyverno": {"init_config": {}, "instances": [{"openmetrics_endpoint": "http://%%host%%:8000/metrics"}]}}
```

Annotate each Kyverno controller pod (admission, background, cleanup, reports) that exposes
`/metrics`. Confirm the container name per the pinned Kyverno chart at build.

### Falco: via falcosidekick -> Datadog output (already wired), not a pod-annotation check

Falco has **no `ad.datadoghq.com` check that the node Agent scrapes**; the supported "Falco events
in Datadog" path is the **falcosidekick `datadog` output**, which the repo already configures
(`gitops/apps/falcosidekick.yaml`: `config.datadog.minimumpriority: notice` + `DATADOG_APIKEY`
from `datadog-secret`, `DATADOG_HOST` per site). That is the correct shape; no annotation is
needed for Falco itself. (CONFIRMED in-repo.) If raw Falco *Prometheus metrics* are also wanted in
Datadog, that is an OpenMetrics scrape of falcosidekick's `:2801/metrics` (already annotated for
the OSS Prometheus via `prometheus.io/scrape`), addable as an `ad.datadoghq.com/...checks`
openmetrics instance, but the event feed is the primary Datadog story.

**Swappability note:** all of the above annotations are inert when the Datadog Agent is absent.
They cost nothing and break nothing in the OSS-only configuration, so pre-baking them is safe.

## 1.4 IRSA / IAM, and where the `datadog-secret` must live

Two distinct IAM concerns that are easy to conflate:

1. **The Datadog EKS + CloudWatch integration is a Datadog-account-side cross-account IAM role,
   NOT an IRSA role on our node Agent.** Datadog pulls CloudWatch metrics by assuming a read-only
   IAM role in the AWS account (created via Datadog's CloudFormation template / STS AssumeRole).
   For the in-cluster Agent itself, "you don't need any specific configuration for EKS" beyond the
   standard Kubernetes Agent install; if the Agent add-on needs AWS API access, EKS **Pod Identity
   is the recommended option** (or IRSA)
   ([Getting Started with AWS](https://docs.datadoghq.com/getting_started/integrations/aws/);
   [AWS integration](https://docs.datadoghq.com/integrations/amazon-web-services/);
   [Kubernetes distributions](https://docs.datadoghq.com/containers/kubernetes/distributions/)).
   **Boundary:** the CloudWatch cross-account role and CloudFormation install are **Whitney's**
   (her Datadog org drives it). At 60-70 separate attendee orgs the EKS+CloudWatch integration is
   almost certainly NOT worth wiring per attendee; treat it as optional and facilitator-only
   (instructor C3 / hub) if used at all. UNCERTAIN whether Whitney wants CloudWatch metrics in the
   demo at all; confirm with her.

2. **The `datadog-secret` (key `api-key`) must exist in every namespace that reads it.** Today two
   consumers need it (CONFIRMED in-repo):
   - `monitoring` namespace -> the OTel Collector's `datadog` exporter
     (`gitops/apps/otel-collector.yaml`, `extraEnvs.DD_API_KEY` from `datadog-secret`).
   - `security` namespace -> falcosidekick's `DATADOG_APIKEY`
     (`gitops/apps/falcosidekick.yaml`).
   Adding the Datadog Agent adds a third consumer in the Agent's namespace (e.g. `datadog`).

   **Recommendation: sync with External Secrets Operator (ESO), do NOT hand-create per namespace.**
   The repo already runs ESO with IRSA to read AWS Secrets Manager
   (`gitops/apps/external-secrets.yaml`). Define one `ExternalSecret` per consuming namespace
   (`monitoring`, `security`, `datadog`) that materializes `datadog-secret` (key `api-key`, plus
   the site) from a single SM entry. Reasons:
   - One source of truth; rotating the key in SM repopulates all namespaces.
   - It is the same mechanism already used in the stack (no new tool).
   - At fleet scale, the per-attendee key is injected once into SM by the provisioning pipeline and
     fanned out by ESO (section 3), so no manual `kubectl create secret` per namespace per cluster.
   Per-namespace `kubectl create secret` is acceptable only for a single throwaway test cluster;
   it does not scale to 60-70 clusters and is not swappable-clean.

---

# 2. NODE SIZING / PER-NODE RESOURCE BUDGET

## 2.1 Current pins (CONFIRMED in-repo)

These reflect the earlier hub-and-spoke repo state and predate the topology review; they are the
starting point to revise, not a constraint. The standalone-cluster recommendation is in section 2.4.

| Role | File | Instance | vCPU / RAM | Nodes |
|---|---|---|---|---|
| Hub | `infra/hub-cluster/cluster.yaml` | `m6i.large` | 2 / 8 GiB | 2 (max 3) |
| Spoke (per attendee) | `infra/spoke-cluster/cluster.yaml` | `m6i.xlarge` | 4 / 16 GiB | 1 (max 2) |
| Burn C1 / C2 / instructor C3 | `infra/burn-clusters/cluster.yaml` | `t3.large` | 2 / 8 GiB | 2 (max 3) |
| Test | `infra/test-cluster/cluster.yaml` | `t3.large` | 2 / 8 GiB | 2 (max 3) |

Instance specs (CONFIRMED): `m6i.large` 2 vCPU/8 GiB, `m6i.xlarge` 4 vCPU/16 GiB, `m6i.2xlarge`
8 vCPU/32 GiB, `m7i.2xlarge` 8 vCPU/32 GiB
([M6i](https://aws.amazon.com/ec2/instance-types/m6i/),
[M7i](https://aws.amazon.com/ec2/instance-types/m7i/),
[EC2 general purpose specs](https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html)).
M7i = 4th-gen Xeon + DDR5, ~15% better price/performance than M6i, same vCPU/RAM at a given size.

## 2.2 Per-cluster resource-REQUESTS budget (one standalone full-stack node)

Requests below are from the repo manifests where present (CONFIRMED in-repo), and from upstream
chart defaults where the component is chart-managed (cited). The Datadog Agent row is the **new**
line item this spike adds.

| Component | CPU req | Mem req | Source |
|---|---:|---:|---|
| OTel Collector (DaemonSet) | 100m | 256Mi | repo `otel-collector.yaml` |
| Datadog Agent node DaemonSet (NEW) | see note | see note | chart default is **empty** (see 2.3) |
| Datadog Cluster Agent (NEW, 1 per cluster) | see note | see note | chart default is **empty** (see 2.3) |
| Falco (DaemonSet, modern eBPF) | 100m | 256Mi (repo) / 512Mi (chart default) | repo `falco.yaml`; [Falco chart values](https://github.com/falcosecurity/charts/blob/master/charts/falco/values.yaml) |
| falcosidekick (x2 replicas) | 50m x2 = 100m | 64Mi x2 = 128Mi | repo `falcosidekick.yaml` |
| Falco Talon | 50m | 64Mi | repo `falco-talon.yaml` |
| Kyverno (admission/background/cleanup/reports controllers) | ~250m total | ~512Mi total | repo `kyverno.yaml` (50-100m + 128-256Mi each) |
| Istio istiod (ambient) | 100m | 256Mi | repo `istio.yaml` |
| Istio ztunnel (DaemonSet) | chart default | chart default | repo sets `valuesObject: {}` -> upstream default; UNCERTAIN exact, budget ~100m/256Mi |
| cert-manager (controller + webhook + cainjector) | ~150m total | ~192Mi total | repo `cert-manager.yaml` (50m/64Mi base) |
| External Secrets Operator | 50m | 128Mi | repo `external-secrets.yaml` |
| kagent controller + agent | chart-managed (0.9.9) | chart-managed | repo `kagent.yaml`; UNCERTAIN exact, budget ~250m/512Mi |
| kagent Postgres | chart-managed | chart-managed | UNCERTAIN exact, budget ~100m/256Mi |
| agentgateway (v1.3.0) | chart/manifest-managed | n/a | UNCERTAIN exact, budget ~100m/128Mi |
| guard-proxy | 50m | 64Mi | repo `ai-layer/resources.yaml` |
| LLM Guard (Regex-only default) | 250m | 1Gi (limit 3Gi) | repo `ai-layer/resources.yaml` |
| evil-mcp-shim | 25m | 32Mi | repo `ai-layer/resources.yaml` |
| customer-stream (x2 containers) | 50m | 96Mi | repo `customer-stream/stream.yaml` |
| chat-ui | 25m | 32Mi | repo `ai-layer/resources.yaml` |
| **Subtotal (excluding Datadog Agent + chart-unknowns budgeted)** | **~1.5-1.8 vCPU** | **~3.5-4.5 GiB** | sum of above |

### What the Datadog Agent adds (the load-bearing new number)

**The Datadog Helm chart sets NO default resource requests** for the node Agent or the Cluster
Agent: `clusterAgent.resources` is `{}` and the per-container `agents.containers.*.resources`
blocks are commented-out examples, not defaults
([Datadog chart values.yaml](https://github.com/DataDog/helm-charts/blob/main/charts/datadog/values.yaml)).
This is a trap: with no requests set, the Agent is `BestEffort` and will pack onto the node and
compete with workloads under pressure. We must SET requests explicitly. Datadog's own GKE
Autopilot guidance gives realistic per-container numbers
([Set up the Cluster Agent](https://docs.datadoghq.com/containers/cluster_agent/setup/);
GKE Autopilot recommended requests):

| Datadog container | CPU req (set this) | Mem req (set this) |
|---|---:|---:|
| node Agent (`agent`) | 200m | 256Mi |
| Trace Agent (APM) | 100m | 200Mi |
| Process Agent | 100m | 200Mi |
| System Probe (if eBPF/NPM enabled) | 100m | 400Mi |
| **Cluster Agent** (1 per cluster) | 200m | 256Mi |

For infra-only on a standalone cluster we do NOT need APM (the OTel Collector owns traces), and we
likely do NOT need System Probe (no NPM/USM). A lean infra-only Datadog Agent is roughly **node
Agent 200m / 256Mi + Process Agent 100m / 200Mi + a Cluster Agent 200m / 256Mi ≈ 500m CPU /
~700Mi RAM** per cluster. Enabling logs collection and APM pushes this up; keep them off on the
Agent (the Collector handles app logs/traces).

### Summing it up for one standalone cluster

- **Total requests (full stack + lean infra-only Datadog Agent): ~2.0-2.3 vCPU and ~4.5-5.5 GiB.**
- Add EKS system overhead per node (kubelet, `vpc-cni` / `aws-node`, `kube-proxy`, CoreDNS if
  scheduled, CSI node driver, the OTel + Falco + ztunnel + Datadog **eBPF** agents' kernel-side
  cost): realistically another ~0.5-1.0 vCPU and ~1-2 GiB of *actual usage* beyond requests.
- **The requests fit a 4 vCPU / 16 GiB node** (e.g. `t3.xlarge` or `m6i.xlarge`) in Regex-only LLM
  Guard mode, with roughly half the node free on requests. RAM is comfortable; the open question is
  **sustained CPU**, which is the only reason instance *family* (burstable T3 vs fixed M) matters
  (section 2.3). It does NOT need 8 vCPU / 32 GiB on the request math.
- **It does NOT fit comfortably if `Sensitive` NER is turned on.** The LLM Guard API server wants
  **>=16 GiB alone** with model-backed scanners loaded (per `infra/SIZING.md` / research), which
  by itself consumes a 16 GiB node. If a cluster opts into `Sensitive`, that single cluster needs
  8/32 (`t3.2xlarge` or `m6i.2xlarge`) and should be recorded, exactly as `SIZING.md` states. The
  `PromptInjection` input scanner (DeBERTa classifier) carries its own footprint where the input
  guard runs and is separate from the Regex default.

UNCERTAIN: the chart-managed rows (kagent + Postgres, agentgateway, ztunnel) are budgeted, not
measured. This is exactly why the measure-then-pin rule applies: **measure one live cluster with
`kubectl top` before pinning the fleet** (section 2.4).

## 2.3 T3 burstable: the right starting default for a 2-hour intermittent lab

**This is a ~2-hour lab with intermittent engagement, not a production service.** The workload is
bursty by nature: a student reads, types a prompt, watches an attack fire, reads the Datadog/OTel
output, then sits idle. That idle time is exactly what a burstable T3 is designed to bank as
credits and spend on the next burst. **Default to T3; do NOT start on fixed M-series.** Treat
m6i/m7i as a *measured fallback* if a real test shows credits actually choke.

How the T3 credit mechanic works (CONFIRMED from AWS docs). T3 has a **baseline** CPU level; it
earns credits below baseline and spends them above. T3 baselines per vCPU
([AWS burstable concepts](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html)):

| Instance | vCPU | Baseline / vCPU | Whole-instance baseline | Credits earned/hr | Max accrued |
|---|---:|---:|---:|---:|---:|
| t3.large | 2 | 30% | ~0.6 vCPU | 36 | 864 |
| t3.xlarge | 4 | 40% | ~1.6 vCPU | 96 | 2304 |
| t3.2xlarge | 8 | 40% | ~3.2 vCPU | 192 | 4608 |

Why a `t3.xlarge` is a sound starting point here: the full-stack request math is ~2.0-2.3 vCPU
(section 2.2), but those are *requests* (reservations), not sustained draw. Steady-state draw on an
idle-between-bursts lab cluster sits well below that. A `t3.xlarge` has a **~1.6 vCPU baseline**
(it earns enough credits to run at 1.6 vCPU forever for free) **plus** up to 2304 accrued credits
to burst the remaining ~2.4 vCPU during the active beats. Over a 2-hour session with intermittent
load, a cluster that idles below baseline between beats keeps refilling the bucket. The eBPF agents
(Falco + ztunnel + Datadog) and intermittent LLM inference are real CPU, but they are not a
sustained pin at full node CPU for the whole 2 hours.

Two facts to track, not fear:
- **Default credit mode is `unlimited` for T3** ([AWS burstable concepts](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html)).
  In unlimited mode the node does **not** throttle when accrued credits run out; it spends surplus
  credits and AWS bills a flat extra per-vCPU-hour only if the **24h average** exceeds baseline
  ([Unlimited mode](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode.html)).
  For a 2-hour cluster, even a worst-case surplus overage is small (it is per-vCPU-hour over a
  2-hour life, not a 24-hour average sustained at peak), and there is no mid-demo throttle.
- **Standard mode** is the only mode that throttles to baseline on credit exhaustion. If you
  explicitly want a hard cost ceiling (no surplus billing), set Standard mode and accept that a
  pathological sustained-CPU cluster could throttle. For this lab, leaving the default unlimited
  mode is the safer choice for the live experience.

So: **start on T3, watch `CPUCreditBalance` and `CPUSurplusCreditBalance` in CloudWatch during a
real run.** If credits actually deplete and the node would throttle (Standard) or surplus billing
becomes material (unlimited), THEN move that role to fixed M-series. Do not pre-pay for fixed
performance you have not shown you need.

### Cost delta (why not "just go bigger"): real numbers

On-demand hourly, us-west-2-class pricing (CONFIRMED, [EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/);
[Vantage t3.xlarge](https://instances.vantage.sh/aws/ec2/t3.xlarge),
[Vantage m6i.xlarge](https://instances.vantage.sh/aws/ec2/m6i.xlarge),
[Vantage m6i.2xlarge](https://instances.vantage.sh/aws/ec2/m6i.2xlarge)). One node per cluster:

| Instance | vCPU/RAM | On-demand $/hr | x1 node x 3 hr | x60 clusters x 3 hr | vs t3.xlarge |
|---|---|---:|---:|---:|---:|
| **t3.xlarge** | 4/16 | ~$0.1664 | ~$0.50 | **~$29.95** | baseline |
| m6i.xlarge | 4/16 | ~$0.192 | ~$0.58 | ~$34.56 | +$4.61 (+15%) |
| m6i.2xlarge | 8/32 | ~$0.384 | ~$1.15 | ~$69.12 | +$39.17 (+131%) |
| t3.2xlarge | 8/32 | ~$0.3328 | ~$1.00 | ~$59.90 | +$29.95 (+100%) |

Notes: figures are **compute only** (one node per cluster, ~3-hour window covering setup + the
2-hour lab + teardown), excluding the per-cluster EKS control-plane charge (~$0.10/hr each, which
is identical regardless of node type) and EBS/NAT. The point: moving the fleet from `t3.xlarge` to
`m6i.xlarge` costs only **~$5 more across 60 clusters for 3 hours**, so if a real test shows T3
credits choke, the M-series fallback is cheap and you should just take it. But jumping straight to
**8/32 (`m6i.2xlarge`) more than doubles the bill (~+$39) for RAM the Regex-only budget does not
use**, which is the upgrade to resist without a measurement. Burstable `unlimited`-mode surplus on
T3 is bounded by the short 2-3 hour cluster life and lands far below the m6i.2xlarge delta even in
a heavy-burst worst case. (UNCERTAIN: exact surplus depends on real CPU profile; the
measure-one-cluster step quantifies it.)

## 2.4 Per-role recommendation (standalone-cluster model)

Framed for **independent per-student standalone clusters** (no hub/spoke). "Start" = the
conservative default to provision; "fallback" = move here only if a measured run shows it is
needed.

| Role | Start with | Fallback (only if measured) | Why |
|---|---|---|---|
| **Per-student standalone cluster (full stack, Regex-only)** | `t3.xlarge` (4/16) | `m6i.xlarge` (4/16) | Request math fits 4/16; bursty 2-hr lab is the textbook T3 case. M-series fallback is only ~+15% (~$5/fleet/3hr) if credits choke. |
| **Student cluster that opts into `Sensitive` NER** | `t3.2xlarge` (8/32) | `m6i.2xlarge`/`m7i.2xlarge` (8/32) | NER wants >=16 GiB alone; 8/32 needed for RAM, not CPU. Still start burstable. |
| **Instructor cluster (full stack + Opus-tier model comparison)** | `t3.xlarge` (4/16) | `m6i.xlarge`, or `m6i.2xlarge`/`m7i.2xlarge` if sustained Opus load shows it | One cluster, on stage, presenter-driven. Start T3; the instructor cluster is the single best candidate to *measure first* and upgrade to fixed-perf if Opus round-trips pin CPU. Cost of upgrading one node is trivial. |
| **Any deliberately-light / disposable demo cluster** | `t3.large` (2/8) | n/a | Not the full stack; burstable is plenty. |

**Cost is linear in N** (per-cluster EKS control-plane + one node + overhead). The cost-delta table
above shows the fleet-wide dollar impact of each upgrade, so the trade-off is explicit. **Keep the
measure-then-pin rule:** measure **one live cluster** under a real ~2-hour intermittent run with
`kubectl top nodes` / `kubectl top pods` **and** the CloudWatch `CPUCreditBalance` /
`CPUSurplusCreditBalance` metrics, THEN pin the fleet instance type from that measurement. Do not
blanket-upgrade to fixed M-series or to 8/32 before that one measured run.

---

# 3. ATTENDEE DATADOG ACCOUNTS AT SCALE (~60-70 orgs)

## 3.1 The shape of the problem

~60-70 attendees, each with their **own Datadog org**, so each cluster needs its **own** API key
(and possibly app key + site). Whitney owns provisioning the orgs and keys; we own consuming them
automatically per cluster. The risk is manual key handling at 60-70x: it does not scale, it leaks,
and it is not swappable-clean.

## 3.2 Boundary: what Whitney provides vs what we consume

**Whitney owns (provides):**
- 60-70 Datadog orgs (or one org with 60-70 keyed scopes, if she prefers; see options).
- Per attendee: a **Datadog API key** (`datadogApiKey`), the **site** (`DD_SITE`, e.g.
  `datadoghq.com`, `us5.datadoghq.com`, `datadoghq.eu`), and **only if app-level API calls are
  needed** an **app key** (`datadogAppKey`). For ingest (OTel exporter, falcosidekick, Agent) the
  **API key + site are sufficient**; app keys are for dashboard/monitor API automation, which is
  Whitney's tooling, not the spoke's ingest path.
- A machine-readable mapping of `attendee_id -> {api_key, app_key, site}` delivered into a single
  secure store we agree on (see options).
- The dashboards (built once, per org or templated).

**We own (consume):**
- The `datadog-secret` (key `api-key`, plus the site value) materialized in each consuming
  namespace of each standalone cluster (`monitoring`, `security`, and `datadog` if the Agent is enabled).
- The ESO `ExternalSecret`/`ClusterSecretStore` wiring that pulls the right attendee's key into the
  right cluster automatically.
- The OTel exporter, falcosidekick output, and Datadog Agent that read it (already wired for the
  first two).

## 3.3 Options for getting Whitney's keys into each cluster

- **Option A (RECOMMENDED): provisioning pipeline writes per-attendee key into AWS Secrets
  Manager; ESO syncs it into the cluster.** Whitney hands us the `attendee_id -> key/site` map once. The
  cluster-provisioning pipeline (the same `envsubst`/loop that stamps `ATTENDEE_ID` into the eksctl
  template) writes `watch-it-burn/<attendee_id>/datadog` into AWS Secrets Manager. Each cluster's ESO
  (already present, IRSA-scoped) has one `ExternalSecret` per consuming namespace that reads that
  attendee's SM path and materializes `datadog-secret`. Reasons: reuses the ESO mechanism already
  in the stack; one secure store; key never lands in git or in a manifest; rotation = update SM;
  swappable (delete the `ExternalSecret`s and the Datadog exporter/agent, OSS stack still runs).
  IRSA on each cluster's ESO must be scoped to **that attendee's** SM path only (least privilege),
  which the provisioning step sets per cluster.
- **Option B: pipeline `kubectl create secret` per namespace per spoke at provision time.**
  Simpler to reason about, no ESO dependency, but the key transits the provisioning host and CI
  logs more readily, rotation means re-running the loop, and it is N x 3 imperative secret
  creates. Acceptable as a fallback if ESO-per-cluster proves heavy, but not the default.
- **Option C: one shared Datadog org for the whole room, one key.** Operationally trivial (one
  `datadog-secret` value fanned out everywhere), but it defeats the per-attendee-org goal: every
  attendee sees everyone's telemetry, and Whitney's "each attendee owns their data" story breaks.
  Only viable if the per-attendee-org requirement is relaxed. Note billing: custom metrics +
  ingested spans/logs from 60-70 full stacks into ONE org could be a material Datadog bill;
  per-org spreads (or isolates) that. Flag to Whitney.

**Recommendation: Option A.** It is the only one that is simultaneously per-attendee-isolated,
non-leaking, rotation-friendly, and swappable, and it reuses ESO which is already in the stack. Its
one prerequisite is that Whitney delivers the `attendee_id -> key/site` map into a store our
pipeline can write to (or that she writes directly into AWS Secrets Manager under the agreed path
prefix). Settle the delivery format (CSV/JSON map vs Whitney-writes-SM-directly) with her before
provisioning.

UNCERTAIN until confirmed with Whitney: whether attendees truly each get a separate org (drives
Option A vs C), whether app keys are needed at all (ingest does not need them), and whether the
EKS+CloudWatch cross-account integration is in scope per attendee (almost certainly not; keep it
facilitator-only).

---

## Decisions / recommendations

0. **Topology under review:** size for **independent per-student standalone clusters** (no central
   ArgoCD hub). The Datadog implementation and attendee-account sections are topology-independent;
   only the sizing framing changes (per-cluster, not per-spoke), and ArgoCD annotations apply only
   on a per-student cluster that runs its own ArgoCD.
1. **Hybrid shape:** standalone OTel Collector (neutral) + standalone Datadog Agent DaemonSet
   (infra only), gated behind a flag. **Do not** make DDOT the fleet collector; DDOT only
   optionally on the instructor cluster. Preserves one-line Datadog removal.
2. **Coexistence:** `datadog.prometheusScrape.enabled=false`; align hostname via
   `k8s.node.name` + `k8s.cluster.name` so Datadog sees one host; Agent owns infra/logs/named
   integrations, Collector owns OTLP app traces/metrics/logs + spanmetrics.
3. **Pre-bake named-integration annotations** for ArgoCD (ports 8082/8083/8084, only where a
   cluster runs ArgoCD), cert-manager (9402), Kyverno (8000). Falco -> Datadog stays via the
   existing falcosidekick `datadog` output, not a pod-annotation check. All annotations are inert
   without the Agent, so safe to bake.
4. **`datadog-secret` via ESO**, one `ExternalSecret` per consuming namespace (`monitoring`,
   `security`, `datadog`), one SM source of truth. Not per-namespace `kubectl create`.
5. **EKS+CloudWatch integration is a Datadog-side cross-account IAM role (Whitney's), not node
   IRSA;** keep it facilitator-only if used at all. Agent-to-AWS access, if ever needed, uses EKS
   Pod Identity / IRSA.
6. **Sizing: start on T3 burstable, do NOT start on fixed M-series.** A ~2-hour intermittent lab
   is the textbook burstable case. Default each standalone full-stack cluster to **`t3.xlarge`
   (4/16)** in Regex-only mode (requests fit with headroom). Set explicit Datadog Agent requests
   (chart default is empty); keep APM + System Probe + logs OFF on the Agent (Collector owns those).
   A cluster that opts into `Sensitive` NER needs 8/32 for RAM (start `t3.2xlarge`).
7. **M-series is a measured fallback, not the default.** Move a role to `m6i.xlarge` (or 8/32) ONLY
   if a real run shows T3 credits actually choke (Standard-mode throttle) or surplus billing is
   material (unlimited mode). The fallback is cheap: `t3.xlarge` -> `m6i.xlarge` is only ~+15%
   (~$5 across 60 clusters for 3 hours).
8. **Cost delta answers "why not just go bigger":** at 60 clusters x 3 hr, `t3.xlarge` ~$30 total
   compute, `m6i.xlarge` ~$35 (+$5), `m6i.2xlarge` ~$69 (+$39, +131%). Jumping to 8/32 without a
   measurement more than doubles the bill for RAM the Regex-only budget does not use. **Measure one
   live cluster** (`kubectl top` + CloudWatch `CPUCreditBalance`/`CPUSurplusCreditBalance`) before
   pinning the fleet.
9. **Attendee Datadog at scale:** Option A (pipeline -> AWS Secrets Manager -> ESO per cluster).
   Whitney provides `attendee_id -> {api_key, site[, app_key]}`; we consume via ESO. API key + site
   suffice for ingest; app keys only for Whitney's dashboard automation.

## verify-at-build checklist

- [ ] **Measure one live standalone cluster on `t3.xlarge`** through a real ~2-hour intermittent run:
      `kubectl top nodes` / `kubectl top pods -A` with the Datadog Agent enabled, Regex-only LLM
      Guard, during representative beat/inference bursts, AND watch CloudWatch `CPUCreditBalance` and
      `CPUSurplusCreditBalance`. Pin the fleet instance type from THIS measurement; only move to
      `m6i.xlarge` (or 8/32) if credits actually choke or surplus billing is material. Do this before
      provisioning 60-70.
- [ ] Confirm the chart-managed requests we budgeted but did not read: kagent controller + agent,
      kagent Postgres, agentgateway (v1.3.0), Istio ztunnel default. Read them from the rendered
      manifests, not assumed.
- [ ] Set explicit Datadog Agent + Cluster Agent resource requests (chart default is empty); verify
      with `kubectl describe` that requests are actually applied (not BestEffort).
- [ ] Verify the Datadog host string from the Agent and from the OTel exporter MATCH (no duplicate
      host in Datadog): check `k8s.node.name` + cluster name resolve identically on both paths.
- [ ] Confirm `datadog.prometheusScrape.enabled` is false on the Agent install.
- [ ] Confirm each named-integration container name matches the pinned chart (ArgoCD component
      container names, `cert-manager`, Kyverno controller names) so the `ad.datadoghq.com/<container>`
      keys actually attach.
- [ ] Confirm the Datadog Agent is gated behind a flag and that disabling it + removing the
      `datadog` exporter leaves Prometheus/Grafana/Tempo working (swappability smoke test).
- [ ] Create/sync `datadog-secret` (key `api-key`) in `monitoring`, `security`, and `datadog`
      namespaces via ESO; set `DD_SITE` / `DATADOG_HOST` to the correct per-attendee site.
- [ ] Confirm the T3 credit mode in the node group (default is `unlimited`): decide whether to keep
      `unlimited` (no mid-demo throttle, small bounded surplus billing over the short cluster life)
      or set `standard` (hard cost ceiling, can throttle to baseline). For a live lab, `unlimited`
      is the safer default; record the choice.
- [ ] Confirm the cluster topology decision (independent per-student standalone vs hub-and-spoke);
      if standalone, drop hub/ArgoCD sizing and apply ArgoCD annotations only where a cluster runs
      its own ArgoCD.
- [ ] With Whitney: confirm per-attendee-org (vs shared org), whether app keys are needed, the
      `attendee_id -> key/site` delivery format, and whether EKS+CloudWatch is in scope at all.
- [ ] If the measured run pushes a role to fixed M-series, confirm `m6i.xlarge` / `m7i.2xlarge`
      availability in the chosen region (capacity) before committing the fleet.

## Sources

- Datadog DDOT (recommended): https://www.datadoghq.com/blog/datadog-distribution-otel-collector/ ,
  https://docs.datadoghq.com/opentelemetry/setup/ddot_collector/ ,
  https://docs.datadoghq.com/opentelemetry/setup/ddot_collector/install/
- Datadog OTel/Agent coexistence + OTLP: https://docs.datadoghq.com/opentelemetry/ ,
  https://docs.datadoghq.com/opentelemetry/setup/agent/
- Hostname mapping (k8s.node.name): https://docs.datadoghq.com/opentelemetry/mapping/hostname/ ,
  https://docs.datadoghq.com/opentelemetry/collector_exporter/hostname_tagging/
- Prometheus scrape / Autodiscovery: https://docs.datadoghq.com/containers/kubernetes/prometheus/ ,
  https://docs.datadoghq.com/containers/kubernetes/integrations/ ,
  https://docs.datadoghq.com/getting_started/containers/autodiscovery/
- Named integrations: https://docs.datadoghq.com/integrations/argocd/ ,
  https://www.datadoghq.com/blog/argo-cd-datadog/ ,
  https://docs.datadoghq.com/integrations/cert-manager/ ,
  https://docs.datadoghq.com/integrations/kyverno/ ,
  https://github.com/DataDog/integrations-core/tree/master/kyverno , https://kyverno.io/docs/monitoring/
- Datadog Helm chart defaults (resources empty): https://github.com/DataDog/helm-charts/blob/main/charts/datadog/values.yaml ,
  https://docs.datadoghq.com/containers/cluster_agent/setup/
- Datadog AWS/EKS integration + IRSA/Pod Identity: https://docs.datadoghq.com/getting_started/integrations/aws/ ,
  https://docs.datadoghq.com/integrations/amazon-web-services/ ,
  https://docs.datadoghq.com/containers/kubernetes/distributions/
- Falco chart defaults: https://github.com/falcosecurity/charts/blob/master/charts/falco/values.yaml
- AWS T3 burstable / credits: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances.html ,
  https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html ,
  https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode.html
- Instance specs: https://aws.amazon.com/ec2/instance-types/m6i/ ,
  https://aws.amazon.com/ec2/instance-types/m7i/ ,
  https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html
- Instance pricing (cost-delta table): https://aws.amazon.com/ec2/pricing/on-demand/ ,
  https://instances.vantage.sh/aws/ec2/t3.xlarge ,
  https://instances.vantage.sh/aws/ec2/m6i.xlarge ,
  https://instances.vantage.sh/aws/ec2/m6i.2xlarge
