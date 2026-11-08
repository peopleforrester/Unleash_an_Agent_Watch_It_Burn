#!/bin/bash
# ABOUTME: Wires the student VTT: kubectl from the in-cluster ServiceAccount, the AWS CLI from the
# ABOUTME: student's own keys (optional secret), guardrail toggles, then launches ttyd in /home/student.
set -euo pipefail

SA=/var/run/secrets/kubernetes.io/serviceaccount
export HOME=/home/student
mkdir -p "$HOME/.kube" "$HOME/.aws"

if [ -f "$SA/token" ]; then
  kubectl config set-cluster this \
    --server="https://kubernetes.default.svc" \
    --certificate-authority="$SA/ca.crt" --embed-certs=true >/dev/null
  # tokenFile, NOT a baked --token value. EKS mounts a PROJECTED ServiceAccount token: it is short-lived
  # (~1h) and the kubelet rotates the file in place. Copying the token VALUE into the kubeconfig freezes a
  # snapshot that expires ~1h after pod start, after which every kubectl in this terminal fails with
  # "You must be logged in to the server (the server has asked for the client to provide credentials)" and
  # the guard toggles (which shell out to `kubectl exec deploy/guard-proxy`) all report "Could not reach
  # the guard-proxy". A 3-day-old cluster was hours past expiry; a fresh cluster would break ~1h into the
  # workshop. Pointing at tokenFile makes client-go re-read the rotated token on every call, so it never
  # expires while the pod runs. Regression-guarded by verify/test_terminal_kubeconfig.py.
  kubectl config set-credentials me >/dev/null
  kubectl config set "users.me.tokenFile" "$SA/token" >/dev/null
  kubectl config set-context this --cluster=this --user=me \
    --namespace="$(cat "$SA/namespace")" >/dev/null
  kubectl config use-context this >/dev/null
  : > "$HOME/.motd"   # start empty; only failures write to it
else
  echo "WARNING: no in-cluster ServiceAccount token found; kubectl is not auto-configured." > "$HOME/.motd"
fi

# Pre-configure the AWS CLI with the student's OWN keys. Written as the DEFAULT profile so `aws` works with
# no --profile inside the VTT. On a cluster without the secret, aws is installed but unconfigured; kubectl
# still works via the SA above.
#
# The keys are read here, with this pod's token, from the `student-aws-creds` Secret in namespace
# student-creds (#584), not mounted from `agent`. The key holds EKS cluster-admin on this cluster. In `agent`
# the agent's broad Role (the state Challenge 8 starts in) could read it, presign an EKS token and act as
# cluster-admin, an identity restrict-agent-spawned-workloads does not match. This terminal's ClusterRole
# reads Secrets in every namespace; no agent identity holds any grant in student-creds.
STUDENT_AWS_NS=student-creds
_student_aws() { kubectl -n "$STUDENT_AWS_NS" get secret student-aws-creds -o "jsonpath={.data.$1}" 2>/dev/null \
  | base64 -d 2>/dev/null || true; }
STUDENT_AK="$(_student_aws AWS_ACCESS_KEY_ID)"
STUDENT_SK="$(_student_aws AWS_SECRET_ACCESS_KEY)"
STUDENT_REGION="$(_student_aws AWS_DEFAULT_REGION)"
if [[ -n "${STUDENT_AK}" && -n "${STUDENT_SK}" ]]; then
  cat > "$HOME/.aws/credentials" <<CREDS
[default]
aws_access_key_id = ${STUDENT_AK}
aws_secret_access_key = ${STUDENT_SK}
CREDS
  cat > "$HOME/.aws/config" <<CFG
[default]
region = ${STUDENT_REGION:-us-west-2}
output = json
CFG
  chmod 600 "$HOME/.aws/credentials"
fi
unset STUDENT_AK STUDENT_SK STUDENT_REGION

# Self-serve guardrail toggles (B5/B11). Each prints PLAIN-LANGUAGE confirmation of what changed
# (not raw JSON) so a student can see what the guard does. Output/input guards flip via the guard-proxy
# /toggle (no new pod, ArgoCD-safe, the cost counter survives). The MCP guard (C7) has one control per
# format (#496). On a workshop cluster it patches the kagent Agent's evil-mcp toolNames allow-list. On an
# admin cluster (the KubeCon breakout) it rewrites agentgateway's mcpAuthorization rule for evil-mcp and
# leaves the allow-list full, so the rogue call reaches the gateway and is refused there. Argo CD ignores drift
# on both, so selfHeal keeps either toggle: the workshop-agent app on the allow-list, ai-layer on the rule (#707).
#
# _px <query> : hit the guard-proxy /toggle endpoint, swallow the JSON, return its exit code.
# _pxkey <query> <key> : the same, then print what the proxy now reports for <key>: True, False, or missing
# when this guard-proxy has no such guard. Prints nothing when the proxy could not be reached.
cat > "$HOME/.guardlib" <<'EOS'
# _show <cmd...> : print the command about to run as `$ cmd`, on stderr so a caller's $(...) still captures only
# the result. Michael, 2026-10-29: the room sees the real kubectl behind every guard command, not only the text.
# An argument is quoted the way bash reads it back: double quotes when it holds a ' and no " \ $ or `, else single
# quotes. verify/test_guard_commands_echo.py runs every printed line and compares it with the call that ran.
_show() { local a o='$'
  for a in "$@"; do
    case "$a" in
      *[!A-Za-z0-9_./=:,@%+-]*)
        case "$a" in
          *\'*) case "$a" in *[\"\\\$\`]*) o+=" '${a//\'/\'\\\'\'}'" ;; *) o+=" \"$a\"" ;; esac ;;
          *) o+=" '$a'" ;;
        esac ;;
      *) o+=" $a" ;;
    esac
  done
  printf '%s\n' "$o" >&2; }
