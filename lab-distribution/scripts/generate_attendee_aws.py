# ABOUTME: Generate the AWS half of the attendee pool: one scoped IAM user + access key per cluster,
# ABOUTME: each limited to its own cluster, written to an aws-pool CSV for merge_pool.py. Dry-run by default.
"""Per-attendee AWS credentials.

For each attendee cluster, create a dedicated IAM user with an access key scoped to ONLY that cluster
(eks:DescribeCluster on the cluster ARN, so `aws eks update-kubeconfig` works for theirs and no one
else's), optionally add the EKS access entry that maps the user into the cluster, and write
name,region,access_key,secret_key to an aws-pool CSV. merge_pool.py joins that with the Datadog pool.

This mirrors the single WLee user, scaled per attendee. Secrets are written ONLY to the output CSV
(never stdout), and the CSV is not committed (it holds live keys).

Usage:
    # dry-run (default): show what would be created, create nothing
    uv run --with boto3 python scripts/generate_attendee_aws.py --count 50 --profile accen-dev

    # apply: create the users/keys, write the CSV, and add EKS access entries where the cluster exists
    uv run --with boto3 python scripts/generate_attendee_aws.py --count 50 --profile accen-dev \
        --out ../aws-pool-accen-dev.csv --access-entries --apply

    # or pass explicit cluster names
    uv run --with boto3 python scripts/generate_attendee_aws.py --clusters watch-it-burn-attendee-001,... --apply
"""
from __future__ import annotations

import argparse
import csv
import sys

import boto3
from botocore.exceptions import ClientError

CLUSTER_ADMIN = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"


def cluster_names(args) -> list[str]:
    if args.clusters:
        return [c.strip() for c in args.clusters.split(",") if c.strip()]
    return [f"{args.prefix}-{i:03d}" for i in range(1, args.count + 1)]


def user_for(cluster: str, user_prefix: str) -> str:
    # Short, unique, IAM-legal: the numeric/suffix tail of the cluster name.
    tail = cluster.replace("watch-it-burn-", "")
    return f"{user_prefix}-{tail}"[:64]


def scoped_policy(account: str, region: str, cluster: str) -> str:
    arn = f"arn:aws:eks:{region}:{account}:cluster/{cluster}"
    return (
        '{"Version":"2012-10-17","Statement":['
        f'{{"Sid":"DescribeOwnCluster","Effect":"Allow","Action":["eks:DescribeCluster"],"Resource":"{arn}"}},'
        '{"Sid":"ListClusters","Effect":"Allow","Action":["eks:ListClusters"],"Resource":"*"}]}'
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--count", type=int, help="number of attendee clusters (watch-it-burn-attendee-NNN)")
    g.add_argument("--clusters", help="explicit comma-separated cluster names")
    p.add_argument("--prefix", default="watch-it-burn-attendee", help="name prefix for --count")
    p.add_argument("--user-prefix", default="wib", help="IAM user name prefix")
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--profile", default="accen-dev")
    p.add_argument("--out", default="aws-pool.csv", help="output CSV (name,region,access_key,secret_key)")
    p.add_argument("--access-entries", action="store_true", help="also add EKS cluster access entries")
    p.add_argument("--apply", action="store_true", help="actually create (default is dry-run)")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    account = session.client("sts").get_caller_identity()["Account"]
    iam = session.client("iam")
    eks = session.client("eks")
    clusters = cluster_names(args)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] account={account} region={args.region} clusters={len(clusters)} "
          f"access_entries={args.access_entries} out={args.out}", file=sys.stderr)

    rows: list[dict] = []
    created = skipped = 0
    for c in clusters:
        user = user_for(c, args.user_prefix)
        if not args.apply:
            print(f"  would create IAM user {user} scoped to {c}"
                  + ("  + EKS access entry" if args.access_entries else ""), file=sys.stderr)
            continue
        # IAM user (idempotent).
        try:
            iam.create_user(UserName=user, Tags=[{"Key": "project", "Value": "watch-it-burn"},
                                                 {"Key": "cluster", "Value": c}])
        except iam.exceptions.EntityAlreadyExistsException:
            pass
        iam.put_user_policy(UserName=user, PolicyName="eks-own-cluster",
                            PolicyDocument=scoped_policy(account, args.region, c))
        # One access key; if the user already has the max, skip key creation (do not orphan).
        existing = iam.list_access_keys(UserName=user)["AccessKeyMetadata"]
        if existing:
            print(f"  {user}: already has an access key; not writing a new one to the CSV", file=sys.stderr)
            skipped += 1
        else:
            k = iam.create_access_key(UserName=user)["AccessKey"]
            rows.append({"name": c, "region": args.region,
                         "access_key": k["AccessKeyId"], "secret_key": k["SecretAccessKey"]})
            created += 1
        # EKS access entry so kubectl actually works (not just update-kubeconfig).
        if args.access_entries:
            principal = f"arn:aws:iam::{account}:user/{user}"
            try:
                eks.create_access_entry(clusterName=c, principalArn=principal, type="STANDARD")
                eks.associate_access_policy(clusterName=c, principalArn=principal,
                                            accessScope={"type": "cluster"}, policyArn=CLUSTER_ADMIN)
            except eks.exceptions.ResourceNotFoundException:
                print(f"  {c}: cluster not found yet; skipping access entry (re-run after provisioning)", file=sys.stderr)
            except ClientError as e:
                if "ResourceInUse" not in str(e):
                    print(f"  {c}: access entry error: {e}", file=sys.stderr)

    if args.apply and rows:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["name", "region", "access_key", "secret_key"])
            w.writeheader(); w.writerows(rows)
        print(f"[APPLY] wrote {len(rows)} key(s) to {args.out} (secrets in the file only); "
              f"created={created} skipped={skipped}", file=sys.stderr)
    elif args.apply:
        print(f"[APPLY] no new keys written (created={created} skipped={skipped})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
