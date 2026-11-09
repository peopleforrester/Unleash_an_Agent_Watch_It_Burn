#!/usr/bin/env python3
# ABOUTME: Rebuilds a lost fleet state from what stands in AWS (#979): an account's permissions boundary, its lab VPC, or
# ABOUTME: one cluster built from aws/cluster. It plans the root, finds each planned resource's import id, imports, settles.
"""The states are local files, gitignored, so a state lives only on the machine that applied it. The KubeCon clusters
watch-it-burn-community and watch-it-burn-private were built from aws/cluster by fleet.sh on 2026-10-28, and no
machine a run can read holds their states, accen-dev's lab VPC state or its boundary state; the drift report then
lists both clusters as unmanaged. #955 rebuilt the audit root's state the same way (aws/audit/import-state.sh), from a
fixed list. Here the list cannot be fixed: the cluster root's modules name their roles, policies, groups and node
group with a random suffix, and the set of resources follows the root's variables. So the script asks Terraform:

1. It refuses a state that already manages anything, so it never writes over a live state.
2. It reads the variables the resources were built with from AWS itself (tags, the node group, its launch template),
   never from a guess, and plans the root against an empty state. Every planned resource is one to import.
   A roster cluster built before #636 carries no role= tag; its role is then its roster.tsv row's, as in fleet.sh.
3. It finds each one's import id in AWS before it imports anything, and stops naming the first it cannot find, so a
   half-found set writes no state. NOT_IMPORTABLE lists the planned resources that are not in AWS at all. A security
   group rule the group does not carry is configuration committed after the build (#869's and #906's rules, on the
   KubeCon clusters): it is left out, and the last plan lists it as a create.
4. It imports them one by one, writes the EKS module's time_sleep itself (WRITTEN says why), runs the refresh-only
   apply docs/floor.md gives to settle a state, and plans again. A rebuild that stops part way is carried on with
   --resume, which imports only what the state does not hold yet.

Imports, a refresh-only apply and a plan only read AWS, so nothing in AWS changes. The last plan is the answer: exit
0 when it has no change but the NOT_IMPORTABLE creates, 2 when the state is rebuilt and the plan still has changes
(it lists them: configuration committed since the resources were built, which the next fleet.sh apply makes), 1 on
an error. Every AWS call names --profile and --region.

Only a cluster built from aws/cluster is imported; one that was not is registered in drift/known-unmanaged.yaml
instead (#979). `provenance` answers which (#1043): it reads in AWS each mark the root leaves on a cluster it builds
(PROVENANCE below), says the cluster was built from the root when every one is there, names the choice that follows,
import or register, and reads whether the register covers the cluster. It exits 0 when the repo's choice follows
from what AWS shows (built and in no register entry, or not built and in one), 2 when it does not, 1 on an error.
`cluster` asks the same question first and refuses to import a cluster that was not built from the root.

Usage (each root initialised first, `terraform -chdir=<root> init`):
  python3 infra/terraform/fleet/import-state.py provenance <profile> <name>   (reads AWS only, no root needed)
  python3 infra/terraform/fleet/import-state.py boundary <profile>
  python3 infra/terraform/fleet/import-state.py network <profile>
  python3 infra/terraform/fleet/import-state.py cluster <profile> <name>
  ... --resolve-only   finds and prints every import id, imports nothing, writes no state
  ... --resume         carries on a rebuild this script stopped, importing only what the state does not hold
Run boundary and network first: a cluster's plan reads the boundary policy and takes its subnets from the lab VPC
state. --region defaults to fleet.sh's WIB_REGION; a lab VPC outside the home region is not rebuilt by this script.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

FLEET = pathlib.Path(__file__).resolve().parent            # infra/terraform/fleet
TF_DIR = FLEET.parent                                      # infra/terraform
ROOTS = {"boundary": TF_DIR.parent / "org/boundary", "network": TF_DIR / "aws/network", "cluster": TF_DIR / "aws/cluster"}
STATE_DIR = FLEET / "states"
# Planned resources that are not AWS objects and that Terraform cannot import: a module's local validation and the
# lab-platform operator's id tracker (an attendee seat's only). They stay as creates in the last plan; the next apply
# records them without an AWS call.
NOT_IMPORTABLE = {"null_resource", "terraform_data"}
# Planned resources the script writes into the state itself, after the imports. The EKS module's time_sleep carries
# the cluster's name, endpoint, version, service CIDR and CA in its triggers, and the node group, the access entries
# and the addons read them from there. Terraform imports a time_sleep with no triggers, after which no expression
# that reads them evaluates and the import fails; and with no time_sleep at all those reads are unknown, so the plan
# would replace the node group and the access entries. So it is written with the triggers its module gives it, read
# from the imported cluster, and the last plan shows a no-op for it only if they are what the module computes.
WRITTEN = {"time_sleep"}
# The cluster root's variables the script reads from AWS, and the cluster tags that name three of them (local.fleet_tags).
CLUSTER_TAG_VARS = ("event", "hostname", "role")


class Stop(Exception):
    """Something the rebuild depends on is missing or ambiguous; nothing is guessed past it."""


class Absent(Exception):
    """A planned resource AWS provably does not hold: configuration committed after the resources were built (a
    security group rule the group does not carry). It is not imported, and the last plan lists it as a create."""


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError as e:
        raise Stop(f"{cmd[0]} is not on PATH") from e


def last_line(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "(no output)"


def setting(var: str) -> str:
    """fleet.sh's default for one WIB_ setting, as drift-report.py reads it, so both name the same account and region."""
    text = (FLEET / "fleet.sh").read_text(encoding="utf-8")
    m = re.search(rf'^{var}="\$\{{{var}:-([^}}]*)\}}"$', text, re.M)
    if not m or not m.group(1):
        raise Stop(f"infra/terraform/fleet/fleet.sh has no {var}=\"${{{var}:-...}}\" default to read")
    return m.group(1)


