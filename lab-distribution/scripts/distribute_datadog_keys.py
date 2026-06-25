#!/usr/bin/env python3
# ABOUTME: Loads each attendee's Datadog account (from the assembled pool) into THEIR AWS account's
# ABOUTME: Secrets Manager as watch-it-burn/datadog, so the in-cluster ESO syncs it to datadog-secret.
#
# This is the missing half of "distribute Datadog accounts to each cluster". The pool (pool.csv) already
# pairs each cluster with its AWS creds + its Datadog org keys. The in-cluster consumer chain is already
# live: ClusterSecretStore (Pod Identity) -> ExternalSecret -> datadog-secret -> Collector / Datadog Agent.
# The one piece with no automation was writing each cluster's assigned Datadog keys into that cluster's
# AWS Secrets Manager. This script does exactly that, per row, idempotently.
#
# The Secrets Manager value shape is fixed by gitops/manifests/datadog/datadog-eso.yaml:
#   secret name  : watch-it-burn/datadog   (within the ESO role's secret:watch-it-burn/* scope)
#   secret value : {"api-key": "<datadog_api_key>", "app-key": "<datadog_app_key>"}   (ESO reads .property)
#
# Safety:
#   - DRY RUN by default. Pass --apply to actually write. (Writing real keys to N AWS accounts is a
#     mutation; it never happens implicitly.)
#   - Reads the pool read-only. Never modifies pool.csv.
#   - NEVER prints key values (Datadog api/app keys or AWS keys). Only non-secret identifiers.
#   - Each row uses its OWN AWS creds via an isolated boto3 Session (no shared/default credentials).
#   - Fails explicitly: a row that errors is reported and counted; the script exits non-zero if any failed.
#
# Usage:
#   uv run --with boto3 python scripts/distribute_datadog_keys.py --pool /path/to/pool.csv            # dry run
#   uv run --with boto3 python scripts/distribute_datadog_keys.py --pool /path/to/pool.csv --apply     # write
#   uv run --with boto3 python scripts/distribute_datadog_keys.py --pool ... --only watch-it-burn-attendee-003
import argparse
import csv
import json
import sys

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
except ImportError:
    sys.exit("boto3 is required. Run with: uv run --with boto3 python scripts/distribute_datadog_keys.py ...")

SECRET_NAME = "watch-it-burn/datadog"
REQUIRED_COLS = ("name", "region", "access_key", "secret_key", "datadog_api_key", "datadog_app_key")


def parse_args():
    p = argparse.ArgumentParser(description="Load per-cluster Datadog keys into each AWS account's Secrets Manager.")
    p.add_argument("--pool", required=True, help="Path to the assembled pool.csv (read-only; never modified).")
    p.add_argument("--secret-name", default=SECRET_NAME, help=f"Secrets Manager name (default: {SECRET_NAME}).")
    p.add_argument("--only", help="Only process the row whose `name` equals this cluster name.")
    p.add_argument("--apply", action="store_true", help="Actually write. Without this flag the script is a dry run.")
    return p.parse_args()


def load_rows(path, only):
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLS if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"pool {path} is missing required columns: {', '.join(missing)}")
        rows = [r for r in reader if not only or r.get("name") == only]
    if only and not rows:
        sys.exit(f"no row with name == {only!r} in {path}")
    return rows


def put_keys(row, secret_name, apply):
    """Write {api-key, app-key} to secret_name in this row's AWS account. Returns a short status string."""
    region = row["region"].strip()
    session = boto3.session.Session(
        aws_access_key_id=row["access_key"].strip(),
        aws_secret_access_key=row["secret_key"].strip(),
        region_name=region,
    )
    # Confirm which account these creds resolve to (non-secret; helps catch a mis-joined row).
    account = session.client("sts").get_caller_identity()["Account"]
    payload = json.dumps({"api-key": row["datadog_api_key"].strip(), "app-key": row["datadog_app_key"].strip()})

    if not apply:
        return f"DRY-RUN would write {secret_name} in account {account} ({region})"

    sm = session.client("secretsmanager")
    try:
        sm.describe_secret(SecretId=secret_name)
        sm.put_secret_value(SecretId=secret_name, SecretString=payload)
        return f"updated {secret_name} in account {account} ({region})"
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            sm.create_secret(Name=secret_name, SecretString=payload)
            return f"created {secret_name} in account {account} ({region})"
        raise


def main():
    args = parse_args()
    rows = load_rows(args.pool, args.only)
    total = len(rows)
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"== Datadog account distribution [{mode}] == {total} pool row(s) from {args.pool}\n")

    written = skipped = failed = 0
    for i, row in enumerate(rows, 1):
        name = row.get("name", "?")
        pct = int(i / total * 100)
        if not row.get("datadog_api_key", "").strip() or not row.get("datadog_app_key", "").strip():
            skipped += 1
            print(f"[{i}/{total} {pct:3d}%] {name}: SKIP (no datadog keys in this row)")
            continue
        try:
            status = put_keys(row, args.secret_name, args.apply)
            written += 1
            print(f"[{i}/{total} {pct:3d}%] {name}: {status}")
        except (ClientError, BotoCoreError) as exc:
            failed += 1
            print(f"[{i}/{total} {pct:3d}%] {name}: FAILED ({type(exc).__name__}: {exc})")

    print(f"\nSummary: {written} written, {skipped} skipped (no keys), {failed} failed.")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write the keys.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
