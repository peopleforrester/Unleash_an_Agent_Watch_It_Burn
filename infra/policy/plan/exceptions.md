<!-- ABOUTME: Every finding the plan-time policy check lets through on purpose, each with its reason. -->
<!-- ABOUTME: check-plan.py reads the table below; verify/test_plan_policy.py keeps it and the policies in step. -->

# Plan-time policy exceptions

These findings are intentional, so the check lets them through. Nothing gets suppressed anywhere else.
There are no `#checkov:skip` comments, no `.trivyignore`, and no Kyverno PolicyException. If a finding
isn't in this table, it fails the check.

How each tool reads the table:

- **kyverno** rows must match the `exempt` variable in `policies/<rule>.yaml` exactly.
  `verify/test_plan_policy.py` fails the offline suite when a row and a policy disagree in either
  direction.
- **checkov** and **trivy** rows are read by `check-plan.py` at run time. A row only excuses the named
  rule on the named address. The rule must be one of the gated IDs in `gates.yaml`.

Every row comes from a finding on a real plan of the fleet roots, made by `plan-fleet.py` on
2026-10-24. That script plans `infra/terraform/aws/cluster` and `infra/terraform/aws/network` against
a local AWS API, so the module internals below are the ones the fleet actually creates. The e2e
suite fails when a row stops matching any finding, so a stale exception can't outlive the code it
excused.

To add a row, give the address exactly as the plan prints it, the rule exactly as the tool names it,
and a reason a reviewer can check against the code.

## Exceptions

| Tool | Rule | Address | Reason |
|---|---|---|---|
| kyverno | no-public-eks-endpoint | `module.eks.aws_eks_cluster.this[0]` | `infra/terraform/aws/cluster/main.tf` sets `endpoint_public_access = true` on every attendee cluster. Every tool that builds and runs a cluster reaches its API from outside the lab VPC: `fleet.sh` bootstrap, `deploy-full-idp.sh`, `grant-collaborator-kubeconfig.sh`, and the operator's kubeconfig from the `kubeconfig_command` output. `infra/terraform/aws/network` creates no bastion, VPN or other way into the VPC. A private-only endpoint would leave every cluster unreachable to the tooling that bootstraps it. Each cluster has one attendee, is disposable, and is torn down after the event. |
| checkov | CKV_AWS_39 | `module.eks.aws_eks_cluster.this[0]` | Checkov's version of the no-public-eks-endpoint finding above. Same cluster, same reason. |
| trivy | AWS-0040 | `module.eks.aws_eks_cluster.this[0]` | Trivy's version of the no-public-eks-endpoint finding above. Same cluster, same reason. |
| kyverno | no-iam-wildcard | `module.eks.aws_iam_policy.cluster_encryption[0]` | The document can't be read at plan time because it embeds the ARN of the cluster's KMS key, which is created in the same apply. The terraform-aws-eks v21 source (`main.tf`, `aws_iam_policy.cluster_encryption`) builds it as a single Allow of `kms:Encrypt`, `kms:Decrypt`, `kms:ListGrants` and `kms:DescribeKey` on that one key ARN. It has no `"*"`. |
| kyverno | no-iam-wildcard | `module.ebs_csi_pod_identity.aws_iam_policy.ebs_csi[0]` | The EBS CSI driver policy from terraform-aws-eks-pod-identity (`attach_aws_ebs_csi_policy`), which the cluster root describes as the AWS-managed EBS CSI policy equivalent. On `"*"`, it grants `ec2:Describe*` reads, plus `AttachVolume`, `DetachVolume`, `ModifyVolume`, `CreateSnapshot` and `EnableFastSnapshotRestores` without a condition, as the module ships them, because the driver acts on volumes that do not exist at plan time. Every `ec2:DeleteVolume` and `ec2:DeleteSnapshot` on `"*"` requires one of the driver's own tags (`ebs.csi.aws.com/cluster`, `CSIVolumeName`, `CSIVolumeSnapshotName`, `kubernetes.io/created-for/pvc/name`). Dynamic PVC provisioning cannot work without this grant. |
| checkov | CKV_AWS_355 | `module.ebs_csi_pod_identity.aws_iam_policy.ebs_csi[0]` | Checkov's version of the no-iam-wildcard finding above. Same policy, same reason. |
| kyverno | no-iam-wildcard | `module.aws_lb_controller_pod_identity.aws_iam_policy.lb_controller[0]` | The AWS Load Balancer Controller policy from terraform-aws-eks-pod-identity (`attach_aws_lb_controller_policy`). The controller creates its load balancers, target groups and security groups at runtime, so none of their ARNs exist at plan time. `CreateLoadBalancer`, `CreateTargetGroup`, `DeleteSecurityGroup` and the tag-scoped security-group ingress changes require the `elbv2.k8s.aws/cluster` tag. As the module ships it, some calls on `"*"` carry no condition: `ec2:CreateSecurityGroup`, security-group ingress changes, listener and rule create, modify and delete, and WAF/Shield association. The rest are `Describe*` and `Get*` reads. |
| checkov | CKV_AWS_355 | `module.aws_lb_controller_pod_identity.aws_iam_policy.lb_controller[0]` | Checkov's version of the no-iam-wildcard finding above. Same policy, same reason. |
| kyverno | no-iam-wildcard | `module.eso_pod_identity.aws_iam_policy.external_secrets[0]` | External Secrets Operator's policy. Its one `"*"` statement is `secretsmanager:ListSecrets` and `secretsmanager:BatchGetSecretValue`. ListSecrets supports no resource-level permissions. BatchGetSecretValue only returns secrets the caller also holds `GetSecretValue` on, and the next statement scopes that to `arn:aws:secretsmanager:*:*:secret:watch-it-burn/*` (`external_secrets_secrets_manager_arns` in the cluster root). |
