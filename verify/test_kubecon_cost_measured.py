# ABOUTME: #392's criterion for the third delivery (#879): KubeCon NA is costed from each fleet account's own bill, not
# ABOUTME: by guesswork. Runs the run-of-show's cost command as written against an aws shim, and checks every record.
#
# #392 asked for the project cost-allocation tag to be activated on the payer account, "or the third delivery is
# costed by guesswork too". The payer is the lab-account provider's and is not asked (Michael's rulings on #392,
# 2026-11-01 and 2026-11-03), so the criterion became: each delivery is costed from the member accounts' Cost
# Explorer, by tag or by date, and the recorded figure is not zero (decisions.md, 2026-11-05 · #392). The two past
# deliveries are recorded in cost/measured/. The third, KubeCon NA 2026, is measured once its fleet is down (#872),
# and until then the only thing naming how is the run-of-show's teardown step. This test reads that step and fails
# when it stops holding:
#
#   1. The step names teardown/delivery-cost.py with the delivery's own event tag, a --profile for each fleet account
#      and cost/measured/<event>.txt as the record, and not the estimator.
#   2. That command, filled in with a KubeCon-shaped window and the fleet accounts from fleet.sh, runs against an aws
#      shim answering as a member account does (tag-filtered total 0.00) and prints a non-zero measured figure that
#      is the hand sum of every fleet account's billed usage. Run again with the tags answering as active, it and
#      teardown/cost-report.sh print the non-zero tag-filtered figure, which is #392's literal Done-when on the day
#      the payer activates the tags.
#   3. Every file in cost/measured/ has a non-zero total and non-zero EKS cluster hours, both past deliveries are
#      there, and a KubeCon record, once saved, names its event, covers the session day and measures every account.
#
# The shim's data is synthetic and owned here; nothing reaches AWS (run-tests.sh stubs aws first on PATH, and this
# test puts its own shim in front of that).
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "teardown/delivery-cost.py"
REPORT = REPO / "teardown/cost-report.sh"
ROS_PATH = REPO / "facilitation/kubecon-na-2026-run-of-show.md"
MEASURED = REPO / "cost/measured"
EVENT = ROS_PATH.name.removesuffix("-run-of-show.md")  # kubecon-na-2026, the delivery this run-of-show is for
failures = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def anchor(literal, text, path):
    """Tests own their inputs (CLAUDE.md): a reworded anchor names itself, not a broken check further on."""
    if literal not in text:
        sys.exit(f"anchor {literal!r} is not in {path.relative_to(REPO)}: reword this test with the new text")
    return text.index(literal)


ROS = ROS_PATH.read_text(encoding="utf-8")
fleet = re.search(r'WIB_ATTENDEE_ACCOUNTS="\$\{WIB_ATTENDEE_ACCOUNTS:-([^}]*)\}"',
                  (REPO / "infra/terraform/fleet/fleet.sh").read_text())
if fleet is None:
    sys.exit("infra/terraform/fleet/fleet.sh no longer sets WIB_ATTENDEE_ACCOUNTS's default: reword this test")
FLEET = fleet.group(1).split(",")

print(f"== the run-of-show's cost step names the measurement for {EVENT} ==")
STEP_ANCHOR = "- Record the real spend once the fleet is down"
i = anchor(STEP_ANCHOR, ROS, ROS_PATH)
rest = ROS[i + 2:]
step = " ".join(rest[:min(j for j in (rest.find("\n- "), rest.find("\n---"), len(rest)) if j >= 0)].split())
cmd = next((c for c in re.findall(r"`([^`]+)`", step) if c.startswith("teardown/delivery-cost.py")), None)
check("the step names a teardown/delivery-cost.py command", cmd is not None, step)
cmd = cmd or ""
holes = re.findall(r"<[^>]+>", cmd)
argv = shlex.split(re.sub(r"<[^>]+>", lambda m: f"HOLE{holes.index(m.group(0))}", cmd))[1:]


def after(flag):
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


