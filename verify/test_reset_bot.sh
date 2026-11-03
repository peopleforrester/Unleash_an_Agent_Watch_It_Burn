#!/usr/bin/env bash
# ABOUTME: Behavioural tests for `fleet.sh reset-bot` (#539): guard-proxy is restarted by a pod delete and the
# ABOUTME: public /cost must read $0 over 0 requests afterwards. Offline; kubectl and curl are shims.
#
# Usage: verify/test_reset_bot.sh      (no cloud access)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLEET="${HERE}/../infra/terraform/fleet/fleet.sh"
ROS="${HERE}/../facilitation/kubecon-na-2026-run-of-show.md"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
SHIM="${T}/bin"; mkdir -p "${SHIM}" "${T}/states"; CALLS="${T}/calls"; : >"${CALLS}"
fail=0; pass=0
check() { if eval "$2"; then pass=$((pass+1)); echo "  PASS  $1"; else fail=$((fail+1)); echo "  FAIL  $1"; fi; }

# ---- shims: every external command records its argv and answers from env the test controls ----
cat >"${SHIM}/aws" <<'S'
#!/usr/bin/env bash
echo "aws $*" >>"${CALLS}"; exit 0
S
cat >"${SHIM}/kubectl" <<'S'
#!/usr/bin/env bash
echo "kubectl $* [AWS_PROFILE=${AWS_PROFILE:-}]" >>"${CALLS}"
case "$*" in
  "config current-context") echo "${KCTX}" ;;
  # The guard-proxy Deployment: proxy.py's shape unless the test hands it another (#778).
  *"get deployment guard-proxy -o json"*)
      [[ "${DEPLOY_RC:-0}" -eq 0 ]] || exit 1
      cat "${DEPLOY_FILE:-${T}/deploy-py.json}" ;;
  *"annotate application ai-layer"*) exit "${ANNOTATE_RC:-0}" ;;
  # The scale to 0 empties the selector until the scale back; SCALE0_RC refuses only the scale to 0.
  *"scale deployment guard-proxy --replicas=0"*) [[ "${SCALE0_RC:-0}" -eq 0 ]] || exit 1; touch "${T}/scaled0" ;;
  *"scale deployment guard-proxy --replicas="*) rm -f "${T}/scaled0" ;;
  *"create -f -"*) cat >"${T}/reset-pod.json"; exit "${CREATE_RC:-0}" ;;
  *"get pod guard-proxy-reset-spend -o jsonpath"*) echo "${RESET_PHASE:-Succeeded}" ;;
  *"logs pod/guard-proxy-reset-spend"*) printf '%s\n' "${RESET_LOG:-reset-spend: cleared \$0.0114 over 3 requests (10300 tokens), 2 sessions, and no runtime cost cap from /var/lib/guard-proxy/spend.db}" ;;
  *"delete pod guard-proxy-reset-spend"*) exit 0 ;;
  *"get deployments,services,configmaps,pods"*)
      # Real kubectl leaves managedFields out of -o json unless --show-managed-fields is passed (2026-11-01:
      # reset-bot cleared 0 objects on attackme while a bot-made maintenance-shell stood there).
      if [[ "$*" != *--show-managed-fields* ]]; then echo '{"items":[]}'
      elif [[ -n "${BOTMADE_FILE:-}" ]]; then cat "${BOTMADE_FILE}"
      elif [[ -n "${BOTMADE:-}" ]]; then printf '%s' "${BOTMADE}"; else echo '{"items":[]}'; fi ;;
  *"get pods"*"-o jsonpath"*) [[ -e "${T}/scaled0" && -z "${OLD_STAYS:-}" ]] || echo "guard-proxy-old" ;;
  *"get pods"*"-o json"*)
      if [[ "${READY:-1}" == 1 ]]; then
          echo '{"items":[{"metadata":{"name":"guard-proxy-old","deletionTimestamp":"x"},"status":{"conditions":[{"type":"Ready","status":"True"}]}},
                          {"metadata":{"name":"guard-proxy-new"},"status":{"conditions":[{"type":"Ready","status":"True"}]}}]}'
      else
          echo '{"items":[{"metadata":{"name":"guard-proxy-new"},"status":{"conditions":[{"type":"Ready","status":"False"}]}}]}'
      fi ;;
  *"delete pod"*) exit "${DELETE_RC:-0}" ;;
