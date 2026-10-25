# IAM structural-check exceptions

The structural check (`policy/iam.rego`, check 3 of the [policy pipeline](README.md)) fails every Allow
that has no Condition, has no allow-listed Condition key, allows `Action: "*"` or allows `Resource: "*"`.
A row here waives ONE of those rules for the statements it names, and nothing else. The pipeline reads
this table directly, so a waiver exists only if it is a row here, and adding one is a reviewed PR like any
other policy change.

Columns:

- **Address**: the plan address, as a glob (`*` matches anything, dots and brackets included). Write
  `this*` rather than `this[0]`: brackets in a glob are a character class, not literal brackets.
- **Statement**: the statement's index in the applied document (`0`, `1`, ...), its `Sid`, or `*` for
  every statement in the document.
- **Rule**: `allow-without-condition`, `condition-key`, `action-star` or `resource-star`.
- **Why**: required. A row with no reason fails the pipeline.

The rule that every `aws_iam_role` carries the canonical permissions boundary has no waiver.

| Address | Statement | Rule | Why |
|---|---|---|---|
| `aws_iam_policy.permissions_boundary` | `CeilingIsEverythingTheRoleIsGranted` | `action-star` | A permissions boundary is a ceiling, not a grant: a role can do only what its own policies AND the boundary allow. The boundary's content is its Deny statements; the Allow is there so the role's own (checked) policies stay the thing that grants. |
| `aws_iam_policy.permissions_boundary` | `CeilingIsEverythingTheRoleIsGranted` | `resource-star` | Same statement, same reason. |
| `aws_iam_policy.permissions_boundary` | `CeilingIsEverythingTheRoleIsGranted` | `allow-without-condition` | Same statement, same reason. |
| `module.aws_lb_controller_pod_identity.aws_iam_policy.*` | `*` | `resource-star` | Upstream terraform-aws-modules/eks-pod-identity copy of the AWS Load Balancer Controller's published policy. The `Describe*`/`Get*` reads, `iam:CreateServiceLinkedRole`, and the WAF/Shield/ACM calls do not support resource-level permissions. Bounded by the canonical boundary. |
| `module.aws_lb_controller_pod_identity.aws_iam_policy.*` | `*` | `allow-without-condition` | Same policy. The statements with no Condition are the reads, WAF association, security-group create and ingress edits, and listener, rule and target edits: the controller acts on load balancers it is reconciling, which it finds by name, so AWS publishes them unconditioned. |
| `module.ebs_csi_pod_identity.aws_iam_policy.*` | `*` | `resource-star` | Upstream copy of the EBS CSI driver's published policy. Volume and snapshot create/delete are already scoped by `aws:RequestTag/` and `ec2:ResourceTag/` Conditions; the `Describe*` reads cannot be scoped by resource. |
| `module.ebs_csi_pod_identity.aws_iam_policy.*` | `*` | `allow-without-condition` | Same policy. Statement 0 is the reads plus Attach/Detach/ModifyVolume, which act on volumes the driver did not create (statically provisioned PVs); statement 2 is DeleteTags on volumes and snapshots; statement 5 is the snapshot half of CreateVolume, whose volume half is tag-scoped. |
| `module.eso_pod_identity.aws_iam_policy.*` | `0` | `resource-star` | `secretsmanager:ListSecrets` and `BatchGetSecretValue` take no resource ARN. ESO lists, then reads only through statement 1, which is held to `watch-it-burn/*`. |
| `module.eso_pod_identity.aws_iam_policy.*` | `*` | `allow-without-condition` | Upstream module policy for External Secrets. Statement 1 is scoped by resource to `arn:aws:secretsmanager:*:*:secret:watch-it-burn/*`; statement 2 is `kms:Decrypt`, which Secrets Manager calls on the reader's behalf. |
| `module.eks.aws_iam_policy.cluster_encryption*` | `*` | `allow-without-condition` | The EKS module's envelope-encryption grant: four KMS actions on the cluster's own key ARN, nothing else. |
| `aws_iam_user_policy.attendee_eks` | `ListClusters` | `resource-star` | `eks:ListClusters` takes no resource ARN, so it cannot be scoped by resource. Its `aws:RequestedRegion` Condition holds it to the cluster's region, and it lists names only: describing any cluster but the attendee's own is still denied by statement 0. |
