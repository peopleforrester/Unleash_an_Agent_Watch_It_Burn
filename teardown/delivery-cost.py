#!/usr/bin/env python3
# ABOUTME: Measures one delivery's AWS cost from Cost Explorer in each member account (#392): the tag-filtered figure
# ABOUTME: where the tags are active, and every account's billed usage over the delivery's dates, by service and day.
#
# Why this exists. The payer account (457247706586, the lab-account provider's Organization management account, #202)
# is the only one that can activate `project` and `event` as cost-allocation tags, and nobody asks the provider for
# anything (Michael's rulings on #392, 2026-11-01, and on escalation 227, 2026-11-03). In a member account Cost
# Explorer still answers a tag-filtered query, with 0.00, and refuses to list the tags at all. So this script asks
# each member account two things:
#
#   * the tag-filtered total (project=watch-it-burn, plus event=<event> with --event), printed as it comes back, so
#     the day the tags are active the measured figure is already in the report;
#   * the account's billed usage on the delivery's dates (record type Usage), by service and by day. That is a
#     measurement, not an estimate: it is what the bill says for those days. It is the WHOLE account, so a co-tenant
#     working on the same days is inside it, and the report says so.
#
# Beside them: EKS cluster hours from the same bill (usage type AmazonEKS-Hours:perCluster), so the cost per cluster
# hour is measured too, and the day before and the day after the window, so a window that cuts off part of the
# fleet's life says so (WINDOW CUTS SPEND) rather than printing a quietly lower figure.
#
# Tax is posted on the bill's own days (mostly the 1st of the month), not on the usage days it is for, so it, credits
# and refunds are listed and left out.
#
# Usage:
#   teardown/delivery-cost.py --start 2026-08-26 --end 2026-09-10 --event devopsdays-portland-2026 \
#       --profile accen-dev --profile aws1-student31 ...
# Every AWS call carries its profile (AWS_PROFILE, per call) and region explicitly; Cost Explorer is us-east-1. Any
# call that fails ends the run with exit 3: an account dropped quietly is the 0.00 problem again.
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

CE_REGION = "us-east-1"
EKS_SERVICE = "Amazon Elastic Container Service for Kubernetes"
EKS_CLUSTER_HOURS = re.compile(r"(^|-)AmazonEKS-Hours:perCluster$")
# A day just outside the window is "fleet spend" when it carries more than this share of the window's busiest day,
# and more than the floor below, which is above the idle accounts' own run rate (0.03 to 0.08 USD a day on
# accen-dev between deliveries, read 2026-11-05).
EDGE_SHARE = 0.05
EDGE_FLOOR_USD = 1.00


class AwsError(RuntimeError):
    pass


def aws(profile, *args):
    """One AWS CLI call as JSON, with the profile and region explicit on the call (CLAUDE.md, kube-context rules)."""
    env = dict(os.environ, AWS_PROFILE=profile)
    env.pop("AWS_DEFAULT_PROFILE", None)
    cmd = ["aws", *args, "--region", CE_REGION, "--output", "json"]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise AwsError(f"[{profile}] aws {' '.join(args)} failed (exit {p.returncode}): {p.stderr.strip()}")
    return json.loads(p.stdout) if p.stdout.strip() else {}


def cost_and_usage(profile, start, end, granularity, metrics, filt=None, group_by=()):
    """get-cost-and-usage, every page. Returns the ResultsByTime list."""
    args = ["ce", "get-cost-and-usage", "--time-period", f"Start={start},End={end}",
            "--granularity", granularity, "--metrics", *metrics]
    if filt is not None:
        args += ["--filter", json.dumps(filt, separators=(",", ":"))]
    if group_by:
        args += ["--group-by", *(f"Type=DIMENSION,Key={k}" for k in group_by)]
    results, token = [], None
    while True:
        page = aws(profile, *args, *(["--next-page-token", token] if token else []))
        results += page.get("ResultsByTime", [])
        token = page.get("NextPageToken")
        if not token:
            return results


