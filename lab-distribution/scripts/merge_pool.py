#!/usr/bin/env python3
# ABOUTME: Join the AWS-cluster pool (from the Terraform fleet) with the Datadog accounts (from
# ABOUTME: Secrets Manager watch-it-burn/datadog-pool, or a CSV) row-by-row into the distributor pool.csv.
"""
Build the distributor pool.csv from two inputs, joined by row position:

  --aws      CSV with: name,region,access_key,secret_key[,console_url]
             (one row per provisioned attendee cluster; from generate_attendee_aws.py / the fleet)

  Datadog side (pick one):
    default      pull from Secrets Manager `watch-it-burn/datadog-pool` (the staged 22-org pool),
                 using only role=="attendee" entries (the 2 admin orgs are excluded by default).
    --datadog    a CSV from DataDog/learning-center-lambdas generate_accounts_csv.sh, with columns
                 orgName,datadogEmail,password,apiKey,appKey,...

Row N of --aws is paired with Datadog account N (same attendee). Writes the v2 schema to --out.
Real credentials live in Secrets Manager / the file, never committed.

Usage:
  # Datadog from Secrets Manager (default):
  uv run --with boto3 python scripts/merge_pool.py --aws aws-pool-accen-dev.csv --out pool.csv

  # Datadog from a CSV (legacy):
  python3 scripts/merge_pool.py --aws aws-pool.csv --datadog wib-pool-accounts.csv --out pool.csv
"""
import argparse
import csv
import json
import sys

DEFAULT_DD_SECRET = "watch-it-burn/datadog-pool"

V2_HEADER = [
    "name", "region", "access_key", "secret_key", "console_url",
    "datadog_org", "datadog_email", "datadog_password",
    "datadog_api_key", "datadog_app_key", "datadog_site", "datadog_dashboard_url",
]


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh)]


def _norm_from_csv(rows):
    # generate_accounts_csv.sh shape -> normalized {org,email,password,api_key,app_key}.
    return [{
        "org": (r.get("orgName") or "").strip(),
        "email": (r.get("datadogEmail") or "").strip(),
        "password": (r.get("password") or "").strip(),
        "api_key": (r.get("apiKey") or "").strip(),
        "app_key": (r.get("appKey") or "").strip(),
    } for r in rows]


def _norm_from_secret(secret_id, profile, region, include_admins):
    # watch-it-burn/datadog-pool shape: [{role,org,email,password,api-key,app-key,site}, ...].
    import boto3
    sm = boto3.Session(profile_name=profile, region_name=region).client("secretsmanager")
    pool = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
    out = []
    for a in pool:
        if not include_admins and (a.get("role") or "").startswith("admin"):
            continue  # exclude admin-instructor / admin-attendee from the attendee pool
        out.append({
            "org": a.get("org", ""), "email": a.get("email", ""), "password": a.get("password", ""),
            "api_key": a.get("api-key", ""), "app_key": a.get("app-key", ""),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aws", required=True, help="AWS-cluster pool CSV (name,region,access_key,secret_key[,console_url])")
    ap.add_argument("--datadog", help="legacy: Datadog accounts CSV. Omit to pull from Secrets Manager.")
    ap.add_argument("--datadog-secret", default=DEFAULT_DD_SECRET, help=f"Secrets Manager id (default {DEFAULT_DD_SECRET})")
    ap.add_argument("--profile", default="accen-dev")
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--include-admins", action="store_true",
                    help="include the admin-instructor/admin-attendee orgs (default: attendee orgs only)")
    ap.add_argument("--out", default="pool.csv")
    ap.add_argument("--site", default="datadoghq.com")
    ap.add_argument("--dashboard-url-template", default="",
                    help="optional; {org} is replaced with the Datadog org name. Blank -> empty column.")
    args = ap.parse_args()

    aws = _read_csv(args.aws)
    if args.datadog:
        dd = _norm_from_csv(_read_csv(args.datadog))
        src = f"CSV {args.datadog}"
    else:
        dd = _norm_from_secret(args.datadog_secret, args.profile, args.region, args.include_admins)
        src = f"Secrets Manager {args.datadog_secret}" + ("" if args.include_admins else " (attendee orgs only)")

    if len(aws) != len(dd):
        print(f"warn: {len(aws)} AWS rows vs {len(dd)} Datadog accounts from {src} — joining the first "
              f"{min(len(aws), len(dd))} by position; check the pools line up.", file=sys.stderr)

    written = 0
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(V2_HEADER)
        for a, d in zip(aws, dd):
            org = d["org"]
            dash = args.dashboard_url_template.replace("{org}", org) if args.dashboard_url_template else ""
            w.writerow([
                (a.get("name") or "").strip(), (a.get("region") or "").strip(),
                (a.get("access_key") or "").strip(), (a.get("secret_key") or "").strip(),
                (a.get("console_url") or "").strip(),
                org, d["email"], d["password"], d["api_key"], d["app_key"], args.site, dash,
            ])
            written += 1
    print(f"wrote {written} rows to {args.out} (Datadog from {src})", file=sys.stderr)


if __name__ == "__main__":
    main()
