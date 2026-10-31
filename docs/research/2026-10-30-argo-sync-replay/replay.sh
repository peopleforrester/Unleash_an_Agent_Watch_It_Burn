#!/usr/bin/env bash
# ABOUTME: Runs #679 through Argo CD v3.5.2's own sync and diff code against a real kube-apiserver (envtest's, no
# ABOUTME: cluster, no containers): the Agent's frozen tools array, guard-proxy's frozen env order, and both fixes.
#
# Usage: bash docs/research/2026-10-30-argo-sync-replay/replay.sh
#
# Needs go (1.26 or later), git, curl, jq, python3 with PyYAML, sha512sum, and network for the first run. Everything it
# fetches or builds goes under the repo's gitignored tmp/argo-sync-replay: envtest v1.34.1's etcd, kube-apiserver and
# kubectl (checked against the SHA-512 controller-tools publishes in envtest-releases.yaml), and argo-cd v3.5.2's
# gitops-engine tree, which go.mod's replace points at. It starts its own etcd and apiserver on free localhost ports
# with a kubeconfig of its own, touches no other cluster, and stops both when it exits. Each scenario prints PASS or
# FAIL; any FAIL exits 1. verify/test_agent_tools_sync.py ports what this runs and holds the same results offline.
#
# What a sync does here: the target, as normalizeTargetResources makes it (RespectIgnoreDifferences=true) or as
# committed (without it), server-side applied with field manager argocd-controller and force-conflicts, which is the
# apply gitops-engine runs for ServerSideApply=true. Whether the result reads Synced is util/argo/diff.StateDiff, the
# structured merge diff Argo CD uses for such an Application.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../../.." && pwd)"
WORK="${REPO}/tmp/argo-sync-replay"
ENVTEST_URL="https://github.com/kubernetes-sigs/controller-tools/releases/download/envtest-v1.34.1/envtest-v1.34.1-linux-amd64.tar.gz"
ENVTEST_SHA512="c5e7c237ae18a8c65d0df1214b864ecd19aa9ff4f1383dbd477c202546d778c0f74efe15750ec38f57d8de26ba17cd62f404446cdd3c975399a5d4589de35cdd"
ARGOCD_TAG="v3.5.2"

missing=()
for t in go git curl jq python3 sha512sum tar; do command -v "${t}" >/dev/null 2>&1 || missing+=("${t}"); done
python3 -c 'import yaml' 2>/dev/null || missing+=("PyYAML")
if [[ "${#missing[@]}" -gt 0 ]]; then
    printf 'argo-sync-replay cannot run; missing: %s\n' "${missing[*]}" >&2; exit 1
fi
mkdir -p "${WORK}"

# ---- the tools --------------------------------------------------------------------------------------------------
if [[ ! -x "${WORK}/envtest/kube-apiserver" ]]; then
    curl -fsSL --retry 3 -o "${WORK}/envtest.tgz" "${ENVTEST_URL}"
    echo "${ENVTEST_SHA512}  ${WORK}/envtest.tgz" | sha512sum -c --quiet - \
        || { echo "envtest tarball does not match its published SHA-512" >&2; exit 1; }
    mkdir -p "${WORK}/envtest"
    tar -xzf "${WORK}/envtest.tgz" -C "${WORK}/envtest" --strip-components=2
fi
if [[ ! -d "${WORK}/argo-cd/gitops-engine" ]]; then
    rm -rf "${WORK}/argo-cd"
    git clone -q --depth 1 --branch "${ARGOCD_TAG}" --filter=blob:none --sparse \
        https://github.com/argoproj/argo-cd.git "${WORK}/argo-cd"
    git -C "${WORK}/argo-cd" sparse-checkout set gitops-engine
fi
BIN="${WORK}/argo-sync-replay"
( cd "${HERE}" && go build -o "${BIN}" . )
KUBECTL="${WORK}/envtest/kubectl"

