<!-- ABOUTME: Audit of the attendee platform for components that duplicate another or that nothing in the
     ABOUTME: lab, the deck, the tour, the challenges or the verify harness uses (#236). Static, from git. -->
# Duplicative and unused components on the attendee cluster (#236)

Michael, 2026-09-05: *"do we have a bunch of components that are duplicative that we don't actually need?"*

This audit answers that from the repository at `e8cc179` (2026-10-24). Every candidate was grepped across
the five surfaces the issue names, plus the terminal's `platform` command, and then traced through its
wiring, because a reference count alone misses both directions: a component can be absent from the prose
and still sit on the request path, or appear in the prose and do nothing.

| Surface | Files |
|---|---|
| lab and tour | `gitops/ai-layer/web/lab.html` (step 0 is the tour), `gitops/ai-layer/web/platform.html` |
| deck | `facilitation/slides-outline.md` |
| challenges | `challenges/` |
| run of show | `gitops/ai-layer/web/brief.html`, `facilitation/runbook.md`, `docs/RUN-OF-SHOW-2026-08.md` |
| terminal | `gitops/ai-layer/web-terminal/entrypoint.sh` (the `platform` catalogue) |
| verify harness | `verify/` |

**Not measured: install time.** The issue asks for install time before and after on a fresh attendee
cluster. That needs a cluster provisioned and torn down twice, which this run is not allowed to do. App
counts below are computed from the bootstrap selectors, not read off a cluster.

## App count, today

Computed from the `directory.include` / `exclude` selectors in `gitops/bootstrap/*/`:

| Profile | Child apps | With the root |
|---|---|---|
| attendee | 37 | 38 |
| full | 37 | 38 |
| admin | 39 | 40 |
| burn (Community) | 19 | 20 |

The issue says 39 for an attendee cluster; the selectors give 38 including the root, which is also what
`platform.html:75` tells the student. `gitops/apps/otel-collector-act2-overlay.yaml` is a comments-only
file sitting in the apps directory; it renders no object.

## Summary

Four of the issue's premises do not hold: agentgateway is not idle, Talon is not C3's responder,
`customer-stream` is not C1's target, and `require-resource-limits` is not part of the floor. The audit
also found three problems the issue did not list. The mesh enrolls nothing, so the tour's mTLS sentence is
false. `/display` still returns 404. The Community cluster's collector exports to two endpoints that do not
exist on that profile.

| Candidate | Verdict | Apps saved on attendee |
|---|---|---|
| `customer-stream` | **Remove.** Nothing reads it. C1's data comes from `workshop-mcp`, not from this stream | 1 |
| `chat-ui` | ~~**Remove.**~~ **Removed (#240).** A second chat front end, reachable only from `/console`, which nothing links | 0 (one Deployment, one Service) |
| `loki` + `alloy` | **Remove, after re-pointing one E2E test** at Datadog Logs, which already receives the same lines | 2 |
| `tempo` | ~~**Remove from attendee, keep on admin**~~ **Removed from attendee (#475)**, kept on admin and full, where builders read raw spans | 1 |
| `falco-talon` | ~~**Remove from attendee, keep on admin/full.**~~ **Removed from attendee (#475)**, kept on admin and full. Idle on attendee clusters | 1 |
| `rbac` | **Remove.** Binds roles to groups no identity belongs to | 1 |
| `resource-quotas` | **Remove or trim.** Quota nothing hits, PDBs for a disabled app | 1 |
| Istio (five apps) | **Decide.** The mesh encrypts nothing as built: no namespace is enrolled | 5 |
| `prometheus` + `grafana-dashboards` | Keep pending the Datadog-vs-Grafana call; three findings below | 0 |
| `agentgateway` | **Keep.** It is on the path of every chat message, model call and workshop tool call | 0 |
| `falcosidekick` | **Keep.** It is the only route for Falco's alerts into Datadog as events | 0 |
| `minimal-floor` | **Keep.** It does real work, but it misses the namespaces that matter most | 0 |
| `kyverno-policies` | **Keep.** C2 uses it. `require-resource-limits` is here, not in the floor | 0 |

Taking every removal above except the mesh gives an attendee cluster of 31 apps with the root, against
38 today. Dropping the mesh as well gives 26. The two biggest single wins are the mesh (five apps, two DaemonSets) and
the Loki/Alloy/Tempo trio (three apps, two 5Gi gp2 volumes per cluster).

## Observability

### Loki and Alloy: one consumer, and it has a substitute

No student-facing surface reads Loki. `platform.html:124` lists it with a port-forward and the deck names
it once in a list (`slides-outline.md:43`). Alloy is named nowhere outside its own app file and one test.

The one real consumer arrived today: `verify/test_tool_audit_live.py` (#190) proves the per-agent tool audit
trail by querying Loki for the `pre`/`post` lines `workshop-mcp` writes. The same lines already reach
Datadog, because the Datadog Agent runs with `containerCollectAll: true`
(`gitops/manifests/datadog/datadog-agent.yaml:27`), a fact the #190 entry in `decisions.md` relies on. Two
log stores receive the same stdout.

Removal touches `gitops/apps/{loki,alloy}.yaml`, the Loki datasource in `gitops/apps/prometheus.yaml`, the Loki
row in `platform.html`, the deck line, and the live half of `test_tool_audit_live.py`, which would query
Datadog Logs instead.

### Tempo: a builder's tool, not a student's

No challenge or tour step reads Tempo. Its users are us: `gitops/otel-collector/values.yaml:102` and `:181`
record measurements "read out of Tempo rather than out of Datadog" on `watch-it-burn-michael-admin`
(2026-09-07), and `challenges/03-bad-mcp-excessive-agency/OBSERVABILITY-RUNBOOK.md:9` was verified against
it. Raw spans with every attribute intact are worth keeping somewhere, and that measurement was taken on an
admin cluster. Excluding `tempo` from the attendee selector keeps the debugging lens where builders use it.

On the attendee profile that also needs the `otlp/tempo` exporter dropped from the collector (the attendee
overlay `values-dual.yaml` already restates the exporter lists) and the Tempo datasource removed from Grafana.
`verify/test_observability.py:51` and `:58` assert the Tempo exporter and change with it.

### Prometheus and Grafana

Michael set the Datadog-vs-Grafana question aside, so this audit does not recommend removing them. Three
findings belong to that decision whenever it is made:

- **Alerts that notify nobody.** `prometheus.yaml` ships `additionalPrometheusRulesMap` (NodeNotReady,
  PodCrashLoop, ArgoCDAppDegraded, FalcoCriticalAlert) with `alertmanager.enabled: false`. The rules
  evaluate and go nowhere.
- **Metrics collected twice.** kube-prometheus-stack runs node-exporter and kube-state-metrics, and the
  Datadog Agent collects the same node and object state through its own checks.
- **Grafana is exposed twice.** The chart's Ingress claims the fixed host `grafana.agenticburn.com` on the
  shared ALB group `watch-it-burn-ingress`, the same host on every cluster. The per-cluster
  `grafana-<cluster>` route students actually get comes from the console nginx
  (`gitops/ai-layer/console.conf:184`).

The cost panel is not wired to anything: `verify/test_observability.py:77` asserts the dashboard does
not use `witb_cost_usd`, and `docs/MASTER-RECREATION-SPEC.md:302` records that metric as dropped in favour
of `gen_ai.client.cost`. "Keep Prometheus only if the cost panel gets wired" has no panel to wire today.

### A live problem on the Community cluster

The burn profile installs `otel-collector` (with `values.yaml` only) but not `prometheus` or `tempo`. The
collector's metrics pipeline still exports to `prometheusremotewrite` and its traces pipeline to
`otlp/tempo` (`gitops/otel-collector/values.yaml:275`, `:292`), both pointing at Services that do not exist
on that profile. Every batch on the Community cluster is exported to two dead endpoints and retried. Datadog
still gets its copy, so nothing visible breaks. The fix is a burn values overlay with
Datadog-only exporter lists, the same shape as `values-dual.yaml`.

## Runtime security

### Falcosidekick is not a duplicate

Falco has one `http_output` URL and it points at Falcosidekick (`gitops/apps/falco.yaml:44-46`). Sidekick fans
out to Talon (critical only) and to Datadog (notice and above) (`gitops/apps/falcosidekick.yaml`).

The issue asks whether Datadog's own Falco integration already covers this. Only partly. The integration
is configured (`gitops/apps/falco.yaml:28-29`, the `falco` Autodiscovery check), but it scrapes Falco's
`/metrics`: event *counts* by rule and priority, not the alerts themselves. Falco's stdout also reaches
Datadog Logs through `containerCollectAll`, as log lines. The per-alert Datadog events, with the rule,
output and pod, come only from Sidekick. Removing Sidekick would lose them, so it stays.

### Falco Talon is idle on attendee clusters

The issue calls Talon "the responder C3 uses". It is not, and has not been since #344:

- Talon has two rules, Fork Bomb Response and Recipe Snoop Response (`gitops/apps/falco-talon.yaml`).
- Sidekick forwards only `critical` to Talon. `Recipe Snoop In Agent Namespace` is `WARNING`
  (`gitops/apps/falco.yaml:268`), so Talon never sees it. Its Recipe Snoop rule cannot fire.
- `Fork Bomb In Workload Container` is `CRITICAL`, but the fork bomb was retired as a student beat (#114).
  It survives only as an optional audience demo on the instructor box (`docs/RUN-OF-SHOW-2026-08.md:378`).
- The lab already says so accurately: "Here Falco is set to detect only" (`lab.html:486`), and
  `verify/test_c3_talon_claim.py` guards that sentence.

On an attendee cluster Talon runs and acts on nothing. Keeping it on admin/full preserves the fork-bomb demo.
`platform.html:166` ("Falco sees it and Talon reacts") is then wrong for attendees and needs a word change.
The lab's Talon link is a concept link, pinned by `test_concept_before_tool.py` and `test_doc_links.py`, and
does not depend on Talon being installed.

## Agent namespace

### agentgateway is load-bearing

The issue's premise was "if nothing routes through agentgateway it is idle". Three things route through it:

| Path | Where |
|---|---|
| every chat message: guard-proxy to the agent over A2A, port 3000 | `gitops/ai-layer/resources.yaml:607` |
| ~~every model call: both kagent ModelConfigs, port 3002~~ model calls only on a cluster switched to a `gateway-*` ModelConfig; the committed `bedrock-nova` calls Bedrock directly (corrected in #239, `2026-10-24-agentgateway-evaluation.md`) | `resources.yaml:60`, `:77` |
| every workshop-mcp tool call, port 3001 | `resources.yaml:836` |

The toggle script's "toolNames is the real control" is about C7's *authorization*: the rogue tools live on
`evil-mcp`, which the agent dials directly, so agentgateway's `mcpAuthorization` does not gate them. The
gateway still carries the traffic. One stale comment: `resources.yaml:321` says "the agent dials these MCP
servers directly", which is true of evil-mcp and false of workshop-mcp since `:836`.

### chat-ui duplicates BurritoBot

There are two chat front ends. BurritoBot (`burritbot.html`, served at `/` by the console nginx) is the
one every student uses. `chat-ui` is a separate nginx Deployment serving the older `index.html`/`app.js`,
reached only through `console.conf:129` (`/chat/`). The only thing that loads `/chat/` is the "Agent chat"
tab of `/console` (`console.html:73`), and nothing student-facing links `/console`; the August run of show
mentions it once (`docs/RUN-OF-SHOW-2026-08.md:137`).

**A defect turned up here.** `display.html` and `display.js`, the side-screen prompt stream, are packaged
into `chat-ui-src`, not `console-src` (`gitops/ai-layer/kustomization.yaml:33-38`). The console nginx mounts
`console-src` over its whole web root, so `location = /display { try_files /display.html =404; }`
(`console.conf:65`) finds no file and still returns 404. #338 was closed as fixed on 2026-09-08 after
running nginx against the source `web/` directory, which does contain the file. On a cluster the page is
reachable only as `/chat/display.html`. Moving the two files to `console-src` fixes `/display`, and it is
also the step that frees `chat-ui` to be removed.

**Done in #240:** the display files moved to `console-src`, `/console`'s Agent tab now loads BurritoBot, and
chat-ui is gone. The list below is what that removal touched.

Removing chat-ui touches: its Deployment and Service in `resources.yaml`, the `chat-ui-src` generator, the
`/chat/` location, the second tab of `console.html` (or `/console` entirely), `verify/test_chat_ui.py`, and
the chat-ui row in `verify/test_manifest_contract.py`.

### customer-stream is not what C1 reads

The issue says to keep `customer-stream` as the C1 exfil target. It no longer is. C1 asks how many
customers are humans and how many are vampires (`lab.html:314`). That answer comes from
`get_marketing_intel`, which reads `marketing.json` from workshop-mcp's own filesystem
(`gitops/ai-layer/workshop-mcp-server.py:71-81`, `:183-185`). The generator-to-consumer stream in `apps`
predates the switch from the S3 push to the chat leak (`challenges/c1-exfil-s3/README.md:4-8`). No lab,
deck, tour or challenge text references it, and no tool calls it.

Removal touches `gitops/apps/customer-stream.yaml`, `gitops/manifests/customer-stream/`, the burn selector,
`verify/test_customer_stream.py`, and a comment in `verify/test_no_permanent_drift.py`. No student-facing
text changes.

## Mesh: installed, enrolling nothing

The five Istio apps install the ambient control plane and data plane, and `istio-mesh-config` sets STRICT
mTLS on `agent` and `apps` (`security/istio/peer-authentication.yaml`). Ambient captures a pod's
traffic only when its namespace or the pod carries `istio.io/dataplane-mode=ambient`. **No file in the
repository sets that label.** The only mention is the `verify-at-build` note at the top of
`peer-authentication.yaml` saying it still has to be added. As built:

- ztunnel runs on every node and captures nothing.
- The STRICT PeerAuthentications apply to no traffic.
- The tour tells every student that the mesh "encrypts all traffic between containers inside the cluster,
  automatically" (`lab.html:281-282`). That is not true on a stock cluster.

This is from git, not from a live cluster; `kubectl get ns -L istio.io/dataplane-mode` on any attendee
cluster would confirm it. The issue's "ELB/quota surface" does not apply. No gateway chart is installed,
so the mesh creates no load balancer. Its cost is five apps, two DaemonSets (`istio-cni`, `ztunnel`) and
istiod.

The two ways out:

1. **Enroll `agent` and `apps`.** Then the sentence is true. It needs a live check that STRICT mTLS
   coexists with the C1 egress NetworkPolicy (HBONE uses port 15008), the KubeArmor policy and the probes.
   (#238 found it is more than a label: STRICT on an enrolled `agent` rejects the console's ip-target
   NLB and kagent's controller, and `apps-allow-ingress` would refuse 15008. See
   `2026-10-24-istio-ambient-evaluation.md`, section 3.)
2. **Drop the five apps and the sentence.** No challenge uses a mesh control, `verify/test_mesh.py` goes, and
   the Istio rows in `test_datadog_service_map.py` and `test_observability.py` change.

The sentence is false today either way. If nothing else changes, at minimum the tour should stop saying it.

## Policy floor

### require-resource-limits is in kyverno-policies, not the floor

`policies/floor/minimal-floor.yaml` does one thing: it denies DELETE of protected namespaces and of
workloads in platform namespaces. `require-resource-limits` is in `policies/kyverno/` and ships through
`kyverno-policies`. Several comments in the repo call it "the floor" (`gitops/apps/prometheus.yaml:113`,
`:120`, `infra/argocd-values.yaml:14`), which is probably where the issue's framing came from.

On attendee clusters `require-resource-limits` ships `Audit` and stays there. The student's C2 step patches
only `restrict-image-registries` (`lab.html`, Challenge 2), and `fleet.sh` arms both policies only on the
full and admin profiles (`infra/terraform/fleet/fleet.sh:1009`). So on attendee clusters it blocks nothing and produces the PolicyReport failures and
PolicyViolation events the issue saw on the evil-mcp and workshop-mcp ReplicaSets. On full and admin it is
armed, and it is why every chart now carries limits (#234). It is noise on attendee clusters and a working
control on the armed ones. If the attendee noise matters, the cheapest option is to exclude the policy file
on attendee with a second `kyverno-policies` source, not to edit the policy.

### The burn cluster has no floor at all

`gitops/apps/minimal-floor.yaml:1-2` says the app is separate "so the burn cluster can keep the floor", and
the floor's own header calls it "Cluster 1's ONLY restriction". Both are stale: the burn selector includes
neither `kyverno` nor `minimal-floor` (`gitops/bootstrap/burn/app-of-apps-burn.yaml:46`). Nothing
floor-related is burn-only. Everything the floor does runs on attendee, full and admin.

### The floor misses the namespaces that matter

The floor's header says it protects "ArgoCD/Kyverno/Falco/the agent". Its namespace list is `argocd`,
`kyverno`, `falco`, `monitoring`, `kagent` and the kube-* namespaces. Falco runs in `security`
(`gitops/apps/falco.yaml:321`); `falco` holds only Talon. BurritoBot runs in `agent`. Neither `security` nor
`agent` is protected, and neither is `datadog`. If Talon leaves the attendee profile, the `falco` entry
protects an empty namespace there. Argo CD's selfHeal recreates a deleted workload regardless, so this is a
gap in the floor's stated intent, not an outage.

### rbac and resource-quotas

- `rbac` (`security/rbac/`) binds `app-developer` and `app-viewer` in `apps` to the groups `app-developers`
  and `app-viewers`. No access entry, IAM mapping or test grants anyone those groups, and C8's RBAC lesson
  uses the `agent-sa` Role in the ai-layer instead. The bindings grant nothing to anyone.
- `resource-quotas` (`security/quotas-pdbs/`) caps `apps` at 20 pods and 8 CPU requested, which the five
  party apps do not approach, and ships PodDisruptionBudgets with `minAvailable: 1` for single-replica
  argocd-server, repo-server, Prometheus and Grafana, plus one for Backstage, which is disabled
  (`gitops/apps-disabled/`). Neither app is referenced by the lab, the deck, the tour or a challenge.

## Not duplicates, on inspection

These looked like pairs and are not: each half does a different job.

- `otel-collector` and the Datadog Agent: the collector carries traces and LLM Observability, the Agent
  carries logs, infrastructure metrics and the named integrations.
- `otel-operator` and `ai-layer-otel`: the operator is the injection webhook, `ai-layer-otel` is the
  `Instrumentation` it reads.
- Kyverno, KubeArmor and Falco: admission, inline kernel enforcement and detection. C2 and C3 each use
  exactly the one they teach, and C3 deliberately shows Falco and KubeArmor side by side.
- `external-secrets`/`eso-resources`, `kagent-crds`/`kagent`, `datadog-operator`/`datadog-agent-cr`:
  engine and configuration, split for sync ordering.
- The five `*-party` apps: deliberate filler, named as such in the tour (`lab.html:289-291`).
