# ABOUTME: Renders `terraform show -json` of the cluster, boundary and audit roots' IAM resources with no AWS account,
# ABOUTME: so the policy pipeline's E2E checks read the documents the repo would apply today, not a recorded copy.
"""How. Every IAM document in these roots is computed locally (jsonencode, templatefile, and the modules'
aws_iam_policy_document data sources). The only AWS calls a plan of them makes are STS GetCallerIdentity and
the IAM lookup of the permissions boundary by name. A copy of the root is pointed at a local endpoint that
answers those two, with account 111122223333, and planned with -target on the IAM-bearing resources only.
The EKS module itself is left out: planning it calls EKS, EC2 and SSM, and its own policy documents
(cluster encryption on a KMS key) are known only after apply in any case.

Needs terraform on PATH (or TERRAFORM) and network to registry.terraform.io for `terraform init`."""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parents[1]
CLUSTER = REPO / "infra/terraform/aws/cluster"
BOUNDARY = REPO / "infra/org/boundary"
# The per-account Config recorder and trail (#205). Planned whole: its only AWS reads are the two below.
AUDIT = REPO / "infra/terraform/aws/audit"
# Every root the pipeline runs on (pipeline.ROOTS); test_iam_policy_coverage.py holds the two the same.
ROOTS = {"cluster": CLUSTER, "boundary": BOUNDARY, "audit": AUDIT}
ACCOUNT = "111122223333"
BOUNDARY_NAME = "watch-it-burn-permissions-boundary"
CLUSTER_NAME = "watch-it-burn-attendee-001"
CLUSTER_HOST = "bane-sabrina.agenticburn.com"  # public_host_for of CLUSTER_NAME in fleet.sh
IAM_NS = "https://iam.amazonaws.com/doc/2010-05-08/"
STS_NS = "https://sts.amazonaws.com/doc/2011-06-15/"

CLUSTER_TARGETS = [
    "module.ebs_csi_pod_identity", "module.aws_lb_controller_pod_identity", "module.eso_pod_identity",
    "module.agent_bedrock_pod_identity", "module.tutor_bedrock_pod_identity",
    "aws_iam_policy.bedrock_invoke", "aws_iam_policy.tutor_bedrock_invoke",
    "aws_iam_user.attendee", "aws_iam_user_policy.attendee_eks",
]


def terraform_binary() -> str:
    exe = os.environ.get("TERRAFORM") or shutil.which("terraform")
    if not exe:
        raise SystemExit("FAIL: terraform is not on PATH (or set TERRAFORM); VERSIONS.lock pins v1.15.6")
    return exe


def _boundary_document() -> str:
    text = (REPO / "infra/org/permissions-boundary.json.tftpl").read_text(encoding="utf-8")
    for k, v in (("account_id", ACCOUNT), ("partition", "aws"), ("boundary_name", BOUNDARY_NAME)):
        text = text.replace("${" + k + "}", v)
    return text


def _xml(action: str, body: str, ns: str) -> bytes:
    return (f'<{action}Response xmlns="{ns}"><{action}Result>{body}</{action}Result>'
            f"<ResponseMetadata><RequestId>local</RequestId></ResponseMetadata></{action}Response>").encode()


_POLICY = (f"<PolicyName>{BOUNDARY_NAME}</PolicyName><PolicyId>ANPALOCAL</PolicyId>"
           f"<Arn>arn:aws:iam::{ACCOUNT}:policy/{BOUNDARY_NAME}</Arn><Path>/</Path><DefaultVersionId>v1</DefaultVersionId>"
           "<AttachmentCount>0</AttachmentCount><PermissionsBoundaryUsageCount>0</PermissionsBoundaryUsageCount>"
           "<IsAttachable>true</IsAttachable><CreateDate>2026-10-24T00:00:00Z</CreateDate>"
           "<UpdateDate>2026-10-24T00:00:00Z</UpdateDate><Tags/>")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (http.server's name)
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        action = form.get("Action", [""])[0]
        answers = {
            "GetCallerIdentity": lambda: _xml(action, f"<Arn>arn:aws:iam::{ACCOUNT}:user/render</Arn>"
                                              f"<UserId>AIDALOCAL</UserId><Account>{ACCOUNT}</Account>", STS_NS),
            "ListPolicies": lambda: _xml(action, f"<IsTruncated>false</IsTruncated><Policies><member>{_POLICY}"
                                         "</member></Policies>", IAM_NS),
            "GetPolicy": lambda: _xml(action, f"<Policy>{_POLICY}</Policy>", IAM_NS),
            "GetPolicyVersion": lambda: _xml(action, "<PolicyVersion><Document>"
                                             f"{urllib.parse.quote(_boundary_document())}</Document><VersionId>v1"
                                             "</VersionId><IsDefaultVersion>true</IsDefaultVersion><CreateDate>"
                                             "2026-10-24T00:00:00Z</CreateDate></PolicyVersion>", IAM_NS),
            "ListPolicyTags": lambda: _xml(action, "<IsTruncated>false</IsTruncated><Tags/>", IAM_NS),
        }
        if action not in answers:
            # A call this file does not know is a plan that now needs AWS for real: say so, do not guess.
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"iam_plan_render: unhandled {action}".encode())
            return
        body = answers[action]()
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