def amount(metrics, name="UnblendedCost"):
    return float(metrics.get(name, {}).get("Amount", 0) or 0)


def tag_filter(key, value, event):
    tags = [{"Tags": {"Key": key, "Values": [value]}}]
    if event:
        tags.append({"Tags": {"Key": "event", "Values": [event]}})
    return tags[0] if len(tags) == 1 else {"And": tags}


def day(s):
    return dt.date.fromisoformat(s)


def measure(profile, args):
    start, end = args.start, args.end
    before = (day(start) - dt.timedelta(days=1)).isoformat()
    after_end = (day(end) + dt.timedelta(days=1)).isoformat()
    acct = {"profile": profile, "account": aws(profile, "sts", "get-caller-identity").get("Account", "?")}

    tagged = cost_and_usage(profile, start, end, "MONTHLY", ["UnblendedCost"],
                            filt=tag_filter(args.tag_key, args.tag_value, args.event))
    acct["tagged"] = sum(amount(r.get("Total", {})) for r in tagged)

    # One daily query over the window plus a day on each side, by service and record type.
    by_service, other, daily = {}, {}, {}
    for r in cost_and_usage(profile, before, after_end, "DAILY", ["UnblendedCost"],
                            group_by=("SERVICE", "RECORD_TYPE")):
        d = r["TimePeriod"]["Start"]
        for g in r.get("Groups", []):
            service, record = g["Keys"]
            usd = amount(g["Metrics"])
            if record == "Usage":
                daily[d] = daily.get(d, 0.0) + usd
                if start <= d < end:
                    by_service[service] = by_service.get(service, 0.0) + usd
            elif start <= d < end:
                other[record] = other.get(record, 0.0) + usd
    acct["by_service"] = by_service
    acct["other"] = other
    acct["usage"] = sum(by_service.values())
    acct["days"] = {d: v for d, v in sorted(daily.items()) if start <= d < end}
    acct["before"] = (before, daily.get(before, 0.0))
    acct["after"] = (end, daily.get(end, 0.0))
    peak = max(acct["days"].values(), default=0.0)
    limit = max(EDGE_FLOOR_USD, EDGE_SHARE * peak)
    acct["cuts"] = [f"{d} carries {v:,.2f} USD" for d, v in (acct["before"], acct["after"]) if v > limit]

    hours = 0.0
    for r in cost_and_usage(profile, start, end, "MONTHLY", ["UsageQuantity"],
                            filt={"Dimensions": {"Key": "SERVICE", "Values": [EKS_SERVICE]}},
                            group_by=("USAGE_TYPE",)):
        for g in r.get("Groups", []):
            if EKS_CLUSTER_HOURS.search(g["Keys"][0]):
                hours += amount(g["Metrics"], "UsageQuantity")
    acct["cluster_hours"] = hours
    return acct


def per_hour(usd, hours):
    return f"{usd / hours:,.2f} USD per cluster hour" if hours else "no EKS cluster hours"


