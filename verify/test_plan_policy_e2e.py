# ABOUTME: Proves the plan-time policy check on real plans, made by both Terraform and OpenTofu (#200).
# ABOUTME: Each violation fails under its named policy, the compliant twin passes, and the fleet passes with every exception used.
# SUITE: e2e (needs the pinned toolchain on PATH and network for providers and modules: install-tools.py)
"""Why this exists (#200).

The acceptance for #200 is behavioural: "a PR adding acl = "public-read" to any aws_s3_bucket fails the
plan check with a named policy", and "checks read OpenTofu natively". Neither can be shown without real
plan JSON from real binaries, so this test makes plans with both and runs check-plan.py on them:

1. fixtures/violating: every resource breaks exactly one policy, and the check must fail and name that
   policy and that address. A check that passes everything fails here.
2. fixtures/compliant: the safe twin of each, which must pass. A check that rejects everything fails here.
3. The real fleet roots, planned against a local AWS API by plan-fleet.py, must pass with every row in
   exceptions.md used. That catches a policy change that breaks the fleet, and an exception that has gone
   stale because the code it excused changed.

Prerequisites are checked first and all reported together; a missing one is a failure, not a skip.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
PLAN = REPO / "infra" / "policy" / "plan"
TOOLS = yaml.safe_load((PLAN / "tools.yaml").read_text())

# What fixtures/violating must be failed for, by the Kyverno policy that names it.
EXPECTED = {
    "no-public-s3-acl": ["aws_s3_bucket.public_read (acl = public-read)",
                         "aws_s3_bucket_acl.public_read_write (acl = public-read-write)",
                         "aws_s3_bucket_acl.all_users_grant (grant to a public group)"],
    "no-public-eks-endpoint": ["aws_eks_cluster.default_endpoint"],
    "no-iam-wildcard": ["aws_iam_policy.admin", "aws_iam_role_policy.any_bucket",
                        "aws_iam_user_policy.star_colon_star", "aws_iam_role.not_action inline_policy everything-but-iam"],
    "no-unencrypted-rds": ["aws_db_instance.plain", "aws_rds_cluster.plain"],
}
# And the scanners' independent re-check of the same rules (gates.yaml), as "<policy> (<tool> <rule>): <address>".
EXPECTED_SCANNER = [
    "no-public-s3-acl (checkov CKV_AWS_20): aws_s3_bucket.public_read",
    "no-public-s3-acl (trivy AWS-0092): aws_s3_bucket.public_read",
    "no-public-eks-endpoint (checkov CKV_AWS_39): aws_eks_cluster.default_endpoint",
    "no-public-eks-endpoint (trivy AWS-0040): aws_eks_cluster.default_endpoint",
    "no-iam-wildcard (checkov CKV_AWS_62): aws_iam_policy.admin",
    "no-unencrypted-rds (checkov CKV_AWS_16): aws_db_instance.plain",
    "no-unencrypted-rds (trivy AWS-0080): aws_db_instance.plain",
]

failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def tf_version(binary: str) -> str | None:
    try:
        out = subprocess.run([binary, "version", "-json"], capture_output=True, text=True, timeout=60).stdout
    except FileNotFoundError:
        return None
    return json.loads(out).get("terraform_version")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def plan_fixture(binary: str, fixture: str, work: pathlib.Path) -> pathlib.Path:
    dst = work / f"{binary}-{fixture}"
    shutil.copytree(PLAN / "fixtures" / fixture, dst)
    for step in (["init", "-input=false", "-no-color"], ["plan", "-input=false", "-no-color", "-out=plan.bin"]):
        proc = run([binary, f"-chdir={dst}", *step])
        if proc.returncode != 0:
            raise SystemExit(f"{binary} {step[0]} failed on fixtures/{fixture}:\n{proc.stdout}{proc.stderr}")
    out = dst / "plan.json"
    out.write_text(run([binary, f"-chdir={dst}", "show", "-json", "plan.bin"], check=True).stdout)
    return out


missing = []
for binary in ("terraform", "tofu"):
    got, want = tf_version(binary), str(TOOLS["binaries"][binary]["version"])
    if got != want:
        missing.append(f"{binary} is {got or 'not on PATH'}, pinned {want}")
for tool in ("kyverno", "trivy", "checkov", "moto_server"):
    if shutil.which(tool) is None:
        missing.append(f"{tool} is not on PATH")
if missing:
    print("PLAN POLICY E2E CANNOT RUN; this is a failure, not a skip:", file=sys.stderr)
    for m in missing:
        print(f"  - {m}", file=sys.stderr)
    print(f"  install the pinned set: python3 {PLAN / 'install-tools.py'} <dir>, then PATH=<dir>/bin:$PATH",
          file=sys.stderr)
    sys.exit(1)

checker = [sys.executable, str(PLAN / "check-plan.py")]
with tempfile.TemporaryDirectory() as tmp:
    work = pathlib.Path(tmp)
    for binary in ("terraform", "tofu"):
        print(f"== {binary}: fixtures/violating fails, naming each policy and address ==")
        res = run([*checker, str(plan_fixture(binary, "violating", work))])
        check(f"{binary}: check-plan exits 1 on the violating plan", res.returncode == 1)
        summary = res.stdout.split("\n== summary", 1)[-1]
        for policy, addresses in EXPECTED.items():
            line = next((ln for ln in summary.splitlines() if ln.strip().startswith(f"{policy} (kyverno):")), "")
            check(f"{binary}: {policy} is named as failing", bool(line))
            for a in addresses:
                check(f"{binary}: {policy} names {a}", a in line)
        for expected in EXPECTED_SCANNER:
            check(f"{binary}: {expected}", expected in summary)

        print(f"== {binary}: fixtures/compliant passes ==")
        res = run([*checker, str(plan_fixture(binary, "compliant", work))])
        if res.returncode != 0:
            print(res.stdout[-4000:], res.stderr[-2000:])
        check(f"{binary}: check-plan exits 0 on the compliant plan", res.returncode == 0)

        print(f"== {binary}: the real fleet roots pass, with every exception still needed ==")
        fleet = work / f"{binary}-fleet"
        planned = run([sys.executable, str(PLAN / "plan-fleet.py"), "--tf", binary, str(fleet)])
        print(planned.stdout.strip())
        check(f"{binary}: plan-fleet planned both roots", planned.returncode == 0)
        if planned.returncode != 0:
            print(planned.stderr[-4000:])
            continue
        res = run([*checker, "--require-all-exceptions-used",
                   str(fleet / "network.plan.json"), str(fleet / "cluster.plan.json")])
        if res.returncode != 0:
            print(res.stdout[-6000:], res.stderr[-2000:])
        check(f"{binary}: the fleet passes and every exceptions.md row matched a finding", res.returncode == 0)

if failures:
    print(f"\nFAILED: {len(failures)} check(s)")
    sys.exit(1)
print("\nAll plan-policy e2e checks passed.")
