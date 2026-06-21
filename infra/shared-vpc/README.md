<!-- ABOUTME: One shared VPC for all Watch It Burn clusters. Provisioned once up front; every cluster -->
<!-- ABOUTME: config references its id + subnet ids. Replaces per-cluster VPCs (research/25). -->

# Shared VPC (provision once, all clusters share it)

Every Watch It Burn cluster (attendee, presenter, and the demo burn clusters) is created INTO one
shared VPC. We do NOT create one VPC per attendee. A fake-data 2-hour lab does not need per-tenant
network isolation, and 60 VPCs would burn the VPC-per-region quota for no benefit (research/25).

## Layout

- One VPC, CIDR `10.0.0.0/16` (65,536 addresses).
- Two shared private `/18` subnets, one per AZ (us-west-2a, us-west-2b), where all cluster nodes and
  pods live. VPC-CNI gives every pod a routable VPC IP; ~9,000 pod IPs at 60 clusters is roughly 14%
  of a /16, so prefix delegation is not needed.
- Small public `/24` subnets for the NAT gateway(s) and any ingress load balancers.

## Why this and not per-cluster VPCs

- IP math fits comfortably in one /16 (research/25).
- Shared VPC means the VPC-per-region (default 5), Elastic IP, and NAT quotas are all moot; the only
  deliberate quota increase needed at 60 clusters is EC2 On-Demand Standard vCPU (L-1216C47A, target
  ~1,000 vCPU for an all-t3.xlarge fleet). EKS clusters-per-region default is 100, so 60 fits.
- Independent VPCs are only warranted for hard isolation or compliance (regulatory, overlapping CIDRs,
  real customer data). None apply here.

## Provisioning order (load-bearing)

1. Create the shared VPC + subnets + NAT ONCE, up front, before any cluster.
2. Record the VPC id and the two private subnet ids.
3. Substitute them into every cluster config (`vpc.id`, `vpc.subnets.private.*`) before
   `eksctl create cluster`.

eksctl gotcha (CONFIRMED, research/25): when a ClusterConfig references an EXISTING VPC/subnets,
eksctl does NOT create the VPC, NAT gateway, internet gateway, or routes. Those must already exist on
the shared VPC. So the one-time VPC build is a prerequisite, not something eksctl does per cluster.

verify-at-build: pick the provisioning tool for the shared VPC (a small CloudFormation/Terraform stack,
or `eksctl create cluster` for the first cluster with `vpc.cidr` then reuse its VPC/subnets). Pin the
resulting ids here and in the cluster configs.
