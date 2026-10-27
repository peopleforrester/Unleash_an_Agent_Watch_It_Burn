# ABOUTME: Offline gate for the IAM policy pipeline (#207): extraction from `terraform show -json`, the
# ABOUTME: exceptions table, the canonical boundary, every role and user carrying it, and how each check reads AWS's answer.
#
# Why. The pipeline's four checks run with conftest and against AWS, which this suite has neither of; those
# runs are verify/test_iam_policy_structural.py and verify/test_iam_policy_aws.py in the E2E suite. What can
# be decided here is everything around them: that a plan's documents are all found and none is silently
# dropped, that a document known only after apply stops the run, that a waiver needs a reason, that no
# role or user in infra/ is written without the boundary, and that each check fails on the answers that should fail it.
import json, pathlib, re, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra/org"))
import pipeline as p  # noqa: E402

import yaml  # noqa: E402

failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def raises(fn, needle):
    try:
        fn()
    except p.PipelineError as e:
        return needle in str(e)
    return False


def doc(*statements):
    return json.dumps({"Version": "2012-10-17", "Statement": list(statements)})


ALLOW = {"Effect": "Allow", "Action": "bedrock:InvokeModel", "Resource": "arn:aws:bedrock:*::foundation-model/x",
         "Condition": {"StringEquals": {"aws:PrincipalTag/kubernetes-namespace": "agent"}}}
TRUST = {"Effect": "Allow", "Action": ["sts:AssumeRole", "sts:TagSession"], "Principal": {"Service": "pods.eks.amazonaws.com"}}
BARN = f"arn:aws:iam::111122223333:policy/{p.BOUNDARY_NAME}"


def res(address, type_, **values):
    return {"address": address, "mode": "managed", "type": type_, "name": address.split(".")[-1], "values": values}


PLAN = {
    "format_version": "1.2",
    "variables": {"name": {"value": "c1"}, "region": {"value": "us-west-2"}},
    "planned_values": {"root_module": {
        "resources": [
            res("aws_iam_policy.bedrock_invoke", "aws_iam_policy", name="c1-bedrock-invoke", policy=doc(ALLOW)),
            res("aws_iam_policy.permissions_boundary", "aws_iam_policy", name=p.BOUNDARY_NAME, policy=doc(ALLOW)),
            res("aws_iam_role_policy.inline", "aws_iam_role_policy", policy=doc(ALLOW)),
            res("aws_organizations_policy.scp", "aws_organizations_policy", type="SERVICE_CONTROL_POLICY", content=doc(ALLOW)),
            res("aws_s3_bucket.b", "aws_s3_bucket", bucket="b"),
            res("aws_iam_user.attendee", "aws_iam_user", name="wib-c1", permissions_boundary=BARN),
            res("aws_iam_user_policy.attendee_eks", "aws_iam_user_policy", name="eks-own-cluster", user="wib-c1",
                policy=doc(ALLOW)),
        ],
        "child_modules": [{"address": "module.x", "resources": [
            res("module.x.aws_iam_role.this[0]", "aws_iam_role", name="c1-x", assume_role_policy=doc(TRUST),
                permissions_boundary=BARN, inline_policy=[{"name": "i", "policy": doc(ALLOW)}]),
            res("module.x.aws_iam_role.bare[0]", "aws_iam_role", name="c1-bare", assume_role_policy=doc(TRUST),
                permissions_boundary=None),
        ], "child_modules": [{"address": "module.x.module.kms", "resources": [
            res("module.x.module.kms.aws_kms_key.this[0]", "aws_kms_key", policy=doc(TRUST)),
        ]}]}],
    }},
    "prior_state": {"values": {"root_module": {"resources": [
        {"address": "data.aws_caller_identity.current", "mode": "data", "type": "aws_caller_identity",
         "values": {"account_id": "111122223333"}},
    ]}}},
    "resource_changes": [],
}