esac
exit 0
S
# curl: answers /cost with the next line of ${T}/cost.replies, the last line again once they run out. A line
# reading FAIL is an unreachable host (curl -f exits non-zero with nothing on stdout).
cat >"${SHIM}/curl" <<'S'
#!/usr/bin/env bash
url=""; for a in "$@"; do [[ "${a}" == http* ]] && url="${a}"; done
echo "curl ${url}" >>"${CALLS}"
n="$(grep -c '^curl ' "${CALLS}")"; total="$(wc -l <"${T}/cost.replies")"
reply="$(sed -n "$(( n < total ? n : total ))p" "${T}/cost.replies")"
[[ "${reply}" == FAIL ]] && exit 22
printf '%s' "${reply}"
S
chmod +x "${SHIM}"/*
export T CALLS PATH="${SHIM}:${PATH}"
C=watch-it-burn-community; ADMIN=watch-it-burn-private
touch "${T}/states/${C}.tfstate" "${T}/states/${ADMIN}.tfstate"
ctx_of() { printf 'arn:aws:eks:us-west-2:111122223333:cluster/%s' "$1"; }
ZERO='{"tier": "nova", "requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "usd": 0.0, "cap_usd": 25.0, "budget_guard": false}'
SPENT='{"tier": "nova", "requests": 3, "input_tokens": 9000, "output_tokens": 1300, "total_tokens": 10300, "usd": 0.0114, "cap_usd": 25.0, "budget_guard": false}'
replies() { printf '%s\n' "$@" >"${T}/cost.replies"; }
# The live guard-proxy Deployment, two ways: proxy.py (spend in memory) and the Go build after the #738
# cutover, with go-spend-store's (#751) claim mounted and SPEND_STORE_PATH on it.
cat >"${T}/deploy-py.json" <<'J'
{"spec":{"replicas":1,"template":{"spec":{"containers":[{"name":"proxy","image":"ghcr.io/peopleforrester/watch-it-burn:python-3.12-slim@sha256:6c4d",
 "command":["python","/app/proxy.py"],"env":[{"name":"COST_CAP_USD","value":"25"}],
 "volumeMounts":[{"name":"src","mountPath":"/app","readOnly":true}]}],"volumes":[{"name":"src","configMap":{"name":"guard-proxy-src"}}]}}}}
J
GO_IMAGE="ghcr.io/peopleforrester/watch-it-burn@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
cat >"${T}/deploy-go.json" <<J
{"spec":{"replicas":1,"strategy":{"type":"Recreate"},"template":{"spec":{
 "serviceAccountName":"guard-proxy-reader","automountServiceAccountToken":true,
 "securityContext":{"runAsNonRoot":true,"runAsUser":1000,"runAsGroup":1000,"fsGroup":1000,"seccompProfile":{"type":"RuntimeDefault"}},
 "nodeSelector":{"kubernetes.io/os":"linux"},
 "containers":[{"name":"proxy","image":"${GO_IMAGE}","args":["--listen",":8080"],
  "env":[{"name":"COST_CAP_USD","value":"25"},{"name":"SPEND_STORE_PATH","value":"/var/lib/guard-proxy/spend.db"}],
  "resources":{"limits":{"cpu":"500m","memory":"256Mi"},"requests":{"cpu":"50m","memory":"64Mi"}},
  "securityContext":{"allowPrivilegeEscalation":false,"readOnlyRootFilesystem":true,"capabilities":{"drop":["ALL"]}},
  "readinessProbe":{"httpGet":{"path":"/healthz","port":8080}},
  "volumeMounts":[{"name":"tmp","mountPath":"/tmp"},{"name":"spend-store","mountPath":"/var/lib/guard-proxy"}]}],
 "volumes":[{"name":"tmp","emptyDir":{}},{"name":"spend-store","persistentVolumeClaim":{"claimName":"guard-proxy-spend"}}]}}}}
J
# Sourcing fleet.sh: the source guard keeps main() from running; WIB_* settings make every wait instant.
src() { # $1: bash snippet to run after sourcing
  : >"${CALLS}"; : >"${T}/stderr"
  ( cd "$(dirname "${FLEET}")" && WIB_STATE_DIR="${T}/states" WIB_LOG_DIR="${T}/logs" WIB_DEFAULT_ACCOUNT=accen-dev \
      WIB_RESTART_WAIT=2 WIB_RESTART_INTERVAL=1 \
      bash -c "source '${FLEET}' >/dev/null 2>&1; $1" 2>>"${T}/stderr" )
}

echo "== reset-bot restarts guard-proxy and reads the counter back at zero =="
replies "${ZERO}"
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "exits 0 once the new pod is Ready and /cost reads zero" '[[ "${rc}" -eq 0 ]]'
check "deletes the guard-proxy pod by its selector, in ns agent, with an explicit context" \
  'grep -q -- "kubectl --context $(ctx_of "${C}") -n agent get pods -l app.kubernetes.io/name=guard-proxy" "${CALLS}" && grep -q "kubectl --context $(ctx_of "${C}") -n agent delete pod guard-proxy-old --wait=false" "${CALLS}"'
check "runs in the roster's account" 'grep "delete pod" "${CALLS}" | grep -q "AWS_PROFILE=accen-dev"'
check "a pod delete, never a rollout restart or a spec edit (Argo CD owns the spec)" '! grep -qE "rollout|set env|patch|annotate|scale" "${CALLS}"'
check "reads the counter the room sees, on attackme" 'grep -q "^curl https://attackme.burritobot.co/cost$" "${CALLS}"'
check "the delete comes before the read" 'grep -n "delete pod\|^curl " "${CALLS}" | head -1 | grep -q "delete pod"'
check "says the counter is at zero, with the figure" 'grep -q "counter at zero on https://attackme.burritobot.co/cost (\$0.0000 over 0 requests)" "${T}/stderr"'

check "a proxy.py guard-proxy is read once, and nothing is scaled, paused or created" \
  'grep -q "get deployment guard-proxy -o json" "${CALLS}" && ! grep -qE "create -f -|reset-spend" "${CALLS}"'

echo "== a Go guard-proxy: Argo CD paused, scale to 0, reset-spend from the proxy's image, scale back (#778) =="
replies "${ZERO}"
DEPLOY_FILE="${T}/deploy-go.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
order="$(grep -nE "annotate application ai-layer|scale deployment guard-proxy|create -f -|logs pod/|delete pod guard-proxy-reset-spend|^curl " "${CALLS}" \
  | sed -E 's/^([0-9]+):.*(skip-reconcile=true|skip-reconcile-|replicas=[0-9]+|create -f -|logs|delete pod|curl).*/\2/' | uniq | tr '\n' ' ')"
