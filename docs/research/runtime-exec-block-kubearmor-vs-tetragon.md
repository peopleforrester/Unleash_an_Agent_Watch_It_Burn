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

## KubeArmor on AL2023: viable now (the past blocker was AL2, not AL2023)
- **KubeArmor's block is LSM-based:** enforces via BPF-LSM (or AppArmor). BPF-LSM needs kernel >= 5.7 with
  CONFIG_BPF_LSM and `bpf` in the active `lsm=` list.
- **The past "KubeArmor unusable on EKS" was almost certainly AL2 (kernel 5.4):** AWS confirms default
  AL2 "cannot be used" for BPF-LSM enforcement. That is the AMI they had when they switched to Tetragon.
- **AL2023 changes the answer: BPF-LSM is enabled and activated BY DEFAULT on Amazon Linux 2023** (per
  KubeArmor/AWS docs, retrieved 2026-07-12). Our node group is `AL2023_x86_64_STANDARD` (kernel 6.1), so
  **KubeArmor enforcement should work out of the box** — no Bottlerocket, no bootstrap change needed. The
  old blocker is gone. KubeArmor is a CNCF Sandbox project (why Michael wants it for the CNCF-guardrails
  story); Tetragon is CNCF-Graduated (via Cilium), so both are CNCF, but KubeArmor is the featured name.
- **Still verify live** (recency discipline): the "enabled by default" claim is from docs; confirm on an
  actual node.

## Recommendation
1. **Fold the check into the next R3 provision** (Michael, 2026-07-12): on a live AL2023 node,
   `cat /sys/kernel/security/lsm` and confirm `bpf` is in the list. If yes -> KubeArmor can enforce here.
2. **Confirm the current Tetragon block actually blocks** (the unverified layer): trigger the C3 file read
   (path under `/tmp/burrito-data/config/legacy/`) and confirm the open is denied. Keep this as the baseline.
3. **If BPF-LSM confirmed active:** proceed to swap in KubeArmor for the C3 preemptive block -- deploy the
   KubeArmor gitops app + a KubeArmor policy equivalent to `block-recipe-snoop` (block file open under the
   legacy path for the workshop-mcp pod), verify it BLOCKS, then retire Tetragon (+ tetragon-policies). If
   the live check unexpectedly shows no bpf, fall back: keep Tetragon, or add `lsm=...,bpf` via node
   bootstrap, or Bottlerocket.
4. **Keep Falco + Falco-Talon** (detect + respond, e.g. fork bomb) regardless -- complementary to the block.

Net: KubeArmor is very likely viable on AL2023 now (past failure was AL2). Plan is to confirm BPF-LSM +
the Tetragon baseline on the next provision, then swap Tetragon -> KubeArmor if confirmed. Not blind.
