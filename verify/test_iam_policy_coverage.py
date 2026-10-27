# ABOUTME: Offline gate that org policies, the boundary and every IAM change go through the policy pipeline
# ABOUTME: (#207, #470, #549): no policy document outside the roots it runs on, SCPs and RCPs routed to checks 1 and 3.
#
# Why. test_iam_policy_pipeline.py proves each check reads a document correctly once the pipeline has it. This
# proves the pipeline gets all of them. It fails when a Terraform root the pipeline does not run on gains an
# IAM or Organizations resource, a policy data source, an inline resource policy or an IAM-shaped module
# input; when a resource type carrying a document is one extract() does not read; when an SCP or RCP stops
# reaching Access Analyzer with its own policy type or stops being judged by the Rego rules; and when a
# bounded role could write an org policy by hand. There is no SCP in the repo yet (the org half waits on
# org access, #202), so what is held here is the route one must take, not one that has already taken it.
import contextlib, fnmatch, io, json, pathlib, re, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra/org"))
sys.path.insert(0, str(REPO / "verify"))
import pipeline as p  # noqa: E402
import iam_plan_render  # noqa: E402

import yaml  # noqa: E402

failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


def blocks(text, header_re):
    """(match, body) of every top-level HCL block whose header matches, by brace counting."""
    out = []
    for m in re.finditer(header_re, text, re.M):
        depth, i = 0, m.end() - 1
        for j in range(i, len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                out.append((m, text[i:j + 1]))
                break
    return out


def top_level_args(body):
    """Argument names set directly in a block (terraform fmt indents them two spaces)."""
    return set(re.findall(r"^  ([a-z0-9_]+)\s*=", body, re.M))


print("the roots the pipeline runs on")
roots = {s: path.resolve() for s, path in p.ROOTS.items()}
check("pipeline.ROOTS names roots that exist", all((r / "main.tf").is_file() for r in roots.values()), roots)
check("iam_plan_render renders exactly those roots, so the E2E checks see each one",
      {s: path.resolve() for s, path in iam_plan_render.ROOTS.items()} == roots, iam_plan_render.ROOTS)
spec = yaml.safe_load(p.EFFECT_TESTS.read_text(encoding="utf-8"))
check("effect-tests.yaml has a suite for each root and no other", set(spec) == set(roots), sorted(spec))
for suite in roots:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = p.main(["effect", "--show", "/nonexistent/show.json", "--suite", suite, "--profile", "x", "--region", "y"])
    check(f"the CLI takes --suite {suite} (and then refuses the missing plan)", rc == 1 and "cannot read" in err.getvalue(),
          err.getvalue())
err = io.StringIO()
try:
    with contextlib.redirect_stderr(err):
        p.main(["effect", "--show", "x", "--suite", "network", "--profile", "x", "--region", "y"])
    refused = False
except SystemExit as e:
    refused = e.code == 2
check("the CLI refuses a suite that is not a root", refused, err.getvalue())

print("every IAM and org policy resource is in one of those roots")

# Every resource type extract() reads, proven by handing it one: the values it would see in a plan.
DOC = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Deny", "Action": "s3:*", "Resource": "*"}]})
TAUGHT = {
    "aws_iam_policy": {"name": "x", "policy": DOC},
    "aws_iam_role_policy": {"policy": DOC},
    "aws_iam_user_policy": {"policy": DOC},
    "aws_iam_group_policy": {"policy": DOC},
    "aws_iam_role": {"name": "x", "assume_role_policy": DOC},
    "aws_kms_key": {"policy": DOC},
    "aws_s3_bucket_policy": {"policy": DOC},
    "aws_organizations_policy": {"type": "SERVICE_CONTROL_POLICY", "content": DOC},
}
extracted = set()
for t, values in TAUGHT.items():
    plan = {"planned_values": {"root_module": {"resources": [
        {"address": f"{t}.x", "mode": "managed", "type": t, "name": "x", "values": values}]}}}
    if p.extract(plan)["documents"]:
        extracted.add(t)
check("extract() reads a document from every type it is said to", extracted == set(TAUGHT), sorted(set(TAUGHT) - extracted))
user_plan = {"planned_values": {"root_module": {"resources": [
    {"address": "aws_iam_user.x", "mode": "managed", "type": "aws_iam_user", "name": "x", "values": {"name": "x"}}]}}}
check("extract() lists every IAM user with the roles, so check 3 holds it to the boundary (#549)",
      p.extract(user_plan)["roles"] == [{"address": "aws_iam_user.x", "name": "x", "permissions_boundary": ""}])

# Types an IAM- or policy-shaped name would flag that hold no document of their own. The attachments name a
# policy by ARN, and that policy is checked where it is created; the boundary caps the role whatever it holds.
# A user's grant is its aws_iam_user_policy, read above; the user itself is held to the boundary (below). An
# EKS access policy association names an AWS-managed Kubernetes access policy by ARN: RBAC, not an IAM document.
NO_DOCUMENT = {
    "aws_iam_role_policy_attachment", "aws_iam_user_policy_attachment", "aws_iam_group_policy_attachment",
    "aws_iam_policy_attachment", "aws_iam_instance_profile", "aws_organizations_policy_attachment",
    "aws_iam_user", "aws_eks_access_policy_association",
}
# Policy in the name, but not an IAM grant.
NOT_IAM = {"aws_autoscaling_policy", "aws_appautoscaling_policy", "aws_ecr_lifecycle_policy", "aws_dlm_lifecycle_policy"}
# Resources that take an optional resource-policy argument extract() does not read. Setting it would put a
# document past every check, so it is refused until the pipeline is taught that type.
INLINE_POLICY_ARGS = {
    "aws_vpc_endpoint": "policy", "aws_sqs_queue": "policy", "aws_sns_topic": "policy",
    "aws_secretsmanager_secret": "policy", "aws_s3_bucket": "policy", "aws_api_gateway_rest_api": "policy",
    "aws_opensearch_domain": "access_policies", "aws_elasticsearch_domain": "access_policies",
    "aws_glacier_vault": "access_policy", "aws_ecr_repository": "policy",
}
IAM_SHAPED = re.compile(r"^aws_(iam|organizations)_|^aws_.*polic")
# A module input with one of these in its name asks a registry module to create IAM (a flow-log role, an
# IRSA role, a bucket policy). In a pipeline root the rendered plan shows what it made; anywhere else nothing would.
IAM_INPUT = re.compile(r"iam|polic|role|permissions_boundary|flow_log")

listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard", "*.tf"],
                        capture_output=True, text=True, check=True).stdout.split()
