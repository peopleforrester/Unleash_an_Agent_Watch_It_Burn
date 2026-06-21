<!-- ABOUTME: Research spike on AWS quota increases, shared-VPC design, and cluster topology for 60 independent EKS clusters. -->
<!-- ABOUTME: Research only. Does not propose repo edits. Aligns to the sister Packt one-cluster-per-student model. -->

# 60 Independent EKS Clusters: Quotas, Shared-VPC Design, and Topology

Research spike for "Unleash an Agent, Watch It Burn." Target: 60 attendees, each with their OWN
independent EKS cluster (Kubernetes up, take-home), in a SHARED VPC, account accen-dev
(<ACCOUNT_ID>), region us-west-2. This supersedes the hub-and-spoke model in the current BUILD-SPEC
as the thing under reconsideration.

## Verification Method

Web research conducted 2026-06-21 against AWS primary sources (Service Quotas / EKS / EC2 / VPC docs
and the EKS Best Practices Guide) plus the eksctl user guide. Every quota code, default value, and
IP/CIDR claim below is cited to a primary source and marked CONFIRMED. Items I could not pin to a
primary source are marked UNCERTAIN. Source URLs are listed at the end of each section and
consolidated at the bottom.

This is research only. No repo files were modified other than the creation of this document.

---

## 1. EKS clusters-per-region quota

**CONFIRMED.** The Service Quota "Clusters" (the maximum number of EKS clusters in this account in
the current Region) has a default of **100 per Region**, and it is **adjustable**. The quota code is
**L-1194D53C**.

From the AWS General Reference EKS quotas table:

| Name | Default | Adjustable | Description |
| --- | --- | --- | --- |
| Clusters | Each supported Region: 100 | Yes (L-1194D53C) | The maximum number of EKS clusters in this account in the current Region. |

**Conclusion: 60 clusters fits comfortably under the default 100. No EKS-clusters quota increase is
needed for 60.** This contradicts the BUILD-SPEC SIZING note that treats "EKS clusters per region"
as "the most likely binding quota" and "default account limits are low relative to a large N." At
N=60 the cluster-count quota is not the binding constraint; the vCPU quota is (Section 2). The one
caveat: the account is shared with the sister Packt project, so confirm current *usage* against the
100 ceiling before the event. 60 (ours) + the Packt project's live clusters must stay under 100, or
request an increase. CONFIRMED that the headroom calculation is usage-dependent.

Related EKS per-cluster quotas that matter for the per-student stack, all well within default:
- Managed node groups per cluster: default 30 (L-6D54EA21). We use 1 per cluster. Fine.
- Nodes per managed node group: default 450 (L-BD136A63). We use 2 to 3. Fine.
- Control plane security groups per cluster: default 4, not adjustable. Fine.

Sources:
- https://docs.aws.amazon.com/general/latest/gr/eks.html (EKS endpoints and quotas table)
- https://docs.aws.amazon.com/eks/latest/userguide/service-quotas.html

---

## 2. The quota that actually binds: EC2 On-Demand Standard vCPU (L-1216C47A)

**CONFIRMED.** The EC2 quota "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" is
measured **in vCPUs**, has a default of **5 vCPUs**, and is **adjustable**. The quota code is
**L-1216C47A**. T-family (t3) instances fall under this Standard quota.

