# PRD #389: Upgrade every component to latest GA

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/389
**Inventory**: [`docs/UPGRADE-INVENTORY.md`](../docs/UPGRADE-INVENTORY.md) (measured 2026-09-10)
**Priority**: Medium. Nothing is broken; the stack is simply drifting, and drift gets more expensive per month.
**Status**: Not started. Phase 1.2 (plan written, awaiting approval).

---

## Problem

Seventeen of twenty-one Helm charts are behind their latest release, and three components outside Helm
are behind as well: kagent (0.9.9, latest 0.10.1), agentgateway (v1.3.0, latest v1.5.0) and the EKS
control plane (1.35, with 1.36 in standard support). Two components are already current and need no
work: falco/falcosidekick and LLM Guard 0.3.16.

The stated goal is **the latest GA of each application**. That is not the same as the latest Helm
chart, and treating them as the same is how the drift accumulated. Charts number independently of the
software they install:

| Chart | Chart version | App it ships |
|---|---|---|
| opentelemetry-collector | 0.172.1 | collector 0.159.0 |
| kube-prometheus-stack | 90.0.0 | Prometheus Operator v0.93.1 |
| argo-cd | 10.8.4 | Argo CD v3.5.2 |

**The chart must not be the ceiling.** Where a newer application release exists and the chart has not
caught up, the image tag is overridden in the Application's Helm values and the newer image is taken
directly. That works whenever the delta is a straight image bump.

It does **not** work when the new version requires new CRDs or a changed values schema, because the
chart owns both. Those cases are named per component below rather than discovered during a rollout,
and for them the options are: wait for the chart, or vendor the upstream manifests into `gitops/` and
drop the chart for that component. The second option is on the table and is what "not constrained by
Helm charts" means in practice.

## The constraint that shapes everything

**There are no clusters.** The fleet was destroyed to zero after Portland, verified across five
accounts and seventeen regions. Every upgrade needs a live cluster to validate, and a cluster takes
15 to 25 minutes to build. **Provisioning passes are the cost driver, not version research.**

The plan therefore optimises for *few passes with many changes each*, which is the opposite of the
usual advice to change one thing at a time. The mitigation for that trade is the tier structure: each
tier groups changes with a shared blast radius, so a failed tier is diagnosable without bisecting
across unrelated components.

---

## Solution: four tiers, cheapest first, Argo CD last

Each tier is one branch, one cluster, one verification pass. A tier that fails is fixed or reverted
before the next begins. **Argo CD is upgraded last in every scenario**, because it is the tool
performing all the other upgrades and losing it mid-rollout means hand-reconciling the fleet.

### Tier 1: patch bumps (low risk, cheap win)

| Component | From | To |
|---|---|---|
| istio base / cni / istiod / ztunnel | 1.30.1 | 1.30.4 |
| kyverno | 3.9.0 | 3.9.1 |
| falco-talon | 0.4.1 | 0.4.2 |
| cert-manager | v1.20.3 | v1.21.1 |

