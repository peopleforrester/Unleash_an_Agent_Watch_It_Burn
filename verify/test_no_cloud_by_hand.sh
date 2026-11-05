#!/usr/bin/env bash
# ABOUTME: An offline test run by hand cannot reach a cluster or AWS either (#859): no-cloud.sh's no_cloud_guard and
# ABOUTME: no_cloud.py block, log and clear the cloud, and every offline test that runs fleet.sh guards itself with them.
#
# Why. #857 puts every test run-tests.sh runs behind stubbed cloud tools. A dispatched run that runs one test by
# hand, `bash verify/test_x.sh` or `python3 verify/test_x.py`, goes past the runner with the run's live KUBECONFIG
# and AWS session for watch-it-burn-community and watch-it-burn-private, which is how #421's test reached the
# community cluster for an hour. So each offline test that sources or runs fleet.sh guards itself. This holds the
# two per-test entry points to what they promise and every such test to calling them.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d -t no-cloud-by-hand.XXXX)"; trap 'rm -rf "${T}"' EXIT
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# A second layer of fakes behind the guard's stubs, as test_offline_suite_no_cloud.sh has, so a guard that let a
# call through lands here and is reported, never on the run's real aws.
mkdir -p "${T}/backstop"
for t in aws kubectl eksctl helm terraform; do
    printf '#!/bin/sh\necho "%s $*" >>"%s/backstop-calls"\nexit 1\n' "${t}" "${T}" >"${T}/backstop/${t}"
    chmod +x "${T}/backstop/${t}"
done
export PATH="${T}/backstop:${PATH}"

echo "== no_cloud_guard blocks and logs each cloud tool, and clears the cloud environment =="
# Each probe runs in a subshell that starts with a live-looking environment, the way a dispatched run starts.
probe() { ( export KUBECONFIG=/live/kubeconfig AWS_PROFILE=accen-dev AWS_REGION=us-west-2 \
    AWS_CONFIG_FILE=/live/aws-config AWS_SHARED_CREDENTIALS_FILE=/live/aws-credentials HECATON_CLUSTER_ENV=/live/env
    # shellcheck source=SCRIPTDIR/no-cloud.sh
    . "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/sh"; eval "$1" ) 2>&1; }
for tool in aws kubectl eksctl helm terraform; do
    check "${tool} on PATH is the stub" "[[ \"\$(probe 'command -v ${tool}')\" == '${T}/sh/bin/${tool}' ]]"
done
check "a fresh guard is clean" "probe 'no_cloud_clean' >/dev/null"
check "a call fails, says it is stubbed, and is logged with its arguments" \
  "out=\"\$(probe 'aws eks update-kubeconfig --name watch-it-burn-community; echo rc=\$?; cat \"\${NO_CLOUD_LOG}\"')\"
   grep -q 'rc=1' <<<\"\${out}\" && grep -q 'aws is stubbed here' <<<\"\${out}\" &&
   grep -qx 'aws eks update-kubeconfig --name watch-it-burn-community' <<<\"\${out}\""
check "after a call, no_cloud_clean fails and prints the call, indented" \
  "out=\"\$(probe 'kubectl --context watch-it-burn-private get ns; no_cloud_clean; echo rc=\$?')\"
   grep -q 'rc=1' <<<\"\${out}\" && grep -qx '        kubectl --context watch-it-burn-private get ns' <<<\"\${out}\""
check "a call from a child process with its own PATH prefix is logged too" \
  "probe 'bash -c \"PATH=/nowhere:\\\$PATH helm list\"; cat \"\${NO_CLOUD_LOG}\"' | grep -qx 'helm list'"
check "the AWS profile, region and the hecaton session file are unset" \
  "[[ \"\$(probe 'echo \${AWS_PROFILE-unset} \${AWS_REGION-unset} \${HECATON_CLUSTER_ENV-unset}')\" == 'unset unset unset' ]]"
