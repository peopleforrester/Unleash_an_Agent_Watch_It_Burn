#!/usr/bin/env bash
# ABOUTME: Behavioural tests for the converge repairs (#254): Datadog key resolution per cluster class,
# ABOUTME: identity and key-drift repair, stuck sync and pod handling, empty-state pruning, verifier ledger.
#
# Usage: verify/test_fleet_converge_repairs.sh      (offline; aws, kubectl and the scripts are shims)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
T="$(mktemp -d -p "${HERE}/.." .fleet-repairs-test.XXXX)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }
# Offline means offline (#859): aws, kubectl, eksctl, terraform and helm are stubs that log the call and fail,
# even when the test is run by hand (verify/no-cloud.sh). The last check reads the log.
# shellcheck source=SCRIPTDIR/no-cloud.sh
. "${HERE}/no-cloud.sh"; no_cloud_guard "${T}/no-cloud"
# A test-owned presenter terminal login (#910): `instructors up` refuses to build without one, and the guard above
# shields the real one in mrf-secrets. A placeholder, never a real login.
export WIB_TERMINAL_USER=placeholder-presenter WIB_TERMINAL_PASSWORD=placeholder-presenter-pw

# ---- canned Datadog secrets, as Secrets Manager would answer ----
ADMIN='{"api-key":"ADMIN_API","app-key":"ADMIN_APP","org":"devops-days-portland-090826-001","role":"admin-instructor"}'
ADMATT='{"api-key":"PRES_API","app-key":"PRES_APP","org":"devops-days-portland-090826-002","role":"admin-attendee"}'
POOL='[{"api-key":"ADMIN_API","app-key":"ADMIN_APP","role":"admin-instructor"},{"api-key":"PRES_API","app-key":"PRES_APP","role":"admin-attendee"},{"api-key":"ROW1_API","app-key":"ROW1_APP","org":"devops-days-portland-090826-003"},{"api-key":"ROW2_API","app-key":"ROW2_APP","org":"devops-days-portland-090826-004"}]'
cat >"${SHIM}/aws" <<S
#!/usr/bin/env bash
echo "aws \$*" >>"\${CALLS}"
case "\$*" in
  *"--secret-id watch-it-burn/datadog-pool "*) [[ -f "\${T}/one_org" ]] && { printf '%s' '[{"api-key":"ADMIN_API","app-key":"ADMIN_APP"}]'; exit 0; }; printf '%s' '${POOL}' ;;
  *"--secret-id watch-it-burn/datadog-pool-2 "*) printf '%s' '[]' ;;
  *"--secret-id watch-it-burn/datadog-admin-attendee "*) printf '%s' '${ADMATT}' ;;
  *"--secret-id watch-it-burn/datadog "*) [[ -f "\${T}/no_admin_secret" ]] && exit 254; printf '%s' '${ADMIN}' ;;
  *"eks update-kubeconfig"*) exit 0 ;;
esac
exit 0
S
# kubectl answers from files the test controls; every mutation is recorded.
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $*" >>"${CALLS}"
case "$*" in
  *"config current-context"*) echo "ctx-test" ;;
  *"get applications.argoproj.io -n argocd -o json"*) cat "${T}/apps.json" 2>/dev/null || echo '{"items":[]}' ;;
  *"get pods -A -o json"*) cat "${T}/pods.json" 2>/dev/null || echo '{"items":[]}' ;;
  *"-n agent get configmap cluster-identity"*) cat "${T}/public_host" 2>/dev/null ;;
  *"get configmap cluster-identity"*) cat "${T}/identity" 2>/dev/null ;;
  *"-n agent get agent workshop-agent"*) cat "${T}/agent_tools" 2>/dev/null ;;
  *"-n agent get deployment guard-proxy -o json"*) cat "${T}/gp.json" 2>/dev/null ;;
  *"-n agent get deployment agentgateway -o json"*) cat "${T}/gw.json" 2>/dev/null ;;
  *"-n argocd get application ai-layer -o jsonpath={.status.sync.revision}"*) cat "${T}/ai_rev" 2>/dev/null ;;
  "kustomize "*) [[ -f "${T}/render_fails" ]] && exit 1; cat "${T}/render.yaml" 2>/dev/null ;;
  *"-n agent get deployments -o json"*) cat "${T}/deps.json" 2>/dev/null || echo '{"items":[]}' ;;
  *"-n agent get configmaps,secrets -o name"*) cat "${T}/objs" 2>/dev/null ;;
  *"get secret datadog-secret -o jsonpath={.data.api-key}"*) printf '%s' "$(cat "${T}/live_key" 2>/dev/null)" | base64 ;;
  *"get secret datadog-admin-secret"*) [[ -f "${T}/admin_present" ]] && exit 0; exit 1 ;;
  *"create namespace"*|*"create secret generic"*) echo "kind: Placeholder" ;;
esac
exit 0
S
# git answers ai_layer_rollout's two questions from files the test controls; anything else is the real git.
REAL_GIT="$(command -v git)"
cat >"${SHIM}/git" <<S
#!/usr/bin/env bash
case "\$*" in
  *" rev-parse HEAD") cat "\${T}/head" 2>/dev/null && exit 0 ;;
  *" diff --quiet HEAD -- gitops/ai-layer") [[ -f "\${T}/dirty" ]] && exit 1; exit 0 ;;
