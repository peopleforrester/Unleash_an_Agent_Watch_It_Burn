<!-- ABOUTME: The IAM policy pipeline (#207): the canonical permissions boundary, and the four checks every -->
<!-- ABOUTME: IAM document the repo creates goes through. What the org-level half is waiting on. -->

# IAM policy pipeline

Every IAM role the repo creates carries one permissions boundary, and every policy document it creates
passes four checks before it is applied. The checks read the documents out of `terraform show -json`, so
they judge what Terraform will apply, module-generated policies included, not what a reviewer thinks
the HCL says.

## What is here

| File | What it is |
|---|---|
| `permissions-boundary.json.tftpl` | The canonical boundary: the ceiling for every workload role. |
| `boundary/` | The per-account root that creates it, as `watch-it-burn-permissions-boundary`. |
| `pipeline.py` | Pulls out the documents and runs the checks. `python3 infra/org/pipeline.py --help`. |
| `policy/iam.rego` | Check 3's rules (conftest). `policy/iam_test.rego` holds its unit tests. |
| `exceptions.md` | The only place a check 3 rule is waived, one statement at a time, with the reason. |
| `effect-tests.yaml` | Check 4's cases: what a principal must and must not be able to do. |

## The boundary

The boundary allows everything the role's own policies allow, then denies these to every bounded role,
whatever its own policies say:

- creating a role without this boundary, or removing or changing the boundary;
- IAM escalation: new users or keys, attaching or putting policies, `PassRole`, new identity providers;
- `organizations:*` and `account:*`;
- creating or changing EKS clusters, access entries and Pod Identity associations;
- public S3: ACL writes, bucket policy, Block Public Access and ownership controls, public canned ACLs;
- stopping CloudTrail or AWS Config, and disabling or scheduling deletion of KMS keys.

The CreateRole deny is the in-account backstop the brief wanted from an SCP: a bounded principal cannot
make a role that escapes the boundary.

It is created **once per account** by `boundary/`, before any cluster. The cluster root looks it up by name, so
a cluster plan in an account without it fails at plan time, before any unbounded role can exist:

```bash
. infra/terraform/fleet/event.sh   # WIB_EVENT, the fleet's one `event` tag setting (#494)
terraform -chdir=infra/org/boundary init
terraform -chdir=infra/org/boundary apply -state=states/<profile>.tfstate -var profile=<profile> -var event="${WIB_EVENT}"
```

`event` has no default, as in the network and cluster roots, so an apply that leaves it out fails rather than
tagging the policy with a stale event (#507).

Roles that carry it: the EKS cluster role, the node role, and the EBS CSI, Load Balancer Controller, ESO,
agent Bedrock and tutor Bedrock Pod Identity roles (`infra/terraform/aws/cluster/main.tf`). So does the one IAM
user each cluster creates, the attendee's (`aws_iam_user.attendee`, #549), whose inline policy reaches only its
own cluster.

## Running the pipeline

Plan the root on the branch and on merged main, then run every check. The AWS profile and region are
always passed explicitly.

```bash
# head: this branch, against an applied cluster's state so every document is known
terraform -chdir=infra/terraform/aws/cluster plan -state=<state> -var-file=<vars> -out=/tmp/head.tfplan
terraform -chdir=infra/terraform/aws/cluster show -json /tmp/head.tfplan > /tmp/show-head.json

# base: merged main, from a worktree of it, same state and vars
git worktree add /tmp/base origin/main
terraform -chdir=/tmp/base/infra/terraform/aws/cluster init
terraform -chdir=/tmp/base/infra/terraform/aws/cluster plan -state=<state> -var-file=<vars> -out=/tmp/base.tfplan
terraform -chdir=/tmp/base/infra/terraform/aws/cluster show -json /tmp/base.tfplan > /tmp/show-base.json

python3 infra/org/pipeline.py run --show /tmp/show-head.json --base /tmp/show-base.json \
    --suite cluster --profile <profile> --region us-west-2
```

Use `--suite boundary` for a plan of `infra/org/boundary`. Each check also runs alone:
`extract`, `structural`, `syntax`, `diff`, `effect`.

A document that is known only after apply (a policy naming a KMS key the same apply creates, for
example) cannot be checked, so the run fails and lists it. Plan against an applied cluster's state.

## The four checks

1. **Syntax.** `aws accessanalyzer validate-policy` on every document, with the right `--policy-type`:
   identity and boundary policies as `IDENTITY_POLICY`; trust policies, KMS key policies and bucket
   policies as `RESOURCE_POLICY` with their resource type; SCPs and RCPs as their own types. It fails on
   `ERROR` and `SECURITY_WARNING`.
2. **Semantic diff.** `aws accessanalyzer check-no-new-access` for each identity or boundary document that
   changed against merged main. A wider document fails. It is billed per call, so unchanged documents are
   not sent. A document with no counterpart on main fails until a reviewer passes `--accept-new
   <address>`. It does not diff SCPs or RCPs, which is why check 3 exists.
3. **Structural.** `conftest` with `policy/iam.rego`, on identity policies, the boundary, SCPs and RCPs.
   Every Allow carries a Condition, and at least one of its keys is on the rule file's allow-list of
   scoping keys. No Allow of `Action: "*"` or `Resource: "*"`. A rule is waived only by a row in
   `exceptions.md`. Every `aws_iam_role` and `aws_iam_user` carries the canonical boundary, with no waiver. Each failure names
   the plan address and the statement index, for example:
   `aws_iam_policy.bedrock_invoke: Statement[0] is an Allow with no Condition [allow-without-condition]`.
4. **Effect.** `aws iam simulate-custom-policy` with the plan's own documents and the rendered boundary,
   for each case in `effect-tests.yaml`. Covered: the agent can invoke its models only from its own
   namespace on its own cluster; the agent cannot CreateRole or CreateCluster; no bounded role can make
   S3 public, create an unbounded role, strip the boundary, or touch org policies; the attendee user can
   describe its own cluster and list its region's, and cannot describe another cluster, mint itself a key or
   create an access entry.

Both Bedrock grants are held to the Pod Identity session tags (`aws:PrincipalTag/eks-cluster-name`,
`aws:PrincipalTag/kubernetes-namespace`, and the tutor's ServiceAccount too). EKS Pod Identity sets
those tags on every session it issues.

## Tests

- `verify/test_iam_policy_pipeline.py` (offline): extraction, the exceptions table, the boundary, every role
  in `infra/` carrying it, the effect cases, and how each check reads AWS's answer.
- `verify/test_iam_policy_coverage.py` (offline): nothing escapes the pipeline. Every IAM or Organizations
  resource, policy data source and IAM-shaped module input sits in a root in `pipeline.ROOTS`; no resource
  sets an inline policy the pipeline does not read; no script creates an IAM user, role or policy by API call
  (the attendee users' policy escaped that way until #549); SCPs and RCPs reach check 1 under their own policy type
  and check 3 in both `pipeline.py` and `iam.rego`; and the boundary, with a check 4 case for each,
  explicitly denies every org-policy write.
- `verify/test_iam_policy_structural.py` (E2E; conftest v0.71.1, terraform): Rego unit tests, then the
  repo's real cluster and boundary plans pass, and a plan with the agent's Condition removed fails at
  `Statement[0]`. `verify/iam_plan_render.py` renders those plans without an AWS account.
- `verify/test_iam_policy_aws.py` (E2E; aws CLI, `IAM_PIPELINE_PROFILE`, `IAM_PIPELINE_REGION`): checks 1
  and 4 on the real documents, and check 2 failing a widened agent policy.

## Not here yet, and why

The 2026-09-03 brief asked for an org-level half too. Measured on 2026-09-04 (comment on #207): all five
fleet accounts are member accounts of organization `o-pslkiycmqp`. Its management account is not one we
hold credentials for, and `organizations:ListPolicies` is denied. So these wait on the provider granting
management or delegated-admin access (#202):

- SCPs, RCPs and the org S3 Block Public Access policy themselves, and the SCP that denies CreateRole
  without the boundary at org level (the in-account version is the boundary's own deny, above).
- The SCP denying `organizations:*Policy*` to everyone but the org-policies CI role, the documented
  break-glass for the management account, and the instructor beat of detaching the S3 BPA policy from
  the console and reading the explicit deny.
- The second-reviewer CODEOWNERS label for allow-list SCP switches: there are no SCPs to switch yet.

Applying through OIDC in a separate `org-policies` GitHub environment is a CI workflow, which waits for
the owner. Until it exists, the pipeline runs from the command line as above.

Two effect tests from the brief have no subject in this repo. "CI can write state": Terraform state is
local files, and there is no CI role. "Datadog can still assume in": the Datadog integration uses API keys
only, and there is no AWS integration role. When either role is added, its case goes in `effect-tests.yaml`.
