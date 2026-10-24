<!-- ABOUTME: Plan-time policy for the fleet Terraform: what is checked, how to run it, how to excuse a finding. -->
<!-- ABOUTME: The cluster admission floor stops bad workloads; this stops bad cloud resources before apply (#200). -->

# Plan-time policy

The admission floor in `policies/` applies only to what reaches a cluster. The fleet Terraform creates
the cloud around the clusters: buckets, IAM, the EKS control plane, and databases if we ever add one.
This directory checks a plan of that Terraform before anything is applied (#200).

## What it checks

`check-plan.py` runs three tools over one `terraform show -json` plan.

1. **Kyverno CLI, JSON mode.** It runs the four starter policies in `policies/`, each a `ValidatingPolicy`
   with `evaluation.mode: JSON`, through `kyverno apply <policies> --json plan.json`.

   | Policy | Fails a plan that... |
   |---|---|
   | `no-public-s3-acl` | gives an S3 bucket a public canned ACL (`public-read`, `public-read-write`, `authenticated-read`), or grants the AllUsers / AuthenticatedUsers groups, on `aws_s3_bucket` or `aws_s3_bucket_acl` |
   | `no-public-eks-endpoint` | leaves an `aws_eks_cluster` API endpoint public, including by omission, since the default is public |
   | `no-iam-wildcard` | has an IAM Allow on action `*` / `*:*` or on resource `*`, or uses `NotAction` / `NotResource` in an Allow, or contains a document the plan cannot read yet |
   | `no-unencrypted-rds` | leaves `storage_encrypted` anything but a known `true` on `aws_db_instance` or `aws_rds_cluster` |

2. **Checkov and Trivy `config`** over the same plan. Each is an independent second implementation of the
   same four rules. `gates.yaml` names which of their checks fail the plan, and every other finding is
   printed as advisory on every run.

A failure names the policy and the address, for example:

```
no-public-s3-acl (kyverno): no-public-s3-acl: a public ACL would expose the bucket to anyone: aws_s3_bucket.assets (acl = public-read)
no-public-s3-acl (checkov CKV_AWS_20): aws_s3_bucket.assets
no-public-s3-acl (trivy AWS-0092): aws_s3_bucket.assets
```

The check reads plan JSON, not HCL, so module internals are checked as they will be created. OpenTofu
writes the same format (`tofu show -json`), so the check works unchanged if the repo moves to it. The e2e
suite proves that with both binaries.

## Run it

```bash
python3 infra/policy/plan/install-tools.py ~/.cache/wib-plan-policy   # pinned, checksum-verified (tools.yaml)
export PATH="$HOME/.cache/wib-plan-policy/bin:$PATH"

# Any root, with a real plan:
terraform -chdir=infra/terraform/aws/cluster plan -out=plan.bin ...
terraform -chdir=infra/terraform/aws/cluster show -json plan.bin > plan.json
python3 infra/policy/plan/check-plan.py plan.json

# The fleet roots, with no AWS account (plans aws/network and aws/cluster against a local AWS API):
python3 infra/policy/plan/plan-fleet.py --tf terraform /tmp/fleet-plan
python3 infra/policy/plan/check-plan.py --require-all-exceptions-used /tmp/fleet-plan/*.plan.json
```

`check-plan.py` refuses to run with any tool version other than the pins in `tools.yaml`.

## Excusing a finding

Add a row to `exceptions.md` with the tool, the rule, the address exactly as the plan prints it, and a
reason a reviewer can check against the code. For a Kyverno rule, also add the address to that policy's
`exempt` variable. `verify/test_plan_policy.py` fails when the two disagree. Nothing else excuses a
finding: inline `#checkov:skip` comments, `.trivyignore` and `.checkov.yaml` have no effect on the check,
and the offline suite fails if one appears.

## Tests

- `verify/test_plan_policy.py` (offline). Checks that the policies, `exceptions.md`, `gates.yaml` and
  `tools.yaml` agree.
- `verify/test_plan_policy_e2e.py` (e2e). Makes real plans with Terraform and OpenTofu. Every violation in
  `fixtures/violating` must fail under its named policy, `fixtures/compliant` must pass, and the fleet
  must pass with every exception still needed.

## Not yet wired into CI

#200 asks for this to run on every PR that touches `infra/terraform/**`. The workflow is not in the repo
yet. The runner and how a CI plan gets AWS access are open questions, because this repo is public and
llm-coding-workflow#145 rules out fork-PR code on the self-hosted runner. Everything a workflow would
call is here, and it runs the same way on a laptop.

## Parallel with admission (#204)

C8's admission policy on a `Bucket` kind should use the same `publicAcls` and `publicGrantees` lists as
`no-public-s3-acl`, so the same request reads the same at both layers.
