#!/usr/bin/env python3
# ABOUTME: Join the AWS-cluster pool (from the Terraform fleet) with the Datadog accounts CSV
# ABOUTME: (from Tara's generate_accounts_csv.sh) row-by-row into the distributor's v2 pool.csv.
"""
Build the distributor pool.csv from two inputs, joined by row position:

  --aws      CSV with: name,region,access_key,secret_key,console_url
             (one row per provisioned attendee cluster; from the Terraform fleet output)
  --datadog  CSV from DataDog/learning-center-lambdas generate_accounts_csv.sh, with:
             orgName,orgId,datadogEmail,password,apiKey,appKey,datadogUserId,expirationDate,poolName,parentOrg

Row N of --aws is paired with row N of --datadog (same attendee). Writes the v2 schema to --out.
Real credentials live in the secrets vault, never committed — see README.

Usage:
  python3 scripts/merge_pool.py --aws aws-pool.csv --datadog wib-pool-accounts.csv --out pool.csv \
      [--site datadoghq.com] [--dashboard-url-template "https://app.datadoghq.com/dashboard/lists?q={org}"]
"""
import argparse
import csv
import sys

V2_HEADER = [
    "name", "region", "access_key", "secret_key", "console_url",
    "datadog_org", "datadog_email", "datadog_password",
    "datadog_api_key", "datadog_app_key", "datadog_site", "datadog_dashboard_url",
]


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aws", required=True, help="AWS-cluster pool CSV (name,region,access_key,secret_key,console_url)")
    ap.add_argument("--datadog", required=True, help="Datadog accounts CSV from generate_accounts_csv.sh")
    ap.add_argument("--out", default="pool.csv", help="output pool.csv (default: pool.csv)")
    ap.add_argument("--site", default="datadoghq.com", help="Datadog site (default: datadoghq.com)")
    ap.add_argument("--dashboard-url-template", default="",
                    help="optional; {org} is replaced with the Datadog org name. Blank -> empty column.")
    args = ap.parse_args()

    aws = _read(args.aws)
    dd = _read(args.datadog)
    if len(aws) != len(dd):
        print(f"warn: {len(aws)} AWS rows vs {len(dd)} Datadog rows — joining the first "
              f"{min(len(aws), len(dd))} by position; check the pools line up.", file=sys.stderr)

    written = 0
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(V2_HEADER)
        for a, d in zip(aws, dd):
            org = (d.get("orgName") or "").strip()
            dash = args.dashboard_url_template.replace("{org}", org) if args.dashboard_url_template else ""
            w.writerow([
                (a.get("name") or "").strip(), (a.get("region") or "").strip(),
                (a.get("access_key") or "").strip(), (a.get("secret_key") or "").strip(),
                (a.get("console_url") or "").strip(),
                org, (d.get("datadogEmail") or "").strip(), (d.get("password") or "").strip(),
                (d.get("apiKey") or "").strip(), (d.get("appKey") or "").strip(),
                args.site, dash,
            ])
            written += 1
    print(f"wrote {written} rows to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
