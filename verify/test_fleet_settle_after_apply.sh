#!/usr/bin/env bash
# ABOUTME: fleet.sh follows each cluster apply that succeeds with a refresh-only apply of the same arguments (#956), so
# ABOUTME: a fresh cluster state does not read as drifted in the next drift report. Offline: terraform and aws are shims.
#
# Why. A fresh apply leaves attributes AWS reads back unwritten, and the drift report's refresh-only plan then lists
# the new state as changed outside Terraform. Measured on 2026-11-06 for the lab VPC (five resources) and the
# boundary (an IAM policy's `tags: null -> {}`), and on 2026-11-05 for the audit root (#795). The cluster root holds
# the same shapes and fleet.sh is what applies it, so fleet.sh settles it (docs/floor.md, "Settling a fresh state").
#
# What is run is fleet.sh's own `up <name>` with the bootstrap off; only the terraform under it is a shim, which
# logs every call's arguments one per line and fails an apply or a settle when told to.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -t fleet-settle.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"

# terraform: every apply's arguments go to ${T}/calls/<n>, one per line, in call order. TF_APPLY_FAIL=1 fails the
# build apply, TF_SETTLE_FAIL=1 the refresh-only one.
cat >"${SHIM}/terraform" <<'S'
#!/usr/bin/env bash
case " $* " in
  *" apply "*)
    n="$(ls "${T}/calls" | wc -l)"; printf '%s\n' "$@" >"${T}/calls/$((n + 1))"
    if [[ " $* " == *" -refresh-only "* ]]; then
        [[ -n "${TF_SETTLE_FAIL:-}" ]] && { echo "Error: shim settle failure" >&2; exit 1; }
        echo "shim settle ran"; exit 0
    fi
    [[ -n "${TF_APPLY_FAIL:-}" ]] && { echo "Error: shim apply failure" >&2; exit 1; }
    echo "{}" >"$(printf '%s\n' "$@" | sed -n 's/^-state=//p')"; echo "shim apply ran"; exit 0 ;;
  *" output "*"vpc_id"*) printf 'vpc-test' ;;
  *" output "*"private_subnet_ids"*) printf '["subnet-a","subnet-b"]' ;;
esac
exit 0
S
# aws: no attendee IAM user to adopt before the apply (#549).
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"iam list-user-tags"*) echo "An error occurred (NoSuchEntity) when calling the ListUserTags operation" >&2; exit 254 ;;
esac
exit 0
S
chmod +x "${SHIM}"/*
export T PATH="${SHIM}:${PATH}"

NAME=watch-it-burn-attendee-001
up() { # env assignments for the shim; output in ${T}/out, exit in its last line
    rm -rf "${T}/states" "${T}/logs" "${T}/calls"; mkdir -p "${T}/states" "${T}/logs" "${T}/calls"
    ( cd "$(dirname "${FLEET}")" && env WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" WIB_NO_BOOTSTRAP=1 "$@" \
        bash "${FLEET}" up "${NAME}" ) >"${T}/out" 2>&1
    echo "rc=$?" >>"${T}/out"
}
calls() { ls "${T}/calls" | wc -l; }
# The arguments of call <n> without the flags that say how to run it.
args_of() { grep -vxE -- '-refresh-only|-auto-approve|-no-color|-input=false' "${T}/calls/$1"; }

echo "== the apply succeeds: the settle follows it with the same arguments =="
up
check "up exits 0" 'grep -qx "rc=0" "${T}/out"'
check "terraform apply ran twice" '[[ "$(calls)" -eq 2 ]]'
check "the first is the build, not refresh-only" '[[ -f "${T}/calls/1" ]] && ! grep -qx -- "-refresh-only" "${T}/calls/1"'
check "the second is refresh-only and auto-approved" \
    '[[ -f "${T}/calls/2" ]] && grep -qx -- "-refresh-only" "${T}/calls/2" && grep -qx -- "-auto-approve" "${T}/calls/2"'
check "with the same state, chdir and variables as the build" \
    '[[ -f "${T}/calls/2" ]] && diff <(args_of 1) <(args_of 2) >/dev/null'
check "which name this cluster's state and pass event" \
    '[[ -f "${T}/calls/2" ]] && grep -qx -- "-state=${T}/states/${NAME}.tfstate" "${T}/calls/2" && grep -q "^event=" "${T}/calls/2"'
check "and its output is appended to the cluster's apply log, after the build's" \
    'grep -q "shim apply ran" "${T}/logs/${NAME}.apply.log" && grep -q "shim settle ran" "${T}/logs/${NAME}.apply.log"'

echo "== the apply fails: nothing is settled =="
up TF_APPLY_FAIL=1
check "up exits non-zero" 'grep -q "^rc=" "${T}/out" && ! grep -qx "rc=0" "${T}/out"'
check "only the build apply ran" '[[ "$(calls)" -eq 1 ]] && ! grep -qx -- "-refresh-only" "${T}/calls/1"'

echo "== the settle fails: the run says so and fails =="
up TF_SETTLE_FAIL=1
check "up exits non-zero" 'grep -q "^rc=" "${T}/out" && ! grep -qx "rc=0" "${T}/out"'
check "the cluster is reported built but unsettled" 'grep -q "FAILED: ${NAME} (built, but its state did not settle" "${T}/out"'
check "and the settle's error is in the apply log" 'grep -q "shim settle failure" "${T}/logs/${NAME}.apply.log"'

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
