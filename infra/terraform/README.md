<!-- ABOUTME: Terraform provisioning for Watch It Burn: one shared lab VPC + a per-attendee EKS -->
<!-- ABOUTME: cluster module, stamped out by a fleet driver. Replaces the old eksctl ClusterConfigs. -->

# Terraform provisioning (replaces eksctl)

Provisioning is Terraform, not eksctl. This is the standard across the workshop projects (the Packt
sister repo, KCD Texas, KubeAuto Day) and is what makes the GCP/Azure ports a module swap instead of
a from-scratch rewrite. Modeled directly on the Packt sister repo's proven two-tier + fleet shape.

## Layout

- `lab-vpc/`: the shared lab VPC, provisioned **once**. One `/16`, two `/18` private subnets, one
  shared NAT. Sized for VPC-CNI prefix delegation (~112 IPs/node) to hold ~60 concurrent clusters.
- `cluster/`: one **independent** attendee EKS cluster (take-home). Takes `vpc_id` +
  `private_subnet_ids` as inputs, so it has no VPC of its own. Instantiated once per attendee, each
  with its own state. Carries the three Watch It Burn controls (see below).
- `fleet/fleet.sh`: the driver. Per-attendee state under `states/`, logs under `logs/`, concurrency
  capped by `MAX_PARALLEL` (default 8). One attendee's failure/teardown never touches another.
- `fleet/cleanup-log-groups.sh`: sweeps orphaned EKS log groups (scoped to `watch-it-burn-*`).

## The three Watch It Burn controls baked into `cluster/`

1. **`podPidsLimit = 1024`** in the node `cloudinit_pre_nodeadm` NodeConfig: the per-pod PID cap,
   the only thing that inline-blocks a fork bomb (verified live: pod-cgroup `pids.max=1024`).
2. **`enableNetworkPolicy = "true"`** in the vpc-cni addon: VPC-CNI enforces NetworkPolicy in-kernel;
   the egress default-deny/allowlist beat is inert without it (found live).
3. **Pod Identity for `agent:agent-sa` -> Bedrock**: fleet-safe model access (a per-cluster role +
   association, no SA annotation in gitops, no 60 OIDC trusts).

## Usage

```bash
# 1. Provision the shared VPC once.
cd lab-vpc && terraform init && terraform apply

# 2. Bring up N attendee clusters (parallel, capped).
cd ../fleet
./fleet.sh up 60                          # watch-it-burn-attendee-001 .. -060
./fleet.sh up watch-it-burn-attendee-007  # or specific names

# 3. Watch.
./fleet.sh status

# 4. Tear down.
./fleet.sh down all                       # or: ./fleet.sh down 60  /  down <names>
./cleanup-log-groups.sh --delete          # sweep orphaned EKS log groups (ours only)

# 5. When the event is over, destroy the shared VPC.
cd ../lab-vpc && terraform destroy
```

## Notes

- **State isolation:** each cluster has `states/<name>.tfstate`. Blast radius is one attendee.
- **Collision safety:** the account is shared with Packt. Every resource is tagged
  `project=watch-it-burn` plus `attendee=<name>`; the fleet refuses any name not `watch-it-burn-*`.
  Verify and clean up by tag, never by guessing.
- **Sizing (verify-at-build):** the `cluster/` default is 1x t3.2xlarge (Packt's validated single-node
  AI-platform shape). The full IDP was validated live on a 6x t3.large test cluster; confirm it fits
  the attendee node and bump `instance_types` / `node_*_size` if pods stay Pending. Start conservative.
- **Multi-cloud seam:** `cluster/` is the swappable unit. A GKE/AKS port reimplements just this module
  (the three controls map: GKE `pod_pids_limit` + Dataplane-V2 + Workload Identity; AKS `podMaxPids`
  + Azure/Calico NP + Workload Identity). `lab-vpc/`, `fleet/`, and the entire `gitops/` layer are reused.
- **Per-cluster ceiling:** ~60 concurrent on the `/18` subnets. For more, widen `lab-vpc` subnets and
  raise `MAX_PARALLEL` + AWS API limits. EC2 vCPU quota (L-1216C47A) is the deliberate increase to request.

## Post-provision

After a cluster is up, deploy the IDP onto it the same cloud-agnostic way as before:
`infra/deploy-full-idp.sh` (installs ArgoCD, registers the repo, applies the gitops app-of-apps).
That layer is unchanged by the eksctl -> Terraform switch.
