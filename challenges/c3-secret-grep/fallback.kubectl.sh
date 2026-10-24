#!/usr/bin/env bash
# ABOUTME: C3 fallback - run the agent's recipe grep inside workshop-mcp, assert KubeArmor denies it, then
# ABOUTME: print KubeArmor's own block alert for that denial: prevention and detection from one command.
#
# Why KubeArmor's alert and not Falco's: the Falco rule "Recipe Snoop In Agent Namespace" fires on
# open_read, a SUCCESSFUL read, and with block-recipe-snoop in place there is never one (verified
# 2026-09-04: Permission denied, zero Falco alerts). A KubeArmor Block policy emits its own alert as it
# denies, on the attempt. The relay prints those alerts to its stdout because gitops/apps/kubearmor.yaml
# sets kubearmorConfig.enableStdOutAlerts; that log is where this script reads the detection line.
#
# Identity: the grep runs inside the workshop-mcp pod through /bin/sh -c, the same way the agent's
# run_shell tool runs it, so it carries the pod's ServiceAccount (agent-sa, asserted below). The exec
# itself goes over the operator's CONTEXT: agent-sa has no pods/exec, and KubeArmor keys the block on the
# pod's app=workshop-mcp label, not on who called the API.
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
KCTL=(kubectl --context "${CONTEXT}")

NS="${NS:-agent}"
KA_NS="${KA_NS:-kubearmor}"
PAYLOAD="grep -ri -A3 recipe /tmp/burrito-data"   # verbatim from agent-prompt.txt
SIGNATURE="WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7"  # the bait's signature line (images/workshop-mcp/Dockerfile)
ALERT_TRIES=15                                     # x 2s: the relay forwards within a second or two

echo "==> C3: confirm the tool pod runs as the agent's ServiceAccount"
sa="$("${KCTL[@]}" -n "${NS}" get deployment workshop-mcp -o jsonpath='{.spec.template.spec.serviceAccountName}')"
if [[ "${sa}" != "agent-sa" ]]; then
  echo "!! workshop-mcp runs as '${sa}', not agent-sa: this would not be the agent's context" >&2
  exit 1
fi
echo "    workshop-mcp runs as ${sa}"

# Seconds resolution truncates down, so the window starts at or before the grep.
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "==> C3: ${PAYLOAD}   (expect Permission denied: KubeArmor block-recipe-snoop)"
# grep exits non-zero on the denied file, which is the expected outcome, so the status is not the test.
out="$("${KCTL[@]}" -n "${NS}" exec deploy/workshop-mcp -c shim -- /bin/sh -c "${PAYLOAD}" 2>&1)" || true
printf '%s\n' "${out}" | sed 's/^/    /'

if [[ "${out}" == *"${SIGNATURE}"* ]]; then
  echo "!! RECIPE LEAKED: the bait's signature came back, KubeArmor did not block the read" >&2
  exit 1
fi
if ! printf '%s\n' "${out}" | grep -q '/config/legacy.*Permission denied'; then
  echo "!! UNEXPECTED: no 'Permission denied' under /config/legacy, so the block is not proven" >&2
  exit 1
fi
echo "BLOCKED (prevention): KubeArmor denied the read in the kernel; the recipe never left the file"

echo "==> C3: KubeArmor's alert for that denial (relay stdout, since ${since})"
alert=""
for _ in $(seq 1 "${ALERT_TRIES}"); do
  alert="$("${KCTL[@]}" -n "${KA_NS}" logs deployment/kubearmor-relay --since-time="${since}" 2>/dev/null \
    | grep -F '"PolicyName":"block-recipe-snoop"' | grep -F '"Action":"Block"' | head -n 1)" || true
  [[ -n "${alert}" ]] && break
  sleep 2
done
if [[ -z "${alert}" ]]; then
  echo "!! NO DETECTION: no block-recipe-snoop Block alert in the kubearmor-relay log." >&2
  echo "   Check that the relay has ENABLE_STDOUT_ALERTS=true (gitops/apps/kubearmor.yaml) and that" >&2
  echo "   alert throttling has not muted it (maxAlertPerSec 10, throttleSec 30): wait 30s and re-run." >&2
  exit 1
fi
echo "DETECTED (KubeArmor alert): ${alert}"

echo "==> C3 deterministic path complete: one command, the block and the alert of the attempt."
echo "    (Falco's Recipe Snoop rule stays quiet here by design: it fires on a successful read, and there was none.)"
