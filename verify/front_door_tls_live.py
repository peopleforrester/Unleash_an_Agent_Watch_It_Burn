# ABOUTME: Live check of #638's front door certificate: a throwaway copy of the console Service, built with the patch
# ABOUTME: the chart renders for frontDoor.certificateArn, gets its own NLB, and its 443 must verify for the roster name.
"""Run by hand, against a cluster this run may change:

    KUBECONFIG=<file> python3 verify/front_door_tls_live.py --context <kube-context> --arn <acm-arn> \\
        --aws-profile <profile> --region <region> --name attackme.agenticburn.com [--name <another>] \\
        [--cafile <pem>] [--hold <seconds>]

Why (#638). lab-platform's gateway proxies a roster host to the console Service lab-platform.yaml declares as the
front door, and verifies the certificate it is handed against the system roots for that roster host. The chart's
ai-layer Application puts frontDoor.certificateArn on the console Service as an NLB TLS listener that re-encrypts to
nginx. The render test proves the patch is written; this proves an NLB built from it answers 443 with that
certificate and passes the request through to nginx.

It does not touch the console Service Argo CD manages, which is the cluster's live front door: it renders the chart
for the burn profile with the ARN, applies the ai-layer patch with kustomize as Argo CD does, and creates the patched
console Service under the name front-door-check, in the same namespace and with the same selector. The AWS Load
Balancer Controller gives it an NLB of its own. The check connects to that NLB's 443 with each roster name as SNI and
verifies the chain and the name against the system roots, or against --cafile when the certificate was imported for
a plumbing check, then sends GET / for that host. Then the two checks #660 adds: the NLB's listeners, read with
`aws elbv2 describe-listeners` under the given profile and region, must hold port 443 as TLS with that certificate;
and the terminal's websocket upgrade on /terminal/ws must get through the TLS listener and the re-encrypt to nginx,
a 101 (or 401 once ttyd has a credential) for a plain upgrade, and never a 101 for ttyd's `tty` subprotocol with no
credential (#770). With --hold the Service stays that many seconds after the checks pass, so a check that resolves
a roster name to the NLB, such as `infra/terraform/fleet/check-tls.sh --connect-to <its NLB> <names>`, can run
against it. The Service, and with it the NLB, is deleted on every exit, so the cluster is left as found.

Exit 0 when every check passes; 1 on any failure, the step named.
"""
from __future__ import annotations

import argparse
import json
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
import ttyd_ws  # noqa: E402
from bootstrap_chart import CHART, REPO, values_path  # noqa: E402

CHECK_NAME = "front-door-check"
LABEL = ("watch-it-burn/check", "front-door-638")
COMMIT = "0123456789abcdef0123456789abcdef01234567"
WS_PATH = "/terminal/ws"


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


def tls_listener(listeners: list[dict], arn: str) -> dict | None:
    """The listener on 443 that terminates TLS with the certificate, from describe-listeners' Listeners, or None."""
    for lst in listeners:
        if lst.get("Port") == 443 and lst.get("Protocol") == "TLS" \
                and any(c.get("CertificateArn") == arn for c in lst.get("Certificates", [])):
            return lst
    return None