# ---- a kube-apiserver of its own --------------------------------------------------------------------------------
RUN="$(mktemp -d "${WORK}/run.XXXX")"
read -r ETCD_C ETCD_P API < <(python3 -c 'import socket
ss=[socket.socket() for _ in range(3)]
[s.bind(("127.0.0.1",0)) for s in ss]
print(*[s.getsockname()[1] for s in ss])')
PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "${p}" 2>/dev/null || true; done; wait 2>/dev/null || true; rm -rf "${RUN}"; }
trap cleanup EXIT
openssl req -x509 -newkey rsa:2048 -nodes -keyout "${RUN}/sa.key" -out "${RUN}/sa.crt" -days 1 -subj /CN=sa 2>/dev/null
echo "replay-token,admin,admin,system:masters" >"${RUN}/tokens.csv"
"${WORK}/envtest/etcd" --data-dir "${RUN}/etcd" --listen-client-urls "http://127.0.0.1:${ETCD_C}" \
    --advertise-client-urls "http://127.0.0.1:${ETCD_C}" --listen-peer-urls "http://127.0.0.1:${ETCD_P}" \
    >"${RUN}/etcd.log" 2>&1 &
PIDS+=($!)
"${WORK}/envtest/kube-apiserver" --etcd-servers "http://127.0.0.1:${ETCD_C}" --secure-port "${API}" \
    --bind-address 127.0.0.1 --cert-dir "${RUN}/certs" --token-auth-file "${RUN}/tokens.csv" --authorization-mode RBAC \
    --service-account-issuer https://argo-sync-replay --service-account-key-file "${RUN}/sa.crt" \
    --service-account-signing-key-file "${RUN}/sa.key" --service-cluster-ip-range 10.0.0.0/24 \
    --disable-admission-plugins ServiceAccount >"${RUN}/apiserver.log" 2>&1 &
PIDS+=($!)
KCFG="${RUN}/kubeconfig"
cat >"${KCFG}" <<EOF
apiVersion: v1
kind: Config
clusters: [{name: replay, cluster: {server: "https://127.0.0.1:${API}", insecure-skip-tls-verify: true}}]
users: [{name: admin, user: {token: replay-token}}]
contexts: [{name: argo-sync-replay, context: {cluster: replay, user: admin}}]
current-context: argo-sync-replay
EOF
K() { KUBECONFIG="${KCFG}" "${KUBECTL}" --context argo-sync-replay "$@"; }
for _ in $(seq 60); do K get --raw /readyz >/dev/null 2>&1 && break; sleep 1; done
K get --raw /readyz >/dev/null || { echo "the apiserver did not come up; see ${RUN}/apiserver.log" >&2; exit 1; }
K create namespace agent >/dev/null
K apply -f - >/dev/null <<'EOF'
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: {name: agents.kagent.dev}
spec:
  group: kagent.dev
  names: {kind: Agent, plural: agents, singular: agent, listKind: AgentList}
  scope: Namespaced
  versions:
    - name: v1alpha2
      served: true
      storage: true
      schema: {openAPIV3Schema: {type: object, x-kubernetes-preserve-unknown-fields: true}}
EOF
K wait --for condition=established crd/agents.kagent.dev --timeout=60s >/dev/null

# ---- the inputs, from the repo as committed ------------------------------------------------------------------------
python3 - "${REPO}" "${RUN}" <<'PY'
import copy, json, pathlib, sys, yaml
repo, run = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
def doc(rel, kind, name):
    return next(d for d in yaml.safe_load_all((repo / rel).read_text()) if d and d.get("kind") == kind
                and d["metadata"]["name"] == name)
def track(d, app):
    d = copy.deepcopy(d)
    d["metadata"]["namespace"] = "agent"
    g = d["apiVersion"].rpartition("/")[0]
    d["metadata"].setdefault("annotations", {})["argocd.argoproj.io/tracking-id"] = \
        f"{app}:{g}/{d['kind']}:agent/{d['metadata']['name']}"
    return d
def ignores(app_file, kind, name):
    # The chart's c7Control guard sits in YAML comments, so the file as read is the toolnames render.
    app = yaml.safe_load((repo / "gitops/bootstrap/apps" / app_file).read_text())
    return [i for i in app["spec"]["ignoreDifferences"] if i.get("kind") == kind and i.get("name") in (None, name)]
def put(name, obj):
    (run / name).write_text(json.dumps(obj))
