# ABOUTME: Checks 1, 2 and 4 of the IAM policy pipeline (#207) against AWS: Access Analyzer validates every
# ABOUTME: document, check-no-new-access fails a widened agent policy, and the simulator runs effect-tests.yaml.
# SUITE: e2e (needs terraform and the aws CLI, IAM_PIPELINE_PROFILE and IAM_PIPELINE_REGION; check 2 is billed)
#
# The documents are today's, rendered by verify/iam_plan_render.py. Access Analyzer and the policy simulator
# judge a document as text, so the render's stand-in account id does not change their answer. The caller
# needs access-analyzer:ValidatePolicy, access-analyzer:CheckNoNewAccess and iam:SimulateCustomPolicy.
# Check 2 is called exactly twice per run (one widening, one narrowing); unchanged documents are not sent.
import copy, os, pathlib, shutil, sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra/org"))
sys.path.insert(0, str(REPO / "verify"))
import pipeline as p  # noqa: E402
import iam_plan_render  # noqa: E402

failures = []


def check(n, c, detail=""):
    print(f"  {'PASS' if c else 'FAIL'}  {n}" + (f"\n        {detail}" if (detail and not c) else ""))
    if not c:
        failures.append(n)


missing = [m for m, ok in (("the aws CLI is not on PATH", shutil.which("aws")),
                           ("IAM_PIPELINE_PROFILE is not set: name the AWS profile to run Access Analyzer and the "
                            "simulator as", os.environ.get("IAM_PIPELINE_PROFILE")),
                           ("IAM_PIPELINE_REGION is not set", os.environ.get("IAM_PIPELINE_REGION"))) if not ok]
if missing:
    print("FAIL: cannot run the AWS half of the policy pipeline:\n  - " + "\n  - ".join(missing), file=sys.stderr)
    sys.exit(1)
PROFILE, REGION = os.environ["IAM_PIPELINE_PROFILE"], os.environ["IAM_PIPELINE_REGION"]

shows = {root: iam_plan_render.render(root) for root in ("boundary", "cluster")}
exts = {root: p.extract(show) for root, show in shows.items()}

print("check 1: Access Analyzer validate-policy")
for root, ext in exts.items():
    got = p.syntax(ext, PROFILE, REGION)
    check(f"{root}: no ERROR or SECURITY_WARNING in {len(ext['documents'])} documents", got == [], "\n        ".join(got))

print("check 2: check-no-new-access against the unchanged plan")
base = exts["cluster"]
pairs, new = p.diff_pairs(base, base)
check("an unchanged plan sends nothing (and costs nothing)", pairs == [] and new == [])


def with_agent_policy(mutate):
    head = copy.deepcopy(base)
    rec = next(d for d in head["documents"] if d["address"] == "aws_iam_policy.bedrock_invoke")
    mutate(rec["document"]["Statement"][0])
    return head


wider = with_agent_policy(lambda st: st["Action"].append("s3:GetObject"))
got = p.diff(wider, base, PROFILE, REGION, accept_new=[])
check("a widening identity policy fails check 2, naming the policy",
      len(got) == 1 and got[0].startswith("aws_iam_policy.bedrock_invoke.policy: grants new access"), got)
narrower = with_agent_policy(lambda st: st["Action"].remove("bedrock:ConverseStream"))
got = p.diff(narrower, base, PROFILE, REGION, accept_new=[])
check("a narrowing identity policy passes check 2", got == [], got)

print("check 4: effect tests (iam simulate-custom-policy)")
for root, suite in (("boundary", "boundary"), ("cluster", "cluster")):
    got = p.effect(exts[root], shows[root], suite, PROFILE, REGION)
    check(f"{suite}: every case in effect-tests.yaml gets the decision it expects", got == [], "\n        ".join(got))

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
