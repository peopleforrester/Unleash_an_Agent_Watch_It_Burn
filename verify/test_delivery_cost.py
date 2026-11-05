# ABOUTME: Offline tests for teardown/delivery-cost.py (#392): an aws shim answers Cost Explorer from data this test owns,
# ABOUTME: and the per-account usage, the left-out tax, cluster hours, edge-day guard, paging and refusals are checked.
#
# The responses are synthetic, in the shape `aws ce get-cost-and-usage` returns (ResultsByTime, Groups, Keys, Metrics,
# NextPageToken), written to match what accen-dev returned for the Portland window on 2026-11-05: Usage and Tax
# record types per service and day, the Tax posted on the 1st, AmazonEKS-Hours:perCluster under the EKS service, and
# a tag-filtered total of 0. The live run is recorded in cost/measured/ (decisions.md, #392).
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "teardown/delivery-cost.py"
failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


EKS = "Amazon Elastic Container Service for Kubernetes"

# Usage per account, service and day, and the other record types. Days run 2026-08-30 .. 2026-09-03, with the
# window 2026-08-31 .. 2026-09-03 (end exclusive), so 08-30 is the day before and 09-03 the first day after.
DATA = {
    "acct-a": {
        "account": "111111111111",
        "usage": {
            "2026-08-30": {"Amazon Elastic Compute Cloud - Compute": 0.05},
            "2026-08-31": {"Amazon Elastic Compute Cloud - Compute": 100.0, EKS: 20.0},
            "2026-09-01": {"Amazon Elastic Compute Cloud - Compute": 150.0, EKS: 30.0, "Amazon Bedrock": 5.25},
            "2026-09-02": {"Amazon Elastic Compute Cloud - Compute": 50.0, EKS: 10.0},
            "2026-09-03": {"Amazon Elastic Compute Cloud - Compute": 0.5},
        },
        "other": {"2026-09-01": {"Tax": 40.0}, "2026-08-30": {"Tax": 9.0}, "2026-09-03": {"Credit": -3.0}},
        "eks_usage_types": {"USW2-AmazonEKS-Hours:perCluster": 600.0, "USW2-AmazonEKS-Hours:extendedSupport": 7.0,
                            "USW2-DataTransfer-Out-Bytes": 12.0},
        "tagged": 0.0,
    },
    "acct-b": {
        "account": "222222222222",
        "usage": {
            "2026-08-30": {"Amazon Elastic Compute Cloud - Compute": 30.0},
            "2026-08-31": {"Amazon Elastic Compute Cloud - Compute": 80.0},
            "2026-09-01": {"Amazon Elastic Compute Cloud - Compute": 80.0, EKS: 10.0},
            "2026-09-02": {"Amazon Elastic Compute Cloud - Compute": 40.0},
            "2026-09-03": {"Amazon Elastic Compute Cloud - Compute": 0.02},
        },
        "other": {},
        "eks_usage_types": {"AmazonEKS-Hours:perCluster": 100.0},
        "tagged": 12.5,
    },
}
WINDOW = ["--start", "2026-08-31", "--end", "2026-09-03", "--event", "devopsdays-portland-2026", "--today", "2026-11-05"]

