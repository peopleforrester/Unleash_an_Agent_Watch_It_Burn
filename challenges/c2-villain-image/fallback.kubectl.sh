#!/usr/bin/env bash
# ABOUTME: C2 fallback: as workshop-mcp, create a Deployment of a villain image from a registry the allow-list
# ABOUTME: does not carry, and prove Kyverno's restrict-image-registries refuses it at admission. No model.
#
# Usage: CONTEXT=<admin-cluster kube-context> challenges/c2-villain-image/fallback.kubectl.sh
#
# BurritoBot's deploy_app runs in workshop-mcp, as that pod's own ServiceAccount (workshop-mcp, bound to the
# agent's Role; not agent-sa, #553), and applies a Deployment in the agent namespace. So this creates one the
# same way: as workshop-mcp, in agent, with docker.io/peopleforrester/<villain>:latest.
# The Deployment carries limits, so the only policy it breaks is the registry allow-list and the denial
# message can only be that one. challenges/01-cncf-wall/fallback.kubectl.sh is the retired workshop Beat 1
# (resource limits, nginx) and is not this beat (#499).
#
# The manifest goes in on stdin: no scratch files.
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the admin cluster kube-context}"
command -v kubectl >/dev/null 2>&1 || { echo "kubectl not found on PATH" >&2; exit 1; }

readonly NS="agent"
readonly SA="system:serviceaccount:${NS}:workshop-mcp"
readonly POLICY="restrict-image-registries"
readonly VILLAIN="joker"
readonly IMAGE="docker.io/peopleforrester/${VILLAIN}:latest"
readonly NAME="c2-fallback-${VILLAIN}"

kc() { kubectl --context "${CONTEXT}" -n "${NS}" "$@"; }

failed=0
check() {
    if [[ "$2" == "ok" ]]; then
        echo "  PASS  $1"
    else
        echo "  FAIL  $1${3:+: $3}"
        failed=1
    fi
}

# The agent's Role has no delete verb, so the cleanup is the caller's own identity. Runs on every exit, so a
# Deployment that was wrongly admitted never keeps a villain running.
cleanup() { kc delete deployment "${NAME}" --ignore-not-found --wait=false >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> C2 villain image: create ${IMAGE} as ${SA} in ${NS} on ${CONTEXT}"
# A leftover from an earlier run would answer AlreadyExists, which is not a denial.
cleanup

can="$(kc auth can-i create deployments.apps --as="${SA}" 2>/dev/null || true)"
if [[ "${can}" == "yes" ]]; then
    check "workshop-mcp may create Deployments in ${NS} (so a refusal is admission, not RBAC)" ok
else
    check "workshop-mcp may create Deployments in ${NS}" fail "can-i said '${can:-nothing}'; a refusal would be RBAC"
fi

rc=0
out="$(kc create --as="${SA}" -f - 2>&1 <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${NAME}
  namespace: ${NS}
  labels: { app: ${NAME} }
spec:
  replicas: 1
  selector: { matchLabels: { app: ${NAME} } }
  template:
    metadata:
      labels: { app: ${NAME} }
    spec:
      containers:
        - name: villain
          image: ${IMAGE}
          resources:
            requests: { cpu: 10m, memory: 32Mi }
            limits: { cpu: 100m, memory: 64Mi }
YAML
)" || rc=$?
echo "    kubectl said: ${out}"

if [[ "${rc}" -eq 0 ]]; then
    check "the villain Deployment is refused at admission" fail \
        "it was admitted; is ${POLICY} in Deny? (challenges/01-cncf-wall/toggle-kyverno-enforce.sh)"
else
    check "the villain Deployment is refused at admission" ok
fi
if [[ "${rc}" -eq 0 ]]; then
    check "the denial names ${POLICY}" fail "there was no denial"
elif grep -q "${POLICY}" <<<"${out}"; then
    check "the denial names ${POLICY}" ok
else
    check "the denial names ${POLICY}" fail "the refusal above is not that policy's"
fi

if [[ "${failed}" -eq 0 ]]; then
    echo "==> C2 PROVEN: Kyverno's registry allow-list refused the villain image before any pod existed."
else
    echo "==> C2 NOT PROVEN: see the FAIL lines above." >&2
    exit 1
fi
