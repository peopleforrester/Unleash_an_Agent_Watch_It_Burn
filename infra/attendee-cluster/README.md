*Purpose: provision N independent attendee EKS clusters in parallel from the template, each into the
one shared VPC, each self-bootstrapping its own in-cluster ArgoCD. No hub.*

# Attendee clusters (independent, take-home)

One **independent EKS cluster per attendee** (no vCluster, no hub-and-spoke). Each cluster runs the
full per-attendee IDP stack and its **own in-cluster ArgoCD**, which reconciles the cluster from Git
(`gitops/bootstrap/app-of-apps.yaml`, whose destination is the local cluster). A student takes their
cluster home and it keeps working, because nothing depends on a central control plane.
`cluster.yaml` is a **template**; `ATTENDEE_ID` is substituted per attendee.

## N is a build variable

`N` (working number **60**, hard ceiling owned by Michael) drives the fleet size, provision
parallelism, and AWS quota consumption. Nothing here hardcodes a count; the loop reads `N` from the
environment.

## Shared VPC (provision once, first)

All attendee clusters share ONE pre-provisioned VPC (see `infra/shared-vpc/README.md`), not one VPC
each. Build the VPC + subnets + NAT once, record the ids, and substitute them into `cluster.yaml`
(`vpc.id`, `vpc.subnets.private.*`) before creating any cluster. eksctl will NOT create a VPC/NAT/routes
when a config references an existing VPC, so the shared VPC must exist first.

## Node sizing

`t3.xlarge` (4 vCPU / 16 GiB) burstable, unlimited credit mode, per cluster. Conservative start for a
2-hour intermittent lab; the stack fits because LLM Guard runs output-`Regex`-only by default (no
Sensitive NER model resident). Measure one live cluster before pinning the fleet; scale only if a real
run chokes credits. See `../SIZING.md` and `research/24`.

## Provision the fleet (parallel, time-boxed)

```bash
export N="${N:-60}"   # build variable; raise only after the quota check below

# eksctl create runs ~15-20 min per cluster; run them concurrently and wait.
for i in $(seq -w 1 "${N}"); do
  ATTENDEE_ID="$i" envsubst < infra/attendee-cluster/cluster.yaml \
    > "/tmp/attendee-${i}.yaml"
  eksctl create cluster -f "/tmp/attendee-${i}.yaml" &   # parallel, into the shared VPC
done
wait
echo "All ${N} attendee clusters created."
```

Record median per-cluster provision time in `../SIZING.md` (Phase 2 verification).

## Bootstrap each cluster's own ArgoCD (no hub registration)

Each cluster manages itself. Per cluster: install ArgoCD, then apply the in-cluster app-of-apps; ArgoCD
reconciles the rest from Git. There is no `argocd cluster add` and no central generator.

```bash
for i in $(seq -w 1 "${N}"); do
  ctx="$(kubectl config get-contexts -o name | grep "watch-it-burn-attendee-${i}")"
  # Install ArgoCD into THIS cluster, then point it at itself via the app-of-apps.
  kubectl --context "${ctx}" create namespace argocd --dry-run=client -o yaml | kubectl --context "${ctx}" apply -f -
  helm --kube-context "${ctx}" upgrade --install argo-cd argo/argo-cd -n argocd --wait
  kubectl --context "${ctx}" apply -f gitops/bootstrap/app-of-apps.yaml
done
```

verify-at-build: confirm the ArgoCD chart version pin (deploy-full-idp.sh) and that the app-of-apps
`destination` is `https://kubernetes.default.svc` (the local cluster). The same self-bootstrap is what
makes the cluster take-home.

## AWS service-quota risk, PRE-DAY CHECK (do this before scaling N)

Clusters consume quota that scales with N. With the SHARED VPC, the binding quota is EC2 vCPU, not VPCs
(research/25). Verify **before** the event:

- **EKS clusters per region**: default **100**, so N=60 fits with no increase. Confirm the account's
  actual value and that combined usage with the co-tenant Packt project stays under 100.
- **EC2 vCPU (On-Demand Standard)**: `t3.xlarge` = 4 vCPU each, so 60 clusters is ~240-480 vCPU.
  Default per-region limits routinely sit at 5-64; this is the one increase to request early
  (approval is not instant). Target ~1,000 vCPU.
- **Shared VPC** means VPC-per-region (default 5), Elastic IP, and NAT quotas are moot.

```bash
# The one that binds (run pre-day; raise via Service Quotas if short).
aws service-quotas get-service-quota --profile accen-dev --region us-west-2 \
  --service-code ec2 --quota-code L-1216C47A   # Running On-Demand Standard vCPUs
```

## Teardown

Use the prefix-scoped teardown (cannot touch the co-tenant Packt clusters):

```bash
teardown/teardown.sh --region us-west-2 --prefix watch-it-burn-attendee --yes
```

The shared VPC is left intact by cluster deletes; remove it separately, last (`infra/shared-vpc/`).