check "exits 0 once guard-proxy is back and /cost reads zero" '[[ "${rc}" -eq 0 ]]'
check "in order: pause, scale to 0, clear a leftover, create, logs, delete, scale to 1, resume, read (${order})" \
  '[[ "${order}" == "skip-reconcile=true replicas=0 delete pod create -f - logs delete pod replicas=1 skip-reconcile- curl " ]]'
check "the pause and resume are on the ai-layer Application in argocd, with an explicit context" \
  '[[ "$(grep -c -- "--context $(ctx_of "${C}") -n argocd annotate application ai-layer" "${CALLS}")" -eq 2 ]]'
check "both scales run as the Argo CD controller, the principal the drift policy admits" \
  '[[ "$(grep "scale deployment guard-proxy" "${CALLS}" | grep -c -- "--as=system:serviceaccount:argocd:argocd-application-controller")" -eq 2 ]]'
check "it waits for the old pod to be gone before the reset pod is created" \
  '[[ "$(grep -n "get pods -l app.kubernetes.io/name=guard-proxy -o jsonpath" "${CALLS}" | tail -1 | cut -d: -f1)" -lt "$(grep -n "create -f -" "${CALLS}" | cut -d: -f1)" ]]'
check "never deletes the proxy pod, rolls it out or edits its spec" \
  '! grep -qE "delete pod guard-proxy-old|rollout|set env|patch" "${CALLS}"'