_px() { local c=(kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import urllib.request;urllib.request.urlopen('http://localhost:8080/toggle?$1',timeout=10).read()")
  _show "${c[@]}"; "${c[@]}" >/dev/null 2>&1; }
_pxkey() { local c=(kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import json,urllib.request;print(json.load(urllib.request.urlopen('http://localhost:8080/toggle?$1',timeout=10)).get('$2','missing'))")
  _show "${c[@]}"; "${c[@]}" 2>/dev/null | tail -1; }
# _evil <json-array> : set ONLY the evil-mcp toolNames. It reads the live Agent, finds the tools entry whose
# mcpServer.name is evil-mcp (.evilpatch.py, never a fixed place in the array), and JSON-patches that entry's
# toolNames after a test op on its name, so a reorder in gitops/workshop-agent/agent.yaml, or one between the read
# and the patch, fails instead of narrowing workshop-mcp (#708). The real BurritoBot tools are never touched.
_evil() { local p c
  printf '$ kubectl -n agent get agent workshop-agent -o json | python3 "$HOME/.evilpatch.py" %s\n' "'$1'" >&2
  p="$(kubectl -n agent get agent workshop-agent -o json 2>/dev/null \
  | python3 "$HOME/.evilpatch.py" "$1")" || return 1
  c=(kubectl -n agent patch agent workshop-agent --type=json -p "$p")
  _show "${c[@]}"; "${c[@]}" >/dev/null 2>&1; }
# _c7gw : C7's control on this cluster. Returns 0 on an admin cluster, whose Argo CD root lab-bootstrap is
# labelled lab-platform/profile=admin (gitops/bootstrap/values-admin.yaml), or the KubeCon private one, labelled
# kubecon-private (values-kubecon-private.yaml, #774): there it is agentgateway's rule. Returns 1 anywhere else: there
# it is the toolNames allow-list. Returns 2 when Argo CD could not be asked, so a flaky lookup never picks
# the wrong control for an admin cluster's stage demo.
_c7gw() { local r c=(kubectl -n argocd get application lab-bootstrap --ignore-not-found \
  -o jsonpath='{.metadata.labels.lab-platform/profile}')
  _show "${c[@]}"; r="$("${c[@]}" 2>/dev/null)" || return 2; [ "$r" = admin ] || [ "$r" = kubecon-private ]; }
# _c7rule on|off : rewrite the one rule line in agentgateway-c7-config (on = get_weather only, off = 'true').
# The JSON patch tests the resourceVersion it read, so it never writes over a change it did not see. Then it
# touches the gateway pod: a pod update makes the kubelet refresh the ConfigMap volume now instead of on its
# next periodic sync, and agentgateway reloads the file when it changes. The touch is best effort.
_c7rule() { local p c
  printf '$ kubectl -n agent get configmap agentgateway-c7-config -o json | python3 "$HOME/.c7rule.py" %s\n' "$1" >&2
  p="$(kubectl -n agent get configmap agentgateway-c7-config -o json 2>/dev/null \
  | python3 "$HOME/.c7rule.py" "$1")" || return 1
  c=(kubectl -n agent patch configmap agentgateway-c7-config --type=json -p "$p")
  _show "${c[@]}"; "${c[@]}" >/dev/null 2>&1 || return 1
  c=(kubectl -n agent annotate pod -l app.kubernetes.io/name=agentgateway --overwrite \
    "wib.agenticburn.com/c7-rule-at=$(date +%s)")
  _show "${c[@]}"; "${c[@]}" >/dev/null 2>&1 || true; }
# _mcp on|off : flip C7 through this cluster's control. Prints which one it used (gateway or toolnames), or
# nothing, with a failing status, when the change did not go through. On an admin cluster the rule is written
# first, so a refused patch (a stale read) leaves the allow-list as it was too; nothing here deletes, restarts
# or rolls out the gateway pod.
_mcp() { local all='["get_weather","read_internal_config","apply_optimization"]' gw
  _c7gw; gw=$?
  case "$gw:$1" in
    0:on)  _c7rule on && _evil "$all" && echo gateway ;;
    0:off) _c7rule off && _evil "$all" && echo gateway ;;
    1:on)  _evil '["get_weather"]' && echo toolnames ;;
    1:off) _evil "$all" && echo toolnames ;;
    *) return 1 ;;
  esac; }
# The KubeCon breakout's switch (#774, Michael's spec 2026-11-01): the four Kubernetes guardrails, RBAC, Kyverno,
# KubeArmor and egress, turned on or off on this cluster AND on the other KubeCon cluster at once, from either
# terminal. The other cluster is reached with the kubeconfig `fleet.sh guardrails-link` writes into the
# guardrails-switch/guardrails-peer Secret: its endpoint, its CA and the token of its guardrails-switch ServiceAccount,
# whose grant is these guardrails' objects, what _both's steps need, and nothing else (gitops/guardrails-switch/).
# _peer : write that kubeconfig to ~/.kube/peer and print the other cluster's name. Prints nothing, failing, when this
# cluster has not been linked.
_peer() { local c k n
  c=(kubectl -n guardrails-switch get secret guardrails-peer -o 'jsonpath={.data.kubeconfig}')
  _show "${c[@]}"; k="$("${c[@]}" 2>/dev/null | base64 -d 2>/dev/null)"
  c=(kubectl -n guardrails-switch get secret guardrails-peer -o 'jsonpath={.data.name}')
  _show "${c[@]}"; n="$("${c[@]}" 2>/dev/null | base64 -d 2>/dev/null)"
  [ -n "$k" ] && [ -n "$n" ] || return 1
  mkdir -p "$HOME/.kube"; ( umask 077; printf '%s\n' "$k" > "$HOME/.kube/peer" )
  printf '%s\n' "$n"; }
# _kg on|off rbac|kyverno|kubearmor|egress <kubectl...> : one guardrail on one cluster, through the kubectl given
# (kubectl for this cluster; kubectl --kubeconfig ~/.kube/peer --context <name> for the other). The objects are the
# ones the chat page's badges read (guard-proxy's /controls): the workshop-agent Role, restrict-image-registries'
# action, block-recipe-snoop and agent-egress-allowlist. Kyverno is read back; the rest go by kubectl's exit code.
_kg() { local st="$1" g="$2" c a p; shift 2
  case "$st:$g" in
    on:rbac)       c=("$@" apply -f "$HOME/challenges/c5-scoped-role.yaml") ;;
    off:rbac)      c=("$@" apply -f "$HOME/challenges/c8-broad-role.yaml") ;;
    on:kubearmor)  c=("$@" apply -f "$HOME/challenges/c3-kubearmor-policy.yaml") ;;
    off:kubearmor) c=("$@" delete --ignore-not-found -f "$HOME/challenges/c3-kubearmor-policy.yaml") ;;
    on:egress)     c=("$@" apply -f "$HOME/challenges/c1-network-policy.yaml") ;;
    off:egress)    c=("$@" delete --ignore-not-found -f "$HOME/challenges/c1-network-policy.yaml") ;;
    on:kyverno|off:kyverno)
      a=Deny; [ "$st" = off ] && a=Audit
      for p in restrict-image-registries deny-external-registries; do
        c=("$@" patch validatingpolicy "$p" --type=json \
          -p "[{\"op\":\"replace\",\"path\":\"/spec/validationActions\",\"value\":[\"$a\"]}]")
        _show "${c[@]}"; "${c[@]}" >/dev/null 2>&1
        c=("$@" get validatingpolicy "$p" -o 'jsonpath={.spec.validationActions[0]}')
        _show "${c[@]}"; [ "$("${c[@]}" 2>/dev/null)" = "$a" ] || return 1
      done
      return 0 ;;
    *) return 1 ;;
  esac
  _show "${c[@]}"; "${c[@]}" >/dev/null 2>&1; }
