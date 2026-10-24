#!/usr/bin/env bash
# ABOUTME: C1 fallback - attempt an outbound exfil from an apps-namespace pod to prove egress is denied.
set -euo pipefail
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
NS="${NS:-agent}"
echo "==> Attempting outbound HTTPS from ${NS} (should TIME OUT / be refused under the C1 egress deny)"
kubectl --context "${CONTEXT}" -n "${NS}" exec deploy/guard-proxy -- \
  python3 -c "import urllib.request;urllib.request.urlopen('https://example.com',timeout=8);print('EGRESS ALLOWED (no egress control on this cluster)')" \
  || echo "EGRESS DENIED (C1 NetworkPolicy working as intended)"