check(f"its --event is the delivery's own tag, {EVENT}", after("--event") == EVENT, cmd)
check("its --start and --end are the two placeholders for the fleet's first and last day, and nothing else is",
      len(holes) == 2 and after("--start") == "HOLE0" and after("--end") == "HOLE1", cmd)
check("it asks for a --profile for each fleet account", "a `--profile` for each fleet account" in step, step)
check(f"the record is cost/measured/{EVENT}.txt", f"saved as `cost/measured/{EVENT}.txt`" in step, step)
check("it says the figure is read from each account's bill by date", "reads each account's bill by date" in step, step)
check("it does not cost the delivery with the estimator", "delivery-cost-estimate" not in step, step)
check("it names the issue that owes the record (#872)", "(#872)" in step, step)
README = (MEASURED / "README.md").read_text()
k = anchor("For KubeCon NA", README, MEASURED / "README.md")
check(f"cost/measured/README.md gives KubeCon the same command with --event {EVENT}",
      f"`--event {EVENT}`" in " ".join(README[k:k + 400].split()), README[k:k + 400])

# A KubeCon-shaped window: a build week before the event days 2026-11-09 .. 12, torn down on the 13th.
START, END, TODAY = "2026-11-02", "2026-11-14", "2026-11-20"
DAYS = [f"2026-11-{d:02d}" for d in range(2, 14)]
EKS = "Amazon Elastic Container Service for Kubernetes"
DATA = {}
for n, prof in enumerate(FLEET, start=1):
    usage = {d: {"Amazon Elastic Compute Cloud - Compute": round(10.0 * n + 1.25 * k, 2), EKS: round(2.4 * n, 2)}
             for k, d in enumerate(DAYS)}
    usage["2026-11-01"] = {"Amazon Elastic Compute Cloud - Compute": 0.03}
    usage["2026-11-14"] = {"Amazon Elastic Compute Cloud - Compute": 0.04}
    DATA[prof] = {"account": f"{n:012d}", "usage": usage, "other": {"2026-11-01": {"Tax": 31.0}},
                  "eks_hours": 24.0 * 12 * n, "tagged": 0.0}
WANT = {prof: round(sum(sum(d[day].values()) for day in DAYS for d in [DATA[prof]["usage"]]), 2) for prof in FLEET}
TOTAL = round(sum(WANT.values()), 2)

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
if "--query" in argv:  # teardown/cost-report.sh asks for text through --query
    q = opt("--query")
    if q.endswith(".Unit"):
        print("USD"); sys.exit(0)
    if "[Amount,Unit]" in q:
        print("999.00\tUSD"); sys.exit(0)
    print("\n".join(os.environ["TAGGED_TEXT"].split())); sys.exit(0)
data = json.loads(os.environ["SHIM_DATA"])
if not profile or opt("--region") != "us-east-1" or opt("--output") != "json" or profile not in data:
    sys.exit("shim: every call needs a fleet AWS_PROFILE, --region us-east-1 and --output json: " + " ".join(argv))
d = data[profile]
if argv[:2] == ["sts", "get-caller-identity"]:
    print(json.dumps({"Account": d["account"]})); sys.exit(0)
period = dict(kv.split("=") for kv in opt("--time-period").split(","))
start, end = dt.date.fromisoformat(period["Start"]), dt.date.fromisoformat(period["End"])
metrics = opts("--metrics")
groups = [g.split("Key=")[1] for g in opts("--group-by")] if "--group-by" in argv else []
filt = json.loads(opt("--filter")) if "--filter" in argv else None
def m(v):
    return {k: {"Amount": str(v), "Unit": "Hrs" if k == "UsageQuantity" else "USD"} for k in metrics}
if filt and ("Tags" in filt or "And" in filt):
    tags = sorted(t["Tags"]["Key"] + "=" + t["Tags"]["Values"][0] for t in ([filt] if "Tags" in filt else filt["And"]))
    if tags != sorted(os.environ["WANT_TAGS"].split(",")):
        sys.exit(f"shim: tag filter {tags}")
    print(json.dumps({"ResultsByTime": [{"TimePeriod": period, "Total": m(d["tagged"]), "Groups": []}]})); sys.exit(0)
