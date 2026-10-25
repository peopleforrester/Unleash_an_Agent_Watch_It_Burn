# ABOUTME: Check 3 of the IAM policy pipeline (#207) on the repo's real roots: the Rego unit tests, then the
# ABOUTME: cluster and boundary plans pass, and a plan with an unconditioned Allow fails naming its statement.
# SUITE: e2e (needs conftest v0.71.1 and terraform on PATH, and network to registry.terraform.io)
#
# The plans are rendered from today's main.tf by verify/iam_plan_render.py (no AWS account needed), so this
# is the structural check judging the documents the repo would apply, module-generated ones included. The
# mutated plan is the issue's acceptance case: an Allow without a Condition fails with the statement index.
import os, pathlib, re, shutil, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra/org"))
sys.path.insert(0, str(REPO / "verify"))
import pipeline as p  # noqa: E402
import iam_plan_render  # noqa: E402

WANT_CONFTEST = "0.71.1"
failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


exe = os.environ.get("CONFTEST") or shutil.which("conftest")
if not exe:
    print(f"FAIL: conftest is not on PATH (or set CONFTEST). Install v{WANT_CONFTEST} from "
          f"https://github.com/open-policy-agent/conftest/releases/tag/v{WANT_CONFTEST}", file=sys.stderr)
    sys.exit(1)
ver = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
if f"Conftest: {WANT_CONFTEST}" not in ver:
    print(f"FAIL: conftest is not v{WANT_CONFTEST}; got {ver.strip()!r}", file=sys.stderr)
    sys.exit(1)

print("Rego unit tests (conftest verify)")
r = subprocess.run([exe, "verify", "--no-color", "--policy", str(p.POLICY_DIR)], capture_output=True, text=True)
check("every iam_test.rego case passes", r.returncode == 0 and re.search(r"\b0 failures\b", r.stdout) is not None,
      r.stdout + r.stderr)

print("the repo's own plans")
for root in ("boundary", "cluster"):
    ext = p.extract(iam_plan_render.render(root))
    check(f"{root}: every document is known at plan time", ext["unknown"] == [], ext["unknown"])
    msgs = p.structural(ext)
    check(f"{root}: passes the structural check", msgs == [], "\n        ".join(msgs))
    check(f"{root}: has documents to check", len(ext["documents"]) > 0)
    if root == "cluster":
        check("cluster: every role it creates, and the attendee user, is in the plan, and all carry the boundary",
              len(ext["roles"]) == 6 and all(r["permissions_boundary"].endswith(f":policy/{p.BOUNDARY_NAME}") for r in ext["roles"])
              and "aws_iam_user.attendee" in {r["address"] for r in ext["roles"]}, ext["roles"])
        check("cluster: the attendee user's inline policy is a document the checks read (#549)",
              any(d["address"] == "aws_iam_user_policy.attendee_eks" and d["kind"] == "identity" for d in ext["documents"]),
              sorted(d["address"] for d in ext["documents"]))


print("a plan that breaks the rules")


def break_rules(tf):
    # 1. The agent's Bedrock grant loses its Condition (the issue's acceptance case).
    start = tf.index('resource "aws_iam_policy" "bedrock_invoke"')
    c0 = tf.index("      Condition = {", start)
    inner = tf.index("\n        }\n", c0) + len("\n        }\n")
    c1 = tf.index("      }\n", inner) + len("      }\n")
    tf = tf[:c0] + tf[c1:]
    # 2. The ESO role loses its boundary.
    start = tf.index('module "eso_pod_identity"')
    line = tf.index("  permissions_boundary_arn", start)
    tf = tf[:line] + tf[tf.index("\n", line) + 1:]
    # 3. The tutor's grant widens to every resource.
    start = tf.index('resource "aws_iam_policy" "tutor_bedrock_invoke"')
    r0 = tf.index("      Resource = [", start)
    r1 = tf.index("      ]\n", r0) + len("      ]\n")
    tf = tf[:r0] + '      Resource = "*"\n' + tf[r1:]
    # 4. The attendee user loses its boundary (#549).
    start = tf.index('resource "aws_iam_user" "attendee"')
    line = tf.index("  permissions_boundary", start)
    return tf[:line] + tf[tf.index("\n", line) + 1:]


msgs = p.structural(p.extract(iam_plan_render.render("cluster", edit=break_rules)))
print("    " + "\n    ".join(msgs))
check("an Allow without a Condition fails, naming the address and the statement index",
      "aws_iam_policy.bedrock_invoke: Statement[0] is an Allow with no Condition [allow-without-condition]" in msgs)
check("a role without the boundary fails",
      "module.eso_pod_identity.aws_iam_role.this[0] has no permissions_boundary; every role and user carries "
      f"{p.BOUNDARY_NAME} [role-boundary]" in msgs)
check("Resource \"*\" outside exceptions.md fails",
      'aws_iam_policy.tutor_bedrock_invoke: Statement[0] allows Resource "*" (or uses NotResource) [resource-star]' in msgs)
check("a user without the boundary fails",
      f"aws_iam_user.attendee has no permissions_boundary; every role and user carries {p.BOUNDARY_NAME} [role-boundary]" in msgs)
check("nothing else fails: the waivers in exceptions.md still hold", len(msgs) == 4, msgs)

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