class AWS:
    """One profile and region; every call names both, and each answer is kept, since resolving reads some twice."""

    def __init__(self, profile: str, region: str):
        self.profile, self.region, self.cache = profile, region, {}

    def __call__(self, *args: str, ok_errors: tuple[str, ...] = ()) -> dict | None:
        if args in self.cache:
            return self.cache[args]
        p = run(["aws", *args, "--profile", self.profile, "--region", self.region, "--output", "json"])
        if p.returncode != 0:
            if any(e in p.stderr for e in ok_errors):
                return None
            raise Stop(f"aws {' '.join(args[:2])} ({self.profile}, {self.region}): {last_line(p.stderr)}")
        self.cache[args] = json.loads(p.stdout) if p.stdout.strip() else {}
        return self.cache[args]

    def one(self, items: list, what: str):
        if len(items) != 1:
            raise Stop(f"{what}: AWS holds {len(items)}, not one")
        return items[0]


# ---------------------------------------------------------------- resolvers -------------------------------------
# Each takes the planned resource (address, type, `after` values) and returns the id `terraform import` takes for it.

def module_of(address: str) -> str:
    """`module.eks.module.eks_managed_node_group["default"].aws_iam_role.this[0]` -> the module path before the type."""
    parts = re.findall(r'module\.[A-Za-z0-9_-]+(?:\[[^\]]*\])?', address)
    return ".".join(parts)


def planned_at(planned: list[dict], address: str) -> dict:
    for rc in planned:
        if rc["address"] == address:
            return rc["change"]["after"] or {}
    raise Stop(f"the plan has no {address}")


class Resolver:
    def __init__(self, aws: AWS, account: str):
        self.aws, self.account = aws, account

    def resolve(self, rc: dict, planned: list[dict]) -> str:
        fn = getattr(self, f"r_{rc['type']}", None)
        if fn is None:
            raise Stop(f"{rc['address']}: no import rule for {rc['type']}; add one to import-state.py")
        return fn(rc["address"], rc["change"]["after"] or {}, planned)

    # IAM, shared by every root
    def policy_arn_by_name(self, name: str) -> str:
        arn = f"arn:aws:iam::{self.account}:policy/{name}"
        self.aws("iam", "get-policy", "--policy-arn", arn)
        return arn

    def r_aws_iam_policy(self, address, after, planned):
        if after.get("name"):
            return self.policy_arn_by_name(after["name"])
        prefix = after.get("name_prefix") or ""
        role = self.module_role(address, planned)
        attached = self.aws("iam", "list-attached-role-policies", "--role-name", role)["AttachedPolicies"]
        return self.aws.one([p["PolicyArn"] for p in attached if p["PolicyName"].startswith(prefix)
                             and ":aws:policy/" not in p["PolicyArn"]], f"{address}: policies named {prefix}* on {role}")


class BoundaryResolver(Resolver):
    pass


class NetworkResolver(Resolver):
    def __init__(self, aws: AWS, account: str, vpc_name: str):
        super().__init__(aws, account)
        self.vpc_name = vpc_name
        self._vpc = None

    @property
    def vpc(self) -> str:
        if self._vpc is None:
            vpcs = self.aws("ec2", "describe-vpcs", "--filters", f"Name=tag:Name,Values={self.vpc_name}")["Vpcs"]
            self._vpc = self.aws.one(vpcs, f"VPCs tagged Name={self.vpc_name}")["VpcId"]
        return self._vpc

    def subnet(self, cidr: str) -> str:
        subs = self.aws("ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={self.vpc}")["Subnets"]
        return self.aws.one([s["SubnetId"] for s in subs if s["CidrBlock"] == cidr], f"subnet {cidr} in {self.vpc}")

    def route_table(self, name: str) -> str:
        rts = self.aws("ec2", "describe-route-tables", "--filters", f"Name=vpc-id,Values={self.vpc}")["RouteTables"]
        return self.aws.one([r["RouteTableId"] for r in rts if {"Key": "Name", "Value": name} in r.get("Tags", [])],
                            f"route table {name} in {self.vpc}")

    def nat(self) -> dict:
        nats = self.aws("ec2", "describe-nat-gateways", "--filter", f"Name=vpc-id,Values={self.vpc}",
                        "Name=state,Values=available")["NatGateways"]
        return self.aws.one(nats, f"available NAT gateways in {self.vpc}")

    def r_aws_vpc(self, address, after, planned):
        return self.vpc

    def r_aws_subnet(self, address, after, planned):
        return self.subnet(after["cidr_block"])

    def r_aws_internet_gateway(self, address, after, planned):
        igws = self.aws("ec2", "describe-internet-gateways", "--filters",
                        f"Name=attachment.vpc-id,Values={self.vpc}")["InternetGateways"]
        return self.aws.one(igws, f"internet gateways on {self.vpc}")["InternetGatewayId"]

    def r_aws_nat_gateway(self, address, after, planned):
        return self.nat()["NatGatewayId"]

    def r_aws_eip(self, address, after, planned):
        return self.aws.one([a["AllocationId"] for a in self.nat()["NatGatewayAddresses"] if a.get("AllocationId")],
                            "the NAT gateway's Elastic IPs")

    def r_aws_route_table(self, address, after, planned):
        return self.route_table(after["tags"]["Name"])

    def r_aws_route(self, address, after, planned):
        table = address.split(".")[-1].split("_")[0]   # private_nat_gateway[0] / public_internet_gateway[0]
        rt = planned_at(planned, f"{module_of(address)}.aws_route_table.{table}[0]")
        return f"{self.route_table(rt['tags']['Name'])}_{after['destination_cidr_block']}"

    def r_aws_route_table_association(self, address, after, planned):
        m = re.search(r"aws_route_table_association\.(private|public)\[(\d+)\]$", address)
        if not m:
            raise Stop(f"{address}: not a private[i] or public[i] association")
        kind, i = m.groups()
        sub = planned_at(planned, f"{module_of(address)}.aws_subnet.{kind}[{i}]")
        rt = planned_at(planned, f"{module_of(address)}.aws_route_table.{kind}[0]")
        return f"{self.subnet(sub['cidr_block'])}/{self.route_table(rt['tags']['Name'])}"

    def r_aws_default_network_acl(self, address, after, planned):
        acls = self.aws("ec2", "describe-network-acls", "--filters", f"Name=vpc-id,Values={self.vpc}",
                        "Name=default,Values=true")["NetworkAcls"]
        return self.aws.one(acls, f"default network ACLs of {self.vpc}")["NetworkAclId"]

    def r_aws_default_route_table(self, address, after, planned):
        return self.vpc   # aws_default_route_table is imported by its VPC's id

    def r_aws_default_security_group(self, address, after, planned):
        sgs = self.aws("ec2", "describe-security-groups", "--filters", f"Name=vpc-id,Values={self.vpc}",
                       "Name=group-name,Values=default")["SecurityGroups"]
        return self.aws.one(sgs, f"default security groups of {self.vpc}")["GroupId"]

    def r_aws_security_group(self, address, after, planned):
        sgs = self.aws("ec2", "describe-security-groups", "--filters", f"Name=vpc-id,Values={self.vpc}",
                       f"Name=group-name,Values={after['name']}")["SecurityGroups"]
        return self.aws.one(sgs, f"security groups named {after['name']} in {self.vpc}")["GroupId"]

    def r_aws_vpc_endpoint(self, address, after, planned):
        eps = self.aws("ec2", "describe-vpc-endpoints", "--filters", f"Name=vpc-id,Values={self.vpc}",
                       f"Name=service-name,Values={after['service_name']}")["VpcEndpoints"]
        return self.aws.one([e["VpcEndpointId"] for e in eps if e["State"] != "deleted"],
                            f"{after['service_name']} endpoints in {self.vpc}")

    def r_aws_budgets_budget(self, address, after, planned):
        self.aws("budgets", "describe-budget", "--account-id", self.account, "--budget-name", after["name"])
        return f"{self.account}:{after['name']}"


