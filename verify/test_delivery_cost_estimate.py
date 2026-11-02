# ABOUTME: Offline tests for teardown/delivery-cost-estimate.py (#392): an aws shim answers from verify/fixtures/delivery-cost,
# ABOUTME: and the estimate's line items, upper bounds, tag attribution and refusals are checked against hand-computed figures.
#
# The pricing fixtures are recorded: products copied from the public Price List bulk files for us-west-2 (version and
# publicationDate are in each item), in the item shape `pricing get-products` returns, distractors included, and the
# shim applies the TERM_MATCH filters itself, so a filter that would pick the wrong product here would pick it live.
# The account fixtures (CloudTrail, describe, CloudWatch, Cost Explorer) are synthetic, written in the documented
# response shapes for a Portland-like week; a live run on member accounts is the owed check (decisions.md, #392).
import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "teardown/delivery-cost-estimate.py"
FIX = REPO / "verify/fixtures/delivery-cost"
failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


SHIM = r'''#!/usr/bin/env python3
import json, os, pathlib, re, sys
fix = pathlib.Path(os.environ["FIXTURES"])
argv = sys.argv[1:]
profile = os.environ.get("AWS_PROFILE", "")
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"profile": profile, "argv": argv}) + "\n")
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None
def opts(name):
    i = argv.index(name) + 1
    out = []
    while i < len(argv) and not argv[i].startswith("--"):
        out.append(argv[i]); i += 1
    return out
if not profile or opt("--region") is None or opt("--output") != "json":
    sys.exit("shim: every call needs AWS_PROFILE, --region and --output json: " + " ".join(argv))
svc, op = argv[0], argv[1]
def san(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s)
def emit(path, default=None):
    if path.is_file():
        print(path.read_text()); sys.exit(0)
    if default is not None:
        print(json.dumps(default)); sys.exit(0)
    sys.stderr.write(f"An error occurred (AccessDenied): shim has no fixture {path}\n"); sys.exit(254)
if (svc, op) == ("pricing", "get-products"):
    if opt("--region") != "us-east-1":
        sys.exit("shim: the pricing endpoint is us-east-1")
    want = dict(re.fullmatch(r"Type=TERM_MATCH,Field=([^,]+),Value=(.+)", f).groups() for f in opts("--filters"))
    items = json.loads((fix / "common/pricing" / (opt("--service-code") + ".json")).read_text())
    def match(i):
        a = dict(i["product"]["attributes"], productFamily=i["product"].get("productFamily") or "")
        return all(a.get(k, "").lower() == v.lower() for k, v in want.items())
    print(json.dumps({"FormatVersion": "aws_v1", "PriceList": [json.dumps(i) for i in items if match(i)]})); sys.exit(0)
base = fix / profile
if (svc, op) == ("cloudtrail", "lookup-events"):
    name = re.fullmatch(r"AttributeKey=EventName,AttributeValue=(\w+)", opt("--lookup-attributes")).group(1)
    emit(base / "cloudtrail" / f"{name}.json", {"Events": []})
if (svc, op) == ("cloudwatch", "get-metric-statistics"):
    dim = re.fullmatch(r"Name=\w+,Value=(.+)", opt("--dimensions")).group(1)
    emit(base / "cloudwatch" / f"{san(opt('--namespace'))}_{opt('--metric-name')}_{san(dim)}.json", {"Label": "", "Datapoints": []})
extra = {("eks", "describe-cluster"): opt("--name"), ("cloudwatch", "list-metrics"): opt("--metric-name")}.get((svc, op))
if (svc, op) == ("ce", "get-cost-and-usage") and opt("--region") != "us-east-1":
    sys.exit("shim: Cost Explorer is us-east-1")
emit(base / (f"{svc}_{op}" + (f"_{extra}" if extra else "") + ".json"))
'''


