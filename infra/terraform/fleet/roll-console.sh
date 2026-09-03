#!/usr/bin/env bash
# ABOUTME: Push web changes to every live cluster: ArgoCD hard-refresh, WAIT for the ConfigMap to carry
# ABOUTME: the expected marker, then cycle the console pod. The wait is the point.
#
# The console ConfigMaps have FIXED names, so Argo CD updates their CONTENT in place without changing the
# pod spec and nginx keeps serving whatever it read at startup. A pod cycle is required. The earlier
# version of this slept a flat 12s before cycling, which is a race: when Argo took longer, the pod
# restarted on the OLD content and the cluster looked rolled-out while serving stale config. That is
# exactly how r1-1 ended up running a reverted nginx gate while r2-2 ran the current one.
set -uo pipefail
PROFILE=accen-dev; REGION=us-west-2
MARKER="${1:-}"   # a string that MUST appear in the console ConfigMap before we cycle
if [[ -z "${MARKER}" ]]; then
    cat >&2 <<'USAGE'
usage: roll-console.sh "<marker string from the change you just pushed>"

  Rolls the web layer to every live cluster and waits for the change to actually
  arrive before restarting anything. The marker is any literal string unique to
  the commit, e.g. a new nginx location line or a distinctive comment.

  Without a marker it falls back to a flat 12s sleep, which is a race and is how
  a cluster ends up serving config it already shows as synced.
USAGE
fi
SP="$(mktemp -d -t roll-console.XXXX)"
trap 'rm -rf "${SP}"' EXIT
for c in $(AWS_PROFILE=$PROFILE aws eks list-clusters --region $REGION --query 'clusters[]' --output text | tr '\t' '\n'); do
    KCFG="$SP/${c}.kubeconfig"
    AWS_PROFILE=$PROFILE aws eks update-kubeconfig --kubeconfig "$KCFG" --name "$c" --region $REGION >/dev/null 2>&1 || { echo "  $c: no kubeconfig"; continue; }
    CTX="$(KUBECONFIG=$KCFG kubectl config current-context 2>/dev/null)"
    case "$CTX" in *"$c"*) : ;; *) echo "  $c: CONTEXT MISMATCH ($CTX), skipping"; continue ;; esac
    K=(env KUBECONFIG="$KCFG" AWS_PROFILE="$PROFILE" kubectl --context "$CTX")
    "${K[@]}" -n argocd annotate app ai-layer argocd.argoproj.io/refresh=hard --overwrite >/dev/null 2>&1
    if [[ -n "$MARKER" ]]; then
        ok=0
        for _ in $(seq 1 40); do   # up to ~200s
            if "${K[@]}" -n agent get cm console-conf console-src -o yaml 2>/dev/null | grep -qF -- "$MARKER"; then ok=1; break; fi
            sleep 5
        done
        [[ $ok -eq 1 ]] || { echo "  $c: marker never arrived, NOT cycling (would bake stale config)"; continue; }
    else
        sleep 12
    fi
    "${K[@]}" -n agent delete pod -l app.kubernetes.io/name=console >/dev/null 2>&1
    echo "  $c: synced + console cycled"
done