# _guardrails on|off [seconds] : the switch itself. One guardrail at a time, here and then on the other cluster, so
# each badge lights (or goes dark) on both chat pages together; [seconds] waits between guardrails, so the room can
# watch each one arrive (the page polls every 12 seconds). Says what changed, names anything that did not, and fails
# when either cluster missed a guardrail or the other cluster could not be reached at all.
_guardrails() { local st="$1" pause="${2:-0}" peer g bad=() line
  case "$pause" in ''|*[!0-9]*) echo "Usage: guardrails-$st [seconds between guardrails, default 0]"; return 2 ;; esac
  peer="$(_peer)" || peer=""
  for g in rbac kyverno kubearmor egress; do
    _kg "$st" "$g" kubectl || bad+=("$g on this cluster")
    if [ -n "$peer" ]; then
      _kg "$st" "$g" kubectl --kubeconfig "$HOME/.kube/peer" --context "$peer" || bad+=("$g on $peer")
    fi
    case "$st:$g" in
      on:rbac)       line="🛡️  RBAC ON: agent-sa reads one Secret by name, its own config. The CEO's record is Forbidden." ;;
      on:kyverno)    line="🛡️  Kyverno ON: admission denies every image outside registry.burritobot.co for what BurritoBot deploys, and within a minute Kyverno deletes what it already deployed from anywhere else." ;;
      on:kubearmor)  line="🛡️  KubeArmor ON: the kernel blocks reads of the recipe files in the agent's tool pod." ;;
      on:egress)     line="🛡️  Egress ON: the agent namespace reaches its model, DNS, telemetry and the cluster; the internet is cut off." ;;
      off:rbac)      line="🔓 RBAC OFF: agent-sa reads every Secret in its namespace again." ;;
      off:kyverno)   line="🔓 Kyverno OFF: the registry rules only report; any image BurritoBot deploys is admitted." ;;
      off:kubearmor) line="🔓 KubeArmor OFF: the recipe files are readable from the agent's tool pod again." ;;
      off:egress)    line="🔓 Egress OFF: the agent namespace can reach the internet again." ;;
    esac
    echo "$line"
    [ "$g" = egress ] || [ "$pause" = 0 ] || sleep "$pause"
  done
  if [ -z "$peer" ]; then
    echo "⚠️  This cluster is not linked to the other KubeCon cluster (no guardrails-switch/guardrails-peer Secret),"
    echo "    so only this one was switched. From the fleet host: infra/terraform/fleet/fleet.sh guardrails-link"
    return 1
  fi
  if [ "${#bad[@]}" -gt 0 ]; then
    echo "⚠️  These did not switch $st: ${bad[*]}. Run 'guardrails-$st' again; it is safe to repeat."
    return 1
  fi
  echo "Both clusters, this one and $peer: all four Kubernetes guardrails are $st."; }
# _apply <file> <kubectl...> : a switch step for _both. kubectl apply of ~/challenges/<file> through the kubectl given.
_apply() { local f="$1" c; shift
  c=("$@" apply -f "$HOME/challenges/$f")
  _show "${c[@]}"; "${c[@]}" >/dev/null 2>&1; }
# _toggle <query> <kubectl...> : a switch step for _both. guard-proxy's /toggle?<query> on one cluster (#1148). Here,
# with plain kubectl, it is _px, the kubectl exec into deploy/guard-proxy it always was. On the peer it is a GET through
# the API server's Service proxy on guard-proxy:8080, the one guard-proxy grant guardrails-switch holds there
# (services/proxy, resourceNames guard-proxy:8080, get). An exec cannot be granted by name, since a Deployment's pod
# name changes, so it would open every pod in agent. The Service proxy dials the pod from the control plane on 8080,
# which #869's node rule admits; a cluster without that rule times out, so the wait is bounded at 20 seconds.
_toggle() { local q="$1" c; shift
  if [ "$*" = kubectl ]; then _px "$q"; return; fi
  c=("$@" get --raw "/api/v1/namespaces/agent/services/guard-proxy:8080/proxy/toggle?$q" --request-timeout=20s)
  _show "${c[@]}"; "${c[@]}" >/dev/null 2>&1; }
# _both <step> [args...] : one switch step on this cluster, then on the other KubeCon cluster (#1147, for #1132: the
# room plays on the public bot, so a fix the private terminal makes has to reach it too). The step is a function called
# as `<step> [args...] <kubectl...>`, the way _kg is, with kubectl for this cluster and kubectl --kubeconfig
# ~/.kube/peer --context <name> for the other, reached through guardrails-peer as _guardrails reaches it. The peer
# runs as its guardrails-switch ServiceAccount, so a step there can do only what gitops/guardrails-switch/ grants.
# Says in one line which clusters changed, naming a peer that could not be reached. A cluster with no guardrails-peer
# Secret, the 2-hour workshop's, is switched alone, and that is success; a Secret that is there but cannot be read is
# a failure, so a flaky read never passes for an unlinked cluster.
_both() { local peer="" link=none here=0 there=0 c r
  if peer="$(_peer)"; then link=peer
  else
    c=(kubectl -n guardrails-switch get secret guardrails-peer --ignore-not-found -o name)
    _show "${c[@]}"
    if r="$("${c[@]}" 2>/dev/null)" && [ -z "$r" ]; then link=none; else link=unread; fi
  fi
  "$@" kubectl || here=1
  if [ "$link" = peer ]; then "$@" kubectl --kubeconfig "$HOME/.kube/peer" --context "$peer" || there=1; fi
  case "$link:$here:$there" in
    peer:0:0) echo "Switched on both clusters: this one and $peer."; return 0 ;;
    peer:0:1) echo "⚠️  Switched on this cluster, but not on $peer: it could not be reached, or it refused the change." ;;
    peer:1:0) echo "⚠️  Switched on $peer, but not on this cluster: it refused the change." ;;
    peer:1:1) echo "⚠️  Switched on neither cluster: this one and $peer both failed." ;;
    none:0:*) echo "Switched on this cluster alone: it has no guardrails-switch/guardrails-peer Secret, so no other cluster is linked to it."
              return 0 ;;
    none:1:*) echo "⚠️  This cluster did not switch, and it has no guardrails-switch/guardrails-peer Secret naming another." ;;
    unread:0:*) echo "⚠️  Switched on this cluster, but guardrails-switch/guardrails-peer could not be read, so the other KubeCon cluster was not switched." ;;
    unread:1:*) echo "⚠️  This cluster did not switch, and guardrails-switch/guardrails-peer could not be read." ;;
  esac
  return 1; }
EOS