# infra/policy/plan/fixtures holds deliberately violating plans for the plan-policy tests (#200), not IAM
# anything applies.
tf_files = [REPO / f for f in listed if (REPO / f).is_file() and not f.startswith("infra/policy/plan/fixtures/")]
check("the repo has Terraform to look at", len(tf_files) > 0)
seen = {"resource": 0, "outside": 0}
for f in sorted(tf_files):
    rel = f.relative_to(REPO)
    in_pipeline = f.parent.resolve() in roots.values()
    text = f.read_text(encoding="utf-8")
    for m, body in blocks(text, r'^resource "(aws_[a-z0-9_]+)" "([^"]+)" \{'):
        t, name = m.group(1), m.group(2)
        seen["resource"] += 1
        seen["outside"] += not in_pipeline
        if IAM_SHAPED.search(t) and t not in NOT_IAM:
            check(f"{rel}: {t}.{name} is in a root the pipeline runs on", in_pipeline)
            check(f"{rel}: {t}.{name} is a type the pipeline reads, or one with no document",
                  t in extracted or t in NO_DOCUMENT,
                  f"teach extract() the document in {t}, or list it in NO_DOCUMENT here with the reason")
        arg = INLINE_POLICY_ARGS.get(t)
        if arg:
            check(f"{rel}: {t}.{name} sets no {arg}, which no check would see", arg not in top_level_args(body))
    for m, _ in blocks(text, r'^data "aws_iam_policy_document" "([^"]+)" \{'):
        check(f"{rel}: data.aws_iam_policy_document.{m.group(1)} is in a root the pipeline runs on", in_pipeline)
    if not in_pipeline:
        for m, body in blocks(text, r'^module "([^"]+)" \{'):
            asks = sorted(a for a in top_level_args(body) if IAM_INPUT.search(a))
            check(f"{rel}: module.{m.group(1)} asks for no IAM outside the pipeline's roots", not asks, asks)
check("the scan read resources, roots outside the pipeline among them", seen["resource"] > 0 and seen["outside"] > 0, seen)

print("no script writes an IAM policy by API call")
# A policy written by the aws CLI or boto3 is in no plan, so none of the four checks ever sees it. That is how
# the attendee users' inline policy escaped until #549: provisioning-agenticburn's generate_attendee_aws.py
# called put_user_policy, run from fleet.sh. Grants are Terraform's, in a pipeline root; a script may mint a
# key or delete what teardown finds, but not write a grant or a role. Tests are left out: their shims answer
# these calls, they do not make them.
IAM_WRITE = re.compile(
    r"\biam\s+(put-(user|role|group)-policy|create-policy(-version)?|attach-(user|role|group)-policy|create-role"
    r"|update-assume-role-policy|put-(user|role)-permissions-boundary|create-user)\b"
    r"|\b(put_(user|role|group)_policy|create_policy(_version)?|attach_(user|role|group)_policy|create_role"
    r"|update_assume_role_policy|put_(user|role)_permissions_boundary|create_user)\s*\(")
code = [REPO / f for f in subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard"],
                                         capture_output=True, text=True, check=True).stdout.split()
        if not f.endswith((".tf", ".md", ".lock.hcl")) and not f.startswith(("verify/test_", "tmp/"))]
