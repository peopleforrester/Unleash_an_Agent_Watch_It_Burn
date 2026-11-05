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
CD's tracking annotation and the spec git has. `verify/run-e2e.sh` runs it on every cluster build.

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
   `hostname` and `role`). A state whose tags do not say makes the report incomplete rather than guessed.
2. **Resources Terraform does not manage.** A plan cannot report these: a bucket made by hand is in no
   state, so no plan ever mentions it. So the report lists every S3 bucket in each account and every
   EKS cluster in each region the fleet builds in (us-west-2, every region in `backups.tsv`, and every
   region a lab VPC or cluster state is in), then removes those that some state manages and those named in
   `infra/terraform/drift/known-unmanaged.yaml`. Whatever is left is a finding. Each finding shows who
   created it (from CloudTrail event history) and whether AWS Config has recorded it.
3. **Whether the record is on.** Every account must have a Config recorder in us-west-2 that is
   recording `AWS::S3::Bucket` and `AWS::EKS::Cluster`.

The accounts are `WIB_ATTENDEE_ACCOUNTS`, read from `fleet.sh` when the environment does not set it, so
the report covers the accounts the fleet builds in. Exit codes: 0 means clean, 2 means findings, 1 means
the report is incomplete. An incomplete report is a failure: if the report could not look at something,
it has not shown that thing is free of drift.

**The schedule.** The schedule is a daily cron job on the machine that holds the fleet's state files:

```bash
( crontab -l 2>/dev/null; echo '17 6 * * * <repo>/infra/terraform/drift/scheduled-drift.sh # wib-drift' ) | crontab -
```

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

### AWS Config and CloudTrail

`infra/terraform/aws/audit/` is applied once per fleet account, each into its own state, after the
permissions boundary (its recorder role carries the boundary, which it looks up by name):

```bash
. infra/terraform/fleet/event.sh
terraform -chdir=infra/terraform/aws/audit init
terraform -chdir=infra/terraform/aws/audit apply -state=states/<profile>.tfstate -var profile=<profile> -var event="${WIB_EVENT}"
```

It creates a Config recorder for the six `AWS::EKS::` types, the S3 bucket, bucket-policy and account
public-access-block types, IAM users, user policies, roles, role policies and managed policies (where the
attendee users and their grants live), the two Bedrock types the fleet could touch, the trail and the
recorder itself. It also creates one multi-region CloudTrail trail with log file validation. Both deliver
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
  "created by" column reads that history.

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
| Secret `agent/terminal-auth` | `fleet.sh` | The shared terminal credential |
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
