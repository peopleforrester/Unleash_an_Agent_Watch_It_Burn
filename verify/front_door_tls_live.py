# ABOUTME: Live check of #638's front door certificate: a throwaway copy of the console Service, built with the patch
# ABOUTME: the chart renders for frontDoor.certificateArn, gets its own NLB, and its 443 must verify for the roster name.
"""Run by hand, against a cluster this run may change:

    KUBECONFIG=<file> python3 verify/front_door_tls_live.py --context <kube-context> --arn <acm-arn> \\
        --name attackme.agenticburn.com [--cafile <pem>]

Why (#638). lab-platform's gateway proxies a roster host to the console Service lab-platform.yaml declares as the
front door, and verifies the certificate it is handed against the system roots for that roster host. The chart's
ai-layer Application puts frontDoor.certificateArn on the console Service as an NLB TLS listener that re-encrypts to
nginx. The render test proves the patch is written; this proves an NLB built from it answers 443 with that
certificate and passes the request through to nginx.

It does not touch the console Service Argo CD manages, which is the cluster's live front door: it renders the chart
for the burn profile with the ARN, applies the ai-layer patch with kustomize as Argo CD does, and creates the patched
console Service under the name front-door-check, in the same namespace and with the same selector. The AWS Load
Balancer Controller gives it an NLB of its own. The check connects to that NLB's 443 with the roster name as SNI and
verifies the chain and the name against the system roots, or against --cafile when the certificate was imported for
a plumbing check, then sends GET / for that host. The Service, and with it the NLB, is deleted on every exit, so
the cluster is left as found.

Exit 0 when the handshake verifies and nginx answers; 1 on any failure, the step named.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap_chart import CHART, REPO, values_path  # noqa: E402

CHECK_NAME = "front-door-check"
LABEL = ("watch-it-burn/check", "front-door-638")
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def ai_layer_patches(arn: str) -> list[dict]:
    """The kustomize patches the burn profile's ai-layer Application carries with frontDoor.certificateArn set."""
    helm = shutil.which("helm") or fail("helm is not on PATH")
    r = subprocess.run([helm, "template", "lab-bootstrap", str(CHART), "-f", str(values_path("burn")),
                        "--set", f"revision={COMMIT}", "--set", f"frontDoor.certificateArn={arn}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"the chart does not render with frontDoor.certificateArn={arn}: {r.stderr.strip()[:300]}")
    app = next((d for d in yaml.safe_load_all(r.stdout) if d and d["metadata"]["name"] == "ai-layer"), None)
    patches = ((app or {}).get("spec", {}).get("source", {}).get("kustomize") or {}).get("patches") or []
    if not patches:
        fail("the rendered ai-layer Application carries no kustomize patches for the front door")
    return patches


def check_service(arn: str, namespace: str) -> dict:
    """The console Service as Argo CD builds it with the front door patch, renamed to front-door-check."""
    kubectl = shutil.which("kubectl") or fail("kubectl is not on PATH")
    patches = ai_layer_patches(arn)
    (REPO / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=REPO / "tmp") as d:
        (pathlib.Path(d) / "kustomization.yaml").write_text(yaml.safe_dump({
            "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": [os.path.relpath(REPO / "gitops/ai-layer", d)], "patches": patches}), encoding="utf-8")
        k = subprocess.run([kubectl, "kustomize", d], capture_output=True, text=True)
    if k.returncode != 0:
        fail(f"kustomize does not build gitops/ai-layer with the patch (are the submodules checked out? "
             f"bash verify/ensure-submodules.sh): {k.stderr.strip()[:300]}")
    svc = next((x for x in yaml.safe_load_all(k.stdout) if x and x.get("kind") == "Service"
                and x["metadata"]["name"] == "console"), None)
    if svc is None:
        fail("the kustomize build has no console Service")
    if svc["metadata"].get("annotations", {}).get("service.beta.kubernetes.io/aws-load-balancer-ssl-cert") != arn:
        fail("the built console Service does not carry the certificate")
    svc["metadata"] = {"name": CHECK_NAME, "namespace": namespace, "labels": {LABEL[0]: LABEL[1]},
                       "annotations": svc["metadata"]["annotations"]}
    return svc


def kubectl(context: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", context, *args], input=stdin, capture_output=True, text=True)


def handshake(host: str, name: str, cafile: str | None, port: int = 443) -> tuple[dict, str]:
    """Connect to host:port with SNI name, verify chain and name, and return the peer cert and GET /'s status line."""
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    with socket.create_connection((host, port), timeout=15) as raw, \
            ctx.wrap_socket(raw, server_hostname=name) as tls:
        cert = tls.getpeercert()
        tls.sendall(f"GET / HTTP/1.1\r\nHost: {name}\r\nConnection: close\r\n\r\n".encode())
        head = b""
        while b"\r\n" not in head:
            chunk = tls.recv(4096)
            if not chunk:
                break
            head += chunk
    return cert, head.split(b"\r\n", 1)[0].decode(errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--context", required=True, help="kube-context of the cluster to check on (never guessed)")
    ap.add_argument("--arn", required=True, help="ACM certificate ARN, in the cluster's account and region")
    ap.add_argument("--name", required=True, help="the roster host the gateway sends as SNI and verifies")
    ap.add_argument("--cafile", help="verify against this PEM instead of the system roots (an imported cert)")
    ap.add_argument("--namespace", default="agent")
    ap.add_argument("--wait", type=int, default=900, help="seconds to wait for the NLB to answer")
    a = ap.parse_args()

    svc = check_service(a.arn, a.namespace)
    if kubectl(a.context, "-n", a.namespace, "get", "service", "console").returncode != 0:
        fail(f"{a.context} has no console Service in {a.namespace}: this is not a cluster with the ai-layer")
    if kubectl(a.context, "-n", a.namespace, "get", "service", CHECK_NAME).returncode == 0:
        fail(f"{a.namespace}/{CHECK_NAME} already exists on {a.context}; delete it (an earlier run's) and run again")
    r = kubectl(a.context, "apply", "-f", "-", stdin=yaml.safe_dump(svc))
    if r.returncode != 0:
        fail(f"creating {a.namespace}/{CHECK_NAME}: {r.stderr.strip()[:300]}")
    print(f"created {a.namespace}/{CHECK_NAME} on {a.context} with {a.arn}", flush=True)
    try:
        deadline = time.monotonic() + a.wait
        host = ""
        while not host and time.monotonic() < deadline:
            host = kubectl(a.context, "-n", a.namespace, "get", "service", CHECK_NAME, "-o",
                           "jsonpath={.status.loadBalancer.ingress[0].hostname}").stdout.strip()
            host or time.sleep(10)
        if not host:
            fail(f"{CHECK_NAME} got no load balancer hostname in {a.wait}s")
        print(f"its NLB: {host}", flush=True)
        last, verified = "", False
        while time.monotonic() < deadline:
            try:
                cert, status = handshake(host, a.name, a.cafile)
            except (OSError, ssl.SSLError) as e:
                # DNS for a new NLB, its listener and its targets come up over a few minutes; a verify error
                # once it answers is the finding, so it ends the wait.
                last = f"{type(e).__name__}: {e}"
                if isinstance(e, ssl.SSLCertVerificationError):
                    break
                time.sleep(15)
                continue
            if not verified:
                subject = dict(x[0] for x in cert.get("subject", ()))
                sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
                issuer = dict(x[0] for x in cert.get("issuer", ()))
                print(f"PASS: 443 verifies for {a.name} against {a.cafile or 'the system roots'}: subject "
                      f"{subject.get('commonName')}, SANs {sans}, issuer "
                      f"{issuer.get('organizationName') or issuer.get('commonName')}", flush=True)
                verified = True
            # The NLB finishes the handshake itself and closes the stream until a target behind it is healthy,
            # which on a new NLB takes a few minutes more than its listener.
            if status.startswith("HTTP/1.1 "):
                print(f"PASS: through the NLB's re-encrypt to nginx, GET / for {a.name} answers {status}")
                return 0
            last = f"GET / answered {status!r}"
            time.sleep(15)
        if verified:
            fail(f"443 on {host} verified for {a.name}, but nginx behind it never answered GET / in {a.wait}s ({last})")
        fail(f"443 on {host} never verified for {a.name} in {a.wait}s; last error {last}")
    finally:
        d = kubectl(a.context, "-n", a.namespace, "delete", "service", CHECK_NAME, "--wait=true", "--timeout=300s")
        print(f"deleted {a.namespace}/{CHECK_NAME}" if d.returncode == 0
              else f"WARNING: could not delete {a.namespace}/{CHECK_NAME}: {d.stderr.strip()[:200]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