class ClusterResolver(Resolver):
    def __init__(self, aws: AWS, account: str, name: str):
        super().__init__(aws, account)
        self.name = name

    @property
    def cluster(self) -> dict:
        return self.aws("eks", "describe-cluster", "--name", self.name)["cluster"]

    @property
    def nodegroup(self) -> dict:
        ngs = self.aws("eks", "list-nodegroups", "--cluster-name", self.name)["nodegroups"]
        ng = self.aws.one([n for n in ngs if n.startswith("default-")], f"node groups default-* on {self.name}")
        return self.aws("eks", "describe-nodegroup", "--cluster-name", self.name, "--nodegroup-name", ng)["nodegroup"]

    def launch_template(self) -> dict:
        lt = self.nodegroup["launchTemplate"]
        vers = self.aws("ec2", "describe-launch-template-versions", "--launch-template-id", lt["id"],
                        "--versions", str(lt["version"]))["LaunchTemplateVersions"]
        return self.aws.one(vers, f"launch template {lt['id']} version {lt['version']}")["LaunchTemplateData"]

    def associations(self) -> list[dict]:
        return self.aws("eks", "list-pod-identity-associations", "--cluster-name", self.name)["associations"]

    def association(self, namespace: str, sa: str) -> dict:
        found = [a for a in self.associations() if a["namespace"] == namespace and a["serviceAccount"] == sa]
        a = self.aws.one(found, f"pod identity associations for {namespace}/{sa} on {self.name}")
        return self.aws("eks", "describe-pod-identity-association", "--cluster-name", self.name,
                        "--association-id", a["associationId"])["association"]

    def module_role(self, address: str, planned: list[dict]) -> str:
        """The IAM role the resource's module made, found from what uses it, never from its random suffix."""
        mod = module_of(address)
        if mod == "module.eks":
            arn = self.cluster["roleArn"]
        elif mod.startswith('module.eks.module.eks_managed_node_group['):
            arn = self.nodegroup["nodeRole"]
        else:   # an eks-pod-identity module: its associations all carry its one role
            arns = {self.association(rc["change"]["after"]["namespace"], rc["change"]["after"]["service_account"])
                    ["roleArn"] for rc in planned if rc["type"] == "aws_eks_pod_identity_association"
                    and module_of(rc["address"]) == mod}
            if len(arns) != 1:
                raise Stop(f"{address}: the associations of {mod} name {len(arns)} roles, not one")
            arn = arns.pop()
        role = arn.rsplit("/", 1)[1]
        for rc in planned:
            if rc["type"] == "aws_iam_role" and module_of(rc["address"]) == mod:
                prefix = (rc["change"]["after"] or {}).get("name_prefix") or ""
                if not role.startswith(prefix):
                    raise Stop(f"{address}: {mod}'s role in AWS is {role}, not one named {prefix}*")
        return role

    def r_aws_eks_cluster(self, address, after, planned):
        return self.cluster["name"]

    def r_aws_eks_addon(self, address, after, planned):
        self.aws("eks", "describe-addon", "--cluster-name", self.name, "--addon-name", after["addon_name"])
        return f"{self.name}:{after['addon_name']}"

    def principal(self, address: str, after: dict, planned: list[dict]) -> str:
        if after.get("principal_arn"):
            return after["principal_arn"]
        if address in ("aws_eks_access_entry.attendee", "aws_eks_access_policy_association.attendee_admin"):
            user = planned_at(planned, "aws_iam_user.attendee")["name"]
            return self.aws("iam", "get-user", "--user-name", user)["User"]["Arn"]
        raise Stop(f"{address}: its principal is not known at plan and there is no rule to find it")

    def r_aws_eks_access_entry(self, address, after, planned):
        p = self.principal(address, after, planned)
        self.aws("eks", "describe-access-entry", "--cluster-name", self.name, "--principal-arn", p)
        return f"{self.name}:{p}"

    def r_aws_eks_access_policy_association(self, address, after, planned):
        p = self.principal(address, after, planned)
        held = self.aws("eks", "list-associated-access-policies", "--cluster-name", self.name, "--principal-arn", p)
        if after["policy_arn"] not in [a["policyArn"] for a in held["associatedAccessPolicies"]]:
            raise Stop(f"{address}: {p} has no {after['policy_arn']} on {self.name}")
        return f"{self.name}#{p}#{after['policy_arn']}"

    def r_aws_eks_pod_identity_association(self, address, after, planned):
        a = self.association(after["namespace"], after["service_account"])
        return f"{self.name},{a['associationId']}"

    def r_aws_eks_node_group(self, address, after, planned):
        return f"{self.name}:{self.nodegroup['nodegroupName']}"

    def r_aws_launch_template(self, address, after, planned):
        return self.nodegroup["launchTemplate"]["id"]

    def r_aws_iam_role(self, address, after, planned):
        if after.get("name"):
            return after["name"]
        return self.module_role(address, planned)

    def r_aws_iam_role_policy_attachment(self, address, after, planned):
        role = self.module_role(address, planned)
        attached = [p["PolicyArn"] for p in self.aws("iam", "list-attached-role-policies", "--role-name", role)
                    ["AttachedPolicies"]]
        if after.get("policy_arn"):
            if after["policy_arn"] not in attached:
                raise Stop(f"{address}: {after['policy_arn']} is not attached to {role}")
            return f"{role}/{after['policy_arn']}"
        # Unknown at plan: a policy this root makes. It is the one attached that no sibling attachment names.
        known = {(rc["change"]["after"] or {}).get("policy_arn") for rc in planned
                 if rc["type"] == "aws_iam_role_policy_attachment" and module_of(rc["address"]) == module_of(address)}
        left = [a for a in attached if a not in known]
        return f"{role}/{self.aws.one(left, f'{address}: policies on {role} no other attachment names')}"

    def r_aws_iam_user(self, address, after, planned):
        self.aws("iam", "get-user", "--user-name", after["name"])
        return after["name"]

    def r_aws_iam_user_policy(self, address, after, planned):
        self.aws("iam", "get-user-policy", "--user-name", after["user"], "--policy-name", after["name"])
        return f"{after['user']}:{after['name']}"

    def r_aws_bedrock_inference_profile(self, address, after, planned):
        profiles = self.aws("bedrock", "list-inference-profiles", "--type-equals", "APPLICATION")["inferenceProfileSummaries"]
        return self.aws.one([p["inferenceProfileId"] for p in profiles if p["inferenceProfileName"] == after["name"]],
                            f"application inference profiles named {after['name']}")

    def node_sg(self) -> str:
        sgs = self.aws("ec2", "describe-security-groups", "--filters",
                       f"Name=vpc-id,Values={self.cluster['resourcesVpcConfig']['vpcId']}",
                       f"Name=group-name,Values={self.name}-node-*")["SecurityGroups"]
        return self.aws.one(sgs, f"security groups named {self.name}-node-*")["GroupId"]

    def cluster_sg(self) -> str:
        ids = self.cluster["resourcesVpcConfig"]["securityGroupIds"]
        return self.aws.one(ids, f"additional security groups on {self.name}")

    def r_aws_security_group(self, address, after, planned):
        if address.endswith("aws_security_group.node[0]"):
            return self.node_sg()
        if address.endswith("aws_security_group.cluster[0]"):
            return self.cluster_sg()
        raise Stop(f"{address}: not the module's cluster or node group")

    def r_aws_security_group_rule(self, address, after, planned):
        m = re.search(r"aws_security_group_rule\.(cluster|node)\[", address)
        if not m:
            raise Stop(f"{address}: not a cluster or node rule")
        sg = self.cluster_sg() if m.group(1) == "cluster" else self.node_sg()
        rules = self.aws("ec2", "describe-security-group-rules", "--filters", f"Name=group-id,Values={sg}")["SecurityGroupRules"]
        egress, cidrs = after["type"] == "egress", sorted(after.get("cidr_blocks") or [])

        def source(r: dict) -> str | None:
            if r.get("CidrIpv4"):
                return r["CidrIpv4"]
            ref = (r.get("ReferencedGroupInfo") or {}).get("GroupId")
            return "self" if ref == sg else ref

        cands = [r for r in rules if r["IsEgress"] == egress and r["IpProtocol"] == after["protocol"]
                 and (after["protocol"] == "-1" or (r["FromPort"], r["ToPort"]) == (after["from_port"], after["to_port"]))]
        if cidrs:
            cands = [r for r in cands if r.get("CidrIpv4") in cidrs]
            if not cands:
                raise Absent(f"{sg} has no {after['type']} rule from {cidrs} on {after['from_port']}-{after['to_port']}")
            if len({r["CidrIpv4"] for r in cands}) != len(cidrs):
                raise Stop(f"{address}: {sg} holds {len(cands)} of the rule's CIDRs {cidrs}")
            src = "_".join(cidrs)
        else:
            cands = [r for r in cands if source(r) == "self"] if after.get("self") else \
                [r for r in cands if source(r) not in (None, "self") and not r.get("CidrIpv4")]
            if not cands:
                raise Absent(f"{sg} has no {after['type']} {after['protocol']} rule on {after['from_port']}-"
                             f"{after['to_port']} from {'itself' if after.get('self') else 'a group'}")
            if len(cands) > 1:   # the same port from two groups: the description the module wrote tells them apart
                cands = [r for r in cands if r.get("Description") == after.get("description")]
            src = source(self.aws.one(cands, f"{address}: rules on {sg} for {after['type']} {after['protocol']} "
                                              f"{after['from_port']}-{after['to_port']}"))
        proto = "all" if after["protocol"] == "-1" else after["protocol"]
        return f"{sg}_{after['type']}_{proto}_{after['from_port']}_{after['to_port']}_{src}"

    def r_aws_kms_alias(self, address, after, planned):
        self.aws("kms", "describe-key", "--key-id", after["name"])
        return after["name"]

    def r_aws_kms_key(self, address, after, planned):
        alias = self.aws.one([rc["change"]["after"]["name"] for rc in planned if rc["type"] == "aws_kms_alias"
                              and module_of(rc["address"]) == module_of(address)], f"{address}: aliases in its module")
        return self.aws("kms", "describe-key", "--key-id", alias)["KeyMetadata"]["KeyId"]


