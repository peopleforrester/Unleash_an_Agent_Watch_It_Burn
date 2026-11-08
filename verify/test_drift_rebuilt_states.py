# ABOUTME: #979's last criterion, held (#1044): drift-report.py --accounts accen-dev --region us-west-2, run with the
# ABOUTME: rebuilt states, has an empty Unmanaged table and reads every rebuilt state as clean, and decisions.md says so.
"""Offline. Two halves, both judged by one checker, `judge`, which is first shown to fail on each way the criterion
can stop holding.

1. The report, run with the rebuilt states. A scratch tree holds the five states #979 rebuilt in accen-dev, each at
   the path its rebuild script writes it to: `infra/terraform/fleet/import-state.py`'s `boundary`, `network` and
   `cluster` (read from the script's own ROOTS, STATE_DIR and network_state) and the audit root's
   `import-state.sh` (read from its STATE line). Each state has the shape the live ones have: the lab VPC with its
   outputs, the boundary policy, the audit bucket, watch-it-burn-community with its role tag and
   watch-it-burn-private without one (built before #636). terraform and aws are shims on a sealed PATH; the account
   holds what those states manage and nothing else, as accen-dev did at 2026-11-06T23:26Z. The real drift-report.py
   then runs with `--accounts accen-dev --region us-west-2`, and must exit 0 with Unmanaged `None.` and the five
   states clean. A rebuilt state left out, or one that drifted, must turn the checker red.

2. The record. #979's entries in decisions.md hold the live run's output as a fenced block beginning with the
   command itself. That block must be the exact command, exit 0, Unmanaged `None.`, and every rebuilt state among
   the clean states; and the entry must say each of the five was rebuilt by its script. Its findings, Unmanaged,
   drift and clean-state verdicts must also be what the offline run of part 1 gives, so the fixture is the world the
   live run saw.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
REPORT = REPO / "infra/terraform/drift/drift-report.py"
IMPORT_STATE = REPO / "infra/terraform/fleet/import-state.py"
AUDIT_IMPORT = REPO / "infra/terraform/aws/audit/import-state.sh"
DECISIONS = REPO / "decisions.md"
COMMAND = "python3 infra/terraform/drift/drift-report.py --accounts accen-dev --region us-west-2"
PROFILE, ACCOUNT_ID, REGION = "accen-dev", "111111111111", "us-west-2"
COMMUNITY, PRIVATE = "watch-it-burn-community", "watch-it-burn-private"
# The five states #979 rebuilt in accen-dev, as drift-report.py labels them.
REBUILT = {f"lab VPC {PROFILE}", f"boundary {PROFILE}", f"audit {PROFILE}", f"cluster {COMMUNITY}", f"cluster {PRIVATE}"}
AUDIT_BUCKET = f"watch-it-burn-audit-{ACCOUNT_ID}-{REGION}"
EVENT, NET_EVENT = "kubecon-na-2026", "devopsdays-portland-2026"
failures: list[str] = []


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


def need(text: str, literal: str, where: pathlib.Path) -> None:
    """An anchor this test reads repo text on; a reworded one stops the test by name, not as a broken check."""
    if literal not in text:
        sys.exit(f"anchor missing: {literal!r} is not in {where.relative_to(REPO)}; this test reads it")


# ------------------------------------------------------------------ the checker --------------------------------

def sections(text: str) -> dict[str, list[str]]:
    """Each `## ` heading of a report and the non-blank lines under it, up to the next heading."""
    out: dict[str, list[str]] = {}
    cur = None
    for ln in text.splitlines():
        if ln.startswith("## "):
            cur = ln[3:].strip()
            out[cur] = []
        elif cur is not None and ln.strip():
            out[cur].append(ln.strip())
    return out


def verdict(text: str, code: int) -> dict:
    """What a report says, in the terms of the criterion."""
    secs = sections(text)
    unmanaged = next((v for k, v in secs.items() if k.startswith("Unmanaged")), None)
    clean_key = next((k for k in secs if k.startswith("Clean states")), None)
    clean = [s.strip() for s in secs[clean_key][0].split(",")] if clean_key and secs[clean_key] else []
    m = re.search(r"\*\*(\d+) finding\(s\)\*\*: (\d+) drifted state\(s\), (\d+) unmanaged resource\(s\), "
                  r"(\d+) account\(s\) without a Config record\.", text)
    return {"exit": code,
            "incomplete": any(k.startswith("INCOMPLETE") for k in secs),
            "findings": tuple(int(g) for g in m.groups()) if m else None,
            "unmanaged": unmanaged,
            "drift": secs.get("Terraform drift"),
            "clean_count": int(re.search(r"\((\d+)\)", clean_key).group(1)) if clean_key else None,
            "clean": clean}


def judge(text: str, code: int) -> list[str]:
    """Every way the report falls short of the criterion; empty when it holds."""
    v = verdict(text, code)
    bad = []
    if v["exit"] != 0:
        bad.append(f"exit {v['exit']}, not 0")
    if v["incomplete"]:
        bad.append("the report calls itself INCOMPLETE")
    if v["findings"] != (0, 0, 0, 0):
        bad.append(f"findings line {v['findings']}, not 0 findings with 0 drifted, 0 unmanaged, 0 without Config")
    if v["unmanaged"] != ["None."]:
        bad.append(f"the Unmanaged table is {v['unmanaged']}, not `None.`")
    if v["drift"] != ["No state has drifted."]:
        bad.append(f"Terraform drift reads {v['drift']}")
    missing = sorted(REBUILT - set(v["clean"]))
    if missing:
        bad.append(f"rebuilt states not clean: {missing}")
    if v["clean_count"] != len(v["clean"]):
        bad.append(f"Clean states ({v['clean_count']}) lists {len(v['clean'])}")
    return bad


# ------------------------------------------------------------------ the record ---------------------------------

def entries_for(issue: str, text: str) -> list[str]:
    """decisions.md's entries whose heading names the issue. An entry starts at a dated `## ` heading only: a report
    quoted in a fenced block has `## ` lines of its own."""
    parts = re.split(r"(?m)^(?=## \d{4}-\d{2}-\d{2} · )", text)
    return [p for p in parts if p.startswith("## ") and re.search(rf"· {re.escape(issue)} ·", p.splitlines()[0])]


def recorded_runs(entry: str) -> list[tuple[str, int]]:
    """The fenced blocks of an entry that begin with `$ <COMMAND>` and end with `exit N`: (output, N)."""
    runs = []
    for block in re.findall(r"(?ms)^```[^\n]*\n(.*?)^```", entry):
        lines = block.rstrip("\n").splitlines()
        if not lines or not lines[0].startswith("$ python3 infra/terraform/drift/drift-report.py"):
            continue
        m = re.fullmatch(r"exit (\d+)", lines[-1].strip())
        runs.append(("\n".join(lines), int(m.group(1)) if m else -1))
    return runs


# ------------------------------------------------------------------ the offline run ----------------------------

FAKE_AWS = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
fx = json.load(open(os.environ["FAKE_AWS"]))
def opt(n):
    return a[a.index(n) + 1] if n in a else None
key = " ".join(a[:2])
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(a) + "\n")
if opt("--profile") != fx["profile"]:
    sys.stderr.write("An error occurred (ExpiredToken)\n"); sys.exit(255)
def out(v):
    print(json.dumps(v)); sys.exit(0)
if key == "sts get-caller-identity":
    out({"Account": fx["id"]})
if key == "s3api list-buckets":
    out({"Buckets": [{"Name": n, "CreationDate": "2026-10-28T11:00:00Z"} for n in fx["buckets"]]})
if key == "s3api get-bucket-tagging":
    sys.stderr.write("An error occurred (NoSuchTagSet)\n"); sys.exit(254)
if key == "s3api get-bucket-location":
    out({"LocationConstraint": fx["region"]})
if key == "eks list-clusters":
    out({"clusters": fx["clusters"] if opt("--region") == fx["region"] else []})
if key == "eks describe-cluster":
    out({"cluster": {"name": opt("--name"), "tags": {"ManagedBy": "terraform"}, "createdAt": "2026-10-28T11:39:00Z"}})
if key == "cloudtrail lookup-events":
    out({"Events": []})
if key == "configservice describe-configuration-recorders":
    out({"ConfigurationRecorders": [{"name": "watch-it-burn", "recordingGroup": {"allSupported": False,
         "resourceTypes": ["AWS::S3::Bucket", "AWS::EKS::Cluster", "AWS::IAM::User"]}}]})
if key == "configservice describe-configuration-recorder-status":
    out({"ConfigurationRecordersStatus": [{"name": "watch-it-burn", "recording": True}]})
if key == "configservice get-resource-config-history":
    out({"configurationItems": [{"configurationItemCaptureTime": "2026-10-28T11:45:00Z"}]})
sys.stderr.write("fake aws: unhandled " + key + "\n"); sys.exit(99)
'''

# A refresh-only plan finds nothing, except in a state whose path holds $FAKE_TF_DRIFT.
FAKE_TF = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if "init" in a:
    sys.exit(0)
if "show" in a:
    print(open(a[-1]).read()); sys.exit(0)
state = next(x for x in a if x.startswith("-state="))
out = next(x for x in a if x.startswith("-out="))[len("-out="):]
mark = os.environ.get("FAKE_TF_DRIFT")
drift = []
if mark and mark in state:
    drift = [{"address": "module.eks.aws_eks_cluster.this", "change": {"actions": ["update"]}}]
    print("Note: Objects have changed outside of Terraform\n  # module.eks.aws_eks_cluster.this has changed")
else:
    print("No changes. Your infrastructure still matches the configuration.")
json.dump({"format_version": "1.2", "resource_drift": drift}, open(out, "w"))
'''


def load_import_state():
    spec = importlib.util.spec_from_file_location("import_state", IMPORT_STATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rebuilt_paths() -> dict[str, pathlib.Path]:
    """Where each rebuild script writes its state, repo-relative, read from the scripts."""
    imp = load_import_state()
    audit_src = AUDIT_IMPORT.read_text(encoding="utf-8")
    need(audit_src, 'readonly STATE="states/${PROFILE}.tfstate"', AUDIT_IMPORT)
    need(audit_src, 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"', AUDIT_IMPORT)
    return {
        f"lab VPC {PROFILE}": imp.network_state(PROFILE).relative_to(REPO),
        f"boundary {PROFILE}": (imp.ROOTS["boundary"] / f"states/{PROFILE}.tfstate").relative_to(REPO),
        f"audit {PROFILE}": AUDIT_IMPORT.parent.relative_to(REPO) / f"states/{PROFILE}.tfstate",
        f"cluster {COMMUNITY}": (imp.STATE_DIR / f"{COMMUNITY}.tfstate").relative_to(REPO),
        f"cluster {PRIVATE}": (imp.STATE_DIR / f"{PRIVATE}.tfstate").relative_to(REPO),
    }


def tagged(rtype: str, attrs: dict, tags: dict, module: str | None = None) -> dict:
    r = {"mode": "managed", "type": rtype, "instances": [{"attributes": {**attrs, "tags_all": tags}}]}
    if module:
        r["module"] = module
    return r


def cluster_state(name: str, tags: dict) -> dict:
    """A rebuilt cluster state as import-state.py leaves it: the cluster, its node group's launch template (hop limit
    2 on the community cluster, #113) and a role, each carrying local.fleet_tags."""
    return {"version": 4, "resources": [
        tagged("aws_eks_cluster", {"name": name, "arn": f"arn:aws:eks:{REGION}:{ACCOUNT_ID}:cluster/{name}"}, tags,
               "module.eks"),
        tagged("aws_launch_template", {"metadata_options": [{"http_put_response_hop_limit": 2}]}, tags,
               "module.eks.module.eks_managed_node_group"),
        tagged("aws_iam_role", {"name": f"{name}-cluster-54c5a01d"}, tags, "module.eks")]}


