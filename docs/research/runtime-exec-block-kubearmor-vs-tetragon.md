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

## RESULT 2026-07-18: KubeArmor ENFORCES on AL2023/containerd. Swap is VIABLE.
Live-validated on a full-profile `watch-it-burn-r3-1` (operator 1.7.4, autoDeploy), then torn down:
- **Container resolution works.** KubeArmor logged `Initialized BPF-LSM Enforcer`, `Detected a Security
  Policy (added/agent/block-recipe-snoop)`, and `Detected a Pod (added/agent/workshop-mcp-...)`. The old
  `mntns=0 / task-not-found` failure does NOT reproduce on the current containerd. That documented reason
  for choosing Tetragon is obsolete.
- **Enforcement confirmed two ways.** A Tetragon-independent sentinel probe (`Block` on a file only
  KubeArmor covered) returned `Permission denied`; and the real `block-recipe-snoop` KubeArmorPolicy, with
  the Tetragon rule removed first, also returned `Permission denied` on the bait file. So KubeArmor is
  doing the block, not Tetragon.
- **The real prerequisite is admission ordering, not the kernel or containerd.** KubeArmor enforces only on
  pods admitted AFTER its controller webhook is up (it annotates `kubearmor-policy: enabled` at admission;
  pre-existing pods get visibility only). In the test, workshop-mcp came up before the operator finished
  deploying the controller, so it had to be re-admitted to gain enforcement.

## Remaining work for the actual Tetragon -> KubeArmor cutover (NOT a viability question)
1. **Fix ordering** so workshop-mcp is admitted after the KubeArmor controller. The kubearmor app is
   sync-wave -6 and ai-layer is wave 3, but the OPERATOR reports Healthy once the operator pod is up, not
   when the controller/daemonset/webhook is ready, so ai-layer races ahead. Add a sync-wave gate or a
   health check (e.g. a PreSync/wave hook that waits for the kubearmor DaemonSet + controller Ready) so the
   workload lands after enforcement is armed. A manual `kubectl rollout restart` is NOT the answer on a live
   cluster: the Kyverno `block-argocd-drift` policy denies hand-mutation of the ArgoCD-managed deployment.
2. **Then retire Tetragon** (+ tetragon-policies) and make KubeArmor the featured CNCF prevention engine.
   Until step 1 lands, keep Tetragon as the working C3 block; the KubeArmor engine can ship alongside
   (dual-run) safely since it simply does not enforce on the un-annotated workshop-mcp yet.
3. **Keep Falco + Falco-Talon** (detect + respond) regardless.

No Bottlerocket needed: enforcement works on our AL2023 nodes as-is.