# The rule rewrite behind _c7rule. Reads the ConfigMap as JSON on stdin and prints the JSON patch. Exactly
# one line must carry the `# c7-rule` marker (gitops/ai-layer/agentgateway.yaml); anything else is an error,
# never a guess. verify/test_c7_gateway_toggle.py runs this against the committed ConfigMap.
cat > "$HOME/.c7rule.py" <<'EOS'
import json, sys
RULES = {"on": "'mcp.tool.name == \"get_weather\"'", "off": "'true'"}
MARK = "# c7-rule"
cm = json.load(sys.stdin)
lines = cm["data"]["config.yaml"].split("\n")
hits = [i for i, line in enumerate(lines) if line.rstrip().endswith(MARK)]
if len(sys.argv) != 2 or sys.argv[1] not in RULES or len(hits) != 1:
    sys.exit(1)
line = lines[hits[0]]
lines[hits[0]] = line[:len(line) - len(line.lstrip())] + "- " + RULES[sys.argv[1]] + " " + MARK
print(json.dumps([
    {"op": "test", "path": "/metadata/resourceVersion", "value": cm["metadata"]["resourceVersion"]},
    {"op": "replace", "path": "/data/config.yaml", "value": "\n".join(lines)},
]))
EOS

# The patch behind _evil. Reads the Agent as JSON on stdin and the new toolNames as a JSON array in argv[1], and
# prints the JSON patch for the one tools entry whose mcpServer.name is evil-mcp. No such entry, two of them, or
# an argument that is not a list of names is an error, never a guess. verify/test_evil_tools_by_name.py runs it.
cat > "$HOME/.evilpatch.py" <<'EOS'
import json, sys
tools = json.load(sys.stdin)["spec"]["declarative"]["tools"]
hits = [i for i, t in enumerate(tools) if (t.get("mcpServer") or {}).get("name") == "evil-mcp"]
names = json.loads(sys.argv[1]) if len(sys.argv) == 2 else None
if len(hits) != 1 or not isinstance(names, list) or not all(isinstance(n, str) for n in names):
    sys.exit(1)
entry = "/spec/declarative/tools/%d/mcpServer" % hits[0]
print(json.dumps([
    {"op": "test", "path": entry + "/name", "value": "evil-mcp"},
    {"op": "replace", "path": entry + "/toolNames", "value": names},
]))
EOS

# The platform catalogue, with LIVE values (Michael asked for this three times before it existed).
# Prints every service, where it is, and its actual password read from the cluster, so nobody has to dump
# a ConfigMap or grep a Service list to find their own Grafana. Mirrors gitops/ai-layer/web/platform.html.
cat > "$HOME/platform" <<'EOS'
#!/bin/bash
# ABOUTME: print every installed service, how to reach it, and its live credentials.
b(){ printf '\n\033[1;35m%s\033[0m\n' "$1"; }
row(){ printf '  \033[1m%-22s\033[0m %s\n' "$1" "$2"; }
sec(){ kubectl -n "$1" get secret "$2" -o jsonpath="{.data.$3}" 2>/dev/null | base64 -d 2>/dev/null; }

# The in-pod context is literally named "this" (set by this entrypoint), so derive the real cluster name
# from the kubeconfig cluster entry instead of the context name.
_cn="$(kubectl config view -o jsonpath='{.clusters[0].name}' 2>/dev/null | sed 's|.*/||')"
# The public hostname of this cluster's console, written to the cluster-identity ConfigMap at bootstrap
# (infra/datadog-cluster-identity.sh) and mounted into WIB_PUBLIC_HOST. Every address below is printed
# complete: Whitney (2026-09-06) had no way to know what "<host>" was.
_h="${WIB_PUBLIC_HOST:-<the host in your address bar>}"
# The identity names agenticburn.com; both domains serve every host, and burritobot.co is the one shown (#651).
[[ "${_h}" == *.agenticburn.com ]] && _h="${_h%.agenticburn.com}.burritobot.co"
echo "Everything installed on ${_cn:-your cluster}."

b "OTHER PARTS OF YOUR CLUSTER WITH A WEB PAGE"
row "Backstage" "https://backstage-${_h}   (every app, its owner and its pods)"
row "kagent UI" "in-cluster: kagent-ui.kagent:8080   (BurritoBot as its developer sees it)"
row "Party apps" "in-cluster: kubectl -n apps get svc   (hedgehog, wombat, unicorn, spider, mantis-shrimp)"
row "Grafana" "https://grafana-${_h}   (login: admin / $(sec monitoring prometheus-grafana admin-password 2>/dev/null || echo '<could not read secret>'))"

b "DELIVERY"
ap="$(sec argocd argocd-initial-admin-secret password)"
row "Argo CD" "https://argocd-${_h}"
row ""        "login: admin / ${ap:-<could not read secret>}"
row "Kyverno" "no UI:  kubectl get validatingpolicy"

b "RUNTIME SECURITY"
row "KubeArmor" "kubectl -n agent get kubearmorpolicy -o yaml     (inline block)"
row "Falco" "kubectl -n security logs -l app.kubernetes.io/name=falco -c falco --tail=40"
row "NetworkPolicy" "kubectl -n agent get networkpolicy"

b "THE AI LAYER"
row "kagent"      "kubectl -n agent get agent workshop-agent -o yaml"
row "guard-proxy" "guards-status        (your AI guardrails + spend cap)"
row "LLM Guard"   "in-cluster: llm-guard:8000"
row "MCP servers" "kubectl -n agent get pods -l app=workshop-mcp"
echo
echo "Full list with descriptions: open /platform in your browser."
EOS

# Read-only: which AI guards are currently on. The platform tour on the lab page points at this, and a
# student who has flipped several toggles needs a way to see where they actually are without guessing.
cat > "$HOME/guards-status" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
raw="$(kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8080/guards',timeout=10).read().decode())" 2>/dev/null | tail -1)"
if [ -z "$raw" ]; then
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guards-status' again."
  exit 1
fi
echo "Your AI guardrails right now:"
printf '%s' "$raw" | python3 -c '
import json,sys
g=json.load(sys.stdin)
label={"output":"Output guard (scrubs secrets on the way out)",
       "input_blocklist":"Input block-list (cheap, pre-model)",
       "input_classifier":"Injection classifier (model-based, reads support tickets too)",
       "budget":"Spend budget (freezes cost at the cap)",
       "topic":"On-topic guard (BurritoBot sells burritos only)"}
for k in ("output","input_blocklist","input_classifier","budget","topic"):
    on=g.get(k)
    print(("  n/a  " if on is None else "  ON   " if on else "  off  ")+label.get(k,k))
'
echo
echo "Flip them with: guard-output-on  guard-input-on  guard-mcp-on  guard-budget-on  guard-topic-on  (or guards-on / guards-off)"
echo "Cluster fixes: guard-rbac-on (the CEO's record)  guard-admission-on (the support ticket's image)"
echo "               guard-agency-on (the support ticket's Joker at KubeCon: the bot deploys nothing)"
echo "KubeCon: guardrails-on / guardrails-off (the four Kubernetes guardrails, on both clusters at once)"
EOS