def states() -> dict[str, dict]:
    fleet = {"ManagedBy": "terraform", "Purpose": "attendee-cluster", "project": "watch-it-burn", "event": EVENT}
    return {
        f"lab VPC {PROFILE}": {"version": 4, "outputs": {
            "vpc_id": {"value": "vpc-0607c27ee51fb233c"},
            "private_subnet_ids": {"value": ["subnet-a", "subnet-b", "subnet-c"]}},
            "resources": [tagged("aws_vpc", {"id": "vpc-0607c27ee51fb233c"},
                                 {"Purpose": "lab-shared-vpc", "event": NET_EVENT}, "module.vpc")]},
        f"boundary {PROFILE}": {"version": 4, "resources": [
            tagged("aws_iam_policy", {"name": "watch-it-burn-permissions-boundary"}, {"event": NET_EVENT})]},
        f"audit {PROFILE}": {"version": 4, "resources": [
            tagged("aws_s3_bucket", {"bucket": AUDIT_BUCKET}, {"event": EVENT})]},
        f"cluster {COMMUNITY}": cluster_state(COMMUNITY, {**fleet, "attendee": COMMUNITY, "role": "community",
                                                          "hostname": "burn.agenticburn.com"}),
        # Built 2026-10-28, before #636 put role= on every cluster: no resource of it carries one.
        f"cluster {PRIVATE}": cluster_state(PRIVATE, {**fleet, "attendee": PRIVATE,
                                                      "hostname": "burritobot-private.agenticburn.com"}),
    }