writes, scanned = [], 0
for f in code:
    if not f.is_file():
        continue
    try:
        text = f.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    scanned += 1
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith(("#", "//")):
            continue
        if IAM_WRITE.search(s) or (f.suffix in (".sh", ".py") and "generate_attendee_aws" in s):
            writes.append(f"{f.relative_to(REPO)}:{n}: {s[:120]}")
check("the scan read the repo's scripts", scanned > 100, scanned)
check("no script creates an IAM user, role or policy, or runs generate_attendee_aws.py, outside Terraform",
      not writes, "\n        ".join(writes))

print("org policies and the boundary are routed to the checks that judge them")
rego = (p.POLICY_DIR / "iam.rego").read_text(encoding="utf-8")
m = re.search(r"^permission_kinds := \{([^}]*)\}", rego, re.M)
rego_kinds = set(re.findall(r'"([a-z-]+)"', m.group(1))) if m else set()
check("iam.rego judges the same kinds pipeline.py hands it", rego_kinds == set(p.PERMISSION_KINDS), rego_kinds)
for org_type, kind in (("SERVICE_CONTROL_POLICY", "scp"), ("RESOURCE_CONTROL_POLICY", "rcp")):
    check(f"an Organizations {org_type} is extracted as {kind}", p.ORG_POLICY_KINDS.get(org_type) == kind)
    check(f"check 1 validates a {kind} as Access Analyzer's {org_type}", p.VALIDATE_TYPES.get(kind) == (org_type, None))
    check(f"check 3 judges every {kind}, since check 2 cannot diff one",
          kind in p.PERMISSION_KINDS and kind in rego_kinds and kind not in p.DIFF_KINDS)
check("the boundary goes through checks 1, 2 and 3",
      "boundary" in p.VALIDATE_TYPES and "boundary" in p.DIFF_KINDS and "boundary" in p.PERMISSION_KINDS)

calls = []
real_aws = p.aws
p.aws = lambda profile, region, *args: calls.append(args) or {"findings": []}
try:
    org_plan = {"planned_values": {"root_module": {"resources": [
        {"address": f"aws_organizations_policy.{n}", "mode": "managed", "type": "aws_organizations_policy", "name": n,
         "values": {"type": t, "content": DOC}} for n, t in (("scp", "SERVICE_CONTROL_POLICY"), ("rcp", "RESOURCE_CONTROL_POLICY"))]}}}
    p.syntax(p.extract(org_plan), "x", "y")
finally:
    p.aws = real_aws
sent = [a[a.index("--policy-type") + 1] for a in calls]
check("check 1 sends each org policy to validate-policy with its own type",
      sent == ["SERVICE_CONTROL_POLICY", "RESOURCE_CONTROL_POLICY"] and all("--validate-policy-resource-type" not in a for a in calls), calls)
unknown_scp = {**org_plan, "resource_changes": [
    {"address": "aws_organizations_policy.scp", "change": {"after_unknown": {"content": True}}}]}
del unknown_scp["planned_values"]["root_module"]["resources"][0]["values"]["content"]
try:
    p.require_known(p.extract(unknown_scp))
    stopped = False
except p.PipelineError as e:
    stopped = "aws_organizations_policy.scp.content" in str(e)
check("an SCP known only after apply stops the run, it is not let through", stopped)
for other in ("S3_POLICY", "TAG_POLICY", "BACKUP_POLICY", "AISERVICES_OPT_OUT_POLICY", "CHATBOT_POLICY",
              "DECLARATIVE_POLICY_EC2"):
    plan = {"planned_values": {"root_module": {"resources": [
        {"address": "aws_organizations_policy.o", "mode": "managed", "type": "aws_organizations_policy", "name": "o",
         "values": {"type": other, "content": "{}"}}]}}}
    try:
        p.extract(plan)
        loud = False
    except p.PipelineError as e:
        loud = other in str(e)
    check(f"an Organizations {other} has no check yet, so it fails the run instead of passing unseen", loud)

print("a bounded role cannot write an org policy by hand")
boundary = p.render_boundary("111122223333")


def as_list(x):
    return x if isinstance(x, list) else [x]


ORG_POLICY_WRITES = ("organizations:AttachPolicy", "organizations:DetachPolicy", "organizations:CreatePolicy",
                     "organizations:UpdatePolicy", "organizations:DeletePolicy", "organizations:DisablePolicyType")
cases = {(c["action"], c["expect"]) for c in spec["boundary"]
         if c.get("identity") == "allow-all" and c.get("boundary", "canonical") == "canonical"}
for action in ORG_POLICY_WRITES:
    check(f"the boundary denies {action} outright, whatever the role is granted",
          any(s["Effect"] == "Deny" and not s.get("Condition") and as_list(s.get("Resource")) == ["*"]
              and any(fnmatch.fnmatchcase(action, a) for a in as_list(s["Action"])) for s in boundary["Statement"]))
    check(f"check 4 asks the simulator for an explicit deny of {action}", (action, "explicitDeny") in cases)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