SHIM = r'''#!/usr/bin/env python3
import datetime as dt, json, os, sys
argv = sys.argv[1:]
profile = os.environ.get("AWS_PROFILE", "")
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps({"profile": profile, "argv": argv}) + "\n")
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None
def opts(name):
    i = argv.index(name) + 1; out = []
    while i < len(argv) and not argv[i].startswith("--"):
        out.append(argv[i]); i += 1
    return out
if not profile or opt("--region") != "us-east-1" or opt("--output") != "json":
    sys.exit("shim: every call needs AWS_PROFILE, --region us-east-1 and --output json: " + " ".join(argv))
data = json.loads(os.environ["SHIM_DATA"])
if profile not in data:
    sys.stderr.write(f"An error occurred (AccessDeniedException): no access for {profile}\n"); sys.exit(254)
d = data[profile]
if argv[:2] == ["sts", "get-caller-identity"]:
    print(json.dumps({"Account": d["account"]})); sys.exit(0)
if argv[:2] != ["ce", "get-cost-and-usage"]:
    sys.exit("shim: unexpected call " + " ".join(argv))
period = dict(kv.split("=") for kv in opt("--time-period").split(","))
start, end = dt.date.fromisoformat(period["Start"]), dt.date.fromisoformat(period["End"])
gran, metrics = opt("--granularity"), opts("--metrics")
groups = [g.split("Key=")[1] for g in opts("--group-by")] if "--group-by" in argv else []
filt = json.loads(opt("--filter")) if "--filter" in argv else None
def m(usd):
    return {k: {"Amount": str(usd), "Unit": "USD" if k != "UsageQuantity" else "Hrs"} for k in metrics}
if filt and ("Tags" in filt or "And" in filt):
    tags = [filt] if "Tags" in filt else filt["And"]
    keys = sorted(t["Tags"]["Key"] + "=" + t["Tags"]["Values"][0] for t in tags)
    want = sorted(os.environ["WANT_TAGS"].split(","))
    if keys != want:
        sys.exit(f"shim: tag filter {keys} is not {want}")
    print(json.dumps({"ResultsByTime": [{"TimePeriod": period, "Total": m(d["tagged"]), "Groups": []}]})); sys.exit(0)
if filt and filt == {"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Elastic Container Service for Kubernetes"]}}:
    if gran != "MONTHLY" or groups != ["USAGE_TYPE"] or metrics != ["UsageQuantity"]:
        sys.exit("shim: EKS hours query shape")
    gs = [{"Keys": [k], "Metrics": m(v)} for k, v in d["eks_usage_types"].items()]
    print(json.dumps({"ResultsByTime": [{"TimePeriod": period, "Total": {}, "Groups": gs}]})); sys.exit(0)
if filt is None and gran == "DAILY" and groups == ["SERVICE", "RECORD_TYPE"]:
    days, t = [], start
    while t < end:
        k = t.isoformat()
        gs = [{"Keys": [s, "Usage"], "Metrics": m(v)} for s, v in d["usage"].get(k, {}).items()]
        gs += [{"Keys": ["Tax" if r == "Tax" else "Credits", r], "Metrics": m(v)} for r, v in d["other"].get(k, {}).items()]
        days.append({"TimePeriod": {"Start": k, "End": (t + dt.timedelta(days=1)).isoformat()}, "Total": {}, "Groups": gs})
        t += dt.timedelta(days=1)
    # Two days a page, so the script has to follow NextPageToken to see the whole window.
    page = int(opt("--next-page-token") or 0)
    body = {"ResultsByTime": days[page:page + 2]}
    if page + 2 < len(days):
        body["NextPageToken"] = str(page + 2)
    print(json.dumps(body)); sys.exit(0)
sys.exit("shim: unexpected cost-and-usage query " + " ".join(argv))
'''


def run(*args, data=DATA, want_tags="event=devopsdays-portland-2026,project=watch-it-burn"):
    with tempfile.TemporaryDirectory() as t:
        shim = pathlib.Path(t) / "aws"
        shim.write_text(SHIM)
        shim.chmod(0o755)
        calls = pathlib.Path(t) / "calls"
        calls.touch()
        env = dict(os.environ, PATH=f"{t}:{os.environ['PATH']}", CALLS=str(calls), SHIM_DATA=json.dumps(data),
                   WANT_TAGS=want_tags)
        env.pop("AWS_PROFILE", None)
        p = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True)
        return p, [json.loads(line) for line in calls.read_text().splitlines()]


def row(out, label):
    """The USD figure at the end of the first line that starts with label."""
    for ln in out.splitlines():
        if ln.strip().startswith(label):
            return float(ln.split()[-2].replace(",", "")) if ln.rstrip().endswith("USD") else float(ln.split()[-1].replace(",", ""))
    return None


def near(a, b):
    return a is not None and abs(a - b) < 0.006


print("== two accounts, the Portland-shaped window ==")
p, calls = run(*WINDOW, "--profile", "acct-a", "--profile", "acct-b")
out = p.stdout
check("exits 0", p.returncode == 0, p.stderr)
check("says it is measured from Cost Explorer", "DELIVERY COST, MEASURED FROM COST EXPLORER IN EACH MEMBER ACCOUNT" in out)
check("names the window and the tag filter", "2026-08-31 (incl) .. 2026-09-03 (excl)" in out
      and "tag filter: project=watch-it-burn, event=devopsdays-portland-2026" in out, out)
a_usage = 100 + 20 + 150 + 30 + 5.25 + 50 + 10
b_usage = 80 + 80 + 10 + 40
check(f"acct-a usage is the window's days only, {a_usage:.2f}", f"usage total{'':<43} {a_usage:>10,.2f} USD" in out, out)
check(f"acct-b usage {b_usage:.2f}", f"{b_usage:>10,.2f} USD" in out)
check("the day before and the first day after are not in the total",
      re.search(r"acct-a\s+111111111111\s+365\.25 USD", out) is not None, out)
check("the sum is both accounts", re.search(r"all accounts \(2\)\s+575\.25 USD", out) is not None, out)
check("by service, highest first", out.index("Amazon Elastic Compute Cloud - Compute") < out.index("Amazon Bedrock"))
check("Bedrock is a service row", near(row(out, "Amazon Bedrock"), 5.25), out)
check("tax in the window is listed and left out", "posted in the window and not in the total: Tax 40.00 USD" in out, out)
check("tax and credits outside the window are not listed", "9.00" not in out and "-3.00" not in out, out)
check("EKS cluster hours are perCluster only, not extended support or transfer",
      "EKS cluster hours: 600.0; usage per cluster hour: 0.61 USD per cluster hour" in out, out)
