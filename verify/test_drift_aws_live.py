# ABOUTME: E2E acceptance for #205 on the AWS plane: an attendee key cannot make a bucket and CloudTrail records the
# ABOUTME: refusal; a bucket made out of band shows in AWS Config and in the next drift report. Real AWS, cleans up.
# SUITE: e2e
"""Usage:
  DRIFT_PROFILE=<operator profile> ATTENDEE_CLUSTER=<cluster> [DRIFT_REGION=us-west-2] \\
      python3 verify/test_drift_aws_live.py

DRIFT_PROFILE is the operator's profile for one fleet account. That account must already have the audit root
applied (infra/terraform/aws/audit), and the profile must be one of WIB_ATTENDEE_ACCOUNTS: the drift report
plans every state the fleet keeps, so it needs every account's profile. ATTENDEE_CLUSTER names a cluster in
that account whose attendee key is in infra/terraform/fleet/aws-pool/<cluster>.csv (or set ATTENDEE_KEY_CSV).
The CSV holds name,region,access_key,secret_key, as fleet.sh's mint_attendee_key writes it.

Why two buckets: an attendee key cannot create a bucket (its one grant is the cluster root's
aws_iam_user_policy.attendee_eks, eks:DescribeCluster on its own cluster and eks:ListClusters, and the offline effect
test "the attendee user cannot make a bucket" holds that), so the issue's "hand-made bucket via attendee keys" is a
refused call, and the record of it is CloudTrail's. The bucket that does exist out of band has to come from a principal that can make one, the
operator, and that is the one Config and the drift report must show. Both buckets are deleted at the end,
pass or fail. A missing tool, credential or recorder fails the test by name.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
REPORT = REPO / "infra/terraform/drift/drift-report.py"
PROFILE = os.environ.get("DRIFT_PROFILE", "")
REGION = os.environ.get("DRIFT_REGION", "us-west-2")
CLUSTER = os.environ.get("ATTENDEE_CLUSTER", "")
KEY_CSV = pathlib.Path(os.environ.get("ATTENDEE_KEY_CSV")
                       or REPO / f"infra/terraform/fleet/aws-pool/{CLUSTER}.csv")
# The accounts the report plans: WIB_ATTENDEE_ACCOUNTS, else fleet.sh's own default, read rather than copied.
_FLEET_DEFAULT = re.search(r'^WIB_ATTENDEE_ACCOUNTS="\$\{WIB_ATTENDEE_ACCOUNTS:-([^}]*)\}"$',
                           (REPO / "infra/terraform/fleet/fleet.sh").read_text(encoding="utf-8"), re.M)
ACCOUNTS = os.environ.get("WIB_ATTENDEE_ACCOUNTS") or (_FLEET_DEFAULT.group(1) if _FLEET_DEFAULT else "")
RECORD_WAIT_S = 1200   # Config discovery and CloudTrail event history both lag; 20 minutes is generous for both
POLL_S = 30
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def aws(*args: str, env: dict | None = None, profile: str | None = PROFILE) -> subprocess.CompletedProcess:
    cmd = ["aws", *args, "--region", REGION, "--output", "json"] + (["--profile", profile] if profile else [])
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def attendee_env(ak: str, sk: str) -> dict:
    """The attendee key and nothing else: no profile, no config or credentials file that could lend it more."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    e.update(AWS_ACCESS_KEY_ID=ak, AWS_SECRET_ACCESS_KEY=sk, AWS_CONFIG_FILE=os.devnull,
             AWS_SHARED_CREDENTIALS_FILE=os.devnull, AWS_REGION=REGION)
    return e


def create_bucket(name: str, env: dict | None = None, profile: str | None = PROFILE) -> subprocess.CompletedProcess:
    loc = [] if REGION == "us-east-1" else ["--create-bucket-configuration", f"LocationConstraint={REGION}"]
    return aws("s3api", "create-bucket", "--bucket", name, *loc, env=env, profile=profile)


def finish() -> int:
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("AWS-plane drift acceptance passed.")
    return 0


