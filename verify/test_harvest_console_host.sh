#!/usr/bin/env bash
# ABOUTME: fleet.sh hands the harvester an attendee's two-word hostname as WIB_CONSOLE_HOST, and never
# ABOUTME: registers a retired cluster name through /admin/import (#444). Offline: the harvester is a shim.
#
# Why. provisioning-agenticburn#14 retired rounds in harvest_cluster_access.sh. It maps the community and
# admin clusters to their hosts itself, but an attendee's memorable name (soot-sabrina) cannot be worked out
# from watch-it-burn-attendee-NNN, so it reads WIB_CONSOLE_HOST and otherwise falls back to a-NNN, a route
# #359 removed. Without the variable pool.csv's console_url is an a-NNN host that 404s, or the raw NLB.
# Separately, a watch-it-burn-<owner>-student or r<N>-<n> row imported into the app is classified retired
# and never handed out, so all it does is clutter /admin/roster.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .harvest-host-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
mkdir -p "${T}/prov/scripts" "${T}/states" "${T}/logs"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# The harvester shim prints the cluster and the WIB_CONSOLE_HOST it was given, as one CSV-like row.
cat >"${T}/prov/scripts/harvest_cluster_access.sh" <<'EOF'
#!/usr/bin/env bash
printf '%s,%s,host=%s\n' "$1" "$2" "${WIB_CONSOLE_HOST-<unset>}"
EOF
chmod +x "${T}/prov/scripts/harvest_cluster_access.sh"

# Run one expression against a sourced fleet.sh, pointed at the shim and temp dirs. stderr (log) is kept
# so a check can read what fleet.sh said; curl and kubectl are trapped so nothing leaves the box.
q() { ( cd "$(dirname "${FLEET}")" && WIB_PROVISION_DIR="${T}/prov" WIB_STATE_DIR="${T}/states" \
        WIB_LOG_DIR="${T}/logs" bash -c "source '${FLEET}' >/dev/null 2>&1
        curl() { echo CURL-CALLED >&2; }; kubectl() { echo KUBECTL-CALLED >&2; }
        provider_write_kubeconfig() { echo KUBECONFIG-CALLED >&2; }
        $1" 2>&1 ); }

echo "== harvest passes the attendee's two-word hostname as WIB_CONSOLE_HOST =="
want="$(q 'public_host_for watch-it-burn-attendee-042')"
check "the memorable host is a two-word agenticburn name" '[[ "${want}" =~ ^[a-z]+-[a-z]+\.agenticburn\.com$ ]]'
got="$(q 'harvest_one watch-it-burn-attendee-042')"
check "harvest_one hands the harvester that same host" \
  '[[ "${got}" == "watch-it-burn-attendee-042,us-west-2,host=${want}" ]]'
check "bare hostname, no scheme" '[[ "${got}" != *"host=http"* ]]'
check "never the a-NNN route #359 removed" '[[ "${got}" != *"host=a-"* ]]'
# A variable left exported in the operator's shell must not stamp one host onto every row.
stale="$(WIB_CONSOLE_HOST=stale-host.agenticburn.com q 'harvest_one watch-it-burn-attendee-007')"
check "an exported WIB_CONSOLE_HOST does not override the per-cluster name" \
  '[[ "${stale}" == "watch-it-burn-attendee-007,us-west-2,host=$(q "public_host_for watch-it-burn-attendee-007")" ]]'
for n in watch-it-burn-community watch-it-burn-michael-admin; do
    r="$(WIB_CONSOLE_HOST=stale-host.agenticburn.com q "harvest_one ${n}")"
    check "a roster cluster (${n}) is left to the harvester's own mapping: empty host" \
      '[[ "${r}" == "${n},us-west-2,host=" ]]'
done
fleet="$(WIB_ATTENDEE_ACCOUNTS=a1,a2 q 'require_tools() { :; }; cmd_harvest 2' | grep '^watch-it-burn-')"
check "cmd_harvest gives every attendee row its own host" \
  '[[ "$(wc -l <<<"${fleet}")" == 4 && "$(cut -d= -f2 <<<"${fleet}" | sort -u | wc -l)" == 4 ]]'
check "and each is the one public_host_for publishes" \
  '( while IFS=, read -r n _ h; do [[ "${h#host=}" == "$(q "public_host_for ${n}")" ]] || exit 1; done <<<"${fleet}" )'

echo "== ingest never registers a retired cluster name through /admin/import =="
# A state file for each, so the only thing that can stop the import is the name check.
for n in watch-it-burn-michael-student watch-it-burn-whitney-student watch-it-burn-r2-1 watch-it-burn-r3-2 \
         watch-it-burn-attendee-001 watch-it-burn-community watch-it-burn-michael-admin; do
    : >"${T}/states/${n}.tfstate"
done
for n in watch-it-burn-michael-student watch-it-burn-whitney-student watch-it-burn-r2-1 watch-it-burn-r3-2; do
    out="$(q "ingest_one ${n} accen-dev; echo rc=\$?")"
    check "${n} is refused and says so" 'grep -q "REFUSING" <<<"${out}" && grep -q "rc=0" <<<"${out}"'
    check "${n} never reaches the cluster or the import" '! grep -qE "CURL-CALLED|KUBECTL-CALLED|KUBECONFIG-CALLED" <<<"${out}"'
    check "${n} is not queued for the ingest retry loop" '[[ -z "$(cat "${T}"/logs/.failures.* 2>/dev/null)" ]]'
done
# The live classes still go on to the cluster: the name check stops nothing it should not.
for n in watch-it-burn-attendee-001 watch-it-burn-community watch-it-burn-michael-admin; do
    out="$(WIB_INGEST_LB_WAIT=0 q "ingest_one ${n} accen-dev")"
    check "${n} is not refused" '! grep -q "REFUSING" <<<"${out}" && grep -q "KUBECONFIG-CALLED" <<<"${out}"'
done
rm -f "${T}"/logs/.failures.*
out="$(q 'cmd_ingest_instructors() { :; }; resolve_admin_token() { echo t; }; require_tools() { :; }
          aws() { echo "[]"; }; cmd_ingest watch-it-burn-r2-1 watch-it-burn-michael-student; echo rc=$?')"
check "cmd_ingest by name refuses the retired names without a failure" \
  '[[ "$(grep -c REFUSING <<<"${out}")" == 2 ]] && ! grep -q CURL-CALLED <<<"${out}"'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
