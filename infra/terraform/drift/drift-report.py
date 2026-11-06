#!/usr/bin/env python3
# ABOUTME: Plan-only drift report for the fleet's AWS plane: a refresh-only plan of every Terraform state, plus
# ABOUTME: every S3 bucket and EKS cluster an account holds that no state manages and the register does not name.
"""Detects out-of-band change on the AWS plane (#205). Never applies, never locks, never writes a state.

Three questions, each answered from the account itself rather than from memory:

1. **Has anything Terraform manages changed outside Terraform?** `terraform plan -refresh-only` against every
   state the fleet keeps: each cluster under fleet/states/, each account's lab VPC (the default account's in the
   network root's own terraform.tfstate, the rest under network/states/, and one per account and region outside
   the home region as network/states/<profile>.<region>.tfstate, where #643's standbys build), each account's
   permissions boundary
   under infra/org/boundary/states/ and each account's audit root under aws/audit/states/. A refresh-only plan
   reads every object in the state from AWS and compares it with the state; the objects that differ are the
   plan's `resource_drift`, and that list is the finding. It does not depend on the configuration's variables,
   which only have to make the configuration valid, so each plan is given the ones its root requires, read from
   the tags the root put on its own resources (event, hostname, role), never a guess.
2. **Does the account hold anything Terraform does not manage?** A plan cannot answer this: a bucket made by
   hand is in no state, so no plan mentions it. That is what driftctl did, and driftctl is in maintenance
   mode, so this lists the account's S3 buckets and EKS clusters directly and subtracts every state and every
   entry in known-unmanaged.yaml. Buckets are listed account-wide; clusters in every region the fleet builds in
   (the home region, every region in fleet/backups.tsv, every regional lab VPC state and every cluster state's). What is left is a finding, with who made it from CloudTrail's event history
   and whether AWS Config has a record of it.
3. **Is the record on?** Every account must have a Config recorder in the home region recording AWS::S3::Bucket
   and AWS::EKS::Cluster; without it an out-of-band change leaves nothing behind once it is undone. Config is
   regional and the recorder is in the home region only, so a resource in a standby region is reported as
   outside it; the trail is multi-region, so CloudTrail still names who made it. An account with no recorder
   and no permissions boundary is told to apply the boundary root first, because the audit root needs it.

Every AWS call carries --profile and --region, and every plan carries -var profile/region, so nothing here
reads a shared default another session may have changed (CLAUDE.md, rule 6). The account list and the default
account are read from fleet.sh, so the report covers the accounts the fleet builds in.

Exit codes: 0 nothing found; 2 findings; 1 the report is incomplete (a tool, credential or state could not be
read). Incomplete is a failure, never a pass: a drift check that could not look has not found no drift.

Usage:
  python3 infra/terraform/drift/drift-report.py [--accounts p1,p2] [--region us-west-2] [--out report.md]
                                                [--backups fleet/backups.tsv]
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
import tempfile

import yaml

TF_DIR = pathlib.Path(__file__).resolve().parents[1]  # infra/terraform
DEFAULT_REPO = "peopleforrester/Unleash_an_Agent_Watch_It_Burn"
ISSUE_TITLE = "Fleet drift report"
REQUIRED_CONFIG_TYPES = ("AWS::S3::Bucket", "AWS::EKS::Cluster")
# infra/org/boundary's policy name, which aws/audit (and aws/cluster) look up with data "aws_iam_policy".
BOUNDARY_POLICY = "watch-it-burn-permissions-boundary"
CONFIG_TYPE = {"s3-bucket": "AWS::S3::Bucket", "eks-cluster": "AWS::EKS::Cluster"}
CREATE_EVENT = {"s3-bucket": "CreateBucket", "eks-cluster": "CreateCluster"}
# The tags aws/cluster puts on every resource (local.fleet_tags) that are also variables with no default.
CLUSTER_TAG_VARS = ("event", "hostname", "role")
EXCERPT_LINES = 120
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d+$")


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


def fleet_setting(fleet_sh: pathlib.Path, var: str) -> str:
    """The default fleet.sh gives one of its WIB_ settings, so this report and the fleet name the same accounts."""
    try:
        text = fleet_sh.read_text(encoding="utf-8")
    except OSError as e:
        raise Incomplete(f"cannot read {fleet_sh} for {var}: {e}") from e
    m = re.search(rf'^{var}="\$\{{{var}:-([^}}]*)\}}"$', text, re.M)
    if not m or not m.group(1):
        raise Incomplete(f"{fleet_sh} has no {var}=\"${{{var}:-...}}\" default to read")
    return m.group(1)


def backup_regions(path: pathlib.Path) -> set[str]:
    """The regions backups.tsv builds standbys in (#643, `name|role|region|wave|zone`). Read even when no standby is
    up, so a cluster left behind in one of those regions after its state was removed is still swept."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise Incomplete(f"cannot read {path} for the standby regions: {e}") from e
    regions = set()
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        fields = ln.split("|")
        if len(fields) < 3 or not REGION_RE.match(fields[2].strip()):
            raise Incomplete(f"{path}: cannot read a region from {ln!r}")
        regions.add(fields[2].strip())
    return regions


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


def state_tag(state: dict, key: str, label: str, rtype: str | None = None) -> str:
    """The one value a state's resources carry for tag `key` (in tags_all, which holds default_tags too). More than
    one value, or none, is not something to guess past."""
    seen = {(a.get("tags_all") or a.get("tags") or {}).get(key) for t, a in managed(state) if rtype in (None, t)}
    seen.discard(None)
    if len(seen) != 1:
        raise Incomplete(f"{label}: its state's resources carry {'no' if not seen else 'several'} `{key}` tag"
                         + (f" values {sorted(seen)}" if seen else "") + ", so the plan cannot be given -var "
                         f"{key}= as it was applied")
    return seen.pop()


def hop_limit(state: dict) -> str | None:
    """The node IMDS hop limit a cluster was built with (#113), from its launch template, so the plan states it."""
    for t, a in managed(state):
        if t == "aws_launch_template":
            for mo in a.get("metadata_options") or []:
                if mo.get("http_put_response_hop_limit"):
                    return str(mo["http_put_response_hop_limit"])
    return None


@dataclasses.dataclass
class Plan:
    label: str          # what the report calls it, e.g. "cluster watch-it-burn-attendee-001"
    root: pathlib.Path  # the Terraform root to -chdir into
    state: pathlib.Path
    profile: str
    variables: list[tuple[str, str]]
    result: str = ""    # clean | drift | error
    drifted: list[str] = dataclasses.field(default_factory=list)  # resource_drift addresses and actions
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
        self.region = region  # the home region: the Config recorder's, and the default lab VPCs'
        self.regions: set[str] = {region}  # every region whose EKS clusters are swept
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


def collect_plans(rep: Report, tf_dir: pathlib.Path, org_dir: pathlib.Path, fleet_states: pathlib.Path,
                  default_account: str, ids: dict[str, str], managed_names: dict[str, set[tuple[str, str]]]) -> None:
    """Find every state, work out which account it is in, and record what it manages."""
    network, cluster, audit, boundary = tf_dir / "aws/network", tf_dir / "aws/cluster", tf_dir / "aws/audit", org_dir / "boundary"
    profile_of = {acct_id: prof for prof, acct_id in ids.items()}

    def remember(profile: str, state: dict) -> None:
        for rtype, attrs in managed(state):
            if rtype == "aws_s3_bucket" and attrs.get("bucket"):
                managed_names[profile].add(("s3-bucket", attrs["bucket"]))
            elif rtype == "aws_eks_cluster" and attrs.get("name"):
                managed_names[profile].add(("eks-cluster", attrs["name"]))

    def account_root(label: str, root: pathlib.Path, st: pathlib.Path, prof: str, region: str) -> dict:
        state = load_state(st)
        remember(prof, state)
        rep.plans.append(Plan(f"{label} {prof}", root, st, prof, [
            ("profile", prof), ("region", region), ("event", state_tag(state, "event", f"{label} {prof}"))]))
        return state

    vpc: dict[tuple[str, str], dict] = {}  # (profile, region) -> the lab VPC state's outputs
    for prof in rep.accounts:
        st = network / ("terraform.tfstate" if prof == default_account else f"states/{prof}.tfstate")
        if st.is_file():
            vpc[(prof, rep.region)] = outputs(account_root("lab VPC", network, st, prof, rep.region))
        else:
            rep.notes.append(f"{prof}: no lab VPC state ({st}), so no clusters can be built there")
        # Outside the home region every account, the default one included, keeps one lab VPC state per region
        # (fleet.sh lab_vpc_state_for, #643).
        for st in sorted((network / "states").glob(f"{prof}.*.tfstate")):
            region = st.name[len(prof) + 1:-len(".tfstate")]
            if not REGION_RE.match(region):
                raise Incomplete(f"lab VPC state {st.name}: {region!r} is not a region")
            vpc[(prof, region)] = outputs(account_root(f"lab VPC {region}", network, st, prof, region))
            rep.regions.add(region)
        for label, root in (("boundary", boundary), ("audit", audit)):
            st = root / f"states/{prof}.tfstate"
            if st.is_file():
                account_root(label, root, st, prof, rep.region)
            else:
                rep.notes.append(f"{prof}: {label} root not applied from here ({st} missing)")

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
        recorded = st.with_suffix(".account")  # fleet.sh's record_membership
        if recorded.is_file() and recorded.read_text().strip() not in ("", prof):
            raise Incomplete(f"cluster {name}: {recorded.name} says {recorded.read_text().strip()} but its state "
                             f"is in {prof} ({acct_id})")
        rep.regions.add(region)
        # A standby (#643) is planned against its own region's lab VPC, never the home region's.
        lab = vpc.get((prof, region))
        if lab is None:
            raise Incomplete(f"cluster {name} is in {prof} {region}, which has no lab VPC state to read vpc_id from")
        subnets = lab.get("private_subnet_ids")
        if not lab.get("vpc_id") or not subnets:
            raise Incomplete(f"lab VPC state for {prof} {region} has no vpc_id / private_subnet_ids outputs")
        remember(prof, state)
        variables = [("name", name), ("profile", prof), ("region", region),
                     ("vpc_id", lab["vpc_id"]), ("private_subnet_ids", json.dumps(subnets))]
        variables += [(k, state_tag(state, k, f"cluster {name}", "aws_eks_cluster")) for k in CLUSTER_TAG_VARS]
        hop = hop_limit(state)
        if hop:
            variables.append(("imds_hop_limit", hop))
        rep.plans.append(Plan(f"cluster {name}", cluster, st, prof, variables))


def run_plan(p: Plan) -> Plan:
    with tempfile.TemporaryDirectory(prefix="wib-drift-") as tmp:
        out = pathlib.Path(tmp) / "refresh.tfplan"
        cmd = ["terraform", f"-chdir={p.root}", "plan", "-refresh-only", "-lock=false", "-input=false", "-no-color",
               f"-state={p.state.resolve()}", f"-out={out}"]
        for k, v in p.variables:
            cmd += ["-var", f"{k}={v}"]
        proc = run(cmd)
        if proc.returncode != 0:
            p.result, p.excerpt = "error", last_line(proc.stderr or proc.stdout)
            return p
        show = run(["terraform", f"-chdir={p.root}", "show", "-json", str(out)])
        if show.returncode != 0:
            p.result, p.excerpt = "error", f"terraform show: {last_line(show.stderr)}"
            return p
    try:
        drift = json.loads(show.stdout).get("resource_drift") or []
    except ValueError:
        p.result, p.excerpt = "error", "terraform show -json gave no JSON"
        return p
    p.drifted = [f"{d.get('address')} ({'/'.join(d.get('change', {}).get('actions', []))})" for d in drift
                 if d.get("change", {}).get("actions") not in (None, ["no-op"])]
    if not p.drifted:
        p.result = "clean"
        return p
    p.result = "drift"
    lines = proc.stdout.splitlines()
    start = next((i for i, ln in enumerate(lines) if "changed outside of Terraform" in ln), 0)
    p.excerpt = "\n".join(lines[start:start + EXCERPT_LINES])
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


# (profile, region, event name) -> that event's history, newest first. One lookup serves every unmanaged resource.
_CREATE_EVENTS: dict[tuple[str, str, str], list[dict]] = {}


def creator(profile: str, region: str, kind: str, name: str) -> str:
    """Who made `name`, from the newest successful create event for it in the region's 90-day event history.

    Looked up by event name and matched on the resource, not looked up by resource name: a cluster's history by
    name is its pod identity calls, dozens an hour, so its CreateCluster is past any page of it within a day
    (seen live on 2026-11-05: the newest 50 events for watch-it-burn-community were all AssumeRoleForPodIdentity).
    Every page of the create events is read; a refused call (an errorCode) made nothing and is not the creator."""
    event = CREATE_EVENT[kind]
    key = (profile, region, event)
    if key not in _CREATE_EVENTS:
        _CREATE_EVENTS[key] = (aws(profile, region, "cloudtrail", "lookup-events", "--lookup-attributes",
                                   f"AttributeKey=EventName,AttributeValue={event}") or {}).get("Events", [])
    for ev in _CREATE_EVENTS[key]:
        try:
            body = json.loads(ev.get("CloudTrailEvent") or "{}")
        except ValueError:
            body = {}
        params = body.get("requestParameters") or {}
        names = {r.get("ResourceName") for r in ev.get("Resources") or []} | {params.get("bucketName"),
                                                                             params.get("name")}
        if name not in names or body.get("errorCode"):
            continue
        who = (body.get("userIdentity") or {}).get("arn") or ev.get("Username", "")
        return f"{who} at {ev.get('EventTime', '?')}"
    return f"no {event} event in {region}'s 90-day event history"


def config_has(profile: str, region: str, kind: str, name: str) -> str:
    got = aws(profile, region, "configservice", "get-resource-config-history", "--resource-type",
              CONFIG_TYPE[kind], "--resource-id", name, "--limit", "1",
              ok_errors=("ResourceNotDiscoveredException",))
    items = (got or {}).get("configurationItems", [])
    return f"recorded {items[0].get('configurationItemCaptureTime', '')}".strip() if items else "NOT recorded"


def has_boundary(profile: str, region: str, account_id: str) -> bool:
    """Whether infra/org/boundary's policy is in the account. The audit root looks it up by name, so in an account
    without it the apply the report would name fails at plan (#981: aws1-student31 to 34 on 2026-11-06)."""
    arn = f"arn:aws:iam::{account_id}:policy/{BOUNDARY_POLICY}"
    return aws(profile, region, "iam", "get-policy", "--policy-arn", arn, ok_errors=("NoSuchEntity",)) is not None


def check_config(rep: Report, profile: str, account_id: str) -> None:
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
    if not recs and not has_boundary(profile, rep.region, account_id):
        rep.config[profile] = (f"NO recorder in {rep.region}, and no {BOUNDARY_POLICY}: apply infra/org/boundary, "
                               "then infra/terraform/aws/audit, for this account")
    elif not recs:
        rep.config[profile] = f"NO recorder in {rep.region}: apply infra/terraform/aws/audit for this account"
    else:
        rep.config[profile] = (f"no recorder in {rep.region} is both recording and covering "
                               f"{', '.join(REQUIRED_CONFIG_TYPES)} (have: {', '.join(r.get('name', '?') for r in recs)})")


def inventory(rep: Report, profile: str, register: list[dict], managed_names: set[tuple[str, str]]) -> None:
    home = rep.region
    live: list[tuple[str, str, str, str]] = []  # kind, name, created, the region it is looked up in
    # list-buckets is account-wide; each bucket's own region is read when it matters, below.
    for b in (aws(profile, home, "s3api", "list-buckets") or {}).get("Buckets", []):
        live.append(("s3-bucket", b["Name"], str(b.get("CreationDate", "")), home))
    for region in sorted(rep.regions):
        for c in (aws(profile, region, "eks", "list-clusters") or {}).get("clusters", []):
            live.append(("eks-cluster", c, "", region))

    for kind, name, created, region in live:
        if (kind, name) in managed_names:
            continue
        cache: dict = {}

        def tags(kind=kind, name=name, region=region, cache=cache) -> dict:
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
        where = bucket_region(profile, home, name) if kind == "s3-bucket" else region
        if kind == "eks-cluster":
            detail = cache["detail"] if "detail" in cache else cluster_detail(profile, region, name)
            f.created = str(detail.get("createdAt", ""))
        f.creator = creator(profile, where, kind, name)
        # Config is regional and records a resource in the resource's own region; the recorder is in the home
        # region only, so it cannot have seen one elsewhere. CloudTrail's trail is multi-region.
        f.in_config = (config_has(profile, home, kind, name) if where == home
                       else f"in {where}; the recorder is in {home}")
        rep.unmanaged.append(f)


# ---------------------------------------------------------------- output -------------------------------------

def render(rep: Report, now: str) -> str:
    out = [f"# {ISSUE_TITLE}, {now}", "",
           f"Accounts: {', '.join(rep.accounts)}. Region: {rep.region} (Config; clusters also swept in "
           f"{', '.join(sorted(rep.regions - {rep.region})) or 'no other region'}). "
           "Plan-only: `terraform plan -refresh-only`, "
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
            out += [f"### {p.label} ({p.profile})", ""] + [f"- `{d}`" for d in p.drifted]
            out += ["", "```", p.excerpt, "```", ""]
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
    ap.add_argument("--accounts", default=os.environ.get("WIB_ATTENDEE_ACCOUNTS"),
                    help="comma-separated profiles (default: $WIB_ATTENDEE_ACCOUNTS, else fleet.sh's default)")
    ap.add_argument("--region", default=os.environ.get("WIB_REGION", "us-west-2"))
    ap.add_argument("--tf-dir", type=pathlib.Path, default=TF_DIR, help="the infra/terraform tree")
    ap.add_argument("--org-dir", type=pathlib.Path, default=None,
                    help="the infra/org tree, which holds the boundary root (default: <tf-dir>/../org)")
    ap.add_argument("--states", type=pathlib.Path, default=None,
                    help="cluster states (default: $WIB_STATE_DIR or <tf-dir>/fleet/states, as fleet.sh)")
    ap.add_argument("--register", type=pathlib.Path, default=None,
                    help="default: <tf-dir>/drift/known-unmanaged.yaml")
    ap.add_argument("--backups", type=pathlib.Path, default=None,
                    help="the standby roster whose regions are swept too (default: <tf-dir>/fleet/backups.tsv)")
    ap.add_argument("--out", type=pathlib.Path, help="also write the report here")
    ap.add_argument("--post", action="store_true", help=f"comment on (or open) the '{ISSUE_TITLE}' issue")
    ap.add_argument("--repo", default=os.environ.get("WIB_DRIFT_REPO", DEFAULT_REPO))
    ap.add_argument("--parallel", type=int, default=4)
    args = ap.parse_args(argv)

    org_dir = args.org_dir or args.tf_dir.parent / "org"
    states = args.states or pathlib.Path(os.environ.get("WIB_STATE_DIR") or args.tf_dir / "fleet/states")
    register_path = args.register or args.tf_dir / "drift/known-unmanaged.yaml"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    rep = Report([], args.region)

    try:
        fleet_sh = args.tf_dir / "fleet/fleet.sh"
        accounts = args.accounts or fleet_setting(fleet_sh, "WIB_ATTENDEE_ACCOUNTS")
        rep.accounts = [a for a in accounts.split(",") if a]
        default_account = os.environ.get("WIB_DEFAULT_ACCOUNT") or fleet_setting(fleet_sh, "WIB_DEFAULT_ACCOUNT")
        register = load_register(register_path)
        rep.regions |= backup_regions(args.backups or args.tf_dir / "fleet/backups.tsv")
        ids: dict[str, str] = {}
        for prof in rep.accounts:
            ids[prof] = (aws(prof, args.region, "sts", "get-caller-identity") or {}).get("Account", "")
            if not ids[prof]:
                raise Incomplete(f"sts get-caller-identity ({prof}) returned no account")
        managed_names: dict[str, set] = {prof: set() for prof in rep.accounts}
        collect_plans(rep, args.tf_dir, org_dir, states, default_account, ids, managed_names)
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
        # -lockfile=readonly: a report never rewrites a committed lock (verify/test_terraform_lock_init.py).
        init = run(["terraform", f"-chdir={root}", "init", "-input=false", "-no-color", "-lockfile=readonly"])
        if init.returncode != 0:
            rep.errors.append(f"terraform init in {root}: {last_line(init.stderr)}")
    if not rep.errors:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            list(pool.map(run_plan, rep.plans))
        rep.errors += [f"plan {p.label}: {p.excerpt}" for p in rep.plans if p.result == "error"]

    for prof in rep.accounts:
        try:
            check_config(rep, prof, ids[prof])
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