# ---------------------------------------------------------------- variables -------------------------------------

def tags_of(items: list[dict]) -> dict:
    return {t["Key"]: t["Value"] for t in items or []}


def one_tag(tags: dict, key: str, what: str) -> str:
    if not tags.get(key):
        raise Stop(f"{what} carries no `{key}` tag, so the plan cannot be given -var {key}= as it was applied")
    return tags[key]


def roster_role(roster: pathlib.Path, name: str) -> str | None:
    """A roster cluster's role from roster.tsv (`name|role|...`), the data fleet.sh's role_for_cluster answers from.
    Clusters built before #636 carry no role= tag, watch-it-burn-private among them; both roster clusters are in it."""
    for ln in roster.read_text(encoding="utf-8").splitlines():
        fields = ln.split("|")
        if ln.strip() and not ln.lstrip().startswith("#") and fields[0].strip() == name and len(fields) > 1:
            return fields[1].strip() if fields[1].strip() in ("community", "admin") else None
    return None


def network_state(profile: str) -> pathlib.Path:
    """Where fleet.sh keeps an account's home-region lab VPC state (read_vpc_for): the default account's in the root's
    own terraform.tfstate, every other account's under states/."""
    net = ROOTS["network"]
    return net / "terraform.tfstate" if profile == setting("WIB_DEFAULT_ACCOUNT") else net / f"states/{profile}.tfstate"