check("cluster hours and the rate summed across accounts",
      "EKS cluster hours, all accounts: 700.0; 0.82 USD per cluster hour" in out, out)
check("the tag-filtered figure is printed per account as it comes back",
      "tag-filtered total (project=watch-it-burn, event=devopsdays-portland-2026): 12.50 USD" in out
      and "tag-filtered, all accounts: 12.50 USD" in out, out)
check("daily usage printed for the window", "2026-09-01      185.25" in out, out)
check("the day before and after are shown", "day before the window (2026-08-30): 0.05 USD; first day after it (2026-09-03): 0.50 USD" in out, out)
check("idle edge days do not cut acct-a", "WINDOW CUTS SPEND: 2026-08-30" not in out.split("== acct-b")[0], out)
check("a busy day before the window cuts acct-b",
      "WINDOW CUTS SPEND: 2026-08-30 carries 30.00 USD" in out.split("== acct-b")[1], out)
check("and the footnote says to widen it", "widen the window to the fleet's whole life" in out)
check("says it is the whole account, co-tenants included", "a co-tenant's spend on the same days is inside it" in out)
check("says a missing account is not in it", "A fleet account left off the command line is not in it." in out)
check("no payer footnote when a tag figure came back", "only the payer account can activate" not in out)
check("every call carries one of the given profiles", all(c["profile"] in ("acct-a", "acct-b") for c in calls))
check("every call is us-east-1 json", all(c["argv"][c["argv"].index("--region") + 1] == "us-east-1" for c in calls))
check("read-only: only get-caller-identity and get-cost-and-usage",
      {tuple(c["argv"][:2]) for c in calls} == {("sts", "get-caller-identity"), ("ce", "get-cost-and-usage")})
daily = [c for c in calls if "DAILY" in c["argv"] and c["profile"] == "acct-a"]
check("the daily query pages through NextPageToken (5 days, 2 a page)", len(daily) == 3, daily)
check("the daily query spans a day either side", any("Start=2026-08-30,End=2026-09-04" in c["argv"] for c in daily), daily)
tag_calls = [c for c in calls if "--filter" in c["argv"] and "Tags" in c["argv"][c["argv"].index("--filter") + 1]]
check("the tag query covers the window only", all("Start=2026-08-31,End=2026-09-03" in c["argv"] for c in tag_calls), tag_calls)

print("== no --event: the tag filter is project alone, and a 0.00 says why ==")
zero = {k: dict(v, tagged=0.0) for k, v in DATA.items()}
p, _ = run("--start", "2026-08-31", "--end", "2026-09-03", "--today", "2026-11-05", "--profile", "acct-a",
           data=zero, want_tags="project=watch-it-burn")
check("exits 0", p.returncode == 0, p.stderr)
check("filter is project alone", "tag filter: project=watch-it-burn\n" in p.stdout, p.stdout)
check("0.00 is explained by the payer", "only the payer account can activate cost-allocation tags" in p.stdout)

print("== refusals ==")
p, calls = run(*WINDOW, "--profile", "acct-a", "--profile", "nope")
check("an account it cannot read ends the run with exit 3", p.returncode == 3, p.stderr)
check("and prints no total", "all accounts" not in p.stdout and "nope" in p.stderr, p.stdout)
p, calls = run("--start", "2026-08-31", "--end", "2026-11-05", "--today", "2026-11-05", "--profile", "acct-a")
check("a window whose day after is not over is refused", p.returncode == 2 and not calls, p.stderr)
p, calls = run("--start", "2026-09-03", "--end", "2026-09-03", "--today", "2026-11-05", "--profile", "acct-a")
check("an empty window is refused", p.returncode == 2 and not calls, p.stderr)
p, calls = run(*WINDOW, "--profile", "acct-a", "--profile", "acct-a")
check("a profile given twice is refused", p.returncode == 2 and not calls, p.stderr)
same = dict(DATA, **{"acct-c": dict(DATA["acct-a"])})
p, _ = run(*WINDOW, "--profile", "acct-a", "--profile", "acct-c", data=same)
check("two profiles on one account are refused", p.returncode == 3 and "same account 111111111111" in p.stderr, p.stderr)

print("== the recorded runs are the script's output ==")
MEASURED = REPO / "cost/measured"
for f in ("devopsdays-portland-2026.txt", "ai-engineer-worldsfair-2026.txt"):
    text = (MEASURED / f).read_text() if (MEASURED / f).is_file() else ""
    check(f"{f} is recorded", text.startswith("DELIVERY COST, MEASURED FROM COST EXPLORER IN EACH MEMBER ACCOUNT"))
    check(f"{f} has no WINDOW CUTS SPEND line", text and "WINDOW CUTS SPEND" not in text)

if failures:
    print(f"\n{len(failures)} delivery-cost check(s) failed")
    sys.exit(1)
print("all delivery-cost checks passed")
