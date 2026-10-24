#!/usr/bin/env bash
# ABOUTME: Puts the cluster's bootstrap secrets behind OpenBao (#394, question 656): `token` writes the per-cluster
# ABOUTME: root token, `seed` writes the Datadog keys into OpenBao and has ESO materialise datadog-secret from them.
#
# Usage: CONTEXT=<kube-context> [KUBECONFIG=<isolated file>] infra/openbao-secrets.sh token
#        CONTEXT=<kube-context> WITB_DD_API_KEY=... WITB_DD_APP_KEY=... infra/openbao-secrets.sh seed
#
# token  Creates the openbao and platform namespaces if missing and writes the root token twice:
#        openbao/openbao-root-token (the server's dev root token, gitops/apps/openbao.yaml) and
#        platform/openbao-token (what ESO's ClusterSecretStore authenticates with). An existing token is
#        REUSED, never rotated: the dev server reads it once at start, so a new value on a running cluster
#        would lock ESO out until the pod restarted, and a restart empties the in-memory store.
# seed   Waits for the OpenBao pod and ESO's webhook, writes secret/datadog {api-key, app-key} through
#        `kubectl exec` (the keys go over stdin, never onto a command line on this host), applies
#        security/openbao/datadog-externalsecrets.yaml, and waits until datadog-secret exists in datadog,
#        monitoring and security. Idempotent: fleet.sh converge re-runs it to repair key drift, and after
#        an OpenBao restart.
#
# The target is never guessed: CONTEXT is required and passed to every kubectl call (AGENTS.md, Kube-context
# safety). Anything missing or not ready in time is a failure with the reason printed.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTERNAL_SECRETS="${REPO}/security/openbao/datadog-externalsecrets.yaml"
WAIT_S="${OPENBAO_WAIT_S:-600}"
readonly SECRET_NAMESPACES="datadog monitoring security"

log() { printf '    openbao: %s\n' "$*" >&2; }
die() { printf 'openbao-secrets.sh: %s\n' "$*" >&2; exit 1; }
[[ -n "${CONTEXT:-}" ]] || die "CONTEXT is not set: name the kube-context of the cluster to act on"
kc() { kubectl --context "${CONTEXT}" "$@"; }

# Poll until "$@" succeeds or WAIT_S passes. The resources waited on are created by Argo CD a moment
# after their Application, so a single `rollout status` would fail on "not found" before they exist.
wait_for() {
    local what="$1" deadline=$(( SECONDS + WAIT_S ))
    shift
    until "$@" >/dev/null 2>&1; do
        (( SECONDS < deadline )) || die "${what} not ready after ${WAIT_S}s on ${CONTEXT}"
        sleep 5
    done
}

# True once ESO has written THIS api key, not merely once a datadog-secret exists: on a key-drift repair
# the old Secret is already there, and passing on it would report a repair that has not happened.
secret_has_key() {
    [[ "$(kc -n "$1" get secret datadog-secret -o jsonpath='{.data.api-key}' 2>/dev/null | base64 -d 2>/dev/null)" == "$2" ]]
}

ensure_namespace() { kc create namespace "$1" --dry-run=client -o yaml | kc apply -f - >/dev/null; }

cmd_token() {
    ensure_namespace openbao
    ensure_namespace platform
    local token
    token="$(kc -n openbao get secret openbao-root-token -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    if [[ -z "${token}" ]]; then
        token="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
        [[ "${#token}" -eq 64 ]] || die "could not generate a root token"
        log "generated a new root token"
    else
        log "reusing the existing root token"
    fi
    local ns name ns_name
    for ns_name in "openbao/openbao-root-token" "platform/openbao-token"; do
        ns="${ns_name%%/*}"; name="${ns_name#*/}"
        kc -n "${ns}" create secret generic "${name}" --from-literal=token="${token}" \
            --dry-run=client -o yaml | kc apply -f - >/dev/null
    done
    log "root token in openbao/openbao-root-token and platform/openbao-token"
}

cmd_seed() {
    local api="${WITB_DD_API_KEY:-}" app="${WITB_DD_APP_KEY:-}"
    [[ -n "${api}" && -n "${app}" ]] || die "seed needs WITB_DD_API_KEY and WITB_DD_APP_KEY"
    [[ -f "${EXTERNAL_SECRETS}" ]] || die "missing ${EXTERNAL_SECRETS}"

    wait_for "the OpenBao pod" kc -n openbao wait --for=condition=Ready pod/openbao-0 --timeout=5s
    local token
    token="$(kc -n openbao get secret openbao-root-token -o jsonpath='{.data.token}' | base64 -d)"
    [[ -n "${token}" ]] || die "openbao/openbao-root-token is empty; run '$0 token' first"
    # Three lines on stdin: the token and the two keys. `read` keeps them off this host's process list;
    # inside the pod they reach `bao` as arguments, in the one pod that holds them anyway.
    # shellcheck disable=SC2016  # the script is expanded by the pod's shell, not this one
    printf '%s\n%s\n%s\n' "${token}" "${api}" "${app}" \
        | kc -n openbao exec -i openbao-0 -c openbao -- sh -ec \
            'read -r t; read -r a; read -r p; BAO_ADDR=http://127.0.0.1:8200 BAO_TOKEN="$t" bao kv put -mount=secret datadog api-key="$a" app-key="$p" >/dev/null' \
        || die "writing secret/datadog into OpenBao failed (is the root token the one the server started with?)"
    log "secret/datadog written"

    wait_for "ESO's ExternalSecret CRD" kc wait --for=condition=Established crd/externalsecrets.external-secrets.io --timeout=5s
    wait_for "ESO's webhook" kc -n platform rollout status deploy/external-secrets-webhook --timeout=5s
    wait_for "ESO's controller" kc -n platform rollout status deploy/external-secrets --timeout=5s
    local ns
    for ns in ${SECRET_NAMESPACES}; do ensure_namespace "${ns}"; done
    # The webhook can report Ready a moment before it serves, so the apply is retried with the rest.
    wait_for "the datadog-secret ExternalSecrets" kc apply -f "${EXTERNAL_SECRETS}"
    for ns in ${SECRET_NAMESPACES}; do
        kc -n "${ns}" annotate externalsecret datadog-secret "force-sync=$(date +%s)" --overwrite >/dev/null
        wait_for "datadog-secret in ${ns} carrying the seeded key" secret_has_key "${ns}" "${api}"
    done
    log "datadog-secret written by ESO in ${SECRET_NAMESPACES// /\/}"
}

case "${1:-}" in
    token) cmd_token ;;
    seed)  cmd_seed ;;
    *)     echo "usage: CONTEXT=<kube-context> $0 token|seed" >&2; exit 2 ;;
esac
