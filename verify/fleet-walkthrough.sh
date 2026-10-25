#!/usr/bin/env bash
# ABOUTME: Acceptance walkthrough for the whole fleet: for every provisioned cluster, check the console,
# ABOUTME: the lab page, the terminal, Argo convergence, BurritoBot's pod, and its Datadog org and traces.
#
# Why this exists. Before a delivery the question is not "did provisioning exit 0" but "can a student who
# opens their link do the workshop". Those are different: a cluster can provision cleanly and still hand
# someone a 502 console, an unregistered claim, or an org with no traces. This walks what the student
# touches, per cluster, and prints one line each so a failure is named rather than averaged away.
#
# Usage:
#   verify/fleet-walkthrough.sh                 # every cluster with terraform state
#   verify/fleet-walkthrough.sh --chat 5        # also send a real prompt to 5 clusters (slow, ~20s each)
#   verify/fleet-walkthrough.sh --only michael-admin,attendee-001
#   verify/fleet-walkthrough.sh --json report.json   # also write the report the admin console shows (#268)
#
# The JSON report carries, per cluster, the columns of the admin console's health row: console HTTP code,
# Argo Synced+Healthy count, whether BurritoBot's pod is Ready, and the last trace the instructor Datadog
# org saw from it (verify/last_trace.py). `fleet.sh serve-actions` posts it to the provisioning app.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
FLEET="${REPO}/infra/terraform/fleet/fleet.sh"
PROFILE_DEFAULT="${WIB_DEFAULT_ACCOUNT:-accen-dev}"
CHAT_N=0; ONLY=""; JSON=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --chat) CHAT_N="${2:-5}"; shift 2 ;;
        --only) ONLY="${2:-}"; shift 2 ;;
        --json) JSON="${2:-}"; shift 2 ;;
        *) echo "usage: $0 [--chat N] [--only a,b] [--json report.json]" >&2; exit 2 ;;
    esac
done
# fleet.sh carries the naming rules (public_host_for, is_presenter_name, is_attendee_name); source it rather than restate them.
source "${FLEET}" >/dev/null 2>&1
KDIR="$(mktemp -d -t wibwalk.XXXX)"; trap 'rm -rf "${KDIR}"' EXIT
# Last trace seen, for the whole fleet in one Datadog query. No trace is not a failure (an idle cluster is a
# correct one), so it is a column rather than an issue. A failed query makes the column unknown, and the
# report says why instead of showing every cluster as silent.
TRACES="${KDIR}/traces.tsv"; TRACE_ERR=""
if ! python3 "${HERE}/last_trace.py" --profile "${PROFILE_DEFAULT}" --region "${WIB_REGION}" \
        >"${TRACES}" 2>"${KDIR}/traces.err"; then
    TRACE_ERR="$(tail -1 "${KDIR}/traces.err")"; TRACE_ERR="${TRACE_ERR:-last_trace.py failed}"
    echo "  last trace unknown: ${TRACE_ERR}"
fi
pass=0; fail=0; rows=""
note() { printf '  %-28s %s\n' "$1" "$2"; }
ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); rows="${rows}\n  FAIL ${1}: ${2}"; }

# fleet.sh's STATE_DIR, so WIB_STATE_DIR moves the walkthrough with the verbs that call it.
mapfile -t names < <(find "${STATE_DIR}" -name '*.tfstate' -exec basename {} .tfstate \; 2>/dev/null | sort)
# A cluster named in --only that matches no state file is a failure, not a silent omission. When every
# apply failed before writing state (the 2026-10-24 KubeCon bring-up), the list narrowed to nothing and
# the walk reported "0 healthy, 0 with problems, out of 0" and exited 0 (#570).
missing=()
if [[ -n "${ONLY}" ]]; then
    IFS=',' read -ra wanted <<<"${ONLY}"
    for w in "${wanted[@]}"; do
        [[ -n "${w}" ]] || continue
        printf '%s\n' "${names[@]}" | grep -qE -- "${w}" || missing+=("${w}")
    done
    mapfile -t names < <(printf '%s\n' "${names[@]}" | grep -E "$(echo "${ONLY}" | tr ',' '|')")
fi
echo "walking ${#names[@]} cluster(s)"
for w in "${missing[@]}"; do
    bad "${w}" "no-state"; note "${w}" "FAIL no-state (no ${STATE_DIR}/${w}.tfstate)"
    [[ -z "${JSON}" ]] || printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "${w}" "$(public_host_for "${w}")" \
        fail no-state "" "" "" "" "" >> "${JSON}.tsv"
