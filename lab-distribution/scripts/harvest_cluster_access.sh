#!/usr/bin/env bash
# ABOUTME: Harvest a bootstrapped cluster's student-facing access info into a CSV row for the provisioning
# ABOUTME: pool (issue #37/#15). Reads live Services/Ingresses; cluster's own account never needs Secrets Mgr.
#
# Per cluster it emits ONE CSV row (printed to stdout, appendable to an aws-pool CSV that merge_pool.py
# ingests): name,region,console_url,burritbot_url,grafana_url,grafana_password,argocd_url,argocd_password
#
# Access-model reality (verified live 2026-06-27, see RUN-OF-SHOW backlog):
#   - console      = an NLB LoadBalancer Service (agent/console). Its raw *.elb.amazonaws.com hostname is
#                    UNIQUE per cluster and works with no DNS. This is the reliable student front door.
#   - grafana      = an ALB Ingress, HOST-ROUTED (grafana.agenticburn.com). The host must resolve to THIS
#                    cluster's ALB; for a fleet that needs a per-cluster hostname + DNS record. We emit the
#                    configured host AND the raw ALB hostname so a DNS decision can be made later.
#   - argocd       = ClusterIP today (not exposed). Emitted blank until an Ingress is added if we want it.
#   - burritbot    = not deployed yet (#38 backend decision); blank until it lands.
# Grafana admin is the static demo password (prometheus.yaml): admin / watchitburn-admin.
set -o pipefail

usage(){ echo "usage: AWS_PROFILE=<acct> $0 <cluster-name> [region]" >&2; exit 2; }
NAME="${1:?$(usage)}"; REGION="${2:-us-west-2}"
[[ "${NAME}" == watch-it-burn-* ]] || { echo "refusing non-watch-it-burn cluster: ${NAME}" >&2; exit 1; }
: "${AWS_PROFILE:?set AWS_PROFILE to the cluster account}"
command -v jq >/dev/null || { echo "need jq" >&2; exit 1; }

KCFG="$(mktemp)"; trap 'rm -f "${KCFG}"' EXIT
aws eks update-kubeconfig --kubeconfig "${KCFG}" --name "${NAME}" --region "${REGION}" >/dev/null 2>&1 \
  || { echo "cannot reach ${NAME} in ${AWS_PROFILE}" >&2; exit 1; }
kc(){ KUBECONFIG="${KCFG}" kubectl "$@"; }

# console NLB (the reliable per-cluster front door: chat + terminal + agent)
console_host=""; grafana_host=""; ah=""; bb=""
console_url=""; grafana_url=""; argocd_url=""; argocd_password=""; burritbot_url=""
grafana_password="watchitburn-admin"

console_host="$(kc -n agent get svc console -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)" || true
[[ -n "${console_host}" ]] && console_url="http://${console_host}"

# grafana: configured Ingress host (needs DNS to resolve to THIS cluster's ALB)
grafana_host="$(kc -n monitoring get ingress prometheus-grafana -o jsonpath='{.spec.rules[0].host}' 2>/dev/null)" || true
[[ -n "${grafana_host}" ]] && grafana_url="https://${grafana_host}"

# argocd: only emit a URL if it's actually exposed (Ingress), else blank (it's ClusterIP today)
if kc -n argocd get ingress argocd-server >/dev/null 2>&1; then
  ah="$(kc -n argocd get ingress argocd-server -o jsonpath='{.spec.rules[0].host}' 2>/dev/null)" || true
  [[ -n "${ah}" ]] && argocd_url="https://${ah}"
  argocd_password="$(kc -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' 2>/dev/null | base64 -d 2>/dev/null)" || true
fi

# burritbot: emit when the app is deployed (Service named burritbot); blank for now (#38)
bb="$(kc get svc -A -o json 2>/dev/null | jq -r '.items[] | select(.metadata.name|test("burritbot")) | .status.loadBalancer.ingress[0].hostname // empty' 2>/dev/null | head -1)" || true
[[ -n "${bb}" ]] && burritbot_url="http://${bb}"

# one CSV row (quote nothing risky; these are hostnames/urls)
printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
  "${NAME}" "${REGION}" "${console_url}" "${burritbot_url}" \
  "${grafana_url}" "${grafana_password}" "${argocd_url}" "${argocd_password}"