class World:
    def __init__(self, root: pathlib.Path):
        self.root, self.tf, self.bin = root, root / "infra/terraform", root / "bin"
        self.log, self.fixture = root / "aws-calls.log", root / "aws.json"
        self.bin.mkdir()
        # Not a symlink: a venv's python3 linked from elsewhere starts without the venv (#1047).
        (self.bin / "python3").write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
        for name, src in (("python3", None), ("aws", FAKE_AWS), ("terraform", FAKE_TF)):
            if src:
                (self.bin / name).write_text(src)
            (self.bin / name).chmod(0o755)
        for rel in ("drift/known-unmanaged.yaml", "fleet/fleet.sh", "fleet/backups.tsv", "fleet/roster.tsv"):
            (self.tf / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / "infra/terraform" / rel, self.tf / rel)
        self.paths = rebuilt_paths()
        for label, obj in states().items():
            p = root / self.paths[label]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(obj))
            if label.startswith("cluster "):
                p.with_suffix(".account").write_text(f"{PROFILE}\n")   # import-state.py's record_membership
        # accen-dev holds what the rebuilt states manage and nothing else.
        self.fx = {"profile": PROFILE, "id": ACCOUNT_ID, "region": REGION, "buckets": [AUDIT_BUCKET],
                   "clusters": [COMMUNITY, PRIVATE]}

    def run(self, **env: str) -> tuple[int, str]:
        self.fixture.write_text(json.dumps(self.fx))
        self.log.write_text("")
        e = {"PATH": str(self.bin), "FAKE_AWS": str(self.fixture), "FAKE_LOG": str(self.log),
             "HOME": str(self.root), **env}
        argv = shlex.split(COMMAND)[1:]
        p = subprocess.run([sys.executable, str(REPORT), *argv[1:], "--tf-dir", str(self.tf)],
                           capture_output=True, text=True, env=e)
        return p.returncode, p.stdout + p.stderr