proxy = track(doc("gitops/ai-layer/resources.yaml", "Deployment", "guard-proxy"), "ai-layer")
put("gp-git.json", proxy)
old = copy.deepcopy(proxy)
c = old["spec"]["template"]["spec"]["containers"][0]
c["env"] = [e for e in c["env"] if e["name"] != "CONSOLE_ORIGIN"]
put("gp-old.json", old)
gi = ignores("ai-layer.yaml", "Deployment", "guard-proxy")
put("gp-ign.json", gi)
put("gp-exprs.json", [e for i in gi for e in i["jqPathExpressions"]])
put("gp-order.json", [e["name"] for e in proxy["spec"]["template"]["spec"]["containers"][0]["env"]])
agent = doc("gitops/ai-layer-agent/workshop-agent.yaml", "Agent", "workshop-agent")
stale = copy.deepcopy(agent)
for t in stale["spec"]["declarative"]["tools"]:
    if t["mcpServer"]["name"] == "workshop-mcp":
        t["mcpServer"]["toolNames"] = [x for x in t["mcpServer"]["toolNames"] if x != "read_support_ticket"]
# Before #679 the Agent was ai-layer's, with these two ignores and RespectIgnoreDifferences=true.
evil = '.spec.declarative.tools[] | select(.mcpServer.name == "evil-mcp") | .mcpServer.toolNames'
old_ign = [{"group": "kagent.dev", "kind": "Agent", "name": "workshop-agent",
            "jqPathExpressions": [evil, ".spec.declarative.modelConfig"]}]
put("ag-git-old.json", track(agent, "ai-layer")); put("ag-stale-old.json", track(stale, "ai-layer"))
put("ag-ign-old.json", old_ign); put("ag-exprs-old.json", old_ign[0]["jqPathExpressions"])
put("ag-git.json", track(agent, "ai-layer-agent"))
put("ag-ign.json", ignores("ai-layer-agent.yaml", "Agent", "workshop-agent"))
PY

fails=0
expect() { # name, got, want
    if [[ "$2" == "$3" ]]; then echo "  PASS  $1"; else echo "  FAIL  $1 (got ${2}, want ${3})"; fails=$((fails + 1)); fi
}
apply() { K apply --server-side --force-conflicts --field-manager=argocd-controller -f "$1" >/dev/null; }
live() { K -n agent get "$1" -o json >"${RUN}/live.json"; }
state() { "${BIN}" diff "${KCFG}" "$1" "${RUN}/live.json" "$2"; }
sync_respecting() { # target, exprs file: normalizeTargetResources, then the apply
    jq -n --slurpfile t "$1" --slurpfile l "${RUN}/live.json" --slurpfile e "$2" '{target:$t[0], live:$l[0], exprs:$e[0]}' \
        >"${RUN}/in.json"
    "${BIN}" norm "${RUN}/in.json" >"${RUN}/patched.json"
    apply "${RUN}/patched.json"
}
env_names() { jq -c '[.spec.template.spec.containers[0].env[].name]' "${RUN}/live.json"; }
env_value() { jq -r --arg n "$1" '.spec.template.spec.containers[0].env[] | select(.name == $n) | .value' "${RUN}/live.json"; }
GIT_ORDER="$(jq -c . "${RUN}/gp-order.json")"

echo "== guard-proxy: a6af457's CONSOLE_ORIGIN through Argo, with a live MODEL_TIER toggle (ai-layer, RespectIgnoreDifferences) =="
apply "${RUN}/gp-old.json"
K -n agent set env deploy/guard-proxy -c proxy MODEL_TIER=sonnet >/dev/null
live deploy/guard-proxy
expect "before the sync: OutOfSync" "$(state "${RUN}/gp-git.json" "${RUN}/gp-ign.json")" OutOfSync
sync_respecting "${RUN}/gp-git.json" "${RUN}/gp-exprs.json"; live deploy/guard-proxy
expect "after one sync: Synced" "$(state "${RUN}/gp-git.json" "${RUN}/gp-ign.json")" Synced
expect "CONSOLE_ORIGIN landed in git's place" "$(env_names)" "${GIT_ORDER}"
expect "the live MODEL_TIER toggle survived the sync" "$(env_value MODEL_TIER)" sonnet

