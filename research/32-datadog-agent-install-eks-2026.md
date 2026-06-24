<!-- ABOUTME: Datadog Agent install-method, feature-flag, IAM, Cluster-Agent, GitOps-manifest, and EKS- -->
<!-- ABOUTME: integration decisions for the Watch-It-Burn workshop (M5: Agent DaemonSet alongside OTel). -->

# 32. Datadog Agent Install Method + Feature Flags on EKS (build spec)

---

## ⚠ CORRECTIONS (2026-06-24) — Read before using any conclusion below

Two conclusions in this spike were overridden in the meta-PRD #7 Decision Log (2026-06-24). The
rest of the spike's research (sizing, feature flags, IAM options, Cluster Agent, integration list)
remains valid and is relied on in M5.

| Overridden conclusion | Correct decision | Where decided |
|---|---|---|
| **Install method: Helm chart** (`datadog.*` keys) | **Datadog Operator** (`spec.features.*` keys — DatadogAgent CR format). The sync-wave CRD-before-CR concern is standard ArgoCD pattern; not a reason to forgo the official tool. As a Datadog employee demonstrating the stack, using the Operator is the appropriate showcase. | meta-PRD #7 Decision Log 2026-06-24 |
| **`prometheusScrape`: OFF** | **`spec.features.prometheusScrape.enabled: true` — ON**. Several stack components are Prometheus-only (cert-manager, ESO, Falco, Falcosidekick). With it OFF those components produce zero telemetry. The OFF rationale assumed M5 wire-or-skip decisions would route all Prometheus data through the OTel Collector — that is not confirmed. Per-component deduplication strategy is M5 Decision 4 scope. **Note:** this is the Datadog Agent's Prometheus scraping feature — distinct from the OTel Collector's `datadog.prometheusScrape` exporter config (which remains OFF per the existing 2026-06-23 entry in the meta-PRD Decision Log). | meta-PRD #7 Decision Log 2026-06-24 |

---

Date: 2026-06-23

## Verification Method

- **Approach:** Web research dated 2026-06-23 against CURRENT (2026) official Datadog documentation
  (`docs.datadoghq.com`) and the DataDog/helm-charts repo, plus direct reads of the live repo at
  `/home/michael/repos/events/Unleash_an_Agent_Watch_It_Burn`. Every non-obvious, time-sensitive
  claim carries a citation (URL) inline; the full list is in the Sources section.
