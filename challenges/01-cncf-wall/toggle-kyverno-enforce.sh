#!/usr/bin/env bash
# ABOUTME: Round-2 live toggle — flips the CNCF admission policies Audit -> Deny (require-resource-limits
# ABOUTME: + restrict-image-registries, the C2 villain-image wall). Idempotent. Reverse with --audit.
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
KCTL=(kubectl --context "${CONTEXT}")

# Kyverno CEL ValidatingPolicy (#206): the action is spec.validationActions, a list. "Deny" is what the
# ClusterPolicy called Enforce. The script keeps its name and its --audit flag so nothing that calls it moves.
ACTION="Deny"
[[ "${1:-}" == "--audit" ]] && ACTION="Audit"

# Both policies are flipped together: the resource-limits wall (beat-1) and the registry allow-list that
# blocks the C2 villain image (docker.io/peopleforrester/<villain>). ArgoCD ignoreDifferences covers both
# /spec/validationActions fields, so selfHeal does not revert the live flip.
for pol in require-resource-limits restrict-image-registries; do
  echo "==> Setting ${pol} validationActions to [${ACTION}]"
  "${KCTL[@]}" patch validatingpolicy "${pol}" --type=json \
    -p="[{\"op\":\"replace\",\"path\":\"/spec/validationActions\",\"value\":[\"${ACTION}\"]}]"
done

echo "==> Done. Current actions:"
for pol in require-resource-limits restrict-image-registries; do
  printf '  %-28s %s\n' "${pol}" "$("${KCTL[@]}" get validatingpolicy "${pol}" -o jsonpath='{.spec.validationActions[0]}')"
done
