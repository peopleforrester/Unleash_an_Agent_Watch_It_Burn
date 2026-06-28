#!/usr/bin/env bash
# ABOUTME: Create/update the per-cluster `student-aws-creds` Secret (namespace agent) so the VTT's aws CLI
# ABOUTME: opens pre-configured with the student's own keys. One call per cluster, from the cluster bootstrap.
set -euo pipefail

# Per-cluster step (run after the ai-layer is applied to the cluster). The keys are the same ones
# generate_attendee_aws.py mints into the pool CSV and that the provisioning page shows the student.
# kube-safety: an explicit --context is REQUIRED; this never touches the current-context.

usage() {
    cat >&2 <<USAGE
usage: $0 --context CTX --access-key AK --secret-key SK [--region us-west-2] [--namespace agent]

  --context      kube context for the target cluster (required; no current-context fallback)
  --access-key   the student's AWS access key id for THIS cluster
  --secret-key   the student's AWS secret access key for THIS cluster
  --region       default AWS region baked into the VTT profile (default: us-west-2)
  --namespace    namespace the ai-layer runs in (default: agent)

Set KUBECONFIG to an isolated file before calling; this script does not write ~/.kube/config.
USAGE
    exit 2
}

CONTEXT=""; ACCESS_KEY=""; SECRET_KEY=""; REGION="us-west-2"; NAMESPACE="agent"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --context)    CONTEXT="$2"; shift 2 ;;
        --access-key) ACCESS_KEY="$2"; shift 2 ;;
        --secret-key) SECRET_KEY="$2"; shift 2 ;;
        --region)     REGION="$2"; shift 2 ;;
        --namespace)  NAMESPACE="$2"; shift 2 ;;
        -h|--help)    usage ;;
        *) echo "unknown arg: $1" >&2; usage ;;
    esac
done
[[ -n "${CONTEXT}" && -n "${ACCESS_KEY}" && -n "${SECRET_KEY}" ]] || usage

command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found" >&2; exit 1; }

kubectl --context "${CONTEXT}" -n "${NAMESPACE}" create secret generic student-aws-creds \
    --from-literal=AWS_ACCESS_KEY_ID="${ACCESS_KEY}" \
    --from-literal=AWS_SECRET_ACCESS_KEY="${SECRET_KEY}" \
    --from-literal=AWS_DEFAULT_REGION="${REGION}" \
    --dry-run=client -o yaml | kubectl --context "${CONTEXT}" apply -f -

# Restart the VTT so it remounts the secret and rewrites ~/.aws (pod-delete; ArgoCD-safe, never rollout).
kubectl --context "${CONTEXT}" -n "${NAMESPACE}" delete pod \
    -l app.kubernetes.io/name=web-terminal >/dev/null 2>&1 || true

printf 'student-aws-creds applied on %s (region %s); web-terminal restarted.\n' "${CONTEXT}" "${REGION}" >&2
