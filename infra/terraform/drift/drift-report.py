#!/usr/bin/env python3
# ABOUTME: Plan-only drift report for the fleet's AWS plane: a refresh-only plan of every Terraform state, plus
# ABOUTME: every S3 bucket and EKS cluster an account holds that no state manages and the register does not name.
"""Detects out-of-band change on the AWS plane (#205). Never applies, never locks, never writes a state.

Three questions, each answered from the account itself rather than from memory:

1. **Has anything Terraform manages changed outside Terraform?** `terraform plan -refresh-only
   -detailed-exitcode` against every state the fleet keeps: each cluster under fleet/states/, each account's
   lab VPC (accen-dev's in the network root's default terraform.tfstate, the rest under network/states/), and
   each account's audit root under audit/states/. Exit 2 from a plan is drift.
2. **Does the account hold anything Terraform does not manage?** A plan cannot answer this: a bucket made by
   hand is in no state, so no plan mentions it. That is what driftctl did, and driftctl is in maintenance
   mode, so this lists the account's S3 buckets and EKS clusters directly and subtracts every state and every
   entry in known-unmanaged.yaml. What is left is a finding, with who made it from CloudTrail's event history
   and whether AWS Config has a record of it.
3. **Is the record on?** Every account must have a Config recorder recording AWS::S3::Bucket and
   AWS::EKS::Cluster; without it an out-of-band change leaves nothing behind once it is undone.

Every AWS call carries --profile and --region, and every plan carries -var profile/region, so nothing here
reads a shared default another session may have changed (CLAUDE.md, rule 6).

Exit codes: 0 nothing found; 2 findings; 1 the report is incomplete (a tool, credential or state could not be
read). Incomplete is a failure, never a pass: a drift check that could not look has not found no drift.

Usage:
  python3 infra/terraform/drift/drift-report.py [--accounts p1,p2] [--region us-west-2] [--out report.md]
                                                [--post] [--repo owner/name] [--parallel 4]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import fnmatch
import json
import os
import pathlib
import re
import subprocess
import sys

import yaml

TF_DIR = pathlib.Path(__file__).resolve().parents[1]  # infra/terraform
DEFAULT_ACCOUNTS = "accen-dev,aws1-student31,aws1-student32,aws1-student33,aws1-student34"  # fleet.sh's list
# The account whose lab VPC lives in the network root's DEFAULT state, not states/<acct>.tfstate (fleet.sh).
DEFAULT_ACCOUNT = "accen-dev"
DEFAULT_REPO = "peopleforrester/Unleash_an_Agent_Watch_It_Burn"
ISSUE_TITLE = "Fleet drift report"
REQUIRED_CONFIG_TYPES = ("AWS::S3::Bucket", "AWS::EKS::Cluster")
CONFIG_TYPE = {"s3-bucket": "AWS::S3::Bucket", "eks-cluster": "AWS::EKS::Cluster"}
CREATE_EVENT = {"s3-bucket": "CreateBucket", "eks-cluster": "CreateCluster"}
EXCERPT_LINES = 120


class Incomplete(Exception):
    """A command the report depends on failed; the report cannot claim anything about what it covered."""


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise Incomplete(f"{cmd[0]} is not on PATH") from e


def last_line(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "(no output)"


def aws(profile: str, region: str, *args: str, ok_errors: tuple[str, ...] = ()) -> dict | None:
    """Run one AWS CLI call as JSON. Returns None when stderr carries one of ok_errors (an expected answer such as
    NoSuchTagSet), raises Incomplete on any other failure."""
    p = run(["aws", *args, "--profile", profile, "--region", region, "--output", "json"])
    if p.returncode != 0:
        if any(e in p.stderr for e in ok_errors):
            return None
        raise Incomplete(f"aws {' '.join(args[:2])} ({profile}, {region}): {last_line(p.stderr)}")
    return json.loads(p.stdout) if p.stdout.strip() else {}


# ---------------------------------------------------------------- Terraform state ----------------------------

def load_state(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Incomplete(f"cannot read state {path}: {e}") from e


def managed(state: dict):
    """(type, attributes) for every managed resource instance in a state, modules included."""
    for r in state.get("resources", []):
        if r.get("mode") != "managed":
            continue
        for inst in r.get("instances", []):
            yield r.get("type"), inst.get("attributes") or {}


def outputs(state: dict) -> dict:
    return {k: v.get("value") for k, v in (state.get("outputs") or {}).items()}


@dataclasses.dataclass
class Plan:
    label: str          # what the report calls it, e.g. "cluster watch-it-burn-attendee-001"
    root: pathlib.Path  # the Terraform root to -chdir into
    state: pathlib.Path
    profile: str
    variables: list[tuple[str, str]]
    result: str = ""    # clean | drift | error
    excerpt: str = ""


@dataclasses.dataclass
class Finding:
    account: str
    kind: str
    name: str
    created: str = ""
    creator: str = ""
    in_config: str = ""
    entry: str = ""     # for a known one: which register entry it matched


class Report:
    def __init__(self, accounts: list[str], region: str):
        self.accounts = accounts
        self.region = region
        self.errors: list[str] = []
        self.plans: list[Plan] = []
        self.unmanaged: list[Finding] = []
        self.known: list[Finding] = []
        self.config: dict[str, str] = {}   # account -> "ok: ..." or the problem
        self.config_ok: dict[str, bool] = {}
        self.notes: list[str] = []

    @property
    def drifted(self) -> list[Plan]:
        return [p for p in self.plans if p.result == "drift"]

    @property
    def findings(self) -> int:
        return len(self.drifted) + len(self.unmanaged) + sum(1 for ok in self.config_ok.values() if not ok)

    def exit_code(self) -> int:
        if self.errors:
            return 1
        return 2 if self.findings else 0


def network_state(network: pathlib.Path, profile: str) -> pathlib.Path:
    return network / ("terraform.tfstate" if profile == DEFAULT_ACCOUNT else f"states/{profile}.tfstate")


def collect_plans(rep: Report, tf_dir: pathlib.Path, fleet_states: pathlib.Path, ids: dict[str, str],
                  managed_names: dict[str, set[tuple[str, str]]]) -> None:
    """Find every state, work out which account it is in, and record what it manages."""
    network, cluster, audit = tf_dir / "aws/network", tf_dir / "aws/cluster", tf_dir / "aws/audit"
    profile_of = {acct_id: prof for prof, acct_id in ids.items()}

    def remember(profile: str, state: dict) -> None:
        for rtype, attrs in managed(state):
            if rtype == "aws_s3_bucket" and attrs.get("bucket"):
                managed_names[profile].add(("s3-bucket", attrs["bucket"]))
            elif rtype == "aws_eks_cluster" and attrs.get("name"):
                managed_names[profile].add(("eks-cluster", attrs["name"]))

    vpc: dict[str, dict] = {}
    for prof in rep.accounts:
        st = network_state(network, prof)
        if not st.is_file():
            rep.notes.append(f"{prof}: no lab VPC state ({st.relative_to(tf_dir)}), so no clusters can be built there")
            continue
        state = load_state(st)
        remember(prof, state)
        vpc[prof] = outputs(state)
        rep.plans.append(Plan(f"lab VPC {prof}", network, st, prof, [("profile", prof), ("region", rep.region)]))

        ast = audit / f"states/{prof}.tfstate"
        if ast.is_file():
            state = load_state(ast)
            remember(prof, state)
            rep.plans.append(Plan(f"audit {prof}", audit, ast, prof, [("profile", prof), ("region", rep.region)]))
        else:
            rep.notes.append(f"{prof}: audit root not applied here ({ast.relative_to(tf_dir)} missing)")

    for st in sorted(fleet_states.glob("*.tfstate")):
        name = st.stem
        state = load_state(st)
        arns = [a.get("arn", "") for t, a in managed(state) if t == "aws_eks_cluster"]
        if not arns:
            rep.notes.append(f"cluster {name}: state holds no EKS cluster (an emptied state), nothing to plan")
            continue
        m = re.match(r"arn:[^:]+:eks:([^:]+):(\d+):cluster/", arns[0])
        if not m:
            raise Incomplete(f"cluster {name}: cannot parse the EKS ARN in its state: {arns[0]!r}")
        region, acct_id = m.groups()
        prof = profile_of.get(acct_id)
        if prof is None:
            raise Incomplete(f"cluster {name}: its state is in account {acct_id}, which none of the profiles "
                             f"{','.join(rep.accounts)} reaches; pass that account's profile in --accounts")
        recorded = st.with_suffix(".account")
        if recorded.is_file() and recorded.read_text().strip() not in ("", prof):
            raise Incomplete(f"cluster {name}: {recorded.name} says {recorded.read_text().strip()} but its state "
                             f"is in {prof} ({acct_id})")
        if prof not in vpc:
            raise Incomplete(f"cluster {name} is in {prof}, which has no lab VPC state to read vpc_id from")
        subnets = vpc[prof].get("private_subnet_ids")
        if not vpc[prof].get("vpc_id") or not subnets:
            raise Incomplete(f"lab VPC state for {prof} has no vpc_id / private_subnet_ids outputs")
        remember(prof, state)
        rep.plans.append(Plan(f"cluster {name}", cluster, st, prof, [
            ("name", name), ("profile", prof), ("region", region),
            ("vpc_id", vpc[prof]["vpc_id"]), ("private_subnet_ids", json.dumps(subnets)),
        ]))


def run_plan(p: Plan) -> Plan:
    cmd = ["terraform", f"-chdir={p.root}", "plan", "-refresh-only", "-detailed-exitcode", "-lock=false",
           "-input=false", "-no-color", f"-state={p.state}"]
    for k, v in p.variables:
        cmd += ["-var", f"{k}={v}"]
    proc = run(cmd)
    if proc.returncode == 0:
        p.result = "clean"
    elif proc.returncode == 2:
        p.result = "drift"
        out = proc.stdout.splitlines()
        start = next((i for i, ln in enumerate(out) if "changed outside of Terraform" in ln), 0)
        p.excerpt = "\n".join(out[start:start + EXCERPT_LINES])
    else:
        p.result = "error"
        p.excerpt = last_line(proc.stderr or proc.stdout)
    return p


# ---------------------------------------------------------------- live inventory -----------------------------

def load_register(path: pathlib.Path) -> list[dict]:
    try:
        entries = (yaml.safe_load(path.read_text()) or {}).get("entries") or []
    except (OSError, yaml.YAMLError) as e:
        raise Incomplete(f"cannot read the register {path}: {e}") from e
    for e in entries:
        if e.get("kind") not in CONFIG_TYPE or bool(e.get("name")) == bool(e.get("tag")) or not e.get("accounts"):
            raise Incomplete(f"register entry {e!r} needs a kind ({'/'.join(CONFIG_TYPE)}), accounts, "
                             "and exactly one of name or tag")
    return entries


def bucket_tags(profile: str, region: str, name: str) -> dict:
    got = aws(profile, region, "s3api", "get-bucket-tagging", "--bucket", name, ok_errors=("NoSuchTagSet",))
    return {t["Key"]: t["Value"] for t in (got or {}).get("TagSet", [])}


def cluster_detail(profile: str, region: str, name: str) -> dict:
    return (aws(profile, region, "eks", "describe-cluster", "--name", name) or {}).get("cluster", {})


def bucket_region(profile: str, region: str, name: str) -> str:
    loc = (aws(profile, region, "s3api", "get-bucket-location", "--bucket", name) or {}).get("LocationConstraint")
    return {None: "us-east-1", "": "us-east-1", "EU": "eu-west-1"}.get(loc, loc)


def match_register(entries: list[dict], profile: str, kind: str, name: str, tags) -> str:
    """The `made_by` of the first register entry this resource matches, or "". `tags` is called only when a
    tag entry could apply, so an account with no tag entries costs no tag lookups."""
    for e in entries:
        if e["kind"] != kind or not ("*" in e["accounts"] or profile in e["accounts"]):
            continue
        if e.get("name") and fnmatch.fnmatchcase(name, e["name"]):
            return e.get("made_by", e["name"])
        if e.get("tag") and all(tags().get(k) == str(v) for k, v in e["tag"].items()):
            return e.get("made_by", str(e["tag"]))
    return ""


def creator(profile: str, region: str, kind: str, name: str) -> str:
    got = aws(profile, region, "cloudtrail", "lookup-events", "--lookup-attributes",
              f"AttributeKey=ResourceName,AttributeValue={name}", "--max-items", "50") or {}
    for ev in got.get("Events", []):
        if ev.get("EventName") != CREATE_EVENT[kind]:
            continue
        who = ev.get("Username", "")
        try:
            who = json.loads(ev.get("CloudTrailEvent", "{}")).get("userIdentity", {}).get("arn", who)
        except ValueError:
            pass
        return f"{who} at {ev.get('EventTime', '?')}"
    return f"no {CREATE_EVENT[kind]} event in {region}'s 90-day event history"


def config_has(profile: str, region: str, kind: str, name: str) -> str:
    got = aws(profile, region, "configservice", "get-resource-config-history", "--resource-type",
              CONFIG_TYPE[kind], "--resource-id", name, "--limit", "1",
              ok_errors=("ResourceNotDiscoveredException",))
    items = (got or {}).get("configurationItems", [])
    return f"recorded {items[0].get('configurationItemCaptureTime', '')}".strip() if items else "NOT recorded"


def check_config(rep: Report, profile: str) -> None:
    recs = (aws(profile, rep.region, "configservice", "describe-configuration-recorders") or {}).get(
        "ConfigurationRecorders", [])
    status = {s.get("name"): s for s in (aws(profile, rep.region, "configservice",
                                             "describe-configuration-recorder-status") or {}).get(
        "ConfigurationRecordersStatus", [])}
    for r in recs:
        grp = r.get("recordingGroup", {})
        covers = grp.get("allSupported") or set(REQUIRED_CONFIG_TYPES) <= set(grp.get("resourceTypes", []))
        if covers and status.get(r.get("name"), {}).get("recording"):
            rep.config[profile] = f"ok: recorder {r.get('name')} is recording"
            rep.config_ok[profile] = True
            return
    rep.config_ok[profile] = False
    if not recs:
        rep.config[profile] = f"NO recorder in {rep.region}: apply infra/terraform/aws/audit for this account"
    else:
        rep.config[profile] = (f"no recorder in {rep.region} is both recording and covering "
                               f"{', '.join(REQUIRED_CONFIG_TYPES)} (have: {', '.join(r.get('name', '?') for r in recs)})")


def inventory(rep: Report, profile: str, register: list[dict], managed_names: set[tuple[str, str]]) -> None:
    region = rep.region
    live: list[tuple[str, str, str]] = []  # kind, name, created
    for b in (aws(profile, region, "s3api", "list-buckets") or {}).get("Buckets", []):
        live.append(("s3-bucket", b["Name"], str(b.get("CreationDate", ""))))
    for c in (aws(profile, region, "eks", "list-clusters") or {}).get("clusters", []):
        live.append(("eks-cluster", c, ""))

    for kind, name, created in live:
        if (kind, name) in managed_names:
            continue
        cache: dict = {}

        def tags(kind=kind, name=name, cache=cache) -> dict:
            if "tags" not in cache:
                if kind == "s3-bucket":
                    cache["tags"] = bucket_tags(profile, region, name)
                else:
                    cache["detail"] = cluster_detail(profile, region, name)
                    cache["tags"] = cache["detail"].get("tags") or {}
            return cache["tags"]

        entry = match_register(register, profile, kind, name, tags)
        f = Finding(profile, kind, name, created=created, entry=entry)
        if entry:
            rep.known.append(f)
            continue
        where = bucket_region(profile, region, name) if kind == "s3-bucket" else region
        if kind == "eks-cluster":
            detail = cache["detail"] if "detail" in cache else cluster_detail(profile, region, name)
            f.created = str(detail.get("createdAt", ""))
        f.creator = creator(profile, where, kind, name)
        # Config records a bucket in the bucket's own region; a recorder here cannot have seen one elsewhere.
        f.in_config = (config_has(profile, region, kind, name) if where == region
                       else f"in {where}; the recorder is in {region}")
        rep.unmanaged.append(f)


# ---------------------------------------------------------------- output -------------------------------------

def render(rep: Report, now: str) -> str:
    out = [f"# {ISSUE_TITLE}, {now}", "",
           f"Accounts: {', '.join(rep.accounts)}. Region: {rep.region}. Plan-only: `terraform plan -refresh-only`, "
           "nothing applied. Written by `infra/terraform/drift/drift-report.py`; how to read it is in "
           "`docs/floor.md`.", ""]
    if rep.errors:
        out += ["## INCOMPLETE: these could not be read, so this report proves nothing about them", ""]
        out += [f"- {e}" for e in rep.errors] + [""]
    out += [f"**{rep.findings} finding(s)**: {len(rep.drifted)} drifted state(s), {len(rep.unmanaged)} unmanaged "
            f"resource(s), {sum(1 for ok in rep.config_ok.values() if not ok)} account(s) without a Config record.", ""]

    out += ["## Terraform drift", ""]
    if rep.drifted:
        for p in rep.drifted:
            out += [f"### {p.label} ({p.profile})", "", "```", p.excerpt, "```", ""]
    else:
        out += ["No state has drifted." if not rep.errors else "No drift in the states that could be planned.", ""]

    out += ["## Unmanaged: in the account, in no Terraform state, not in the register", ""]
    if rep.unmanaged:
        out += ["| account | kind | name | created | created by (CloudTrail) | AWS Config |", "|---|---|---|---|---|---|"]
        out += [f"| {f.account} | {f.kind} | `{f.name}` | {f.created} | {f.creator} | {f.in_config} |"
                for f in rep.unmanaged]
        out += ["", "Each of these is either removed, brought into Terraform, or added to "
                "`infra/terraform/drift/known-unmanaged.yaml` with who made it and why.", ""]
    else:
        out += ["None.", ""]

    out += ["## AWS Config", ""]
    out += [f"- {a}: {msg}" for a, msg in rep.config.items()] or ["(not checked)"]
    out += [""]

    if rep.known:
        out += ["## Known unmanaged (in the register)", ""]
        out += [f"- {f.account} {f.kind} `{f.name}`: {f.entry}" for f in rep.known] + [""]
    clean = [p for p in rep.plans if p.result == "clean"]
    if clean:
        out += [f"## Clean states ({len(clean)})", "", ", ".join(p.label for p in clean), ""]
    if rep.notes:
        out += ["## Notes", ""] + [f"- {n}" for n in rep.notes] + [""]
    return "\n".join(out)


def post(repo: str, body: str, code: int) -> None:
    """One open issue carries the running record: comment on it if it is open, open it if not. A clean day is
    posted only when an issue is open, so the last word on an open issue is never a stale finding."""
    p = run(["gh", "issue", "list", "-R", repo, "--state", "open", "--search", f'in:title "{ISSUE_TITLE}"',
             "--json", "number,title"])
    if p.returncode != 0:
        raise Incomplete(f"gh issue list: {last_line(p.stderr)}")
    numbers = [i["number"] for i in json.loads(p.stdout or "[]") if i.get("title") == ISSUE_TITLE]
    if numbers:
        cmd = ["gh", "issue", "comment", str(numbers[0]), "-R", repo, "--body-file", "-"]
    elif code == 0:
        return
    else:
        cmd = ["gh", "issue", "create", "-R", repo, "--title", ISSUE_TITLE, "--body-file", "-"]
    q = subprocess.run(cmd, input=body, capture_output=True, text=True)
    if q.returncode != 0:
        raise Incomplete(f"{' '.join(cmd[:3])}: {last_line(q.stderr)}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--accounts", default=os.environ.get("WIB_ATTENDEE_ACCOUNTS", DEFAULT_ACCOUNTS))
    ap.add_argument("--region", default=os.environ.get("WIB_REGION", "us-west-2"))
    ap.add_argument("--tf-dir", type=pathlib.Path, default=TF_DIR, help="the infra/terraform tree")
    ap.add_argument("--states", type=pathlib.Path, default=None,
                    help="cluster states (default: $WIB_STATE_DIR or <tf-dir>/fleet/states, as fleet.sh)")
    ap.add_argument("--register", type=pathlib.Path, default=None,
                    help="default: <tf-dir>/drift/known-unmanaged.yaml")
    ap.add_argument("--out", type=pathlib.Path, help="also write the report here")
    ap.add_argument("--post", action="store_true", help=f"comment on (or open) the '{ISSUE_TITLE}' issue")
    ap.add_argument("--repo", default=os.environ.get("WIB_DRIFT_REPO", DEFAULT_REPO))
    ap.add_argument("--parallel", type=int, default=4)
    args = ap.parse_args(argv)

    accounts = [a for a in args.accounts.split(",") if a]
    states = args.states or pathlib.Path(os.environ.get("WIB_STATE_DIR") or args.tf_dir / "fleet/states")
    register_path = args.register or args.tf_dir / "drift/known-unmanaged.yaml"
    rep = Report(accounts, args.region)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")

    try:
        register = load_register(register_path)
        ids: dict[str, str] = {}
        for prof in accounts:
            ids[prof] = (aws(prof, args.region, "sts", "get-caller-identity") or {}).get("Account", "")
            if not ids[prof]:
                raise Incomplete(f"sts get-caller-identity ({prof}) returned no account")
        managed_names: dict[str, set] = {prof: set() for prof in accounts}
        collect_plans(rep, args.tf_dir, states, ids, managed_names)
    except Incomplete as e:
        # Without the account map or the state inventory nothing below means anything. Not posted: the issue
        # records the fleet's drift, and this run never reached the fleet. The exit code and the copy say so.
        rep.errors.append(str(e))
        body = render(rep, now)
        print(body)
        if args.out:
            args.out.write_text(body + "\n")
        return 1

    for root in sorted({p.root for p in rep.plans}):
        init = run(["terraform", f"-chdir={root}", "init", "-input=false", "-no-color"])
        if init.returncode != 0:
            rep.errors.append(f"terraform init in {root.relative_to(args.tf_dir)}: {last_line(init.stderr)}")
    if not rep.errors:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            list(pool.map(run_plan, rep.plans))
        rep.errors += [f"plan {p.label}: {p.excerpt}" for p in rep.plans if p.result == "error"]

    for prof in accounts:
        try:
            check_config(rep, prof)
            inventory(rep, prof, register, managed_names[prof])
        except Incomplete as e:
            rep.errors.append(str(e))

    body = render(rep, now)
    code = rep.exit_code()
    print(body)
    if args.out:
        args.out.write_text(body + "\n")
    if args.post:
        try:
            post(args.repo, body, code)
        except Incomplete as e:
            print(f"POST FAILED: {e}", file=sys.stderr)
            return 1
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