def main() -> int:
    print("== prerequisites ==")
    for tool in ("aws", "terraform"):
        check(f"{tool} is on PATH", shutil.which(tool) is not None)
    check("DRIFT_PROFILE names the operator profile", bool(PROFILE))
    check("DRIFT_PROFILE is one of WIB_ATTENDEE_ACCOUNTS (the report plans every account's states)",
          PROFILE in ACCOUNTS.split(","))
    check(f"the attendee key CSV is readable ({KEY_CSV})", KEY_CSV.is_file())
    if failures:
        return finish()
    ident = aws("sts", "get-caller-identity")
    check(f"DRIFT_PROFILE authenticates ({ident.stderr.strip() or 'ok'})", ident.returncode == 0)
    rows = list(csv.reader(KEY_CSV.read_text().splitlines()))
    ak, sk = (rows[1][2].strip(), rows[1][3].strip()) if len(rows) > 1 and len(rows[1]) >= 4 else ("", "")
    check("the CSV has an access key and secret on its first data row", bool(ak and sk))
    rec = aws("configservice", "describe-configuration-recorder-status")
    recording = rec.returncode == 0 and any(s.get("recording") for s in json.loads(rec.stdout or "{}").get(
        "ConfigurationRecordersStatus", []))
    check("a Config recorder is recording in the account (apply infra/terraform/aws/audit if not)", recording)
    if failures:
        return finish()
    account = json.loads(ident.stdout)["Account"]
    who = subprocess.run(["aws", "sts", "get-caller-identity", "--output", "json"], capture_output=True,
                         text=True, env=attendee_env(ak, sk))
    check(f"the attendee key authenticates ({who.stderr.strip() or 'ok'})", who.returncode == 0)
    if failures:
        return finish()
    attendee_arn = json.loads(who.stdout)["Arn"]
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    refused, oob = f"wib-drift-attendee-{account}-{stamp}", f"wib-drift-oob-{account}-{stamp}"
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    made: list[str] = []
    try:
        print(f"== the attendee key ({attendee_arn}) tries to make {refused} ==")
        p = create_bucket(refused, env=attendee_env(ak, sk), profile=None)
        if p.returncode == 0:
            made.append(refused)
        check(f"refused with AccessDenied ({(p.stderr.strip() or 'it SUCCEEDED').splitlines()[-1]})",
              p.returncode != 0 and "AccessDenied" in p.stderr)

        print(f"== the operator makes {oob} out of band ==")
        p = create_bucket(oob)
        check(f"created ({p.stderr.strip() or 'ok'})", p.returncode == 0)
        if p.returncode != 0:
            return finish()
        made.append(oob)

        print(f"== waiting up to {RECORD_WAIT_S}s for Config and CloudTrail ==")
        in_config = denied_logged = False
        t0 = time.monotonic()
        while time.monotonic() - t0 < RECORD_WAIT_S and not (in_config and denied_logged):
            if not in_config:
                h = aws("configservice", "get-resource-config-history", "--resource-type", "AWS::S3::Bucket",
                        "--resource-id", oob, "--limit", "1")
                in_config = h.returncode == 0 and bool(json.loads(h.stdout or "{}").get("configurationItems"))
            if not denied_logged:
                ev = aws("cloudtrail", "lookup-events", "--lookup-attributes",
                         "AttributeKey=EventName,AttributeValue=CreateBucket", "--start-time", started)
                for e in json.loads(ev.stdout or "{}").get("Events", []) if ev.returncode == 0 else []:
                    body = json.loads(e.get("CloudTrailEvent", "{}"))
                    if (body.get("userIdentity", {}).get("arn") == attendee_arn
                            and (body.get("requestParameters") or {}).get("bucketName") == refused):
                        denied_logged = body.get("errorCode") == "AccessDenied"
            if not (in_config and denied_logged):
                time.sleep(POLL_S)
        print(f"  after {time.monotonic() - t0:.0f}s")
        check(f"AWS Config has a configuration item for {oob}", in_config)
        check(f"CloudTrail records the attendee's CreateBucket for {refused} as AccessDenied", denied_logged)

        print("== the next drift report lists it as unmanaged ==")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "report.md"
            r = subprocess.run([sys.executable, str(REPORT), "--accounts", ACCOUNTS, "--region", REGION,
                                "--out", str(out)], capture_output=True, text=True)
            text = out.read_text() if out.is_file() else r.stdout
        unmanaged = text.split("## Unmanaged", 1)[-1].split("\n## ", 1)[0]
        # drift-report.py returns 0 clean, 1 incomplete, 2 findings; the out-of-band bucket is a finding.
        check(f"the report completed with findings, code 2 (got {r.returncode})", r.returncode == 2)
        row = next((ln for ln in unmanaged.splitlines() if f"`{oob}`" in ln), "")
        check(f"{oob} is in the report's Unmanaged table", bool(row))
        # By now CloudTrail has the attendee's call, made seconds before the operator's, so this one is there too.
        check("with the operator as its creator, from CloudTrail", json.loads(ident.stdout)["Arn"] in row)
        check("and Config's record of it", "recorded " in row)
        if r.returncode == 1:
            print(text)
    finally:
        for b in made:
            d = aws("s3api", "delete-bucket", "--bucket", b)
            print(f"  cleanup: delete {b}: {'ok' if d.returncode == 0 else d.stderr.strip()}")
            check(f"cleanup removed {b}", d.returncode == 0)
    return finish()


if __name__ == "__main__":
    sys.exit(main())
