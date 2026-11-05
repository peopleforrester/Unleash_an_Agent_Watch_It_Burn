# ABOUTME: Offline half of verify/front_door_tls_live.py (#638): the Service it creates is the chart-patched console
# ABOUTME: under another name, and its handshake verifies a cert for the roster name and refuses a self-signed one.
# SUITE: e2e (needs helm and kubectl to render the chart and build gitops/ai-layer with kustomize, and openssl)
# E2E TIER: tools (no cluster, no AWS: run-e2e-tools.sh runs it with the pinned tools, #572)
#
# Why. The live check never touches the console Service Argo CD manages, which is the cluster's real front door. It
# creates a copy with the front door patch. If that copy drifted from what Argo CD builds, the live check would prove
# a Service nobody runs; if its handshake did not verify, a pass would mean nothing. Both are checked here without a
# cluster: the copy against the kustomize build, the handshake against a local TLS server with a throwaway cert.
from __future__ import annotations

import pathlib
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import front_door_tls_live as live  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


for tool in ("helm", "kubectl", "openssl"):
    if not shutil.which(tool):
        print(f"FAIL: {tool} is not on PATH (run through verify/run-e2e-tools.sh)", file=sys.stderr)
        sys.exit(1)

CERT = "arn:aws:acm:us-west-2:111122223333:certificate/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
SSL_ANN = {"service.beta.kubernetes.io/aws-load-balancer-ssl-cert": CERT,
           "service.beta.kubernetes.io/aws-load-balancer-ssl-ports": "443",
           "service.beta.kubernetes.io/aws-load-balancer-backend-protocol": "ssl",
           "service.beta.kubernetes.io/aws-load-balancer-ssl-negotiation-policy": "ELBSecurityPolicy-TLS13-1-2-2021-06"}

print("== the Service the live check creates ==")
svc = live.check_service(CERT, "agent")
meta = svc["metadata"]
check("it is named front-door-check, in agent, labelled as the check's",
      meta["name"] == "front-door-check" and meta["namespace"] == "agent"
      and meta["labels"] == {"watch-it-burn/check": "front-door-638"}, str(meta))
ann = meta["annotations"]
check("it carries the chart's four front door annotations with the ARN",
      all(ann.get(k) == v for k, v in SSL_ANN.items()), str(ann))
check("and the console Service's own NLB annotations, internet-facing with ip targets",
      ann.get("service.beta.kubernetes.io/aws-load-balancer-type") == "external"
      and ann.get("service.beta.kubernetes.io/aws-load-balancer-scheme") == "internet-facing"
      and ann.get("service.beta.kubernetes.io/aws-load-balancer-nlb-target-type") == "ip", str(ann))
check("its spec is the console Service's: a LoadBalancer on the console pods, 80 and 443",
      svc["spec"]["type"] == "LoadBalancer" and svc["spec"]["selector"] == {"app.kubernetes.io/name": "console"}
      and sorted(p["port"] for p in svc["spec"]["ports"]) == [80, 443], str(svc["spec"]))

print("== its handshake, against a local TLS server ==")
NAME = "attackme.agenticburn.com"
with tempfile.TemporaryDirectory() as d:
    key, pem = f"{d}/key.pem", f"{d}/cert.pem"
    r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-keyout", key,
                        "-out", pem, "-subj", f"/CN={NAME}", "-addext", f"subjectAltName=DNS:{NAME}"],
                       capture_output=True, text=True)
    check("openssl makes a throwaway certificate for the roster name", r.returncode == 0, r.stderr.strip()[:200])
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(pem, key)
    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]

    def serve() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                with sctx.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(4096)
                    tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except (OSError, ssl.SSLError):
                pass

    threading.Thread(target=serve, daemon=True).start()
    cert, status = live.handshake("127.0.0.1", NAME, pem, port)
    check("with that certificate as the CA, it verifies for the roster name and reads GET /'s status line",
          status == "HTTP/1.1 200 OK" and ("DNS", NAME) in cert.get("subjectAltName", ()), status)
    try:
        live.handshake("127.0.0.1", "burritobot.co", pem, port)
        check("for another name it is refused", False, "verified")
    except ssl.SSLCertVerificationError as e:
        check("for another name it is refused", "match" in str(e) or "mismatch" in str(e), str(e))
    try:
        live.handshake("127.0.0.1", NAME, None, port)
        check("against the system roots the self-signed certificate is refused, as the gateway refuses nginx's", False,
              "verified")
    except ssl.SSLCertVerificationError as e:
        check("against the system roots the self-signed certificate is refused, as the gateway refuses nginx's",
              "self-signed" in str(e) or "self signed" in str(e), str(e))
    srv.close()

if failures:
    print(f"\n{len(failures)} FAILED: {failures}", file=sys.stderr)
    sys.exit(1)
print("\nALL FRONT DOOR LIVE-CHECK LOGIC TESTS GREEN")