_PROVIDER = re.compile(r'provider "aws" \{\n  region  = var\.region\n  profile = var\.profile\n')


def _point_at(main_tf: str, port: int) -> str:
    local = (f'provider "aws" {{\n  region                      = var.region\n'
             f'  access_key                  = "AKIALOCALRENDERONLY0"\n  secret_key                  = "local"\n'
             f"  skip_credentials_validation = true\n  skip_metadata_api_check     = true\n"
             f"  skip_requesting_account_id  = true\n"
             f'  endpoints {{\n    sts = "http://127.0.0.1:{port}"\n    iam = "http://127.0.0.1:{port}"\n  }}\n')
    out, n = _PROVIDER.subn(local, main_tf, count=1)
    if n != 1:
        raise SystemExit("FAIL: iam_plan_render cannot find the root's provider \"aws\" block to point it locally")
    return out


_CACHE: list[str] = []
# A terraform call that has not finished in this long is a stalled registry download, not a slow one: the aws
# provider is ~800 MB, and a run that waited on it with no bound held the whole E2E tier for 15 minutes (#572).
TERRAFORM_TIMEOUT = 600


def _plugin_cache() -> str:
    # One provider download per test process, not one per render. The E2E tier sets TF_PLUGIN_CACHE_DIR to a
    # directory that survives between tests (run-e2e-tools.sh), so the download happens once per checkout.
    # That holds only with TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE set (render() sets it). The renders copy no
    # lockfile, and Terraform 1.4+ ignores the cache for a provider no lockfile records: each init fetched aws (about
    # 840 MB) and cloudinit from releases.hashicorp.com again, four times per test, and a reset connection on one of
    # those fetches failed the tier on staging (#883, as in run 16828).
    if not _CACHE:
        _CACHE.append(tempfile.mkdtemp(prefix="wib-tf-plugins-"))
    return _CACHE[0]


def render(root: str, edit=None) -> dict:
    """`terraform show -json` for 'cluster', 'boundary' or 'audit'. edit(main_tf) -> main_tf mutates the copy first."""
    src = ROOTS[root]
    tf = terraform_binary()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp) / "infra/org/boundary" if root == "boundary" else pathlib.Path(tmp) / "root"
            work.mkdir(parents=True)
            if root == "boundary":
                shutil.copy(REPO / "infra/org/permissions-boundary.json.tftpl", work.parent)
            text = _point_at((src / "main.tf").read_text(encoding="utf-8"), server.server_address[1])
            if root == "cluster":
                # The associations name the EKS module's cluster; with the module out of the plan, name it directly.
                text = text.replace("module.eks.cluster_name", "var.name")
            (work / "main.tf").write_text(edit(text) if edit else text, encoding="utf-8")
            env = {**os.environ, "TF_PLUGIN_CACHE_DIR": os.environ.get("TF_PLUGIN_CACHE_DIR") or _plugin_cache(),
                   "TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE": "true"}
            def run(*a):
                try:
                    return subprocess.run([tf, f"-chdir={work}", *a], capture_output=True, text=True, env=env,
                                          timeout=TERRAFORM_TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise SystemExit(f"FAIL: terraform {a[0]} of {root} did not finish within {TERRAFORM_TIMEOUT}s; "
                                     "a provider download from registry.terraform.io has stalled")
            # No lockfile is copied: the committed cluster lock trails the module's provider floor, and this renders
            # documents, it does not apply them.
            r = run("init", "-input=false", "-no-color")
            if r.returncode:
                raise SystemExit(f"FAIL: terraform init of {root} failed:\n{r.stderr or r.stdout}")
            # event has no default in any root (#494, #507, #205), nor the cluster root's hostname (#602) or
            # role (#636).
            args = ["plan", "-input=false", "-no-color", "-refresh=false", "-out=render.tfplan", "-var", "profile=render",
                    "-var", "event=render"]
            if root == "cluster":
                args += [f"-target={t}" for t in CLUSTER_TARGETS]
                args += ["-var", f"name={CLUSTER_NAME}", "-var", f"hostname={CLUSTER_HOST}",
                         "-var", "role=attendee", "-var", "vpc_id=vpc-render",
                         "-var", 'private_subnet_ids=["subnet-render"]']
            r = run(*args)
            if r.returncode:
                raise SystemExit(f"FAIL: terraform plan of {root} failed:\n{r.stderr or r.stdout}")
            r = run("show", "-json", "render.tfplan")
            if r.returncode:
                raise SystemExit(f"FAIL: terraform show of {root} failed:\n{r.stderr}")
            return json.loads(r.stdout)
    finally:
        server.shutdown()