def run(*args, fixtures=FIX):
    with tempfile.TemporaryDirectory() as t:
        shim = pathlib.Path(t) / "aws"
        shim.write_text(SHIM)
        shim.chmod(0o755)
        calls = pathlib.Path(t) / "calls"
        calls.touch()
        env = dict(os.environ, PATH=f"{t}:{os.environ['PATH']}", FIXTURES=str(fixtures), CALLS=str(calls))
        env.pop("AWS_PROFILE", None)
        p = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True)
        import json
        return p, [json.loads(line) for line in calls.read_text().splitlines()]


PORTLAND = ["--start", "2026-09-06", "--end", "2026-09-12", "--region", "us-west-2", "--event", "devopsdays-portland-2026",
            "--profile", "accen-dev", "--profile", "aws1-student31", "--as-of", "2026-11-01T12:00:00Z"]


def line(out, profile, item):
    """USD of one line item, or None."""
    for ln in out.splitlines():
        if ln.strip().startswith(profile) and item in ln:
            return float(ln.split()[-1].replace(",", ""))
    return None


def qty(out, profile, item):
    for ln in out.splitlines():
        if ln.strip().startswith(profile) and item in ln:
            m = re.search(r"\s([\d,]+\.\d+)\s+\S+\s+\S+\s+[\d,]+\.\d+$", ln)
            return float(m.group(1).replace(",", "")) if m else None
    return None


def near(a, b):
    return a is not None and abs(a - b) < 0.006


print("== Portland window, two accounts ==")
p, calls = run(*PORTLAND)
out = p.stdout
check("exits 0", p.returncode == 0, p.stderr)
check("labeled an estimate, not a bill", "ESTIMATE, NOT A BILL" in out)
check("names the window and the filter", "2026-09-06 (incl) .. 2026-09-12 (excl)" in out
      and "project=watch-it-burn, event=devopsdays-portland-2026" in out)
# Rates from the recorded price list: t3.2xlarge 0.3328/h, EKS 0.10/h, gp3 0.08/GB-Mo, NLB 0.0225/h, NAT 0.045/h and
# 0.045/GB, Haiku 4.5 regional 1.10 and 5.50 per 1M tokens, Nova Pro 0.0008 and 0.0032 per 1K.
check("accen-dev EKS: attendee-001's Portland lifetime only, 36 h", near(line(out, "accen-dev", "EKS cluster"), 3.60), out)
check("the KubeCon-tagged rebuild of the same name is not Portland's", near(qty(out, "accen-dev", "EKS cluster"), 36.0))
check("accen-dev EC2 t3.2xlarge 35.5 h", near(line(out, "accen-dev", "EC2 t3.2xlarge"), 35.5 * 0.3328), out)
check("Packt's m5.large is not counted", "m5.large" not in out)
check("the KubeCon node on the reused attendee-001 name is not counted, by its event tag", near(qty(out, "accen-dev", "EC2 t3.2xlarge"), 35.5))
check("accen-dev EBS gp3: root disk 35.5 h x 100 GiB plus the CSI volume 34 h x 10 GiB",
      near(line(out, "accen-dev", "EBS gp3"), (3550 + 340) * 0.08 / 730), out)
check("the CSI volume counts through its kubernetes.io/cluster tag", near(qty(out, "accen-dev", "EBS gp3"), 3890.0))
check("accen-dev NLB 34.5 h, through elbv2.k8s.aws/cluster", near(line(out, "accen-dev", "NLB"), 34.5 * 0.0225), out)
check("Packt's ALBs are not counted", line(out, "accen-dev", "ALB ") is None, out)
check("the lab NAT, made before the lookback, runs the whole window from describe", near(line(out, "accen-dev", "NAT gateway  "), 144 * 0.045)
      or near(line(out, "accen-dev", "NAT gateway "), 144 * 0.045), out)