esac
exec "${REAL_GIT}" "\$@"
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
src() { # $1: snippet run after sourcing; the three external actions are replaced by recorders
  ( cd "$(dirname "${FLEET}")" && WIB_STATE_DIR="${T}/states" \
      bash -c "source '${FLEET}' >/dev/null 2>&1
        mkdir -p \"\${LOG_DIR}\"  # record_fail writes here; the cmd_* callers create it, a fresh clone has none
        run_identity_script() { echo \"identity-script CLUSTER_NAME=\${CLUSTER_NAME} admin=\${WITB_DD_ADMIN_API_KEY}\" >>'${CALLS}'; }
        reload_datadog_consumers() { echo \"reload \$1 \$2\" >>'${CALLS}'; }
        run_datadog_orgs_verify() { echo \"verify \$1 \$2\" >>'${CALLS}'; return \${VERIFY_RC:-0}; }
        $1" 2>>"${T}/stderr" )
}

echo "== datadog_keys_for: one truth for every cluster class =="
check "attendee-002 gets pool row 2 plus the instructor org second" \
  '[[ "$(src "datadog_keys_for watch-it-burn-attendee-002")" == "ROW2_API ROW2_APP ADMIN_API ADMIN_APP" ]]'
check "an admin cluster gets the instructor org and nothing second" \
  '[[ "$(src "datadog_keys_for watch-it-burn-private")" == "ADMIN_API ADMIN_APP  " ]]'
check "nothing reads the retired admin-attendee org (#295)" \
  '( : >"${CALLS}"; src "datadog_keys_for watch-it-burn-private" >/dev/null; ! grep -q datadog-admin-attendee "${CALLS}" )'
check "an instructor cluster gets the instructor org and nothing second" \
  '[[ "$(src "datadog_keys_for watch-it-burn-r2-1")" == "ADMIN_API ADMIN_APP  " ]]'
check "a slot beyond the pool resolves nothing and returns 1" \
  '! src "datadog_keys_for watch-it-burn-attendee-099" >/dev/null'

echo "== repair_datadog =="
: >"${CALLS}"; printf 'watch-it-burn-attendee-002' >"${T}/identity"; printf 'ROW2_API' >"${T}/live_key"; touch "${T}/admin_present"
printf '%s' "$(src 'public_host_for watch-it-burn-attendee-002')" >"${T}/public_host"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "a cluster that matches the repo is left alone (no identity script, no reload)" '! grep -q "identity-script\|reload" "${CALLS}"'
: >"${CALLS}"; printf 'stale.agenticburn.com' >"${T}/public_host"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "a wrong public-host is repaired through the identity script" 'grep -q "identity-script" "${CALLS}"'
printf '%s' "$(src 'public_host_for watch-it-burn-attendee-002')" >"${T}/public_host"
: >"${CALLS}"; rm -f "${T}/identity"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "missing identity: identity script runs with the cluster name and admin key, consumers reloaded" \
  'grep -q "identity-script CLUSTER_NAME=watch-it-burn-attendee-002 admin=ADMIN_API" "${CALLS}" && grep -q "^reload ctx-test acct" "${CALLS}"'
: >"${CALLS}"; printf 'watch-it-burn-attendee-002' >"${T}/identity"; printf 'STALE_JUNE_KEY' >"${T}/live_key"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "key drift: datadog-secret rewritten in all three namespaces and consumers reloaded" \
  '[[ "$(grep -c "create secret generic datadog-secret --from-literal=api-key=ROW2_API" "${CALLS}")" -eq 3 ]] && grep -q "^reload" "${CALLS}"'
: >"${CALLS}"; printf 'ROW2_API' >"${T}/live_key"; rm -f "${T}/admin_present"
src 'repair_datadog watch-it-burn-attendee-002 /dev/null acct'
check "attendee without the admin secret: repaired (dual shipping restored)" 'grep -q "identity-script" "${CALLS}"'
: >"${CALLS}"; printf 'watch-it-burn-r2-1' >"${T}/identity"; printf 'ADMIN_API' >"${T}/live_key"; touch "${T}/admin_present"
src 'repair_datadog watch-it-burn-r2-1 /dev/null acct'
check "instructor WITH an admin secret: repaired (the stale secret goes)" 'grep -q "identity-script CLUSTER_NAME=watch-it-burn-r2-1 admin=$" "${CALLS}"'
rm -f "${T}/admin_present"
# One org (#587): the pool row is the instructor key itself (question 926's one-row pool), so the identity script
# writes no admin secret, and a converge that wanted one would repair, and restart the consumers, on every pass.
touch "${T}/one_org"; : >"${CALLS}"; printf 'watch-it-burn-attendee-001' >"${T}/identity"; printf 'ADMIN_API' >"${T}/live_key"
printf '%s' "$(src 'public_host_for watch-it-burn-attendee-001')" >"${T}/public_host"
src 'repair_datadog watch-it-burn-attendee-001 /dev/null acct'
check "one org: an attendee on the instructor key without an admin secret is left alone" '! grep -q "identity-script\|reload" "${CALLS}"'
: >"${CALLS}"; touch "${T}/admin_present"
src 'repair_datadog watch-it-burn-attendee-001 /dev/null acct'
check "one org: an admin secret there is repaired away (it would count everything twice)" 'grep -q "identity-script CLUSTER_NAME=watch-it-burn-attendee-001" "${CALLS}"'
rm -f "${T}/one_org" "${T}/admin_present"

echo "== no shared-org secret: roster clusters carry a logged gap, attendees are refused (#510) =="
touch "${T}/no_admin_secret"
check "a roster cluster resolves no keys and returns 1" '! src "datadog_keys_for watch-it-burn-private" >/dev/null'
: >"${CALLS}"; rm -f "${T}/live_key" "${T}/admin_present"; : >"${T}/stderr"
src 'repair_datadog watch-it-burn-private /dev/null acct; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"
check "repair: a roster cluster without keys is a logged gap, not a failure" \
  '[[ ! -s "${T}/out" ]] && grep -q "watch-it-burn-private: Datadog gap logged" "${T}/stderr" && ! grep -q "identity-script\|reload" "${CALLS}"'
check "repair: an attendee whose keys do not resolve is still recorded as datadog-keys-unresolved" \
  '! src "datadog_keys_for watch-it-burn-attendee-099" >/dev/null && src "repair_datadog watch-it-burn-attendee-099 /dev/null acct; cat \"\${FAIL_FILE}\"; rm -f \"\${FAIL_FILE}\"" | grep -qx "watch-it-burn-attendee-099:datadog-keys-unresolved"'
# bootstrap_one with every external step replaced by a recorder; the key decision stays the real one.
boot() { src "provider_write_kubeconfig() { :; }; bootstrap_student_aws() { echo \"student-aws \$1\" >>'${CALLS}'; }
    bootstrap_terminal_auth() { echo \"terminal-auth \$1\" >>'${CALLS}'; }
    arm_infra_guardrails() { echo \"arm \$1\" >>'${CALLS}'; }
    pin_bedrock_profiles() { echo \"pin-bedrock \$1\" >>'${CALLS}'; }  # its own test: test_pin_bedrock_profiles.sh
    run_idp_script() { echo \"idp \${CLUSTER_NAME} \$1 api=\${WITB_DD_API_KEY} app=\${WITB_DD_APP_KEY}\" >>'${CALLS}'; }
    load_roster; $1
    cat \"\${FAIL_FILE}\" 2>/dev/null; rm -f \"\${FAIL_FILE}\""; }
# The Night Before build: every roster cluster 'instructors up all' selects, with the profile it selects.
night="$(src '_provision_spec_fleet() { :; }; require_tools() { :; }; cmd_guardrails_link() { :; }; load_roster; cmd_instructors up all >/dev/null 2>&1
    for k in "${!PROVISION_SPEC[@]}"; do echo "${k} $(cut -d"|" -f2 <<<"${PROVISION_SPEC[$k]}")"; done | sort')"
# KubeCon (event.sh's WIB_ROSTER_PROFILES=kubecon, #774): the pair whose four Kubernetes guardrails start off.
check "instructors up all selects the two roster clusters, on the KubeCon profiles" \
  '[[ "$(wc -l <<<"${night}")" -eq 2 ]] && grep -q "^watch-it-burn-community kubecon-community$" <<<"${night}" && grep -q "^watch-it-burn-private kubecon-private$" <<<"${night}"'
: >"${CALLS}"; : >"${T}/stderr"
boot "$(while read -r n p; do printf 'bootstrap_one %s %s; ' "$n" "$p"; done <<<"${night}")" >"${T}/out"
check "bootstrap: every roster cluster runs deploy-full-idp with empty keys and nothing is recorded failed" \
  '[[ ! -s "${T}/out" ]] && [[ "$(grep -c "^idp watch-it-burn-[a-z-]* [a-z-]* api= app=$" "${CALLS}")" -eq 2 ]]'
# Nothing is armed at bootstrap on the KubeCon pair: the four Kubernetes guardrails wait for guardrails-on (#774).
check "bootstrap: each one goes on to its terminal login, and neither KubeCon cluster is armed at bootstrap" \
  '[[ "$(grep -c "^terminal-auth " "${CALLS}")" -eq 2 ]] && [[ "$(grep -c "^arm " "${CALLS}")" -eq 0 ]]'
check "bootstrap: each one points its Bedrock ModelConfigs at its tagged profiles (#513)" \
  '[[ "$(grep -c "^pin-bedrock " "${CALLS}")" -eq 2 ]]'
check "bootstrap: the gap is a WARN naming the cluster" \
  '[[ "$(grep -c "WARN: watch-it-burn-[a-z-]*: no Datadog keys" "${T}/stderr")" -eq 2 ]] && ! grep -q "BOOTSTRAP FAILED" "${T}/stderr"'
: >"${CALLS}"; : >"${T}/stderr"
boot "bootstrap_one watch-it-burn-private admin" >"${T}/out"
check "bootstrap: the workshop's admin profile is still armed at bootstrap" \
  'grep -q "^arm watch-it-burn-private$" "${CALLS}" && [[ "$(grep -c "^arm " "${CALLS}")" -eq 1 ]]'
: >"${CALLS}"; : >"${T}/stderr"
boot "bootstrap_one watch-it-burn-attendee-099 attendee" >"${T}/out"
check "bootstrap: an attendee whose org does not resolve is refused, never given the shared org" \
  'grep -qx "watch-it-burn-attendee-099" "${T}/out" && ! grep -q "^idp " "${CALLS}" && grep -q "refusing to fall back" "${T}/stderr"'
# Loading the key later is all it takes: the next converge sees own-key-drift and turns Datadog on.
rm -f "${T}/no_admin_secret"; : >"${CALLS}"; printf 'watch-it-burn-private' >"${T}/identity"
printf '%s' "$(src 'public_host_for watch-it-burn-private')" >"${T}/public_host"
src 'repair_datadog watch-it-burn-private /dev/null acct'
check "once the key exists, repair writes datadog-secret in all three namespaces and reloads the consumers" \
  '[[ "$(grep -c "create secret generic datadog-secret --from-literal=api-key=ADMIN_API" "${CALLS}")" -eq 3 ]] && grep -q "^reload ctx-test acct" "${CALLS}"'
: >"${T}/stderr"

echo "== converge alone turns Datadog on for clusters whose keys arrived after bring-up (#635) =="
# The 2026-10-28 KubeCon run: the keys went into watch-it-burn/datadog after bring-up, `./fleet.sh converge
# watch-it-burn-community watch-it-burn-michael-admin` said CONVERGED 2/2, and no datadog-secret was written.
# repair_agent_tools read a path relative to the working directory, which from the fleet directory does not
# exist, and errexit ended each converge_one job before repair_datadog. This runs the real cmd_converge from
# that directory through every real repair; only the cluster edges and pin_bedrock_profiles are stubbed.
python3 -c 'import json; print(json.dumps({"items":[{"metadata":{"name":f"app-{i}"},"status":{"sync":{"status":"Synced"},"health":{"status":"Healthy"},"operationState":{"phase":"Succeeded"}}} for i in range(12)]}))' >"${T}/apps.json"
python3 - "${HERE}/../gitops/workshop-agent/agent.yaml" >"${T}/agent_tools" <<'PY'
import json, sys, yaml
for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")):
    if d and d.get("kind") == "Agent":
        for s in d["spec"]["declarative"]["tools"]:
            if (s.get("mcpServer") or {}).get("name") == "workshop-mcp":
                print(json.dumps(s["mcpServer"]["toolNames"], separators=(",", ":")), end="")  # as kubectl prints it
PY
rm -f "${T}/live_key" "${T}/admin_present"; : >"${CALLS}"; : >"${T}/stderr"; mkdir -p "${T}/logs"
WIB_LOG_DIR="${T}/logs" WIB_CONVERGE_ROUNDS=1 src 'provider_write_kubeconfig() { :; }; require_tools() { :; }
    converge_endpoint() { echo console.example; }
    pin_bedrock_profiles() { echo "pin-bedrock $1" >>"${CALLS}"; }  # its own test: test_pin_bedrock_profiles.sh
    cmd_converge watch-it-burn-community watch-it-burn-private'; rc=$?
check "converge reaches repair_datadog on both clusters and runs the identity script for each" \
  'grep -q "^identity-script CLUSTER_NAME=watch-it-burn-community " "${CALLS}" && grep -q "^identity-script CLUSTER_NAME=watch-it-burn-private " "${CALLS}"'
check "it writes datadog-secret in all three namespaces of both clusters and reloads both" \
  '[[ "$(grep -c "create secret generic datadog-secret --from-literal=api-key=ADMIN_API" "${CALLS}")" -eq 6 && "$(grep -c "^reload ctx-test " "${CALLS}")" -eq 2 ]]'
check "it logs the own-key-drift it repaired, for each cluster" \
  '[[ "$(grep -c "watch-it-burn-[a-z]*: repairing datadog (.*own-key-drift" "${T}/stderr")" -eq 2 ]]'
check "the verifier after it runs too, and the agent tools repair found nothing to do" \
  '[[ "$(grep -c "^verify ctx-test " "${CALLS}")" -eq 2 ]] && ! grep -q "delete agent workshop-agent" "${CALLS}"'
check "and only then does it say CONVERGED 2/2" \
  '[[ "${rc}" -eq 0 ]] && grep -q "CONVERGED: 2/2" "${T}/stderr" && ! grep -q "stopped with exit" "${T}/stderr"'
rm -f "${T}/agent_tools"; : >"${T}/stderr"

echo "== repair_agent_tools: the #679 state is recreated from git =="
# Both KubeCon clusters on 2026-10-29: git's workshop-mcp had twelve tools, the live Agent the eleven from before
# read_support_ticket (#640), and Argo CD cannot write one element of the tools array on a toolnames profile
# (verify/test_agent_tools_sync.py ports why). Deleting the Agent is the repair: Argo recreates it from git.
printf '%s' '["lookup_customer_records","check_inventory","reorder_supply","get_order_history","get_marketing_intel","search_web","post_marketing","get_vault_entry","list_services","deploy_app","run_shell"]' >"${T}/agent_tools"
: >"${CALLS}"; : >"${T}/stderr"; src 'repair_agent_tools watch-it-burn-community /dev/null'
check "the live eleven against git's twelve: the stale list is logged and the Agent CR is deleted for Argo to recreate" \
  'grep -qx "kubectl -n agent delete agent workshop-agent" "${CALLS}" && grep -q "watch-it-burn-community: agent tool list is stale" "${T}/stderr"'
python3 - "${HERE}/../gitops/workshop-agent/agent.yaml" >"${T}/agent_tools" <<'PY'
import json, sys, yaml
for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")):
    if d and d.get("kind") == "Agent":
        for s in d["spec"]["declarative"]["tools"]:
            if (s.get("mcpServer") or {}).get("name") == "workshop-mcp":
                print(json.dumps(list(reversed(s["mcpServer"]["toolNames"])), separators=(",", ":")), end="")
PY
: >"${CALLS}"; src 'repair_agent_tools watch-it-burn-community /dev/null'
check "git's twelve in another order: nothing is deleted (the lists are compared as sets)" \
  '! grep -q "delete agent" "${CALLS}" && grep -q "read_support_ticket" "${T}/agent_tools"'
rm -f "${T}/agent_tools"; : >"${CALLS}"; src 'repair_agent_tools watch-it-burn-community /dev/null'
check "no live Agent (Argo still recreating it): nothing is deleted" '! grep -q "delete agent" "${CALLS}"'
: >"${T}/stderr"

echo "== repair_env_order: a list Argo CD syncs in its live order is put back in git's (#679) =="
# Both KubeCon clusters on 2026-10-29: CONSOLE_ORIGIN was added to guard-proxy live with `kubectl set env`, which
# appends, so the live env ended ... OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT, CONSOLE_ORIGIN while git puts
# it before OTEL_SERVICE_NAME. ai-layer syncs the list in its live order (RespectIgnoreDifferences), so it never read
# Synced again. The fixture is git's Deployment in that order, with a live guard toggle (MODEL_TIER=sonnet) on it.
deploy_json() { # $1 file, $2 Deployment, $3 container, $4 "append NAME" | "same"; MODEL_TIER, if any, is set to sonnet
  python3 - "${HERE}/../$1" "$2" "$3" "$4" <<'PY'
import json, sys, yaml
src, dep, ctr, how = sys.argv[1:5]
d = next(d for d in yaml.safe_load_all(open(src, encoding="utf-8"))
         if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == dep)
c = next(c for c in d["spec"]["template"]["spec"]["containers"] if c["name"] == ctr)
for e in c.get("env") or []:
    if e["name"] == "MODEL_TIER":
        e["value"] = "sonnet"
if how.startswith("append "):
    n = how.split()[1]
    c["env"] = [e for e in c["env"] if e["name"] != n] + [e for e in c["env"] if e["name"] == n]
print(json.dumps(d))
PY
}
deploy_json gitops/ai-layer/resources.yaml guard-proxy proxy "append CONSOLE_ORIGIN" >"${T}/gp.json"
deploy_json gitops/ai-layer/agentgateway.yaml agentgateway agentgateway same >"${T}/gw.json"
: >"${CALLS}"; : >"${T}/stderr"; src 'repair_env_order watch-it-burn-community /dev/null'; rc=$?
check "the 2026-10-29 guard-proxy: its env is patched, as the Argo controller, and the repair returns 0" \
  '[[ "${rc}" -eq 0 ]] && grep -q "^kubectl -n agent patch deployment guard-proxy --type json -p .* --as=system:serviceaccount:argocd:argocd-application-controller$" "${CALLS}"'
python3 - "${CALLS}" "${HERE}/../gitops/ai-layer/resources.yaml" >"${T}/patched" <<'PY'
import json, re, sys, yaml
line = next(l for l in open(sys.argv[1]) if l.startswith("kubectl -n agent patch deployment guard-proxy"))
patch = json.loads(re.search(r" -p (\[.*\]) --as=", line).group(1))
git = next(d for d in yaml.safe_load_all(open(sys.argv[2], encoding="utf-8"))
           if d and d.get("kind") == "Deployment" and d["metadata"]["name"] == "guard-proxy")
want = [e["name"] for e in git["spec"]["template"]["spec"]["containers"][0]["env"]]
env = patch[1]["value"]
print("order" if [e["name"] for e in env] == want else "disorder")
print("tier=" + next(e["value"] for e in env if e["name"] == "MODEL_TIER"))
print("test" if patch[0] == {"op": "test", "path": "/spec/template/spec/containers/0/name", "value": "proxy"} else "untested")
PY
check "the patch writes git's order, CONSOLE_ORIGIN back before OTEL_SERVICE_NAME" 'grep -qx order "${T}/patched"'
check "with every live value kept: the live MODEL_TIER=sonnet toggle stays" 'grep -qx tier=sonnet "${T}/patched"'
check "and it first tests that container 0 is still proxy, so a moved container is not rewritten" 'grep -qx test "${T}/patched"'
check "agentgateway, already in git's order, is not patched" '! grep -q "patch deployment agentgateway" "${CALLS}"'
check "the reorder is logged, naming the Deployment and #679" \
  'grep -q "watch-it-burn-community: guard-proxy.s proxy env is out of git.s order, which Argo CD cannot correct (#679)" "${T}/stderr"'
deploy_json gitops/ai-layer/resources.yaml guard-proxy proxy same >"${T}/gp.json"
: >"${CALLS}"; src 'repair_env_order watch-it-burn-community /dev/null'
check "guard-proxy in git's order (a toggled value is not an order): nothing is patched" '! grep -q "patch deployment" "${CALLS}"'
rm -f "${T}/gp.json" "${T}/gw.json"; : >"${CALLS}"; src 'repair_env_order watch-it-burn-community /dev/null'; rc=$?
check "neither Deployment there yet: nothing is patched, and that is not a failure" '[[ "${rc}" -eq 0 ]] && ! grep -q "patch deployment" "${CALLS}"'
: >"${T}/stderr"

echo "== ai_layer_rollout: delivery is read from the hashed names, not the sync phase (#679) =="
# After ed8dbf8 every ai-layer sync on both KubeCon clusters said Succeeded and applied nothing new: the pods kept
# the old hashed ConfigMaps. The commit's render names what must be live and mounted; the fixture is a small one.
cat >"${T}/render.yaml" <<'Y'
apiVersion: v1
kind: ConfigMap
metadata: {name: guard-proxy-src-new1}
---
apiVersion: v1
kind: Secret
metadata: {name: llm-guard-auth-sec1}
---
apiVersion: v1
kind: Service
metadata: {name: guard-proxy}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: guard-proxy}
spec:
  template:
    spec:
      containers:
        - name: proxy
          env: [{name: LLM_GUARD_TOKEN, valueFrom: {secretKeyRef: {name: llm-guard-auth-sec1, key: token}}}]
      volumes: [{name: src, configMap: {name: guard-proxy-src-new1}}]
Y
live_deps() { # $1: the guard-proxy-src name the live Deployment mounts
  printf '{"items":[{"metadata":{"name":"guard-proxy"},"spec":{"template":{"spec":{"containers":[{"name":"proxy","env":[{"name":"LLM_GUARD_TOKEN","valueFrom":{"secretKeyRef":{"name":"llm-guard-auth-sec1","key":"token"}}}]}],"volumes":[{"name":"src","configMap":{"name":"%s"}}]}}}},{"metadata":{"name":"workshop-agent"},"spec":{"template":{"spec":{"containers":[{"name":"kagent"}]}}}}]}' "$1" >"${T}/deps.json"; }
printf 'aaaa000000000000000000000000000000000000' >"${T}/head"; printf 'aaaa000000000000000000000000000000000000' >"${T}/ai_rev"
printf 'configmap/guard-proxy-src-new1\nsecret/llm-guard-auth-sec1\nconfigmap/kube-root-ca.crt\n' >"${T}/objs"; live_deps guard-proxy-src-new1
: >"${T}/stderr"; src 'ai_layer_rollout c /dev/null'; rc=$?
check "the commit's hashed names live and mounted: rolled out, exit 0" \
  '[[ "${rc}" -eq 0 ]] && grep -q "c: ai-layer aaaa000 is rolled out" "${T}/stderr"'
printf 'configmap/guard-proxy-src-old0\nsecret/llm-guard-auth-sec1\n' >"${T}/objs"; live_deps guard-proxy-src-old0
: >"${T}/stderr"; src 'ai_layer_rollout c /dev/null'; rc=$?
check "the 2026-10-29 state, Succeeded and nothing applied: exit 1, saying the sync phase is not delivery" \
  '[[ "${rc}" -eq 1 ]] && grep -q "c: ai-layer says it synced aaaa000, and the cluster does not run it" "${T}/stderr"'
check "it names the generated ConfigMap the commit needs" 'grep -q "configmap/guard-proxy-src-new1 is missing" "${T}/stderr"'
check "and the Deployment still mounting the old one" \
  'grep -q "deployment/guard-proxy mounts \[.configmap/guard-proxy-src-old0.\] where the commit mounts \[.configmap/guard-proxy-src-new1.\]" "${T}/stderr"'
: >"${CALLS}"; src 'verify_one c /dev/null acct; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "verify_one records it as <name>:ai-layer-rollout" 'grep -qx "c:ai-layer-rollout" "${T}/out"'
printf 'bbbb000000000000000000000000000000000000' >"${T}/ai_rev"; : >"${T}/stderr"; src 'ai_layer_rollout c /dev/null'; rc=$?
check "a cluster that compares another commit is reported, not judged (exit 0)" \
  '[[ "${rc}" -eq 0 ]] && grep -q "c: ai-layer compares bbbb000 and this checkout is aaaa000; its rollout is not judged" "${T}/stderr"'
printf 'aaaa000000000000000000000000000000000000' >"${T}/ai_rev"; touch "${T}/dirty"; : >"${T}/stderr"
src 'ai_layer_rollout c /dev/null'; rc=$?
check "uncommitted changes in gitops/ai-layer: the local render is not the commit, so not judged (exit 0)" \
  '[[ "${rc}" -eq 0 ]] && grep -q "gitops/ai-layer has uncommitted changes here" "${T}/stderr"'
rm -f "${T}/dirty"; touch "${T}/render_fails"; : >"${T}/stderr"; src 'ai_layer_rollout c /dev/null'; rc=$?
check "a render that fails is a failure, not a pass" '[[ "${rc}" -eq 1 ]] && grep -q "could not render gitops/ai-layer" "${T}/stderr"'
rm -f "${T}/render_fails" "${T}/render.yaml" "${T}/deps.json" "${T}/objs" "${T}/ai_rev" "${T}/head"; : >"${T}/stderr"

echo "== repair_step: a repair that fails is logged and recorded, and the next one still runs (#635) =="
: >"${CALLS}"
WIB_LOG_DIR="${T}/logs" src 'boom() { false; echo "boom-went-on $1" >>"${CALLS}"; }; after() { echo "after-ran $1" >>"${CALLS}"; }
    repair_step boom c; repair_step after c; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "the failing repair stops at its first unguarded error" '! grep -q "boom-went-on" "${CALLS}"'
check "it is recorded as <name>:<repair> and logged" \
  'grep -qx "c:boom" "${T}/out" && grep -q "c: boom stopped with exit 1" "${T}/stderr"'
check "the repair after it still runs" 'grep -qx "after-ran c" "${CALLS}"'
: >"${T}/stderr"

echo "== repair_stuck_syncs =="
old="$(date -u -d '40 minutes ago' +%FT%TZ)"; new="$(date -u -d '2 minutes ago' +%FT%TZ)"
printf '{"items":[{"metadata":{"name":"prometheus"},"status":{"operationState":{"phase":"Running","startedAt":"%s"}}},{"metadata":{"name":"kagent"},"status":{"operationState":{"phase":"Running","startedAt":"%s"}}},{"metadata":{"name":"ai-layer"},"status":{"operationState":{"phase":"Succeeded","startedAt":"%s"}}}]}' "$old" "$new" "$old" >"${T}/apps.json"
: >"${CALLS}"; src 'repair_stuck_syncs c /dev/null'
check "only the operation Running past the threshold is terminated" \
  'grep -q "patch application prometheus --type json" "${CALLS}" && ! grep -q "patch application kagent\|patch application ai-layer" "${CALLS}"'

echo "== repair_failed_syncs =="
printf '{"items":[{"metadata":{"name":"otel-operator"},"status":{"sync":{"status":"OutOfSync"},"operationState":{"phase":"Failed"}}},{"metadata":{"name":"ai-layer-otel"},"status":{"sync":{"status":"OutOfSync"},"operationState":{"phase":"Error"}}},{"metadata":{"name":"busy"},"operation":{"sync":{}},"status":{"sync":{"status":"OutOfSync"},"operationState":{"phase":"Failed"}}},{"metadata":{"name":"fine"},"status":{"sync":{"status":"Synced"},"operationState":{"phase":"Failed"}}}]}' >"${T}/apps.json"
: >"${CALLS}"; src 'repair_failed_syncs c /dev/null'
check "OutOfSync apps whose last operation failed get a sync operation; a Synced one and one already running do not" \
  'grep -q "patch application otel-operator --type merge" "${CALLS}" && grep -q "patch application ai-layer-otel --type merge" "${CALLS}" && ! grep -q "patch application busy\|patch application fine" "${CALLS}"'

echo "== repair_agent_injection =="
mkpods() { printf '{"items":[{"metadata":{"name":"workshop-agent-a","namespace":"agent","annotations":{"instrumentation.opentelemetry.io/inject-python":"watch-it-burn-python"}},"spec":{"initContainers":%s,"containers":[]}},{"metadata":{"name":"guard-proxy-b","namespace":"agent"},"spec":{"containers":[]}}]}' "$1" >"${T}/agentpods.json"; }
python3 - "${SHIM}/kubectl" <<'PY2'
import sys,pathlib
p=pathlib.Path(sys.argv[1]); s=p.read_text()
s=s.replace('case "$*" in','case "$*" in\n  *"-n agent get pods -o json"*) cat "${T}/agentpods.json" 2>/dev/null || echo \'{"items":[]}\'; exit 0 ;;\n  *"get endpoints otel-operator-opentelemetry-operator-webhook"*) cat "${T}/webhook_ip" 2>/dev/null; exit 0 ;;\n  *"get instrumentation watch-it-burn-python"*) [[ -f "${T}/instr_present" ]] && exit 0; exit 1 ;;',1)
p.write_text(s)
PY2
mkpods '[]'; printf '10.0.1.5' >"${T}/webhook_ip"; touch "${T}/instr_present"; : >"${CALLS}"
src 'repair_agent_injection c /dev/null'
check "an annotated pod without the injected init container is recreated once the webhook serves" \
  'grep -q "\-n agent delete pod workshop-agent-a" "${CALLS}" && ! grep -q "delete pod guard-proxy-b" "${CALLS}"'
: >"${CALLS}"; : >"${T}/webhook_ip"; src 'repair_agent_injection c /dev/null'
check "with no webhook endpoints the pod is left alone (deleting it would not help)" '! grep -q "delete pod" "${CALLS}"'
printf '10.0.1.5' >"${T}/webhook_ip"; mkpods '[{"name":"opentelemetry-auto-instrumentation-python"}]'; : >"${CALLS}"; src 'repair_agent_injection c /dev/null'
check "an already-instrumented pod is left alone" '! grep -q "delete pod" "${CALLS}"'
mkpods '[]'; : >"${CALLS}"; src 'verify_one c /dev/null acct; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "verify records an uninstrumented agent pod as <name>:otel-injection" 'grep -qx "c:otel-injection" "${T}/out"'
: >"${T}/webhook_ip"; : >"${CALLS}"; src 'verify_one c /dev/null acct; cat "${FAIL_FILE}" 2>/dev/null; rm -f "${FAIL_FILE}"' >"${T}/out"
check "with no serving webhook (burn profile) an uninjected pod is not recorded" '! grep -q "otel-injection" "${T}/out"'
printf '10.0.1.5' >"${T}/webhook_ip"
rm -f "${T}/agentpods.json"

echo "== repair_stuck_pods =="
printf '{"items":[{"metadata":{"namespace":"datadog","name":"datadog-agent-old","deletionTimestamp":"%s"}},{"metadata":{"namespace":"agent","name":"console-new","deletionTimestamp":"%s"}},{"metadata":{"namespace":"agent","name":"console-live"}}]}' "$old" "$new" >"${T}/pods.json"
: >"${CALLS}"; src 'repair_stuck_pods c /dev/null'
check "only the pod Terminating past the threshold is force-deleted" \
  'grep -q "\-n datadog delete pod datadog-agent-old --force --grace-period=0" "${CALLS}" && ! grep -q "delete pod console" "${CALLS}"'

echo "== prune_empty_states =="
echo '{"resources":[]}' >"${T}/states/watch-it-burn-attendee-105.tfstate"; echo '{"resources":[{"type":"x"}]}' >"${T}/states/watch-it-burn-attendee-001.tfstate"
src 'prune_empty_states'
check "an empty state is removed and a real one kept" '[[ ! -e "${T}/states/watch-it-burn-attendee-105.tfstate" && -e "${T}/states/watch-it-burn-attendee-001.tfstate" ]]'

echo "== verify_one =="
: >"${CALLS}"; VERIFY_RC=1 src 'verify_one watch-it-burn-attendee-002 /dev/null acct; cat "${FAIL_FILE}"; rm -f "${FAIL_FILE}"' >"${T}/out"
check "a failing datadog-orgs verifier is recorded as <name>:datadog-orgs" 'grep -qx "watch-it-burn-attendee-002:datadog-orgs" "${T}/out" && grep -q "^verify ctx-test acct" "${CALLS}"'

echo "== wiring =="
check "converge_one runs repair_one" 'grep -q "^    repair_one \"\${name}\" \"\${kcfg}\" \"\${acct_profile}\"" "${FLEET}"'
check "repair_one includes repair_failed_syncs" 'grep -q "^    repair_step repair_failed_syncs \"\${name}\" \"\${kcfg}\"" "${FLEET}"'
check "every repair and verifier in repair_one runs as a repair_step, but pin_bedrock_profiles (#635)" \
  '[[ "$(sed -n "/^repair_one() {/,/^}/p" "${FLEET}" | grep -cE "^    (repair_|verify_)" )" -eq 8 && "$(sed -n "/^repair_one() {/,/^}/p" "${FLEET}" | grep -c "^    repair_step ")" -eq 8 ]]'
check "repair_one runs repair_env_order (#679)" 'grep -q "^    repair_step repair_env_order \"\${name}\" \"\${kcfg}\"" "${FLEET}"'
check "verify_one judges the ai-layer rollout and records it (#679)" \
  'sed -n "/^verify_one() {/,/^}/p" "${FLEET}" | grep -q "ai_layer_rollout \"\${name}\" \"\${kcfg}\" || record_fail \"\${name}:ai-layer-rollout\""'
check "converge instructors skips roster slots with no state" 'grep -q "not provisioned, skipping" "${FLEET}"'
check "up ends with a converge pass over what it built" 'grep -q "repair-and-verify pass over" "${FLEET}"'
check "the post-up wait and verify iterate the PROVISION_SPEC names, never the register arguments" \
  'grep -q "wait_for_console_lbs \"\${built\[@\]}\"" "${FLEET}" && grep -q "for _n in \"\${built\[@\]}\"" "${FLEET}" && ! grep -q "wait_for_console_lbs \"\$@\"" "${FLEET}"'
: >"${CALLS}"; rm -f "${T}/k_polls"
src 'wait_for_console_lbs ""; echo rc=$?' >"${T}/out"
check "an empty name is not waited for" 'grep -qx "rc=0" "${T}/out" && [[ ! -f "${T}/k_polls" ]]'
check "bootstrap_one resolves keys through datadog_keys_for" 'grep -q "< <(datadog_keys_for \"\${name}\")" "${FLEET}"'
check "status, routes and converge prune empty states" '[[ "$(grep -c "^    prune_empty_states$" "${FLEET}")" -eq 3 ]]'

echo "== offline means offline =="
check "no check above called aws, kubectl, eksctl, terraform or helm" 'no_cloud_clean'

echo; echo "  ${pass} passed, ${fail} failed"
[[ -s "${T}/stderr" ]] && { echo "  (stderr, last lines)"; tail -4 "${T}/stderr" | sed 's/^/    /'; }
exit $(( fail > 0 ))
