*Purpose: provision N attendee spoke EKS clusters in parallel from the template and register each one to the hub ArgoCD.*

# Spoke clusters

One **EKS cluster per attendee** (rev3, no vCluster). Each spoke runs the full
per-attendee IDP stack and is registered to the hub ArgoCD as a sync destination.
`cluster.yaml` is a **template**, `ATTENDEE_ID` is substituted per attendee.

## N is a build variable

`N` (default **25**, hard ceiling TBD by Michael) drives the spoke fleet size,
provision parallelism, and AWS quota consumption. Nothing here hardcodes a count , 
the provisioning loop reads `N` from the environment.

## Node sizing

`m6i.xlarge` (4 vCPU / 16 GiB) per spoke. The whole per-spoke stack fits **because
LLM Guard runs output-`Regex`-only by default**, no Sensitive NER model is resident.
Opt-in NER requires a larger instance; record any deviation in `../SIZING.md`.

## Provision the fleet (parallel, time-boxed)

```bash
export N="${N:-25}"   # build variable; raise only after the quota check below

# eksctl create runs ~15-20 min per cluster; run them concurrently and wait.
for i in $(seq -w 1 "${N}"); do
  ATTENDEE_ID="$i" envsubst < infra/spoke-cluster/cluster.yaml \
    > "/tmp/spoke-${i}.yaml"
  eksctl create cluster -f "/tmp/spoke-${i}.yaml" &   # parallel
done
wait
echo "All ${N} spokes created."
```

Record median per-spoke provision time in `../SIZING.md` (Phase 2 verification).

## Register each spoke to the hub ArgoCD

`argocd cluster add` writes a cluster Secret in the hub's `argocd` namespace. Label
it `workshop-spoke=true` so the hub `attendee-spokes` ApplicationSet's cluster
generator selects it. The label is what wires a spoke into delivery.

```bash
# Hub ArgoCD must be logged in first (argocd login <hub-server>).
for i in $(seq -w 1 "${N}"); do
  ctx="$(kubectl config get-contexts -o name | grep "workshop-spoke-${i}")"
  name="workshop-spoke-${i}"
  argocd cluster add "${ctx}" --name "${name}" --yes
  # Tag the generated cluster Secret so the cluster generator picks it up.
  kubectl -n argocd label secret \
    "$(kubectl -n argocd get secret -l argocd.argoproj.io/secret-type=cluster \
        -o jsonpath="{.items[?(@.data.name=='$(printf %s "${name}" | base64)')].metadata.name}")" \
    workshop-spoke=true --overwrite
done
```

Once labelled, the ApplicationSet renders an `attendee-<name>` Application per
spoke automatically. No per-attendee edit on the hub.

> verify-at-build: the cluster-Secret labelling one-liner above is the fiddly part , 
> confirm the selector path against the real `argocd cluster add` Secret shape at
> build (the Secret `data.name` is base64 of the cluster name). If awkward, label by
> iterating `kubectl -n argocd get secret -l argocd.argoproj.io/secret-type=cluster`.

## AWS service-quota risk, PRE-DAY CHECK (do this before scaling N)

Spokes consume real quota that scales linearly with N. Verify **before** the event:

- **EKS cluster count per region**, default soft limit is commonly **100**, but
  confirm the account's actual value; N spokes + 1 hub must fit.
- **EC2 vCPU (On-Demand Standard family)**, `m6i.xlarge` = 4 vCPU each, so N=25 is
  **100 vCPU** of spoke nodes plus the hub. Default per-region On-Demand vCPU limits
  routinely sit at 5–64 unless raised, this is the most likely blocker.
- **Elastic IPs / NAT gateways / VPCs**, each `eksctl create cluster` builds a VPC
  by default; VPC-per-region (default 5) and EIP limits bite fast at N spokes.

```bash
# Check the two that bite first (run pre-day; raise via Service Quotas if short).
aws service-quotas get-service-quota \
  --service-code eks --quota-code L-1194D53C   # Clusters per region
aws service-quotas get-service-quota \
  --service-code ec2 --quota-code L-1216C47A   # Running On-Demand Standard vCPUs
```

If quota is short, request increases days ahead (approval is not instant), or shrink
N. Do not discover this on the morning of the workshop.

## Teardown

```bash
for i in $(seq -w 1 "${N}"); do
  eksctl delete cluster --name "workshop-spoke-${i}" --region us-west-2 &
done
wait
```

See `teardown/` for full state + trace-data cleanup.