# Combined: flip EVERY AI guard at once (the "reset and explore" convenience). guards-on leaves the on-topic
# guard OFF on purpose: every challenge prompt is off-topic by design, so with it on it would refuse each one
# before the guard that challenge teaches could fire. guards-off does turn it off, so off means wide open.
cat > "$HOME/guards-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
_px "output=on" && _px "input_blocklist=on&input_classifier=on" && _px "budget=on"
if ! _mcp on >/dev/null; then
  echo "⚠️  The MCP tool restriction did not switch on; it is left as it was. The other AI guards were"
  echo "    switched on. Run 'guard-mcp-on' to retry it."; exit 1
fi
echo "🛡️  ALL AI guards ON: output scrubbing, input block-list + injection classifier, MCP tool"
echo "    restriction, and the spend budget. Re-run any challenge to watch it get blocked, redacted,"
echo "    or frozen on cost."
EOS
cat > "$HOME/guards-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
_px "output=off" && _px "input_blocklist=off&input_classifier=off" && _px "budget=off" && _px "topic=off"
if ! _mcp off >/dev/null; then
  echo "⚠️  The MCP tool restriction did not switch off; it is left as it was. The other AI guards were"
  echo "    switched off. Run 'guard-mcp-off' to retry it."; exit 1
fi
echo "🔓 ALL AI guards OFF: the agent is back to wide open. Re-run any challenge prompt to see the weakness."
EOS

# OUTPUT guard (scrubs the leaked Bat Spit Amazing Awesome Sauce from replies).
cat > "$HOME/guard-output-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "output=on"; then
  echo "🛡️  OUTPUT guard ON. The agent's replies are now scanned on the way out: the recipe"
  echo "    amounts, the ogre-toenails ingredient, and the signature are redacted before they reach you."
  echo "    Re-send the recipe prompt; the reply comes back scrubbed (and Datadog shows the guard fired)."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-output-on' again."
fi
EOS
cat > "$HOME/guard-output-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "output=off"; then
  echo "🔓 OUTPUT guard OFF. Replies are no longer scrubbed. Re-send the recipe prompt and the"
  echo "    full secret recipe leaks straight through."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-output-off' again."
fi
EOS

# INPUT guards, the support ticket's fix (deterministic block-list + prompt-injection classifier), upstream of the model.
# Both set the two stages on this cluster's guard-proxy and on the other KubeCon cluster's (_both _toggle in .guardlib,
# #1148), so from slide 50 on every prompt the room sends the public bot is checked too. On the 2-hour lab's lone
# cluster, this one alone.
cat > "$HOME/guard-input-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _both _toggle "input_blocklist=on&input_classifier=on"; then
  echo "🛡️  INPUT guards ON, the support ticket's first tier (two stages): (1) a block-list rejects prompts containing"
  echo "    destructive commands or the secret-recipe phrases, and (2) a prompt-injection classifier catches"
  echo "    poisoned instructions, both in a prompt and in a support ticket as the ticket tool reads it."
  echo "    Re-send the ticket ask: the ticket comes back withheld, so the model never sees the hidden"
  echo "    instructions and nothing is deployed. A prompt the guards block never reaches the model at all."
else
  echo "⚠️  The input guards did not change everywhere. Wait a moment and try 'guard-input-on' again; it is safe to repeat."
  exit 1
fi
EOS
cat > "$HOME/guard-input-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _both _toggle "input_blocklist=off&input_classifier=off"; then
  echo "🔓 INPUT guards OFF. Prompts go straight to the model. Re-send the poisoned support ticket and"
  echo "    the injected instructions ride right in (and you pay tokens for it)."
else
  echo "⚠️  The input guards did not change everywhere. Wait a moment and try 'guard-input-off' again; it is safe to repeat."
  exit 1
fi
EOS

# MCP tool authorization, the poisoned weather tool's fix. Only get_weather stays usable on evil-mcp; the rogue tools
# (read_internal_config, apply_optimization) are stopped. workshop-mcp is left fully intact. Where they are
# stopped depends on the cluster (_mcp in .guardlib): at agentgateway on an admin cluster, in the agent's
# allow-list everywhere else.
cat > "$HOME/guard-mcp-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
case "$(_mcp on)" in
  gateway)
    echo "🛡️  MCP tool authorization ON, at the gateway, against the poisoned weather tool. agentgateway now allows only get_weather"
    echo "    on evil-mcp: the rogue tools drop out of the tool list it hands the agent, and a call to"
    echo "    read_internal_config is refused before evil-mcp ever runs it. Your real BurritoBot tools are"
    echo "    untouched. Re-ask the weather question: the poisoned description still tries, and the gateway"
    echo "    says no, so the sentinel never appears. The gateway reloads its rule without a restart." ;;
  toolnames)
    echo "🛡️  MCP tool authorization ON, against the poisoned weather tool. The rogue evil-mcp tools (read_internal_config,"
    echo "    apply_optimization) are removed from the agent's allow-list; only get_weather remains. Your real"
    echo "    BurritoBot tools are untouched. Re-ask the weather question: the poisoned description still tries,"
    echo "    but the rogue tool is gone, so the sentinel never appears." ;;
  *)
    echo "⚠️  The MCP tool restriction did not switch on. Wait a moment and try 'guard-mcp-on' again."; exit 1 ;;
esac
EOS
cat > "$HOME/guard-mcp-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
case "$(_mcp off)" in
  gateway)
    echo "🔓 MCP tool authorization OFF, at the gateway, for the poisoned weather tool. agentgateway lets every evil-mcp tool"
    echo "    through again. Re-ask the weather question and the agent gets chained into read_internal_config,"
    echo "    leaking the sentinel." ;;
  toolnames)
    echo "🔓 MCP tool authorization OFF for the poisoned weather tool. The rogue evil-mcp tools are back in the allow-list."
    echo "    Re-ask the weather question and the agent gets chained into read_internal_config, leaking the"
    echo "    sentinel." ;;
  *)
    echo "⚠️  The MCP tool restriction did not switch off. Wait a moment and try 'guard-mcp-off' again."; exit 1 ;;
esac
EOS
# DENIAL-OF-WALLET. The agent does not have to crash your cluster to hurt you; it can just
# run up the bill. On the community cluster there is no cap and the cost counter on BurritoBot climbs
# with no ceiling. The control is a per-agent budget at the gateway: once this cluster's spend crosses
# its cap, further requests are refused BEFORE the model is called, so a blocked request costs nothing.
cat > "$HOME/guard-budget-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "budget=on"; then
  echo "🛡️  BUDGET guard ON. This cluster now has a spend cap at the gateway. Keep chatting;"
  echo "    once the tab crosses the cap, BurritoBot refuses further requests BEFORE calling the model, so"
  echo "    the cost counter stops dead and a blocked request costs \$0. The agent is not down; the bill is"
  echo "    capped. That is denial-of-wallet stopped at the platform, not in the app."
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-budget-on' again."
fi
EOS
cat > "$HOME/guard-budget-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _px "budget=off"; then
  echo "Budget limits are now removed. You should be able to proceed with the lab."
  echo "(The meter keeps counting; only the limit is gone.)"