done
chat_done=0
for name in "${names[@]}"; do
    host="$(public_host_for "${name}")"
    acct="$(read_membership "${name}" 2>/dev/null || true)"; [[ -n "${acct}" ]] || acct="${PROFILE_DEFAULT}"
    issues=""; okc=""; total=""; agent_ready=""
    # 1. the console and the lab page a student opens
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://${host}/" || echo 000)"
    [[ "${code}" == "200" ]] || issues="${issues} console=${code}"
    lab="$(curl -s --max-time 20 "https://${host}/lab.html" || true)"
    grep -q "Challenge 1" <<<"${lab}" || issues="${issues} lab-content"
    # 2. the terminal answers and demands its password
    tcode="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://${host}/terminal/" || echo 000)"
    [[ "${tcode}" == "401" || "${tcode}" == "200" ]] || issues="${issues} terminal=${tcode}"
    # 3. the platform converged
    kc="${KDIR}/${name}.kubeconfig"
    if AWS_PROFILE="${acct}" aws eks update-kubeconfig --kubeconfig "${kc}" --name "${name}" --region "${WIB_REGION}" >/dev/null 2>&1; then
        ctx="$(KUBECONFIG="${kc}" kubectl config current-context 2>/dev/null)"
        read -r okc total < <(AWS_PROFILE="${acct}" KUBECONFIG="${kc}" kubectl --context "${ctx}" -n argocd get applications --no-headers 2>/dev/null \
            | awk '{t++; if($2=="Synced"&&$3=="Healthy")o++} END{print o+0, t+0}')
        [[ "${total}" -gt 0 ]] || issues="${issues} no-argo"
        [[ "${okc}" == "${total}" ]] || issues="${issues} argo=${okc}/${total}"
        # 3b. nothing has pre-solved a challenge for the student. C6's success signal is a Deployment
        # named maintenance-shell, so a rehearsal that left one behind hands the student a challenge that
        # is already done and a pod nobody can explain in Step 0 (#285). One kubectl, and it catches the
        # whole class of "a probe run polluted this cluster".
        if AWS_PROFILE="${acct}" KUBECONFIG="${kc}" kubectl --context "${ctx}" -n agent get deploy \
                maintenance-shell >/dev/null 2>&1; then
            issues="${issues} c6-artifact-present"
        fi
        # 3c. BurritoBot answers: its pod exists and is Ready. Argo can call the agent app Healthy while the
        # pod is between restarts, and otherwise the student's first prompt is what finds out (#268).
        agent_ready="$(AWS_PROFILE="${acct}" KUBECONFIG="${kc}" kubectl --context "${ctx}" -n agent get pods \
            -l app.kubernetes.io/name=workshop-agent \
            -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2>/dev/null \
            | grep -c '^True$')" || true
        [[ "${agent_ready:-0}" -ge 1 ]] && agent_ready=true || { agent_ready=false; issues="${issues} agent-not-ready"; }
        # 4. the Datadog org, identity and dual shipping this cluster was given
        if ! AWS_PROFILE="${acct}" KUBECONFIG="${kc}" bash "${HERE}/datadog-orgs.sh" "${ctx}" "${acct}" >/dev/null 2>&1; then
            issues="${issues} datadog"
        fi
    else
        issues="${issues} unreachable"
    fi
    # 5. a real prompt, on a sample
    if [[ "${chat_done}" -lt "${CHAT_N}" ]]; then
        reply="$(curl -s --max-time 150 -X POST "https://${host}/chat" -H 'Content-Type: application/json' -H "Origin: https://${host}" \
            --data '{"prompt":"[[wib-probe]] name one salsa"}' 2>/dev/null | python3 -c 'import sys,json
try: print((json.load(sys.stdin).get("reply") or "")[:40])
except Exception: print("")' 2>/dev/null)"
        [[ -n "${reply}" ]] || issues="${issues} chat"
        chat_done=$((chat_done+1))
    fi
    if [[ -z "${issues}" ]]; then ok; note "${name}" "OK  ${host}"; else bad "${name}" "${issues# }"; note "${name}" "FAIL${issues}"; fi
    last_trace="$(awk -F'\t' -v n="${name}" '$1 == n { print $2 }' "${TRACES}")"
    [[ -z "${JSON}" ]] || printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "${name}" "${host}" \
        "$([[ -z "${issues}" ]] && echo ok || echo fail)" "${issues# }" "${code}" "${okc}" "${total}" \
        "${agent_ready}" "${last_trace}" >> "${JSON}.tsv"
done
if [[ -n "${JSON}" ]]; then
    TRACE_ERR="${TRACE_ERR}" python3 - "${JSON}" "${JSON}.tsv" <<'PY2'
import json, os, sys, datetime, pathlib
out, tsv = sys.argv[1], pathlib.Path(sys.argv[2])
num = lambda v: int(v) if v.isdigit() else None
rows = []
for line in (tsv.read_text().splitlines() if tsv.exists() else []):
    name, host, status, issues, console, argo_ok, argo_total, agent, trace = (line.split("\t") + [""] * 9)[:9]
    rows.append({"cluster": name, "host": host, "status": status,
                 "issues": [i for i in issues.split() if i],
                 "console_http": num(console),
                 "argo": {"synced_healthy": num(argo_ok), "total": num(argo_total)},
                 "agent_ready": {"true": True, "false": False}.get(agent),
                 "last_trace": trace or None})
json.dump({"generated": datetime.datetime.now(datetime.UTC).isoformat(),
           "clusters": len(rows), "healthy": sum(r["status"] == "ok" for r in rows),
           "failed": sum(r["status"] != "ok" for r in rows),
           "last_trace_error": os.environ.get("TRACE_ERR") or None, "results": rows},
          open(out, "w"), indent=2)
PY2
    rm -f "${JSON}.tsv"; echo "  report: ${JSON}"
fi
echo
echo "  ${pass} healthy, ${fail} with problems, out of $(( ${#names[@]} + ${#missing[@]} ))"
[[ "${fail}" -eq 0 ]] || { printf '%b\n' "${rows}"; exit 1; }