def render(args, accts):
    out = []
    w = out.append
    tag = f"{args.tag_key}={args.tag_value}" + (f", event={args.event}" if args.event else "")
    w("DELIVERY COST, MEASURED FROM COST EXPLORER IN EACH MEMBER ACCOUNT")
    w(f"window: {args.start} (incl) .. {args.end} (excl), UTC days")
    if args.event:
        w(f"delivery: {args.event}")
    w(f"tag filter: {tag}")
    w("")
    for a in accts:
        name = f"{a['profile']}  {a['account']}"
        w(f"== {name}")
        w(f"  tag-filtered total ({tag}): {a['tagged']:,.2f} USD")
        w("  billed usage on the window's dates, by service (the whole account):")
        for svc, usd in sorted(a["by_service"].items(), key=lambda kv: -kv[1]):
            w(f"    {svc:<52} {usd:>10,.2f}")
        w(f"  usage total{'':<43} {a['usage']:>10,.2f} USD")
        if a["other"]:
            w("  posted in the window and not in the total: " +
              ", ".join(f"{k} {v:,.2f} USD" for k, v in sorted(a["other"].items())))
        w(f"  EKS cluster hours: {a['cluster_hours']:,.1f}; usage per cluster hour: {per_hour(a['usage'], a['cluster_hours'])}")
        w(f"  day before the window ({a['before'][0]}): {a['before'][1]:,.2f} USD; "
          f"first day after it ({a['after'][0]}): {a['after'][1]:,.2f} USD")
        for c in a["cuts"]:
            w(f"  WINDOW CUTS SPEND: {c}, so fleet spend runs past the window and the total is too low")
        w("  usage by day:")
        for d, usd in a["days"].items():
            w(f"    {d}  {usd:>10,.2f}")
        w("")
    usage = sum(a["usage"] for a in accts)
    tagged = sum(a["tagged"] for a in accts)
    hours = sum(a["cluster_hours"] for a in accts)
    w("== DELIVERY COST, BILLED USAGE ON THE WINDOW'S DATES")
    for a in accts:
        w(f"  {a['profile']:<20} {a['account']:<14} {a['usage']:>10,.2f} USD")
    w(f"  {'all accounts (' + str(len(accts)) + ')':<35} {usage:>10,.2f} USD")
    w(f"  EKS cluster hours, all accounts: {hours:,.1f}; {per_hour(usage, hours)}")
    w(f"  tag-filtered, all accounts: {tagged:,.2f} USD")
    w("")
    w("What the figure is:")
    w("  * Each account's billed usage (Cost Explorer record type Usage, unblended) on the window's UTC days. It is")
    w("    measured, not estimated, and it is the whole account: a co-tenant's spend on the same days is inside it.")
    w("  * Only the accounts listed above. A fleet account left off the command line is not in it.")
    w("  * Tax, credits and refunds are left out. Tax is posted on the bill's own days, mostly the 1st of the month,")
    w("    not on the usage days it is for.")
    if tagged == 0:
        w("  * The tag-filtered total is 0.00 because only the payer account can activate cost-allocation tags, and the")
        w("    payer is the lab-account provider's, which is not asked (#392). It is printed so the day the tags are")
        w("    active, the per-delivery figure is in this report without a code change.")
    if any(a["cuts"] for a in accts):
        w("  * WINDOW CUTS SPEND is printed above for at least one account: widen the window to the fleet's whole life.")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="window start, YYYY-MM-DD, inclusive (UTC)")
    ap.add_argument("--end", required=True, help="window end, YYYY-MM-DD, exclusive (UTC), the Cost Explorer convention")
    ap.add_argument("--profile", action="append", required=True,
                    help="an AWS profile per fleet account; repeat it for each account")
    ap.add_argument("--event", help="also require event=<value> in the tag-filtered query (e.g. devopsdays-portland-2026)")
    ap.add_argument("--tag-key", default="project")
    ap.add_argument("--tag-value", default="watch-it-burn")
    ap.add_argument("--today", help="the date counted as today, YYYY-MM-DD (default: the UTC date now)")
    args = ap.parse_args(argv)
    try:
        start, end = day(args.start), day(args.end)
        today = day(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    except ValueError as e:
        ap.error(f"dates must be YYYY-MM-DD: {e}")
    if end <= start:
        ap.error("--end must be after --start")
    # The day after the window is read too, and it has to be over, or a fleet still running reads as a closed window.
    if end >= today:
        ap.error(f"--end {args.end} is not in the past: the window and the day after it must be over (today is {today})")
    if len(set(args.profile)) != len(args.profile):
        ap.error("a --profile is given twice, which would count its account twice")
    try:
        accts = [measure(p, args) for p in args.profile]
    except AwsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Nothing printed: a total missing an account would read as the delivery's cost.", file=sys.stderr)
        return 3
    seen = {}
    for a in accts:
        if a["account"] in seen:
            print(f"ERROR: profiles {seen[a['account']]} and {a['profile']} are the same account {a['account']}, "
                  "which would count it twice", file=sys.stderr)
            return 3
        seen[a["account"]] = a["profile"]
    sys.stdout.write(render(args, accts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