else
  echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-budget-off' again."
fi
EOS
# The KubeCon finale (#690): the room is invited to drive the public cluster's spend to its cap. COST_CAP_USD
# is $25 for the whole cluster, out of reach in a few minutes, so finale-cap-on lowers the cap live to what this
# cluster has already spent plus a little headroom (guard-proxy's /toggle?cost_cap=N, guard-proxy-agenticburn#23).
# The tally is kept, so the cap sits just above it. finale-cap-off restores COST_CAP_USD. cost-watch shows the
# spend against the cap, large, for the screen. Nothing lowers the cap until a presenter runs finale-cap-on.
cat > "$HOME/finale-cap-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
head="${1:-1.00}"
case "$head" in ''|*[!0-9.]*|*.*.*) echo "Usage: finale-cap-on [dollars of headroom, default 1.00]"; exit 2 ;; esac
c=(kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import json,urllib.request as u;g=lambda p:json.load(u.urlopen('http://localhost:8080'+p,timeout=10));s=g('/cost')['usd'];print(json.dumps({'spent':s,'cap':g('/toggle?cost_cap=%.4f'%(s+$head)).get('cost_cap_usd')}))")
_show "${c[@]}"
r="$("${c[@]}" 2>/dev/null | tail -1)"
spent="$(printf '%s' "$r" | python3 -c 'import json,sys;print("%.2f"%json.load(sys.stdin)["spent"])' 2>/dev/null)"
cap="$(printf '%s' "$r" | python3 -c 'import json,sys;print("%.2f"%json.load(sys.stdin)["cap"])' 2>/dev/null)"
if [ -z "$spent" ] || [ -z "$cap" ]; then
  echo "⚠️  The cap did not change: this guard-proxy has no runtime cost cap, or it could not be reached."; exit 1
fi
echo "🔥 Finale cap ON. This cluster has spent \$$spent; the cap is now \$$cap for the whole room."
echo "    Every turn counts toward it. When the room crosses it, BurritoBot stops calling the model for"
echo "    everyone, and a blocked request costs nothing. Watch it with: cost-watch. Put it back: finale-cap-off."
EOS
cat > "$HOME/finale-cap-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
case "$(_pxkey "cost_cap=default" cost_cap_usd)" in
  ""|missing) echo "⚠️  The cap did not change: this guard-proxy has no runtime cost cap, or it could not be reached."; exit 1 ;;
  *) echo "🔓 Finale cap OFF. The cluster is back on its normal backstop (COST_CAP_USD). BurritoBot answers again." ;;
esac
EOS
cat > "$HOME/cost-watch" <<'EOS'
#!/bin/bash
# Large spend-against-cap readout for the screen, every 2 seconds. Ctrl-C stops it.
source "$HOME/.guardlib"
c=(kubectl -n agent exec deploy/guard-proxy -- python3 -c \
  "import json,urllib.request as u;d=json.load(u.urlopen('http://localhost:8080/cost',timeout=10));print(json.dumps(d))")
cmd="$(_show "${c[@]}" 2>&1)"
while true; do
  r="$("${c[@]}" 2>/dev/null | tail -1)"
  line="$(printf '%s' "$r" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except ValueError: print("  waiting for guard-proxy..."); sys.exit()
s,c=d.get("usd",0),d.get("cap_usd",0)
bar="" if not c else "#"*min(40,int(40*s/c))+"."*max(0,40-int(40*s/c))
print("  SPENT  $%.4f\n  CAP    $%.2f\n  TURNS  %d\n  [%s]%s" % (s,c,d.get("requests",0),bar,"  CAP HIT: the kitchen is closed" if c and s>=c else ""))' 2>/dev/null)"
  printf '\033[H\033[2J%s   (every 2 seconds)\n\n  BurritoBot, this cluster\n\n%s\n\n  (Ctrl-C to stop)\n' "$cmd" "$line"
  sleep 2
done
EOS
# The KubeCon ending (#455, run-of-show segment 7): the on-topic guard. BurritoBot answers the menu, hours
# and locations and turns everything else back to the menu, before the model is called. It reports what the
# proxy says rather than assuming the flip worked, because a guard-proxy without the topic stage ignores the
# key and would otherwise print a confident ON for a guard that does not exist.
cat > "$HOME/guard-topic-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
case "$(_pxkey "topic=on" topic)" in
  True)
    echo "🛡️  On-topic guard ON. BurritoBot now sells burritos only: the menu, hours and locations get answered,"
    echo "    and anything else (salsa dance moves, a hot dog party, karaoke for a wedding) is turned back to the"
    echo "    menu, politely, before the model is called. Re-send your weirdest off-topic question." ;;
  "")
    echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-topic-on' again."; exit 1 ;;
  *)
    echo "⚠️  This guard-proxy has no on-topic guard, so nothing changed. It needs the guard-proxy build with"
    echo "    the topic stage."; exit 1 ;;
esac
EOS
cat > "$HOME/guard-topic-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
case "$(_pxkey "topic=off" topic)" in
  False)
    echo "🔓 On-topic guard OFF. BurritoBot will chat about anything again. Ask it for salsa dance moves." ;;
  missing)
    echo "🔓 This guard-proxy has no on-topic guard, so BurritoBot already chats about anything." ;;
  "")
    echo "⚠️  Could not reach the guard-proxy. Wait a moment and try 'guard-topic-off' again."; exit 1 ;;
  *)
    echo "⚠️  The guard-proxy still reports the on-topic guard on. Try 'guard-topic-off' again."; exit 1 ;;
esac
EOS
# The cluster fixes, beside the AI guards. Each prints its kubectl before it runs, as the AI guards do.
#
# guard-rbac-on: the CEO's record. agent-sa ships with get and list on every Secret in the namespace, so the bot
# reads ceo-personal-record. The fix is a Role that names the one Secret the agent reads, its own workshop-agent
# config; c5-scoped-role.yaml is that Role. guard-rbac-off puts back the shipped Role (c8-broad-role.yaml). The
# workshop-agent Application ignores the Role's rules, so Argo CD leaves the live Role as applied.
cat > "$HOME/guard-rbac-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
c=(kubectl apply -f "$HOME/challenges/c5-scoped-role.yaml")
_show "${c[@]}"
if "${c[@]}" >/dev/null 2>&1; then
  echo "🛡️  RBAC fix ON for the CEO's record. agent-sa's Role now reads one Secret by name, the agent's own"
  echo "    workshop-agent config, and lists none. Re-ask for the CEO's record: the read comes back Forbidden"
  echo "    from the Kubernetes API, so there is nothing for the bot to repeat."
