# ABOUTME: A kubectl port-forward from this host to a pod or Service port, and one HTTP GET over it, for live checks
# ABOUTME: that must not go through the API server's Service proxy, which the control plane cannot dial on 8080 (#998).
"""Why a port-forward, not the Service proxy (#998). `kubectl get --raw /api/v1/namespaces/<ns>/services/<svc>:<port>
/proxy/<path>` has the API server open the connection to the pod itself, from the control-plane ENIs. On the two
KubeCon clusters the node security group admits those only on 443, 4443, 6443, 8443, 9443, 10250 and 10251, so a
proxy read of an app on 8080 is accepted and then hangs (watch-it-burn-community and watch-it-burn-private,
2026-11-06 and again 2026-11-07). #869 adds 8080 and 3000 to the Terraform root, and a cluster gets them on its next
apply. A port-forward goes from the API server to the kubelet on 10250, which is admitted, and the kubelet dials the
pod on its own node, so a live check that reads an app this way works on a cluster with or without #869's rules.

gateway_forward.chat sends its model call over forwarded() too. verify/test_port_forward.py runs get() against a
stub kubectl, and verify/test_gateway_forward.py runs chat() against one.
"""
from __future__ import annotations

import contextlib
import re
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Iterator


class ForwardFailed(Exception):
    """The port-forward did not come up; the message carries kubectl's own reason."""


@contextlib.contextmanager
def forwarded(kubectl: list[str], namespace: str, target: str, port: int) -> Iterator[int]:
    """Run `kubectl -n <namespace> port-forward --address 127.0.0.1 <target> :<port>` and yield the local port it
    picked. kubectl is the argv prefix, its --context included; target is what port-forward takes, e.g.
    svc/fake-ticket or pod/agentgateway-abc. The port-forward is stopped on the way out, whatever happened."""
    pf = subprocess.Popen([*kubectl, "-n", namespace, "port-forward", "--address", "127.0.0.1", target, f":{port}"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        # kubectl picks the local port and prints it once the listener is up; read until that line or exit.
        line = re.compile(r"Forwarding from 127\.0\.0\.1:(\d+) -> " + str(port))
        found: list[int] = []
        reader = threading.Thread(target=lambda: found.extend(_first_forwarding(pf.stdout, line)), daemon=True)
        reader.start()
        reader.join(timeout=30)
        if not found:
            pf.kill()
            err = pf.stderr.read() if pf.stderr else ""
            raise ForwardFailed(f"kubectl port-forward {target} :{port} did not come up: {' '.join(err.split())[:400]}")
        yield found[0]
    finally:
        if pf.poll() is None:
            pf.terminate()
        try:
            pf.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pf.kill()
            pf.wait()


def get(kubectl: list[str], namespace: str, target: str, port: int, path: str,
        timeout: int = 30) -> tuple[str, str, str]:
    """GET http://<target>:<port><path> over a port-forward. Returns (status, body, error): status is the HTTP code
    as text and body the reply, whole, or ("", "", why) when no answer came back."""
    try:
        with forwarded(kubectl, namespace, target, port) as local:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{local}{path}", timeout=timeout) as r:
                    return str(r.status), r.read().decode("utf-8", "replace"), ""
            except urllib.error.HTTPError as e:
                return str(e.code), e.read().decode("utf-8", "replace"), ""
            except OSError as e:
                return "", "", f"the request over the port-forward failed: {e}"
    except ForwardFailed as e:
        return "", "", str(e)


def _first_forwarding(stream, line: re.Pattern) -> list[int]:
    for text in stream:
        m = line.search(text)
        if m:
            return [int(m.group(1))]
    return []
