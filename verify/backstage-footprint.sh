#!/usr/bin/env bash
# ABOUTME: Measures Backstage + Postgres on one live attendee cluster before Backstage goes fleet-wide (#484):
# ABOUTME: usage against requests, node allocatable against requests, and pods on two entities' Kubernetes tabs.
#
# Usage: CONTEXT=<kube-context> [SAMPLES=6] [INTERVAL=10] bash verify/backstage-footprint.sh
#        (KUBECONFIG=<isolated-file> may prefix it for this one command; it is never exported.)
#
# Run it on a t3.2xlarge already carrying the attendee profile, with the backstage app synced on the rebuilt,
# signed image (#483). Everything here is a READ: the only thing it starts is a port-forward to the backstage
# Service, which it stops on exit.
#
# Usage is read from the kubelet summary API (nodes/<node>/proxy/stats/summary), not `kubectl top`: nothing in
# this repo installs metrics-server, so the metrics API `top` reads is absent on an attendee cluster. The
# summary is what metrics-server would have scraped; verify/backstage_footprint.py says which field is which.
# SAMPLES readings INTERVAL seconds apart give a last and a peak; leave the Backstage tab open and click
# around during the window to see a working peak rather than an idle one.
#
# Exit 0 only when every backstage pod is Ready, every container produced a reading, and the Kubernetes tab
# lists at least one pod and no errors for both unicorn-party and workshop-agent. The numbers themselves are
# reported, not judged: they are what #484 asks to see.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
: "${CONTEXT:?CONTEXT is required: name the kube-context of the attendee cluster to measure}"
SAMPLES="${SAMPLES:-6}"
INTERVAL="${INTERVAL:-10}"
readonly NS=backstage
readonly ENTITIES=(component:default/unicorn-party component:default/workshop-agent)

missing=()
for tool in kubectl python3 curl; do
    command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool} is not on PATH")
done
if [[ "${#missing[@]}" -gt 0 ]]; then
    printf 'cannot measure:\n' >&2
    printf '  %s\n' "${missing[@]}" >&2
    exit 1
fi

k() { kubectl --context "${CONTEXT}" "$@"; }
fp() { python3 "${SCRIPT_DIR}/backstage_footprint.py" "$@"; }

work="$(mktemp -d)"
pf_pid=""
cleanup() {
    if [[ -n "${pf_pid}" ]]; then kill "${pf_pid}" 2>/dev/null || true; fi
    rm -rf "${work}"
}
trap cleanup EXIT

fail=0
failed=()
mark() { fail=1; failed+=("$1"); }

printf '== cluster ==\n'
printf '  context %s, server %s\n' "${CONTEXT}" \
    "$(k config view --minify -o jsonpath='{.clusters[0].cluster.server}')"

k get nodes -o json >"${work}/nodes.json"
k get pods -A -o json >"${work}/pods.json"

printf '\n== backstage pods (image is the digest actually running) ==\n'
fp pods "${work}/pods.json" || mark "backstage pods not all Ready"

printf '\n== usage over %s samples, %ss apart (kubelet summary) ==\n' "${SAMPLES}" "${INTERVAL}"
mapfile -t ns_nodes < <(k -n "${NS}" get pods -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | sed '/^$/d')
summaries=()
for ((i = 1; i <= SAMPLES; i++)); do
    for node in "${ns_nodes[@]}"; do
        f="${work}/summary-${i}-${node}.json"
        k get --raw "/api/v1/nodes/${node}/proxy/stats/summary" >"${f}"
        summaries+=("${f}")
    done
    [[ "${i}" -lt "${SAMPLES}" ]] && sleep "${INTERVAL}"
done
if [[ "${#summaries[@]}" -eq 0 ]]; then
    printf '  no node hosts a backstage pod, so there is nothing to sample\n'
    mark "no usage readings"
else
    fp usage "${work}/pods.json" "${summaries[@]}" || mark "a backstage container produced no usage reading"
fi

printf '\n== node allocatable versus requests (all namespaces, Running and Pending pods) ==\n'
fp requests "${work}/nodes.json" "${work}/pods.json"

# One entity's Kubernetes tab: fetch the entity, then ask the kubernetes backend for its objects with it.
# Chained with && because set -e does not apply inside a function called from `||`.
tab_check() {
    local ref="$1" kind rest namespace name
    kind="${ref%%:*}"
    rest="${ref#*:}"
    namespace="${rest%%/*}"
    name="${rest#*/}"
    curl -fsS -H "Authorization: Bearer ${token}" \
            "${base}/api/catalog/entities/by-name/${kind}/${namespace}/${name}" >"${work}/entity-${name}.json" \
        && python3 -c 'import json, sys; print(json.dumps({"entity": json.load(open(sys.argv[1]))}))' \
            "${work}/entity-${name}.json" >"${work}/body-${name}.json" \
        && curl -fsS -X POST -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' \
            --data @"${work}/body-${name}.json" \
            "${base}/api/kubernetes/services/${name}" >"${work}/tab-${name}.json" \
        && fp tab "${ref}" "${work}/tab-${name}.json"
}

printf '\n== Kubernetes tab (POST /api/kubernetes/services/<name>, as the portal does, signed in as guest) ==\n'
port="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
# kubectl itself, not k(): a backgrounded function is a subshell, and killing it would orphan the port-forward.
kubectl --context "${CONTEXT}" -n "${NS}" port-forward svc/backstage "${port}:80" >"${work}/port-forward.log" 2>&1 &
pf_pid=$!
base="http://127.0.0.1:${port}"
for _ in $(seq 1 30); do
    curl -fsS -o /dev/null "${base}/.backstage/health/v1/readiness" 2>/dev/null && break
    sleep 1
done
if ! curl -fsS -o /dev/null "${base}/.backstage/health/v1/readiness"; then
    printf '  backstage is not ready behind the port-forward:\n' >&2
    sed 's/^/    /' "${work}/port-forward.log" >&2
    mark "backstage not reachable"
else
    if curl -fsS -H 'X-Requested-With: XMLHttpRequest' "${base}/api/auth/guest/refresh" >"${work}/refresh.json" \
        && token="$(fp token "${work}/refresh.json")"; then
        for ref in "${ENTITIES[@]}"; do
            tab_check "${ref}" || mark "Kubernetes tab of ${ref}"
        done
    else
        mark "guest sign-in (/api/auth/guest/refresh)"
    fi
fi

if [[ "${fail}" -eq 0 ]]; then
    printf '\nBACKSTAGE FOOTPRINT MEASURED, ALL CHECKS GREEN\n'
else
    printf '\nBACKSTAGE FOOTPRINT CHECKS FAILED:\n' >&2
    printf '  %s\n' "${failed[@]}" >&2
    exit 1
fi
