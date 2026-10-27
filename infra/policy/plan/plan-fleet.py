#!/usr/bin/env python3
# ABOUTME: Plans the real fleet roots (aws/network, aws/cluster) against a local AWS API, with no AWS account.
# ABOUTME: Usage: plan-fleet.py --tf terraform|tofu <out-dir>; writes network.plan.json and cluster.plan.json.
#
# Why a mock: a plan reads data sources, and the cluster root reads STS, EC2, SSM and EKS before it can
# say what it would create. Against moto (plus a small stub for the two calls moto lacks) the module logic
# runs exactly as it does for real, so the plan has the fleet's real resources, addresses and IAM documents.
# Only API-sourced values differ: the account id, the subnet ids, the AMI and addon versions. None of the
# plan-time policies read those. That makes a plan of the fleet something any machine can produce, which is
# what lets the e2e suite prove the fleet passes its own policy and that every exception is still needed.
#
# Safety: the child processes get fake credentials in a throwaway config and every AWS_* variable from the
# caller is dropped, so even a call that escaped the endpoint override would reach real AWS unsigned by
# any real key and be refused. Nothing is applied; there is no state to apply from.
import argparse
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOTS = {"network": REPO / "infra/terraform/aws/network", "cluster": REPO / "infra/terraform/aws/cluster"}
REGION = "us-west-2"
CLUSTER_NAME = "watch-it-burn-attendee-001"
# The cluster root requires its public hostname with no default (#602); any valid DNS name plans.
CLUSTER_HOST = "plan-fleet.agenticburn.com"
EVENT_SH = REPO / "infra/terraform/fleet/event.sh"

# What the stub answers. Plausible values only: no policy reads them, they only have to let the plan finish.
ADDON_VERSIONS = {
    "vpc-cni": "v1.20.4-eksbuild.1",
    "kube-proxy": "v1.36.0-eksbuild.1",
    "coredns": "v1.12.4-eksbuild.1",
    "eks-pod-identity-agent": "v1.3.9-eksbuild.1",
    "aws-ebs-csi-driver": "v1.50.0-eksbuild.1",
}
AMI_RELEASE_VERSION = "1.36.0-20261001"