check("NAT data processed from both byte counters, 10 GB", near(line(out, "accen-dev", "NAT gateway data processed"), 10 * 0.045), out)
check("aws1-student31 EKS: no delete in the window, runs to its end, 105 h", near(line(out, "aws1-student31", "EKS cluster"), 10.50), out)
check("aws1-student31 two instances from one RunInstances, 161.5 h", near(line(out, "aws1-student31", "EC2 t3.2xlarge"), 161.5 * 0.3328), out)
check("tagged Haiku profile input, priced at the regional rate", near(line(out, "aws1-student31", "Claude Haiku 4.5 input"), 1.10), out)
check("tagged Haiku profile output", near(line(out, "aws1-student31", "Claude Haiku 4.5 output"), 1.10), out)
total = (3.60 + 35.5 * 0.3328 + 3890 * 0.08 / 730 + 34.5 * 0.0225 + 144 * 0.045 + 10 * 0.045
         + 10.50 + 161.5 * 0.3328 + 16150 * 0.08 / 730 + 2.20)
m = re.search(r"ESTIMATED TOTAL, tagged resources:\s+([\d,]+\.\d\d) USD", out)
check(f"estimated total {total:.2f}", m is not None and near(float(m.group(1).replace(",", "")), round(total, 2)), out)
check("untagged Nova Pro on accen-dev is reported beside it, not in it (2M in + 0.5M out = 3.20)",
      "plus untagged Bedrock on the same accounts:" in out and re.search(r"untagged Bedrock on the same accounts:\s+3\.20 USD", out) is not None, out)
check("a model with no price is named, not dropped silently", "us.meta.llama3-3-70b-instruct-v1:0, a model this script has no price for" in out)
check("upper bound per account, unfiltered", re.search(r"accen-dev\s+111111111111\s+550\.88 USD", out) is not None
      and re.search(r"aws1-student31\s+222222222222\s+300\.00 USD", out) is not None, out)
check("upper bound summed", re.search(r"all accounts\s+850\.88 USD", out) is not None)
check("a delete with no create in the lookback is named", "i-0beforelookback1" in out and "before the CloudTrail lookback" in out)
check("what is left out is listed", "Not in the estimate:" in out and "LCUs" in out and "public IPv4" in out)
check("says when CloudTrail history for the window ends", "event history for this window ends 2026-12-05T00:00:00Z" in out)

print("== every call is explicit ==")
check("every call carries one of the given profiles", all(c["profile"] in ("accen-dev", "aws1-student31") for c in calls))
check("every call names its region", all("--region" in c["argv"] for c in calls))
check("pricing goes to us-east-1 with the first profile",
      all(c["argv"][c["argv"].index("--region") + 1] == "us-east-1" and c["profile"] == "accen-dev"
          for c in calls if c["argv"][:2] == ["pricing", "get-products"]))
check("CloudTrail is read from 30 days before the window",
      any(c["argv"][:2] == ["cloudtrail", "lookup-events"] and "2026-08-07T00:00:00Z" in c["argv"] for c in calls))
check("each price is asked once per run", len([c for c in calls if c["argv"][:2] == ["pricing", "get-products"]])
      == len({tuple(c["argv"]) for c in calls if c["argv"][:2] == ["pricing", "get-products"]}))
check("no call writes anything", not any(re.match(r"(create|delete|update|put|start|terminate|run)-", c["argv"][1]) for c in calls))

print("== without --event, the KubeCon rebuild on 2026-09-10 counts too ==")
p2, _ = run(*[a for a in PORTLAND if a not in ("--event", "devopsdays-portland-2026")])
check("exits 0", p2.returncode == 0, p2.stderr)
check("EKS hours 36 + 48", near(qty(p2.stdout, "accen-dev", "EKS cluster"), 84.0), p2.stdout)
check("the rebuild's node (47 h 40 min) and its CSI volume (47 h x 10 GiB), which only its cluster tag ties to the fleet",
      abs(qty(p2.stdout, "accen-dev", "EBS gp3") - ((35.5 + 47 + 40 / 60) * 100 + 340 + 470)) < 0.01, p2.stdout)

