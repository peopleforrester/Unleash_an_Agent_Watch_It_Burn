#!/usr/bin/env bash
# ABOUTME: The harvest CODE must stay in git and the harvest DATA must stay out of it; this pins both
# ABOUTME: halves so a future gitignore edit cannot quietly delete the only tool that captures an event.
#
# Why (issue #399). The Portland harvest produced the only record of what attendees actually did: 2,091
# distinct user messages, 580 terminal commands, per-challenge completion read off live cluster state,
# and the 108 beacon hits that are the authoritative Challenge 1 success count. It was produced by five
# scripts that lived in .harvest/, which is gitignored, so the tool was one `rm` from gone while the
# knowledge inside it existed nowhere else.
#
# The data stays ignored on purpose: it is attendee-typed prompts and terminal history from a live
# workshop, and it is not ours to commit.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

echo "== the code is present and tracked =="
for f in run.sh 01-clusters.py 02-forensics.py 03-falco.py 04-argo-datadog.py 05-analyze.py; do
    check "scripts/harvest/${f} exists" "[ -f '${REPO}/scripts/harvest/${f}' ]"
    check "scripts/harvest/${f} is NOT gitignored" \
          "! git -C '${REPO}' check-ignore -q 'scripts/harvest/${f}'"
done

echo "== the data is still ignored =="
check ".harvest/ is gitignored" "git -C '${REPO}' check-ignore -q '.harvest/anything.json'"
check "no harvested data is tracked" \
      "[ -z \"\$(git -C '${REPO}' ls-files '.harvest' 2>/dev/null)\" ]"

echo "== it is reusable, not hard-coded to one event =="
check "the entry point takes an event name" "grep -q 'WIB_EVENT' '${REPO}/scripts/harvest/run.sh'"
check "every pass honours WIB_EVENT" \
      "[ \$(grep -lc 'WIB_EVENT' ${REPO}/scripts/harvest/0*.py | wc -l) -eq 5 ]"
check "run.sh refuses without an event name" \
      "! bash '${REPO}/scripts/harvest/run.sh' </dev/null >/dev/null 2>&1"

echo "== a failed pass does not abort the rest =="
# The passes read different sources. A Datadog outage must not cost the cluster-state capture, which is
# the half that cannot be re-read once the fleet is torn down.
check "run.sh continues past a failing pass" "grep -q 'continuing' '${REPO}/scripts/harvest/run.sh'"

echo
if [ "${fail}" -gt 0 ]; then echo "FAILED: ${fail} check(s), ${pass} passed"; exit 1; fi
echo "All harvest-tracking checks passed (${pass})."
