<!-- ABOUTME: Facilitator runbook for the IMDS credential-theft beat (#113, ASI03): a pod on the community
     ABOUTME: cluster steals the node instance-role creds via 169.254.169.254 and names the node role and its AWS account. -->

# Facilitator runbook: IMDS credential theft (the blast radius leaves the cluster)

A presenter-driven beat on the **community cluster** (`attackme`), the unguarded spectacle. BurritoBot is
asked something innocent ("check why the order service is slow"); as it looks around it reads instance
metadata, obtains the **node** role, and can then call AWS from inside the pod. One request turns a
container compromise into a cloud-account compromise. OWASP Agentic calls this **ASI03, Identity and
Privilege Abuse**, the same id the lab names in Challenge 8.

This is **not** an attendee step. Every student cluster blocks it (that is the lesson), so there is nothing
for a phone to do; it is watched on the screen, like the Challenge 4 fork bomb on our box. Run it on the
community cluster to show the theft, then against an admin or attendee cluster to show the same request
refused.

## Why it lands here and nowhere else

| Control | What it does | Community (`burn`) | admin / attendee |
|---|---|---|---|
| Node IMDSv2 hop limit (`var.imds_hop_limit`, cluster `main.tf`) | a hop limit of 1 kills a pod's packet one hop short of node IMDS | **2** (fleet.sh sets it for the `community` role, #113): pods reach IMDS | **1**: pods cannot reach IMDS |
| `agent-deny-imds` ClusterNetworkPolicy (`policies/cluster-network-policies/`) | an Admin-tier `Deny` of `169.254.169.254/32` from the agent namespace | **absent** (the burn profile ships no defence) | present on admin and attendee (full too) |
| EKS Pod Identity scope | binds the agent a Bedrock-only role at `169.254.170.23`, a different endpoint | unchanged | unchanged |

So on the community cluster both IMDS controls are deliberately off; everywhere else both hold. Pod Identity
is untouched either way, because it never used IMDS, so BurritoBot still reaches Bedrock on every cluster.

## Run the theft (copy-ready)

```bash
export CONTEXT=<kube-context>              # the community/attackme cluster
CONTEXT="$CONTEXT" challenges/imds-node-creds/steal-node-creds.sh
```

The script execs into the agent's tool pod (`workshop-mcp`, which is what runs `run_shell`), requests an
IMDSv2 token, reads the node role name and its credentials, then reads the node **instance-identity
document** with the stolen token to name the AWS account and region the node role lives in. On the
community cluster it prints the node instance-role name and that account and region, the pivot off the
node into a real AWS account. It does **not** call `aws sts get-caller-identity`: the minimal tool-pod
image carries no aws CLI, so an aws call would only print `aws: not found` on stage, and the identity
document proves the same cloud-account reach using the stolen token (#748). It only reads; it changes nothing.

Then point it at a guarded cluster to show the control:

```bash
CONTEXT=<an-admin-or-attendee-context> challenges/imds-node-creds/steal-node-creds.sh
# IMDS: BLOCKED. No IMDSv2 token (the node is one hop out of reach). The theft FAILS here.
```

## The contrast with Challenge 8's probe

Challenge 8's student probe (`~/challenges/cloud-credential-probe.yaml`, run on an attendee cluster) ends
with the same two IMDS lines reading `BLOCKED`, and the lab explains "the node already refuses to answer a
pod (hop limit of 1)" plus the readable `agent-deny-imds` rule. This beat is that probe's verdict turned
inside out: on the one cluster where both controls are off, IMDS answers and the node role is yours. Show
the probe's `BLOCKED` first (the control working), then this on the community cluster (the control absent).

## The fix, stated out loud

- **Infra, already true on every non-burn cluster:** the node hop limit of 1 keeps pods off IMDS, the
  `agent-deny-imds` ClusterNetworkPolicy denies `169.254.169.254/32` in words, and EKS Pod Identity hands
  the agent a narrowly scoped role instead of the broad node role. GKE Agent Sandbox now blocks the
  metadata server by default; Hugging Face lists "IMDS access not blocked at pod level" among its failed
  controls. The community cluster has the first two turned off on purpose.

## Gotchas

- **Node role scope.** The drama is the stolen credential being a *node* role in a real AWS account,
  which is instantly legible. On a stock EKS node role the stolen credential can read ECR and describe the cluster. It cannot
  list S3 or read Secrets Manager, so do not promise S3 or Secrets on stage unless the node role has been
  widened for the demo. The lesson is the boundary crossing itself. A disposable cluster's node role is fine
  to leave as it is.
- **Pod Identity uses a different endpoint.** `169.254.170.23` (the container-credentials endpoint Pod
  Identity uses) is reachable on every cluster, and this theft does not touch it. If someone conflates them,
  show that the script targets `169.254.169.254` and that Bedrock still works on the guarded clusters.
- **Stale eBPF.** As with the Challenge 1 egress wall, an already-running pod can lag a policy change; a
  fresh `workshop-mcp` pod always reflects the current node hop limit.

## Not yet run on a cluster

**Validated live by the coordinator (recorded on #717).** On 2026-11-01, on the rebuilt
`watch-it-burn-community` node at IMDS hop limit 2, `CONTEXT=<community-ctx>
challenges/imds-node-creds/steal-node-creds.sh` from the tool pod REACHED IMDS and the node handed out its
instance-role name, so the theft lands (ASI03). On 2026-10-31 the same script against the guarded
`watch-it-burn-private` node (hop limit 1) printed `IMDS: BLOCKED`, and `verify/test_bedrock_profile_live.py`
confirmed Pod Identity / Bedrock still answers on the community cluster at hop limit 2.

**Still owed on a build with AWS access.** The 2026-11-01 run used the pre-#748 script, whose closing line
was the (now removed) `aws sts get-caller-identity`, so the current script's instance-identity-document
output (the node role name plus its AWS account and region) has not yet been seen live; and `IMDS: BLOCKED`
has so far been shown only on the guarded cluster, not a fresh attendee cluster. At the next
community/attendee bring-up (`fleet.sh instructors up community`), re-run `CONTEXT=<community-ctx>
challenges/imds-node-creds/steal-node-creds.sh` and confirm it names the node role and its AWS account and
region, then run it against a fresh attendee cluster and confirm `IMDS: BLOCKED`. This is the live half of
`verify/test_imds_credential_theft.py` (offline today).
