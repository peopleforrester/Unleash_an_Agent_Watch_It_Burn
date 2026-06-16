#!/usr/bin/env bash
# ABOUTME: Deterministic fallback for Beat 1 — proves all three CNCF walls without the agent.
# ABOUTME: Runs as the scoped agent ServiceAccount so the outcomes match the live demo.
set -euo pipefail

NS="${1:?usage: fallback.kubectl.sh <attendee-namespace>}"
SA="system:serviceaccount:${NS}:agent-sa"
AS=(--as="${SA}")

echo "==> Beat 1, Step 1a: deploy a non-compliant workload (policy in Audit) — expect ADMIT"
kubectl "${AS[@]}" -n "${NS}" create deployment sample-web --image=nginx:latest

echo "==> Toggle: switch the resource-limits policy to Enforce"
kubectl patch clusterpolicy require-resource-limits --type=json \
  -p='[{"op":"replace","path":"/spec/rules/0/validate/failureAction","value":"Enforce"}]'
echo "    (waiting for the webhook to pick up the change)"
sleep 5

echo "==> Beat 1, Step 1b: redeploy the same non-compliant workload — expect REJECT (Kyverno)"
kubectl "${AS[@]}" -n "${NS}" delete deployment sample-web --ignore-not-found
if kubectl "${AS[@]}" -n "${NS}" create deployment sample-web --image=nginx:latest; then
  echo "!! UNEXPECTED: workload admitted while policy is in Enforce" >&2
  exit 1
fi

echo "==> Beat 1, Step 2: privilege escalation — expect FORBIDDEN (RBAC, no toggle)"
if kubectl "${AS[@]}" create clusterrolebinding agent-admin \
     --clusterrole=cluster-admin --serviceaccount="${NS}:agent-sa"; then
  echo "!! UNEXPECTED: clusterrolebinding created — RBAC scoping failed" >&2
  exit 1
fi

echo "==> Beat 1, Step 3: out-of-band mutation of an ArgoCD-managed resource — expect DENY (admission)"
if kubectl "${AS[@]}" -n "${NS}" scale deployment argocd-managed-app --replicas=5; then
  echo "!! UNEXPECTED: drift admitted — block-argocd-drift policy failed" >&2
  exit 1
fi

echo "==> All three walls held. Beat 1 deterministic path complete."
