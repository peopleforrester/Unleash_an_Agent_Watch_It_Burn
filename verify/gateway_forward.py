# ABOUTME: One chat completion through agentgateway's :3002 model bind, sent from this host over a kubectl
# ABOUTME: port-forward to a gateway pod, so a live check needs no tool inside any pod on the cluster (#583).
"""Why a port-forward, not an exec into workshop-agent (#583). The live checks used to run `python3 -c` in the
workshop-agent pod's kagent container, because that pod is the one peer chat-path-ingress admits to :3002 (#552).
On watch-it-burn-community on 2026-10-31 that exec failed with `exec: "python3": executable file not found in
$PATH`, so the model call never ran. Why is still open: the published kagent/app:0.10.1 image (index
sha256:d39d5c94..., read with podman on 2026-10-31) puts /.kagent/.venv/bin first on its PATH, and its python3
there resolves, through two symlinks, to /python/cpython-3.13.15-linux-x86_64-gnu/bin/python3.13. That image also
has nothing in /bin or /usr/bin, so no shell, curl or wget, and no other command run inside the container would
get round it.

A port-forward reaches the gateway pod's own loopback through the kubelet, so it depends on nothing inside any
container, and the NetworkPolicy (which judges pod-to-pod traffic) has nothing to say about it. The request
goes through the same :3002 listener, route and backend as the agent's: the gateway signs the Bedrock call
with its own Pod Identity credentials whoever calls it, and the model in the path is its BEDROCK_NOVA_MODEL.
What this gives up is the agent-pod hop itself; that chat-path-ingress admits workshop-agent to :3002 is read
off the live policies by verify/test_llm_bypass_live.py. verify/test_gateway_forward.py runs this against a
stub kubectl. The port-forward itself is verify/port_forward.py's (#998).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import port_forward

PORT = 3002


def chat(kubectl: list[str], namespace: str, target: str, route: str, model: str,
         timeout: int = 60) -> tuple[str, str, str]:
    """POST one 5-token chat completion to http://<target>:3002/<route>/v1/chat/completions.

    kubectl is the argv prefix, its --context included. target is what port-forward takes, e.g.
    pod/agentgateway-abc or deploy/agentgateway. Returns (status, reply, error): status is the HTTP code as
    text and reply the body, whole (a 5-token completion with its usage block can pass 400
    characters, and a cut one is not JSON), or ("", "", why) when no request was made."""
    try:
        with port_forward.forwarded(kubectl, namespace, target, PORT) as local:
            body = json.dumps({"model": model, "max_tokens": 5,
                               "messages": [{"role": "user", "content": "Reply with the single word OK."}]}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{local}/{route}/v1/chat/completions", data=body,
                                         headers={"content-type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return str(r.status), r.read().decode(), ""
            except urllib.error.HTTPError as e:
                return str(e.code), e.read().decode(), ""
            except OSError as e:
                return "", "", f"the request over the port-forward failed: {e}"
    except port_forward.ForwardFailed as e:
        return "", "", str(e)