All are same-minor or single-minor moves within a stable API. cert-manager is the only one crossing a
minor; check its release notes for CRD conversion, since cert-manager has historically shipped CRD
changes on minors and the console certificate depends on it (#139).

**Exit**: `verify/` green, all Argo CD apps Synced+Healthy, console TLS still issued, a BurritoBot
message round-trips.

### Tier 2: the application layer (medium risk, highest value)

| Component | From | To | Watch for |
|---|---|---|---|
| kagent + kagent-crds | 0.9.9 | 0.10.1 | **CRD group is `kagent.dev/v1alpha2`.** An alpha API across a minor is exactly where fields move. Our Agent CR uses `toolNames`, `modelConfig`, `systemMessage`. 0.10 adds `requireApproval` and Bedrock Guardrails in ModelConfig. |
| agentgateway | v1.3.0 | v1.5.0 | Two minors on the component behind #382. **Version-line question unresolved** (see Open Questions). |
| external-secrets | 2.6.0 | 2.10.0 | Four minors; ESO owns cluster secret plumbing, so a break costs every Datadog key. |
| datadog-operator | 2.23.2 | 2.26.0 | Operator 2.26 ships agent 1.30.0; confirm the Agent CR schema still matches. |
| opentelemetry-operator | 0.117.0 | 0.122.0 | The Instrumentation CR and the injection webhook. See [[otel-injection-fails-open]]: a pod created before the webhook serves never traces. |
| opentelemetry-collector | 0.158.2 | 0.172.1 | Collector config schema churns often between minors. |
| alloy, loki, backstage | see inventory | latest | Observability scenery; lowest consequence in this tier. |

**Exit**: Tier 1 exit criteria, plus traces reaching Datadog with tool spans present, guard toggles
working through `/controls`, and all eight challenge attacks landing at their measured rates.

### Tier 3: EKS 1.35 to 1.36

Control plane, then node groups, then addons (vpc-cni, coredns, kube-proxy, ebs-csi). Everything in
tiers 1 and 2 rides on this, so it goes after them: a workload failure on a new control plane is
otherwise indistinguishable from a failure caused by the component upgrades.

**Watch for** removed APIs in 1.36 and the EBS CSI driver, which has already caused PVC release
problems during teardown.

**Exit**: a cluster built from scratch on 1.36 passes the full `verify/` suite and a complete
walkthrough of all eight challenges.

### Tier 4: Argo CD 9.6.0 to 10.8.4 (app v3.5.2)

A major chart jump on the component that manages every other component.

**Watch for**: `Application` and `ApplicationSet` schema changes; the multi-source root app-of-apps
pattern (#253), which is the least standard thing we do and therefore the most likely to break; and
RBAC/config-map key renames across the major.

**Exit**: every root app reconciles itself from `staging` as before, `selfHeal` and `prune` behave,
and the drift-block policy still denies non-Argo changes.

---

## Where the chart is a ceiling, and what to do about it

Three cases, in increasing order of cost:

1. **Chart current, app current**: nothing to do. Bump `targetRevision`.
2. **Chart behind app, straight image bump**: override `image.tag` in the Application's Helm values.
   Record why in a comment next to the override, or the next reader assumes it is accidental drift.
3. **Chart behind app, needs new CRDs or a changed values schema**: the override cannot work. Either
   wait for the chart, or **vendor the upstream manifests into `gitops/` and stop using the chart for
   that component**. Vendoring is a real option here and should be chosen deliberately, per component,
   not as a blanket policy: it trades chart maintenance for manifest maintenance, and it is only worth
   it where the app moves faster than its chart consistently does.

## Verification

Each tier is gated on the same three things, in order:

1. **Offline**: the `verify/` suite (approximately 66 standalone checks). Free, no cluster.
2. **Live smoke**: one cluster, `fleet.sh up` a single attendee build, console reachable, BurritoBot
   answers, traces arrive in Datadog.
3. **Behavioural**: `verify/agent_probe.py` against the measured landing rates. A component upgrade
   that silently changes model behaviour shows up here and nowhere else.

Step 3 matters most for tier 2. kagent 0.10's Bedrock Guardrails and `requireApproval` are capable of
**defusing challenges 5, 6 and 7 outright** if they default to on. That is a workshop regression that
no health check would catch, because every pod would be Running and every app Synced.

## Risks

- **Upgrading defuses the workshop.** The real hazard of this PRD. Guardrail features added upstream
  can block the very attacks the challenges depend on. Mitigation: behavioural probe in every tier
  exit, and treat any new guardrail as a candidate ninth challenge rather than a default-on setting.
- **No rollback for EKS minor versions.** AWS does not support downgrading a control plane. The
  rollback for tier 3 is to build a new cluster on 1.35, which is why tier 3 is validated on a
  from-scratch build rather than an in-place upgrade.
- **Losing Argo CD mid-rollout.** Mitigated by ordering alone: it is last.
- **Batching changes obscures the cause of a failure.** Accepted deliberately, to reduce provisioning
  passes. Mitigated by grouping each tier by shared blast radius.

## Open questions

- **RESOLVED 2026-09-10, agentgateway version lines.** The artifact is **v1.5.0**. The `2.2.x` in
  documentation URLs is a docs tree, not a binary version; the Kubernetes and standalone distributions
  are documented separately and both resolve. Tier 2 targets the release tag v1.5.0.
- **RESOLVED 2026-09-10, tempo.** Measurement error, not an ambiguity: the wrong chart repo was queried.
  Single-binary goes **2.2.3 -> 2.3.0** (app 2.10.7 -> 2.10.8), a patch bump. Tempo **3.0.3** is only
  available through the **`tempo-distributed` chart 3.5.1**, which is a microservices deployment rather
  than one pod and therefore a different change with a different resource budget. Tier 1 takes 2.3.0;
  moving to Tempo 3 is separate work with its own justification.
- **ANSWERED 2026-09-10, why not Kubernetes 1.37.** Because EKS does not offer it. Upstream Kubernetes
  is v1.37.0, but `aws eks describe-cluster-versions` lists **1.36 as the highest and the default**
  (standard support to 2027-08-02), then 1.35 and 1.34. 1.36 is the ceiling available to us, and moving
  1.35 -> 1.36 buys roughly five extra months of standard support.
- `[Answer]:` **Do we want kagent 0.10's Bedrock Guardrails at all?** They overlap guard-proxy
  directly. Turning them on is a design decision about the workshop, not an upgrade detail.
- `[Answer]:` **How many provisioning passes is this worth?** Four tiers means at least four cluster
  builds. If the answer is "fewer", tiers 1 and 2 can merge at the cost of harder diagnosis.

## Out of scope

- The agentgateway guardrails question (its own work; see #388 and the guardrail-taxonomy note).
- Rebuilding our own images (`web-terminal`, `workshop-mcp`, `sample-app`) for base-image CVEs. Worth
  doing, unrelated to version drift.
- Anything that changes challenge content. This PRD upgrades the platform; it does not redesign beats.