check "prints the command's line naming what it cleared" \
  'grep -q "watch-it-burn-community: reset-spend: cleared \$0.0114 over 3 requests (10300 tokens), 2 sessions, and no runtime cost cap from /var/lib/guard-proxy/spend.db" "${T}/stderr"'
pod_field() { python3 -c 'import json, sys; p = json.load(open(sys.argv[1])); print(json.dumps(eval(sys.argv[2])))' "${T}/reset-pod.json" "$1"; }
check "the reset pod runs the proxy's own digest-pinned image" '[[ "$(pod_field "p[\"spec\"][\"containers\"][0][\"image\"]")" == "\"${GO_IMAGE}\"" ]]'
check "with args reset-spend --store SPEND_STORE_PATH, and the image's entrypoint" \
  '[[ "$(pod_field "[c.get(\"command\"), c[\"args\"]] if (c := p[\"spec\"][\"containers\"][0]) else 0")" == "[null, [\"reset-spend\", \"--store\", \"/var/lib/guard-proxy/spend.db\"]]" ]]'
check "mounts only the store's claim, where the proxy mounts it" \
  '[[ "$(pod_field "[p[\"spec\"][\"volumes\"], p[\"spec\"][\"containers\"][0][\"volumeMounts\"]]")" == "[[{\"name\": \"spend-store\", \"persistentVolumeClaim\": {\"claimName\": \"guard-proxy-spend\"}}], [{\"name\": \"spend-store\", \"mountPath\": \"/var/lib/guard-proxy\"}]]" ]]'
check "runs once, as the proxy's user and group with its fsGroup, and with no API token" \
  '[[ "$(pod_field "[p[\"spec\"][\"restartPolicy\"], p[\"spec\"][\"securityContext\"][\"runAsUser\"], p[\"spec\"][\"securityContext\"][\"fsGroup\"], p[\"spec\"][\"automountServiceAccountToken\"], \"serviceAccountName\" in p[\"spec\"]]")" == "[\"Never\", 1000, 1000, false, false]" ]]'
check "keeps the container's security context and resources, so admission treats it as the proxy" \
  '[[ "$(pod_field "[c[\"securityContext\"][\"readOnlyRootFilesystem\"], c[\"resources\"][\"limits\"][\"memory\"], \"readinessProbe\" in c] if (c := p[\"spec\"][\"containers\"][0]) else 0")" == "[true, \"256Mi\", false]" ]]'
check "is not selected as guard-proxy, so the Service never routes to it" \
  '[[ "$(pod_field "p[\"metadata\"][\"labels\"]")" == "{\"app.kubernetes.io/name\": \"guard-proxy-reset-spend\"}" ]]'

echo "== a failed reset still brings guard-proxy and Argo CD back =="
replies "${ZERO}"
RESET_PHASE=Failed RESET_LOG="guard-proxy: open spend store /var/lib/guard-proxy/spend.db: held by another process" \
  DEPLOY_FILE="${T}/deploy-go.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a Failed reset pod fails, prints the command's refusal, and /cost is not read" \
  '[[ "${rc}" -ne 0 ]] && grep -q "held by another process" "${T}/stderr" && grep -q "reset-spend did not succeed (pod phase Failed" "${T}/stderr" && ! grep -q "^curl " "${CALLS}"'