print("== the checker fails on each way the criterion can stop holding ==")
GOOD = """# Fleet drift report, 2026-11-06T23:26Z
**0 finding(s)**: 0 drifted state(s), 0 unmanaged resource(s), 0 account(s) without a Config record.
## Terraform drift
No state has drifted.
## Unmanaged: in the account, in no Terraform state, not in the register
None.
## AWS Config
- accen-dev: ok: recorder watch-it-burn is recording
## Clean states (5)
lab VPC accen-dev, boundary accen-dev, audit accen-dev, cluster watch-it-burn-community, cluster watch-it-burn-private
"""
ROW = "| accen-dev | eks-cluster | `watch-it-burn-private` | 2026-10-28 | user/nwuser | recorded |"
broken = {
    "a non-zero exit": (GOOD, 2),
    "an Unmanaged row": (GOOD.replace("None.", ROW).replace("0 unmanaged", "1 unmanaged")
                         .replace("**0 finding", "**1 finding"), 0),
    "a rebuilt state missing from Clean states": (GOOD.replace("(5)", "(4)")
                                                  .replace(", cluster watch-it-burn-private", ""), 0),
    "a drifted state": (GOOD.replace("No state has drifted.", "### cluster watch-it-burn-private (accen-dev)"), 0),
    "an INCOMPLETE report": (GOOD.replace("## Terraform drift", "## INCOMPLETE: x\n- y\n## Terraform drift"), 0),
    "a clean count that is not the list": (GOOD.replace("(5)", "(6)"), 0),
    "no findings line": (GOOD.replace("**0 finding(s)**", "0 finding(s)"), 0),
}
check(f"the good report passes ({judge(GOOD, 0)})", judge(GOOD, 0) == [])
for why, (text, code) in broken.items():
    check(f"fails on {why}", judge(text, code) != [])

