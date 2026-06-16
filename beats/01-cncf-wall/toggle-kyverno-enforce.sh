#!/usr/bin/env bash
# ABOUTME: Beat-1 live toggle — flips the require-resource-limits policy Audit -> Enforce.
# ABOUTME: Idempotent; safe to run repeatedly. Reverse with the --audit flag.
set -euo pipefail

ACTION="Enforce"
[[ "${1:-}" == "--audit" ]] && ACTION="Audit"

echo "==> Setting require-resource-limits validate.failureAction to ${ACTION}"
kubectl patch clusterpolicy require-resource-limits --type=json \
  -p="[{\"op\":\"replace\",\"path\":\"/spec/rules/0/validate/failureAction\",\"value\":\"${ACTION}\"}]"

echo "==> Done. Current action:"
kubectl get clusterpolicy require-resource-limits \
  -o jsonpath='{.spec.rules[0].validate.failureAction}{"\n"}'