def aws(profile: str, region: str, *args: str) -> list | dict:
    """One aws CLI call under an explicit profile and region (repo CLAUDE.md rule 6), its JSON output."""
    cli = shutil.which("aws") or fail("aws is not on PATH")
    r = subprocess.run([cli, "--region", region, "--output", "json", *args],
                       env={**os.environ, "AWS_PROFILE": profile}, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"aws {' '.join(args[:2])} under profile {profile} in {region}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout or "null")


def nlb_listeners(profile: str, region: str, host: str) -> tuple[str, list[dict]]:
    """The NLB whose DNS name is host, and its listeners."""
    lbs = aws(profile, region, "elbv2", "describe-load-balancers")["LoadBalancers"]
    lb = next((x for x in lbs if x.get("DNSName") == host), None)
    if lb is None:
        fail(f"no load balancer in {region} under {profile} has the DNS name {host}")
    return lb["LoadBalancerArn"], aws(profile, region, "elbv2", "describe-listeners",
                                      "--load-balancer-arn", lb["LoadBalancerArn"])["Listeners"]


def terminal_upgrade(host: str, name: str, cafile: str | None, port: int = 443) -> tuple[int, int]:
    """The terminal's websocket upgrade through host:port for name: the plain upgrade's HTTP status, then the
    status ttyd's `tty` subprotocol gets with no credential (0 when the socket is dropped, nginx's 502 otherwise)."""
    codes = []
    for protocol in (None, "tty"):
        try:
            sock, status, _ = ttyd_ws.connect(host, port, WS_PATH, tls=True, server_name=name, protocol=protocol,
                                              cafile=cafile, timeout=15)
            sock.close()
        except ConnectionError:
            status = 0
        codes.append(status)
    return codes[0], codes[1]


def upgrade_ok(plain: int, tty: int) -> bool:
    """check-tls.sh's reading of the two upgrades: the plain one reaches the terminal (101, or 401 once ttyd has a
    credential) and the shell's own subprotocol never opens with no credential (#770)."""
    return plain in (101, 401) and tty != 101


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--context", required=True, help="kube-context of the cluster to check on (never guessed)")
    ap.add_argument("--arn", required=True, help="ACM certificate ARN, in the cluster's account and region")
    ap.add_argument("--aws-profile", required=True, help="AWS profile the cluster's account is read with")
    ap.add_argument("--region", required=True, help="the cluster's region, where its NLB and the certificate are")
    ap.add_argument("--name", required=True, action="append",
                    help="a roster host the gateway sends as SNI and verifies; repeat for more")
    ap.add_argument("--cafile", help="verify against this PEM instead of the system roots (an imported cert)")
    ap.add_argument("--namespace", default="agent")
    ap.add_argument("--wait", type=int, default=900, help="seconds to wait for the NLB to answer")
    ap.add_argument("--hold", type=int, default=0,
                    help="seconds to keep the Service after the checks pass, for a check run against its NLB by hand")
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
        for name in a.name:
            last, verified = "", False
            while time.monotonic() < deadline:
                try:
                    cert, status = handshake(host, name, a.cafile)
                except (OSError, ssl.SSLError) as e:
                    # DNS for a new NLB, its listener and its targets come up over a few minutes; a verify error
                    # once it answers is the finding, so it ends the wait.
                    if isinstance(e, ssl.SSLCertVerificationError):
                        fail(f"443 on {host} is refused for {name} against {a.cafile or 'the system roots'}: {e}")
                    last = f"{type(e).__name__}: {e}"
                    time.sleep(15)
                    continue
                if not verified:
                    subject = dict(x[0] for x in cert.get("subject", ()))
                    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
                    issuer = dict(x[0] for x in cert.get("issuer", ()))
                    print(f"PASS: 443 verifies for {name} against {a.cafile or 'the system roots'}: subject "
                          f"{subject.get('commonName')}, SANs {sans}, issuer "
                          f"{issuer.get('organizationName') or issuer.get('commonName')}", flush=True)
                    verified = True
                # The NLB finishes the handshake itself and closes the stream until a target behind it is healthy,
                # which on a new NLB takes a few minutes more than its listener.
                if status.startswith("HTTP/1.1 "):
                    print(f"PASS: through the NLB's re-encrypt to nginx, GET / for {name} answers {status}",
                          flush=True)
                    break
                last = f"GET / answered {status!r}"
                time.sleep(15)
            else:
                if verified:
                    fail(f"443 on {host} verified for {name}, but nginx behind it never answered GET / in "
                         f"{a.wait}s ({last})")
                fail(f"443 on {host} never verified for {name} in {a.wait}s; last error {last}")

        lb_arn, listeners = nlb_listeners(a.aws_profile, a.region, host)
        lst = tls_listener(listeners, a.arn)
        shape = [(x.get("Port"), x.get("Protocol")) for x in listeners]
        if lst is None:
            fail(f"describe-listeners on {lb_arn} shows no TLS listener on 443 with {a.arn}: {shape}")
        print(f"PASS: describe-listeners on {lb_arn}: port 443 is {lst['Protocol']} with {a.arn}, "
              f"policy {lst.get('SslPolicy')}; listeners {shape}", flush=True)

        for name in a.name:
            plain, tty = terminal_upgrade(host, name, a.cafile)
            if not upgrade_ok(plain, tty):
                fail(f"the terminal's websocket through the TLS listener for {name}: the plain upgrade on {WS_PATH} "
                     f"got {plain} (wanted 101, or 401 when credentialed) and the tty subprotocol with no "
                     f"credential got {tty} (must not be 101)")
            print(f"PASS: the terminal's websocket upgrade on {WS_PATH} for {name} gets {plain} through the TLS "
                  f"listener and the re-encrypt to nginx; the tty subprotocol with no credential gets {tty}",
                  flush=True)
        if a.hold:
            print(f"holding {a.namespace}/{CHECK_NAME} and {host} for {a.hold}s", flush=True)
            time.sleep(a.hold)
        return 0
    finally:
        d = kubectl(a.context, "-n", a.namespace, "delete", "service", CHECK_NAME, "--wait=true", "--timeout=300s")
        print(f"deleted {a.namespace}/{CHECK_NAME}" if d.returncode == 0
              else f"WARNING: could not delete {a.namespace}/{CHECK_NAME}: {d.stderr.strip()[:200]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