check "and still scales guard-proxy back and resumes Argo CD" \
  'grep -q "scale deployment guard-proxy --replicas=1" "${CALLS}" && grep -q "skip-reconcile-" "${CALLS}"'
CREATE_RC=1 DEPLOY_FILE="${T}/deploy-go.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a refused reset pod fails, and guard-proxy and Argo CD come back" \
  '[[ "${rc}" -ne 0 ]] && grep -q "reset pod guard-proxy-reset-spend was refused" "${T}/stderr" && grep -q "replicas=1" "${CALLS}" && grep -q "skip-reconcile-" "${CALLS}"'
SCALE0_RC=1 DEPLOY_FILE="${T}/deploy-go.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a refused scale to 0 fails before any reset pod, and Argo CD is resumed" \
  '[[ "${rc}" -ne 0 ]] && ! grep -q "create -f -" "${CALLS}" && grep -q "skip-reconcile-" "${CALLS}"'
OLD_STAYS=1 DEPLOY_FILE="${T}/deploy-go.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "an old pod that never goes fails before any reset pod, and guard-proxy and Argo CD come back" \
  '[[ "${rc}" -ne 0 ]] && grep -q "still has guard-proxy-old" "${T}/stderr" && ! grep -q "create -f -" "${CALLS}" && grep -q "replicas=1" "${CALLS}" && grep -q "skip-reconcile-" "${CALLS}"'
ANNOTATE_RC=1 DEPLOY_FILE="${T}/deploy-go.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "Argo CD that cannot be paused leaves guard-proxy running" \
  '[[ "${rc}" -ne 0 ]] && ! grep -q "scale deployment" "${CALLS}" && grep -q "guard-proxy left running" "${T}/stderr"'

echo "== a store the reset pod could not reach is refused before anything changes =="
python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); s = d["spec"]["template"]["spec"]; s["volumes"][1] = {"name": "spend-store", "emptyDir": {}}; json.dump(d, open(sys.argv[2], "w"))' "${T}/deploy-go.json" "${T}/deploy-emptydir.json"
DEPLOY_FILE="${T}/deploy-emptydir.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a store on an emptyDir is refused, saying so" \
  '[[ "${rc}" -ne 0 ]] && grep -q "is on volume spend-store, which is not a PersistentVolumeClaim" "${T}/stderr" && ! grep -qE "annotate|scale|create" "${CALLS}"'
python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); d["spec"]["template"]["spec"]["containers"][0]["volumeMounts"].pop(); json.dump(d, open(sys.argv[2], "w"))' "${T}/deploy-go.json" "${T}/deploy-nomount.json"
DEPLOY_FILE="${T}/deploy-nomount.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a store on no mount is refused" '[[ "${rc}" -ne 0 ]] && grep -q "is on no read-write volume" "${T}/stderr" && ! grep -q "scale" "${CALLS}"'
python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); d["spec"]["template"]["spec"]["containers"][0]["command"] = ["/guard-proxy", "--config", "/etc/c.yaml"]; json.dump(d, open(sys.argv[2], "w"))' "${T}/deploy-go.json" "${T}/deploy-cmdargs.json"
DEPLOY_FILE="${T}/deploy-cmdargs.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a command that carries its own arguments is refused" '[[ "${rc}" -ne 0 ]] && grep -q "is not the guard-proxy binary alone" "${T}/stderr" && ! grep -q "scale" "${CALLS}"'
python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); d["spec"]["template"]["spec"]["containers"][0]["command"] = ["/guard-proxy"]; json.dump(d, open(sys.argv[2], "w"))' "${T}/deploy-go.json" "${T}/deploy-cmd.json"
replies "${ZERO}"
DEPLOY_FILE="${T}/deploy-cmd.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a command that is the binary alone is kept" '[[ "${rc}" -eq 0 ]] && [[ "$(pod_field "p[\"spec\"][\"containers\"][0][\"command\"]")" == "[\"/guard-proxy\"]" ]]'
DEPLOY_RC=1 KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "an unreadable guard-proxy Deployment fails before any restart" \
  '[[ "${rc}" -ne 0 ]] && grep -q "could not read the guard-proxy Deployment" "${T}/stderr" && ! grep -q "delete pod guard-proxy-old" "${CALLS}"'