- **Scope (Whitney's constraint):** install method + feature flags ONLY. The architecture shape
  (standalone Datadog Agent DaemonSet alongside the OTel Collector, NOT DDOT) and the node-sizing
  numbers are **LOCKED** in `research/24-datadog-hybrid-impl-sizing-2026.md` and are NOT reopened
  here. This spike answers issue #14's six questions and builds on research/24, research/23
  (`research/23-observability-decision-points-2026.md`), and research/18
  (`research/18-datadog-integrations-stack-2026.md`).
- **In-repo facts taken as CONFIRMED (read directly from files):**
  - ArgoCD app-of-apps points at `gitops/apps/` (`gitops/bootstrap/app-of-apps.yaml`), and every
    component is **one flat `argoproj.io/v1alpha1` Application that renders an upstream Helm chart
    via `source.chart` + `helm.valuesObject`** with a `argocd.argoproj.io/sync-wave` annotation,
    `destination.server: https://kubernetes.default.svc`, and `syncPolicy.automated{prune,selfHeal}`
    (verified in `otel-collector.yaml`, `kagent.yaml`, `falcosidekick.yaml`, `external-secrets.yaml`).
  - The OTel Collector (`gitops/apps/otel-collector.yaml`, contrib `0.158.2`, DaemonSet) already has
    a `datadog` exporter (primary) on BOTH the metrics and traces pipelines, plus
    `prometheusremotewrite` + `otlp/tempo` (OSS fallback), a `resource` processor upserting
    `cluster.name=watch-it-burn`, and the `spanmetrics` connector. It reads `DD_API_KEY` from
    `datadog-secret` and `DD_SITE` (default `datadoghq.com`).
  - falcosidekick (`gitops/apps/falcosidekick.yaml`, `security` ns) already forwards to Datadog via
    `config.datadog` + `DATADOG_APIKEY` from `datadog-secret`.
  - ESO is present (`gitops/apps/external-secrets.yaml`, `platform` ns, chart `2.6.0`) and reads AWS
    Secrets Manager via **EKS Pod Identity** (per PROJECT_STATE 2026-06-22, PR #4: ESO moved IRSA ->
    Pod Identity). The agent and AWS Load Balancer Controller also use Pod Identity; **IRSA is
    retained only for the EBS CSI driver** (PROJECT_STATE + `infra/terraform/cluster/main.tf`).
  - Namespaces are declared in `gitops/namespaces/namespaces.yaml`; there is currently **no
    `datadog` namespace** (one must be added).
- **Items needing a live cluster** are marked UNCERTAIN and pushed to the verify-at-build checklist.

---

## Q1. Install method on EKS

**The full option set, evaluated for ArgoCD GitOps + EKS + ~60-70 single-node workshop clusters.**

Datadog documents four ways to get the Agent onto Kubernetes/EKS
([Install the Datadog Agent on Kubernetes](https://docs.datadoghq.com/containers/kubernetes/installation/);
[Kubernetes](https://docs.datadoghq.com/containers/kubernetes/)):

### Option A: Datadog Helm chart manages the Agent DaemonSet directly (`datadog/datadog`)

One Helm release renders the node Agent DaemonSet + Cluster Agent (+ optional cluster-checks runner)
directly as Kubernetes objects. No CRD, no second controller.

- **Pro (fits this repo exactly):** identical to the pattern every other component here already uses:
  one ArgoCD `Application` with `source.chart` + `helm.valuesObject` (otel-collector, kagent,
  falcosidekick, external-secrets all do this). ArgoCD renders the chart and applies the resulting
  DaemonSet/Deployment; no ordering dependency between "install a controller" and "apply a CR."
- **Pro:** single sync wave, single Application, single diff to review. Swappability is one line
  (`datadog.agent.enabled` / disable the Application).
- **Con:** "Unlike the Helm chart, the Operator is **included in the Kubernetes reconciliation
  loop**"; the chart is a one-shot render, so cross-field validation and best-practice defaults are
  weaker than the Operator's
  ([Datadog Operator](https://docs.datadoghq.com/containers/datadog_operator/)).

### Option B: Datadog Operator + `DatadogAgent` CR (Operator installed via its own Helm chart)

Install the `datadog-operator` Helm chart (a controller), then apply a `DatadogAgent` custom
resource; the Operator reconciles it into the DaemonSet + Cluster Agent.

- **Pro:** "built-in defaults based on Datadog best practices," "limits the risk of
  misconfiguration," a **single CRD deploys node Agent + Cluster Agent + cluster-checks runner**, and
  it is "treated as a first-class resource by the Kubernetes API" and "included in the Kubernetes
  reconciliation loop." Datadog now recommends the Operator as the primary path
  ([Datadog Operator](https://docs.datadoghq.com/containers/datadog_operator/)).
- **Con (the GitOps cost):** this is a **two-stage install with a CRD-ordering dependency**: the
  `DatadogAgent` CR cannot apply until the Operator's CRD is established. In ArgoCD that means either
  two Applications with carefully ordered sync-waves, or one Application with sync-wave-separated
  resources and likely `ServerSideApply` + retry, plus a custom health check for the `DatadogAgent`
  CR. The well-known ArgoCD operator pattern (install operator in wave N, apply the CR in wave N+1)
  applies here ([Operator installation with Argo CD/GitOps](https://www.redhat.com/en/blog/operator-installation-with-argo-cd/gitops);
  [argo-cd discussion #6364](https://github.com/argoproj/argo-cd/discussions/6364)). That is
  strictly more moving parts than every other component in this repo, replicated across ~60-70
  self-reconciling clusters.

### Option C: EKS add-on (Datadog Operator EKS add-on via AWS Marketplace)

Install through AWS's native add-on system (`aws eks create-addon --addon-name datadog_operator`)
after subscribing on AWS Marketplace.

- **Disqualifying for this stack.** It requires an **AWS Marketplace subscription** (mandatory) and
  is installed by an **out-of-band AWS API call**, NOT from Git, so it sits outside the
  in-cluster-ArgoCD GitOps loop the whole repo is built on. It further constrains the install:
  "images must be pulled only from the EKS repository. This can't be changed," Operator Helm values
  "are restricted to a schema file," and "Agents installed using the Operator add-on only collect
  data from pods running on EC2 instances"
  ([Datadog Operator EKS add-on](https://docs.datadoghq.com/containers/guide/operator-eks-addon/)).
  None of that is worth taking on for a take-home, Git-reconciled fleet.

### Option D: Manual DaemonSet manifests

Hand-write the DaemonSet/Deployment YAML.

- **Disqualifying.** Datadog: "manual DaemonSet configuration leaves significant room for error"
  ([Further configure the Agent](https://docs.datadoghq.com/containers/kubernetes/configuration/);
  [Manual DaemonSet install](https://docs.datadoghq.com/containers/guide/kubernetes_daemonset/)).
  It also defeats version pinning and the chart's coexistence toggles. No reason to choose it when a
  chart exists.

### DECISION (Q1): **Option A, the Datadog Helm chart (`datadog/datadog`) as a single ArgoCD Application.**

Rationale: it is the **lowest-friction fit for this exact GitOps shape**. Every component in this
repo is already a one-Application-renders-one-chart manifest with a sync-wave; the Datadog Agent
should be the same so it reconciles, diffs, and is swappable identically, with no CRD-ordering
dance replicated across 60-70 independent clusters. The Operator's advantages (reconciliation loop,
best-practice defaults) are real but are a production-fleet management story; for a 2-hour,
take-home, infra-only-additive Agent they do not outweigh the added two-stage CRD wiring. The EKS
add-on is out (Marketplace + out-of-band, breaks GitOps); manual is out (error-prone).
**Caveat for the facilitator/instructor cluster only:** if Whitney wants the Operator's richer
single-CR management on the on-stage instructor Cluster 3, Option B is acceptable *there* (it is not
part of the swappable per-attendee fleet), exactly as research/24 §1.1 already carves DDOT out as
an instructor-only option. Fleet-wide stays Option A.

**Confidence: HIGH.** (The option set, the Operator-vs-Helm tradeoff, the add-on constraints, and
the repo's existing pattern are all directly evidenced.)

---

## Q2. Required feature flags (minimal additive set)

The Agent is **additive** for infra metrics, container logs, and named integrations; the OTel
Collector already owns OTLP traces+metrics into Datadog. Default-on/off status confirmed from
[Further configure the Agent](https://docs.datadoghq.com/containers/kubernetes/configuration/),
[Kubernetes log collection](https://docs.datadoghq.com/containers/kubernetes/log/), and
[OTLP ingest in the Agent](https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/).

| Capability | Helm value (`datadog/datadog` chart) | Default | Decision for this stack |
|---|---|---|---|
| **Infra/host + container metrics** | (core Agent; always on) | ON | **KEEP ON.** This is the whole reason we add the Agent (EKS infra auto-discovery). |
| **Container log collection** | `datadog.logs.enabled: true` + `datadog.logs.containerCollectAll: true` | **OFF** (explicit opt-in) | **TURN ON.** M5 explicitly wants container logs. Both flags required; without `containerCollectAll` it collects nothing by default. |
| **Live container collection** (live container view) | `datadog.processAgent.enabled` (via Process Agent) | **ON by default** | **LEAVE AT DEFAULT (on).** Lightweight container view; no extra flag needed. (Operator field: `features.liveContainerCollection.enabled`.) |
| **Process collection** (full per-process inspection) | `datadog.processAgent.processCollection: true` | **OFF** (Process Agent runs, but process *collection* is opt-in) | **LEAVE OFF.** Not needed for the workshop story; saves CPU/RAM. (Operator: `features.liveProcessCollection.enabled`.) |
| **DogStatsD** | enabled by default; non-local via `datadog.dogstatsd.nonLocalTraffic` / `DD_DOGSTATSD_NON_LOCAL_TRAFFIC` | **ON by default**; chart default `nonLocalTraffic: true` (corrected 2026-06-23: the chart turns non-local ON by default, contrary to an earlier draft note) | **LEAVE AT DEFAULT.** No app in this stack emits StatsD; effectively dormant. (Earlier text implied non-local was off by default; it is on in the chart. Either way, no action needed and nothing emits StatsD.) |
| **APM trace collection / Agent OTLP receiver** | `datadog.apm.*`; OTLP via `datadog.otlp.receiver.protocols.{grpc,http}.enabled` | APM default-on over UDS; **OTLP receiver OFF by default** | **DO NOT ENABLE the OTLP receiver; disable APM on the Agent.** See confirmation below. |
| **Named integrations** (ArgoCD/cert-manager/Kyverno) | Autodiscovery pod annotations (`ad.datadoghq.com/<container>.checks`), pre-baked per research/24 §1.3 | n/a (per-pod opt-in) | **KEEP as pre-baked annotations** (research/24 owns the exact shapes; inert without the Agent). |
| **Cluster-wide Prometheus autoscrape** | `datadog.prometheusScrape.enabled` | OFF | **KEEP OFF.** research/24 §1.2 rule 1: would double-count series the OTel pipeline already ships. |

### Confirming the APM OTLP receiver is NOT needed

**Confirmed NOT needed.** The Datadog Agent's OTLP ingest is **off by default**: "OTLP ingestion is
off by default, and you can turn it on by updating your `datadog.yaml` ... or by setting environment
variables" ([OTLP ingest in the Agent](https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/)).
The Agent's OTLP receiver exists so apps with OTel SDKs can send OTLP **to the Agent**, which then
forwards to Datadog. In this stack the **standalone OTel Collector already exports OTLP traces and
metrics directly to Datadog via its `datadog` exporter** (`gitops/apps/otel-collector.yaml`,
confirmed). Routing app telemetry a second time *through* the Agent would duplicate the trace/metric
path and reintroduce the host-double-count and double-billing problems research/24 §1.2 guards
against. So: **leave the Agent's OTLP receiver disabled (its default) and disable APM on the Agent.**
The Collector remains the sole OTLP-to-Datadog path; the Agent does infra/logs/integrations only.

### Minimal feature set (the decision)

**Enable:** core infra/container metrics (inherent) + container logs (`logs.enabled`,
`logs.containerCollectAll`). **Leave at default-on (no action):** live container collection,
DogStatsD (local, dormant). **Explicitly keep OFF:** Agent OTLP receiver, Agent APM, full process
collection, System Probe/NPM/USM, `prometheusScrape`. **Named integrations** come from pre-baked
annotations, not Agent flags.

### Resource cross-reference (research/24 §2.3, LOCKED, not reopened)

research/24 §2.3 sizes a **lean infra-only Agent** as ≈ node Agent 200m/256Mi + Process Agent
100m/200Mi + Cluster Agent 200m/256Mi ≈ **500m CPU / ~700Mi RAM** per cluster, explicitly with
**APM, System Probe, and logs treated as the "off" baseline** ("keep them off on the Agent"). The
one delta this spike's feature decision introduces against that baseline is **turning container logs
ON** (M5 requires them). Log collection is handled inside the existing node-Agent container (it
tails `/var/log/pods`), so it does **not** add a new container/pod; it raises that container's CPU/
mem draw modestly rather than adding a sizing row. The chart sets **no default resource requests**
(research/24 §2.3: a trap, since the Agent would be `BestEffort`), so we must **set requests explicitly**;
budget the node Agent slightly above the §2.3 256Mi line to absorb log buffering, and re-measure per
the §2.3 measure-then-pin rule. Everything still fits the LOCKED `t3.xlarge` (4/16) Regex-only
budget; logs do not change the instance recommendation. **The §2.3 numbers themselves are
unchanged. This is a cross-reference, not a re-sizing.**

**Confidence: HIGH** on the flag list and defaults (each cited); **MEDIUM** on the exact incremental
RAM that container-log buffering adds (needs the §2.3 live measurement; bounded, does not change the
instance pick).

---

## Q3. EKS IAM: does the Agent need AWS API access?

**For its CORE function here (node/host metrics, container metrics, kube-state metrics, container
logs, named Prometheus/OpenMetrics integration scrapes), the in-cluster Datadog Agent does NOT need
AWS API access.** Those signals come from the kubelet, the container runtime, the Kubernetes API
(via the Cluster Agent), and in-cluster `/metrics` endpoints, none of which is an AWS API call.
research/24 §1.4 already states the boundary: for the in-cluster Agent "you don't need any specific
configuration for EKS" beyond the standard Kubernetes install, and AWS API access is only needed for
the separate cross-account CloudWatch integration (Q6), which is a **Datadog-account-side** role, not
a node IRSA/Pod-Identity role
([Kubernetes distributions](https://docs.datadoghq.com/containers/kubernetes/distributions/);
[Getting started with AWS](https://docs.datadoghq.com/getting_started/integrations/aws/)).

**IF** AWS API access were ever wanted *from the Agent pod* (e.g. an AWS-service integration scraped
from inside the cluster, or Datadog's cloud-based API-key auth that authenticates via AWS
credentials, [Cloud-based Authentication](https://docs.datadoghq.com/account_management/cloud_provider_authentication/)),
the right mechanism for this repo is **EKS Pod Identity**, not IRSA, on **repo-convention** grounds
(agent / AWS LBC / ESO already use Pod Identity; PROJECT_STATE 2026-06-22), not on a Datadog-specific
endorsement. (Citation corrected 2026-06-23: the previously cited
[`aws_eks_podidentityassociation` resource-catalog page](https://docs.datadoghq.com/infrastructure/resource_catalog/aws_eks_podidentityassociation/)
is a Datadog Resource Catalog **metadata entry describing the AWS resource type**. It does NOT
document Pod Identity as a supported Datadog Agent credential path, so it does not back the "Datadog
documents Pod Identity for the Agent" claim. The Pod-Identity-if-ever-needed decision stands on the
repo convention; the standard Agent EKS install needs no AWS credentials at all.)

### DECISION (Q3): **No AWS API access required for the Agent's core function. If ever needed, use EKS Pod Identity (NOT IRSA).**

Rationale: the repo's convention is already **Pod Identity for agent / AWS LBC / ESO**, with IRSA
retained only for the EBS CSI driver (PROJECT_STATE 2026-06-22; `infra/terraform/cluster/main.tf`).
Pod Identity is also the fleet-friendly choice: a Terraform pod-identity *association* per cluster,
no per-cluster OIDC trust to stamp 60-70 times and no SA annotation in GitOps (the exact reason the
agent's Bedrock access was moved to Pod Identity). So if an Agent-side AWS role is ever added, it
follows the established Pod Identity path. **Default for the workshop: do not grant the Agent any AWS
role at all**, since its core duties don't need one.

**Confidence: HIGH.**

---

## Q4. Cluster Agent: required or optional

**Strongly recommended; effectively required for the clean version of this design, but it is a
single Deployment, not part of the DaemonSet.** The Cluster Agent "acts as a proxy between the API
server and node-based Agents," relays cluster-level metadata so node Agents can enrich local
metrics, is the **only** component that talks to the Kubernetes API when present ("your node Agents
are not able to interact with the Kubernetes API server — only the Cluster Agent is able to do so"),
and serves cluster-level data (kube-state, events, service checks) plus dispatches Autodiscovery
configs to the node Agents
([Cluster Agent for Kubernetes](https://docs.datadoghq.com/containers/cluster_agent/);
[Set up the Cluster Agent](https://docs.datadoghq.com/containers/cluster_agent/setup/)).

### Interaction with the node Agent DaemonSet on a single-node cluster

On a 1-node workshop cluster the topology is: **one node Agent (DaemonSet, 1 replica because 1 node)
+ one Cluster Agent (Deployment, 1 replica)**, both on the same node. The Cluster Agent still does
the same job at N=1: it centralizes the API-server calls and kube-state/events collection and feeds
metadata + Autodiscovery config to the lone node Agent (the node Agent polls it ~every 10s). The
benefit at N=1 is less about offloading API-server load (trivial here) and more about **correctness
and parity**: kube-state metrics, cluster events, and the **named-integration Autodiscovery**
(research/24 §1.3: ArgoCD/cert-manager/Kyverno) are dispatched the way Datadog expects, and the
single-node footprint matches the fleet. The Cluster Agent is in the Datadog chart's default
topology, so this is the supported shape.

### DECISION (Q4): **Enable the Cluster Agent (1 replica). Required for clean kube-state/events + Autodiscovery dispatch; one extra Deployment on the single node.**

Sizing: research/24 §2.3 (LOCKED) already budgets the Cluster Agent at **200m/256Mi** inside the
≈500m/700Mi infra-only total that fits the `t3.xlarge` node, so enabling it costs nothing beyond
the already-locked budget. Set its requests explicitly (chart default is empty).

**Confidence: HIGH** on role and topology; the "required vs nice-to-have at N=1" line is a design
call (we choose required for correctness + parity), clearly reasoned above.

---

## Q5. GitOps manifest shape

**Where it lives:** a new file `gitops/apps/datadog-agent.yaml`, auto-discovered by the existing
app-of-apps (`gitops/bootstrap/app-of-apps.yaml` points `path: gitops/apps`, so any Application file
dropped there is picked up, confirmed). Add a `datadog` namespace to
`gitops/namespaces/namespaces.yaml` (it does not exist today).

**Shape:** one `argoproj.io/v1alpha1` `Application` rendering the upstream `datadog/datadog` Helm
chart via `source.chart` + `helm.valuesObject`, mirroring `otel-collector.yaml`/`falcosidekick.yaml`
exactly. Illustrative shape (NOT applied, research-only; pin the chart version and set Agent
resource requests at build):

```yaml
# gitops/apps/datadog-agent.yaml  (ILLUSTRATIVE — do not apply from this spike)
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: datadog-agent
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "2"   # after namespaces/ESO; see note
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    chart: datadog
    repoURL: https://helm.datadoghq.com
    targetRevision: "<PIN-AT-BUILD>"     # verify current GA Datadog chart version
    helm:
      valuesObject:
        datadog:
          apiKeyExistingSecret: datadog-secret   # key `api-key`; ESO-synced (research/24 §1.4)
          site: datadoghq.com                     # set to Whitney's site per attendee
          clusterName: watch-it-burn               # MUST match OTel resource cluster.name (host dedup)
          logs:
            enabled: true                          # Q2: container logs ON (opt-in)
            containerCollectAll: true
          prometheusScrape:
            enabled: false                         # research/24 §1.2 rule 1 (no double-scrape)
          otlp:
            receiver:
              protocols:
                grpc: { enabled: false }           # Q2: Collector owns OTLP -> Datadog
                http: { enabled: false }
          # apm / systemProbe / processAgent.processCollection: left at lean defaults (Q2)
        clusterAgent:
          enabled: true                            # Q4
          replicas: 1
          resources:                               # chart default is EMPTY -> set explicitly
            requests: { cpu: 200m, memory: 256Mi }
        agents:
          containers:
            agent:
              resources:                           # set explicitly (research/24 §2.3 trap)
                requests: { cpu: 200m, memory: 256Mi }
  destination:
    server: https://kubernetes.default.svc
    namespace: datadog
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

Notes on the shape: (1) the `datadog-secret` is referenced via `apiKeyExistingSecret`, materialized
in the `datadog` namespace by an ESO `ExternalSecret` (research/24 §1.4 / Q6 of the issue), not
hand-created. (2) `clusterName: watch-it-burn` must equal the OTel Collector's
`resource.cluster.name` so the Agent and the OTLP path resolve to one Datadog host (research/24 §1.2
rule 2). (3) Swappability: disabling/deleting this one Application + removing the Collector's
`datadog` exporter leaves the OSS stack intact. (4) **Sync-wave caveat (verify-at-build):** the chart
ships Datadog CRDs (e.g. `DatadogMetric`); if ArgoCD reports CRD/`ServerSideApply` ordering issues,
either add `ServerSideApply=true` (as `external-secrets.yaml` and `kagent.yaml` already do) or split
the CRD install. But because Option A renders the DaemonSet/Deployment directly (no `DatadogAgent`
CR), there is **no operator-CR ordering dependency**, which is the main reason Option A is simpler
here. Pin `targetRevision` and confirm the value keys against the pinned chart's `values.yaml` at
build ([datadog chart values.yaml](https://github.com/DataDog/helm-charts/blob/main/charts/datadog/values.yaml);
[datadog chart README](https://github.com/DataDog/helm-charts/blob/main/charts/datadog/README.md)).

**Confidence: HIGH** on file location + Application skeleton (matches repo pattern verbatim);
**MEDIUM** on the exact `valuesObject` key paths (some keys, e.g. `apiKeyExistingSecret` vs
`apiKeyExistingSecret`/`api.keyExistingSecret`, and the `agents.containers.agent.resources` path,
shift across chart versions; verify against the pinned chart at build).

---

## Q6. EKS + CloudWatch integration (optional scope)

**What it is (confirmed):** the Datadog **AWS integration** is **IAM Role Delegation**: a
CloudFormation stack creates "an IAM role and associated policy, allowing **Datadog's AWS account to
make API calls to your AWS account**," configured **in the Datadog account UI** ("Add AWS Account"),
NOT on any in-cluster Agent
([Getting started with AWS](https://docs.datadoghq.com/getting_started/integrations/aws/)). It pulls
CloudWatch metrics into Datadog backend-side. This matches research/24 §1.4 exactly: it is a
Datadog-account-side cross-account role, not node IRSA/Pod Identity.

**Is it needed for this workshop?** **No, not for the core story, and NOT per-attendee.** The
workshop's observability payoff (input/output/tool-call traces, GenAI semconv, the cost counter, EKS
infra metrics, container logs, named integrations) is fully served by the OTel Collector + the
in-cluster Datadog Agent. CloudWatch metrics (EC2/EBS/ELB/EKS control-plane CloudWatch series) add
AWS-resource telemetry that this 2-hour chaos lab does not narrate. At 60-70 separate attendee orgs,
wiring a CloudFormation cross-account role + Datadog "Add AWS Account" per attendee is heavy,
slow, and adds AWS-account-delegation surface for zero demo value.

### DECISION (Q6): **Not needed. Skip it fleet-wide. If Whitney wants any CloudWatch data, it is facilitator-only (one instructor/facilitator cluster + that one Datadog org), set up once via her CloudFormation stack in her Datadog UI.**

Requirements **if** it is ever wired (facilitator-only): a CloudFormation stack in the AWS account
that creates the cross-account read-only IAM role (with the external ID Datadog provides) + adding
the account in the Datadog integrations UI; this is **Whitney's piece** (her Datadog org). Per-attendee
is explicitly out of scope. This is consistent with research/24 §1.4 and does not reopen it.

**Confidence: HIGH** on mechanism + the not-needed/facilitator-only recommendation. **UNCERTAIN
(for Whitney, not researchable):** whether she nonetheless *wants* CloudWatch metrics on the
instructor cluster for narration; a preference, not a technical requirement.

---

## Decisions / recommendations (summary)

1. **Install (Q1):** Datadog **Helm chart** (`datadog/datadog`) as **one ArgoCD Application** in
   `gitops/apps/datadog-agent.yaml`. Operator only optionally on the instructor cluster; EKS add-on
   rejected (Marketplace + out-of-band, breaks GitOps); manual rejected.
2. **Feature flags (Q2):** ON = infra/container metrics (inherent) + container logs
   (`logs.enabled`+`logs.containerCollectAll`). Default-on, no action = live container collection,
   local DogStatsD. **OFF** = Agent OTLP receiver, Agent APM, process collection, System Probe,
   `prometheusScrape`. **APM OTLP receiver confirmed NOT needed** (Collector exports to Datadog
   directly; Agent OTLP is off by default). Cross-ref to research/24 §2.3: only delta is logs ON;
   still fits the LOCKED `t3.xlarge` budget; set Agent requests explicitly.
3. **IAM (Q3):** Agent core function needs **no AWS API access**. If ever needed, **EKS Pod
   Identity** (repo convention), not IRSA.
4. **Cluster Agent (Q4):** **Enable** it (1 replica), required for clean kube-state/events +
   Autodiscovery dispatch; budgeted at 200m/256Mi in the LOCKED §2.3 total.
5. **Manifest (Q5):** new `gitops/apps/datadog-agent.yaml`, single Application rendering the chart,
   add a `datadog` namespace; `clusterName=watch-it-burn` for host dedup; `datadog-secret` via ESO.
6. **EKS+CloudWatch (Q6):** **not needed**; skip fleet-wide; facilitator-only via Whitney's
   CloudFormation if she wants it.

## verify-at-build checklist

- [ ] Pin the current GA `datadog/datadog` chart `targetRevision`; confirm the `valuesObject` key
      paths against that version's `values.yaml` (esp. `apiKeyExistingSecret`/`api.keyExistingSecret`,
      `agents.containers.agent.resources`, `logs.containerCollectAll`, `otlp.receiver.protocols.*`,
      `prometheusScrape.enabled`, `clusterAgent.*`).
- [ ] Add a `datadog` namespace to `gitops/namespaces/namespaces.yaml`.
- [ ] Add the ESO `ExternalSecret` that materializes `datadog-secret` (key `api-key` + site) in the
      `datadog` namespace (research/24 §1.4 Option A).
- [ ] Set explicit Agent + Cluster Agent resource requests (chart default is EMPTY, avoid
      BestEffort); verify with `kubectl describe`.
- [ ] Confirm `datadog.otlp.receiver.protocols.{grpc,http}.enabled=false` and APM disabled on the
      Agent (Collector remains the sole OTLP->Datadog path; no host/trace double-count).
- [ ] Confirm `datadog.prometheusScrape.enabled=false`.
- [ ] Confirm `clusterName` on the Agent == OTel `resource.cluster.name` (`watch-it-burn`) so Datadog
      shows one host (research/24 §1.2).
- [ ] Confirm container logs actually arrive (`logs.enabled`+`containerCollectAll`) and measure the
      node-Agent RAM delta from log buffering against the §2.3 budget on one live cluster.
- [ ] Swappability smoke test: disable the `datadog-agent` Application + drop the Collector `datadog`
      exporter -> Prometheus/Grafana/Tempo still working.
- [ ] If ArgoCD reports CRD ordering on the chart's Datadog CRDs, add `ServerSideApply=true` (as in
      `kagent.yaml`/`external-secrets.yaml`).
- [ ] With Whitney: does she want any CloudWatch data on the instructor cluster (facilitator-only)?
      If yes, her CloudFormation cross-account role + "Add AWS Account" in her Datadog org.

## Validation pass (adversarial, 2026-06-23)

Adversarial re-verification of the load-bearing claims against CURRENT (2026) official Datadog docs
and the live `DataDog/helm-charts` `values.yaml`. Default posture: skeptical, unbacked = UNVERIFIED.
Two inaccuracies were found and fixed inline (a misattributed Pod-Identity citation in Q3 and a wrong
DogStatsD non-local default in the Q2 table); neither changes any decision.

**Q1: Install method**

- CONFIRMED: The Datadog Operator is the **explicitly recommended** install method. The Kubernetes
  installation index lists "**Datadog Operator (recommended)**", Helm, and Manual, so the file's
  "Datadog now recommends the Operator as the primary path" is accurate.
  (https://docs.datadoghq.com/containers/kubernetes/installation/)
  Nuance: the standalone Operator page is softer ("Datadog fully supports using a DaemonSet to deploy
  the Agent") and does not say "use Operator over Helm", but the installation index page carries the
  explicit "(recommended)" tag, so the claim is backed. The file choosing Option A (Helm) anyway is a
  reasoned GitOps-fit tradeoff against this recommendation, not a contradiction of it.
  (https://docs.datadoghq.com/containers/datadog_operator/)
- CONFIRMED: Operator advantages: "built-in defaults based on Datadog best practices" and "Unlike
  the Helm chart, the Operator is included in the Kubernetes reconciliation loop", quoted accurately.
  (https://docs.datadoghq.com/containers/datadog_operator/)
- CONFIRMED: EKS add-on disqualifiers, all verbatim: AWS **Marketplace subscription required**;
  "images must be pulled only from the EKS repository. This can't be changed"; Helm values
  "restricted to a schema file"; "Agents installed using the Operator add-on only collect data from
  pods running on EC2 instances". (https://docs.datadoghq.com/containers/guide/operator-eks-addon/)
- CONFIRMED (not separately re-fetched this pass, low-risk): manual DaemonSet "leaves significant room
  for error". (https://docs.datadoghq.com/containers/kubernetes/configuration/)

**Q2: Feature flags / defaults** (verified against the live chart `values.yaml`,
https://raw.githubusercontent.com/DataDog/helm-charts/main/charts/datadog/values.yaml)

- CONFIRMED: Container logs are OFF by default and BOTH flags are the opt-in: chart defaults
  `datadog.logs.enabled: false` and `datadog.logs.containerCollectAll: false`; the log-collection doc
  states `containerCollectAll` "When set to `false` (default)". Decision to turn both ON is correct.
  (values.yaml; https://docs.datadoghq.com/containers/kubernetes/log/)
- CONFIRMED: Live container collection is default-ON via `processAgent.containerCollection: true`,
  while full **process collection is OFF** (`processAgent.processCollection: false`) with the Process
  Agent itself enabled (`processAgent.enabled: true`). The file's table mapping (live container view
  on, process collection off/opt-in) is correct. (values.yaml)
- CONFIRMED: Agent **OTLP ingest is off by default**: "OTLP ingestion is off by default, and you can
  turn it on…"; chart `otlp.receiver.protocols.grpc.enabled: false` and `http.enabled: false`. The
  "do NOT enable the OTLP receiver" decision is sound: the standalone OTel Collector already exports
  OTLP traces+metrics to Datadog via its `datadog` exporter (confirmed in-repo), so routing app
  telemetry a second time through the Agent would duplicate the path. APM-OTLP-receiver "NOT needed"
  is CONFIRMED. (https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/; values.yaml)
- CONFIRMED: `prometheusScrape.enabled: false` by default, keep-off decision backed. (values.yaml)
- REFUTED (minor, fixed inline): the table claimed DogStatsD "non-local… do NOT enable" implying
  non-local is off by default. The chart default is `datadog.dogstatsd.nonLocalTraffic: true` (non-local
  IS on by default). Corrected in the table. This does not change the decision: nothing in the stack
  emits StatsD, so DogStatsD stays dormant regardless. (values.yaml)
- CONFIRMED: `apiKeyExistingSecret` uses key name `api-key` inside the secret. (values.yaml)

**Q3: EKS IAM / AWS API access**

- CONFIRMED: The Agent needs **no AWS API access** for its core function. Datadog's EKS distribution
  guidance states "No specific configuration is required" for Amazon EKS; core signals come from the
  kubelet / Kubernetes API (via Cluster Agent) / in-cluster `/metrics`, none of which is an AWS API
  call. (https://docs.datadoghq.com/containers/kubernetes/distributions/)
- REFUTED → corrected inline: the claim "Datadog documents EKS Pod Identity associations as a
  supported credential path for the Agent," cited to the `aws_eks_podidentityassociation` Resource
  Catalog page, is NOT supported by that page. That page is a Datadog **Resource Catalog metadata
  entry** describing the AWS resource type's fields (`association_arn`, `role_arn`, etc.). It is not
  guidance that the Agent uses Pod Identity for credentials. The Pod-Identity-if-ever-needed
  *decision* is still correct on repo-convention grounds (agent/LBC/ESO already use Pod Identity), so
  the recommendation stands; only the citation was wrong. Fixed: the claim is now grounded in the repo
  convention, not a Datadog endorsement.
  (https://docs.datadoghq.com/infrastructure/resource_catalog/aws_eks_podidentityassociation/)

**Q4: Cluster Agent**

- CONFIRMED: Role and topology: the Cluster Agent "act[s] as a proxy between the API server and
  node-based Agents," centralizes API-server communication, relays cluster-level metadata so node
  Agents enrich local metrics, and node Agents are reduced to reading "metrics and metadata from the
  kubelet" (i.e. not the API server). It is enabled by default in the chart (`clusterAgent.enabled:
  true`), supporting "in the chart's default topology." The "enable it (1 replica)" decision is
  backed. (https://docs.datadoghq.com/containers/cluster_agent/; values.yaml)

**Q5: GitOps manifest shape**

- CONFIRMED (in-repo, not re-litigated): Application skeleton mirrors the existing one-chart-per-Application
  pattern. The author already flags the `valuesObject` key paths as MEDIUM-confidence "verify against
  the pinned chart", appropriate. This pass confirms the load-bearing value keys exist as written in
  the current chart: `datadog.logs.{enabled,containerCollectAll}`, `datadog.otlp.receiver.protocols.{grpc,http}.enabled`,
  `datadog.prometheusScrape.enabled`, `clusterAgent.enabled`, and `api-key` secret key. The current
  GA chart is ~`3.226.x` (Artifact Hub, June 2026); the file correctly leaves `targetRevision` as
  `<PIN-AT-BUILD>`, so no version claim to refute.
  (https://artifacthub.io/packages/helm/datadog/datadog; values.yaml)

**Q6: EKS + CloudWatch integration**

- CONFIRMED: Mechanism is **IAM Role Delegation**: "The CloudFormation template creates an IAM role
  and associated policy, allowing Datadog's AWS account to make API calls to your AWS account," set up
  in the Datadog UI via "Add AWS Account," NOT on any in-cluster Agent. The "not needed fleet-wide,
  facilitator-only if wanted" recommendation is consistent with this account-side mechanism.
  (https://docs.datadoghq.com/getting_started/integrations/aws/)

**Net:** All six decisions survive validation. One citation was wrong (Q3 Pod Identity) and one
default was stated wrong (Q2 DogStatsD non-local); both fixed inline. No decision changed.

## Sources

- Install methods / Kubernetes: https://docs.datadoghq.com/containers/kubernetes/installation/ ,
  https://docs.datadoghq.com/containers/kubernetes/
- Datadog Operator (recommended; reconciliation loop, single CRD, best-practice defaults):
  https://docs.datadoghq.com/containers/datadog_operator/ ,
  https://docs.datadoghq.com/containers/datadog_operator/migration/
- EKS add-on (Marketplace + constraints): https://docs.datadoghq.com/containers/guide/operator-eks-addon/
- Manual DaemonSet (error-prone): https://docs.datadoghq.com/containers/guide/kubernetes_daemonset/ ,
  https://docs.datadoghq.com/containers/kubernetes/configuration/
- ArgoCD operator/CRD sync-wave pattern: https://www.redhat.com/en/blog/operator-installation-with-argo-cd/gitops ,
  https://github.com/argoproj/argo-cd/discussions/6364
- Feature flags / defaults (logs, container/process, APM, DogStatsD):
  https://docs.datadoghq.com/containers/kubernetes/configuration/ ,
  https://docs.datadoghq.com/containers/kubernetes/log/ ,
  https://docs.datadoghq.com/containers/kubernetes/apm/
- OTLP ingest in the Agent (off by default; receiver value keys):
  https://docs.datadoghq.com/opentelemetry/setup/otlp_ingest_in_the_agent/ ,
  https://docs.datadoghq.com/opentelemetry/setup/agent/
- Cluster Agent (role, API-server proxy, metadata, single-node):
  https://docs.datadoghq.com/containers/cluster_agent/ ,
  https://docs.datadoghq.com/containers/cluster_agent/setup/
- EKS / IAM (Agent needs no specific EKS config; Pod Identity supported):
  https://docs.datadoghq.com/containers/kubernetes/distributions/ ,
  https://docs.datadoghq.com/integrations/amazon-eks/ ,
  https://docs.datadoghq.com/infrastructure/resource_catalog/aws_eks_podidentityassociation/ ,
  https://docs.datadoghq.com/account_management/cloud_provider_authentication/
- AWS integration = cross-account IAM Role Delegation via CloudFormation, Datadog-account-side:
  https://docs.datadoghq.com/getting_started/integrations/aws/
- Datadog Helm chart values/README (verify key paths at build):
  https://github.com/DataDog/helm-charts/blob/main/charts/datadog/values.yaml ,
  https://github.com/DataDog/helm-charts/blob/main/charts/datadog/README.md
- Prior work (not reopened): research/24-datadog-hybrid-impl-sizing-2026.md (LOCKED architecture +
  sizing), research/23-observability-decision-points-2026.md, research/18-datadog-integrations-stack-2026.md