else
  echo "⚠️  The Role did not change. Wait a moment and try 'guard-rbac-on' again."; exit 1
fi
EOS
cat > "$HOME/guard-rbac-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
c=(kubectl apply -f "$HOME/challenges/c8-broad-role.yaml")
_show "${c[@]}"
if "${c[@]}" >/dev/null 2>&1; then
  echo "🔓 RBAC fix OFF for the CEO's record. agent-sa can read every Secret in the namespace again, so the"
  echo "    CEO's record is back in reach."
else
  echo "⚠️  The Role did not change. Wait a moment and try 'guard-rbac-off' again."; exit 1
fi
EOS
# guard-admission-on: the support ticket's second tier. Kyverno's restrict-image-registries denies the Joker image
# the ticket asks deploy_app for. On sets its validationActions to Deny, off to Audit (admitted, only reported);
# both read the action back. Argo CD ignores /spec/validationActions, so the live flip stays.
cat > "$HOME/guard-admission-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
c=(kubectl patch validatingpolicy restrict-image-registries --type=json \
  -p '[{"op":"replace","path":"/spec/validationActions","value":["Deny"]}]')
g=(kubectl get validatingpolicy restrict-image-registries -o 'jsonpath={.spec.validationActions[0]}')
_show "${c[@]}"; "${c[@]}" >/dev/null 2>&1
_show "${g[@]}"
if [ "$("${g[@]}" 2>/dev/null)" = Deny ]; then
  echo "🛡️  Admission control ON for the support ticket. Kyverno's registry allow-list now denies any image"
  echo "    from outside the allowed registries, so the Joker the ticket asks for is refused at admission."
  echo "    Re-send the ticket ask: the deploy is denied, and the deny message names restrict-image-registries."
else
  echo "⚠️  restrict-image-registries is not in Deny. Wait a moment and try 'guard-admission-on' again."; exit 1
fi
EOS
cat > "$HOME/guard-admission-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
c=(kubectl patch validatingpolicy restrict-image-registries --type=json \
  -p '[{"op":"replace","path":"/spec/validationActions","value":["Audit"]}]')
g=(kubectl get validatingpolicy restrict-image-registries -o 'jsonpath={.spec.validationActions[0]}')
_show "${c[@]}"; "${c[@]}" >/dev/null 2>&1
_show "${g[@]}"
if [ "$("${g[@]}" 2>/dev/null)" = Audit ]; then
  echo "🔓 Admission control OFF for the support ticket. The registry allow-list only reports now, so the"
  echo "    Joker the ticket asks for is admitted and lands on the wall."
else
  echo "⚠️  restrict-image-registries is not in Audit. Wait a moment and try 'guard-admission-off' again."; exit 1
fi
EOS
# guard-agency-on: the support ticket's cluster fix at KubeCon (#775), least privilege (OWASP LLM06, Excessive Agency).
# HC-666's Joker comes from registry.burritobot.co, which Kyverno trusts, so admission passes it. This Role,
# c6-least-privilege-role.yaml, takes create and patch on Deployments and Pods away from agent-sa, so deploy_app comes
# back Forbidden whatever the image; the CEO's record stays scoped. guard-agency-off applies c5-scoped-role.yaml, the
# Role guard-rbac-on and guardrails-on leave. The 2-hour lab's second tier stays guard-admission-on, above.
# Both apply their Role on this cluster and on the other KubeCon cluster (_both in .guardlib, #1147), so the fix run
# from the private terminal reaches the public bot the room plays on. On the 2-hour lab's lone cluster, this one alone.
cat > "$HOME/guard-agency-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _both _apply c6-least-privilege-role.yaml; then
  echo "🛡️  Least privilege ON for the support ticket. agent-sa's Role no longer creates or changes Deployments"
  echo "    or Pods, so BurritoBot cannot deploy anything, from any registry. Re-send the ticket ask: deploy_app"
  echo "    comes back Forbidden from the Kubernetes API. The CEO's record stays out of reach."
else
  echo "⚠️  The Role did not change everywhere. Wait a moment and try 'guard-agency-on' again; it is safe to repeat."; exit 1
fi
EOS
cat > "$HOME/guard-agency-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
if _both _apply c5-scoped-role.yaml; then
  echo "🔓 Least privilege OFF for the support ticket. agent-sa can create Deployments and Pods again, so the"
  echo "    ticket's Joker lands. The CEO's record stays out of reach."
else
  echo "⚠️  The Role did not change everywhere. Wait a moment and try 'guard-agency-off' again; it is safe to repeat."; exit 1
fi
EOS
# guardrails-on / guardrails-off: the KubeCon breakout's one command for the four Kubernetes guardrails on both
# clusters (#774; _guardrails in .guardlib). An optional number of seconds waits between guardrails.
cat > "$HOME/guardrails-on" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
_guardrails on "${1:-0}"
EOS
cat > "$HOME/guardrails-off" <<'EOS'
#!/bin/bash
source "$HOME/.guardlib"
_guardrails off "${1:-0}"
EOS
chmod +x "$HOME/platform" "$HOME/guards-status" "$HOME/guards-on" "$HOME/guards-off" \
  "$HOME"/guardrails-on "$HOME"/guardrails-off \
  "$HOME"/guard-output-on "$HOME"/guard-output-off "$HOME"/guard-input-on "$HOME"/guard-input-off \
  "$HOME"/guard-mcp-on "$HOME"/guard-mcp-off "$HOME"/guard-budget-on "$HOME"/guard-budget-off \
  "$HOME"/guard-topic-on "$HOME"/guard-topic-off "$HOME"/guard-rbac-on "$HOME"/guard-rbac-off \
  "$HOME"/guard-admission-on "$HOME"/guard-admission-off "$HOME"/guard-agency-on "$HOME"/guard-agency-off \
  "$HOME"/finale-cap-on "$HOME"/finale-cap-off "$HOME"/cost-watch

# No banner. The shell opens on a prompt and nothing else (#342).
#
# What it used to print was seven lines of orientation a student had already been given by the lab page,
# plus two things they are specifically not supposed to know about: `guards-on`/`guards-off`, which is our
# abstraction rather than anything Kubernetes has, and `platform`, which Whitney asked to remove outright.
# The lab is the place that tells a student what to do; a shell that repeats it in different words is one
# more thing to read and one more chance for the two to disagree.
#
# The only surviving .motd write is the failure case, which fires when there is no ServiceAccount token and
# kubectl is therefore NOT configured. That is a broken terminal, and a broken terminal must say so.
cat > "$HOME/.bashrc" <<'BRC'
cat ~/.motd 2>/dev/null
cd "$HOME"
export PATH="$HOME:$PATH"
export PS1='\[\e[38;5;208m\]watch-it-burn\[\e[0m\]:\w$ '
BRC