echo "== the old pod answering for a moment is waited out, not taken as the reset =="
replies "${SPENT}" "${ZERO}"
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a first read of the old figure, then zero, passes" '[[ "${rc}" -eq 0 ]] && [[ "$(grep -c "^curl " "${CALLS}")" -eq 2 ]]'

echo "== a counter that is not zero, or cannot be read, is a failure =="
replies "${SPENT}"
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a counter still at the first run's spend fails" '[[ "${rc}" -ne 0 ]]'
check "and says what it read" 'grep -q "still reads \$0.0114 over 3 requests" "${T}/stderr"'
replies FAIL
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "an unreachable /cost fails" '[[ "${rc}" -ne 0 ]] && grep -q "still reads unreadable" "${T}/stderr"'
replies '{"usd": 0.0}'
KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a reply without the request count is not taken as zero" '[[ "${rc}" -ne 0 ]]'

echo "== the restart has to finish before anything is read =="
replies "${ZERO}"
READY=0 KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "no Ready replacement fails, and /cost is not read" '[[ "${rc}" -ne 0 ]] && ! grep -q "^curl " "${CALLS}"'
DELETE_RC=1 KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a refused delete fails" '[[ "${rc}" -ne 0 ]] && grep -q "the delete was refused" "${T}/stderr"'

echo "== the target is confirmed before any mutation =="
KCTX="$(ctx_of watch-it-burn-whitney-admin)" src "cmd_reset_bot ${C}"; rc=$?
check "a kubeconfig pointing at another cluster is refused" '[[ "${rc}" -ne 0 ]] && ! grep -q "delete" "${CALLS}"'
src "cmd_reset_bot packt-cluster-1"; rc=$?
check "a non-watch-it-burn name is refused before kubectl runs" '[[ "${rc}" -ne 0 ]] && ! grep -q "kubectl" "${CALLS}"'
src "cmd_reset_bot"; rc=$?
check "no name is a usage error" '[[ "${rc}" -ne 0 ]] && grep -q "usage: reset-bot <name...>" "${T}/stderr"'

echo "== an admin cluster is read on its own host =="
replies "${ZERO}"
KCTX="$(ctx_of "${ADMIN}")" src "cmd_reset_bot ${ADMIN}"; rc=$?
check "michael-admin reads burritobot-private.burritobot.co/cost" '[[ "${rc}" -eq 0 ]] && grep -q "^curl https://burritobot-private.burritobot.co/cost$" "${CALLS}"'

echo "== it clears what the bot deployed, and nothing Argo CD owns (2026-11-01) =="
# The 2026-10-31 load replay left promo-mascot and two loyalty-rewards Deployments on attackme, made by the bot
# through deploy_app, and a rehearsal leaves Jokers on the wall. The room has to open on a clean cluster.
mf() { printf '{"kind":"%s","metadata":{"name":"%s","managedFields":[%s]}}' "$1" "$2" "$3"; }
MCP='{"manager":"workshop-mcp","operation":"Apply"}'; ARGO='{"manager":"argocd-controller","operation":"Apply"}'
BOTMADE="{\"items\":[$(mf Deployment promo-mascot "${MCP}"),$(mf Deployment joker-agatha-the-banshee "${MCP}"),$(mf Service maintenance-shell "${ARGO}"),$(mf Deployment guard-proxy "${ARGO},${MCP}"),$(mf ConfigMap note-from-bot "${MCP}")]}"
replies "${ZERO}"
BOTMADE="${BOTMADE}" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "exits 0" '[[ "${rc}" -eq 0 ]]'
check "deletes the Deployments and ConfigMap the bot applied" \
  'grep -q "delete deployment/promo-mascot" "${CALLS}" && grep -q "delete deployment/joker-agatha-the-banshee" "${CALLS}" && grep -q "delete configmap/note-from-bot" "${CALLS}"'
