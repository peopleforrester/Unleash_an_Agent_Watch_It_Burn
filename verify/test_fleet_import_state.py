# ABOUTME: Offline check of infra/terraform/fleet/import-state.py (#979): each planned resource gets the import id the
# ABOUTME: AWS objects give it, a rule AWS lacks is left for the next apply, and a live state or a doubt stops it first.
"""Offline: python3 and the repo. The script is loaded as a module and its one subprocess door, `run`, is replaced by
a fake that answers `aws` from a small world written here and `terraform` from plans written here, so nothing reaches
an account, and its roots and state directory point into a temp dir, so the repo's gitignored states are never read
or written.

The world is the shape the KubeCon clusters had on 2026-11-06 (run 17958): the module's roles and groups named with a
random suffix, a pod identity role found only through its association, a cluster API rule from the node group and a
hand-made one from another cluster's nodes on the same port, and the #906 lab-VPC rule committed after the build and
missing from AWS. A resource type the roots plan that the script has no rule for would stop a real rebuild halfway
through a resolve; so the types the three roots planned live (fixtures/import-state/planned-types.txt) are held to the
script's rules here, as are the resource types main.tf declares at top level.
"""
from __future__ import annotations

import base64
import contextlib
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
TYPES = REPO / "verify/fixtures/import-state/planned-types.txt"
ACCOUNT = "123456789012"
NAME = "watch-it-burn-t1"
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


# ---------------------------------------------------------------- the world -------------------------------------

def rc(address: str, rtype: str, **after) -> dict:
    return {"address": address, "mode": "managed", "type": rtype, "change": {"actions": ["create"], "after": after}}