print("== the record: #979's entries hold the live run's output ==")
dec = DECISIONS.read_text(encoding="utf-8")
entries = entries_for("#979", dec)
check(f"decisions.md has #979 entries ({len(entries)})", len(entries) >= 1)
runs = [(entry, out, code) for entry in entries for out, code in recorded_runs(entry)]
check(f"one of them records a drift-report run as a fenced block ({len(runs)})", len(runs) >= 1)
for entry, out, code in runs:
    head = out.splitlines()[0]
    check(f"the block runs the criterion's exact command (got {head!r})", head == f"$ {COMMAND}")
    problems = judge(out, code)
    check(f"and its output meets the criterion: exit 0, Unmanaged None., every rebuilt state clean ({problems})",
          not problems)
    flat = " ".join(entry.split())
    for said in ("`import-state.py boundary accen-dev` exit 0", "`import-state.py network accen-dev` exit 0",
                 "`import-state.py cluster accen-dev <name>` for both",
                 "`infra/terraform/aws/audit/import-state.sh accen-dev`, exit 0"):
        check(f"the entry says the state was rebuilt: {said}", said in flat)
    check("and names both clusters it rebuilt", COMMUNITY in flat and PRIVATE in flat)
check("every rebuilt state has a rebuild script whose path this test read",
      set(rebuilt_paths()) == REBUILT)

print("== the report, run with the rebuilt states, as the criterion's command ==")
with tempfile.TemporaryDirectory(prefix="drift-rebuilt-") as tmp:
    w = World(pathlib.Path(tmp))
    for label, rel in sorted(w.paths.items()):
        print(f"     {label}: {rel}")
    rc, out = w.run()
    problems = judge(out, rc)
    check(f"exit 0, Unmanaged None., all five rebuilt states clean ({problems or 'ok'})", not problems)
    v = verdict(out, rc)
    check(f"the five clean states are the rebuilt ones and no other ({v['clean']})", set(v["clean"]) == REBUILT)
    calls = [json.loads(ln) for ln in w.log.read_text().splitlines()]
    check("every aws call names the accen-dev profile and a region",
          calls and all(c[c.index("--profile") + 1] == PROFILE and "--region" in c for c in calls))
    check("the private cluster's role comes from roster.tsv, as the live Notes said",
          "cluster watch-it-burn-private: no `role` tag in its state (built before #636), so it is planned with its "
          "roster.tsv role, admin" in out)
    if runs:
        rec = verdict(runs[0][1], runs[0][2])
        for k in ("exit", "findings", "unmanaged", "drift", "clean_count"):
            check(f"the recorded run and this one agree on {k} ({rec[k]!r})", rec[k] == v[k])
        check("and on which states are clean", set(rec["clean"]) == set(v["clean"]))

    print("== the same run turns red when a rebuilt state is lost or drifts ==")
    priv = pathlib.Path(tmp) / w.paths[f"cluster {PRIVATE}"]
    parked = pathlib.Path(tmp) / "parked.tfstate"
    priv.rename(parked)
    rc, out = w.run()
    check(f"with private's state gone it is unmanaged, exit 2, and the checker fails (got {rc})",
          rc == 2 and f"`{PRIVATE}`" in "\n".join(verdict(out, rc)["unmanaged"] or [])
          and any("not clean" in p for p in judge(out, rc)) and any("Unmanaged" in p for p in judge(out, rc)))
    parked.rename(priv)
    rc, out = w.run(FAKE_TF_DRIFT=f"{COMMUNITY}.tfstate")
    check(f"with community drifted it is a finding, exit 2, and the checker fails (got {rc})",
          rc == 2 and any(f"cluster {COMMUNITY}" in p for p in judge(out, rc)))
    bnd = pathlib.Path(tmp) / w.paths[f"boundary {PROFILE}"]
    bnd.rename(parked)
    rc, out = w.run()
    check("with the boundary state gone it is not among the clean states, and the checker fails",
          any(f"boundary {PROFILE}" in p for p in judge(out, rc)))
    parked.rename(bnd)
    rc, out = w.run()
    check(f"put back, the run is green again (got {rc})", rc == 0 and not judge(out, rc))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All rebuilt-state drift checks passed.")
