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

## The KubeArmor catch (why the swap is not a clean win)
- **KubeArmor's block is LSM-based:** it enforces via BPF-LSM (or AppArmor). BPF-LSM needs kernel >= 5.7
  AND `bpf` present in the kernel's active `lsm=` list. AWS's own blog: "BPF-LSM ... introduced in newer
  kernels (> 5.7)"; default Amazon Linux 2 (kernel 5.4) "cannot be used" for enforcement; **Bottlerocket**
  is the OS AWS documents for KubeArmor enforcement on EKS.
- **AL2023 (kernel 6.1) is new enough** for BPF-LSM, but whether `bpf` is in the ACTIVE `lsm=` boot
  parameter on the stock EKS AL2023 AMI is UNVERIFIED. Standard EKS AMIs have historically not included
  `bpf` in `lsm=`. If it is absent, KubeArmor on these nodes is **observability-only (cannot block)** — a
  regression from the working Tetragon block.

## Recommendation
1. **Do NOT drop Tetragon blindly.** The deployed Tetragon Override IS the preemptive frontend block; it
   works on AL2023 without LSM changes.
2. **First, confirm the block actually blocks** (this is the unverified guardrail layer): on a live cluster,
   trigger the C3 file read and confirm Tetragon returns the error. This is the core "does it block" check.
3. **If we still want KubeArmor**, verify BPF-LSM is active first: `cat /sys/kernel/security/lsm` on an
   AL2023 node and look for `bpf`. If present, KubeArmor can enforce and we can A/B it against Tetragon. If
   absent, options are (a) enable bpf-lsm via the node bootstrap (`lsm=...,bpf` in the kernel cmdline /
   nodeadm), or (b) switch the node group to Bottlerocket (AWS-documented KubeArmor enforcement) — both are
   bigger changes than the policy swap.
4. **Keep Falco + Falco-Talon** (detect + respond, e.g. fork bomb) regardless. They are complementary to the
   preemptive block, not a replacement.

Net: the "one unconfirmed guardrail layer" is real and worth a live block-test, but the fix is likely to
CONFIRM Tetragon (already preemptive) rather than replace it, unless a live check shows AL2023 has BPF-LSM
active for KubeArmor. Verify on the next cluster.