print("== a cluster week whose nodes were not attributed says the total is too low ==")
with tempfile.TemporaryDirectory() as t:
    import json
    import shutil
    fx = pathlib.Path(t) / "fx"
    shutil.copytree(FIX, fx)
    ri = fx / "aws1-student31/cloudtrail/RunInstances.json"
    doc = json.loads(ri.read_text())
    for e in doc["Events"]:
        ct = json.loads(e["CloudTrailEvent"])
        for it in ct["responseElements"]["instancesSet"]["items"]:
            it.pop("tagSet", None)
        e["CloudTrailEvent"] = json.dumps(ct)
    ri.write_text(json.dumps(doc))
    p7, _ = run(*PORTLAND, fixtures=fx)
check("exits 0", p7.returncode == 0, p7.stderr)
check("the untagged nodes are not counted", line(p7.stdout, "aws1-student31", "EC2 t3.2xlarge") is None, p7.stdout)
check("the report says the total is too low, naming the account and its cluster hours",
      re.search(r"INCOMPLETE, the total is too low: aws1-student31: fleet EKS clusters ran 105\.0 h", p7.stdout) is not None, p7.stdout)
check("an account whose nodes were attributed is not flagged", "INCOMPLETE" not in out and "accen-dev: fleet EKS" not in p7.stdout)

print("== refusals ==")
p3, c3 = run("--start", "2026-06-29", "--end", "2026-07-03", "--region", "us-west-2", "--profile", "accen-dev",
             "--as-of", "2026-11-01T00:00:00Z")
check("a window wholly past CloudTrail's 90 days fails", p3.returncode == 3 and "90-day event history" in p3.stderr, p3.stderr)
p4, _ = run("--start", "2026-09-06", "--end", "2026-09-12", "--profile", "accen-dev")
check("no --region is a usage error", p4.returncode == 2 and "--region" in p4.stderr, p4.stderr)
p5, _ = run("--start", "2026-09-06", "--end", "2026-09-12", "--region", "us-west-2")
check("no --profile is a usage error", p5.returncode == 2 and "--profile" in p5.stderr, p5.stderr)
p6, _ = run(*[a if a != "aws1-student31" else "aws1-student99" for a in PORTLAND])
check("an account whose calls fail ends the run, no partial estimate",
      p6.returncode == 3 and "ESTIMATED TOTAL" not in p6.stdout and "aws1-student99" in p6.stderr, p6.stderr)

print("== the script keeps up with the fleet ==")
sys.path.insert(0, str(REPO / "teardown"))
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("estimate", SCRIPT)
est = importlib.util.module_from_spec(spec)
spec.loader.exec_module(est)
main_tf = (REPO / "infra/terraform/aws/cluster/main.tf").read_text()
tiers = re.search(r"bedrock_tiers = \{(.*?)\}", main_tf, re.S).group(1)
models = set(re.findall(r'"([^"]+)"', tiers))
models.add(re.search(r'variable "tutor_model".*?default\s*=\s*"([^"]+)"', main_tf, re.S).group(1))
for mid in sorted(models):
    check(f"Bedrock model {mid} has a price-list entry", est.base_model(mid) in est.BEDROCK_MODELS)
disk = re.search(r'variable "node_disk_size".*?default\s*=\s*(\d+)', main_tf, re.S).group(1)
check(f"--root-volume-gib defaults to node_disk_size ({disk})", f"default={disk}," in SCRIPT.read_text().replace(" ", ""))
itype = re.search(r'variable "instance_types".*?default\s*=\s*\["([^"]+)"\]', main_tf, re.S).group(1)
check(f"the fleet's instance type {itype} has a recorded price", f"BoxUsage:{itype}" in (FIX / "common/pricing/AmazonEC2.json").read_text())

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all delivery-cost-estimate checks passed")
