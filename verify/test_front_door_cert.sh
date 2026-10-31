#!/usr/bin/env bash
# ABOUTME: Behavioural test of infra/front-door-cert.sh (#638): it reuses or requests the one ACM certificate for
# ABOUTME: both domains, prints the validation CNAMEs while pending, the bare ARN once issued, and passes profile and region.
#
# Why. lab-platform's gateway verifies a roster cluster's front door against the system roots, so the console NLB
# has to present a public certificate, and the root has to be handed its ARN. A second request for the same pair
# would leave two certificates and two sets of records to keep in DNS, so an existing one is reused.
#
# Usage: verify/test_front_door_cert.sh      (offline; aws is a shim)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
SCRIPT="${REPO}/infra/front-door-cert.sh"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; CALLS="${T}/calls"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

ARN="arn:aws:acm:us-west-2:111122223333:certificate/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
# The shim answers from files: ${T}/existing (list-certificates), ${T}/status, ${T}/records (describe-certificate).
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "AWS_PROFILE=${AWS_PROFILE:-} aws $*" >>"${CALLS}"
case "$*" in
  *" list-certificates "*) cat "${T}/existing" ;;
  *" request-certificate "*) echo "${ARN}" ;;
  *" describe-certificate "*"Certificate.Status"*) cat "${T}/status" ;;
  *" describe-certificate "*"DomainValidationOptions"*) cat "${T}/records" ;;
  *) exit 1 ;;
esac
S
chmod +x "${SHIM}/aws"
export T CALLS ARN

run() { : >"${CALLS}"; rc=0; PATH="${SHIM}:${PATH}" bash "${SCRIPT}" "$@" >"${T}/out" 2>"${T}/err" || rc=$?; }
printf 'None\n' >"${T}/existing"
printf 'PENDING_VALIDATION\n' >"${T}/status"
printf '*.agenticburn.com\t_a1b2.agenticburn.com.\t_c3d4.xyz.acm-validations.aws.\n*.burritobot.co\t_e5f6.burritobot.co.\t_a7b8.xyz.acm-validations.aws.\n' >"${T}/records"

echo "== no certificate yet: it requests one and prints the records it waits on =="
run accen-dev us-west-2
check "it exits 3 while the certificate waits on DNS" '[[ "${rc}" -eq 3 ]]'
check "it requests *.agenticburn.com with *.burritobot.co, by DNS" \
  'grep -q -- "request-certificate --domain-name \*.agenticburn.com --subject-alternative-names \*.burritobot.co --validation-method DNS" "${CALLS}"'
check "the request is tagged project=watch-it-burn" 'grep "request-certificate" "${CALLS}" | grep -q "Key=project,Value=watch-it-burn"'
check "every call carries the profile and the region" \
  '[[ -s "${CALLS}" ]] && ! grep -v "^AWS_PROFILE=accen-dev aws acm --region us-west-2 " "${CALLS}" | grep -q .'
check "it prints the agenticburn.com record as set-demo-dns.py arguments" \
  'grep -q "python3 infra/dns/set-demo-dns.py --domain agenticburn.com _a1b2=_c3d4.xyz.acm-validations.aws$" "${T}/err"'
check "and the burritobot.co one" \
  'grep -q "python3 infra/dns/set-demo-dns.py --domain burritobot.co _e5f6=_a7b8.xyz.acm-validations.aws$" "${T}/err"'
check "it prints nothing on stdout while pending" '[[ ! -s "${T}/out" ]]'

echo "== one exists and is issued: it is reused and its ARN printed =="
printf '%s\n' "${ARN}" >"${T}/existing"; printf 'ISSUED\n' >"${T}/status"
run accen-dev us-west-2
check "it exits 0" '[[ "${rc}" -eq 0 ]]'
check "it requests nothing" '! grep -q "request-certificate" "${CALLS}"'
check "stdout is the bare ARN, the value labctl's --front-door-cert takes" '[[ "$(cat "${T}/out")" == "${ARN}" ]]'
check "stderr names the labctl flag it goes to" 'grep -q -- "--front-door-cert=" "${T}/err"'

echo "== failures are loud =="
printf 'FAILED\n' >"${T}/status"
run accen-dev us-west-2
check "a FAILED certificate exits 1, naming it" '[[ "${rc}" -eq 1 ]] && grep -q "is FAILED" "${T}/err"'
printf 'arn:aws:acm:us-east-1:111122223333:certificate/abc\n' >"${T}/existing"
run accen-dev us-west-2
check "an ARN from another region is refused" '[[ "${rc}" -eq 1 ]] && grep -q "no certificate ARN" "${T}/err"'
run accen-dev
check "no region: usage, exit non-zero, no AWS call" '[[ "${rc}" -ne 0 ]] && [[ ! -s "${CALLS}" ]]'

echo
echo "front-door-cert: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
