# ABOUTME: A kubectl port-forward from this host to a pod or Service port, and one HTTP GET over it, so a live check
# ABOUTME: reads an app through the kubelet rather than the API server's service proxy (#998, after #583).
"""Why a port-forward, not the API server's service proxy (#998). `kubectl get --raw
/api/v1/namespaces/<ns>/services/<svc>:<port>/proxy/...` makes the API server dial the app's pod from the
control-plane ENIs, so the node security group has to admit the cluster security group on the app's port.
#869 put 8080 and 3000 in the cluster root's node rules, but neither watch-it-burn-community nor
watch-it-burn-private holds them (the 2026-11-06 drift entry in decisions.md), so on 2026-11-06 and 2026-11-07
every service-proxy read of fake-ticket's :8080 timed out on both. A port-forward goes API server -> kubelet on
:10250, which the module's recommended node rules always admit, and the kubelet opens the pod's port from inside
the node, so no security group or NetworkPolicy stands in the path.

verify/test_kube_forward.py runs this against a stub kubectl.
"""
from __future__ import annotations

import contextlib
import re
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Iterator


@contextlib.contextmanager
def forward(kubectl: list[str], namespace: str, target: str, port: int) -> Iterator[tuple[str, str]]:
    """Run `kubectl port-forward --address 127.0.0.1 <target> :<port>` and yield (local_port, error).

    kubectl is the argv prefix, its --context included; target is what port-forward takes, e.g. svc/fake-ticket or
    pod/agentgateway-abc. local_port is the loopback port kubectl picked, "" when the listener never came up, and
    then error carries kubectl's own reason. The port-forward is stopped when the block ends, however it ends."""
    pf = subprocess.Popen([*kubectl, "-n", namespace, "port-forward", "--address", "127.0.0.1", target, f":{port}"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pattern = re.compile(r"Forwarding from 127\.0\.0\.1:(\d+) -> " + str(port))
    try:
        # kubectl picks the local port and prints it once the listener is up; read until that line or exit.
        found: list[str] = []
        reader = threading.Thread(target=lambda: found.extend(_first_forwarding(pf.stdout, pattern)), daemon=True)
        reader.start()
        reader.join(timeout=30)
        if not found:
            pf.kill()
            err = pf.stderr.read() if pf.stderr else ""
            yield "", f"kubectl port-forward {target} :{port} did not come up: {' '.join(err.split())[:400]}"
        else:
            yield found[0], ""
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
    with forward(kubectl, namespace, target, port) as (local, err):
        if err:
            return "", "", err
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{local}{path}", timeout=timeout) as r:
                return str(r.status), r.read().decode("utf-8", "replace"), ""
        except urllib.error.HTTPError as e:
            return str(e.code), e.read().decode("utf-8", "replace"), ""
        except OSError as e:
            return "", "", f"the GET over the port-forward failed: {e}"


def _first_forwarding(stream, pattern: re.Pattern) -> list[str]:
    for line in stream:
        m = pattern.search(line)
        if m:
            return [m.group(1)]
    return []
