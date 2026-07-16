# Research Spike: runtime exec/file block — KubeArmor vs Tetragon on EKS AL2023

Date: 2026-07-12. Question: for the C3 runtime block (stop the agent from reading the secret-recipe file
/ exec+ls snooping), should we drop Tetragon for KubeArmor (Michael's preference for a "preemptive,
frontend" block, keeping Falco+Talon for the responsive side)? Sources (retrieved 2026-07-12): AWS
Containers blog "Secure Bottlerocket deployments on Amazon EKS with KubeArmor", KubeArmor support matrix
+ GitHub. Recency/verification per the standing rule.

## Current state (as deployed, verified in-repo)
- **Nodes: `AL2023_x86_64_STANDARD`** (Amazon Linux 2023, kernel 6.1) — `infra/terraform/aws/cluster/main.tf`.
- **Runtime apps deployed:** Falco (detect) + Falco-Talon (respond) + **Tetragon** (+ tetragon-policies).
  No KubeArmor.
- **The C3 block is Tetragon**, not KubeArmor: `policies/tetragon/block-recipe-snoop.yaml` is a Cilium
  `TracingPolicyNamespaced` that kprobes `security_file_open` on the `workshop-mcp` pod and does
  `action: Override, argError: -1` when a file under `/tmp/burrito-data/config/legacy/` is opened. That
  Override is a **preemptive block** (it fails the open before it succeeds) — i.e. Tetragon is already
  doing the "catch it on the frontend" that the KubeArmor swap was meant to add. Tetragon's kprobe+override
  enforcement does NOT depend on the kernel's active LSM list, so it works on AL2023 as-is.

## CORRECTION 2026-07-16: the real blocker is containerd namespace resolution, NOT the kernel LSM
An earlier draft of this spike said the KubeArmor blocker was AL2 (kernel 5.4) lacking BPF-LSM, and that
moving to AL2023 fixes it "with zero infra change." **That root cause was wrong.** The authoritative
reason lives in our own `gitops/apps/tetragon.yaml` comment, written when the switch was made:

> "KubeArmor v1.7.x cannot resolve container namespaces against EKS AL2023's containerd 2.2.4 (its
> enforcer reports mntns=0 / 'task not found'), so its BPF-LSM block never engages. Tetragon reads
> container identity from BPF/cgroups directly, works on containerd 2.x with no node reconfiguration."

So the blocker is a **KubeArmor-to-containerd-2.x container-identity bug on AL2023**, not a missing kernel
LSM. BPF-LSM being present is necessary but NOT sufficient: with `bpf` active and the enforcer unable to
map the container, the block still never fires.

### What IS confirmed vs what is NOT
- **CONFIRMED live 2026-07-16:** BPF-LSM is active on our AL2023 nodes. A bare single-node cluster was
  provisioned and `/sys/kernel/security/lsm` read from a privileged pod:
  - `KERNEL = 6.12.90-120.164.amzn2023.x86_64`
  - `LSM_LIST = lockdown,capability,landlock,yama,safesetid,selinux,bpf,ima` (`bpf` and `selinux` present)
  - Cluster torn down immediately (trap EXIT); fleet back to zero. This clears the LSM prerequisite ONLY.
- **NOT confirmed:** that KubeArmor's enforcer resolves containers on our current containerd (2.1.x on
  AL2023) so a KubeArmorPolicy actually BLOCKS. This is the real gate and it is still open.

### Upstream status (retrieved 2026-07-16, per recency discipline)
- Latest KubeArmor: **v1.7.4 (2026-07-03)**; v1.7.5-rc1 (2026-07-13). Recent releases touch containerd
  event handling ("use TaskExit type to unmarshal containerd exit events", bump to the containerd v1.8 Go
  module), so the area is active, but **no release note states "AL2023 containerd 2.x enforcement fixed."**
- AWS's own supported KubeArmor-on-EKS reference (Containers blog, 2025-10-21) runs on **EKS Auto Mode =
  Bottlerocket nodes**, not self-managed AL2023 + containerd. Bottlerocket is the AWS-blessed substrate.
- Sources: github.com/kubearmor/KubeArmor/releases; aws.amazon.com/blogs/containers/enhancing-container-
  security-in-amazon-eks-auto-mode-with-kubearmor; artifacthub.io kubearmor-operator 1.7.4.

## Recommendation (revised)
1. **Build the KubeArmor test rig (DONE 2026-07-16):** `gitops/apps/kubearmor.yaml` (operator 1.7.4,
   autoDeploy), `gitops/apps/kubearmor-policies.yaml`, `policies/kubearmor/block-recipe-snoop.yaml`
   (KubeArmorPolicy Block on the legacy dir for app=workshop-mcp). Engine added to the R1 burn include-glob
   (engine only, no policy) so it is present on all three builds while R1 stays enforcement-free.
2. **Validate on the next R2/R3 provision (THE real gate):** apply the KubeArmorPolicy and confirm `cat` of
   `/tmp/burrito-data/config/legacy/secret-sauce-recipe.conf` is DENIED and that KubeArmor (kArmor logs),
   not Tetragon, recorded the block. Also confirm the Tetragon baseline still blocks.
3. **If KubeArmor blocks:** retire Tetragon (+ tetragon-policies); KubeArmor becomes the featured CNCF
   prevention engine. If it does NOT block (containerd bug reproduces): the fix is a **Bottlerocket node
   group** (an AMI change, AWS's supported KubeArmor substrate), or stay on Tetragon. Do NOT remove Tetragon
   until KubeArmor is proven.
4. **Keep Falco + Falco-Talon** (detect + respond, e.g. fork bomb) regardless.

Net: BPF-LSM is confirmed active, but that was never the blocker. The open question is KubeArmor's
container resolution on AL2023 containerd 2.x. Test rig is built; the next provision decides swap vs
Bottlerocket vs stay-on-Tetragon. Not green-lit yet.