check "never deletes an object Argo CD manages, even one the bot also patched" \
  '! grep -q "delete deployment/guard-proxy\|delete service/maintenance-shell" "${CALLS}"'
check "in ns agent with an explicit context" 'grep "delete deployment/promo-mascot" "${CALLS}" | grep -q -- "--context $(ctx_of "${C}") -n agent"'
check "and says how many it cleared" 'grep -q "cleared 3 object(s) the bot deployed" "${T}/stderr"'

echo "== a live namespace's list is megabytes, which must not hit the argument limit =="
BIG="{\"items\":[$(for i in $(seq 1 4000); do printf '%s,' "$(mf ConfigMap "argo-cm-${i}" "${ARGO}")"; done)$(mf Deployment promo-mascot "${MCP}")]}"
printf '%s' "${BIG}" >"${T}/big.json"; unset BIG
replies "${ZERO}"
BOTMADE_FILE="${T}/big.json" KCTX="$(ctx_of "${C}")" src "cmd_reset_bot ${C}"; rc=$?
check "a $(( $(wc -c <"${T}/big.json") / 1024 )) KiB list still clears the one bot object" \
  '[[ "${rc}" -eq 0 ]] && grep -q "delete deployment/promo-mascot" "${CALLS}" && grep -q "cleared 1 object" "${T}/stderr"'

echo "== wired into the driver =="
src_txt="$(cat "${FLEET}")"; usage_txt="$(sed -n '/^usage() {/,/^}/p' "${FLEET}")"
check "main dispatches reset-bot" 'grep -qE "^        reset-bot\) cmd_reset_bot" <<<"${src_txt}"'
check "usage documents reset-bot" 'grep -q "^    reset-bot <name...>" <<<"${usage_txt}"'

echo "== the run-of-show resets the community bot before every run on one bring-up =="
ros="$(cat "${ROS}")"
night="$(sed -n '/^## Night Before$/,/^## Rollback on the day$/p' "${ROS}")"
record="$(sed -n '/^### Run-through record$/,/^### Probe record$/p' "${ROS}")"
check "Night Before resets the community cluster" 'grep -q "fleet.sh reset-bot watch-it-burn-community" <<<"${night}"'
check "the reset comes after the probe, which spends on attackme" \
  '[[ "$(grep -n "kubecon_probe.py community" <<<"${night}" | head -1 | cut -d: -f1)" -lt "$(grep -n "reset-bot" <<<"${night}" | head -1 | cut -d: -f1)" ]]'
check "the run-through record says to reset before each run" 'grep -q "fleet.sh reset-bot watch-it-burn-community" <<<"${record}"'
check "the counter is read back at zero in the run-of-show" 'grep -q "https://attackme.burritobot.co/cost" <<<"${ros}"'
check "the run-through record says the Go build's reset runs reset-spend and prints what it cleared (#778)" \
  'grep -q "guard-proxy reset-spend" <<<"${record}" && grep -q "reset-spend: cleared" <<<"${record}"'
check "the run-of-show never restarts guard-proxy with rollout restart" '! grep -qE "rollout restart[^|]*guard-proxy" <<<"${ros}"'
echo; echo "  ${pass} passed, ${fail} failed"; [[ "${fail}" -eq 0 ]]
