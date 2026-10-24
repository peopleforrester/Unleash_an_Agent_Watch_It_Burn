<!-- ABOUTME: Drift on both planes: how fast Argo CD puts a deleted object back, how out-of-band change on the AWS -->
<!-- ABOUTME: plane is detected and recorded, and the register of everything deliberately left unmanaged. -->

# Drift and the unmanaged register

When somebody changes something by hand, what notices it, and how fast? This page answers that for each
plane (#205, from the 2026-09-03 floor brief). It also lists everything left outside reconciliation on
purpose, so a difference that is meant to be there is not mistaken for drift, and real drift is not
mistaken for one that is meant to be there.

| Plane | What puts it back | What records it | Check |
|---|---|---|---|
| Kubernetes | Argo CD selfHeal + prune, on every Application | Argo CD's sync history | `verify/test_drift_floor.py` (offline), `verify/test_drift_selfheal_live.py` (E2E) |
| AWS | nothing: Terraform runs only when someone runs it | AWS Config, CloudTrail, the daily drift report | `verify/test_drift_report.py` (offline), `verify/test_drift_aws_live.py` (E2E) |

## Kubernetes plane: Argo CD

Every Application in `gitops/apps/` and all four roots in `gitops/bootstrap/` sync automatically with
`prune: true` and `selfHeal: true`. `verify/test_drift_floor.py` fails the build if one stops doing so.

### How fast a changed object comes back

Two different clocks are involved, and the floor brief's "~180 s" is only one of them:

| What changed | What notices | How fast |
|---|---|---|
| A managed object in the cluster: deleted, or edited by hand | The application controller watches every object it manages. A change to one refreshes the owning app straight away, and self-heal syncs it back. | **Within 30 seconds**, as long as the owning app has not self-healed in the previous 5 minutes. This is the window the drill below checks. |
| A commit on `staging` | The controller's periodic resync polls git | **Up to 180 seconds**: `timeout.reconciliation` 120 s plus up to 60 s of jitter. These are the Argo CD defaults, and `infra/argocd-values.yaml` overrides neither. |

**Repeated heals slow down.** If the same app has to self-heal again at the same git revision, the
controller backs off. Each heal waits longer than the one before: 2 s, 6 s, 18 s, 54 s, 162 s, and then
300 s for every heal after that. The wait counts from when the previous sync finished, and the count
starts again only at a new revision. This was read from the Argo CD v3.5.2 controller source
(`selfHealRemainingBackoff`, flags `--self-heal-backoff-timeout-seconds 2`, `--self-heal-backoff-factor 3`,
`--self-heal-backoff-cap-seconds 300`). v3.5.2 is what `infra/deploy-full-idp.sh` installs (chart 10.8.4).
So deleting an object once brings it back in seconds. Deleting objects of the same app over and over
within a few minutes means each one takes longer to return, up to 5 minutes. That happens when a room
of people work on one shared cluster, or when a beat is rehearsed twice back to back.

**No Git webhook is configured**, so a pushed commit reaches a cluster within 180 s, not seconds. If a
beat needs a push to land in seconds, it has to say so on the run sheet and run a hard refresh on the
app straight after the push:
`kubectl --context "$CONTEXT" -n argocd annotate application <app> argocd.argoproj.io/refresh=hard --overwrite`.
A beat that relies on an object coming back after a deletion uses the watch path above and needs no
webhook.

### The drill: delete a managed NetworkPolicy

The managed NetworkPolicy present on every profile is `agent/platform-console-egress`. It is owned by
the `ai-layer` app and defined in `gitops/ai-layer/resources.yaml`. The `network-policies` app (the
`default-deny-all` set) is deployed only on the admin profile. On the attendee and full profiles those
policies are the Challenge 1 control and are left unmanaged on purpose (see the register below), so
deleting one there brings nothing back.

```bash
CONTEXT=<kube-context> python3 verify/test_drift_selfheal_live.py
```

The drill first waits until `ai-layer` has gone 5 minutes without a self-heal, so the backoff above
does not apply. If that does not happen within 10 minutes, the drill fails: an app that heals all the
time is drift in itself. The drill then deletes the policy and times how long it takes to come back.
It passes only if the policy returns within 30 seconds as a new object (a new uid) that carries Argo
CD's tracking annotation.

Kyverno's `block-argocd-drift` refuses UPDATE and DELETE on Deployments, ConfigMaps and Services that
Argo CD manages. For those three kinds, a hand-made change is refused at admission and never has to be
healed. NetworkPolicy is not covered by it, which is why the drill uses a NetworkPolicy.

### What Argo CD deliberately does not put back

Each `ignoreDifferences` entry below is a field that selfHeal leaves alone. A change to one of these
fields stays in place until somebody reverts it. `verify/test_drift_floor.py` fails if an entry exists
in `gitops/` without a row here.

| App | Object | Field | Why |
|---|---|---|---|
| `ai-layer` | Deployment `guard-proxy` | env `INPUT_BLOCKLIST`, `INPUT_CLASSIFIER`, `OUTPUT_GUARD`, `PROXY_FAIL_CLOSED`, `MODEL_TIER`, `RATE_LIMIT_RPM`, `COST_CAP_USD`, `STREAM_PROMPTS`, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` on the `proxy` container | The guard toggles are flipped live during the challenges, so selfHeal must not flip them back. `verify/fleet-drift-audit.sh` reads their live values. |
| `ai-layer` | Agent `workshop-agent` | the evil-mcp entry's `toolNames`, and `modelConfig` | Challenge 7's live toggle (`toggle-mcp-authz-on.sh`) patches evil-mcp's tool list, and `setup-instructor-cluster.sh` sets each cluster's model tier. |
| `ai-layer` | Role `workshop-agent` | `.rules` | C8: the student applies a scoped Role. The committed Role stays broad so that a fresh cluster starts vulnerable. |
| `kyverno-policies` | ClusterPolicy `require-resource-limits` | `/spec/rules/0/validate/failureAction` | The Audit-to-Enforce toggle in the CNCF beat. |
| `kyverno-policies` | ClusterPolicy `restrict-image-registries` | `/spec/rules/0/validate/failureAction` | The same toggle. |
| `kyverno` | every CustomResourceDefinition | `/metadata/labels` | The chart renders labels that the API server never stores, which caused permanent OutOfSync (#254). |
| every root | Application | `/metadata/finalizers` | Kyverno's chart adds finalizers at runtime that git can never match (#265). |

## AWS plane: Terraform, AWS Config and CloudTrail

Nothing reconciles the AWS plane. Terraform changes something only when somebody runs `fleet.sh`. Two
things are needed instead: a check that notices change, and a record that survives the change being
undone.

### The daily drift plan

`infra/terraform/drift/drift-report.py` is plan-only. It never applies, never takes a lock and never
writes a state. Each run covers three things:

1. **Drift on what Terraform manages.** It runs `terraform plan -refresh-only -detailed-exitcode` against
   every state the fleet keeps: each cluster under `infra/terraform/fleet/states/`, each account's lab
   VPC, and each account's audit root. A cluster is planned through the account its state is actually
   in, which it reads from the EKS ARN in the state. It is never planned through a default account.
2. **Resources Terraform does not manage.** A plan cannot report these: a bucket made by hand is in no
   state, so no plan ever mentions it. So the report lists every S3 bucket and EKS cluster in each
   account, then removes those that some state manages and those named in
   `infra/terraform/drift/known-unmanaged.yaml`. Whatever is left is a finding. Each finding shows who
   created it (from CloudTrail event history) and whether AWS Config has recorded it.
3. **Whether the record is on.** Every account must have a Config recorder that is recording
   `AWS::S3::Bucket` and `AWS::EKS::Cluster`.

Exit codes: 0 means clean, 2 means findings, 1 means the report is incomplete. An incomplete report is a
failure: if the report could not look at something, it has not shown that thing is free of drift.

**The schedule.** The schedule is a daily cron job on the machine that holds the fleet's state files:

```bash
( crontab -l 2>/dev/null; echo '17 6 * * * <repo>/infra/terraform/drift/scheduled-drift.sh # wib-drift' ) | crontab -
```

`scheduled-drift.sh` supplies the PATH that cron does not have, keeps a dated copy of each report, and
posts the result to a single open GitHub issue titled "Fleet drift report". It comments if that issue
is already open and opens it if not. A clean day is posted only when the issue is open.

Why cron and not a GitHub Actions workflow: the states are local files on the operator's machine,
gitignored under `states/`. There is no remote backend, so a CI runner has nothing to plan against. A
scheduled workflow needs two things first: the state move tracked on #201, and a decision on the CI
credentials. Both wait on Michael.

driftctl is not used because it is in maintenance mode. If the states move off the laptop, HCP
Terraform, Spacelift and env0 are the managed alternatives that run drift detection themselves.

### AWS Config and CloudTrail

`infra/terraform/aws/audit/` is applied once per fleet account, each into its own state, in the same way
as the lab VPC:

```bash
terraform -chdir=infra/terraform/aws/audit init
terraform -chdir=infra/terraform/aws/audit apply -state=states/<profile>.tfstate -var profile=<profile>
```

It creates a Config recorder for the six `AWS::EKS::` types, the S3 bucket, bucket-policy and account
public-access-block types, IAM users, roles and policies (where the attendee keys live), the two Bedrock
types the fleet could touch, and the trail itself. It also creates one multi-region CloudTrail trail
with log file validation. Both deliver to a private, encrypted bucket of their own. Before the first
apply in an account, run `aws configservice describe-configuration-recorders --profile <p> --region
us-west-2`. AWS allows one customer-managed recorder per account and region, and a lab provider's
existing recorder makes the apply fail. If an existing recorder already records S3 buckets and EKS
clusters, the drift report accepts it.

What each record covers:

- Config records a bucket in the bucket's own region. The recorder is in us-west-2, so a bucket made in
  another region appears in the drift report as "in <region>; the recorder is in us-west-2".
- The drift report's S3 sweep is account-wide, so it still finds a bucket in another region.
- The trail is multi-region.
- CloudTrail event history keeps 90 days of management events even without a trail, and the report's
  "created by" column reads that history.

### The acceptance case: a bucket made with an attendee key

An attendee key cannot make a bucket. `generate_attendee_aws.py` (in provisioning-agenticburn) gives
each attendee IAM user exactly two permissions: `eks:DescribeCluster` on their own cluster and
`eks:ListClusters`. The owner measured this on 2026-09-04 (#202). So when someone tries with an
attendee key, the call is refused, CloudTrail records it as a `CreateBucket` with `errorCode`
AccessDenied, and nothing exists for Config or a plan to show. `verify/test_drift_aws_live.py` checks
both halves:

1. the attendee key's `CreateBucket` is refused, and CloudTrail records the refusal against that user;
2. a bucket made out of band with the operator's profile shows up in AWS Config and in the next drift
   report as unmanaged. The operator's profile is the only principal that can make one.

## The unmanaged register

Everything deliberately left outside reconciliation, on both planes. The AWS half that the drift report
reads is `infra/terraform/drift/known-unmanaged.yaml`. When a finding turns out to be something that is
meant to be there, add it in both places in one commit, with who made it and why.

### Attendee keys

- **What:** one IAM user per attendee cluster, tagged `project=watch-it-burn`, with an access key and an
  inline policy `eks-own-cluster`, plus an EKS access entry that maps the user to cluster-admin on that
  cluster.
- **Made by:** `generate_attendee_aws.py`, called from `fleet.sh` (`bootstrap_student_aws`). These users
  are in no Terraform state.
- **Where the key lives:** `infra/terraform/fleet/aws-pool/<cluster>.csv` (gitignored), and in the
  cluster as the Secret `agent/student-aws-creds`.
- **How changes are recorded:** Config records `AWS::IAM::User`, so a change to one of these users
  (a new policy, for example) is on record. The drift report does not sweep IAM.
- **Not torn down:** nothing in this repo or in the generator deletes these users. `fleet.sh` reuses
  the existing key when a cluster with the same name is rebuilt.

### `ignore_changes`

- **Terraform:** no root has an `ignore_changes` block today. `verify/test_drift_floor.py` fails if one is
  added without a row here, because an ignored attribute is drift that the daily plan will never report.
- **Argo CD:** the field-level equivalents are the `ignoreDifferences` table above.

### Hand-made event objects

On the Kubernetes plane, these are created imperatively at bootstrap or on the day. Argo CD does not
track them, so it neither heals them nor prunes them:

| Object | Made by | Note |
|---|---|---|
| Argo CD itself (namespace `argocd`, the Helm release) | `infra/deploy-full-idp.sh` | The GitOps engine is not an Application. Its config is `infra/argocd-values.yaml`. |
| StorageClass `gp3` | `infra/deploy-full-idp.sh` | |
| Secrets `argocd/witb-repo`, `argocd/ghcr-kagent-oci` | `infra/deploy-full-idp.sh` | Repository credentials |
| Secret `datadog-secret` (Datadog namespaces) | `fleet.sh`, `deploy-full-idp.sh` | Per-org keys |
| Secret `agent/terminal-auth` | `fleet.sh` | The shared terminal credential |
| Secret `agent/student-aws-creds` | `push_vtt_aws_creds.sh` (provisioning-agenticburn) | The attendee key, see above |
| The C1 NetworkPolicies and the C3 KubeArmor policy | the student, from `~/challenges` (the `challenge-fixes` ConfigMap) | On the attendee and full profiles these are the challenge controls. Deleting one brings nothing back, and Argo CD does not remove it either. On the admin profile, the `network-policies` app manages them. |
| Anything a student or presenter applies by hand during the session | hand | Argo CD prunes only what it tracks, so these stay until the cluster is destroyed. |

On the AWS plane, these are created by a controller or a script and are in no state:

| Resource | Made by | Swept by |
|---|---|---|
| NLBs and ALBs, and their security groups | the AWS Load Balancer Controller | `fleet.sh` (drains the LBs before destroy, `reap-lbs`), `teardown/` |
| EBS volumes for PVCs, ENIs | the EBS CSI driver, VPC-CNI | `infra/terraform/aws/teardown/tag-audit.sh`, `sweep-account.sh` |
| EKS control-plane log groups | EKS | `infra/terraform/fleet/cleanup-log-groups.sh` |
| Bucket `watch-it-burn-exfil-hoop` | `games/eso-s3-exfil/s3-hoop-setup.sh` | `games/eso-s3-exfil/teardown.sh`; listed in `known-unmanaged.yaml` |
| Packt's resources in accen-dev (tagged `Workshop=packt`) | the co-tenant | never by us; listed in `known-unmanaged.yaml` |

The drift report sweeps only S3 buckets and EKS clusters. The other AWS rows are cleaned up by
teardown, which is where their lifecycle is managed. The Datadog dashboards root
(`infra/terraform/dashboards/`) is not on the AWS plane, and the drift report does not plan it.
