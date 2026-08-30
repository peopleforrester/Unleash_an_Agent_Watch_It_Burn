#!/usr/bin/env bash
# ABOUTME: Pre-flight drift audit: confirms one live cluster carries every shipped fix (guards, model tier,
# ABOUTME: terminal image, credential split, web pages, runtime security, C3 bait) in a single line of output.
#
# Usage:  verify/fleet-drift-audit.sh <cluster-name>
#         for c in $(aws eks list-clusters --region us-west-2 --query 'clusters[]' --output text); do
#             verify/fleet-drift-audit.sh "$c"; done
#
# WHY: the fleet is mutated through several channels that do NOT all flow from git. ConfigMap content
# arrives via Argo CD, guard-proxy env has to be patched live (Argo CD ignoreDifferences excludes it, see
# docs/GOTCHAS-FLEET-AND-DELIVERY.md), images land only when a pod is cycled, and the terminal credential is
# a Secret created at bootstrap. A cluster can therefore be "Synced" and still be missing three fixes. This
# reads the LIVE state of each one rather than trusting sync status.
#
# Read the output as: every field should match the expected column below.
#   guards_budget=True   cost_cap=25.0   tier=nova   tokenFile=1   gbudget=1   gstatus=1
#   cred=sprouts (roster clusters) | cred=agentic (attendee pool)
#   lab_tour=1  lab_hints=9  lab_ddcreds=2  lab_whereami=1  lab_nopoller=0
#   bb_logo=1   bb_caprow=1  bb_greet=1     brief=1
#   tetragon_apps=0   ka_annot=enabled
#   c3=READABLE on burn (R1) clusters, c3=DENIED everywhere else
#
# lab_nopoller MUST be 0: a non-zero count means the focus-stealing terminal poller is back.
set -uo pipefail
c="$1"
K=$(mktemp); AWS_PROFILE=accen-dev aws eks update-kubeconfig --kubeconfig "$K" --name "$c" --region us-west-2 >/dev/null 2>&1
export KUBECONFIG=$K AWS_PROFILE=accen-dev
kubectl config current-context 2>/dev/null | grep -q "$c" || { echo "$c CTX-MISMATCH"; exit 1; }
f=""
ok(){ f="$f $1=$2"; }
# 1 proxy: budget guard + cap + nova tier
g=$(kubectl -n agent exec deploy/guard-proxy -- python3 -c "import json,urllib.request;d=json.load(urllib.request.urlopen('http://localhost:8080/guards',timeout=8));print('budget' in d)" 2>/dev/null|tail -1)
ok guards_budget "${g:-ERR}"
cap=$(kubectl -n agent exec deploy/guard-proxy -- python3 -c "import json,urllib.request;print(json.load(urllib.request.urlopen('http://localhost:8080/cost',timeout=8)).get('cap_usd'))" 2>/dev/null|tail -1)
ok cost_cap "${cap:-ERR}"
ok tier "$(kubectl -n agent exec deploy/guard-proxy -- sh -c 'echo $MODEL_TIER' 2>/dev/null|tail -1)"
# 2 terminal image: tokenFile, budget+status scripts
ok tokenFile "$(kubectl -n agent exec deploy/web-terminal -- sh -c 'grep -c tokenFile /home/student/.kube/config 2>/dev/null||echo 0' 2>/dev/null|tail -1)"
ok gbudget "$(kubectl -n agent exec deploy/web-terminal -- sh -c 'test -x /home/student/guard-budget-on&&echo 1||echo 0' 2>/dev/null|tail -1)"
ok gstatus "$(kubectl -n agent exec deploy/web-terminal -- sh -c 'test -x /home/student/guards-status&&echo 1||echo 0' 2>/dev/null|tail -1)"
# 3 credential split
ok cred "$(kubectl -n agent get secret terminal-auth -o jsonpath='{.data.TTYD_CREDENTIAL}' 2>/dev/null|base64 -d 2>/dev/null|cut -d: -f1)"
# 4 web pages
L=/usr/share/nginx/html/lab.html; B=/usr/share/nginx/html/burritbot.html
ok lab_tour "$(kubectl -n agent exec deploy/console -- grep -c 'What you were just handed' $L 2>/dev/null|tail -1)"
ok lab_hints "$(kubectl -n agent exec deploy/console -- grep -c 'details class=.hint' $L 2>/dev/null|tail -1)"
ok lab_ddcreds "$(kubectl -n agent exec deploy/console -- grep -c 'ddcreds' $L 2>/dev/null|tail -1)"
ok lab_whereami "$(kubectl -n agent exec deploy/console -- grep -c 'Where you are' $L 2>/dev/null|tail -1)"
ok lab_nopoller "$(kubectl -n agent exec deploy/console -- sh -c "grep -c 'setInterval(' $L 2>/dev/null||echo 0" 2>/dev/null|tail -1)"
ok bb_logo "$(kubectl -n agent exec deploy/console -- grep -c 'Redesigned 2026-08-30' $B 2>/dev/null|tail -1)"
ok bb_caprow "$(kubectl -n agent exec deploy/console -- grep -c 'id=\"caprow\"' $B 2>/dev/null|tail -1)"
ok bb_greet "$(kubectl -n agent exec deploy/console -- grep -c 'burrito-ordering app' $B 2>/dev/null|tail -1)"
ok brief "$(kubectl -n agent exec deploy/console -- sh -c 'test -f /usr/share/nginx/html/brief.html&&echo 1||echo 0' 2>/dev/null|tail -1)"
# 5 runtime security
ok tetragon_apps "$(kubectl -n argocd get applications -o name 2>/dev/null|grep -c tetragon)"
ok ka_annot "$(kubectl -n agent get pod -l app=workshop-mcp -o jsonpath='{.items[0].metadata.annotations.kubearmor-policy}' 2>/dev/null)"
# 6 C3 bait (baked): burn=readable, enforced=denied
bait=$(kubectl -n agent exec deploy/workshop-mcp -- sh -c 'cat /tmp/burrito-data/config/legacy/secret-sauce-recipe.conf 2>&1|head -1' 2>/dev/null|tail -1)
case "$bait" in *"Permission denied"*) ok c3 DENIED;; *"Hex & Cauldron"*) ok c3 READABLE;; *) ok c3 "OTHER";; esac
echo "$c$f"