check "KUBECONFIG and the AWS config files point at files that do not exist, under the guard's directory" \
  "probe '[[ \${KUBECONFIG} == ${T}/sh/* && ! -e \${KUBECONFIG} && \${AWS_CONFIG_FILE} == ${T}/sh/* && ! -e \${AWS_CONFIG_FILE}
           && \${AWS_SHARED_CREDENTIALS_FILE} == ${T}/sh/* && ! -e \${AWS_SHARED_CREDENTIALS_FILE} ]] && echo ok' | grep -qx ok"
check "the SDKs are kept off the host's instance role" "[[ \"\$(probe 'echo \${AWS_EC2_METADATA_DISABLED}')\" == true ]]"
check "a test's own fake put on PATH after the guard still answers first" \
  "probe 'mkdir -p ${T}/own; printf \"#!/bin/sh\necho own\n\" >${T}/own/aws; chmod +x ${T}/own/aws; PATH=${T}/own:\${PATH}; aws; no_cloud_clean && echo clean' |
   tr '\n' ' ' | grep -qx 'own clean '"
check "no_cloud_clean refuses to pass when the guard was never set up" \
  "! ( . '${HERE}/no-cloud.sh'; unset NO_CLOUD_LOG; no_cloud_clean ) 2>/dev/null"

echo "== no_cloud.py is the same guard for the Python tests =="
py() { ( export KUBECONFIG=/live/kubeconfig AWS_PROFILE=accen-dev AWS_SHARED_CREDENTIALS_FILE=/live/aws-credentials
    python3 -c "import sys; sys.path.insert(0, '${HERE}'); import no_cloud, os, subprocess; no_cloud.setup('${T}/py'); $1" ) 2>&1; }
check "a subprocess call to aws fails and is logged" \
  "py 'r = subprocess.run([\"aws\", \"sts\", \"get-caller-identity\"], capture_output=True); print(\"rc\", r.returncode); print(no_cloud.calls(), end=\"\")' |
   tr '\n' ' ' | grep -q 'rc 1 aws sts get-caller-identity'"
check "a fresh guard has no calls" "[[ -z \"\$(py 'print(no_cloud.calls(), end=\"\")')\" ]]"
check "the profile is unset and KUBECONFIG and the credentials file are moved under the guard" \
  "py 'print(os.environ.get(\"AWS_PROFILE\", \"unset\"), os.environ[\"KUBECONFIG\"].startswith(\"${T}/py/\"),
       os.environ[\"AWS_SHARED_CREDENTIALS_FILE\"].startswith(\"${T}/py/\"), os.environ[\"AWS_EC2_METADATA_DISABLED\"])' |
   grep -qx 'unset True True true'"
# no_cloud.py writes no stub and names no variable of its own: no-cloud.sh does both, so the two cannot drift.
check "its stubs are the ones no-cloud.sh writes, byte for byte" \
  'for t in aws kubectl eksctl helm terraform; do
       diff <(sed "s|${T}/py/|DIR/|" "${T}/py/bin/${t}") <(sed "s|${T}/sh/|DIR/|" "${T}/sh/bin/${t}") >/dev/null || exit 1
   done'
check "it clears every variable no-cloud.sh lists" \
  "py 'import shlex; print(*[v for v in subprocess.run([\"bash\", \"-c\", \". ${HERE}/no-cloud.sh; printf \\\"%s\\\\\\\\n\\\" \\\"\\\${NO_CLOUD_UNSET[@]}\\\"\"],
       capture_output=True, text=True).stdout.split() if v in os.environ] or [\"none\"])' | grep -qx none"

echo "== every offline test that sources or runs fleet.sh guards itself =="
# Found by what the code does: a non-comment line that sources fleet.sh or hands it to bash, through the FLEET
# variable or the path.
DRIVES='^[^#]*(source|bash)\b[^#]*(\bFLEET\b|fleet\.sh)'
drivers=()
for t in "${HERE}"/test_*.sh "${HERE}"/test_*.py; do
    case "$(basename "${t}")" in test_no_cloud_by_hand.sh|test_offline_suite_no_cloud.sh) continue ;; esac
    grep -q '^# SUITE: e2e' "${t}" && continue
    grep -qE "${DRIVES}" "${t}" && drivers+=("$(basename "${t}")")
done
printf '    %d offline tests source or run fleet.sh\n' "${#drivers[@]}"
# The scan is checked against two tests known to run fleet.sh, one of each kind, so a regex that stopped matching
# reads as that and not as an empty, passing audit.
for known in test_presenter_student_retired.sh test_round_names_retired.py; do
    check "the scan finds ${known}" '[[ " ${drivers[*]} " == *" ${known} "* ]]'
done
unguarded=()
for t in "${drivers[@]}"; do
    case "${t}" in
        *.sh) grep -qE '^[^#]*\. "\$\{HERE\}/no-cloud\.sh"; no_cloud_guard ' "${HERE}/${t}" &&
              grep -qE "^[^#]*'no_cloud_clean'" "${HERE}/${t}" || unguarded+=("${t}") ;;
        *.py) grep -qx 'no_cloud.setup()' "${HERE}/${t}" && grep -q '^_calls = no_cloud.calls()' "${HERE}/${t}" ||
              unguarded+=("${t}") ;;
    esac
done
check "each sets the guard up and ends with its check" \
  '[[ "${#unguarded[@]}" -eq 0 ]] || { printf "        %s\n" "${unguarded[@]}"; false; }'

echo "== offline means offline =="
check "nothing got past the guard's stubs to the backstop behind them" \
  '[[ ! -s "${T}/backstop-calls" ]] || { sed "s/^/        /" "${T}/backstop-calls"; false; }'

echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