print("extraction")
ext = p.extract(PLAN)
kinds = {(d["address"], d["attribute"]): d["kind"] for d in ext["documents"]}
check("every document in root and nested modules is found", kinds == {
    ("aws_iam_policy.bedrock_invoke", "policy"): "identity",
    ("aws_iam_policy.permissions_boundary", "policy"): "boundary",
    ("aws_iam_role_policy.inline", "policy"): "identity",
    ("aws_iam_user_policy.attendee_eks", "policy"): "identity",
    ("aws_organizations_policy.scp", "content"): "scp",
    ("module.x.aws_iam_role.this[0]", "assume_role_policy"): "trust",
    ("module.x.aws_iam_role.this[0]", "inline_policy[0].policy"): "identity",
    ("module.x.aws_iam_role.bare[0]", "assume_role_policy"): "trust",
    ("module.x.module.kms.aws_kms_key.this[0]", "policy"): "kms-key",
}, json.dumps(sorted(kinds.items()), indent=1))
check("documents are parsed, not passed on as strings",
      all(isinstance(d["document"], dict) for d in ext["documents"]))
check("every role and user is listed with its boundary, a missing one as empty",
      ext["roles"] == [{"address": "aws_iam_user.attendee", "name": "wib-c1", "permissions_boundary": BARN},
                       {"address": "module.x.aws_iam_role.this[0]", "name": "c1-x", "permissions_boundary": BARN},
                       {"address": "module.x.aws_iam_role.bare[0]", "name": "c1-bare", "permissions_boundary": ""}], ext["roles"])
bare_user = json.loads(json.dumps(PLAN))
bare_user["planned_values"]["root_module"]["resources"][5]["values"]["permissions_boundary"] = None
check("a user with no boundary is listed with an empty one, for check 3 to fail (#549)",
      {"address": "aws_iam_user.attendee", "name": "wib-c1", "permissions_boundary": ""} in p.extract(bare_user)["roles"])
check("a fully known plan has nothing unknown", ext["unknown"] == [])
check("data sources are not documents", not any(d["address"].startswith("data.") for d in ext["documents"]))

state = {"values": PLAN["planned_values"]}
check("a state file's show (values, not planned_values) extracts the same", p.extract(state)["documents"] == ext["documents"])

unknown_plan = json.loads(json.dumps(PLAN))
del unknown_plan["planned_values"]["root_module"]["resources"][0]["values"]["policy"]
unknown_plan["resource_changes"] = [{"address": "aws_iam_policy.bedrock_invoke", "change": {"after_unknown": {"policy": True}}},
                                    {"address": "module.x.aws_iam_role.this[0]", "change": {"after_unknown": {"permissions_boundary": True}}}]
uext = p.extract(unknown_plan)
check("a document known only after apply is reported, not dropped",
      uext["unknown"] == ["aws_iam_policy.bedrock_invoke.policy", "module.x.aws_iam_role.this[0].permissions_boundary"], uext["unknown"])
check("...and stops every check", raises(lambda: p.require_known(uext), "aws_iam_policy.bedrock_invoke.policy"))
check("...the structural check included, before it looks for conftest",
      raises(lambda: p.structural(uext, exceptions=[]), "known only after apply"))

s3_plan = json.loads(json.dumps(PLAN))
s3_plan["planned_values"]["root_module"]["resources"][3]["values"]["type"] = "S3_POLICY"
check("an org policy type with no validator fails loudly", raises(lambda: p.extract(s3_plan), "S3_POLICY"))
check("something that is not show -json fails loudly", raises(lambda: p.extract({"resources": []}), "not `terraform show -json`"))
bad = json.loads(json.dumps(PLAN))
bad["planned_values"]["root_module"]["resources"][0]["values"]["policy"] = "{not json"
check("a policy that is not JSON fails loudly", raises(lambda: p.extract(bad), "aws_iam_policy.bedrock_invoke.policy"))
check("plan variables give the effect tests their cluster and region",
      p.effect_env(PLAN, "cluster") == {"account_id": "111122223333", "cluster_name": "c1", "region": "us-west-2"})

print("exceptions.md")
rows = p.load_exceptions()
check("the table parses and has rows", len(rows) > 0)
check("every row names a known rule and gives a reason", all(r["rule"] in p.RULES and r["why"] for r in rows))
check("no row uses brackets, which a glob reads as a character class", not any("[" in r["address"] for r in rows),
      [r["address"] for r in rows if "[" in r["address"]])