# --- Browser IDE and notebook -------------------------------------------------------------------
#
# Both run as background processes beside ttyd, sharing /home/student, so a file written in any surface
# appears in the others immediately. Each gets a restart loop: a crashed IDE must not cost the attendee
# their shell, and a silently dead tab is worse than a restarting one because it reads as a broken lab.
run_service() {
  local name="$1"; shift
  (
    while true; do
      "$@" >>"$HOME/.session/${name}.log" 2>&1
      echo "[$(date -Is)] ${name} exited ($?), restarting in 3s" >>"$HOME/.session/${name}.log"
      sleep 3
    done
  ) &
}
mkdir -p "$HOME/.session" "$HOME/work"

# The console nginx runs in a SEPARATE pod here (it proxies to web-terminal:7681), unlike the sister
# repo where it was a sidecar sharing loopback. So these two have to bind 0.0.0.0 and are reachable
# from anywhere on the pod network, which means "bind to loopback, only nginx can reach it" is NOT
# available as an argument and neither surface may run unauthenticated.
#
# That matters more here than almost anywhere: this cluster deliberately runs hostile workloads. The
# whole exercise is an over-permissioned agent with shell and apply, plus villain images. An IDE with
# --auth none on that pod network is a root shell handed to the thing the workshop is about. So both
# reuse the terminal credential rather than inventing a second one; a credential that has to be
# distributed twice drifts, and one the attendee has already been handed costs nothing extra.
# The `:-` is load-bearing. This script runs under `set -u`, where ${VAR#pattern} on an UNSET variable
# is a hard error, not an empty expansion. Without the default, a cluster whose terminal-auth Secret is
# missing died right here with "TTYD_CREDENTIAL: unbound variable", which crash-looped the pod and made
# every no-credential branch below unreachable, including the warnings written for exactly that case.
# The Secret is declared optional in gitops/ai-layer/resources.yaml, so that path is reachable in
# practice: bootstrap_terminal_auth can fail and log "terminal-auth NOT created".
TTYD_CREDENTIAL="${TTYD_CREDENTIAL:-}"
CRED_PASS="${TTYD_CREDENTIAL#*:}"

if [[ -n "${CRED_PASS}" ]]; then
  PASSWORD="${CRED_PASS}" run_service ide /opt/code-server/bin/code-server \
    --bind-addr 0.0.0.0:8443 \
    --auth password \
    --disable-telemetry \
    --disable-update-check \
    "$HOME/work"
else
  echo "WARNING: no TTYD_CREDENTIAL; starting code-server with auth DISABLED on the pod network." >&2
  run_service ide /opt/code-server/bin/code-server \
    --bind-addr 0.0.0.0:8443 --auth none \
    --disable-telemetry --disable-update-check "$HOME/work"
fi

# JupyterLab. base_url matches the nginx location EXACTLY, because the prefix is KEPT on that route
# (see console.conf); getting it backwards yields a blank tab that still returns HTTP 200. The token is
# the same shared credential. disable_check_xsrf is required because the lab page frames this on a
# different path, and allow_origin is scoped to the console rather than left open.
run_service jupyter /opt/jupyter/bin/jupyter lab \
  --no-browser \
  --ip=0.0.0.0 --port=8888 \
  --ServerApp.base_url=/jupyter \
  --ServerApp.token="${CRED_PASS:-}" \
  --ServerApp.password= \
  --ServerApp.disable_check_xsrf=True \
  --ServerApp.allow_remote_access=True \
  --ServerApp.tornado_settings="{'headers': {'Content-Security-Policy': \"frame-ancestors 'self'\"}}" \
  --ServerApp.root_dir="$HOME/work"

# --- No workshop tutor, deliberately -----------------------------------------------------------
#
# A second ttyd on 7682 used to run the Claude Code CLI as an in-workbench tutor, with a nudge watcher
# and a small HTTP server on 7683 feeding a banner on the lab page.
#
# It is gone because clicking it showed an attendee Claude Code's "Trust this folder?" prompt. The
# suppression it relied on is undocumented per-project config internal to that CLI, so even when
# corrected a future release can bring the prompt back, and it would appear live in front of the room.
# No attendee-facing surface may run a coding-agent CLI or show its UI.
#
# The problem it addressed is real and unsolved: one instructor cannot hand-diagnose a room working at
# its own pace. A replacement must be purpose-built, taking a question and rendering a server-side
# answer, with no terminal and nothing that can raise a dialog. See issue #89.

# -W writable (interactive); -b serves under /terminal so the console frontend can proxy it on a subpath.
#
# The shell is NO LONGER wrapped in script(1). That transcript existed solely so the tutor could read
# what the attendee had typed; with the tutor gone (issue #89) nothing consumes it, and it was recording
# every keystroke of every session, including anything pasted into the shell, to a file on the pod.
# Keeping a verbatim record of what people type, for no reader, is a liability rather than a feature.
#
# AUTHENTICATION. This used to read "auth/exposure are handled upstream by the per-attendee router".
# That was wrong, and it was measured wrong on the sister Packt fleet on 2026-07-25: the cluster NLB
# answers on its BARE IP with no Host header, so anything the router enforces is bypassed by dialling
# the load balancer directly. A router in front of a publicly-reachable upstream is not a control, and
# a non-guessable hostname is not a credential. On 2026-07-23 an attendee reached the instructor's
# cluster through its terminal URL because of exactly this gap.
#
# So the credential is enforced HERE, at ttyd, which is the only place upstream reachability cannot
# route around. TTYD_CREDENTIAL ("user:password") arrives from the optional `terminal-auth` Secret,
# created per-cluster by the provisioning bootstrap with a random password.
if [[ -n "${TTYD_CREDENTIAL:-}" ]]; then
  exec ttyd -p 7681 -W -b /terminal -c "${TTYD_CREDENTIAL}" \
    -t fontSize=14 -t 'theme={"background":"#0f1117"}' \
    bash --rcfile "$HOME/.bashrc"
fi

# No credential supplied. Run open so an existing cluster does not break on rollout, but say so loudly
# in the pod log: an unauthenticated terminal on an internet-facing NLB is a shell anyone can open.
echo "WARNING: no TTYD_CREDENTIAL set. This terminal is UNAUTHENTICATED and reachable by anyone who" >&2
echo "WARNING: can reach the load balancer. Create the 'terminal-auth' Secret to close it." >&2
exec ttyd -p 7681 -W -b /terminal -t fontSize=14 -t 'theme={"background":"#0f1117"}' \
  bash --rcfile "$HOME/.bashrc"