if filt:
    gs = [{"Keys": ["USW2-AmazonEKS-Hours:perCluster"], "Metrics": m(d["eks_hours"])}]
    print(json.dumps({"ResultsByTime": [{"TimePeriod": period, "Total": {}, "Groups": gs}]})); sys.exit(0)
days, t = [], start
while t < end:
    k = t.isoformat()
    gs = [{"Keys": [s, "Usage"], "Metrics": m(v)} for s, v in d["usage"].get(k, {}).items()]
    gs += [{"Keys": ["Tax", r], "Metrics": m(v)} for r, v in d["other"].get(k, {}).items()]
    days.append({"TimePeriod": {"Start": k, "End": (t + dt.timedelta(days=1)).isoformat()}, "Total": {}, "Groups": gs})
    t += dt.timedelta(days=1)
print(json.dumps({"ResultsByTime": days}))
'''


def run(prog, args, data, tagged_text="0"):
    with tempfile.TemporaryDirectory() as t:
        shim = pathlib.Path(t) / "aws"
        shim.write_text(SHIM)
        shim.chmod(0o755)
        calls = pathlib.Path(t) / "calls"
        calls.touch()
        env = dict(os.environ, PATH=f"{t}:{os.environ['PATH']}", CALLS=str(calls), SHIM_DATA=json.dumps(data),
                   WANT_TAGS=f"project=watch-it-burn,event={EVENT}", TAGGED_TEXT=tagged_text)
        env.pop("AWS_PROFILE", None)
        p = subprocess.run([*prog, *args], env=env, capture_output=True, text=True)
        return p, [json.loads(line) for line in calls.read_text().splitlines()]


def usd(text, label):
    """The USD figure on the first line starting with label, or None."""
    for ln in text.splitlines():
        if ln.strip().startswith(label) and ln.rstrip().endswith("USD"):
            return float(ln.split()[-2].replace(",", ""))
    return None


filled = [START if a == "HOLE0" else END if a == "HOLE1" else a for a in argv]
filled += [x for prof in FLEET for x in ("--profile", prof)] + ["--today", TODAY]

print(f"== that command, as written, costs {EVENT} from every fleet account's bill (tags inactive, as now) ==")
p, calls = run([sys.executable, str(SCRIPT)], filled, DATA)
out = p.stdout
check("exits 0", p.returncode == 0, p.stderr)
check(f"names the delivery {EVENT} and the tag filter on it",
      f"delivery: {EVENT}\ntag filter: project=watch-it-burn, event={EVENT}\n" in out, out[:300])
check(f"asks Cost Explorer in each of the {len(FLEET)} fleet accounts",
      sorted({c["profile"] for c in calls}) == sorted(FLEET), sorted({c["profile"] for c in calls}))
check("read-only: only get-caller-identity and get-cost-and-usage", calls and all(
    c["argv"][:2] in (["sts", "get-caller-identity"], ["ce", "get-cost-and-usage"]) for c in calls), calls)
for prof in FLEET:
    block = out.split(f"== {prof} ")[1].split("\n\n")[0] if f"== {prof} " in out else ""
    check(f"{prof}: the tag figure is 0.00, as a member account answers",
          f"tag-filtered total (project=watch-it-burn, event={EVENT}): 0.00 USD" in block, block[:200])
    got = usd(block, "usage total")
    check(f"{prof}: the measured usage is the window's days, {WANT[prof]:,.2f} USD, edge days and tax left out",
          got is not None and abs(got - WANT[prof]) < 0.006, got)
got = usd(out, f"all accounts ({len(FLEET)})")
check(f"the delivery's figure is all {len(FLEET)} accounts, {TOTAL:,.2f} USD, and not zero",
      got is not None and got > 0 and abs(got - TOTAL) < 0.011, got)
check("the tag sum is 0.00, and the report says why", "tag-filtered, all accounts: 0.00 USD" in out
      and "only the payer account can activate cost-allocation tags" in out, out[-900:])
check("the measured figure is not an estimate", "It is\n    measured, not estimated" in out, out[-900:])

print("== the day the tags are active, the tag-filtered figure reads non-zero ==")
active = {prof: dict(d, tagged=round(WANT[prof] * 0.8, 2)) for prof, d in DATA.items()}
p, _ = run([sys.executable, str(SCRIPT)], filled, active)
tag_sum = round(sum(d["tagged"] for d in active.values()), 2)
check("delivery-cost.py exits 0", p.returncode == 0, p.stderr)
check(f"and prints the tag sum, {tag_sum:,.2f} USD", f"tag-filtered, all accounts: {tag_sum:,.2f} USD" in p.stdout,
      p.stdout[-900:])
check("with no payer footnote", "only the payer account can activate" not in p.stdout)
report = ["bash", str(REPORT), "--start", START, "--end", END, "--tag-key", "event", "--tag-value", EVENT]
p, calls = run(report, [], DATA, tagged_text="412.30 388.70")
check("cost-report.sh by the event tag exits 0", p.returncode == 0, p.stderr)
check("and filters on event=" + EVENT, calls and all(
    json.loads(c["argv"][c["argv"].index("--filter") + 1]) == {"Tags": {"Key": "event", "Values": [EVENT]}}
    for c in calls if "--filter" in c["argv"]), calls)
check("and prints the non-zero tag-filtered total, 801.00 USD", "TOTAL:  801.00 USD" in p.stdout, p.stdout)
check("with no zero warning", "Tag-filtered total is 0.00" not in p.stdout, p.stdout)
p, _ = run(report, [], DATA, tagged_text="0")
check("while the tags are inactive, cost-report.sh's 0.00 points at delivery-cost.py",
      p.returncode == 0 and "TOTAL:  0.00 USD" in p.stdout and "teardown/delivery-cost.py" in p.stdout, p.stdout)

print("== every recorded delivery is measured, not zero ==")
files = sorted(MEASURED.glob("*.txt"))
names = {f.name for f in files}
for past in ("ai-engineer-worldsfair-2026.txt", "devopsdays-portland-2026.txt"):
    check(f"{past} is recorded", past in names, sorted(names))
for f in files:
    text = f.read_text()
    total = usd(text, "all accounts (")
    check(f"{f.name}: the measured total is not zero", total is not None and total > 0, total)
    hours = re.search(r"EKS cluster hours, all accounts: ([\d,]+\.\d)", text)
    check(f"{f.name}: its window has fleet activity (EKS cluster hours above zero)",
          hours is not None and float(hours.group(1).replace(",", "")) > 0, hours)
SESSION = re.search(r"30 minutes, Thursday (\d{4}-\d\d-\d\d)\.", ROS)
if SESSION is None:
    sys.exit(f"anchor '30 minutes, Thursday <date>.' is not in {ROS_PATH.relative_to(REPO)}: reword this test")
kubecon = MEASURED / f"{EVENT}.txt"
if kubecon.is_file():
    text = kubecon.read_text()
    w = re.search(r"^window: (\S+) \(incl\) \.\. (\S+) \(excl\)", text, re.M)
    check(f"{kubecon.name} names its delivery", f"\ndelivery: {EVENT}\n" in text, text[:300])
    check(f"{kubecon.name}'s window takes in the session day {SESSION.group(1)}",
          w is not None and w.group(1) <= SESSION.group(1) < w.group(2), w)
    missing = [a for a in FLEET if not re.search(rf"^  {re.escape(a)}\s+\d{{12}}\s+[\d,]+\.\d\d USD$", text, re.M)]
    check(f"{kubecon.name} measures every fleet account", not missing, missing)
    check(f"{kubecon.name} has no WINDOW CUTS SPEND line", "WINDOW CUTS SPEND" not in text)
else:
    print(f"  ({kubecon.relative_to(REPO)} is not recorded yet: #872 records it once the fleet is down; the command"
          " above is what it runs)")

if failures:
    print(f"\n{len(failures)} check(s) failed: #392's third delivery would be costed by guesswork")
    sys.exit(1)
print(f"all checks passed: {EVENT} is costed from the fleet accounts' bills, and every record is measured")
