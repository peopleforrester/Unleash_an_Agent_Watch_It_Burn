#!/usr/bin/env bash
# ABOUTME: converge must repair a stale agent tool list, because Argo structurally cannot: it drops the
# ABOUTME: whole tools array rather than writing one element, and reports Synced while the cluster is wrong.
#
# Why (#349). get_recipe was renamed to get_vault_entry. The manifest updated, every live cluster kept the
# dead name, Challenge 5 became impossible, and Argo said Synced and Healthy the entire time. Narrowing the
# ignore made the drift visible but not fixable; converge did not touch the field; an explicit sync said
# "no more tasks"; Force changed nothing. Replacing the object is the only repair, so it lives in converge.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
src="$(cat "${FLEET}")"

echo "== the repair exists and runs as part of converge =="
check "repair_agent_tools is defined"        'grep -q "^repair_agent_tools() {" <<<"$src"'
check "repair_one calls it"                  'grep -q "repair_agent_tools \"\${name}\" \"\${kcfg}\"" <<<"$src"'
# Ordering: after the injection repair, so a cycled pod is instrumented by the step that follows.
check "it runs alongside the other repairs"  'grep -A6 "^repair_one() {" <<<"$src" | grep -q repair_agent_tools'

echo "== it is idempotent: it acts only on an actual difference =="
check "it reads the committed list"          'grep -q "resources.yaml" <<<"$src"'
check "it reads the live list"               'grep -q "kubectl -n agent get agent workshop-agent" <<<"$src"'
check "it compares before deleting"          'grep -q "if \[\[ \"\${live}\" != \"\${want}\" \]\]" <<<"$src"'
check "no live list means no action"         'grep -q "\[\[ -n \"\${live}\" \]\] || return 0" <<<"$src"'
check "no committed list means no action"    'grep -q "\[\[ -n \"\${want}\" \]\] || return 0" <<<"$src"'

echo "== the repair is a recreate, which is the only thing that works =="
check "it deletes the Agent CR"              'grep -q "kubectl -n agent delete agent workshop-agent" <<<"$src"'
check "it says why a patch cannot work"      'grep -q "single element of the .spec.declarative.tools array" <<<"$src"'
check "it names the failure it prevents"     'grep -q "Challenge 5 impossible" <<<"$src"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
