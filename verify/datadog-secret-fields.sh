#!/usr/bin/env bash
# ABOUTME: Confirm datadog-secret exists in every namespace that reads it and carries every key the repo's
# ABOUTME: references name, printing key names only: no value is read out of the cluster (#594, PRD #13 M1).
#
# Usage:
#   verify/datadog-secret-fields.sh <kube-context>
#   KUBECONFIG=/tmp/<cluster>.kubeconfig verify/datadog-secret-fields.sh <kube-context>   (per command only)
#
# Why the template: `-o jsonpath={.data.api-key}`, `-o yaml` and `-o json` all bring the base64 value back to
# this shell, and `kubectl describe` is a different code path per kubectl version. The go-template below runs
# inside kubectl and emits each key's name and the word set or empty, so the value never reaches this
# process, the terminal or a log. PRD #13's Milestone 1 rule is "never print a credential value".
#
# The namespaces are the three consumers: the Datadog Agent (datadog), the OTel Collector (monitoring) and
# falcosidekick (security), the same three deploy-full-idp.sh step 3.6 and fleet.sh repair_datadog write.
# The keys are every secretKeyRef/keyName to datadog-secret under gitops/; verify/test_datadog_secret_fields.py
# fails when a reference names a key this list does not.
set -uo pipefail

CONTEXT="${1:-}"
if [[ -z "${CONTEXT}" ]]; then
    echo "usage: $0 <kube-context>   (no current-context fallback: name the cluster you mean)" >&2
    exit 2
fi

NAMESPACES=(datadog monitoring security)
REQUIRED_KEYS=(api-key app-key)
TEMPLATE='{{range $k, $v := .data}}{{$k}}={{if $v}}set{{else}}empty{{end}}{{"\n"}}{{end}}'

err_file="$(mktemp)"
trap 'rm -f "${err_file}"' EXIT
fail=0
for ns in "${NAMESPACES[@]}"; do
    # kubectl's error line is shown as it is (NotFound, Forbidden, a bad context): it carries no secret data.
    if ! fields="$(kubectl --context "${CONTEXT}" -n "${ns}" get secret datadog-secret \
            -o go-template="${TEMPLATE}" 2>"${err_file}")"; then
        printf '  FAIL  %-11s datadog-secret not readable: %s\n' "${ns}" "$(head -n1 "${err_file}")"
        fail=1
        continue
    fi
    missing=()
    for key in "${REQUIRED_KEYS[@]}"; do
        if grep -qx "${key}=set" <<<"${fields}"; then
            continue
        elif grep -qx "${key}=empty" <<<"${fields}"; then
            missing+=("${key}(empty)")
        else
            missing+=("${key}(absent)")
        fi
    done
    present="$(sed -n 's/=set$//p' <<<"${fields}" | paste -sd, -)"
    if [[ "${#missing[@]}" -eq 0 ]]; then
        printf '  PASS  %-11s datadog-secret fields: %s\n' "${ns}" "${present}"
    else
        printf '  FAIL  %-11s datadog-secret fields: %s; missing: %s\n' "${ns}" "${present:-none}" "${missing[*]}"
        fail=1
    fi
done

if [[ "${fail}" -eq 0 ]]; then
    echo "datadog-secret on ${CONTEXT}: every field present in ${NAMESPACES[*]} (values not read)"
else
    echo "datadog-secret on ${CONTEXT}: INCOMPLETE (values not read)" >&2
    exit 1
fi