def cluster_vars(aws: AWS, res: ClusterResolver, profile: str) -> list[tuple[str, str]]:
    cl = res.cluster
    tags = cl.get("tags") or {}
    lab = network_state(profile)
    if not lab.is_file():
        raise Stop(f"no lab VPC state at {lab}: rebuild it first (import-state.py network {profile})")
    outs = {k: v.get("value") for k, v in (json.loads(lab.read_text()).get("outputs") or {}).items()}
    subnets, vpc = outs.get("private_subnet_ids") or [], outs.get("vpc_id")
    if vpc != cl["resourcesVpcConfig"]["vpcId"] or set(subnets) != set(cl["resourcesVpcConfig"]["subnetIds"]):
        raise Stop(f"{res.name} is in {cl['resourcesVpcConfig']['vpcId']} {sorted(cl['resourcesVpcConfig']['subnetIds'])}, "
                   f"not the lab VPC state's {vpc} {sorted(subnets)}")
    ng, lt = res.nodegroup, res.launch_template()
    user_data = base64.b64decode(lt.get("UserData") or "").decode("utf-8", "replace")

    def kubelet(key: str) -> str:
        m = re.search(rf"^\s*{key}:\s*(-?\d+)\s*$", user_data, re.M)
        if not m:
            raise Stop(f"{res.name}: its launch template's user data states no {key}")
        return m.group(1)

    disks = [b["Ebs"]["VolumeSize"] for b in lt.get("BlockDeviceMappings") or [] if b.get("DeviceName") == "/dev/xvda"]
    variables = [("name", res.name), ("profile", profile), ("region", aws.region), ("vpc_id", vpc),
                 ("private_subnet_ids", json.dumps(subnets))]
    for k in CLUSTER_TAG_VARS:
        if k == "role" and not tags.get(k):
            role = roster_role(FLEET / "roster.tsv", res.name)
            if role is None:
                raise Stop(f"cluster {res.name} carries no `role` tag and is not a community or admin row of roster.tsv")
            print(f"import-state: {res.name} carries no role= tag (built before #636); roster.tsv names its role {role}")
            variables.append((k, role))
        else:
            variables.append((k, one_tag(tags, k, f"cluster {res.name}")))
    variables += [("kubernetes_version", cl["version"]),
                  ("instance_types", json.dumps(ng["instanceTypes"])),
                  ("node_min_size", str(ng["scalingConfig"]["minSize"])),
                  ("node_max_size", str(ng["scalingConfig"]["maxSize"])),
                  ("node_desired_size", str(ng["scalingConfig"]["desiredSize"])),
                  ("imds_hop_limit", str(lt["MetadataOptions"]["HttpPutResponseHopLimit"])),
                  ("max_pods", kubelet("maxPods")), ("pod_pids_limit", kubelet("podPidsLimit")),
                  ("node_disk_size", str(aws.one(disks, f"{res.name}: /dev/xvda volumes in its launch template")))]
    # A node group pinned to one zone (fleet.sh roster_zone / standby_zone) names its subnet, in the lab VPC's order.
    if set(ng["subnets"]) != set(subnets):
        variables.append(("node_subnet_ids", json.dumps([s for s in subnets if s in ng["subnets"]])))
    return variables


