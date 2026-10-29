# ABOUTME: The one-shot pod a live check runs a shell script in, inside namespace agent, built so the admin profile's
# ABOUTME: armed Kyverno admits it: an allowed, already-signed image and CPU and memory limits on its container.
"""Built here, not by `kubectl run`, so the pod a live check creates is the manifest the offline gate judges
(verify/test_probe_pod_admission.py runs it through every workshop policy with the Kyverno CLI). `kubectl run`
cannot be rendered offline: with or without --overrides it asks the API server for discovery first, and it has
no flag for resource limits (none in the pinned v1.36.2).

Why the old `kubectl run --image=curlimages/curl` pod does not do (#555): fleet.sh arm_infra_guardrails flips
restrict-image-registries and require-resource-limits to Deny on every admin and full cluster. curlimages/curl
is on no allowed registry (docker.io/library/ is, a bare name is not) and the pod set no limits, so the API
server refuses it there before it runs. The image here is the workshop-mcp Deployment's own, read off the
cluster by the caller: ghcr.io is allowed, verify-image-signatures already admitted that digest for the
Deployment, the node has it cached, and it carries sh and curl (images/workshop-mcp/Dockerfile).
"""
from __future__ import annotations

LIMITS = {"limits": {"cpu": "200m", "memory": "128Mi"}, "requests": {"cpu": "50m", "memory": "32Mi"}}


def shell_pod(name: str, namespace: str, image: str, script: str) -> dict:
    """A Pod that runs `sh -c script` once and stops. Its stdout is the script's answer; read it with logs."""
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "containers": [{"name": "probe", "image": image, "command": ["sh", "-c", script], "resources": LIMITS}],
        },
    }
