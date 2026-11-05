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

print("== --recorded: an account read from saved replies gives the live figures ==")


def day_range(a, b):
    import datetime as dt
    t, out = dt.date.fromisoformat(a), []
    while t < dt.date.fromisoformat(b):
        out.append(t.isoformat())
        t += dt.timedelta(days=1)
    return out


def nxt(d):
    import datetime as dt
    return (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()


def usd(v, unit="USD"):
    return {"Amount": str(v), "Unit": unit}


def record(root, profile, d, cost_days=("2026-08-30", "2026-09-04"), eks_days=("2026-08-29", "2026-09-04"),
           cost_groups=("SERVICE", "RECORD_TYPE"), token=None, account=None):
    """Write DATA[profile] as the two saved replies and meta.json, in the shape the escalation posted them.

    The EKS reply is daily and runs a day either side of the window, with perCluster hours on those days that the
    script must leave out; the window's hours sit on its first day."""
    out = pathlib.Path(root) / profile
    out.mkdir(parents=True)
    days = []
    for k in day_range(*cost_days):
        gs = [{"Keys": [s, "Usage"], "Metrics": {"UnblendedCost": usd(v)}} for s, v in d["usage"].get(k, {}).items()]
        gs += [{"Keys": ["Tax", r], "Metrics": {"UnblendedCost": usd(v)}} for r, v in d["other"].get(k, {}).items()]
        days.append({"TimePeriod": {"Start": k, "End": nxt(k)}, "Total": {}, "Groups": gs, "Estimated": False})
    cost = {"GroupDefinitions": [{"Type": "DIMENSION", "Key": g} for g in cost_groups], "ResultsByTime": days,
            "DimensionValueAttributes": []}
    if token:
        cost["NextPageToken"] = token
    eks = []
    for k in day_range(*eks_days):
        if k == "2026-08-31":
            gs = [{"Keys": [u], "Metrics": {"UsageQuantity": usd(v, "Hrs")}} for u, v in d["eks_usage_types"].items()]
        else:
            gs = [{"Keys": ["USW2-AmazonEKS-Hours:perCluster"], "Metrics": {"UsageQuantity": usd(999.0, "Hrs")}}]
            gs = gs if k < "2026-08-31" or k >= "2026-09-03" else []
        eks.append({"TimePeriod": {"Start": k, "End": nxt(k)}, "Total": {}, "Groups": gs, "Estimated": False})
    (out / "cost-by-service-record-type.json").write_text(json.dumps(cost))
    (out / "eks-usage-by-usage-type.json").write_text(json.dumps(
        {"GroupDefinitions": [{"Type": "DIMENSION", "Key": "USAGE_TYPE"}], "ResultsByTime": eks}))
    (out / "meta.json").write_text(json.dumps({"profile": profile, "account": account or d["account"],
                                               "read_on": "2026-11-05", "source": f"https://example.test/{profile}"}))
    return str(out)


def summary_line(out, profile):
    m = re.search(rf"^  {re.escape(profile)}\s+\d{{12}}\s+[\d,]+\.\d\d USD$", out, re.M)
    return m.group(0) if m else None


live, _ = run(*WINDOW, "--profile", "acct-a", "--profile", "acct-b")
with tempfile.TemporaryDirectory() as root:
    rb = record(root, "acct-b", DATA["acct-b"])
    p, calls = run(*WINDOW, "--profile", "acct-a", "--recorded", rb)
    out = p.stdout
    check("exits 0", p.returncode == 0, p.stderr)
    check("no AWS call for the recorded account", all(c["profile"] == "acct-a" for c in calls), calls)
    block_b = out.split("== acct-b")[1].split("\n\n")[0]
    check("the recorded account's block is the live one's, but for the source and the tag line",
          [ln for ln in block_b.splitlines() if "tag-filtered" not in ln and "recorded" not in ln]
          == [ln for ln in live.stdout.split("== acct-b")[1].split("\n\n")[0].splitlines() if "tag-filtered" not in ln],
          block_b)
    check("its summary line is the live one's", summary_line(out, "acct-b") == summary_line(live.stdout, "acct-b")
          and summary_line(out, "acct-b") is not None, out)
    check("EKS hours outside the window are not counted, nor non-perCluster types",
          "EKS cluster hours: 100.0;" in block_b, block_b)
    check("the all-accounts figures match the live run", re.search(r"all accounts \(2\)\s+575\.25 USD", out)
          and "EKS cluster hours, all accounts: 700.0; 0.82 USD per cluster hour" in out, out)
    check("names where the replies came from", "not asked by this run: https://example.test/acct-b (read 2026-11-05)"
          in block_b, block_b)
    check("its tag figure is not read, never 0.00",
          "tag-filtered total (project=watch-it-burn, event=devopsdays-portland-2026): not read" in block_b, block_b)
    check("the tag sum counts only the live account and names the recorded one",
          "tag-filtered, the 1 account(s) asked live: 0.00 USD; not read on acct-b" in out, out)
    check("the footnote says a recorded account was not asked", "was not asked by this run" in out, out)

    # Recorded only: no AWS call at all, and no payer footnote, since no tag figure was read.
    ra = record(root, "acct-a", DATA["acct-a"])
    p, calls = run(*WINDOW, "--recorded", ra, "--recorded", rb)
    check("recorded only: exits 0 with no AWS call", p.returncode == 0 and not calls, p.stderr + str(calls))
    check("recorded only: the live total", re.search(r"all accounts \(2\)\s+575\.25 USD", p.stdout) is not None, p.stdout)
    check("recorded only: no payer footnote without a tag figure", "only the payer account" not in p.stdout, p.stdout)

    def refused(name, path, needle, extra=()):
        p, _ = run(*WINDOW, "--profile", "acct-a", *extra, "--recorded", path)
        check(name, p.returncode == 3 and needle in p.stderr and "all accounts" not in p.stdout, p.stderr + p.stdout)

    refused("a cost reply that misses the day after the window is refused",
            record(root, "short", DATA["acct-b"], cost_days=("2026-08-30", "2026-09-03")),
            "does not cover 2026-09-03")
    refused("an EKS reply that misses a window day is refused",
            record(root, "eks-short", DATA["acct-b"], eks_days=("2026-09-02", "2026-09-04")),
            "does not cover 2026-08-31 and 1 more day(s)")
    refused("a reply with a NextPageToken is refused", record(root, "paged", DATA["acct-b"], token="abc"),
            "carries a NextPageToken")
    refused("a cost reply grouped otherwise is refused",
            record(root, "grouped", DATA["acct-b"], cost_groups=("SERVICE",)), "is grouped by ['SERVICE']")
    monthly = record(root, "monthly", DATA["acct-b"])
    f = pathlib.Path(monthly) / "eks-usage-by-usage-type.json"
    f.write_text(json.dumps(dict(json.loads(f.read_text()), ResultsByTime=[
        {"TimePeriod": {"Start": "2026-08-01", "End": "2026-09-01"}, "Total": {}, "Groups": []}])))
    refused("a reply that is not daily is refused", monthly, "is not daily")
    nometa = record(root, "nometa", DATA["acct-b"])
    (pathlib.Path(nometa) / "meta.json").write_text(json.dumps({"profile": "nometa", "account": "333333333333"}))
    refused("a meta.json without its source is refused", nometa, "meta.json has no read_on")
    refused("a recorded account that is a live one too is refused",
            record(root, "dup", DATA["acct-b"], account="111111111111"), "same account 111111111111")
    p, calls = run(*WINDOW)
    check("no account at all is refused", p.returncode == 2 and not calls, p.stderr)

print("== the recorded runs are the script's output ==")
MEASURED = REPO / "cost/measured"
RECORDED = MEASURED / "recorded"
fleet = re.search(r'WIB_ATTENDEE_ACCOUNTS="\$\{WIB_ATTENDEE_ACCOUNTS:-([^}]*)\}"',
                  (REPO / "infra/terraform/fleet/fleet.sh").read_text())
check("fleet.sh names the fleet accounts", fleet is not None)
FLEET = fleet.group(1).split(",") if fleet else []
saved = sorted(d.name for d in RECORDED.iterdir() if d.is_dir()) if RECORDED.is_dir() else []
check("each recorded account is a fleet account", saved and set(saved) <= set(FLEET), saved)
for name in saved:
    meta = json.loads((RECORDED / name / "meta.json").read_text())
    check(f"{name}: meta.json names it, a 12-digit account and a source",
          meta.get("profile") == name and re.fullmatch(r"\d{12}", meta.get("account", "")) is not None
          and meta.get("source", "").startswith("https://"), meta)
WINDOWS = {"devopsdays-portland-2026.txt": ["--start", "2026-08-26", "--end", "2026-09-10",
                                            "--event", "devopsdays-portland-2026"],
           "ai-engineer-worldsfair-2026.txt": ["--start", "2026-06-25", "--end", "2026-07-01"]}
for f, window in WINDOWS.items():
    text = (MEASURED / f).read_text() if (MEASURED / f).is_file() else ""
    check(f"{f} is recorded", text.startswith("DELIVERY COST, MEASURED FROM COST EXPLORER IN EACH MEMBER ACCOUNT"))
    check(f"{f} has no WINDOW CUTS SPEND line", text and "WINDOW CUTS SPEND" not in text)
    check(f"{f} names its window", f"window: {window[1]} (incl) .. {window[3]} (excl)" in text, text[:200])
    missing = [a for a in FLEET if summary_line(text, a) is None]
    check(f"{f} measures every fleet account in fleet.sh", FLEET and not missing, missing)
    check(f"{f} sums {len(FLEET)} accounts", f"all accounts ({len(FLEET)})" in text)
    # Replaying the saved replies gives the figures the file holds for those accounts, block and summary line.
    p, calls = run(*window, "--today", "2026-11-05", *[x for n in saved for x in ("--recorded", str(RECORDED / n))])
    check(f"{f}: the saved replies replay with no AWS call", p.returncode == 0 and not calls, p.stderr)
    for n in saved:
        replay_block = p.stdout.split(f"== {n} ")[1].split("\n\n")[0] if f"== {n} " in p.stdout else None
        file_block = text.split(f"== {n} ")[1].split("\n\n")[0] if f"== {n} " in text else ""
        check(f"{f}: {n}'s block and total are its saved replies replayed",
              replay_block == file_block and summary_line(p.stdout, n) == summary_line(text, n), replay_block)
    total = re.search(r"all accounts \(\d+\)\s+([\d,]+\.\d\d) USD", text)
    lines = [summary_line(text, a) for a in FLEET]
    check(f"{f}: the total is the sum of its account lines", total and all(lines) and abs(
        sum(float(ln.split()[-2].replace(",", "")) for ln in lines) - float(total.group(1).replace(",", ""))) < 0.011,
        total)

if failures:
    print(f"\n{len(failures)} delivery-cost check(s) failed")
    sys.exit(1)
print("all delivery-cost checks passed")