# ---------------------------------------------------------------- provenance ------------------------------------
# What aws/cluster leaves on every cluster it builds, each read in AWS (#1043): the fixed values of main.tf's
# local.fleet_tags and its `attendee = var.name` on the cluster; the EKS module's cluster role, which it names
# `<name>-cluster-<suffix>`; its one managed node group, keyed `default`, which it names `default-<suffix>`; and
# var.vpc_id, the network root's lab VPC, which that root tags Purpose=lab-shared-vpc. A cluster made any other way
# (by hand, by lab-platform, by a co-tenant) lacks at least one. verify/test_cluster_provenance.py holds these to the
# two main.tf files, so a root that stops leaving a mark fails there rather than here.
PROVENANCE_TAGS = {"project": "watch-it-burn", "Purpose": "attendee-cluster", "ManagedBy": "terraform"}
LAB_VPC_TAG = ("Purpose", "lab-shared-vpc")
REGISTER = TF_DIR / "drift/known-unmanaged.yaml"
DRIFT_REPORT = TF_DIR / "drift/drift-report.py"


def provenance(res: ClusterResolver) -> list[tuple[str, bool, str]]:
    """Each mark aws/cluster leaves on a cluster it builds: (the mark, whether AWS shows it, what AWS holds)."""
    cl = res.cluster
    tags = cl.get("tags") or {}
    marks = [(f"tag {k}={v}", tags.get(k) == v, f"{k}={tags[k]}" if k in tags else f"no {k} tag")
             for k, v in {**PROVENANCE_TAGS, "attendee": res.name}.items()]
    role = (cl.get("roleArn") or "").rsplit("/", 1)[-1]
    marks.append((f"cluster role named {res.name}-cluster-*", role.startswith(f"{res.name}-cluster-"), role or "no role"))
    ngs = res.aws("eks", "list-nodegroups", "--cluster-name", res.name)["nodegroups"]
    default = [n for n in ngs if n.startswith("default-")]
    marks.append(("one node group named default-*", len(default) == 1, ", ".join(ngs) or "no node group"))
    vpc = (cl.get("resourcesVpcConfig") or {}).get("vpcId") or ""
    k, v = LAB_VPC_TAG
    vtags = tags_of(res.aws.one(res.aws("ec2", "describe-vpcs", "--vpc-ids", vpc)["Vpcs"], f"VPC {vpc}").get("Tags")) \
        if vpc else {}
    marks.append((f"in the lab VPC, tagged {k}={v}", vtags.get(k) == v,
                  f"{vpc} {k}={vtags[k]}" if k in vtags else f"{vpc or 'no VPC'}, no {k} tag"))
    return marks


def register_entry(profile: str, name: str, tags: dict) -> str:
    """The register entry covering this cluster, matched by drift-report.py's own reader and matcher, or ""."""
    spec = importlib.util.spec_from_file_location("drift_report", DRIFT_REPORT)
    drift = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, drift)   # its dataclasses look their module up there while it loads
    try:
        spec.loader.exec_module(drift)
        entries = drift.load_register(REGISTER)
    except Exception as e:   # drift.Incomplete for an unreadable register, ImportError without PyYAML
        raise Stop(f"cannot read the register {REGISTER}: {e}") from e
    return drift.match_register(entries, profile, "eks-cluster", name, lambda: tags)


def report_provenance(res: ClusterResolver, profile: str) -> int:
    marks = provenance(res)
    built = all(held for _, held, _ in marks)
    entry = register_entry(profile, res.name, res.cluster.get("tags") or {})
    print(f"provenance: {res.name} ({profile}, {res.aws.region})")
    for mark, held, seen in marks:
        print(f"  {'held   ' if held else 'MISSING'}  {mark}  ({seen})")
    print(f"verdict: {'built' if built else 'not built'} from infra/terraform/aws/cluster")
    print(f"choice: {'import' if built else 'register'}")
    print(f"register: {entry if entry else 'no entry covers it'}")
    follows = built != bool(entry)
    print(f"follows: {'yes' if follows else 'no'}")
    if not follows:
        print(f"provenance: {res.name} was built from aws/cluster and a register entry ({entry}) calls it unmanaged; "
              "import it and drop the entry" if built else
              f"provenance: {res.name} was not built from aws/cluster and no register entry covers it; register it in "
              f"{REGISTER.relative_to(TF_DIR.parent.parent)} with who made it and why", file=sys.stderr)
    return 0 if follows else 2


# ---------------------------------------------------------------- the rebuild -----------------------------------

def managed_in(state: pathlib.Path) -> list[str]:
    if not state.is_file() or not state.read_text().strip():
        return []
    try:
        doc = json.loads(state.read_text())
    except ValueError as e:
        raise Stop(f"{state} is not a state file: {e}") from e
    return [f"{r.get('module', '') + '.' if r.get('module') else ''}{r['type']}.{r['name']}"
            for r in doc.get("resources", []) if r.get("mode") == "managed"]


