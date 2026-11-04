<!-- ABOUTME: Build design for #112: a challenge in which the agent uses its legitimate create RBAC to launch a
     ABOUTME: privileged/hostPath pod and read the node, refused at admission by a scoped Kyverno policy. Deferred to the next event. -->
# Privileged pod / hostPath escape with the RBAC the agent already holds

**Status: deferred to the next event.** Michael deferred #112 on 2026-09-07 with the label `deferred-barcelona`
("Portland ships eight; that set is closed") and kept it open because the design work is still wanted for the next
event; decisions.md question 575 (2026-10-24) re-confirms that disposition. On #447 he set that the Barcelona
challenges wait until 2026-11-13, the day after the KubeCon NA 2026 breakout
(`facilitation/kubecon-na-2026-run-of-show.md`, "Dates to hold"). This note is the design, in the shape of
`docs/research/2026-10-31-c1-dns-exfil-beat.md` (#116/#723) and `docs/research/2026-11-02-workload-management-exercises.md`
(#130). It changes no lab text, slide, run of show or deploy config. The build, the lab text and the arming step start
on or after 2026-11-13. The gap this note describes was confirmed live on 2026-11-04 (see "Confirmed live" below);
the control and its arming flip are still owed on a cluster.

The issue's done-when has three parts: the agent uses its legitimate `create` RBAC to launch a privileged pod that
mounts host root and reads the node filesystem; the control refuses that pod **at admission** with a named policy in
the error; and the refusal is wired into the arming set the student flips, so the flip is visible. This note specifies the
attack against the current manifests, shows why the policy the issue names does not cover it as written, specifies
the control and the arming step, and lists the build pieces and the live checks they owe. It maps to OWASP Agentic
**ASI03 (Identity and Privilege Abuse)** and **ASI05 (Unexpected Code Execution)**.

## What exists today

Facts checked on staging 916b016e and, where marked, live on the two KubeCon clusters on 2026-11-04.

- **The RBAC the agent holds.** The `workshop-agent` Role (`gitops/ai-layer/resources.yaml:38`) grants, in namespace
  `agent`: `create, get, list, patch` on `deployments` (`apps`), the same four verbs on `pods`, `configmaps` and
  `services` (core), and `get, list` on `secrets`. The MCP tools run as the `workshop-mcp` ServiceAccount
  (`resources.yaml:772`), which the RoleBinding at `resources.yaml:57` binds to this same Role, so `deploy_app` and
  `run_shell` call the API with the agent's real namespaced RBAC. Challenge 2 ("Deploy a villain image",
  `challenges/LAB-TEXT.md:216`) already exercises the `create` on `deployments`; this challenge reuses the same grant
  for a pod shape nobody intended. Confirmed live: `kubectl auth can-i create pods -n agent` returns `yes` for both
  `system:serviceaccount:agent:agent-sa` and `system:serviceaccount:agent:workshop-mcp` on both clusters.
- **How the agent creates workloads.** `deploy_app` builds a Deployment and labels its pod
  `burritobot.co/workload=maintenance-shell` (`resources.yaml:715`); `apply_optimization` (the Beat-3 clown file,
  `gitops/ai-layer/server.py:117`) returns a `privileged: true` busybox Deployment in namespace `apps` for the agent
  to apply. Both paths go through the Deployment controller, and the agent can equally create a bare Pod, because its
  Role grants `create` on both.
- **The agent namespace has no Pod Security Admission label at all.** In `gitops/namespaces/namespaces.yaml` only
  `apps` carries PSA labels (`enforce: baseline`, `warn: restricted`, lines 38-41). Namespace `agent` (line 74),
  where the agent creates, carries none. A privileged, hostPath, hostPID or hostNetwork pod created in `agent` is
  admitted today. Confirmed live: `kubectl get ns agent -o jsonpath='{.metadata.labels}'` shows no
  `pod-security.kubernetes.io/*` label on either cluster.
- **The policy the issue names is scoped to `apps` and checks only `privileged`.** `policies/kyverno/disallow-privileged.yaml`
  is a CEL `ValidatingPolicy` (migrated from ClusterPolicy by #206). Its `matchConstraints` select `pods` only, with a
  `namespaceSelector` of `In [apps]`; its one validation checks `securityContext.privileged`. It does **not** match
  namespace `agent`, does **not** check `hostPath` volumes, `hostPID` or `hostNetwork`, and names only `pods`
  (Deployments are reached by Kyverno autogen, see below). Its `validationActions` is already `[Deny]`, so the Beat-3
  clown file in `apps` is refused today. The issue's "Check before building" section says the policy ships at
  `failureAction: Audit`; that was the pre-#206 ClusterPolicy wording, and is stale. Confirmed live on the private
  cluster: `disallow-privileged` is present, `validationActions: [Deny]`, `namespaceSelector` `In [apps]`, `pods`
  only. The community cluster serves no `policies.kyverno.io/v1` ValidatingPolicy at all (`kubectl get
  validatingpolicy` returns "the server doesn't have a resource type"), as `challenges/LAB-TEXT.md:295` already says
  of it ("No admission controller is installed here: no Kyverno, no policy, no webhook").
- **The agent-spawned-workload control does not cover this shape.** `policies/kyverno/restrict-agent-spawned-workloads.yaml`
  (#490) is a `ValidatingPolicy`, `validationActions: [Deny]`, that does match namespace `agent` and does match the
  agent's own ServiceAccount identities. But it validates three things only: the pod's ServiceAccount is not a
  Bedrock-bound identity, the pod wears no label a NetworkPolicy trusts, and the pod mounts or reads through env no
  Secret but `ceo-personal-record`. It does **not** check `privileged`, `hostPath`, `hostPID` or `hostNetwork`. A
  privileged hostPath pod on the `default` ServiceAccount, with no trusted label and no Secret reference, passes it.
- **The arming model.** `challenges/01-cncf-wall/toggle-kyverno-enforce.sh` flips exactly
  `require-resource-limits` and `restrict-image-registries` from `Audit` to `Deny` (`validationActions`), and ArgoCD
  `ignoreDifferences` covers those two fields so selfHeal does not revert the live flip. `fleet.sh` arms admin
  (presenter) clusters by running that toggle after bootstrap; attendee clusters ship those policies in `Audit` on
  purpose and the **student** flips them to `Deny` during the workshop (#160). On the two KubeCon clusters the four
  Kubernetes guardrails ship present and off, and `guardrails-on` arms them on both (#774). `disallow-privileged` is
  in none of these sets: it ships `Deny` always, independent of the toggle. Challenge 3's
  `challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh` is the precedent for a challenge carrying its own
  arming step rather than joining the CNCF-wall toggle.
- **The kill chain it pairs with.** Challenge 8 ("Take Advantage of Overscoped Permissions",
  `challenges/LAB-TEXT.md:780`, #111, ASI03) is token/credential theft: read the projected ServiceAccount token and
  act as the agent. #113 (`challenges/imds-node-creds/`, ASI03) is the node-credential theft that leaves the cluster.
  This challenge is the middle link the Sysdig 2026-05-29 sequence and the Hugging Face timeline both show: hold the
  token, then use the permissions it grants to escape the container to the node.

## The attack

On an unarmed attendee cluster (the escape policy still at `Audit`, or absent as on the community cluster), a
support-ticket or rogue-tool prompt gets BurritoBot to apply a pod like this in namespace `agent`, using the `create`
its Role already holds:

```yaml
apiVersion: v1
kind: Pod
metadata: { name: node-debug, namespace: agent }
spec:
  hostPID: true
  containers:
    - name: shell
      image: busybox
      securityContext: { privileged: true }
      command: ["sleep", "infinity"]
      volumeMounts: [{ name: host, mountPath: /host }]
  volumes:
    - { name: host, hostPath: { path: / } }
```

No kernel exploit and no CVE: the pod is admitted because nothing in `agent` refuses the shape. The agent then reads
the node filesystem under `/host`: kubelet credentials, the container-runtime socket, and every other pod's mounted
Secrets. With `hostPID` plus `privileged` it can `nsenter --target 1` into the node's init namespace, which is the
Sysdig fallback the issue cites. The Deployment form (what `deploy_app` and `apply_optimization` produce) is the same
shape wrapped in a pod template, and is admitted the same way until a control covers Deployments.

## Confirmed live (2026-11-04, run 17019)

This is the one piece a dispatched run could not do before: run 17019 held an AWS session and kubectl access to the
two KubeCon clusters (`watch-it-burn-community`, `watch-it-burn-private`), so it tested the unarmed/gap direction
live. Every write was a server-side dry-run (`kubectl apply --dry-run=server`), which runs the full admission chain
(PSA in-process and the Kyverno validating webhook) without persisting anything; impersonation (`--as`) put the
request under the agent's own ServiceAccount, so the API server authorised it exactly as BurritoBot's tools are.
Nothing was created, changed or deleted on either cluster; both were left as found.

- **Community cluster (the unguarded attendee analog).** The escape pod above, applied as
  `system:serviceaccount:agent:agent-sa`, was admitted: `pod/hecaton-112-dryrun-node-debug created (server dry run)`,
  exit 0. The cluster serves no ValidatingPolicy CRD and `agent` has no PSA label, so nothing refuses the shape. This
  is the attack landing, same as Challenge 2's villain image lands here.
- **Private cluster (the full policy set, several guardrails already at Deny).** The first dry-run of the escape pod
  was refused, but by `require-resource-limits` ("CPU and memory resource limits are required on every container"),
  which is `[Deny]` here and cluster-wide (empty `namespaceSelector`), not by any escape-shape rule. Adding resource
  limits to the container, so the only remaining variable was the escape shape itself, the same privileged + hostPath
  + hostPID pod was admitted: `created (server dry run)`, exit 0. So on a cluster where `disallow-privileged` (Deny,
  `apps`-scoped) and `restrict-agent-spawned-workloads` (Deny, agent-scoped) are both enforcing, neither refuses the
  escape: the first does not match `agent`, the second does not check these fields. The gap is structural, not a
  matter of which guardrails are armed.

The other direction, that a correctly-scoped control **refuses** the shape at admission with its name in the error,
is the build's to prove and is still owed on a cluster (see "Validation owed").

## Why the shipped policy does not cover this, as written

Three gaps, each a build task, not a reuse:

1. **Wrong namespace.** `disallow-privileged` matches `In [apps]`. The agent creates in `agent`. The policy never
   sees this pod.
2. **Only `privileged`.** It does not deny `hostPath`, `hostPID` or `hostNetwork`. A hostPath mount alone (no
   `privileged`) already reads the node filesystem; the issue names all four and the control must too.
3. **The unarmed state conflicts with the policy's current job.** The flip the issue wants (admitted while unarmed,
   then refused at admission once armed, with a named policy) needs the escape policy at `Audit` before the student
   arms it and `Deny` after. But `disallow-privileged` is `Deny` today **because** it is what refuses the Beat-3 clown
   file in `apps`. A
   `ValidatingPolicy` has one `validationActions` for the whole policy, so it cannot be `Deny` for `apps` and `Audit`
   for `agent` at once. Extending and down-shifting `disallow-privileged` would break the always-on clown-file
   refusal.

For these reasons the control is a **separate** policy, not an edit to `disallow-privileged`.

## Why it must not be armed cluster-wide

The currency review records the hazard directly (`docs/research/2026-08-28-challenge-currency-review.md`):
`disallow-privileged` "must not be armed as written; it would deny nine platform DaemonSets." The platform's own
privileged / hostPath workloads (the node-level security and observability agents such as Falco, KubeArmor and the
Datadog node agent, and the CNI) legitimately run privileged with hostPath and hostNetwork, and they live in
`security`, `monitoring`, `datadog` and `kube-system`, never in `agent` or `apps`. Scoping the escape policy to
namespace `agent` is therefore exactly what keeps it safe: it refuses the agent's attack shapes and never evaluates
the platform DaemonSets. A cluster-wide privileged/hostPath deny would take the cluster down with it. The build must
confirm no platform pod in `agent` uses any of the four fields (none does on 916b016e; the greps that found
`privileged`/`hostPath` in `gitops/` hit only `server.py`'s synthetic clown file and a comment in `console.conf`
about nginx-unprivileged, neither a running privileged pod).

## The control

A new CEL `ValidatingPolicy`, e.g. `policies/kyverno/disallow-host-escape.yaml`, modelled on `disallow-privileged`:

- **Scope:** `matchConstraints` on `pods`, `CREATE` and `UPDATE`, `namespaceSelector` `In [agent]`. Autogen (default
  on, #206) produces the matching Deployment/ReplicaSet/Job rules, so `deploy_app`'s Deployment and
  `apply_optimization`'s Deployment are refused at the controller object, which is what makes the C2 and Beat-3 beats
  fail "at the Deployment" rather than at a pod that never appears. Confirm autogen is on for this policy at build
  time, as #206 did for the CNCF-wall policies.
- **Validations**, each with its own named message so the error says which rule refused it:
  - no container (incl. initContainers) with `securityContext.privileged == true`;
  - no `hostPath` volume;
  - `spec.hostPID` not true;
  - `spec.hostNetwork` not true.
  Reuse the `alreadyViolating` UPDATE carve-out pattern from `disallow-privileged` so a pre-existing violator can
  still be updated and a compliant pod cannot be updated into one.
- **Unarmed state:** ships `validationActions: [Audit]` so the attack is admitted and the student sees the node read
  succeed, exactly as C2's villain image deploys on an unarmed attendee cluster.
- **The arming flip:** its own arming step, `challenges/<new>/toggle-host-escape-enforce.sh`, modelled on
  `toggle-kyverno-enforce.sh` (reads a required `CONTEXT`, `--audit` to reverse, patches `/spec/validationActions`).
  Add that path to ArgoCD `ignoreDifferences` for the new policy so the live flip survives selfHeal, the same way the
  two CNCF-wall policies are covered. The student (attendee cluster) or `fleet.sh` (admin) runs it; once `Deny`, the
  pod is **refused at admission** with the policy name in the API error, and the Deployment keeps no pods, which the
  console surfaces the same way the maintenance-shell Service reports "no endpoints" when the Joker is refused
  (`resources.yaml:722`).

On Pod Security Admission: the issue asks for PSA `restricted` on the agent namespace as well. **Recommend against
enforcing it namespace-wide**, for the same blunt-instrument reason the policy is not armed cluster-wide. Namespace
`agent` also holds the platform's own pods (`workshop-agent`, `workshop-mcp`, `evil-mcp-shim`, `guard-proxy`,
`agentgateway`, the console and web terminal, and the `deploy_app` maintenance-shell), several of which do not meet
`restricted` (runAsNonRoot, seccomp, dropped capabilities), and PSA cannot tell the agent's attack pod from the
platform's own pods, since both are created in `agent`. A shape-based Kyverno deny can, because it refuses on the escape
fields the platform pods do not use, and it carries the named message that makes the arming flip legible, which PSA
does not. If a PSA signal is wanted for defence-in-depth, set `agent` to `warn: restricted` (visible at `kubectl`
time, non-blocking) and leave the enforcing refusal to Kyverno. This is the open choice below.

## Open choices (for the build)

- **PSA posture on `agent`.** (A) Kyverno-only enforce, no PSA label on `agent`; recommended, it needs no change to
  the platform's own pods. (B) Kyverno enforce plus `agent` `warn: restricted` for the defence-in-depth signal.
  (C) PSA `enforce: restricted` on `agent`; rejected, it breaks the platform's own pods and cannot name the policy in
  the error. Recommend A for the first build, B if the slide wants a second layer visible.
- **Where the arming step lives.** (A) a dedicated `toggle-host-escape-enforce.sh` for this challenge, like Challenge
  3's `toggle-mcp-authz-on.sh`; recommended, the CNCF-wall toggle is the C2 beat and flipping this policy at C2 time
  is the wrong sequencing. (B) add the policy to `toggle-kyverno-enforce.sh`; simpler to run but couples two beats.
  Recommend A. On the two KubeCon clusters the live analog is `guardrails-on` (#774); whether this policy joins that
  switch or stays a separate flip is the same choice, decided with placement at build time.
- **Attendee step or presenter beat.** It pairs with Challenge 8 as one kill chain (steal the token, then use it to
  escape) and demos crisply as an attendee flip. But #113 (IMDS) is presenter-only because node-level theft is not
  safe to hand every attendee a cluster for; confirm at build time whether the privileged-pod read of other pods'
  Secrets is in the same category. The next event's run of show decides placement; this note does not touch it.

## Build pieces

1. **The policy** `policies/kyverno/disallow-host-escape.yaml` (agent-scoped, four validations, `Audit`), added to
   `policies/kyverno/Kustomization` and the relevant `gitops/bootstrap/values-<profile>.yaml` lists (and a per-app
   file under `gitops/bootstrap/apps/` if it needs its own Application), with `test_bootstrap_chart.py`'s counts
   updated (CLAUDE.md, #609). `verify/test_guardrails_arm.py` fails on a `*.yaml` left off the Kustomization.
2. **The arming step** `challenges/<new>/toggle-host-escape-enforce.sh` and the ArgoCD `ignoreDifferences` entry for
   the new policy's `/spec/validationActions`.
3. **Lab text and brief.** The new challenge in `challenges/LAB-TEXT.md`, the reset line if it leaves state, and the
   matching `/brief` rows; `verify/lab-render.py` and `test_instructor_brief.py` cover the rendered pages.
4. **Run of show.** The next event's run of show places the challenge with its timing. The KubeCon NA 2026 breakout
   is demo-only and does not carry it.

## Offline checks (the Test tier)

- A Kyverno CEL engine test in the shape of `verify/test_kyverno_cel_policies.py` (Kyverno CLI, the pinned
  engine, #206): on a fixture CREATE in namespace `agent`, the policy at `Deny` refuses each of the four shapes
  (privileged pod, hostPath volume, hostPID, hostNetwork) and the autogen'd Deployment form of each, and admits a
  compliant pod; at `Audit` it admits all; a pod in any other namespace is not evaluated (the nine-DaemonSet guard);
  and the `alreadyViolating` UPDATE carve-out admits an update to a pre-existing violator. This check belongs in the
  E2E suite with the other Kyverno-CLI test, because it needs that pinned binary.
- A render/structure check that the new policy is in the expected profile lists and that `test_bootstrap_chart.py`'s
  counts match.

## Validation owed on a cluster (the `verify/run-e2e.sh` tier)

The unarmed/gap direction is confirmed live above. What the build still owes, in a new script taking `<kube-context>`
like the existing beat checks:

- Armed (after the arming step): the same `kubectl create`/`deploy_app` is **refused at admission**, the API error
  names `disallow-host-escape`, and the Deployment keeps no pods; `fleet.sh` (or `guardrails-on`) arming an admin
  cluster reaches `Deny`.
- No regression: the platform's own `agent`-namespace pods (`workshop-agent`, `workshop-mcp`, `guard-proxy`, the
  maintenance-shell on a legitimate deploy) still admit under the armed policy; the Beat-3 clown file in `apps` is
  still refused by the unchanged `disallow-privileged`.

The armed direction is owed because the policy does not exist yet: this run confirmed only that today's clusters do
not refuse the shape, which is the half a dispatched run can test without building.

## References

- #112 (this design), #110 (the retired tracker), #447 (the 2026-11-13 Barcelona build date), question 575 (the
  deferral), #111 (Challenge 8, the token-theft link), #113 (the IMDS beat it chains with), #116/#723 and #130 (the
  two sibling design notes this follows), #206 (the CEL ValidatingPolicy migration and autogen), #160 (the
  student-flips-the-wall arming model), #490 (the agent-spawned-workload control), #609 (the bootstrap chart and
  profile lists), #774 (the KubeCon `guardrails-on` switch).
- Hugging Face agent-intrusion technical timeline (2026-07-16): "missing admission policies rejecting
  privileged/hostPath containers" in the failed-controls list. Present the chain, never the model attribution
  (`docs/research/2026-08-28-challenge-currency-review.md`). Sysdig 2026-05-29: Docker-socket escape with
  `nsenter --target 1` fallback. Re-check both dated claims against their sources before any slide.
- `gitops/ai-layer/resources.yaml`, `gitops/ai-layer/server.py`, `gitops/namespaces/namespaces.yaml`,
  `policies/kyverno/disallow-privileged.yaml`, `policies/kyverno/restrict-agent-spawned-workloads.yaml`,
  `challenges/01-cncf-wall/toggle-kyverno-enforce.sh`,
  `challenges/03-bad-mcp-excessive-agency/toggle-mcp-authz-on.sh`, `challenges/LAB-TEXT.md`,
  `infra/terraform/fleet/fleet.sh`.
