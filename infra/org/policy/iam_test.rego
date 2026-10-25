# ABOUTME: Unit tests for iam.rego, run by `conftest verify --policy infra/org/policy`. Each case is one
# ABOUTME: rule's pass and fail, including IAM's string-or-array forms and the exceptions.md waiver.
package iam

import rego.v1

doc(address, kind, statement) := {"documents": [{"address": address, "attribute": "policy", "kind": kind,
	"document": {"Version": "2012-10-17", "Statement": statement}}], "roles": [], "boundary_name": "b"}

scoped := {"Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": "arn:aws:bedrock:*::foundation-model/x",
	"Condition": {"StringEquals": {"aws:PrincipalTag/kubernetes-namespace": "agent"}}}

test_scoped_allow_passes if {
	count(deny) == 0 with input as doc("aws_iam_policy.a", "identity", [scoped])
}

test_allow_without_condition_names_statement_index if {
	bare := object.remove(scoped, ["Condition"])
	deny == {"aws_iam_policy.a: Statement[1] is an Allow with no Condition [allow-without-condition]"} with input as doc("aws_iam_policy.a", "identity", [scoped, bare])
}

test_single_statement_object_is_read if {
	bare := object.remove(scoped, ["Condition"])
	deny == {"aws_iam_policy.a: Statement[0] is an Allow with no Condition [allow-without-condition]"} with input as doc("aws_iam_policy.a", "identity", bare)
}

test_sid_is_named if {
	bare := object.union(object.remove(scoped, ["Condition"]), {"Sid": "Wide"})
	deny == {"aws_iam_policy.a: Statement[0] (Sid Wide) is an Allow with no Condition [allow-without-condition]"} with input as doc("aws_iam_policy.a", "identity", [bare])
}

test_deny_statements_need_no_condition if {
	count(deny) == 0 with input as doc("aws_iam_policy.a", "identity", [{"Effect": "Deny", "Action": "*", "Resource": "*"}])
}

test_trust_policies_are_not_structural if {
	count(deny) == 0 with input as doc("aws_iam_role.r", "trust", [{"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"Service": "pods.eks.amazonaws.com"}}])
}

test_decorative_condition_fails if {
	st := object.union(object.remove(scoped, ["Condition"]), {"Condition": {"Bool": {"aws:SecureTransport": "true"}}})
	deny == {`aws_iam_policy.a: Statement[0] has a Condition on ["aws:securetransport"], none of which is an allow-listed scoping key [condition-key]`} with input as doc("aws_iam_policy.a", "identity", [st])
}

test_condition_keys_are_case_insensitive if {
	st := object.union(object.remove(scoped, ["Condition"]), {"Condition": {"StringEquals": {"AWS:RequestedRegion": "us-west-2"}}})
	count(deny) == 0 with input as doc("aws_iam_policy.a", "identity", [st])
}

test_action_star_string_and_array if {
	s1 := object.union(scoped, {"Action": "*"})
	s2 := object.union(scoped, {"Action": ["s3:GetObject", "*"]})
	deny == {
		"aws_iam_policy.a: Statement[0] allows Action \"*\" (or uses NotAction) [action-star]",
		"aws_iam_policy.a: Statement[1] allows Action \"*\" (or uses NotAction) [action-star]",
	} with input as doc("aws_iam_policy.a", "identity", [s1, s2])
}

test_not_action_counts_as_star if {
	st := object.union(object.remove(scoped, ["Action"]), {"NotAction": "iam:*"})
	deny == {"aws_iam_policy.a: Statement[0] allows Action \"*\" (or uses NotAction) [action-star]"} with input as doc("aws_iam_policy.a", "identity", [st])
}

test_resource_star if {
	st := object.union(scoped, {"Resource": ["*"]})
	deny == {"aws_iam_policy.a: Statement[0] allows Resource \"*\" (or uses NotResource) [resource-star]"} with input as doc("aws_iam_policy.a", "scp", [st])
}

test_exception_by_sid_waives_only_its_rule if {
	st := object.union(object.remove(scoped, ["Condition"]), {"Sid": "Ceiling", "Action": "*"})
	exc := [{"address": "aws_iam_policy.b*", "statement": "Ceiling", "rule": "action-star", "why": "w"}]
	deny == {"aws_iam_policy.boundary: Statement[0] (Sid Ceiling) is an Allow with no Condition [allow-without-condition]"} with input as doc("aws_iam_policy.boundary", "boundary", [st])
		with data.exceptions as exc
}

test_exception_by_index_and_glob if {
	bare := object.remove(scoped, ["Condition"])
	exc := [{"address": "module.eso_pod_identity.*", "statement": "1", "rule": "allow-without-condition", "why": "w"}]
	deny == {"module.eso_pod_identity.aws_iam_policy.this[0]: Statement[0] is an Allow with no Condition [allow-without-condition]"} with input as doc("module.eso_pod_identity.aws_iam_policy.this[0]", "identity", [bare, bare])
		with data.exceptions as exc
}

test_exception_for_other_address_does_not_apply if {
	bare := object.remove(scoped, ["Condition"])
	exc := [{"address": "module.eso_pod_identity.*", "statement": "*", "rule": "allow-without-condition", "why": "w"}]
	count(deny) == 1 with input as doc("aws_iam_policy.a", "identity", [bare]) with data.exceptions as exc
}

roles(rs) := {"documents": [], "roles": rs, "boundary_name": "watch-it-burn-permissions-boundary"}

test_role_with_canonical_boundary_passes if {
	count(deny) == 0 with input as roles([{"address": "module.eks.aws_iam_role.this[0]",
		"permissions_boundary": "arn:aws:iam::111122223333:policy/watch-it-burn-permissions-boundary"}])
}

test_role_without_boundary_fails if {
	deny == {"aws_iam_role.r has no permissions_boundary; every role and user carries watch-it-burn-permissions-boundary [role-boundary]"} with input as roles([{"address": "aws_iam_role.r", "permissions_boundary": ""}])
}

test_role_with_other_boundary_fails if {
	deny == {"aws_iam_role.r has permissions_boundary arn:aws:iam::111122223333:policy/watch-it-burn-permissions-boundary-v2, not the canonical watch-it-burn-permissions-boundary [role-boundary]"} with input as roles([{"address": "aws_iam_role.r",
		"permissions_boundary": "arn:aws:iam::111122223333:policy/watch-it-burn-permissions-boundary-v2"}])
}

test_user_without_boundary_fails if {
	deny == {"aws_iam_user.attendee has no permissions_boundary; every role and user carries watch-it-burn-permissions-boundary [role-boundary]"} with input as roles([{"address": "aws_iam_user.attendee", "permissions_boundary": ""}])
}
