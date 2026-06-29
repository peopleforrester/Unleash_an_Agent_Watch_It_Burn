#!/usr/bin/env bash
# ABOUTME: Round-2 live toggle — flips the CNCF admission policies Audit -> Enforce (require-resource-limits
# ABOUTME: + restrict-image-registries, the C2 villain-image wall). Idempotent. Reverse with --audit.
set -euo pipefail

# Kube-context safety (see CLAUDE.md): target an explicit context; never the global current-context.
CONTEXT="${CONTEXT:?set CONTEXT to the target kube-context}"
KCTL=(kubectl --context "${CONTEXT}")

ACTION="Enforce"
[[ "${1:-}" == "--audit" ]] && ACTION="Audit"

# Both policies are flipped together: the resource-limits wall (beat-1) and the registry allow-list that
# blocks the C2 villain image (docker.io/peopleforrester/<villain>). ArgoCD ignoreDifferences covers both
# failureAction fields, so selfHeal does not revert the live flip.
for pol in require-resource-limits restrict-image-registries; do
  echo "==> Setting ${pol} validate.failureAction to ${ACTION}"
  "${KCTL[@]}" patch clusterpolicy "${pol}" --type=json \
    -p="[{\"op\":\"replace\",\"path\":\"/spec/rules/0/validate/failureAction\",\"value\":\"${ACTION}\"}]"
done

echo "==> Done. Current actions:"
for pol in require-resource-limits restrict-image-registries; do
  printf '  %-28s %s\n' "${pol}" "$("${KCTL[@]}" get clusterpolicy "${pol}" -o jsonpath='{.spec.rules[0].validate.failureAction}')"
done