echo "== guard-proxy: the same entry added live with kubectl set env, which appends (the 2026-10-29 stopgap) =="
K -n agent delete deploy guard-proxy >/dev/null
apply "${RUN}/gp-old.json"
K -n agent set env deploy/guard-proxy -c proxy CONSOLE_ORIGIN=https://start.burritobot.co >/dev/null
live deploy/guard-proxy
expect "CONSOLE_ORIGIN is live, appended last" "$(jq -r '.[-1]' <<<"$(env_names)")" CONSOLE_ORIGIN
expect "and the Deployment reads OutOfSync on order alone" "$(state "${RUN}/gp-git.json" "${RUN}/gp-ign.json")" OutOfSync
for n in 1 2; do
    sync_respecting "${RUN}/gp-git.json" "${RUN}/gp-exprs.json"; live deploy/guard-proxy
    expect "sync ${n}: still OutOfSync (the sync applies the live order)" \
        "$(state "${RUN}/gp-git.json" "${RUN}/gp-ign.json")" OutOfSync
done
expect "and CONSOLE_ORIGIN is still last" "$(jq -r '.[-1]' <<<"$(env_names)")" CONSOLE_ORIGIN
expect "while a server dry run of git's Deployment puts it in git's place (what the diff predicts)" \
    "$(K apply --server-side --force-conflicts --field-manager=argocd-controller --dry-run=server -o json \
        -f "${RUN}/gp-git.json" | jq -c '[.spec.template.spec.containers[0].env[].name]')" "${GIT_ORDER}"

echo "== guard-proxy: fleet.sh repair_env_order's rewrite, then a sync =="
python3 - "${RUN}/live.json" "${RUN}/gp-order.json" >"${RUN}/reorder.json" <<'PY'
import json, sys
live, order = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
env = live["spec"]["template"]["spec"]["containers"][0]["env"]
want = [e for n in order for e in env if e["name"] == n] + [e for e in env if e["name"] not in order]
print(json.dumps([{"op": "test", "path": "/spec/template/spec/containers/0/name", "value": "proxy"},
                  {"op": "replace", "path": "/spec/template/spec/containers/0/env", "value": want}]))
PY
K -n agent patch deploy guard-proxy --type json -p "$(cat "${RUN}/reorder.json")" >/dev/null
live deploy/guard-proxy
sync_respecting "${RUN}/gp-git.json" "${RUN}/gp-exprs.json"; live deploy/guard-proxy
expect "after the reorder and a sync: Synced" "$(state "${RUN}/gp-git.json" "${RUN}/gp-ign.json")" Synced
expect "in git's order" "$(env_names)" "${GIT_ORDER}"

echo "== the Agent before #679: in ai-layer, which respects its evil-mcp toolNames ignore on sync =="
apply "${RUN}/ag-stale-old.json"; live agent/workshop-agent
tools() { jq -c '[.spec.declarative.tools[] | select(.mcpServer.name == "workshop-mcp") | .mcpServer.toolNames[]] | length' \
    "${RUN}/live.json"; }
expect "the live Agent has the stale eleven" "$(tools)" 11
expect "git's twelve read OutOfSync" "$(state "${RUN}/ag-git-old.json" "${RUN}/ag-ign-old.json")" OutOfSync
for n in 1 2; do
    sync_respecting "${RUN}/ag-git-old.json" "${RUN}/ag-exprs-old.json"; live agent/workshop-agent
    expect "sync ${n}: read_support_ticket never lands (eleven)" "$(tools)" 11
done
expect "and the Agent is still OutOfSync" "$(state "${RUN}/ag-git-old.json" "${RUN}/ag-ign-old.json")" OutOfSync

echo "== the Agent since #679: ai-layer-agent, which does not respect its ignores on sync =="
apply "${RUN}/ag-git.json"; live agent/workshop-agent
expect "one sync applies git's twelve" "$(tools)" 12
expect "and the Agent reads Synced" "$(state "${RUN}/ag-git.json" "${RUN}/ag-ign.json")" Synced
K -n agent patch agent workshop-agent --type json \
    -p '[{"op":"replace","path":"/spec/declarative/tools/1/mcpServer/toolNames","value":["get_weather"]}]' >/dev/null
live agent/workshop-agent
expect "a student's guard-mcp-on (evil-mcp narrowed to get_weather) still reads Synced, so selfHeal leaves it" \
    "$(state "${RUN}/ag-git.json" "${RUN}/ag-ign.json")" Synced

echo
if [[ "${fails}" -gt 0 ]]; then echo "${fails} scenario check(s) FAILED"; exit 1; fi
echo "All argo-sync-replay scenarios match."
