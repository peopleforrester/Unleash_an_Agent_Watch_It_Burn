<!-- ABOUTME: Drift on both planes: how fast Argo CD puts a deleted object back, how out-of-band change on the AWS -->
<!-- ABOUTME: plane is detected and recorded, and the register of everything deliberately left unmanaged. -->

# Drift and the unmanaged register

When somebody changes something by hand, what notices it, and how fast? This page answers that for each
plane (#205, from the 2026-09-03 floor brief). It also lists everything left outside reconciliation on
purpose, so a difference that is meant to be there is not mistaken for drift, and real drift is not
mistaken for one that is meant to be there.

| Plane | What puts it back | What records it | Check |
|---|---|---|---|
| Kubernetes | Argo CD selfHeal + prune, on every Application and on the root | Argo CD's sync history | `verify/test_drift_floor.py` (offline), `verify/test_drift_selfheal_live.py` (E2E) |
| AWS | nothing: Terraform runs only when someone runs it | AWS Config, CloudTrail, the daily drift report | `verify/test_drift_report.py` (offline), `verify/test_drift_aws_live.py` (E2E) |

## Kubernetes plane: Argo CD

Every Application in `gitops/bootstrap/apps/` and the `lab-bootstrap` root syncs automatically with
`prune: true` and `selfHeal: true`. `verify/test_drift_floor.py` fails the build if one stops doing so.
The root comes from one of two places. On a cluster `infra/deploy-full-idp.sh` builds, the root follows
`staging`. On a cluster lab-platform builds (`labctl event up`), the root and every app are pinned to
one commit (`lab-platform.yaml`, #609).

### How fast a changed object comes back

Two different clocks are involved, and the floor brief's "~180 s" is only one of them:

| What changed | What notices | How fast |
|---|---|---|
| A managed object in the cluster: deleted, or edited by hand | The application controller watches every object it manages. A change to one refreshes the owning app straight away, and self-heal syncs it back. | **Within 30 seconds**, as long as the owning app has not self-healed in the previous 5 minutes. This is the window the drill below checks. |
| A commit on `staging` | The controller's periodic resync polls git | **Up to 180 seconds** on a `deploy-full-idp.sh` cluster: `timeout.reconciliation` 120 s plus up to 60 s of jitter. These are the Argo CD defaults, and neither `infra/argocd-values.yaml` nor lab-platform's Argo CD values override them. **Never** on a lab-platform cluster: its revision is a pinned commit, so a push reaches it only when lab-platform moves the pin. |

**Repeated heals slow down.** If the same app has to self-heal again at the same git revision, the
controller backs off. Each heal waits longer than the one before: 2 s, 6 s, 18 s, 54 s, 162 s, and then
300 s for every heal after that. The wait counts from when the previous sync finished, and the count
starts again only at a new revision. This was read from the Argo CD v3.5.2 controller source
(`selfHealRemainingBackoff` in `controller/appcontroller.go`; flags `--self-heal-backoff-timeout-seconds 2`,
`--self-heal-backoff-factor 3`, `--self-heal-backoff-cap-seconds 300`), and both are byte for byte the same
in Argo CD v3.5.7, which is what `infra/deploy-full-idp.sh` installs (chart 10.11.7) since #858.
lab-platform installs Argo CD v3.5.6 (chart 10.11.3), and its source has the same code and defaults. `--self-heal-backoff-cooldown-seconds` is deprecated in
both and has no effect.

What that means on the day:

- Deleting an object once brings it back in seconds.
- Deleting objects of the same app over and over within a few minutes means each one takes longer to
  return, up to 5 minutes. That happens when a room of people work on one shared cluster, or when a beat
  is rehearsed twice back to back.
- On a lab-platform cluster the revision never changes during an event, so the count never starts
  again. That costs nothing after a quiet spell: once 300 s have passed since the last heal, the next
  heal is immediate, whatever the count.

**A heal takes one of two paths.** Most heals sync only the objects that are out of sync. No hook
runs, and a deleted object is back in about a second. The other path is a full sync, which applies
every object of the app, wave by wave, with 2 s between waves. It can happen only when `staging` has
moved since the app last synced, even by a commit that changes none of its manifests (the app still
reads Synced, so nothing has synced it). Even then it is not certain. Argo CD v3.5.7 starts a full
sync only when a comparison with `staging`'s head is the first to see the object missing, and the
refresh a delete asks for usually compares at the revision the app last compared. So the first heal
after a staging commit takes either path. On 2026-11-05 three such heals were full syncs (#795). On
2026-11-06, on watch-it-burn-private, two were selective at the new revision, back in 2.7 s and 2.5 s
(#962).

Until #898 that full sync was the slow path for `ai-layer`. Its two ordering gates, `kubearmor-gate` and
`otel-gate`, were PreSync hooks, and a full sync deleted, re-created and ran them before it applied
anything. On 2026-11-05 (#795) the full path brought the drill's policy back in 20.1, 25.2 and 27.2 s,
inside the 30 s window with as little as 3 s to spare, against 1.2 to 3.1 s for the selective path; on
2026-11-06 a full sync on watch-it-burn-private spent 24 of its 29 s on the hooks. Since #898 the gates
are plain Jobs at sync-wave -1, and everything else in `ai-layer` is at wave 0. On a fresh cluster Argo
CD holds wave 0 until each gate Job is Complete, so workshop-mcp is still admitted after the KubeArmor
webhook and guard-proxy after the OTel webhook. A later full sync re-applies the Complete Jobs unchanged,
which runs no pod, so a heal no longer waits on the gates. On 2026-11-06 at 10:03:41Z a full sync of
`ai-layer` on watch-it-burn-private re-applied both Complete gate Jobs at :46 without starting a pod and
applied the drill's policy at :48, 7 s in. At 03:47Z that day, under the hooks, the same point came
24 s in. A gate runs again only when its Job is
renamed: the name carries a hash of the Job and its script, and `verify/test_ai_layer_gates.py` names
the new one after an edit. The drill prints which path the heal took. On a full sync it names its PreSync
Jobs as none, and a Job named there means a hook is back.

If a gate's pod cannot run for 10 minutes, its Job fails, and every later `ai-layer` sync then fails
naming it. Auto-sync does not retry a revision whose sync failed, so delete the Job and ask for a sync,
which re-creates and runs it:

```bash
kubectl --context "$CONTEXT" -n agent delete job -l app.kubernetes.io/name=kubearmor-gate   # or otel-gate
kubectl --context "$CONTEXT" -n argocd patch application ai-layer --type merge \
  -p '{"operation":{"initiatedBy":{"username":"floor"},"sync":{"prune":true}}}'
```

**No Git webhook is configured**, on either kind of cluster, so a pushed commit reaches a `staging` cluster
within 180 s, not seconds. If a beat needs a push to land in seconds, it has to say so on the run sheet and
run a hard refresh on the app straight after the push:
`kubectl --context "$CONTEXT" -n argocd annotate application <app> argocd.argoproj.io/refresh=hard --overwrite`.
A beat that relies on an object coming back after a deletion uses the watch path above and needs no
webhook.

### The drill: delete a managed NetworkPolicy

The managed NetworkPolicy present on every profile is `agent/platform-console-egress`. It is owned by
the `ai-layer` app and defined in `gitops/ai-layer/resources.yaml`, and every profile's values file lists
`ai-layer` (attendee, burn, admin, full and local-inference). The `network-policies` app (the
`default-deny-all` set) is deployed only on the admin profile. On the other profiles those policies are
the Challenge 1 control and are left unmanaged on purpose (see the register below), so deleting one there
brings nothing back.

```bash
CONTEXT=<kube-context> python3 verify/test_drift_selfheal_live.py
```

The drill first waits until `ai-layer` has gone 5 minutes without a self-heal, so the backoff above
does not apply. If that does not happen within 10 minutes, the drill fails: an app that heals all the
time is drift in itself. The drill then deletes the policy and times how long it takes to come back.
It passes only if the policy returns within 30 seconds as a new object (a new uid) that carries Argo
CD's tracking annotation and the spec git has, and if the automated sync that put it back then ends
`Succeeded`. The policy is back before that sync ends, so the drill waits up to 2 minutes for it.
`verify/run-e2e.sh` runs it on every cluster build.

Kyverno's `block-argocd-drift` refuses UPDATE and DELETE on Deployments, ConfigMaps and Services that
Argo CD manages. For those three kinds, a hand-made change is refused at admission on the profiles that
run Kyverno, and never has to be healed; `argocd-managed-app`, Beat 1's wall 3, is that case. No policy
covers NetworkPolicy, which is why the drill uses one, and `verify/test_drift_floor.py` fails if a policy
starts refusing its deletion. The burn profile runs no Kyverno at all, so there every kind, Deployments
included, is put back by self-heal alone.

### What Argo CD deliberately does not put back

Each `ignoreDifferences` entry below is a field that selfHeal leaves alone. A change to one of these
fields stays in place until somebody reverts it. `verify/test_drift_floor.py` fails if an entry exists
in `gitops/bootstrap/apps/` or on the root without a row here.

| App | Object | Field | Why |
|---|---|---|---|
| `ai-layer` | Deployment `guard-proxy` | env `INPUT_BLOCKLIST`, `INPUT_CLASSIFIER`, `OUTPUT_GUARD`, `PROXY_FAIL_CLOSED`, `MODEL_TIER`, `RATE_LIMIT_RPM`, `COST_CAP_USD`, `STREAM_PROMPTS`, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` on the `proxy` container | The guard toggles are flipped live during the challenges, so selfHeal must not flip them back. `verify/fleet-drift-audit.sh` reads their live values. |
| `workshop-agent` | Agent `workshop-agent` | the evil-mcp entry's `toolNames`, and `modelConfig` | Challenge 7's live toggle (`guard-mcp-on`) narrows evil-mcp's tool list, and each cluster's model tier is set live. The `toolNames` ignore is rendered only where `c7Control` is not `gateway`; on the admin profile C7 is agentgateway's rule and the list syncs from git (#679). The Agent has its own app, without `RespectIgnoreDifferences`, since #707. |
| `ai-layer` | ModelConfig, every one whose provider is Bedrock | `.spec.model` (`model`) and `.spec.bedrock.region` (`region`) | `fleet.sh pin_bedrock_profiles` sets each cluster's own tagged application inference profile ARN, which git cannot know (#513), and the region it is in, which for a standby outside us-west-2 is its own (#643). |
| `ai-layer` | Deployment `agentgateway` | env `BEDROCK_NOVA_MODEL` and `BEDROCK_REGION` on the `agentgateway` container | The same pin on the gateway path (#561), and its region (#643). |
| `ai-layer` | ConfigMap `agentgateway-c7-config` | `config.yaml` | On an admin cluster `guard-mcp-on` and `guard-mcp-off` rewrite its `# c7-rule` line live (#496, #515). A committed change reaches new clusters only. A running cluster brought onto the committed tracing form by hand needs the agentgateway pod restarted in the same step: a gateway that started on the old `config.tracing` fails every reload of a file in the new form, a `guard-mcp-on` rule flip included (#867). The principal `block-argocd-drift` admits for that update is the web terminal's service account, so the file goes on with `kubectl --as system:serviceaccount:agent:web-terminal -n agent patch configmap agentgateway-c7-config`, and the pod restart is a delete of the agentgateway pod, which the policy does not match. watch-it-burn-private was brought onto the committed form that way (#868). |
| `ai-layer` | Role `workshop-agent` | `rules` | C8: the student applies a scoped Role. The committed Role stays broad so that a fresh cluster starts vulnerable. |
| `kyverno-policies` | ValidatingPolicy `require-resource-limits` | `/spec/validationActions` | The Audit-to-Deny toggle (`toggle-kyverno-enforce.sh`). Not rendered on a root lab-platform arms, which holds Deny from git (#638). |
| `kyverno-policies` | ValidatingPolicy `restrict-image-registries` | `/spec/validationActions` | The same toggle, for Challenge 2's villain image. |
| `kyverno-breakout` | ValidatingPolicy `deny-external-registries` | `/spec/validationActions` | The KubeCon guardrails switch (#774): `guardrails-on` sets Deny on both KubeCon clusters, `guardrails-off` Audit. |
| `kyverno-registry-policy` | ValidatingPolicy `restrict-image-registries` | `/spec/validationActions` | The same switch, on the KubeCon community cluster, which takes this one policy alone (#774). |
| `kyverno` | every CustomResourceDefinition | `/metadata/labels` | The chart renders labels that the API server never stores, which caused permanent OutOfSync (#254). |
| `lab-bootstrap` | every child Application | `/metadata/finalizers` | Kyverno's chart adds finalizers at runtime that git can never match (#265). `infra/deploy-full-idp.sh` and lab-platform write the same ignore on the root. |

## AWS plane: Terraform, AWS Config and CloudTrail

Nothing reconciles the AWS plane. Terraform changes something only when somebody runs `fleet.sh`. Two
things are needed instead: a check that notices change, and a record that survives the change being
undone.

### The daily drift plan

`infra/terraform/drift/drift-report.py` is plan-only. It never applies, never takes a lock and never
writes a state. Each run covers three things:

1. **Drift on what Terraform manages.** It runs `terraform plan -refresh-only` against every state the
   fleet keeps: each cluster under `infra/terraform/fleet/states/`, each account's lab VPC, each
   account's permissions boundary (`infra/org/boundary/states/`) and each account's audit root. The
   standbys (#643, `infra/terraform/fleet/backups.tsv`) are built in us-east-1 and us-east-2 as well as
   us-west-2, and each account keeps one lab VPC state per region outside us-west-2
   (`aws/network/states/<profile>.<region>.tfstate`); each of those is planned in its own region. A
   cluster is planned through the account and region its state is actually in, which it reads from the
   EKS ARN in the state, against that region's lab VPC. It is never planned through a default account
   or region. A refresh-only plan reads every object in
   the state from AWS and compares it with the state; the objects that differ are the plan's
   `resource_drift`, read with `terraform show -json`, and that list is the finding. It does not depend
   on the variables, which only have to make the configuration valid, so each plan is given the ones
   its root requires, read from the tags that root put on its own resources (`event`, and a cluster's
   `hostname` and `role`). A state whose tags do not say makes the report incomplete rather than guessed. The
   one exception is a roster cluster built before #636 put `role` on every cluster: its role is its
   `infra/terraform/fleet/roster.tsv` row's, the data `fleet.sh` passes its apply, and the report's Notes say so.
   watch-it-burn-private is one (#979).
2. **Resources Terraform does not manage.** A plan cannot report these: a bucket made by hand is in no
   state, so no plan ever mentions it. So the report lists every S3 bucket in each account and every
   EKS cluster in each region the fleet builds in (us-west-2, every region in `backups.tsv`, and every
   region a lab VPC or cluster state is in), then removes those that some state manages and those named in
   `infra/terraform/drift/known-unmanaged.yaml`. Whatever is left is a finding. Each finding shows who
   created it (from CloudTrail event history) and whether AWS Config has recorded it.
3. **Whether the record is on.** Every account must have a Config recorder in us-west-2 that is
   recording `AWS::S3::Bucket` and `AWS::EKS::Cluster`.

The accounts are `WIB_ATTENDEE_ACCOUNTS`, read from `fleet.sh` when the environment does not set it, so
the report covers the accounts the fleet builds in. Run it on the machine that holds the states. Anywhere
else every cluster `fleet.sh` built is in no state the report can read, so each one is listed as
unmanaged: run from the hecaton host on 2026-11-05, it listed both KubeCon clusters that way. Their states,
and accen-dev's lab VPC and boundary states, were on no machine at all, and are rebuilt from AWS as
"Rebuilding a lost state" below says (#979). Exit codes: 0 means clean, 2 means findings, 1 means
the report is incomplete. An incomplete report is a failure: if the report could not look at something,
it has not shown that thing is free of drift.

**The schedule.** The schedule is a daily cron job on the machine that holds the fleet's state files:

```bash
( crontab -l 2>/dev/null; echo '17 6 * * * <repo>/infra/terraform/drift/scheduled-drift.sh # wib-drift' ) | crontab -
```

The machine is tanjiro-wsl2, with `<repo>` as `/home/michael/repos/talks/Unleash_an_Agent_Watch_It_Burn` (#955,
2026-11-06). It is the operator machine runs reach: it has terraform, aws with every fleet profile, gh signed in,
PyYAML and a running cron. megumi-wsl2 does not answer ssh. The states the report plans go there. The line is
installed there, and the accen-dev audit state was rebuilt there with `import-state.sh` (both 2026-11-06, #955).
accen-dev's boundary, lab VPC and both KubeCon cluster states were rebuilt there with "Rebuilding a lost state"
below, by the operator's own AWS identity, `nwuser` (2026-11-07, #1041). The report reads the states of the checkout
it runs from, so that checkout is moved forward with `git checkout --detach origin/main`, which leaves the
guard-proxy submodule as it stands; it was at ec03eb5f until then.

`scheduled-drift.sh` supplies the PATH that cron does not have, keeps a dated copy of each report, and
posts the result to a single open GitHub issue titled "Fleet drift report". It comments if that issue
is already open and opens it if not. A clean day is posted only when the issue is open.

Why cron and not a GitHub Actions workflow: the states are local files on the operator's machine,
gitignored under `states/`. There is no remote backend, so a CI runner has nothing to plan against.
`.github/workflows/plan-policy.yml` plans against a local AWS mock (#200), which is right for a policy
check and useless for drift. A scheduled workflow needs the state move tracked on #201 and a CI
credential for the fleet accounts first.

driftctl is not used because it is in maintenance mode. If the states move off the laptop, HCP
Terraform, Spacelift and env0 are the managed alternatives that run drift detection themselves.

### Rebuilding a lost state

The states are local files, so a state lives only on the machine that applied it, and a machine that is
lost, or a worktree that is retired, takes its states with it. The KubeCon clusters watch-it-burn-community
and watch-it-burn-private were built from `infra/terraform/aws/cluster` by `fleet.sh` on 2026-10-28 (their
`ManagedBy=terraform`, `Purpose=attendee-cluster` and `attendee` tags and their module-named roles say so),
and on 2026-11-06 no machine held their states or accen-dev's lab VPC and boundary states (#979). They
are rebuilt from AWS on the machine that is to keep them, the boundary and lab VPC first, since a cluster's
plan reads the boundary policy and takes its subnets from the lab VPC state:

```bash
for r in org/boundary terraform/aws/network terraform/aws/cluster; do terraform -chdir=infra/$r init; done
python3 infra/terraform/fleet/import-state.py boundary accen-dev
python3 infra/terraform/fleet/import-state.py network accen-dev
python3 infra/terraform/fleet/import-state.py cluster accen-dev watch-it-burn-community
python3 infra/terraform/fleet/import-state.py cluster accen-dev watch-it-burn-private
```

The script plans the root against an empty state with the variables the resources were built with, read
from AWS (the tags, the node group and its launch template; a roster cluster built before #636 takes its
role from `roster.tsv`). Every planned resource is one to import. It finds each one's import id in AWS
before it imports any, and stops at the first it cannot find, so it never writes half a state. Then it
imports them one at a time, settles the state with the refresh-only apply below, and plans again. It
refuses a state that already manages a resource; `--resume` carries on a rebuild that stopped part way (a
credential timeout stopped one on 2026-11-06), importing only what the state does not hold. Imports, the
settle and the plan only read AWS, so it changes nothing there: CloudTrail holds 3,230 events from the
run that rebuilt the five accen-dev states, and none of them is a write. `--resolve-only` prints the
import ids and stops. Exit 0 means the last plan has no changes, 2 that the state is rebuilt and the plan
still has some, which it lists with the attributes each one changes, and 1 an error.

Two things in the cluster root needed care. The EKS module passes the cluster's name, endpoint, version and
CA to the node group and the access entries through a `time_sleep`'s triggers. Terraform imports a
`time_sleep` with no triggers, after which nothing that reads them evaluates. So the script writes it into
the state itself, its triggers read from the imported cluster, and the last plan shows it unchanged. And
the node group states `kubernetes_version = var.kubernetes_version`: left to the module, the version came
through that `time_sleep`, which is unknown in an empty state, and a `count` that hangs on it failed every
import.

Rebuild a cluster's state as the machine's own operator, the identity that built it: the module's
`cluster_creator` access entry and the KMS key policy name whoever runs the plan. A state rebuilt by another
identity, a hecaton run's role for one, plans both as changed, and a copy of that state must not be taken
to the operator machine.

Exit 2 is what the KubeCon clusters give, and none of their changes replaces the cluster, its node group or
an access entry. Three security group rules the cluster root has committed since 2026-10-28 were on neither
cluster when the states were rebuilt: #869's node rules for 8080 and 3000, and #906's lab VPC rule to the API
on 443 (#906's fix was made by hand as a rule from the other cluster's nodes). AWS did not hold them, so they
were not imported, and the plan creates them. On 2026-11-08 #1171 put #869's two rules on both clusters by
hand, with the root's own descriptions, so the Service proxy reaches guard-proxy on 8080 before the KubeCon
run. The states rebuilt before that still lack them, and an apply that creates a rule AWS already holds fails
as a duplicate. So before the next apply of either cluster, import the two rules into its state:

    terraform -chdir=infra/terraform/aws/cluster import \
      'module.eks.aws_security_group_rule.node["ingress_cluster_8080_workshop_apps"]' \
      <node-sg>_ingress_tcp_8080_8080_<cluster-sg>
    terraform -chdir=infra/terraform/aws/cluster import \
      'module.eks.aws_security_group_rule.node["ingress_cluster_3000_grafana"]' \
      <node-sg>_ingress_tcp_3000_3000_<cluster-sg>

with the same `-state` and `-var` arguments as the plan, where `<node-sg>` is the group named
`<cluster>-node` and `<cluster-sg>` the group `aws eks describe-cluster` lists under
`resourcesVpcConfig.securityGroupIds`. A state rebuilt after 2026-11-08 imports them itself. The rest is
configuration committed after the build: the launch template's user data
(#714 removed the containerd registry part, so the next apply rolls the node), the agent and tutor
policies (#203 dropped the `bedrock:Converse` actions), the tutor's inference profile, replaced for #882's
model, and on watch-it-burn-private the `role` tag on every resource. Then there are settings Terraform keeps
and AWS has no copy of (`force_destroy`, `force_detach_policies`, `force_update_version`, the addons'
conflict settings), as after any import. The next `fleet.sh` apply of each cluster makes all of it; until
then the drift report, which plans refresh-only, reads both states as clean. A cluster's rebuild takes
about 35 minutes (65 imports, each one refreshing the root's data sources), the lab VPC's 9 and the
boundary's 1. `verify/test_fleet_import_state.py` holds the import ids to an AWS world of the clusters'
shape, and holds the script to a rule for each resource type the three roots plan
(`verify/fixtures/import-state/planned-types.txt`, from the plans of 2026-11-06).

### Settling a fresh state

Every root the report plans is applied twice: the apply, then a refresh-only apply with the same
arguments. The second changes nothing in AWS. It writes into the state what AWS reads back for the
objects the first apply just made, values the apply never wrote. Without it, the first drift report
after any apply lists the fresh state as drifted, and the report cannot filter that out, because an
out-of-band change to the same attributes looks identical.

Each root shows it. On 2026-11-05 a fresh audit state read three resources as changed (#795). On
2026-11-06 fresh copies of the lab VPC and boundary roots were applied into scratch states in
accen-dev and planned the way the report plans them (#956). The lab VPC, in us-east-2, read five
resources as changed: both route tables' routes, which their own `aws_route` resources add; the NAT
address's association, which the NAT gateway makes; and the default network ACL and route table. The
boundary read one, `tags: null -> {}` on its policy. After the refresh-only apply both plans said "No
changes", and a tag set by hand on the policy and on the VPC still showed as drift. The cluster root
was not built for this, since a dispatched run creates no cluster. It holds the same shapes: two
untagged IAM policies like the boundary's, and IAM roles whose policies are attached by sibling
resources, like the audit role.

- **Clusters:** `fleet.sh` runs the refresh-only apply after each cluster apply that succeeds, into the
  same apply log. A settle that fails fails the run, and `WIB_FORCE_UP=1` re-applies and settles.
- **Lab VPC, boundary and audit roots:** they are applied by hand, and every documented command is
  followed by its refresh-only twin: `infra/terraform/README.md`, `infra/org/README.md`, the boundary
  and audit roots' headers, the recreation and build specs, the run-of-show, and the apply lines
  `preflight.sh`, `fleet.sh` and `backups.py` print. `verify/test_drift_settle.py` fails a documented
  apply of these roots that has no settle with the same arguments after it, and
  `verify/test_fleet_settle_after_apply.sh` holds the `fleet.sh` step.

### AWS Config and CloudTrail

`infra/terraform/aws/audit/` is applied once per fleet account, each into its own state, after the
permissions boundary (its recorder role carries the boundary, which it looks up by name):

```bash
. infra/terraform/fleet/event.sh
terraform -chdir=infra/terraform/aws/audit init
terraform -chdir=infra/terraform/aws/audit apply -state=states/<profile>.tfstate -var profile=<profile> -var event="${WIB_EVENT}"
terraform -chdir=infra/terraform/aws/audit apply -refresh-only -auto-approve -state=states/<profile>.tfstate -var profile=<profile> -var event="${WIB_EVENT}"
```

The second apply is refresh-only: it changes nothing in AWS and writes into the state what AWS reads back
for the objects the first apply just made. Without it, the next drift report lists the fresh audit state as
drifted. The trail, the role and the bucket each read back attributes their sibling resources set after they
were created: the role's managed and inline policies, the bucket's policy, lifecycle and encryption, and an
empty `tags` map on all three. The #795 apply of 2026-11-05 showed exactly that, three resources "changed
outside of Terraform" minutes after the apply. Settled, the report reads the state as clean, and a later
out-of-band change to one of those attributes still shows as drift.

A lost audit state is rebuilt from AWS, on the machine that is to keep it:

```bash
terraform -chdir=infra/terraform/aws/audit init
infra/terraform/aws/audit/import-state.sh <profile>
```

Every resource in the root has a fixed name built from the account id and the region, so the script imports
each one by that name, settles the state as above, and ends on a plan that has to say no changes. Only
`force_destroy` on the bucket differs after an import, because it is a Terraform setting AWS has no copy of;
a targeted apply of the bucket writes it into the state and changes nothing in AWS. The script refuses a
state that already manages a resource. Run 17588 (#795) applied the root in accen-dev from a hecaton
worktree that has since been retired, its state with it; on 2026-11-06 the script rebuilt that state from
AWS in 3 minutes, and the drift report read it as clean (#955).

It creates a Config recorder for the six `AWS::EKS::` types, the S3 bucket, bucket-policy and account
public-access-block types, IAM users, user policies, roles, role policies and managed policies (where the
attendee users and their grants live), the two Bedrock types the fleet could touch, and the trail. The
recorder itself is on record without being listed: `AWS::Config::` types are Config's own system types,
recorded by default, and AWS refuses one in a recording group. It also creates one multi-region CloudTrail trail with log file validation. Both deliver
to a private, encrypted bucket of their own. The recorder's role, its delivery grant and the trail's
bucket policy go through the IAM policy pipeline as its `audit` suite (`infra/org/pipeline.py`,
`infra/org/effect-tests.yaml`), like the cluster root's IAM. The permissions boundary already denies a
bounded role `config:StopConfigurationRecorder`, `config:DeleteDeliveryChannel` and
`cloudtrail:StopLogging`, so nothing the fleet runs can turn the record off.

Before the first apply in an account, run
`aws configservice describe-configuration-recorders --profile <p> --region us-west-2`. AWS allows one
customer-managed recorder per account and region, and a lab provider's existing recorder makes the apply
fail. If an existing recorder already records S3 buckets and EKS clusters, the drift report accepts it.

What each record covers:

- Config records a bucket in the bucket's own region. The recorder is in us-west-2, so a bucket made in
  another region appears in the drift report as "in <region>; the recorder is in us-west-2".
- The drift report's S3 sweep is account-wide, so it still finds a bucket in another region. Its EKS
  sweep covers us-west-2 and every standby region, and an unmanaged cluster in a standby region is
  reported the same way, "in <region>; the recorder is in us-west-2". The audit root is not applied per
  region: the recorder's IAM role is global and named once per account, and the standbys are short-lived.
  CloudTrail is what records who made something in a standby region.
- The trail is multi-region.
- CloudTrail event history keeps 90 days of management events even without a trail, and the report's
  "created by" column reads that history. It asks for the create events by name (`CreateBucket`,
  `CreateCluster`) and picks the newest successful one for the resource. Asking by resource name does not
  work: a cluster's newest events are its pod identity calls, so on 2026-11-05 the newest 50 for
  `watch-it-burn-community` were all `AssumeRoleForPodIdentity` and its `CreateCluster` was past them.

### The acceptance case: a bucket made with an attendee key

An attendee key cannot make a bucket. The key belongs to the cluster's IAM user, whose one grant is the
cluster root's `aws_iam_user_policy.attendee_eks`: `eks:DescribeCluster` on its own cluster and
`eks:ListClusters`, both in the cluster's region. The effect test "the attendee user cannot make a
bucket" in `infra/org/effect-tests.yaml` holds that. So when someone tries with an attendee key, the call
is refused, CloudTrail records it as a `CreateBucket` with `errorCode` AccessDenied, and nothing exists
for Config or a plan to show. `verify/test_drift_aws_live.py` checks both halves:

1. the attendee key's `CreateBucket` is refused, and CloudTrail records the refusal against that user;
2. a bucket made out of band with the operator's profile shows up in AWS Config and in the next drift
   report as unmanaged. The operator's profile is the principal that can make one.

## The unmanaged register

Everything deliberately left outside reconciliation, on both planes. The AWS half that the drift report
reads is `infra/terraform/drift/known-unmanaged.yaml`. When a finding turns out to be something that is
meant to be there, add it in both places in one commit, with who made it and why.
`verify/test_drift_floor.py` fails if an entry in the file has no row here.

### Attendee keys

- **What:** one IAM user per cluster, `wib-<name less its watch-it-burn- prefix>`, tagged
  `project=watch-it-burn` and `cluster=<name>`, with the inline policy `eks-own-cluster` and an EKS access
  entry that maps the user to cluster-admin on that cluster.
- **Made by:** the cluster root since #549: the user, its policy and the access entry are in the
  cluster's state, carry the permissions boundary, and go through the IAM policy pipeline. The access key
  is the one part outside Terraform. `fleet.sh` mints it (`mint_attendee_key`, from `bootstrap_student_aws`
  and `fleet.sh aws-keys`) so that its secret never sits in a state file.
- **Where the key lives:** `infra/terraform/fleet/aws-pool/<cluster>.csv` (gitignored), and in the
  cluster as the Secret `student-creds/student-aws-creds`.
- **How changes are recorded:** a refresh-only plan of the cluster reports a changed user or policy.
  Config records `AWS::IAM::User` and `AWS::IAM::UserPolicy`, and CloudTrail records every call the key
  makes, refused ones included.
- **Torn down:** `terraform destroy` of the cluster deletes the user and its key (`force_destroy`).
  `fleet.sh`'s IAM user sweep removes the users made before #549.

The community cluster is the one place a second credential is exposed on purpose: its nodes' IMDS hop
limit is 2 (#113), so a compromised pod can take the node role's credentials. Nothing reconciles what is
done with them; CloudTrail records each call under the node role.

### `ignore_changes`

- **Terraform:** no root has an `ignore_changes` block today. `verify/test_drift_floor.py` fails if one is
  added without a row here, because an ignored attribute is drift that the daily plan will never report.
- **Argo CD:** the field-level equivalents are the `ignoreDifferences` table above.

### Hand-made event objects

On the Kubernetes plane, these are created imperatively at bootstrap or on the day. Argo CD does not
track them, so it neither heals them nor prunes them:

| Object | Made by | Note |
|---|---|---|
| Argo CD itself (namespace `argocd`) | `infra/deploy-full-idp.sh` (Helm), or lab-platform's bootstrap | The GitOps engine is not an Application. Its config is `infra/argocd-values.yaml`, or lab-platform's copy of it. |
| StorageClass `gp3` | `infra/deploy-full-idp.sh`, or lab-platform's bootstrap | |
| Secret `datadog-secret` in `datadog`, `monitoring` and `security` | `fleet.sh`, `infra/deploy-full-idp.sh` | Per-org keys |
| Secret `agent/terminal-auth` | `fleet.sh`, or by hand on watch-it-burn-community and watch-it-burn-private | The shared terminal credential. On those two it is set by hand (#1069), and fleet.sh never writes it there (#1074). |
| Secret `student-creds/student-aws-creds` | `fleet.sh` (`push_student_aws`) | The attendee key, see above |
| The C1 NetworkPolicies and the C3 KubeArmor policy | the student, from `~/challenges` (the `challenge-fixes` ConfigMap) | On the profiles other than admin these are the challenge controls. Deleting one brings nothing back, and Argo CD does not remove it either. On the admin profile, the `network-policies` and `kubearmor-policies` apps manage them. |
| Anything a student or presenter applies by hand during the session | hand | Argo CD prunes only what it tracks, so these stay until the cluster is destroyed. |

There is no repository Secret any more: `witb-repo` is deleted by `infra/deploy-full-idp.sh` (#609), and
`ghcr-kagent-oci` is rendered by the root chart, so the root manages it.

On the AWS plane, these are created by a controller, a script or another system, and are in no state:

| Resource | Made by | Swept by |
|---|---|---|
| NLBs and ALBs, and their security groups | the AWS Load Balancer Controller | `fleet.sh` (drains the LBs before destroy, `reap-lbs`), `infra/terraform/aws/teardown/` |
| EBS volumes for PVCs, ENIs | the EBS CSI driver, VPC-CNI | `infra/terraform/aws/teardown/`, `fleet.sh reap-lbs` |
| EKS control-plane log groups | EKS | `infra/terraform/fleet/cleanup-log-groups.sh` |
| Bucket `watch-it-burn-exfil-hoop` | `games/eso-s3-exfil/s3-hoop-setup.sh` | `games/eso-s3-exfil/teardown.sh`; listed in `known-unmanaged.yaml` |
| Clusters and buckets tagged `lab-platform:managed=true` | lab-platform (`labctl event up`) | lab-platform's own teardown; listed in `known-unmanaged.yaml` |
| Packt's resources in accen-dev (tagged `Workshop=packt`) | the co-tenant | never by us; listed in `known-unmanaged.yaml` |

The drift report sweeps only S3 buckets and EKS clusters. The other AWS rows are cleaned up by
teardown, which is where their lifecycle is managed. The Datadog dashboards root
(`infra/terraform/dashboards/`) is not on the AWS plane, and the drift report does not plan it.