tmp = REPO / "infra/org/.exceptions-test.md"
try:
    tmp.write_text("| `aws_iam_policy.a` | `0` | `action-star` |  |\n", encoding="utf-8")
    check("a row without a reason fails the pipeline", raises(lambda: p.load_exceptions(tmp), "without a reason"))
    tmp.write_text("| `aws_iam_policy.a` | `0` | `anything-goes` | because |\n", encoding="utf-8")
    check("a row with an unknown rule fails the pipeline", raises(lambda: p.load_exceptions(tmp), "anything-goes"))
finally:
    tmp.unlink(missing_ok=True)

print("canonical permissions boundary")
boundary = p.render_boundary("111122223333")
sids = {s.get("Sid"): s for s in boundary["Statement"]}
check("the template renders to a policy with every placeholder filled", "${" not in json.dumps(boundary))
check("statement 0 is the ceiling that exceptions.md waives, by the same Sid",
      boundary["Statement"][0]["Sid"] == "CeilingIsEverythingTheRoleIsGranted"
      and {r["rule"] for r in rows if r["statement"] == "CeilingIsEverythingTheRoleIsGranted"}
      == {"action-star", "resource-star", "allow-without-condition"})
create = sids.get("NoNewRoleWithoutThisBoundary", {})
check("CreateRole without this boundary is denied, naming this boundary's own ARN",
      create.get("Effect") == "Deny" and "iam:CreateRole" in create.get("Action", [])
      and create.get("Condition") == {"StringNotEquals": {"iam:PermissionsBoundary": BARN}})


def denied(action):
    return any(s["Effect"] == "Deny" and not s.get("Condition") and action in p_list(s["Action"]) for s in boundary["Statement"])


def p_list(x):
    return x if isinstance(x, list) else [x]


for action in ("iam:DeleteRolePermissionsBoundary", "iam:AttachRolePolicy", "iam:PutRolePolicy", "iam:CreateUser",
               "iam:CreateAccessKey", "iam:CreatePolicyVersion", "organizations:*", "eks:CreateCluster",
               "s3:PutBucketAcl", "s3:PutBucketPublicAccessBlock", "s3:PutBucketPolicy", "cloudtrail:StopLogging",
               "kms:ScheduleKeyDeletion"):
    check(f"the boundary denies {action} outright", denied(action))
names = {
    "pipeline.py": p.BOUNDARY_NAME,
    "boundary/main.tf": re.search(r'boundary_name = "([^"]+)"', (REPO / "infra/org/boundary/main.tf").read_text()).group(1),
    "cluster/main.tf": re.search(r'permissions_boundary_name = "([^"]+)"',
                                 (REPO / "infra/terraform/aws/cluster/main.tf").read_text()).group(1),
}
check("the boundary has one name in all three places", len(set(names.values())) == 1, names)


print("every role and user carries the boundary")


