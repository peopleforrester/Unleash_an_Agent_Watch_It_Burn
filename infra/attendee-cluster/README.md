<!-- ABOUTME: The attendee-cluster MODEL (independent, take-home, own in-cluster ArgoCD). The IaC that -->
<!-- ABOUTME: actually provisions it is Terraform at infra/terraform/ (lab-vpc + cluster + fleet). -->

# Attendee clusters (independent, take-home)

One **independent EKS cluster per attendee** (no vCluster, no hub-and-spoke). Each cluster runs the
full per-attendee IDP and its **own in-cluster ArgoCD**, which reconciles the cluster from Git
(`gitops/bootstrap/app-of-apps.yaml`, destination `kubernetes.default.svc`). An attendee takes their
cluster home and it keeps working, because nothing depends on a central control plane.

> **Provisioning is Terraform.** This doc is the *model*; the IaC lives in `infra/terraform/`
> (`lab-vpc/` shared VPC + `cluster/` per-attendee module + `fleet/fleet.sh`). See
> `infra/terraform/README.md` for the full workflow.

## N is a build variable

`N` (working number **60**, ceiling owned by Michael) drives the fleet size and parallelism. Nothing
hardcodes a count; `fleet.sh up <N>` generates `watch-it-burn-attendee-001 .. -<N>`.

## Shared VPC (provisioned once, first)

All attendee clusters share ONE VPC (`infra/terraform/aws/network/`), not one each. Apply it once; the
`cluster/` module reads its `vpc_id` + private subnet ids straight from the lab-vpc state, so there is
no manual id substitution. See `infra/shared-vpc/README.md`.

## Node sizing (validated)

**1× t3.2xlarge** per cluster, 100 GiB root, prefix delegation + `maxPods: 110`. Measured live: the
full IDP runs at ~38% CPU / 19% memory on one node, so one t3.2xlarge holds it with headroom. Defaults
live in `infra/terraform/aws/cluster/main.tf` (`instance_types`, `node_disk_size`); scale only if a real
run chokes. See `../SIZING.md`.

## Provision the fleet

```bash
# 1. Shared VPC, once.
cd infra/terraform/aws/network && terraform init && terraform apply

# 2. N attendee clusters (parallel, per-attendee isolated state).
cd ../fleet && ./fleet.sh up 60          # or: ./fleet.sh up watch-it-burn-attendee-007
./fleet.sh status

# 3. Deploy the IDP onto each cluster (installs ArgoCD + applies the app-of-apps).
KUBECONFIG=/tmp/watch-it-burn-attendee-001.kubeconfig \
  aws eks update-kubeconfig --name watch-it-burn-attendee-001 --region us-west-2 --profile accen-dev
infra/deploy-full-idp.sh full
```

Each cluster self-bootstraps its own ArgoCD (no `argocd cluster add`, no central generator); the
app-of-apps `destination` is the local cluster, which is what makes it take-home.

## AWS quota (pre-day check)

With the shared VPC the binding quota is **EC2 vCPU**, not VPCs. EKS clusters-per-region default is
100 (60 fits). For an all-t3.2xlarge fleet (8 vCPU each) request a vCPU increase early (target
~1,000 vCPU); the lab team handles this.

```bash
aws service-quotas get-service-quota --profile accen-dev --region us-west-2 \
  --service-code ec2 --quota-code L-1216C47A   # Running On-Demand Standard vCPUs
```

## Teardown

```bash
teardown/teardown.sh         # destroys all watch-it-burn-* clusters (prefix-scoped; cannot hit Packt)
teardown/teardown.sh --vpc   # also remove the shared lab VPC when the event is over
```
