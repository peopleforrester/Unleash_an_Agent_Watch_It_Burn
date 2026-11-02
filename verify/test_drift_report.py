# ABOUTME: Behavioural tests for the AWS-plane drift report (#205): refresh-only plans per state, unmanaged buckets
# ABOUTME: and clusters found and attributed, the register honoured, the Config check, exit codes, and the post.
"""Offline. terraform, aws and gh are shims on PATH that answer from a fixture, so nothing here reaches AWS or
GitHub. The fixture is one shared account (accen-dev, with a co-tenant, a lab-platform cluster and the exfil
game's bucket in it) and one rented account (aws1-student31) holding a drifted cluster, an orphaned cluster and a
bucket made by hand in another region with no Config recorder running, plus a standby (#643) in us-east-1 with its
own regional lab VPC and an orphaned cluster left in us-east-2, a region only backups.tsv names. The acceptance case on the issue, a
hand-made bucket, is `hand-made-by-hand`: it must come out of the report as unmanaged, with who made it and
whether Config has it. The tree is a scratch copy holding the real fleet.sh, so the accounts the report covers
by default are the ones the fleet builds in, and the real backups.tsv, so the regions it sweeps are the
standbys'.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
REPORT = REPO / "infra/terraform/drift/drift-report.py"
SCHED = REPO / "infra/terraform/drift/scheduled-drift.sh"
REGISTER = REPO / "infra/terraform/drift/known-unmanaged.yaml"
FLEET = REPO / "infra/terraform/fleet/fleet.sh"
BACKUPS = REPO / "infra/terraform/fleet/backups.tsv"
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


FAKE_AWS = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("aws " + json.dumps(a) + "\n")
fx = json.load(open(os.environ["FAKE_AWS"]))
def opt(n):
    return a[a.index(n) + 1] if n in a else None
prof, key = opt("--profile"), " ".join(a[:2])
acct = fx.get(prof)
if acct is None or acct.get("broken"):
    sys.stderr.write("An error occurred (ExpiredToken): The security token included in the request is expired\n")
    sys.exit(255)
def out(v):
    print(json.dumps(v)); sys.exit(0)
if key == "sts get-caller-identity":
    out({"Account": acct["id"]})
if key == "s3api list-buckets":
    out({"Buckets": [{"Name": n, "CreationDate": b.get("created", "2026-10-01T00:00:00Z")} for n, b in acct["buckets"].items()]})
if key == "s3api get-bucket-tagging":
    tags = acct["buckets"][opt("--bucket")].get("tags")
    if not tags:
        sys.stderr.write("An error occurred (NoSuchTagSet) when calling the GetBucketTagging operation\n"); sys.exit(254)
    out({"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]})
if key == "s3api get-bucket-location":
    out({"LocationConstraint": acct["buckets"][opt("--bucket")].get("region")})
if key == "eks list-clusters":
    out({"clusters": [n for n, c in acct["clusters"].items() if c.get("region", "us-west-2") == opt("--region")]})
if key == "eks describe-cluster":
    c = acct["clusters"][opt("--name")]
    out({"cluster": {"name": opt("--name"), "tags": c.get("tags", {}), "createdAt": "2026-10-02T00:00:00Z"}})
if key == "cloudtrail lookup-events":
    name = opt("--lookup-attributes").split("AttributeValue=")[1]
    who = acct.get("creators", {}).get(name)
    evs = [] if not who else [{"EventName": who[0], "EventTime": "2026-10-03T09:00:00Z", "Username": "u",
                               "CloudTrailEvent": json.dumps({"userIdentity": {"arn": who[1]}})}]
    out({"Events": evs})
if key == "configservice describe-configuration-recorders":
    out({"ConfigurationRecorders": acct.get("recorders", [])})
if key == "configservice describe-configuration-recorder-status":
    out({"ConfigurationRecordersStatus": [{"name": r["name"], "recording": True} for r in acct.get("recorders", [])]})
if key == "configservice get-resource-config-history":
    if opt("--resource-id") in acct.get("config_has", []):
        out({"configurationItems": [{"configurationItemCaptureTime": "2026-10-03T09:05:00Z"}]})
    sys.stderr.write("An error occurred (ResourceNotDiscoveredException)\n"); sys.exit(254)
sys.stderr.write("fake aws: unhandled " + key + "\n"); sys.exit(99)
'''

# plan writes the drift it found into the -out file and prints what terraform prints; show -json reads it back.
# A state whose path names "drifted" has a tag changed by hand; one naming "outputs-only" has only an output that
# differs (a variable the plan was given that the apply was not), which is not drift.
FAKE_TF = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("terraform " + json.dumps(a) + "\n")
if "init" in a:
    sys.exit(int(os.environ.get("FAKE_TF_INIT_RC", "0")))
if "show" in a:
    print(open(a[-1]).read()); sys.exit(0)
state = next(x for x in a if x.startswith("-state="))
out = next(x for x in a if x.startswith("-out="))[len("-out="):]
drift = []
if "drifted" in state:
    drift = [{"address": "module.eks.aws_eks_cluster.this", "change": {"actions": ["update"]}}]
    print("Note: Objects have changed outside of Terraform\n\nTerraform detected the following changes made outside of Terraform since the last \"terraform apply\":\n\n  # module.eks.aws_eks_cluster.this has changed\n  ~ resource \"aws_eks_cluster\" \"this\" {\n      ~ tags = { + \"hand\" = \"made\" }\n    }")
elif "outputs-only" in state:
    print("Changes to Outputs:\n  ~ kubeconfig_command = \"a\" -> \"b\"")
else:
    print("No changes. Your infrastructure still matches the configuration.")
json.dump({"format_version": "1.2", "resource_drift": drift}, open(out, "w"))
sys.exit(0)
'''

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("gh " + json.dumps(a) + "\n")
if a[:2] == ["issue", "list"]:
    print(os.environ.get("FAKE_GH_ISSUES", "[]")); sys.exit(0)
if a[:2] in (["issue", "comment"], ["issue", "create"]):
    open(os.environ["FAKE_GH_BODY"], "w").write(sys.stdin.read()); sys.exit(0)
sys.exit(99)
'''

EVENT = "kubecon-na-2026"


def cluster_state(name: str, acct_id: str, host: str, role: str = "attendee", hop: int = 1,
                  region: str = "us-west-2", tags: dict | None = None) -> dict:
    t = {"project": "watch-it-burn", "event": EVENT, "attendee": name, "hostname": host, "role": role}
    if tags is not None:
        t = tags
    return {"version": 4, "resources": [
        {"mode": "managed", "type": "aws_eks_cluster", "module": "module.eks",
         "instances": [{"attributes": {"name": name, "arn": f"arn:aws:eks:{region}:{acct_id}:cluster/{name}",
                                       "tags_all": t}}]},
        {"mode": "managed", "type": "aws_launch_template", "module": "module.eks.module.eks_managed_node_group",
         "instances": [{"attributes": {"metadata_options": [{"http_put_response_hop_limit": hop}],
                                       "tags_all": {"event": EVENT}}}]},
        {"mode": "managed", "type": "aws_iam_user", "instances": [{"attributes": {"name": "wib-x",
                                                                                 "tags_all": {"event": EVENT}}}]}]}


def vpc_state(vpc: str, event: str = EVENT) -> dict:
    return {"version": 4, "outputs": {"vpc_id": {"value": vpc}, "private_subnet_ids": {"value": [f"{vpc}-a", f"{vpc}-b"]}},
            "resources": [{"mode": "managed", "type": "aws_vpc", "module": "module.vpc",
                           "instances": [{"attributes": {"id": vpc, "tags_all": {"event": event}}}]},
                          {"mode": "managed", "type": "aws_route_table_association", "module": "module.vpc",
                           "instances": [{"attributes": {"id": "rtbassoc-1"}}]}]}


def tagged_state(rtype: str, attrs: dict, event: str = EVENT) -> dict:
    return {"version": 4, "resources": [{"mode": "managed", "type": rtype,
                                         "instances": [{"attributes": {**attrs, "tags_all": {"event": event}}}]}]}


STANDBY = "watch-it-burn-community-b02"
RECORDER = [{"name": "watch-it-burn", "recordingGroup": {"allSupported": False,
             "resourceTypes": ["AWS::S3::Bucket", "AWS::EKS::Cluster", "AWS::IAM::User"]}}]
AUDIT_BUCKET = "watch-it-burn-audit-111111111111-us-west-2"

FIXTURE = {
    "accen-dev": {
        "id": "111111111111",
        "buckets": {
            AUDIT_BUCKET: {},
            "watch-it-burn-exfil-hoop": {"tags": {"project": "watch-it-burn"}},
            "packt-lab-assets": {"tags": {"Workshop": "packt"}},
            "hand-made-by-hand": {"region": "us-west-2"},
        },
        "clusters": {"watch-it-burn-attendee-001": {}, "packt-eks-01": {"tags": {"Workshop": "packt"}},
                     "lab-kubecon-007": {"tags": {"lab-platform:managed": "true", "lab-platform:cluster": "c7"}}},
        "creators": {"hand-made-by-hand": ["CreateBucket", "arn:aws:iam::111111111111:user/someone-by-hand"]},
        "recorders": RECORDER,
        "config_has": ["hand-made-by-hand"],
    },
    "aws1-student31": {
        "id": "222222222222",
        "buckets": {"student31-handmade": {"region": "us-east-1"}},
        "clusters": {"watch-it-burn-attendee-002-drifted": {}, "watch-it-burn-attendee-099": {},
                     STANDBY: {"region": "us-east-1"}, "watch-it-burn-community-b04": {"region": "us-east-2"}},
        "creators": {"watch-it-burn-community-b04": ["CreateCluster", "arn:aws:iam::222222222222:user/operator"]},
        "recorders": [],
    },
}
C002 = "fleet/states/watch-it-burn-attendee-002-drifted"


class Env:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.tf = root / "infra/terraform"
        self.org = root / "infra/org"
        self.bin = root / "bin"
        self.log = root / "calls.log"
        self.fixture = root / "aws.json"
        self.body = root / "gh-body.md"
        self.bin.mkdir()
        # Only these tools are on PATH: whatever a real machine has in /usr/bin cannot leak into a test.
        (self.bin / "python3").symlink_to(sys.executable)
        for name, src in (("aws", FAKE_AWS), ("terraform", FAKE_TF), ("gh", FAKE_GH)):
            (self.bin / name).write_text(src)
            (self.bin / name).chmod(0o755)
        for d in ("aws/network/states", "aws/cluster", "aws/audit/states", "fleet/states", "drift"):
            (self.tf / d).mkdir(parents=True)
        (self.org / "boundary/states").mkdir(parents=True)
        shutil.copy(REGISTER, self.tf / "drift/known-unmanaged.yaml")
        shutil.copy(FLEET, self.tf / "fleet/fleet.sh")
        shutil.copy(BACKUPS, self.tf / "fleet/backups.tsv")
        self.write("aws/network/terraform.tfstate", vpc_state("vpc-accen", event="devopsdays-portland-2026"))
        self.write("aws/network/states/aws1-student31.tfstate", vpc_state("vpc-s31"))
        # Outside the home region every account keeps one lab VPC state per region (fleet.sh lab_vpc_state_for).
        self.write("aws/network/states/aws1-student31.us-east-1.tfstate", vpc_state("vpc-s31-use1"))
        self.write(f"fleet/states/{STANDBY}.tfstate", cluster_state(
            STANDBY, "222222222222", "burn.agenticburn.com", role="community", region="us-east-1"))
        self.write("aws/audit/states/accen-dev.tfstate", tagged_state("aws_s3_bucket", {"bucket": AUDIT_BUCKET}))
        (self.org / "boundary/states/accen-dev.tfstate").write_text(json.dumps(
            tagged_state("aws_iam_policy", {"name": "watch-it-burn-permissions-boundary"})))
        self.write("fleet/states/watch-it-burn-attendee-001.tfstate",
                   cluster_state("watch-it-burn-attendee-001", "111111111111", "bane-sabrina.agenticburn.com"))
        (self.tf / "fleet/states/watch-it-burn-attendee-001.account").write_text("accen-dev\n")
        # The community cluster is built with hop limit 2 (#113); its plan has to say so.
        self.write(f"{C002}.tfstate", cluster_state("watch-it-burn-attendee-002-drifted", "222222222222",
                                                     "burn.agenticburn.com", role="community", hop=2))
        self.fx = json.loads(json.dumps(FIXTURE))

    def write(self, rel: str, obj: dict) -> None:
        (self.tf / rel).write_text(json.dumps(obj))

    def run(self, *args: str, accounts: str | None = "accen-dev,aws1-student31", path: str | None = None, **env: str):
        self.fixture.write_text(json.dumps(self.fx))
        self.log.write_text("")
        e = {"PATH": path or str(self.bin), "FAKE_LOG": str(self.log), "FAKE_AWS": str(self.fixture),
             "FAKE_GH_BODY": str(self.body), "HOME": str(self.root), **env}
        acc = ["--accounts", accounts] if accounts else []
        p = subprocess.run([sys.executable, str(REPORT), "--tf-dir", str(self.tf), *acc, *args],
                           capture_output=True, text=True, env=e)
        return p.returncode, p.stdout + p.stderr

    def calls(self, tool: str) -> list[list[str]]:
        return [json.loads(ln.split(" ", 1)[1]) for ln in self.log.read_text().splitlines() if ln.startswith(tool + " ")]


def section(out: str, title: str) -> str:
    start = out.find(title)
    if start < 0:
        return ""
    nxt = out.find("\n## ", start + len(title))
    return out[start: nxt if nxt > 0 else len(out)]


with tempfile.TemporaryDirectory(prefix="drift-test-") as tmp:
    env = Env(pathlib.Path(tmp))

    print("== the full fleet: drift, unmanaged resources and a missing Config record are all findings ==")
    rc, out = env.run()
    check(f"returns code 2, findings (got {rc})", rc == 2)
    check("does not call itself incomplete", "INCOMPLETE" not in out)
    unmanaged = section(out, "## Unmanaged")
    check("the hand-made bucket is reported unmanaged", "`hand-made-by-hand`" in unmanaged)
    check("with who made it, from CloudTrail", "arn:aws:iam::111111111111:user/someone-by-hand" in unmanaged)
    check("and the time AWS Config recorded it", "recorded 2026-10-03T09:05:00Z" in unmanaged)
    check("a bucket made in another region says the recorder cannot have seen it",
          "`student31-handmade`" in unmanaged and "in us-east-1; the recorder is in us-west-2" in unmanaged)
    check("a bucket with no create event in history says so rather than guessing",
          "no CreateBucket event in us-east-1's 90-day event history" in unmanaged)
    check("a watch-it-burn cluster with no state is reported (an orphan still billing)",
          "`watch-it-burn-attendee-099`" in unmanaged)
    check("a bucket in a state is not reported", AUDIT_BUCKET not in unmanaged)
    check("a cluster in a state is not reported",
          "attendee-001" not in unmanaged and "attendee-002-drifted" not in unmanaged and STANDBY not in unmanaged)
    check("a cluster left in a standby region with no state is found, with its region's creator, outside Config",
          "`watch-it-burn-community-b04`" in unmanaged and "arn:aws:iam::222222222222:user/operator" in unmanaged
          and "in us-east-2; the recorder is in us-west-2" in unmanaged)
    check("the header names the home region and the standby regions swept",
          "Region: us-west-2 (Config; clusters also swept in us-east-1, us-east-2)." in out)
    known = section(out, "## Known unmanaged")
    check("the register's named bucket is known, not a finding",
          "watch-it-burn-exfil-hoop" in known and "watch-it-burn-exfil-hoop" not in unmanaged)
    check("the co-tenant's bucket and cluster match the register by tag",
          "packt-lab-assets" in known and "packt-eks-01" in known and "packt" not in unmanaged)
    check("a lab-platform cluster matches the register by its lab-platform:managed tag",
          "lab-kubecon-007" in known and "lab-kubecon-007" not in unmanaged)
    drift = section(out, "## Terraform drift")
    check("the drifted cluster is named with the resource that drifted, and its plan excerpt",
          "cluster watch-it-burn-attendee-002-drifted (aws1-student31)" in drift
          and "`module.eks.aws_eks_cluster.this (update)`" in drift and "has changed" in drift)
    clean = section(out, "## Clean states")
    check("the clean states are listed as clean, the boundary and audit roots among them",
          all(s in clean for s in ("cluster watch-it-burn-attendee-001", "lab VPC accen-dev", "lab VPC aws1-student31",
                                   "lab VPC us-east-1 aws1-student31", f"cluster {STANDBY}",
                                   "boundary accen-dev", "audit accen-dev")))
    config = section(out, "## AWS Config")
    check("an account with no recorder is a finding that names the fix",
          "aws1-student31: NO recorder in us-west-2: apply infra/terraform/aws/audit" in config)
    check("an account recording S3 and EKS is ok", "accen-dev: ok: recorder watch-it-burn is recording" in config)
    check("the count adds up: 1 drifted state, 4 unmanaged, 1 account without Config",
          "**6 finding(s)**: 1 drifted state(s), 4 unmanaged resource(s), 1 account(s)" in out)
    notes = section(out, "## Notes")
    check("an account root not applied from here is a note, not a silent gap",
          "aws1-student31: audit root not applied from here" in notes
          and "aws1-student31: boundary root not applied from here" in notes)

    print("== it only ever plans, and every call names its account and region ==")
    tf = env.calls("terraform")
    plans = [c for c in tf if "plan" in c]
    verbs = {c[1] for c in tf}
    check(f"terraform verbs are init, plan and show only (got {sorted(verbs)})", verbs <= {"init", "plan", "show"})
    check("every init leaves the committed lock alone (-lockfile=readonly)",
          all("-lockfile=readonly" in c for c in tf if "init" in c))
    check("every plan is -refresh-only -lock=false and saved for show -json",
          plans and all({"-refresh-only", "-lock=false"} <= set(c) and any(x.startswith("-out=") for x in c)
                        for c in plans))
    check("each saved plan is read back with show -json", len([c for c in tf if "show" in c]) == len(plans))
    check("one plan per state: 3 lab VPCs, 1 boundary, 1 audit root, 3 clusters", len(plans) == 8)
    check("the boundary state is planned in infra/org/boundary",
          any(c[0] == f"-chdir={env.org / 'boundary'}" for c in plans))
    p1 = next((c for c in plans if any("attendee-001.tfstate" in x for x in c)), [])
    p2 = next((c for c in plans if any("attendee-002-drifted" in x for x in c)), [])
    check("a cluster is planned through the account its state is in (from the ARN), not a default",
          "profile=aws1-student31" in p2 and "region=us-west-2" in p2)
    check("with that account's lab VPC, read from its lab VPC state",
          "vpc_id=vpc-s31" in p2 and 'private_subnet_ids=["vpc-s31-a", "vpc-s31-b"]' in p2)
    check("and the event, hostname and role it was built with, read from its own tags",
          {f"event={EVENT}", "hostname=burn.agenticburn.com", "role=community"} <= set(p2)
          and "hostname=bane-sabrina.agenticburn.com" in p1 and "role=attendee" in p1)
    ps = next((c for c in plans if any(f"{STANDBY}.tfstate" in x for x in c)), [])
    check("a standby is planned in its own region, against that region's lab VPC, not the home region's (#643)",
          "region=us-east-1" in ps and "vpc_id=vpc-s31-use1" in ps
          and 'private_subnet_ids=["vpc-s31-use1-a", "vpc-s31-use1-b"]' in ps)
    pr = next((c for c in plans if any(x.endswith("aws1-student31.us-east-1.tfstate") for x in c)), [])
    check("and a regional lab VPC state is planned in its region", "region=us-east-1" in pr and "profile=aws1-student31" in pr)
    check("clusters are listed in every standby region, each call naming it",
          {r for c in env.calls("aws") if c[:2] == ["eks", "list-clusters"] for r in [c[c.index("--region") + 1]]}
          == {"us-west-2", "us-east-1", "us-east-2"})
    check("and its IMDS hop limit, read from its launch template (#113)",
          "imds_hop_limit=2" in p2 and "imds_hop_limit=1" in p1)
    pv = next((c for c in plans if any(x.endswith("aws/network/terraform.tfstate") for x in c)), [])
    check("the default account's lab VPC is planned from the network root's default state, with its own event",
          "profile=accen-dev" in pv and "event=devopsdays-portland-2026" in pv)
    awscalls = env.calls("aws")
    check(f"every aws call carries --profile and --region ({len(awscalls)} calls)",
          awscalls and all("--profile" in c and "--region" in c for c in awscalls))
    check("tags are only fetched for resources not already in a state",
          not any(c[:2] == ["s3api", "get-bucket-tagging"] and AUDIT_BUCKET in c for c in awscalls))

    print("== drift is what the refresh found, not what the plan would change ==")
    (env.tf / f"{C002}.tfstate").rename(env.root / "parked-002.tfstate")
    (env.tf / f"fleet/states/{STANDBY}.tfstate").rename(env.root / "parked-standby.tfstate")
    env.write("fleet/states/watch-it-burn-attendee-003-outputs-only.tfstate",
              cluster_state("watch-it-burn-attendee-003-outputs-only", "111111111111", "x.agenticburn.com"))
    env.fx["accen-dev"]["clusters"]["watch-it-burn-attendee-003-outputs-only"] = {}
    rc, out = env.run(accounts="accen-dev")
    check(f"a plan whose only change is an output, with no resource_drift, is clean (got {rc})",
          "cluster watch-it-burn-attendee-003-outputs-only" in section(out, "## Clean states")
          and "No state has drifted." in out)
    (env.tf / "fleet/states/watch-it-burn-attendee-003-outputs-only.tfstate").unlink()
    del env.fx["accen-dev"]["clusters"]["watch-it-burn-attendee-003-outputs-only"]

    print("== a clean account exits 0 ==")
    env.fx["accen-dev"]["buckets"] = {AUDIT_BUCKET: {}}
    env.fx["accen-dev"]["clusters"] = {"watch-it-burn-attendee-001": {}}
    rc, out = env.run(accounts="accen-dev")
    check(f"exits 0 (got {rc})", rc == 0)
    check("and says so", "**0 finding(s)**" in out and "No state has drifted." in out)

    print("== the report refuses to pass when it could not look ==")
    env.fx["accen-dev"]["broken"] = True
    rc, out = env.run(accounts="accen-dev")
    check(f"an account whose credentials fail is exit 1, not 0 (got {rc})", rc == 1)
    check("and the report says it is incomplete and why", "INCOMPLETE" in out and "ExpiredToken" in out)
    env.fx["accen-dev"]["broken"] = False

    rc, out = env.run(accounts=None)
    check(f"with no --accounts it covers fleet.sh's accounts, and one it cannot reach is exit 1 (got {rc})",
          rc == 1 and "Accounts: accen-dev, aws1-student31, aws1-student32, aws1-student33, aws1-student34." in out
          and "sts get-caller-identity (aws1-student32, us-west-2): An error occurred (ExpiredToken)" in out)

    (env.root / "parked-002.tfstate").rename(env.tf / f"{C002}.tfstate")
    rc, out = env.run(accounts="accen-dev")
    check(f"a cluster state in an account none of the profiles reach is exit 1 (got {rc})",
          rc == 1 and "account 222222222222, which none of the profiles" in out)

    (env.tf / f"{C002}.account").write_text("accen-dev\n")
    rc, out = env.run()
    check(f"a .account file that disagrees with the state is exit 1 (got {rc})",
          rc == 1 and "attendee-002-drifted.account says accen-dev but its state is in aws1-student31" in out)
    (env.tf / f"{C002}.account").unlink()

    env.write("fleet/states/watch-it-burn-attendee-004.tfstate", cluster_state(
        "watch-it-burn-attendee-004", "111111111111", "", tags={"project": "watch-it-burn", "event": EVENT}))
    rc, out = env.run()
    check(f"a cluster whose tags do not say its hostname is exit 1, not a guessed -var (got {rc})",
          rc == 1 and "cluster watch-it-burn-attendee-004: its state's resources carry no `hostname` tag" in out)
    (env.tf / "fleet/states/watch-it-burn-attendee-004.tfstate").unlink()

    rc, out = env.run(FAKE_TF_INIT_RC="1")
    check(f"a failed terraform init is exit 1 with no plans run (got {rc})",
          rc == 1 and not [c for c in env.calls("terraform") if "plan" in c])

    nobin = env.root / "nobin"
    nobin.mkdir()
    (nobin / "python3").symlink_to(sys.executable)
    (nobin / "aws").symlink_to(env.bin / "aws")
    rc, out = env.run(path=str(nobin))
    check(f"terraform missing from PATH is exit 1 (got {rc})", rc == 1 and "terraform is not on PATH" in out)

    bad = env.root / "bad-register.yaml"
    bad.write_text("entries:\n  - kind: s3-bucket\n    accounts: ['*']\n    made_by: nobody\n")
    rc, out = env.run("--register", str(bad))
    check(f"a register entry with neither name nor tag is exit 1 (got {rc})",
          rc == 1 and "exactly one of name or tag" in out)

    print("== --post keeps one running issue ==")
    env.fx = json.loads(json.dumps(FIXTURE))
    rc, out = env.run("--post")
    gh = env.calls("gh")
    check("with findings and no open issue, it opens one",
          rc == 2 and any(c[:2] == ["issue", "create"] and "Fleet drift report" in c for c in gh))
    check("whose body is the report", "`hand-made-by-hand`" in env.body.read_text())
    rc, out = env.run("--post", FAKE_GH_ISSUES=json.dumps([{"number": 7, "title": "Fleet drift report"}]))
    check("with an open issue, it comments on that one",
          any(c[:3] == ["issue", "comment", "7"] for c in env.calls("gh")))
    env.body.unlink()
    (env.tf / f"{C002}.tfstate").unlink()
    env.fx["accen-dev"]["buckets"] = {AUDIT_BUCKET: {}}
    env.fx["accen-dev"]["clusters"] = {"watch-it-burn-attendee-001": {}}
    rc, out = env.run("--post", accounts="accen-dev")
    check("a clean run with no open issue posts nothing",
          rc == 0 and not any(c[1] in ("create", "comment") for c in env.calls("gh")) and not env.body.exists())

    print("== the cron wrapper ==")
    logs = env.root / "logs"
    e = {"PATH": f"{env.bin}:/usr/bin:/bin", "FAKE_LOG": str(env.log), "FAKE_AWS": str(env.fixture),
         "FAKE_GH_BODY": str(env.body), "HOME": str(env.root), "WIB_DRIFT_LOG_DIR": str(logs)}
    p = subprocess.run(["bash", str(SCHED), "--tf-dir", str(env.tf), "--accounts", "accen-dev"],
                       capture_output=True, text=True, env=e)
    check(f"passes a clean report's exit code through (got {p.returncode})", p.returncode == 0)
    check("keeps a dated copy", len(list(logs.glob("drift-*.md"))) == 1)
    check("and posts (the wrapper always runs with --post)", any(c[:2] == ["issue", "list"] for c in env.calls("gh")))
    # A missing report, not a missing tool: the wrapper appends linuxbrew to PATH on purpose, so on the machine
    # it is written for a real terraform or gh would be found and the case could not be staged.
    env.log.write_text("")
    p = subprocess.run(["bash", str(SCHED), "--tf-dir", str(env.tf)], capture_output=True, text=True,
                       env={**e, "WIB_DRIFT_BIN": str(env.root / "no-such-report.py")})
    check(f"refuses to run without its report, exit 1, and runs nothing (got {p.returncode})",
          p.returncode == 1 and "DRIFT REPORT NOT RUN: missing the report at" in p.stdout
          and not env.calls("aws") and not env.calls("terraform"))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All drift-report checks passed.")