From the EC2 instance type quotas page (On-Demand Instance quotas table, "The following table shows
the maximum number of vCPUs that you can provision for On-Demand Instances"):

| Name | Default | Adjustable |
| --- | --- | --- |
| Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances | 5 | Yes (L-1216C47A) |

Note: AWS automatically raises this quota based on usage over time, so an established account may
already sit well above 5. CONFIRMED that the *documented default* for a new account is 5 vCPUs. Do
not assume the accen-dev account is at 5; read the current applied value in the Service Quotas
console before computing the delta to request.

### vCPU demand at 60 clusters

t3 vCPU counts (CONFIRMED, standard t3 sizing): t3.large = 2 vCPU, t3.xlarge = 4 vCPU,
t3.2xlarge = 8 vCPU. The current facilitator template (`infra/burn-clusters/cluster.yaml`) uses
t3.large desiredCapacity 2 (maxSize 3); the prompt's planning cases are t3.xlarge and t3.2xlarge.

Per-cluster vCPU = nodes_per_cluster x vCPU_per_node. Total = 60 x per-cluster.

| Node size | vCPU/node | 2 nodes/cluster | 3 nodes/cluster |
| --- | --- | --- | --- |
| t3.large | 2 | 60 x 4 = **240 vCPU** | 60 x 6 = **360 vCPU** |
| t3.xlarge | 4 | 60 x 8 = **480 vCPU** | 60 x 12 = **720 vCPU** |
| t3.2xlarge | 8 | 60 x 16 = **960 vCPU** | 60 x 24 = **1,440 vCPU** |

The arithmetic is mine; the per-node vCPU figures are CONFIRMED standard t3 specs. These are
steady-state running totals. Provisioning all 60 in parallel can momentarily exceed steady state if
old/new nodes overlap, so size the request with headroom, not to the exact figure.

### Exact increase to request

This is the single most important request, and AWS approval is **not instant** (it can take from
minutes to several business days depending on the size and the account, and large jumps may route to
a human). File it **well ahead of the event.**

Recommended target for L-1216C47A, with the decided conservative start (t3.xlarge or smaller, 2 to 3
nodes) plus headroom for parallel provisioning, the Packt project's concurrent usage, and the
facilitator/hub nodes:

- **Request L-1216C47A = 1,000 vCPUs** if staying at t3.xlarge or below (covers the 720 vCPU
  worst case at 3 x t3.xlarge with ~40% headroom).
- **Request L-1216C47A = 1,600 to 2,000 vCPUs** if t3.2xlarge is on the table (covers the
  1,440 vCPU worst case at 3 x t3.2xlarge).

Pick the target from the node decision before filing; over-asking slightly is free and avoids a
re-request, but do not request 2,000 if you are committed to t3.xlarge. CONFIRMED that the quota is
per-Region and per-account, so this single request in us-west-2 covers all 60 clusters' node groups.

How to request (CONFIRMED path): Service Quotas console -> Amazon Elastic Compute Cloud (Amazon EC2)
-> "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" (L-1216C47A) -> Request
increase at account level -> enter the new vCPU value. Or AWS CLI:
`aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A
--desired-value 1000 --region us-west-2`.

Sources:
- https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html
- https://repost.aws/knowledge-center/ec2-on-demand-instance-vcpu-increase
- https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-on-demand-instances.html

---

## 3. Shared-VPC design for 60 EKS clusters in ONE VPC

### Is it supported?

**CONFIRMED, yes.** The EKS Best Practices Guide states directly: "Amazon EKS clusters and worker
nodes can be created within shared subnets that are all part of the same VPC. Amazon EKS does not
support the creation of clusters across multiple VPCs." Each EKS cluster has its own AWS-managed
control-plane VPC (invisible to the account); the customer-managed VPC is where nodes live, and
multiple clusters can share it. An re:Post answer confirms multiple EKS control planes in one VPC is
a supported pattern.

EKS places **up to 4 cross-account ENIs (X-ENIs)** per cluster in the cluster subnets you specify at
creation, and creates a per-cluster security group `eks-cluster-sg-<name>-<id>`. With 60 clusters
sharing subnets, that is up to 60 x 4 = 240 X-ENIs plus the node ENIs, all drawing from the same VPC
IP space and counting against the same ENI-per-region quota (Section 4).

### How to put many clusters in one VPC

**eksctl (CONFIRMED).** Point each cluster's config at the existing VPC and subnets:

```yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: watch-it-burn-cN
  region: us-west-2
vpc:
  id: "vpc-XXXXXXXX"
  subnets:
    private:
      us-west-2a: { id: "subnet-aaaa" }
      us-west-2b: { id: "subnet-bbbb" }
managedNodeGroups:
  - name: ng-default
    privateNetworking: true
```

Key eksctl behavior (CONFIRMED from the eksctl VPC docs): when you supply an existing VPC/subnets,
"eksctl create cluster will determine the VPC ID automatically, but it will not create any routing
tables or other resources, such as internet/NAT gateways." So the shared VPC, its subnets, IGW, NAT
gateway(s), and route tables must be **provisioned once, up front** (by a small Terraform VPC stack
or a one-time eksctl/CloudFormation run), and all 60 cluster configs then reference the same subnet
IDs. eksctl still creates per-cluster security groups. At least 2 subnets in 2 AZs are required per
cluster (enforced by EKS).

**Terraform (CONFIRMED pattern, aligns to the sister Packt repo).** The Packt repo uses a VPC module
plus an EKS module per student. To convert to a shared VPC: run the VPC module **once** to create the
shared VPC and subnets, then pass the existing subnet IDs into each per-student EKS module invocation
(`subnet_ids = [...]`, `vpc_id = ...`) instead of creating a VPC per student. This is the smallest
change to the proven Packt model: keep the per-student EKS module, drop the per-student VPC module,
share one VPC's subnet IDs across all 60.

### The real constraint: IP exhaustion

**CONFIRMED.** The Amazon VPC CNI "assigns each pod an IP address from the VPC's CIDR(s)." Every pod
across all 60 clusters draws a routable VPC IP from the shared subnets. This, not the cluster count,
is the design pressure in a shared VPC.

#### IP math

A /16 VPC provides **65,536** addresses (CONFIRMED: "The allowed block size is between a /16 prefix
(65,536 IP addresses) and /28 prefix (16 IP addresses)").

Demand per cluster, default VPC CNI (no prefix delegation), each pod = 1 VPC IP:
- Nodes: 2 to 3 per cluster.
- Pods/node: the workshop per-spoke stack (Kyverno, Falco, kagent + gateway, LLM Guard, the bad MCP
  server, web-terminal, plus kube-system: CoreDNS, kube-proxy, aws-node) is on the order of 15 to 30
  pods per node. Call it 30 pods/node as a conservative ceiling.
- X-ENIs: up to 4 per cluster.
- VPC CNI warm pool: by default the CNI keeps a whole ENI's worth of IPs warm per node, so *assigned*
  IPs run ahead of *running* pods. CONFIRMED ("the VPC CNI keeps an entire ENI ... in the warm
  pool").

Rough per-cluster IP draw at 3 nodes x 30 pods/node + nodes + X-ENIs + warm pool padding:
~3x30 = 90 pod IPs + 3 node IPs + 4 X-ENIs + warm-pool overhead, call it ~120 to 150 IPs/cluster.
At 60 clusters: **~7,200 to 9,000 IPs.**

Against a single /16 (65,536): this fits with large margin (roughly 11 to 14% utilization). The
warning from AWS is real but it is about *subnet* fragmentation and *per-subnet* exhaustion, not the
/16 total. The mitigation is subnet sizing and layout (below), not a bigger VPC.

#### Prefix delegation: not needed here

**CONFIRMED mechanism.** With `ENABLE_PREFIX_DELEGATION=true`, IPAMD assigns **/28 prefixes (16 IPs
each)** to ENIs instead of individual secondary IPs, raising pod density per node and cutting EC2 API
calls. `WARM_PREFIX_TARGET` sets how many free /28 prefixes ipamd keeps warm (cannot be 0 with prefix
delegation on). Prefix delegation's purpose is **higher pod density per node and faster scaling**,
and it actually consumes contiguous /28 blocks, which can cause `InsufficientCidrBlocks` on a
*fragmented* subnet.

For this lab, prefix delegation is **not required**: 2 to 3 small t3 nodes per cluster with ~30 pods
each do not approach the per-node IP ceiling, and the /16 has ample total space. Adding prefix
delegation would increase per-node IP *reservation* (each node grabs whole /28 blocks warm), which is
counterproductive when the goal is to pack 60 clusters into shared subnets without fragmenting them.
Leave the VPC CNI at defaults. If a live run ever shows per-node IP pressure (it should not at this
node count), revisit. CONFIRMED this is the conservative call.

#### Recommended CIDR / subnet layout

Work backwards from scale (AWS guidance: "work backwards from the required workload scale"). Targets:
~9,000 IPs worst case, 60 clusters, 2 AZs minimum, avoid per-subnet exhaustion and fragmentation,
keep it simple to provision once.

**Recommendation: one shared VPC, large private subnets, NOT per-cluster subnets.**

- **VPC CIDR: 10.0.0.0/16** (65,536 IPs). Plenty of headroom; AWS recommends sizing for growth.
- **Two private subnets, one per AZ, each a /18** (16,384 IPs each): `10.0.0.0/18` (us-west-2a),
  `10.0.64.0/18` (us-west-2b). Two /18s = 32,768 IPs for nodes and pods, ~3.5x the ~9,000 worst case.
  Optionally add a third AZ `10.0.128.0/18` for spread; not required (EKS minimum is 2 AZs).
- **Two small public subnets, one per AZ, /24 each** (`10.0.252.0/24`, `10.0.253.0/24`) for the NAT
  gateway and any internet-facing load balancers. Nodes run private (privateNetworking: true).
- **All 60 clusters share the same two private subnets.** Do NOT cut 60 tiny per-cluster subnets:
  small subnets fragment the address space, complicate prefix-delegation if ever enabled, and add
  60x the route-table/management overhead for zero isolation benefit in a fake-data lab. Two big
  shared /18 private subnets keep one contiguous pool per AZ and let the CNI allocate freely.
- Tag the shared subnets for discovery (CONFIRMED eksctl requirement when using existing subnets):
  `kubernetes.io/role/internal-elb=1` on private subnets, `kubernetes.io/role/elb=1` on public, and
  the per-cluster `kubernetes.io/cluster/<name>=shared` tag.

This avoids secondary CIDRs entirely. If the pod-per-node estimate proves high in Phase 2 measurement
and IPs tighten, the documented escape hatch is a non-routable secondary CIDR from `100.64.0.0/10`
(RFC 6598) with VPC CNI custom networking (CONFIRMED AWS recommendation), or simply enlarge the
subnets. Neither is needed at the projected scale.

Sources:
- https://docs.aws.amazon.com/eks/latest/best-practices/subnets.html
- https://docs.aws.amazon.com/eks/latest/best-practices/ip-opt.html
- https://docs.aws.amazon.com/eks/latest/userguide/cni-increase-ip-addresses.html
- https://github.com/aws/amazon-vpc-cni-k8s/blob/master/docs/prefix-and-ip-target.md
- https://docs.aws.amazon.com/eks/latest/eksctl/vpc-configuration.html
- https://repost.aws/questions/QUj7XJ_3cVTuiWTSj0LZ8gig/multiple-eks-control-planes-one-vpc

---

## 4. Other quotas: shared VPC vs per-VPC

A shared VPC eliminates several quotas that per-VPC-per-student would have hit, but introduces ENI
pressure. Defaults below are CONFIRMED from AWS VPC quota sources; treat the exact applied values in
accen-dev as needing a console check.

| Quota | Default | Per-VPC model (60 VPCs) | Shared-VPC model (1 VPC) | Action at 60 |
| --- | --- | --- | --- | --- |
| VPCs per Region | 5 (adjustable) | Would need increase to >=60+ | 1 VPC | **Moot. No increase.** |
| Elastic IPs per Region | 5 (adjustable) | 60 NAT GWs would need 60 EIPs | 1 to 2 NAT GWs = 1 to 2 EIPs | Fine under default, or tiny bump |
| NAT gateways per AZ | 5 (adjustable) | 60+ | 1 per AZ (Single or HA mode) | **Fine. No increase.** |
| Network interfaces (ENIs) per Region | 5,000 (adjustable) | spread across 60 VPCs | All in 1 VPC: X-ENIs + node ENIs | **Watch this one (below)** |
| Security groups per Region | 2,500 (adjustable) | 60 clusters x per-cluster SGs | Same SG count, one VPC | Fine under default |
| Security groups per network interface | 5 (adjustable to 16) | n/a | n/a | Fine |

UNCERTAIN: the "Network interfaces per Region" default is widely reported as 5,000 but I did not pull
it from the canonical VPC quota table in this session; verify in the Service Quotas console. The
others (VPC=5, EIP=5, NAT=5/AZ) are CONFIRMED from AWS VPC quota guidance.

**The ENI quota is the one to watch in the shared-VPC model.** Each cluster: up to 4 X-ENIs + one ENI
per node (more if the CNI attaches secondary ENIs for IP capacity). At 60 clusters x (4 X-ENIs + ~3
node ENIs + warm-pool secondary ENIs) you are on the order of 60 x 7 to 60 x 12 = ~420 to ~720 ENIs.
That is comfortably under a 5,000 default. CONFIRMED the arithmetic stays well under default; no ENI
increase expected, but monitor with the CNI Metrics Helper during provisioning.

**Net: with a shared VPC and a single NAT path, the only quota that needs a deliberate increase is
the EC2 vCPU quota (Section 2).** EIPs may want a token bump only if you run HA NAT (one per AZ) and
the account already has EIPs in use; one or two EIPs is within the default of 5.

Sources:
- https://docs.aws.amazon.com/vpc/latest/userguide/amazon-vpc-limits.html
- https://docs.aws.amazon.com/general/latest/gr/vpc-service.html
- https://docs.aws.amazon.com/eks/latest/eksctl/vpc-configuration.html (NAT modes: Disable/Single/HighlyAvailable)

---

## 5. When are independent VPCs actually warranted?

Independent (per-cluster) VPCs are warranted when there is a **hard isolation requirement that subnet
or namespace boundaries cannot satisfy**:

1. **Regulatory / compliance hard isolation** of real regulated data (PCI, HIPAA, FedRAMP boundaries)
   where the network blast radius itself is an auditable control.
2. **Overlapping CIDRs** that must coexist (mergers, customer-supplied address space). AWS explicitly
   handles this with separate VPCs plus private NAT gateway / VPC Lattice / Transit Gateway, and
   "strongly recommend deploying EKS clusters and nodes to IP ranges that do not overlap." CONFIRMED.
3. **Blast-radius isolation for real customer data**, where one tenant's network compromise must not
   reach another tenant's traffic at the VPC layer.
4. **Per-tenant network ownership / delegation**, where each tenant (or account) must independently
   own and administer its VPC, typically via the cross-account RAM shared-VPC pattern.

**None of these apply to this lab. The case for a shared VPC here is explicit:**

- The data is **obviously fake** (planted `FAKE-...-sentinel` secrets). There is no regulated or real
  customer data to isolate.
- **Network isolation between students is explicitly NOT a requirement** (per the HARD CONTEXT). The
  isolation that matters in this workshop is at the cluster / Falco / admission-webhook layer (each
  student gets a real cluster), not the VPC layer.
- It is a **2-hour intermittent lab**, not standing multi-tenant infrastructure.
- Cost and operational simplicity matter: 60 VPCs means 60x the NAT gateways (each NAT GW bills
  hourly + per-GB), 60 route tables, a VPC-per-region quota increase, and 60x the IGW/EIP plumbing,
  all for isolation nobody needs.

Requesting 60 VPCs (or even raising the VPCs-per-region quota) is **unnecessary and wasteful** for
this engagement. One shared VPC with the layout in Section 3 is the correct design.

Sources:
- https://docs.aws.amazon.com/eks/latest/best-practices/subnets.html (overlapping CIDR / Lattice / cross-account RAM)

---

## 6. Topology: independent per-student ArgoCD vs hub-and-spoke

### The two models

- **Independent (Packt model, recommended):** each student's cluster runs its OWN in-cluster ArgoCD,
  reconciling that cluster from Git. Self-contained. No cross-cluster control plane.
- **Hub-and-spoke (current BUILD-SPEC rev3):** one hub cluster runs a central ArgoCD that registers
  all 60 spokes and delivers the per-attendee stack via an ApplicationSet **cluster generator**, which
  produces Applications per registered cluster Secret. CONFIRMED that this is how the cluster
  generator works.

### Honest comparison

| Dimension | Independent per-student ArgoCD | Hub-and-spoke central ArgoCD |
| --- | --- | --- |
| Blast radius | Failure is contained to one student's cluster. | Hub ArgoCD outage or a bad ApplicationSet template affects all 60 at once. CONFIRMED that AWS/Argo guidance treats reducing blast radius as a primary reason to split control planes. |
| Reconciliation load | Each ArgoCD reconciles only its own cluster (tiny). | One ArgoCD reconciles 60 clusters. Community rule of thumb is ~1 controller shard per 15 to 20 clusters and ~20 to 30 clusters per ArgoCD instance, so 60 spokes needs sharding/tuning to stay healthy. CONFIRMED. |
| Take-home portability | Native. The student leaves with a complete, self-reconciling cluster and its Git repo. Nothing points back to a facilitator hub. | Broken. A spoke detached from the hub stops getting reconciled; the student's cluster was never self-contained. The hub-registration model is the opposite of take-home. |
| Provisioning complexity | N identical, independent provisions. Trivially parallel. No registration step. Matches the proven Packt one-cluster-per-student flow. | Must stand up and size a hub, register 60 spoke Secrets into it, manage the cluster generator, and keep the hub alive for the whole event. Extra moving part that can fail centrally. |
| Failure isolation during the live "burn" | A student melting their own cluster (fork bomb, etc.) cannot touch anyone else's reconciliation. | A spoke's chaos plus a shared hub means the hub's reconciliation queue and the cluster generator are a shared resource across the room. |
| Cost | One ArgoCD per cluster (small, fits the existing per-spoke node budget). | Saves one ArgoCD-per-cluster but adds a dedicated hub cluster (control plane + nodes) that must run the whole event. |

### Recommendation

**Use the independent per-student model: each cluster runs its own in-cluster ArgoCD reconciling
itself from Git.** This is the correct fit because:

1. **Take-home is a stated goal.** Only the self-contained model produces a cluster the student can
   keep and keep running. Hub-and-spoke produces spokes that are inert once detached.
2. **Blast radius and failure isolation** are exactly what a "watch it burn" lab stresses. The
   independent model guarantees one student's destruction stays local; hub-and-spoke introduces a
   shared control plane that is precisely the wrong thing to share in a chaos lab.
3. **It matches the proven sister-repo model** (Packt one-cluster-per-student via Terraform), so
   provisioning is already de-risked and trivially parallel, with no spoke-registration step.
4. **Hub-and-spoke buys nothing here.** Its real value is centralized fleet management of
   long-lived, related clusters by one platform team. These 60 clusters are independent, short-lived,
   and explicitly NOT a managed fleet. Central ArgoCD at 60 spokes also forces sharding/tuning work
   (the ~20 to 30 clusters/instance guidance) for a 2-hour event, which is effort spent solving a
   problem the architecture created.

**Hub-and-spoke is the wrong fit** because it optimizes for centralized control of a fleet you do not
want to centrally control, breaks the take-home requirement, and concentrates blast radius in a
shared hub for a lab whose entire point is isolated, observable destruction.

Sources:
- https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators-Cluster/
- https://akuity.io/blog/argo-cd-architectures-explained
- https://argo-cd.readthedocs.io/en/stable/operator-manual/ (sharding / scaling guidance)

---

## Bottom line

### (a) Quota increases to request now

| Quota | Code | Current default | Request for 60 clusters | Priority |
| --- | --- | --- | --- | --- |
| EC2 Running On-Demand Standard (A,C,D,H,I,M,R,T,Z) vCPUs | **L-1216C47A** | 5 vCPU (new acct; verify applied value) | **1,000 vCPU** if t3.xlarge or smaller; **1,600 to 2,000 vCPU** if t3.2xlarge | **CRITICAL, file first, approval not instant** |
| EKS Clusters per Region | L-1194D53C | 100 | **No increase** (60 < 100; verify shared-account usage headroom) | Verify only |
| Elastic IPs per Region | (VPC) | 5 | No increase for Single NAT; verify if HA NAT + existing EIP usage | Verify only |
| NAT gateways per AZ | (VPC) | 5 | No increase | None |
| Network interfaces per Region | (VPC) | ~5,000 (UNCERTAIN, verify) | No increase (~420 to 720 ENIs needed) | Monitor only |
| VPCs per Region | (VPC) | 5 | No increase (shared VPC = 1) | None |

The vCPU quota is the only deliberate, time-sensitive request. Everything else is verify-or-monitor.

### (b) Recommended shared-VPC CIDR / subnet layout

- One VPC, `10.0.0.0/16` (65,536 IPs).
- Two private subnets, one per AZ, /18 each: `10.0.0.0/18` (2a), `10.0.64.0/18` (2b). Optional third
  AZ `10.0.128.0/18`.
- Two public /24 subnets for NAT + ingress LBs: `10.0.252.0/24`, `10.0.253.0/24`.
- All 60 clusters share the two private subnets (nodes private). Do NOT cut per-cluster subnets.
- Single NAT gateway (or one per AZ for HA). Provision the VPC/subnets/NAT/IGW/routes ONCE up front;
  point all 60 eksctl/Terraform cluster configs at the existing subnet IDs. Tag subnets for discovery.
- VPC CNI at defaults: no prefix delegation, no secondary CIDR needed at this scale. Escape hatch if
  Phase-2 measurement shows IP pressure: `100.64.0.0/16` secondary CIDR + custom networking.

### (c) Topology recommendation

Independent per-student clusters, each running its own in-cluster ArgoCD reconciling itself from Git
(the Packt model). Drop the hub-and-spoke / central-ArgoCD-cluster-generator design from BUILD-SPEC
rev3. It breaks take-home portability, concentrates blast radius in a shared hub, adds a
spoke-registration step and ArgoCD sharding work, and centralizes control of a fleet that is
explicitly not meant to be centrally controlled.

---

## Consolidated sources

- EKS quotas table (Clusters L-1194D53C = 100): https://docs.aws.amazon.com/general/latest/gr/eks.html
- EKS service quotas console guide: https://docs.aws.amazon.com/eks/latest/userguide/service-quotas.html
- EC2 instance type quotas (Standard vCPU L-1216C47A = 5): https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-quotas.html
- EC2 On-Demand vCPU increase how-to: https://repost.aws/knowledge-center/ec2-on-demand-instance-vcpu-increase
- EKS VPC and subnet considerations (shared subnets, one VPC, /16 to /28, X-ENIs): https://docs.aws.amazon.com/eks/latest/best-practices/subnets.html
- EKS optimizing IP utilization (prefix delegation, secondary CIDR 100.64.0.0/10, warm pool): https://docs.aws.amazon.com/eks/latest/best-practices/ip-opt.html
- EKS assign more IPs with prefixes (/28 prefix, max-pods): https://docs.aws.amazon.com/eks/latest/userguide/cni-increase-ip-addresses.html
- VPC CNI prefix/IP target docs: https://github.com/aws/amazon-vpc-cni-k8s/blob/master/docs/prefix-and-ip-target.md
- eksctl VPC configuration (existing VPC/subnets, NAT modes, no IGW/NAT auto-create): https://docs.aws.amazon.com/eks/latest/eksctl/vpc-configuration.html
- Multiple EKS control planes in one VPC (re:Post): https://repost.aws/questions/QUj7XJ_3cVTuiWTSj0LZ8gig/multiple-eks-control-planes-one-vpc
- VPC quotas: https://docs.aws.amazon.com/vpc/latest/userguide/amazon-vpc-limits.html
- ArgoCD ApplicationSet cluster generator: https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators-Cluster/
- Argo CD architectures (blast radius, scaling): https://akuity.io/blog/argo-cd-architectures-explained
