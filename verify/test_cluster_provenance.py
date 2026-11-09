# ABOUTME: Offline check of #979's provenance finding (#1043): from what stood in AWS, both KubeCon clusters read as built
# ABOUTME: from aws/cluster, so they are imported and not registered; a cluster missing any root mark is registered instead.
"""Offline: python3, PyYAML and the repo. infra/terraform/fleet/import-state.py is loaded as a module and its one
subprocess door, `run`, answers `aws` from verify/fixtures/import-state/kubecon-clusters.json, the answers AWS gave
for watch-it-burn-community and watch-it-burn-private on 2026-11-09 (run 19259), so nothing reaches an account.
verify/test_cluster_provenance_live.py asks AWS itself.

The criterion (#979, via #1043): each of the two clusters is shown to have been built from infra/terraform/aws/cluster
(or not), from what stands in AWS, and the choice between importing it and registering it follows from that. It stops
holding, and this fails, when:
- the marks `provenance` reads are no longer what the cluster root and the network root leave (main.tf changes);
- either recorded cluster stops reading as built, or the choice for it is not import, or the register
  (infra/terraform/drift/known-unmanaged.yaml) comes to cover it;
- a cluster missing any one mark still reads as built, or its choice is not register, or `cluster` imports it;
- the register's coverage stops deciding `follows`: a built cluster the register covers, or an unbuilt one it does
  not, must exit 2;
- docs/floor.md stops saying the two were built from the root, or stops importing them.
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "infra/terraform/fleet/import-state.py"
FIXTURE = REPO / "verify/fixtures/import-state/kubecon-clusters.json"
CLUSTER_TF = REPO / "infra/terraform/aws/cluster/main.tf"
NETWORK_TF = REPO / "infra/terraform/aws/network/main.tf"
FLOOR = REPO / "docs/floor.md"
NAMES = ("watch-it-burn-community", "watch-it-burn-private")
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def load():
    spec = importlib.util.spec_from_file_location("import_state", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Fake:
    """`run` for the script: aws answers from a world; any other command is a failure, since provenance reads AWS only."""

    def __init__(self, w: dict):
        self.w, self.calls = w, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] != "aws":
            return subprocess.CompletedProcess(cmd, 1, "", f"fake: {cmd[0]} is not expected")
        key = " ".join(cmd[1:cmd.index("--profile")])
        if key not in self.w:
            return subprocess.CompletedProcess(cmd, 255, "", f"fake aws: no answer for {key}")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(self.w[key]), "")


def main_of(kind: str, name: str, w: dict, register: pathlib.Path | None = None, extra: tuple = ()):
    mod = load()
    if register is not None:
        mod.REGISTER = register
    fake = Fake(w)
    mod.run = fake
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main([kind, "accen-dev", name, *extra])
    lines = dict(ln.split(": ", 1) for ln in out.getvalue().splitlines()
                 if re.match(r"^(verdict|choice|register|follows): ", ln))
    held = [ln for ln in out.getvalue().splitlines() if ln.startswith("  held ")]
    missing = [ln for ln in out.getvalue().splitlines() if ln.startswith("  MISSING")]
    return code, lines, held, missing, fake, out.getvalue() + err.getvalue()


# ---------------------------------------------------------------- anchors ----------------------------------------

for path in (SCRIPT, FIXTURE, CLUSTER_TF, NETWORK_TF, FLOOR):
    if not path.is_file():
        sys.exit(f"anchor missing: {path.relative_to(REPO)} is read by every check below")
recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
WORLD = recorded["answers"]
for n in NAMES:
    if f"eks describe-cluster --name {n}" not in WORLD:
        sys.exit(f"anchor missing: {FIXTURE.relative_to(REPO)} holds no describe-cluster answer for {n}")
cluster_tf = CLUSTER_TF.read_text(encoding="utf-8")
fleet_tags = re.search(r"^  fleet_tags = \{\n(.*?)\n  \}", cluster_tf, re.S | re.M)
eks = re.search(r'^module "eks" \{\n(.*?)\n\}', cluster_tf, re.S | re.M)
for what, m in (("locals { fleet_tags = { ... } }", fleet_tags), ('module "eks" { ... }', eks)):
    if not m:
        sys.exit(f"anchor missing: {what} is not in {CLUSTER_TF.relative_to(REPO)}")

mod = load()

print("The marks are the ones the cluster root and the network root leave:")
fixed = dict(re.findall(r'^\s*([A-Za-z_]+)\s*=\s*"([^"]*)"\s*$', fleet_tags.group(1), re.M))
check("provenance reads every fixed value local.fleet_tags sets, and no other", fixed == mod.PROVENANCE_TAGS,
      f"main.tf {fixed}, import-state.py {mod.PROVENANCE_TAGS}")
for k, v in mod.PROVENANCE_TAGS.items():
    check(f"local.fleet_tags sets {k} = \"{v}\"",
          re.search(rf'^\s*{re.escape(k)}\s*=\s*"{re.escape(v)}"\s*$', fleet_tags.group(1), re.M) is not None)
check("local.fleet_tags sets attendee = var.name",
      re.search(r"^\s*attendee\s*=\s*var\.name\s*$", fleet_tags.group(1), re.M) is not None)
check("the provider puts local.fleet_tags on every resource it makes, the cluster among them",
      re.search(r"default_tags \{\n\s*tags = local\.fleet_tags\n", cluster_tf) is not None)
check("module.eks is named var.name and leaves its cluster role's name to the module (<name>-cluster-*)",
      re.search(r"^\s*name\s*=\s*var\.name\s*$", eks.group(1), re.M) is not None
      and not re.search(r"^\s*iam_role_(name|use_name_prefix)\s*=", eks.group(1), re.M))
check("module.eks is put in var.vpc_id, the lab VPC", re.search(r"^\s*vpc_id\s*=\s*var\.vpc_id\s*$", eks.group(1), re.M)
      is not None)
check("its one managed node group is keyed default (named default-*)",
      re.search(r"eks_managed_node_groups = \{\n    default = \{\n.*?\n    \}\n  \}", cluster_tf, re.S) is not None)
k, v = mod.LAB_VPC_TAG
check(f"the network root tags the lab VPC {k} = \"{v}\"",
      re.search(rf'^\s*{k}\s*=\s*"{v}"\s*$', NETWORK_TF.read_text(encoding="utf-8"), re.M) is not None)

print(f"The KubeCon clusters, from what stood in AWS ({recorded['recorded']}):")
for n in NAMES:
    code, lines, held, missing, fake, text = main_of("provenance", n, WORLD)
    check(f"{n}: every mark is held", len(held) == 7 and not missing, text)
    check(f"{n}: built from infra/terraform/aws/cluster", lines.get("verdict") == "built from infra/terraform/aws/cluster",
          text)
    check(f"{n}: so the choice is import", lines.get("choice") == "import", text)
    check(f"{n}: and no register entry covers it", lines.get("register") == "no entry covers it", text)
    check(f"{n}: the choice follows, exit 0", code == 0 and lines.get("follows") == "yes", f"exit {code}")
    check(f"{n}: provenance only read AWS", all(c[0] == "aws" for c in fake.calls))

print("Each mark taken away in turn: not built, so register, and `cluster` refuses it:")
VPC = WORLD[f"eks describe-cluster --name {NAMES[0]}"]["cluster"]["resourcesVpcConfig"]["vpcId"]


def without(n: str, how: str) -> dict:
    w = copy.deepcopy(WORLD)
    cl = w[f"eks describe-cluster --name {n}"]["cluster"]
    if how.startswith("drop tag "):
        del cl["tags"][how[9:]]
    elif how.startswith("change tag "):
        cl["tags"][how[11:]] = "by-hand"
    elif how == "a console-made cluster role":
        cl["roleArn"] = cl["roleArn"].rsplit("/", 1)[0] + "/eksClusterRole"
    elif how == "no node group":
        w[f"eks list-nodegroups --cluster-name {n}"] = {"nodegroups": []}
    elif how == "a hand-named node group":
        w[f"eks list-nodegroups --cluster-name {n}"] = {"nodegroups": ["workers"]}
    elif how == "two default-* node groups":
        w[f"eks list-nodegroups --cluster-name {n}"] = {"nodegroups": ["default-a", "default-b"]}
    elif how == "a VPC with no Purpose tag":
        w[f"ec2 describe-vpcs --vpc-ids {VPC}"]["Vpcs"][0]["Tags"] = [
            t for t in w[f"ec2 describe-vpcs --vpc-ids {VPC}"]["Vpcs"][0]["Tags"] if t["Key"] != "Purpose"]
    elif how == "another VPC":
        cl["resourcesVpcConfig"]["vpcId"] = "vpc-other"
        w["ec2 describe-vpcs --vpc-ids vpc-other"] = {"Vpcs": [{"VpcId": "vpc-other", "Tags": [
            {"Key": "Purpose", "Value": "default"}]}]}
    else:
        raise AssertionError(how)
    return w


WAYS = [f"{v} tag {k}" for k in (*mod.PROVENANCE_TAGS, "attendee") for v in ("drop", "change")] + [
    "a console-made cluster role", "no node group", "a hand-named node group", "two default-* node groups",
    "a VPC with no Purpose tag", "another VPC"]
for n in NAMES:
    for how in WAYS:
        w = without(n, how)
        code, lines, held, missing, _, text = main_of("provenance", n, w)
        check(f"{n}, {how}: one mark missing, not built, choice register, unregistered so exit 2",
              len(missing) == 1 and lines.get("verdict") == "not built from infra/terraform/aws/cluster"
              and lines.get("choice") == "register" and lines.get("follows") == "no" and code == 2, text)
        code, _, _, _, fake, text = main_of("cluster", n, w)
        check(f"{n}, {how}: `cluster` stops before any plan or import",
              code == 1 and not any(c[0] == "terraform" for c in fake.calls)
              and "not built from aws/cluster" in text, text)

print("The register decides whether the choice was made:")
with tempfile.TemporaryDirectory() as t:
    reg = pathlib.Path(t) / "known-unmanaged.yaml"
    reg.write_text("entries:\n  - kind: eks-cluster\n    name: watch-it-burn-community\n    accounts: [accen-dev]\n"
                   "    made_by: a test\n    why: a test\n", encoding="utf-8")
    code, lines, *_ = main_of("provenance", NAMES[0], WORLD, reg)
    check("a built cluster the register covers: follows no, exit 2",
          code == 2 and lines.get("choice") == "import" and lines.get("register") == "a test" and lines.get("follows") == "no")
    code, lines, *_ = main_of("provenance", NAMES[0], without(NAMES[0], "drop tag ManagedBy"), reg)
    check("an unbuilt cluster the register covers: choice register, follows yes, exit 0",
          code == 0 and lines.get("choice") == "register" and lines.get("follows") == "yes")
lab = {"eks describe-cluster --name lab-x": {"cluster": {
           "name": "lab-x", "roleArn": "arn:aws:iam::1:role/lab-x-eks", "tags": {"lab-platform:managed": "true"},
           "resourcesVpcConfig": {"vpcId": "vpc-lab"}}},
       "eks list-nodegroups --cluster-name lab-x": {"nodegroups": ["pool-a"]},
       "ec2 describe-vpcs --vpc-ids vpc-lab": {"Vpcs": [{"VpcId": "vpc-lab", "Tags": []}]},
       "sts get-caller-identity": WORLD["sts get-caller-identity"]}
code, lines, held, missing, _, text = main_of("provenance", "lab-x", lab)
check("a lab-platform cluster: no mark held, registered by the repo's own register's tag entry, exit 0",
      not held and lines.get("choice") == "register" and "lab-platform" in lines.get("register", "") and code == 0, text)

print("docs/floor.md says what AWS shows:")
floor = " ".join(FLOOR.read_text(encoding="utf-8").split())
check("it says both clusters were built from `infra/terraform/aws/cluster`",
      "watch-it-burn-community and watch-it-burn-private were built from `infra/terraform/aws/cluster`" in floor)
for n in NAMES:
    check(f"and imports {n}", f"python3 infra/terraform/fleet/import-state.py cluster accen-dev {n}" in floor)
check("and names the provenance command that shows it", "import-state.py provenance" in floor)

print("Usage:")
code, *_ = main_of("provenance", NAMES[0], WORLD, extra=("--resume",))
check("provenance refuses --resume", code == 1)
mod = load()
mod.run = Fake(WORLD)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    code = mod.main(["provenance", "accen-dev"])
check("provenance needs a cluster name", code == 1)

if failures:
    print(f"\nFAIL: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("\nPASS: cluster provenance")