def blocks(text, header_re):
    """(header, body) of every top-level HCL block whose header matches, by brace counting."""
    out = []
    for m in re.finditer(header_re, text, re.M):
        depth, i = 0, m.end() - 1
        for j in range(i, len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                out.append((m.group(0), text[i:j + 1]))
                break
    return out


BOUNDARY_REF = "data.aws_iam_policy.permissions_boundary.arn"
# infra/policy/plan/fixtures holds deliberately violating plans for the plan-policy tests (#200), and
# .terraform is a local provider and module cache, so neither is Terraform this repo deploys.
tf_files = sorted(p for p in (REPO / "infra").rglob("*.tf")
                  if ".terraform" not in p.parts and "infra/policy/plan/fixtures" not in p.as_posix())
check("infra/ has Terraform to look at", len(tf_files) > 0)
for f in tf_files:
    text = f.read_text(encoding="utf-8")
    rel = f.relative_to(REPO)
    for header, body in blocks(text, r'^resource "aws_iam_role" "[^"]+" \{'):
        check(f"{rel}: {header[:-2]} sets permissions_boundary", re.search(r"^\s*permissions_boundary\s*=", body, re.M) is not None)
    users = blocks(text, r'^resource "aws_iam_user" "[^"]+" \{')
    if rel.as_posix() == "infra/terraform/aws/cluster/main.tf":
        check(f"{rel}: the attendee IAM user is created here, where the pipeline plans it (#549)", len(users) == 1)
    for header, body in users:
        check(f"{rel}: {header[:-2]} carries the canonical boundary",
              re.search(rf"^  permissions_boundary\s*=\s*{re.escape(BOUNDARY_REF)}\s*$", body, re.M) is not None)
    for header, body in blocks(text, r'^module "[^"]+" \{'):
        if "terraform-aws-modules/eks-pod-identity/aws" in body:
            check(f"{rel}: {header[:-2]} passes the canonical boundary",
                  re.search(rf"^\s*permissions_boundary_arn\s*=\s*{re.escape(BOUNDARY_REF)}\s*$", body, re.M) is not None)
        if "terraform-aws-modules/eks/aws" in body:
            check(f"{rel}: {header[:-2]} gives the cluster role the canonical boundary",
                  re.search(rf"^  iam_role_permissions_boundary\s*=\s*{re.escape(BOUNDARY_REF)}\s*$", body, re.M) is not None)
            ngs = blocks(body[1:], r"^  eks_managed_node_groups = \{")
            groups = blocks(ngs[0][1][1:], r"^    [a-z0-9_-]+ = \{") if ngs else []
            check(f"{rel}: {header[:-2]} defines its node groups", len(groups) > 0)
            for g, gbody in groups:
                check(f"{rel}: node group {g.split()[0]} gives the node role the canonical boundary",
                      re.search(rf"^\s*iam_role_permissions_boundary\s*=\s*{re.escape(BOUNDARY_REF)}\s*$", gbody, re.M) is not None)
        if re.search(r'source\s*=\s*"terraform-aws-modules/iam/', body):
            check(f"{rel}: {header[:-2]} is an IAM module the pipeline has not been taught", False)

print("effect-tests.yaml")
spec = yaml.safe_load((REPO / "infra/org/effect-tests.yaml").read_text(encoding="utf-8"))
cluster_tf = (REPO / "infra/terraform/aws/cluster/main.tf").read_text(encoding="utf-8")
declared = {f"{t}.{n}" for t, n in re.findall(r'^resource "(aws_iam_policy|aws_iam_user_policy)" "([^"]+)"', cluster_tf, re.M)}
check("both suites are present and non-empty", all(spec.get(s) for s in ("boundary", "cluster")))
for suite, cases in spec.items():
    for c in cases:
        ok = {"name", "action", "expect", "identity"} <= set(c) and c["expect"] in ("allowed", "explicitDeny", "implicitDeny", "denied")
        check(f"{suite}: {c.get('name')!r} is well-formed", ok, c)
        text = json.dumps(c)
        check(f"{suite}: {c.get('name')!r} uses only placeholders the pipeline fills",
              set(re.findall(r"\$\{(\w+)\}", text)) <= {"account_id", "cluster_name", "region"})
        if suite == "cluster" and c.get("identity") != "allow-all":
            check(f"cluster: {c['name']!r} names policies the cluster root declares", set(c["identity"]) <= declared, c["identity"])
check("the effect tests hold an allowed case in each suite, so a deny-everything policy cannot pass",
      all(any(c["expect"] == "allowed" for c in spec[s]) for s in ("boundary", "cluster")))

print("reading AWS's answers")
rec = {"address": "aws_iam_policy.a", "attribute": "policy", "kind": "identity", "document": json.loads(doc(ALLOW))}
findings = {"findings": [
    {"findingType": "ERROR", "issueCode": "MISSING_VERSION", "findingDetails": "x", "locations": [{"path": [{"value": "Statement"}, {"index": 0}]}]},
    {"findingType": "SECURITY_WARNING", "issueCode": "PASS_ROLE_WITH_STAR_IN_RESOURCE", "findingDetails": "y", "locations": []},
    {"findingType": "WARNING", "issueCode": "w", "findingDetails": "z", "locations": []},
    {"findingType": "SUGGESTION", "issueCode": "s", "findingDetails": "z", "locations": []},
]}
got = p.syntax_failures(rec, findings)
check("check 1 fails on ERROR and SECURITY_WARNING only", len(got) == 2 and "MISSING_VERSION" in got[0] and "PASS_ROLE" in got[1], got)
check("check 1 says where in the document", "(at Statement, 0)" in got[0], got[0])
check("check 1 passes a document with only warnings", p.syntax_failures(rec, {"findings": findings["findings"][2:]}) == [])
for kind in ("identity", "boundary", "trust", "kms-key", "s3-bucket", "scp", "rcp"):
    check(f"check 1 knows the Access Analyzer type for {kind}", kind in p.VALIDATE_TYPES)

head = {"documents": [rec, {**rec, "address": "aws_iam_policy.new"}, {**rec, "address": "aws_iam_policy.same"},
                      {**rec, "address": "aws_organizations_policy.scp", "kind": "scp"}], "roles": [], "unknown": []}
wider = json.loads(doc(ALLOW))
wider["Statement"][0]["Action"] = ["bedrock:InvokeModel", "s3:GetObject"]
base = {"documents": [{**rec, "document": wider}, {**rec, "address": "aws_iam_policy.same"},
                      {**rec, "address": "aws_organizations_policy.scp", "kind": "scp", "document": wider}], "roles": [], "unknown": []}
pairs, new = p.diff_pairs(head, base)
check("check 2 sends only changed identity/boundary documents (each call is billed)",
      [(h["address"], b["address"]) for h, b in pairs] == [("aws_iam_policy.a", "aws_iam_policy.a")])
check("check 2 does not pretend to diff SCPs", all(h["kind"] != "scp" for h, _ in pairs) and all(n["kind"] != "scp" for n in new))
check("check 2 sees a policy with no counterpart on main", [n["address"] for n in new] == ["aws_iam_policy.new"])
check("check 2 fails a FAIL result and names the statement",
      p.diff_failures(rec, {"result": "FAIL", "message": "new access", "reasons": [{"statementIndex": 0, "description": "s3:GetObject"}]})
      == ["aws_iam_policy.a.policy: grants new access (FAIL): new access [Statement[0] s3:GetObject]"])
check("check 2 passes a PASS result", p.diff_failures(rec, {"result": "PASS", "message": ""}) == [])

case = {"name": "c", "identity": "allow-all", "action": "iam:CreateRole", "resource": "arn:aws:iam::${account_id}:role/x",
        "context": {"iam:PermissionsBoundary": "arn:aws:iam::${account_id}:policy/b"}, "expect": "explicitDeny"}
req = p.simulate_request(case, ext, {"account_id": "111122223333"})
check("check 4 sends the rendered boundary with the case", json.loads(req["PermissionsBoundaryPolicyInputList"][0]) == boundary)
check("check 4 fills placeholders in resource and context",
      req["ResourceArns"] == ["arn:aws:iam::111122223333:role/x"]
      and req["ContextEntries"][0]["ContextKeyValues"] == ["arn:aws:iam::111122223333:policy/b"])
check("check 4 can leave the boundary out", "PermissionsBoundaryPolicyInputList" not in p.simulate_request({**case, "boundary": "none"}, ext, {"account_id": "1"}))
check("check 4 refuses a case naming a policy the plan lacks",
      raises(lambda: p.simulate_request({**case, "identity": ["aws_iam_policy.gone"]}, ext, {"account_id": "1"}), "aws_iam_policy.gone"))
check("check 4 uses the plan's own documents",
      json.loads(p.simulate_request({**case, "identity": ["aws_iam_policy.bedrock_invoke"]}, ext, {"account_id": "1"})["PolicyInputList"][0])
      == json.loads(doc(ALLOW)))
ev = lambda *d: {"EvaluationResults": [{"EvalDecision": x} for x in d]}  # noqa: E731
check("check 4: matching decision passes", p.effect_failure(case, ev("explicitDeny")) is None)
check("check 4: an implicit deny is not the explicit deny a case asks for", p.effect_failure(case, ev("implicitDeny")) is not None)
check("check 4: 'denied' takes either deny", p.effect_failure({**case, "expect": "denied"}, ev("implicitDeny")) is None)
check("check 4: no answer is a failure, not a pass", p.effect_failure(case, {"EvaluationResults": []}) is not None)

print("conftest discovery")
import os  # noqa: E402
saved = os.environ.get("CONFTEST")
os.environ["CONFTEST"] = "/nonexistent/conftest"
try:
    check("a conftest path that is not there fails loudly", raises(p.conftest_binary, "conftest is not on PATH"))
finally:
    os.environ.pop("CONFTEST")
    if saved is not None:
        os.environ["CONFTEST"] = saved

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
