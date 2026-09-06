#!/usr/bin/env bash
# ABOUTME: Behavioural tests for the zero audit (#255): a clean account passes with the lab VPC's
# ABOUTME: allowances, and any leftover cluster, instance, load balancer, target group, volume, extra NAT,
# ABOUTME: unmatched Elastic IP or foreign ENI fails by id. Offline; aws is a shim.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-zero-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"; fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# The shim answers each query from a file named after the query kind; missing file = empty answer.
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"list-clusters"*) f=eks ;; *"describe-instances"*) f=ec2 ;; *"describe-load-balancers"*) f=elbv2 ;;
  *"describe-target-groups"*) f=tg ;; *"describe-volumes"*) f=vol ;; *"describe-nat-gateways"*) f=nat ;;
  *"describe-addresses"*) f=eip ;; *"describe-network-interfaces"*) f=eni ;; *) f=none ;;
esac
cat "${T}/${AWS_PROFILE}.${f}" 2>/dev/null; exit 0
S
chmod +x "${SHIM}/aws"; export T PATH="${SHIM}:${PATH}"
src() { ( cd "$(dirname "${FLEET}")" && WIB_ATTENDEE_ACCOUNTS="${ACCTS:-acct-a}" bash -c "source '${FLEET}' >/dev/null 2>&1; set +e; $1" 2>&1 ) ; }
clean() { rm -f "${T}"/acct-a.* "${T}"/acct-b.*; printf 'nat-1\n' >"${T}/acct-a.nat"; printf 'eipalloc-1\n' >"${T}/acct-a.eip"
  printf 'eni-1\tInterface for NAT Gateway nat-1\neni-2\tVPC Endpoint Interface vpce-1\n' >"${T}/acct-a.eni"; }

echo "== a clean account =="
clean; out="$(src 'audit_zero; echo rc=$?')"
check "passes with one NAT, its address and the NAT/endpoint ENIs" 'grep -q "rc=0" <<<"$out" && grep -q "acct-a: ZERO" <<<"$out"'

echo "== leftovers fail by id =="
clean; printf 'vol-0abc\tvol-0def\n' >"${T}/acct-a.vol"; out="$(src 'audit_zero; echo rc=$?; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"')"
check "a stray volume fails and is named" 'grep -q "rc=1" <<<"$out" && grep -q "volume NOT zero: vol-0abc vol-0def" <<<"$out" && grep -q "zero:acct-a:volume" <<<"$out"'
clean; printf 'watch-it-burn-r2-1\n' >"${T}/acct-a.eks"; out="$(src 'audit_zero; echo rc=$?')"
check "a surviving cluster fails and is named" 'grep -q "rc=1" <<<"$out" && grep -q "eks NOT zero: watch-it-burn-r2-1" <<<"$out"'
clean; printf 'k8s-agent-console-1\n' >"${T}/acct-a.elbv2"; printf 'k8s-apps-demo-1\n' >"${T}/acct-a.tg"; out="$(src 'audit_zero; echo rc=$?')"
check "a load balancer and a target group both fail" 'grep -q "elbv2 NOT zero: k8s-agent-console-1" <<<"$out" && grep -q "target-group NOT zero: k8s-apps-demo-1" <<<"$out"'
clean; printf 'eipalloc-1\neipalloc-orphan\n' >"${T}/acct-a.eip"; out="$(src 'audit_zero; echo rc=$?')"
check "an Elastic IP beyond the NAT count fails" 'grep -q "rc=1" <<<"$out" && grep -q "2 Elastic IP(s) for 1 NAT" <<<"$out"'
clean; printf 'eni-1\tInterface for NAT Gateway nat-1\neni-9\tELB app/k8s-agent/abc\n' >"${T}/acct-a.eni"; out="$(src 'audit_zero; echo rc=$?')"
check "an ENI that is not the NAT or the endpoint fails by id" 'grep -q "rc=1" <<<"$out" && grep -q "beyond the NAT and the Bedrock endpoint: eni-9" <<<"$out"'

echo "== every account is audited =="
clean; printf 'nat-b\n' >"${T}/acct-b.nat"; printf 'eipalloc-b\n' >"${T}/acct-b.eip"; printf 'i-0bad\n' >"${T}/acct-b.ec2"
out="$(ACCTS="acct-a,acct-b" src 'audit_zero; echo rc=$?')"
check "a clean account and a dirty one are both reported" 'grep -q "acct-a: ZERO" <<<"$out" && grep -q "acct-b: ec2 NOT zero: i-0bad" <<<"$out" && grep -q "rc=1" <<<"$out"'

echo "== wiring =="
check "down all ends with the audit" 'grep -q "\[\[ \"\${1:-}\" == \"all\" \]\] && audit_zero" "${FLEET}"'
check "down-fleet ends with the audit" 'awk "/^cmd_down_fleet\(\)/,/^}/" "${FLEET}" | grep -q "^    audit_zero"'
check "audit-zero is a subcommand" 'grep -q "audit-zero) cmd_audit_zero" "${FLEET}"'
echo; echo "  ${pass} passed, ${fail} failed"; exit $(( fail > 0 ))