NG = 'module.eks.module.eks_managed_node_group["default"]'
PLANNED = [
    rc("module.eks.aws_eks_cluster.this[0]", "aws_eks_cluster", name=NAME),
    rc("module.eks.aws_iam_role.this[0]", "aws_iam_role", name_prefix=f"{NAME}-cluster-"),
    rc('module.eks.aws_iam_role_policy_attachment.this["AmazonEKSClusterPolicy"]', "aws_iam_role_policy_attachment",
       policy_arn="arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"),
    rc("module.eks.aws_iam_role_policy_attachment.cluster_encryption[0]", "aws_iam_role_policy_attachment"),
    rc("module.eks.aws_iam_policy.cluster_encryption[0]", "aws_iam_policy", name_prefix=f"{NAME}-cluster-ClusterEncryption"),
    rc('module.eks.aws_eks_addon.this["coredns"]', "aws_eks_addon", addon_name="coredns"),
    rc('module.eks.aws_eks_access_entry.this["cluster_creator"]', "aws_eks_access_entry",
       principal_arn=f"arn:aws:iam::{ACCOUNT}:user/op"),
    rc('module.eks.aws_eks_access_policy_association.this["cluster_creator_admin"]', "aws_eks_access_policy_association",
       principal_arn=f"arn:aws:iam::{ACCOUNT}:user/op",
       policy_arn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"),
    rc("module.eks.aws_security_group.cluster[0]", "aws_security_group", name_prefix=f"{NAME}-cluster-"),
    rc("module.eks.aws_security_group.node[0]", "aws_security_group", name_prefix=f"{NAME}-node-"),
    rc('module.eks.aws_security_group_rule.cluster["ingress_nodes_443"]', "aws_security_group_rule", type="ingress",
       protocol="tcp", from_port=443, to_port=443, description="Node groups to cluster API", self=False),
    rc('module.eks.aws_security_group_rule.cluster["ingress_lab_vpc_443_api"]', "aws_security_group_rule",
       type="ingress", protocol="tcp", from_port=443, to_port=443, cidr_blocks=["10.0.0.0/16"], description="Lab VPC"),
    rc('module.eks.aws_security_group_rule.node["egress_all"]', "aws_security_group_rule", type="egress",
       protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"], self=False, description="Allow all egress"),
    rc('module.eks.aws_security_group_rule.node["ingress_self_coredns_udp"]', "aws_security_group_rule",
       type="ingress", protocol="udp", from_port=53, to_port=53, self=True, description="Node to node CoreDNS UDP"),
    rc('module.eks.aws_security_group_rule.node["ingress_cluster_8080_workshop_apps"]', "aws_security_group_rule",
       type="ingress", protocol="tcp", from_port=8080, to_port=8080, self=False, description="Cluster API to node 8080"),
    rc("module.eks.time_sleep.this[0]", "time_sleep", create_duration="30s"),
    rc("module.eks.module.kms.aws_kms_key.this[0]", "aws_kms_key"),
    rc('module.eks.module.kms.aws_kms_alias.this["cluster"]', "aws_kms_alias", name=f"alias/eks/{NAME}"),
    rc(f"{NG}.aws_eks_node_group.this[0]", "aws_eks_node_group", node_group_name_prefix="default-"),
    rc(f"{NG}.aws_iam_role.this[0]", "aws_iam_role", name_prefix="default-eks-node-group-"),
    rc(f'{NG}.aws_iam_role_policy_attachment.this["AmazonEKS_CNI_Policy"]', "aws_iam_role_policy_attachment",
       policy_arn="arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"),
    rc(f"{NG}.aws_launch_template.this[0]", "aws_launch_template", name_prefix="default-"),
    rc(f"{NG}.module.user_data.null_resource.validate_cluster_service_cidr", "null_resource"),
    rc("module.agent_bedrock_pod_identity.aws_iam_role.this[0]", "aws_iam_role", name_prefix=f"{NAME}-bedrock-"),
    rc('module.agent_bedrock_pod_identity.aws_iam_role_policy_attachment.this["bedrock"]', "aws_iam_role_policy_attachment"),
    rc('module.agent_bedrock_pod_identity.aws_eks_pod_identity_association.this["main"]',
       "aws_eks_pod_identity_association", cluster_name=NAME, namespace="agent", service_account="agent-sa"),
    rc('module.agent_bedrock_pod_identity.aws_eks_pod_identity_association.this["gateway"]',
       "aws_eks_pod_identity_association", cluster_name=NAME, namespace="agent", service_account="agentgateway"),
    rc("module.ebs_csi_pod_identity.aws_iam_policy.ebs_csi[0]", "aws_iam_policy", name_prefix="AmazonEKS_EBS_CSI-"),
    rc("module.ebs_csi_pod_identity.aws_iam_role.this[0]", "aws_iam_role", name_prefix=f"{NAME}-ebs-csi-"),
    rc("module.ebs_csi_pod_identity.aws_iam_role_policy_attachment.ebs_csi[0]", "aws_iam_role_policy_attachment"),
    rc('module.ebs_csi_pod_identity.aws_eks_pod_identity_association.this["main"]', "aws_eks_pod_identity_association",
       cluster_name=NAME, namespace="kube-system", service_account="ebs-csi-controller-sa"),
    rc("aws_iam_policy.bedrock_invoke", "aws_iam_policy", name=f"{NAME}-bedrock-invoke"),
    rc('aws_bedrock_inference_profile.agent["nova"]', "aws_bedrock_inference_profile", name=f"{NAME}-nova"),
    rc("aws_iam_user.attendee", "aws_iam_user", name="wib-t1"),
    rc("aws_iam_user_policy.attendee_eks", "aws_iam_user_policy", name="eks-own-cluster", user="wib-t1"),
    rc("aws_eks_access_entry.attendee", "aws_eks_access_entry", cluster_name=NAME, type="STANDARD"),
    rc("aws_eks_access_policy_association.attendee_admin", "aws_eks_access_policy_association", cluster_name=NAME,
       policy_arn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"),
]

EXPECTED = {
    "module.eks.aws_eks_cluster.this[0]": NAME,
    "module.eks.aws_iam_role.this[0]": f"{NAME}-cluster-abc",
    'module.eks.aws_iam_role_policy_attachment.this["AmazonEKSClusterPolicy"]':
        f"{NAME}-cluster-abc/arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
    "module.eks.aws_iam_role_policy_attachment.cluster_encryption[0]":
        f"{NAME}-cluster-abc/arn:aws:iam::{ACCOUNT}:policy/{NAME}-cluster-ClusterEncryption123",
    "module.eks.aws_iam_policy.cluster_encryption[0]": f"arn:aws:iam::{ACCOUNT}:policy/{NAME}-cluster-ClusterEncryption123",
    'module.eks.aws_eks_addon.this["coredns"]': f"{NAME}:coredns",
    'module.eks.aws_eks_access_entry.this["cluster_creator"]': f"{NAME}:arn:aws:iam::{ACCOUNT}:user/op",
    'module.eks.aws_eks_access_policy_association.this["cluster_creator_admin"]':
        f"{NAME}#arn:aws:iam::{ACCOUNT}:user/op#arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy",
    "module.eks.aws_security_group.cluster[0]": "sg-cluster",
    "module.eks.aws_security_group.node[0]": "sg-node",
    'module.eks.aws_security_group_rule.cluster["ingress_nodes_443"]': "sg-cluster_ingress_tcp_443_443_sg-node",
    'module.eks.aws_security_group_rule.node["egress_all"]': "sg-node_egress_all_0_0_0.0.0.0/0",
    'module.eks.aws_security_group_rule.node["ingress_self_coredns_udp"]': "sg-node_ingress_udp_53_53_self",
    "module.eks.time_sleep.this[0]": "30s,",
    "module.eks.module.kms.aws_kms_key.this[0]": "key-1",
    'module.eks.module.kms.aws_kms_alias.this["cluster"]': f"alias/eks/{NAME}",
    f"{NG}.aws_eks_node_group.this[0]": f"{NAME}:default-ng1",
    f"{NG}.aws_iam_role.this[0]": "default-eks-node-group-n1",
    f'{NG}.aws_iam_role_policy_attachment.this["AmazonEKS_CNI_Policy"]':
        "default-eks-node-group-n1/arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    f"{NG}.aws_launch_template.this[0]": "lt-1",
    "module.agent_bedrock_pod_identity.aws_iam_role.this[0]": f"{NAME}-bedrock-r1",
    'module.agent_bedrock_pod_identity.aws_iam_role_policy_attachment.this["bedrock"]':
        f"{NAME}-bedrock-r1/arn:aws:iam::{ACCOUNT}:policy/{NAME}-bedrock-invoke",
    'module.agent_bedrock_pod_identity.aws_eks_pod_identity_association.this["main"]': f"{NAME},a-agent",
    'module.agent_bedrock_pod_identity.aws_eks_pod_identity_association.this["gateway"]': f"{NAME},a-gw",
    "module.ebs_csi_pod_identity.aws_iam_policy.ebs_csi[0]": f"arn:aws:iam::{ACCOUNT}:policy/AmazonEKS_EBS_CSI-e1",
    "module.ebs_csi_pod_identity.aws_iam_role.this[0]": f"{NAME}-ebs-csi-r2",
    "module.ebs_csi_pod_identity.aws_iam_role_policy_attachment.ebs_csi[0]":
        f"{NAME}-ebs-csi-r2/arn:aws:iam::{ACCOUNT}:policy/AmazonEKS_EBS_CSI-e1",
    'module.ebs_csi_pod_identity.aws_eks_pod_identity_association.this["main"]': f"{NAME},a-ebs",
    "aws_iam_policy.bedrock_invoke": f"arn:aws:iam::{ACCOUNT}:policy/{NAME}-bedrock-invoke",
    'aws_bedrock_inference_profile.agent["nova"]': "ip-nova",
    "aws_iam_user.attendee": "wib-t1",
    "aws_iam_user_policy.attendee_eks": "wib-t1:eks-own-cluster",
    "aws_eks_access_entry.attendee": f"{NAME}:arn:aws:iam::{ACCOUNT}:user/wib-t1",
    "aws_eks_access_policy_association.attendee_admin":
        f"{NAME}#arn:aws:iam::{ACCOUNT}:user/wib-t1#arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy",
}
ABSENT = {'module.eks.aws_security_group_rule.cluster["ingress_lab_vpc_443_api"]',
          'module.eks.aws_security_group_rule.node["ingress_cluster_8080_workshop_apps"]'}

USER_DATA = base64.b64encode(b"MIME-Version: 1.0\n--b\nContent-Type: application/node.eks.aws\n\nspec:\n  kubelet:\n"
                             b"    config:\n      maxPods: 250\n      podPidsLimit: -1\n--b--\n").decode()


def rule(egress, proto, frm, to, cidr=None, ref=None, desc=""):
    r = {"IsEgress": egress, "IpProtocol": proto, "FromPort": frm, "ToPort": to, "Description": desc}
    if cidr:
        r["CidrIpv4"] = cidr
    if ref:
        r["ReferencedGroupInfo"] = {"GroupId": ref}
    return r


def attached(*arns):
    return {"AttachedPolicies": [{"PolicyArn": a, "PolicyName": a.rsplit("/", 1)[1]} for a in arns]}


def assoc(aid, ns, sa, role):
    return {"association": {"associationId": aid, "namespace": ns, "serviceAccount": sa,
                            "roleArn": f"arn:aws:iam::{ACCOUNT}:role/{role}"}}


def world(node_sgs: int = 1, ng_subnets=("subnet-a",)) -> dict:
    op, att = f"arn:aws:iam::{ACCOUNT}:user/op", f"arn:aws:iam::{ACCOUNT}:user/wib-t1"
    admin = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
    w = {
        "sts get-caller-identity": {"Account": ACCOUNT},
        f"eks describe-cluster --name {NAME}": {"cluster": {
            "name": NAME, "version": "1.36", "roleArn": f"arn:aws:iam::{ACCOUNT}:role/{NAME}-cluster-abc",
            "tags": {"event": "kubecon-na-2026", "hostname": "attackme.agenticburn.com", "role": "community"},
            "resourcesVpcConfig": {"vpcId": "vpc-1", "subnetIds": ["subnet-b", "subnet-a"],
                                   "securityGroupIds": ["sg-cluster"]}}},
        f"eks list-nodegroups --cluster-name {NAME}": {"nodegroups": ["default-ng1"]},
        f"eks describe-nodegroup --cluster-name {NAME} --nodegroup-name default-ng1": {"nodegroup": {
            "nodegroupName": "default-ng1", "nodeRole": f"arn:aws:iam::{ACCOUNT}:role/default-eks-node-group-n1",
            "launchTemplate": {"id": "lt-1", "version": "2"}, "subnets": list(ng_subnets),
            "instanceTypes": ["t3.2xlarge"], "scalingConfig": {"minSize": 1, "maxSize": 1, "desiredSize": 1}}},
        "ec2 describe-launch-template-versions --launch-template-id lt-1 --versions 2": {"LaunchTemplateVersions": [
            {"LaunchTemplateData": {"UserData": USER_DATA, "MetadataOptions": {"HttpPutResponseHopLimit": 2},
                                    "BlockDeviceMappings": [{"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 100}}]}}]},
        f"iam list-attached-role-policies --role-name {NAME}-cluster-abc": attached(
            "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
            f"arn:aws:iam::{ACCOUNT}:policy/{NAME}-cluster-ClusterEncryption123"),
        "iam list-attached-role-policies --role-name default-eks-node-group-n1": attached(
            "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"),
        f"iam list-attached-role-policies --role-name {NAME}-bedrock-r1": attached(
            f"arn:aws:iam::{ACCOUNT}:policy/{NAME}-bedrock-invoke"),
        f"iam list-attached-role-policies --role-name {NAME}-ebs-csi-r2": attached(
            f"arn:aws:iam::{ACCOUNT}:policy/AmazonEKS_EBS_CSI-e1"),
        f"iam get-policy --policy-arn arn:aws:iam::{ACCOUNT}:policy/{NAME}-bedrock-invoke": {},
        f"eks describe-addon --cluster-name {NAME} --addon-name coredns": {},
        f"eks describe-access-entry --cluster-name {NAME} --principal-arn {op}": {},
        f"eks describe-access-entry --cluster-name {NAME} --principal-arn {att}": {},
        f"eks list-associated-access-policies --cluster-name {NAME} --principal-arn {op}":
            {"associatedAccessPolicies": [{"policyArn": admin}]},
        f"eks list-associated-access-policies --cluster-name {NAME} --principal-arn {att}":
            {"associatedAccessPolicies": [{"policyArn": admin}]},
        f"ec2 describe-security-groups --filters Name=vpc-id,Values=vpc-1 Name=group-name,Values={NAME}-node-*":
            {"SecurityGroups": [{"GroupId": "sg-node"}] + [{"GroupId": "sg-node2"}] * (node_sgs - 1)},
        "ec2 describe-security-group-rules --filters Name=group-id,Values=sg-cluster": {"SecurityGroupRules": [
            rule(False, "tcp", 443, 443, ref="sg-other-node", desc="other cluster nodes to this API (#906)"),
            rule(False, "tcp", 443, 443, ref="sg-node", desc="Node groups to cluster API")]},
        "ec2 describe-security-group-rules --filters Name=group-id,Values=sg-node": {"SecurityGroupRules": [
            rule(True, "-1", -1, -1, cidr="0.0.0.0/0", desc="Allow all egress"),
            rule(False, "udp", 53, 53, ref="sg-node", desc="Node to node CoreDNS UDP"),
            rule(False, "tcp", 8080, 8443, ref="sg-lb", desc="elbv2.k8s.aws/targetGroupBinding=shared")]},
        f"kms describe-key --key-id alias/eks/{NAME}": {"KeyMetadata": {"KeyId": "key-1"}},
        f"eks list-pod-identity-associations --cluster-name {NAME}": {"associations": [
            {"associationId": "a-agent", "namespace": "agent", "serviceAccount": "agent-sa"},
            {"associationId": "a-gw", "namespace": "agent", "serviceAccount": "agentgateway"},
            {"associationId": "a-ebs", "namespace": "kube-system", "serviceAccount": "ebs-csi-controller-sa"}]},
        f"eks describe-pod-identity-association --cluster-name {NAME} --association-id a-agent":
            assoc("a-agent", "agent", "agent-sa", f"{NAME}-bedrock-r1"),
        f"eks describe-pod-identity-association --cluster-name {NAME} --association-id a-gw":
            assoc("a-gw", "agent", "agentgateway", f"{NAME}-bedrock-r1"),
        f"eks describe-pod-identity-association --cluster-name {NAME} --association-id a-ebs":
            assoc("a-ebs", "kube-system", "ebs-csi-controller-sa", f"{NAME}-ebs-csi-r2"),
        "bedrock list-inference-profiles --type-equals APPLICATION": {"inferenceProfileSummaries": [
            {"inferenceProfileName": f"{NAME}-nova", "inferenceProfileId": "ip-nova"},
            {"inferenceProfileName": "watch-it-burn-other-nova", "inferenceProfileId": "ip-other"}]},
        "iam get-user --user-name wib-t1": {"User": {"Arn": att}},
        "iam get-user-policy --user-name wib-t1 --policy-name eks-own-cluster": {},
    }
    return w


class Fake:
    """`run` for the script: aws answers from the world, terraform from the plans; every call is logged."""

    def __init__(self, w: dict, after: list[dict], import_fail: str = ""):
        self.w, self.after, self.import_fail, self.calls = w, after, import_fail, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        ok = lambda out="": subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[0] == "aws":
            args = cmd[1:cmd.index("--profile")]
            key = " ".join(args)
            if key not in self.w:
                return subprocess.CompletedProcess(cmd, 255, "", f"fake aws: no answer for {key}")
            return ok(json.dumps(self.w[key]))
        args = cmd[2:]
        if args[0] == "plan":
            out = next(a for a in args if a.startswith("-out="))[5:]
            pathlib.Path(out).write_text("plan")
            return ok()
        if args[0] == "show":
            first = pathlib.Path(args[-1]).name.startswith("empty")
            return ok(json.dumps({"resource_changes": PLANNED if first else self.after}))
        if args[0] == "import":
            if self.import_fail and self.import_fail in args:
                return subprocess.CompletedProcess(cmd, 1, "", "Error: Cannot import non-existent remote object")
            return ok()
        return ok()


def layout(mod, tmp: pathlib.Path, state: str | None = None) -> pathlib.Path:
    for kind in ("boundary", "network", "cluster"):
        mod.ROOTS[kind] = tmp / kind
        (tmp / kind / ".terraform").mkdir(parents=True)
    mod.STATE_DIR = tmp / "states"
    (tmp / "network/terraform.tfstate").write_text(json.dumps({"outputs": {
        "vpc_id": {"value": "vpc-1"}, "private_subnet_ids": {"value": ["subnet-a", "subnet-b"]}}}))
    if state is not None:
        mod.STATE_DIR.mkdir()
        (mod.STATE_DIR / f"{NAME}.tfstate").write_text(state)
    return mod.STATE_DIR / f"{NAME}.tfstate"


def case(w: dict, after: list[dict], *, state: str | None = None, extra: tuple = (), import_fail: str = ""):
    mod = load()
    fake = Fake(w, after, import_fail)
    mod.run = fake
    with tempfile.TemporaryDirectory() as t:
        st = layout(mod, pathlib.Path(t), state)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = mod.main(["cluster", "accen-dev", NAME, *extra])
        account = st.with_suffix(".account")
        written = account.read_text() if account.is_file() else None
    imports = {c[-2]: c[-1] for c in fake.calls if c[0] == "terraform" and c[2] == "import"}
    return code, fake, imports, written


def tf_verb(fake: Fake, verb: str) -> list[list[str]]:
    return [c for c in fake.calls if c[0] == "terraform" and c[2] == verb]


# ---------------------------------------------------------------- checks -----------------------------------------

print("A cluster rebuilt from a world with two rules missing:")
NOOP = [dict(r, change={"actions": ["no-op"], "after": {}}) for r in PLANNED if r["type"] != "null_resource"]
PENDING = [dict(r, change={"actions": ["create"], "after": {}}) for r in PLANNED
           if r["address"] in ABSENT or r["type"] == "null_resource"]
code, fake, imports, account = case(world(), NOOP + PENDING)
check("every importable resource is imported with the id AWS gives it", imports == EXPECTED,
      f"wrong: {sorted(set(imports.items()) ^ set(EXPECTED.items()))[:4]}")
check("the two rules AWS lacks are not imported", not (ABSENT & set(imports)))
check("the null_resource is not imported", not any("null_resource" in a for a in imports))
check("the rebuild exits 2: the state is rebuilt and the plan still creates the missing rules", code == 2, f"exit {code}")
check("the membership file names the profile, as fleet.sh's record_membership does", account == "accen-dev\n")
plan = tf_verb(fake, "plan")[0]
vs = dict(plan[i + 1].split("=", 1) for i, a in enumerate(plan) if a == "-var")
check("variables come from AWS: tags, launch template and node group",
      (vs.get("event"), vs.get("hostname"), vs.get("role"), vs.get("imds_hop_limit"), vs.get("max_pods"),
       vs.get("pod_pids_limit"), vs.get("node_disk_size")) ==
      ("kubecon-na-2026", "attackme.agenticburn.com", "community", "2", "250", "-1", "100"), f"{vs}")
check("a node group pinned to one zone passes node_subnet_ids", vs.get("node_subnet_ids") == '["subnet-a"]')
check("the subnets are the lab VPC state's, in its order", vs.get("private_subnet_ids") == '["subnet-a", "subnet-b"]')
applies = tf_verb(fake, "apply")
check("the only apply is the refresh-only settle", len(applies) == 1 and "-refresh-only" in applies[0], f"{applies}")
order = [c[2] for c in fake.calls if c[0] == "terraform"]
check("every import comes after both lookups and before the settle",
      order.index("import") > order.index("show") and order.index("apply") > max(i for i, v in enumerate(order) if v == "import"))

print("The same world, its plan clean but for the null_resource:")
code, *_ = case(world(), NOOP + [r for r in PENDING if r["type"] == "null_resource"])
check("exit 0", code == 0, f"exit {code}")

print("A node group spread over every lab subnet:")
code, fake, _, _ = case(world(ng_subnets=("subnet-b", "subnet-a")), NOOP)
plan = tf_verb(fake, "plan")[0]
check("passes no node_subnet_ids", not any(a.startswith("node_subnet_ids=") for a in plan))

print("Refusals, each before any import:")
live = json.dumps({"resources": [{"mode": "data", "type": "aws_vpc", "name": "lab"},
                                 {"mode": "managed", "type": "aws_eks_cluster", "name": "this", "module": "module.eks"}]})
code, fake, imports, account = case(world(), NOOP, state=live)
check("a state that manages a resource is refused", code == 1 and not imports and not tf_verb(fake, "plan"))
check("and no membership file is written", account is None)
code, fake, imports, _ = case(world(), NOOP, state=json.dumps({"resources": [{"mode": "data", "type": "x", "name": "y"}]}))
check("a state holding only data sources is rebuilt", code == 0 and imports == EXPECTED, f"exit {code}")
code, fake, imports, _ = case(world(node_sgs=2), NOOP)
check("two node groups' security groups stop the resolve, naming them", code == 1 and not imports)
w = world()
del w[f"eks describe-access-entry --cluster-name {NAME} --principal-arn arn:aws:iam::{ACCOUNT}:user/wib-t1"]
code, fake, imports, _ = case(w, NOOP)
check("a resource AWS cannot answer for stops the resolve (it is not taken as absent)", code == 1 and not imports)
code, fake, imports, account = case(world(), NOOP, extra=("--resolve-only",))
check("--resolve-only imports nothing, applies nothing and writes no membership file",
      code == 0 and not imports and not tf_verb(fake, "apply") and account is None)
code, fake, imports, _ = case(world(), NOOP, import_fail="aws_iam_user.attendee")
check("a failed import stops the rebuild before the settle", code == 1 and not tf_verb(fake, "apply"))

print("A cluster built before #636, with no role tag:")
w = world()
del w[f"eks describe-cluster --name {NAME}"]["cluster"]["tags"]["role"]
code, fake, imports, _ = case(w, NOOP)
check("one that is not a roster row stops before any import", code == 1 and not imports and not tf_verb(fake, "plan"))
mod = load()
roster = REPO / "infra/terraform/fleet/roster.tsv"
if "watch-it-burn-private|admin|" not in roster.read_text(encoding="utf-8"):
    sys.exit(f"anchor missing: 'watch-it-burn-private|admin|' is not in {roster}; the role check below reads it")
check("watch-it-burn-private takes its roster.tsv role, admin", mod.roster_role(roster, "watch-it-burn-private") == "admin")
check("watch-it-burn-community takes community", mod.roster_role(roster, "watch-it-burn-community") == "community")
check("a seat is not a roster row", mod.roster_role(roster, "watch-it-burn-attendee-001") is None)

print("Usage:")
mod = load()
mod.run = Fake(world(), NOOP)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    codes = (mod.main(["cluster", "accen-dev", "packt-cluster"]), mod.main(["network", "accen-dev", NAME]))
check("a cluster outside the fleet's names is refused", codes[0] == 1)
check("network with a cluster name is refused", codes[1] == 1)

print("Network and boundary ids:")
mod = load()


class W:
    region = "us-west-2"

    def __init__(self, w):
        self.w = w

    def __call__(self, *args, ok_errors=()):
        return self.w[" ".join(args)]

    one = mod.AWS.one


net = mod.NetworkResolver(W({
    "ec2 describe-vpcs --filters Name=tag:Name,Values=lab": {"Vpcs": [{"VpcId": "vpc-1"}]},
    "ec2 describe-subnets --filters Name=vpc-id,Values=vpc-1": {"Subnets": [
        {"SubnetId": "subnet-a", "CidrBlock": "10.0.0.0/18"}, {"SubnetId": "subnet-p", "CidrBlock": "10.0.128.0/24"}]},
    "ec2 describe-route-tables --filters Name=vpc-id,Values=vpc-1": {"RouteTables": [
        {"RouteTableId": "rtb-priv", "Tags": [{"Key": "Name", "Value": "lab-private"}]},
        {"RouteTableId": "rtb-pub", "Tags": [{"Key": "Name", "Value": "lab-public"}]}]},
    "ec2 describe-nat-gateways --filter Name=vpc-id,Values=vpc-1 Name=state,Values=available": {"NatGateways": [
        {"NatGatewayId": "nat-1", "NatGatewayAddresses": [{"AllocationId": "eipalloc-1"}]}]},
    f"budgets describe-budget --account-id {ACCOUNT} --budget-name b": {},
}), ACCOUNT, "lab")
net_planned = [rc("module.vpc.aws_subnet.private[0]", "aws_subnet", cidr_block="10.0.0.0/18"),
               rc("module.vpc.aws_route_table.private[0]", "aws_route_table", tags={"Name": "lab-private"}),
               rc("module.vpc.aws_subnet.public[0]", "aws_subnet", cidr_block="10.0.128.0/24"),
               rc("module.vpc.aws_route_table.public[0]", "aws_route_table", tags={"Name": "lab-public"})]
want = {
    ("module.vpc.aws_route.private_nat_gateway[0]", "aws_route", "destination_cidr_block", "0.0.0.0/0"): "rtb-priv_0.0.0.0/0",
    ("module.vpc.aws_route.public_internet_gateway[0]", "aws_route", "destination_cidr_block", "0.0.0.0/0"): "rtb-pub_0.0.0.0/0",
    ("module.vpc.aws_route_table_association.private[0]", "aws_route_table_association", "x", None): "subnet-a/rtb-priv",
    ("module.vpc.aws_route_table_association.public[0]", "aws_route_table_association", "x", None): "subnet-p/rtb-pub",
    ("module.vpc.aws_eip.nat[0]", "aws_eip", "x", None): "eipalloc-1",
    ("module.vpc.aws_default_route_table.default[0]", "aws_default_route_table", "x", None): "vpc-1",
    ("aws_budgets_budget.fleet[0]", "aws_budgets_budget", "name", "b"): f"{ACCOUNT}:b",
}
for (addr, rtype, k, v), expect in want.items():
    got = net.resolve(rc(addr, rtype, **{k: v}), net_planned)
    check(f"{addr} <- {expect}", got == expect, f"got {got}")

print("Every resource type the roots plan has a rule:")
if not TYPES.is_file():
    sys.exit(f"anchor missing: {TYPES} lists the types the roots planned live; the coverage check reads it")
rules = {"boundary": mod.BoundaryResolver, "network": mod.NetworkResolver, "cluster": mod.ClusterResolver}
planned_types: dict[str, set[str]] = {}
for ln in TYPES.read_text().splitlines():
    if ln.strip() and not ln.startswith("#"):
        root, rtype = ln.split()
        planned_types.setdefault(root, set()).add(rtype)
check("the fixture lists all three roots", set(planned_types) == set(rules), f"{sorted(planned_types)}")
for root, types in sorted(planned_types.items()):
    missing = sorted(t for t in types if t not in mod.NOT_IMPORTABLE and not hasattr(rules[root], f"r_{t}"))
    check(f"{root}: a rule for each of its {len(types)} planned types", not missing, f"no rule for {missing}")
for root, path in (("boundary", "infra/org/boundary/main.tf"), ("network", "infra/terraform/aws/network/main.tf"),
                   ("cluster", "infra/terraform/aws/cluster/main.tf")):
    declared = set(re.findall(r'^resource "([a-z0-9_]+)"', (REPO / path).read_text(), re.M))
    missing = sorted(t for t in declared if t not in mod.NOT_IMPORTABLE and not hasattr(rules[root], f"r_{t}"))
    check(f"{path}: a rule for each resource type it declares", not missing, f"no rule for {missing}")

if failures:
    print(f"\nFAIL: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("\nPASS: import-state.py")