def tf(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return run(["terraform", f"-chdir={root}", *args])


def plan_json(root: pathlib.Path, state: pathlib.Path, varargs: list[str], tmp: pathlib.Path, label: str,
              refresh: bool = True) -> dict:
    out = tmp / f"{label}.tfplan"
    p = tf(root, "plan", "-input=false", "-lock=false", "-no-color", f"-state={state}", f"-out={out}",
           *([] if refresh else ["-refresh=false"]), *varargs)
    if p.returncode != 0:
        raise Stop(f"terraform plan ({label}) failed: {last_line(p.stderr or p.stdout)}")
    show = tf(root, "show", "-json", str(out))
    if show.returncode != 0:
        raise Stop(f"terraform show ({label}) failed: {last_line(show.stderr)}")
    return json.loads(show.stdout)


def write_time_sleep(state: pathlib.Path, rc: dict) -> None:
    """Add the EKS module's time_sleep to the state, its triggers read from the cluster in the same module (#979)."""
    doc = json.loads(state.read_text())
    mod = module_of(rc["address"])
    clusters = [r for r in doc["resources"] if r["mode"] == "managed" and r["type"] == "aws_eks_cluster"
                and r.get("module", "") == mod]
    if len(clusters) != 1 or len(clusters[0]["instances"]) != 1:
        raise Stop(f"{rc['address']}: the state holds {len(clusters)} clusters in {mod}, not one, to read its triggers from")
    a = clusters[0]["instances"][0]["attributes"]
    net = (a.get("kubernetes_network_config") or [{}])[0]
    m = re.fullmatch(r"(.*)\.time_sleep\.([A-Za-z0-9_-]+)\[(\d+)\]", rc["address"])
    if not m or m.group(1) != mod:
        raise Stop(f"{rc['address']}: not a counted time_sleep in a module")
    after = rc["change"]["after"] or {}
    doc["resources"].append({
        "module": mod, "mode": "managed", "type": "time_sleep", "name": m.group(2),
        "provider": 'provider["registry.terraform.io/hashicorp/time"]',
        "instances": [{"index_key": int(m.group(3)), "schema_version": 0, "sensitive_attributes": [],
                       "dependencies": [f"{mod}.aws_eks_cluster.this"],
                       "attributes": {
                           "create_duration": after.get("create_duration"), "destroy_duration": after.get("destroy_duration"),
                           "id": a.get("created_at") or "", "triggers": {
                               "name": a["id"], "endpoint": a["endpoint"], "kubernetes_version": a["version"],
                               "service_cidr": net.get("service_ipv6_cidr" if net.get("ip_family") == "ipv6"
                                                       else "service_ipv4_cidr", ""),
                               "certificate_authority_data": a["certificate_authority"][0]["data"]}}}]})
    doc["serial"] = doc.get("serial", 0) + 1
    state.write_text(json.dumps(doc, indent=2) + "\n")


def state_addresses(root: pathlib.Path, state: pathlib.Path) -> set[str]:
    if not state.is_file():
        return set()
    p = tf(root, "state", "list", f"-state={state}")
    if p.returncode != 0:
        raise Stop(f"terraform state list {state}: {last_line(p.stderr)}")
    return {ln.strip() for ln in p.stdout.splitlines() if ln.strip()}


def rebuild(kind: str, state: pathlib.Path, variables: list[tuple[str, str]], resolver: Resolver,
            resolve_only: bool = False, resume: bool = False) -> int:
    root = ROOTS[kind]
    if not (root / ".terraform").is_dir():
        raise Stop(f"{root} is not initialised: run 'terraform -chdir={root} init' first")
    held = managed_in(state)
    if held and not resume:
        raise Stop(f"{state} already manages resources; refusing to import over it (--resume carries on a rebuild "
                   "this script stopped):\n  " + "\n  ".join(held))
    done = state_addresses(root, state) if resume else set()
    varargs = [a for k, v in variables for a in ("-var", f"{k}={v}")]
    print(f"import-state: {kind} -> {state}")
    print("import-state: variables " + " ".join(f"{k}={v}" for k, v in variables))
    with tempfile.TemporaryDirectory(prefix="wib-import-") as t:
        tmp = pathlib.Path(t)
        first = plan_json(root, tmp / "empty.tfstate", varargs, tmp, "empty")
        planned = [rc for rc in first.get("resource_changes", []) if rc["mode"] == "managed"]
        odd = [rc["address"] for rc in planned if rc["change"]["actions"] != ["create"]]
        if odd:
            raise Stop(f"a plan against an empty state should only create, and it does more for {odd}")
        imports, skipped, absent, written = [], [], [], []
        for rc in planned:
            if rc["type"] in NOT_IMPORTABLE:
                skipped.append(rc["address"])
                continue
            if rc["type"] in WRITTEN:
                written.append(rc)
                continue
            if rc["address"] in done:
                print(f"import-state: already in the state (--resume): {rc['address']}")
                continue
            try:
                imports.append((rc["address"], resolver.resolve(rc, planned)))
            except Absent as e:
                absent.append(rc["address"])
                print(f"import-state: not in AWS, so not imported: {rc['address']}: {e}")
        print(f"import-state: {len(imports)} to import, {len(absent)} not in AWS, {len(written)} written after the "
              f"imports, {len(skipped)} not importable ({', '.join(skipped) or 'none'})")
        if resolve_only:
            for addr, rid in imports:
                print(f"import-state: would import {addr} <- {rid}")
            print("import-state: --resolve-only, so nothing was imported and no state was written")
            return 0
        state.parent.mkdir(parents=True, exist_ok=True)
        for addr, rid in imports:
            print(f"import-state: {addr} <- {rid}")
            p = tf(root, "import", "-input=false", "-no-color", f"-state={state}", *varargs, addr, rid)
            if p.returncode != 0:
                raise Stop(f"import of {addr} ({rid}) failed: {last_line(p.stderr or p.stdout)}; "
                           f"{state} holds the imports before it")
        for rc in written:
            if rc["address"] in done:
                continue
            print(f"import-state: {rc['address']} written from the imported cluster")
            write_time_sleep(state, rc)
        # The settle step docs/floor.md gives after an apply: it writes what AWS reads back and changes nothing in AWS.
        p = tf(root, "apply", "-input=false", "-no-color", "-refresh-only", "-auto-approve", f"-state={state}", *varargs)
        if p.returncode != 0:
            raise Stop(f"the refresh-only apply failed: {last_line(p.stderr or p.stdout)}")
        last = plan_json(root, state, varargs, tmp, "after")
    pending = [changed(rc) for rc in last.get("resource_changes", [])
               if rc["mode"] == "managed" and rc["change"]["actions"] not in (["no-op"], ["read"])
               and not (rc["type"] in NOT_IMPORTABLE and rc["change"]["actions"] == ["create"])]
    pending += [f"{a} (not in the state)" for a in written_missing(root, state, written)]
    if not pending:
        print(f"import-state: {state} rebuilt; plan: no changes")
        return 0
    print(f"import-state: {state} rebuilt; the plan still has {len(pending)} change(s), configuration the resources "
          "were not built with, which the next apply makes:")
    for line in pending:
        print(f"  {line}")
    return 2


def changed(rc: dict) -> str:
    """`address (update: attr, attr)`: the top-level attributes a planned change touches, so the last plan's list says
    what each change is without a second plan. A replace names the attributes that force it."""
    ch = rc["change"]
    before, after, unknown = ch.get("before") or {}, ch.get("after") or {}, ch.get("after_unknown") or {}
    if ch.get("replace_paths"):
        attrs = sorted({str(path[0]) for path in ch["replace_paths"] if path})
    else:
        attrs = sorted(k for k in set(before) | set(after) if k not in ("tags_all",) and
                       (before.get(k) != after.get(k) or unknown.get(k) is True))
        if not attrs and before.get("tags_all") != after.get("tags_all"):
            attrs = ["tags_all"]
    actions = "/".join(ch["actions"])
    return f"{rc['address']} ({actions}{': ' + ', '.join(attrs) if attrs and ch['actions'] != ['create'] else ''})"


def written_missing(root: pathlib.Path, state: pathlib.Path, written: list[dict]) -> list[str]:
    held = state_addresses(root, state)
    return [rc["address"] for rc in written if rc["address"] not in held]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kind", choices=sorted(ROOTS) + ["provenance"])
    ap.add_argument("profile", help="the fleet account's AWS profile, passed explicitly")
    ap.add_argument("name", nargs="?", help="the cluster's name (cluster only)")
    ap.add_argument("--region", help="default: fleet.sh's WIB_REGION")
    ap.add_argument("--resume", action="store_true",
                    help="carry on a rebuild this script stopped: import only what the state does not hold yet")
    ap.add_argument("--resolve-only", action="store_true",
                    help="find every import id and print them; import nothing and write no state")
    args = ap.parse_args(argv)
    getattr(sys.stdout, "reconfigure", lambda **_: None)(line_buffering=True)   # a rebuild takes half an hour; its log shows each import as it goes
    try:
        region = args.region or setting("WIB_REGION")
        if args.kind == "network" and region != setting("WIB_REGION"):
            raise Stop(f"a lab VPC outside the home region ({setting('WIB_REGION')}) is not rebuilt by this script")
        if (args.kind in ("cluster", "provenance")) != bool(args.name):
            raise Stop("a cluster name is given with `cluster` or `provenance` and only with them")
        if args.kind == "provenance" and (args.resume or args.resolve_only):
            raise Stop("provenance imports nothing: --resume and --resolve-only are for a rebuild")
        aws = AWS(args.profile, region)
        account = aws("sts", "get-caller-identity")["Account"]
        if not re.fullmatch(r"\d{12}", account):
            raise Stop(f"profile {args.profile} gave account {account!r}, not a 12-digit id")
        print(f"import-state: account {account} ({args.profile}), {region}")
        if args.kind == "boundary":
            name = "watch-it-burn-permissions-boundary"
            arn = f"arn:aws:iam::{account}:policy/{name}"
            event = one_tag(tags_of(aws("iam", "list-policy-tags", "--policy-arn", arn)["Tags"]), "event", name)
            return rebuild("boundary", ROOTS["boundary"] / f"states/{args.profile}.tfstate",
                           [("profile", args.profile), ("region", region), ("event", event)],
                           BoundaryResolver(aws, account), args.resolve_only, args.resume)
        if args.kind == "network":
            res = NetworkResolver(aws, account, "watch-it-burn-lab-vpc")
            vpc = aws("ec2", "describe-vpcs", "--vpc-ids", res.vpc)["Vpcs"][0]
            event = one_tag(tags_of(vpc.get("Tags")), "event", f"lab VPC {res.vpc}")
            return rebuild("network", network_state(args.profile),
                           [("profile", args.profile), ("region", region), ("event", event)], res, args.resolve_only, args.resume)
        if args.kind == "provenance":   # any cluster in the account: one the fleet did not build reads as not built
            return report_provenance(ClusterResolver(aws, account, args.name), args.profile)
        if not args.name.startswith("watch-it-burn-"):
            raise Stop(f"{args.name} is not a watch-it-burn-* cluster; the fleet builds no other")
        res = ClusterResolver(aws, account, args.name)
        missing = [f"{mark} ({seen})" for mark, held, seen in provenance(res) if not held]
        if missing:
            raise Stop(f"{args.name} was not built from aws/cluster: AWS shows no {'; no '.join(missing)}. A cluster the "
                       f"root did not build is registered in {REGISTER.relative_to(TF_DIR.parent.parent)}, not imported "
                       "(docs/floor.md, The unmanaged register; import-state.py provenance)")
        variables = cluster_vars(aws, res, args.profile)
        rc = rebuild("cluster", STATE_DIR / f"{args.name}.tfstate", variables, res, args.resolve_only, args.resume)
        if not args.resolve_only:
            (STATE_DIR / f"{args.name}.account").write_text(f"{args.profile}\n")   # fleet.sh's record_membership
        return rc
    except Stop as e:
        print(f"import-state: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