class Stub(BaseHTTPRequestHandler):
    """EKS DescribeAddonVersions and SSM GetParameter, which moto 5.2.4 does not implement."""

    def _json(self, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _refuse(self, what: str) -> None:
        # Loud on purpose: an unhandled call fails the plan instead of returning something made up.
        sys.stderr.write(f"plan-fleet stub: unhandled {what}\n")
        self.send_response(400)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 (http.server's name)
        url = urllib.parse.urlparse(self.path)
        if url.path != "/addons/supported-versions":
            return self._refuse(f"GET {self.path}")
        q = urllib.parse.parse_qs(url.query)
        k8s = q.get("kubernetesVersion", [""])[0]
        names = q.get("addonName", list(ADDON_VERSIONS))
        if any(n not in ADDON_VERSIONS for n in names):
            return self._refuse(f"addon {names}")
        self._json({"addons": [{
            "addonName": n, "type": "stub",
            "addonVersions": [{"addonVersion": ADDON_VERSIONS[n], "architecture": ["amd64"],
                               "compatibilities": [{"clusterVersion": k8s, "defaultVersion": True,
                                                    "platformVersions": ["*"]}]}],
        } for n in names]})

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        target = self.headers.get("X-Amz-Target", "")
        name = body.get("Name", "")
        if target != "AmazonSSM.GetParameter" or not name.startswith("/aws/service/eks/optimized-ami/"):
            return self._refuse(f"POST {target} {name}")
        self._json({"Parameter": {"Name": name, "Type": "String", "Value": AMI_RELEASE_VERSION, "Version": 1,
                                  "DataType": "text", "ARN": f"arn:aws:ssm:{REGION}::parameter{name}"}})

    def log_message(self, *_args) -> None:
        pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def query(endpoint: str, service: str, version: str, region: str = REGION, **params: str) -> str:
    """One AWS Query API call against moto, which reads the service and region from the credential scope."""
    data = urllib.parse.urlencode({**params, "Version": version}).encode()
    req = urllib.request.Request(endpoint, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"AWS4-HMAC-SHA256 Credential=testing/20261024/{region}/{service}/aws4_request, "
                         "SignedHeaders=host, Signature=stub",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


def ec2(endpoint: str, **params: str) -> str:
    return query(endpoint, "ec2", "2016-11-15", **params)


def fleet_event() -> str:
    """The `event` both roots require, read the way fleet.sh reads it: by sourcing fleet/event.sh."""
    proc = subprocess.run(["bash", "-c", 'source "$1" && printf %s "${WIB_EVENT:?}"', "_", str(EVENT_SH)],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout:
        sys.exit(f"could not read WIB_EVENT from {EVENT_SH}: {proc.stderr.strip()}")
    return proc.stdout


def boundary_pipeline():
    """infra/org/pipeline.py, for the boundary's name and its rendered document (one source for both)."""
    spec = importlib.util.spec_from_file_location("org_pipeline", REPO / "infra/org/pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tf", required=True, choices=["terraform", "tofu"], help="which binary plans")
    ap.add_argument("out", type=Path, help="directory for network.plan.json and cluster.plan.json")
    args = ap.parse_args()
    missing = [b for b in (args.tf, "moto_server") if shutil.which(b) is None]
    if missing:
        sys.exit(f"not on PATH: {', '.join(missing)} (install the pinned set: python3 install-tools.py <dir>)")
    args.out.mkdir(parents=True, exist_ok=True)

    moto_port, stub_port = free_port(), free_port()
    moto_url, stub_url = f"http://127.0.0.1:{moto_port}", f"http://127.0.0.1:{stub_port}"
    stub = ThreadingHTTPServer(("127.0.0.1", stub_port), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        moto_log = (work / "moto.log").open("w")
        moto = subprocess.Popen(["moto_server", "-H", "127.0.0.1", "-p", str(moto_port)],
                                stdout=moto_log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(moto_url + "/moto-api/", timeout=1)
                    break
                except OSError:
                    time.sleep(0.2)
            else:
                sys.exit(f"moto_server did not come up on {moto_url}")

            # The cluster root takes the lab VPC as inputs and the node group reads its first subnet back,
            # so they have to exist in the mock, the way the network root's outputs exist for real.
            vpc = re.search(r"<vpcId>([^<]+)</vpcId>", ec2(moto_url, Action="CreateVpc", CidrBlock="10.0.0.0/16"))[1]
            subnets = [re.search(r"<subnetId>([^<]+)</subnetId>",
                                 ec2(moto_url, Action="CreateSubnet", VpcId=vpc, CidrBlock=cidr,
                                     AvailabilityZone=az))[1]
                       for cidr, az in (("10.0.0.0/18", f"{REGION}a"), ("10.0.64.0/18", f"{REGION}b"))]
            # The cluster root looks the per-account permissions boundary up by name (#207), as infra/org/boundary
            # leaves it in every account before any cluster. Created here from the same template that root applies.
            org = boundary_pipeline()
            account = re.search(r"<Account>([^<]+)</Account>",
                                query(moto_url, "sts", "2011-06-15", Action="GetCallerIdentity"))[1]
            query(moto_url, "iam", "2010-05-08", region="us-east-1", Action="CreatePolicy",
                  PolicyName=org.BOUNDARY_NAME, PolicyDocument=json.dumps(org.render_boundary(account)))

            (work / "credentials").write_text("[plan-fleet]\naws_access_key_id = testing\n"
                                              "aws_secret_access_key = testing\n")
            (work / "config").write_text(f"[profile plan-fleet]\nregion = {REGION}\n")
            env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
            env.update({
                "AWS_SHARED_CREDENTIALS_FILE": str(work / "credentials"),
                "AWS_CONFIG_FILE": str(work / "config"),
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_ENDPOINT_URL": moto_url,
                "AWS_ENDPOINT_URL_EKS": stub_url,
                "AWS_ENDPOINT_URL_SSM": stub_url,
                "TF_IN_AUTOMATION": "1",
            })
            event = fleet_event()
            tfvars = {
                "network": {"profile": "plan-fleet", "event": event},
                "cluster": {"profile": "plan-fleet", "event": event, "name": CLUSTER_NAME, "vpc_id": vpc,
                            "private_subnet_ids": subnets, "hostname": CLUSTER_HOST},
            }
            for root, src in ROOTS.items():
                # A copy, so init never writes .terraform or a lock file into the repo, and without the local
                # state, which holds live ids the mock cannot answer for. -upgrade because
                # aws/cluster's committed lock pins hashicorp/aws 6.51.0 while eks ~> 21.0 now needs >= 6.59,
                # so a plain init on a fresh copy fails; this plans with what a fresh `init -upgrade` gets.
                dst = work / root
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
                (dst / "plan-fleet.auto.tfvars.json").write_text(json.dumps(tfvars[root]))
                for step in (["init", "-upgrade", "-input=false", "-no-color"],
                             ["plan", "-input=false", "-no-color", "-out=plan.bin"]):
                    proc = subprocess.run([args.tf, f"-chdir={dst}", *step], env=env, capture_output=True, text=True)
                    if proc.returncode != 0:
                        sys.exit(f"{args.tf} {step[0]} failed for {root}:\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}")
                show = subprocess.run([args.tf, f"-chdir={dst}", "show", "-json", "plan.bin"],
                                      env=env, capture_output=True, text=True, check=True)
                out = args.out / f"{root}.plan.json"
                out.write_text(show.stdout)
                count = sum(1 for rc in json.loads(show.stdout).get("resource_changes", []) if rc["mode"] == "managed")
                print(f"{root}: {count} managed resources planned with {args.tf} -> {out}")
        finally:
            moto.terminate()
            moto.wait(timeout=30)
            moto_log.close()
            stub.shutdown()


if __name__ == "__main__":
    main()
