# ABOUTME: Check 3 of the IAM policy pipeline (#207): the structural rules every permission policy and role
# ABOUTME: in a plan must meet. Input is pipeline.py's extraction; data.exceptions is exceptions.md parsed.
#
# Rego and not Kyverno CEL because IAM's grammar is string-or-array almost everywhere (Action, Resource,
# Statement itself) and Rego has the prior art for normalising it. Every deny names the document's plan
# address and the statement's index in the document as it will be applied, Statement[i], so a failure
# points at the exact line to fix.
#
# Rules, applied to identity policies, the permissions boundary, SCPs and RCPs (kinds below):
#   allow-without-condition  every Allow carries a Condition
#   condition-key            ...and at least one of its keys is on the allow-list below
#   action-star              no Allow of Action "*" (or NotAction, which is wider)
#   resource-star            no Allow on Resource "*" (or NotResource)
# Each can be waived for one statement by a row in exceptions.md, with the reason. The role rule cannot:
#   every aws_iam_role and aws_iam_user carries the canonical permissions boundary (input.roles lists both).
package iam

import rego.v1

permission_kinds := {"identity", "boundary", "scp", "rcp"}

# Condition keys that scope an Allow to something: who is calling, from where, on what, via what. Keys that
# are true of every request a role makes (aws:PrincipalAccount on an identity policy, aws:SecureTransport,
# aws:CurrentTime) are not here: a Condition made only of them is decoration. Tag keys match by prefix;
# ec2:ResourceTag/ and ec2:CreateAction are EC2's own forms (the EBS CSI policy scopes by them).
# Condition keys are case-insensitive in IAM, so the comparison is on the lower-cased key.
allowed_condition_keys := {
	"aws:calledvia",
	"aws:calledviafirst",
	"aws:calledvialast",
	"aws:principalarn",
	"aws:principalorgid",
	"aws:principalorgpaths",
	"aws:requestedregion",
	"aws:resourceaccount",
	"aws:resourceorgid",
	"aws:resourceorgpaths",
	"aws:sourceaccount",
	"aws:sourcearn",
	"aws:sourceorgid",
	"aws:sourcevpc",
	"aws:sourcevpce",
	"ec2:createaction",
	"iam:awsservicename",
	"iam:passedtoservice",
	"iam:permissionsboundary",
	"kms:viaservice",
}

allowed_condition_prefixes := {
	"aws:principaltag/",
	"aws:requesttag/",
	"aws:resourcetag/",
	"ec2:resourcetag/",
}

as_list(x) := x if is_array(x)

as_list(x) := [x] if not is_array(x)

statements(doc) := as_list(doc.Statement)

# Every (document, index, statement) the rules look at.
allow_statements contains [rec, i, st] if {
	some rec in input.documents
	rec.kind in permission_kinds
	some i, st in statements(rec.document)
	st.Effect == "Allow"
}

where(rec, i, st) := sprintf("%s: Statement[%d] (Sid %s)", [rec.address, i, st.Sid]) if st.Sid

where(rec, i, st) := sprintf("%s: Statement[%d]", [rec.address, i]) if not st.Sid

# An exceptions.md row waives one rule for the statements it names: by index, by Sid, or "*" for all of them.
excepted(rule, rec, i, st) if {
	some ex in data.exceptions
	ex.rule == rule
	glob.match(ex.address, null, rec.address)
	statement_matches(ex.statement, i, st)
}

statement_matches("*", _, _) := true

statement_matches(s, i, _) if s == sprintf("%d", [i])

statement_matches(s, _, st) if s == st.Sid

condition_keys(st) := {lower(k) | some _, block in st.Condition; some k, _ in block}

key_allowed(k) if k in allowed_condition_keys

key_allowed(k) if {
	some p in allowed_condition_prefixes
	startswith(k, p)
}

deny contains msg if {
	some [rec, i, st] in allow_statements
	not st.Condition
	not excepted("allow-without-condition", rec, i, st)
	msg := sprintf("%s is an Allow with no Condition [allow-without-condition]", [where(rec, i, st)])
}

deny contains msg if {
	some [rec, i, st] in allow_statements
	st.Condition
	keys := condition_keys(st)
	count({k | some k in keys; key_allowed(k)}) == 0
	not excepted("condition-key", rec, i, st)
	msg := sprintf("%s has a Condition on %v, none of which is an allow-listed scoping key [condition-key]",
		[where(rec, i, st), sort([k | some k in keys])])
}

deny contains msg if {
	some [rec, i, st] in allow_statements
	wide_action(st)
	not excepted("action-star", rec, i, st)
	msg := sprintf("%s allows Action \"*\" (or uses NotAction) [action-star]", [where(rec, i, st)])
}

deny contains msg if {
	some [rec, i, st] in allow_statements
	wide_resource(st)
	not excepted("resource-star", rec, i, st)
	msg := sprintf("%s allows Resource \"*\" (or uses NotResource) [resource-star]", [where(rec, i, st)])
}

wide_action(st) if "*" in as_list(st.Action)

wide_action(st) if st.NotAction

wide_resource(st) if "*" in as_list(st.Resource)

wide_resource(st) if st.NotResource

canonical_boundary(arn) if regex.match(sprintf(`^arn:aws[a-z-]*:iam::[0-9]{12}:policy/%s$`, [input.boundary_name]), arn)

deny contains msg if {
	some role in input.roles
	role.permissions_boundary == ""
	msg := sprintf("%s has no permissions_boundary; every role and user carries %s [role-boundary]", [role.address, input.boundary_name])
}

deny contains msg if {
	some role in input.roles
	role.permissions_boundary != ""
	not canonical_boundary(role.permissions_boundary)
	msg := sprintf("%s has permissions_boundary %s, not the canonical %s [role-boundary]",
		[role.address, role.permissions_boundary, input.boundary_name])
}
