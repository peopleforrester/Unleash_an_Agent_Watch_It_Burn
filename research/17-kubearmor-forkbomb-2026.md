# 17. KubeArmor vs the Fork Bomb (Research Spike)

ABOUTME: Research spike on whether CNCF KubeArmor can prevent a fork bomb on EKS AL2023,
ABOUTME: how it enforces, and how it compares to the repo's existing podPidsLimit + Falco defenses.

## Verification Method

Web research conducted 2026-06-21. All version numbers, CRD field names, maturity claims,
and LSM behavior statements are taken from the cited primary sources below, not from memory.
Primary sources consulted:

- KubeArmor GitHub repo: https://github.com/kubearmor/KubeArmor
- KubeArmor policy spec (raw source of truth): https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md
- KubeArmor FAQ (raw source of truth): https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/FAQ.md
- KubeArmor docs, security policy spec: https://docs.kubearmor.io/kubearmor/documentation/security_policy_specification
- KubeArmor docs, security posture / audit mode: https://docs.kubearmor.io/kubearmor/documentation/default_posture
- KubeArmor docs, runtime enforcer: https://docs.kubearmor.io/kubearmor/quick-links/kubearmor_overview/runtime_enforcer
- KubeArmor Event Auditor design blog (the `rate:` syntax source): https://kubearmor.io/blog/kubearmor-event-auditor-design
- KubeArmor BPF-LSM integration blog: https://kubearmor.io/blog/kubearmor-bpf-lsm-integration
- CNCF project page: https://www.cncf.io/projects/kubearmor/
- AWS Containers blog, KubeArmor on EKS Auto Mode: https://aws.amazon.com/blogs/containers/enhancing-container-security-in-amazon-eks-auto-mode-with-kubearmor/
- AWS Containers blog, KubeArmor on Bottlerocket/EKS: https://aws.amazon.com/blogs/containers/secure-bottlerocket-deployments-on-amazon-eks-with-kubearmor/
- AccuKnox, eBPF/BPF-LSM runtime security: https://accuknox.com/blog/runtime-security-ebpf-bpf-lsm
- Linux kernel docs, LSM BPF programs: https://docs.kernel.org/bpf/prog_lsm.html
- AWS AL2023 kernel hardening docs: https://docs.aws.amazon.com/linux/al2023/ug/kernel-hardening.html

Note on access: `docs.kubearmor.io` and `kubearmor.io/blog` return HTTP 403 to automated
fetch. The authoritative content was instead read from the raw GitHub markdown that those
docs pages are generated from, plus search-engine snapshots of the same pages.

---

## Bottom line up front

The kubelet `podPidsLimit` (cgroup `pids.max`) remains the only true inline fork-bomb block in
this stack. KubeArmor, as shipped (v1.7.3), has **no process-count, thread-count, or fork-rate
field in its enforcement policy (KubeArmorPolicy)**. Its enforcement model is allow/deny of
named binary execution, file access, network protocols, and capabilities, not resource-count
limiting. KubeArmor would **not** stop a classic in-shell fork bomb unless it blocked execution
of the shell itself, which is far blunter and more fragile than a PID cap. KubeArmor's real value
in this workshop is elsewhere: CNCF-native inline prevention of OTHER attacks (binary execution,
file tamper, secret/credential file reads, network egress), not fork-bomb defense.

---

## Q1. What is KubeArmor and how does it enforce? CONFIRMED

**What it is.** KubeArmor is "a cloud-native runtime security enforcement system that restricts
the behavior (such as process execution, file access, and networking operations) of pods,
containers, and nodes (VMs) at the system level" (KubeArmor GitHub repo description and docs).

**CNCF maturity. CONFIRMED.** KubeArmor is a CNCF **Sandbox** project, accepted **November 16,
2021** (CNCF project page, https://www.cncf.io/projects/kubearmor/). It is not Incubating or
Graduated. Treat its API surface as Sandbox-stable, not LTS-guaranteed.

**Latest release. CONFIRMED.** v1.7.3, released 2026-05-29 (GitHub releases, as read 2026-06-21).

**Enforcement LSMs. CONFIRMED.** KubeArmor enforces via Linux Security Modules: "KubeArmor
leverages Linux security modules (LSMs) such as AppArmor, SELinux, or BPF-LSM to enforce the
user-specified policies." (docs / repo). LSM preference order: if BPF-LSM is available it is
used by default; BPF-LSM is a stackable LSM, so if the BPF-LSM enforcer is unavailable KubeArmor
falls back to AppArmor (BPF-LSM integration blog / AccuKnox).

**Enforcement mechanism: inline kernel block (when an enforcing LSM is present). CONFIRMED.**
With BPF-LSM, KubeArmor attaches eBPF bytecode at LSM hooks in the kernel; the kernel evaluates
the policy at the hook and denies the operation inline, returning a permission error to the
calling process before the operation completes (BPF-LSM integration blog; kernel LSM BPF docs,
https://docs.kernel.org/bpf/prog_lsm.html). This is the same hook layer SELinux and AppArmor
use. So KubeArmor enforcement is architecturally inline (pre-operation deny), NOT post-hoc kill,
**for the operations LSM hooks cover** (exec, file open, capability use, etc.).

**Important architectural caveat. CONFIRMED.** Syscall *monitoring* is a separate, audit-only
path. The policy spec states: "For System calls monitoring, we only support audit mode no matter
what the action is set to." (policy spec, raw GitHub source). So the `syscalls:` section of a
KubeArmorPolicy can never block; it only generates alerts. This matters directly for Q2.

---

## Q2. Can KubeArmor prevent a fork bomb, and how exactly? CONFIRMED (it cannot, as a count/rate limiter)

A classic shell fork bomb `:(){ :|:& };:` is an already-running shell repeatedly calling
`clone()`/`fork()` on ITSELF. No new binary is exec'd after the first shell starts. The damage is
unbounded PID/thread COUNT, which is exactly what a cgroup `pids.max` (podPidsLimit) caps.

KubeArmor's enforcement primitives, from the shipped KubeArmorPolicy spec (raw GitHub source):

- `process:` -> `matchPaths` / `matchDirectories` / `matchPatterns` (allow/deny exec of named
  binaries or directories of binaries)
- `file:` -> file read/write access control (`readOnly`, paths/dirs)
- `network:` -> `matchProtocols` (TCP/UDP/ICMP)
- `capabilities:` -> Linux capability allow/deny
- `syscalls:` -> `matchSyscalls` / `matchPaths` (AUDIT-ONLY; cannot block)
- `action:` -> `Allow | Audit | Block`

**There is NO field for process count, thread count, fork rate, PID limit, ulimit, or rate
limiting in the enforcement policy.** CONFIRMED against the raw spec markdown. The enforcement
model is "which binaries/files/protocols/capabilities may be used," not "how many processes may
exist." KubeArmor has no equivalent of `pids.max`.

**What about the `rate: 10p1s` syntax seen in some KubeArmor material? UNCERTAIN -> resolved as
NOT an enforcement feature.** The `rate: 10p1s` / `20p1s` syntax appears in the KubeArmor
**Event Auditor design blog** (https://kubearmor.io/blog/kubearmor-event-auditor-design), which
describes a kprobe-based *telemetry/audit* throttle to keep observability overhead low. It is a
detection-side rate limit on how often events are emitted, in a design document, not a
KubeArmorPolicy enforcement field that throttles forks. It does not appear in the shipped
KubeArmorPolicy CRD spec. Do not represent it as fork-bomb prevention. CONFIRMED that it is
absent from the production policy spec.

**So what could KubeArmor actually do against a fork bomb?**

1. **Block exec of the shell itself** (e.g. `process: matchPaths: /bin/bash`, `/bin/sh`,
   `action: Block`, or an Allow-list that omits shells). This prevents the bomb from ever
   *starting* by denying the initial `execve` of the shell. CONFIRMED this is enforceable inline
   via LSM. But it is blunt: it kills all legitimate shell use in the workload, breaks
   exec-into-pod debugging, and does nothing if the bomb is launched by an already-running shell
   or any non-shell process that can call `fork()` (a Python `os.fork()` loop, a compiled binary,
   etc.). It blocks a *named binary*, not the *act of forking*.

2. **Audit-detect the fork storm** via the `syscalls:` section watching `clone`/`fork`. CONFIRMED
   audit-only; this generates alerts but does NOT block, making it functionally equivalent to
   Falco's detection role, not to the PID cap's prevention role.

**Verdict. CONFIRMED:** KubeArmor cannot prevent a fork bomb in the way a PID cap does. It can
only (a) refuse to start named binaries (including shells) inline, or (b) alert on fork syscalls
after the fact. Against an in-shell or in-process self-forking bomb, KubeArmor provides no inline
COUNT/RATE ceiling. The cgroup `pids.max` remains the correct and only true inline control.

---

## Q3. EKS AL2023 enforcement story (make-or-break). CONFIRMED with one caveat

KubeArmor enforcement depends on an enforcing LSM being present on the node. If neither BPF-LSM
nor AppArmor is enforcing, KubeArmor degrades to **audit-only**: per the FAQ, when no LSM is
available "only Observability will be available and Policy Enforcement won't be available," and
the action mapping becomes Allow -> Audit, Audit -> Audit, Block -> Audit (KubeArmor docs,
default_posture / FAQ).

**BPF-LSM on Amazon Linux 2023. CONFIRMED.** AL2023 ships kernel 6.1+ (originally released March
2023 with 6.1). Multiple corroborating sources state AL2023 has BPF-LSM enabled and activated by
default, and that AL2023 is the default EKS production distribution:
- AccuKnox: AL2023, Bottlerocket, RHEL-family >= 8.5, Oracle UEK > 7, and GKE COS "all have BPF
  LSM enabled and activated by default" (https://accuknox.com/blog/runtime-security-ebpf-bpf-lsm).
- BPF-LSM requires kernel > 5.7 with `CONFIG_BPF_LSM=y` and `CONFIG_DEBUG_INFO_BTF=y`, plus the
  LSM enabled via `CONFIG_LSM="...,bpf"` or boot parameter `lsm=...,bpf` (KubeArmor FAQ; kernel
  docs). AL2023's 6.1 kernel satisfies the kernel-version and BTF requirements.
- AL2023 enables SELinux in **permissive** mode by default and enables lockdown/yama (AWS AL2023
  kernel hardening docs). Permissive SELinux does NOT enforce, so the enforcing LSM relied upon
  is BPF-LSM, not SELinux.

**AppArmor on AL2023. UNCERTAIN / likely absent.** AL2023 is an SELinux-family distribution;
AppArmor is the Ubuntu/Debian family LSM and is not the AL2023 default. Do not rely on AppArmor
on AL2023. The enforcing path on AL2023 is BPF-LSM.

**Net for this workshop. CONFIRMED enforcement is plausible on AL2023, MUST be verified at build.**
On EKS AL2023 nodes, BPF-LSM should be present and KubeArmor should run in *enforcing* mode (not
audit-only). This is the make-or-break item and MUST be verified on the actual provisioned nodes,
because:
- "enabled by default" is reported by third-party (AccuKnox) and corroborated by AWS hardening
  docs, but the AWS KubeArmor blogs do not state AL2023+BPF-LSM enforcement in those exact words.
- The EKS AMI build and any custom `overrideBootstrapCommand` / nodeadm config could in principle
  alter the `lsm=` boot parameter.

**Verify-at-build commands (run on a provisioned AL2023 node / via the DaemonSet pod):**
- `cat /sys/kernel/security/lsm` -> the output MUST contain `bpf` for BPF-LSM enforcement.
- `karmor probe` (kubearmor-client) -> reports active LSM and whether enforcement is available
  per node. CONFIRMED this is the documented verification tool (FAQ; karmor-client repo).
- Apply a trivial `Block` KubeArmorPolicy (e.g. block `/bin/sleep` exec) and confirm the binary
  is actually denied, not merely audited. If it only audits, you are in audit-only mode.

Note: this contrasts with the AWS-documented **Bottlerocket** path, where the AWS Containers blog
explicitly walks through KubeArmor + Bottlerocket and Bottlerocket "supports SELinux and BPF-LSM"
(KubeArmor FAQ). If AL2023 enforcement ever proves flaky at build, Bottlerocket is the
AWS-blessed enforcing-LSM node OS, but switching node OS is a large change for this workshop.

---

## Q4. Deployment shape and Falco coexistence. CONFIRMED

**Deployment.** KubeArmor deploys as a per-node **DaemonSet** (the enforcement engine that loads
LSM/BPF programs), typically installed via the **KubeArmor Operator** (or Helm / `karmor install`).
Policy is expressed as the **KubeArmorPolicy** CRD (namespaced, per-workload; abbreviated KSP).
Related CRDs: **KubeArmorHostPolicy** (HSP, node/VM-level) and **KubeArmorClusterPolicy** (CSP).
CONFIRMED CRD names from docs (Security Policies KSP/HSP/CSP page).

**Closest-to-fork-bomb example policy (block the shell; the honest best KubeArmor can do).**
This denies execution of shells inline via LSM. It does NOT cap fork count; it prevents the bomb
from starting by refusing to exec a shell. Use only if the workload legitimately never needs a
shell.

```yaml
apiVersion: security.kubearmor.com/v1
kind: KubeArmorPolicy
metadata:
  name: block-shell-exec
  namespace: burn-demo
spec:
  selector:
    matchLabels:
      app: target-workload
  process:
    matchPaths:
    - path: /bin/bash
    - path: /bin/sh
    - path: /usr/bin/bash
    - path: /usr/bin/sh
  action: Block
  severity: 7
```

CAVEATS on this example: it blocks a named binary, not forking. A fork bomb launched from an
already-running shell, or from Python/Node/a compiled binary, still forks freely up to the cgroup
limit. This is precisely why the PID cap, not KubeArmor, is the fork-bomb control.
`apiVersion` is `security.kubearmor.com/v1` per the CRD group; CONFIRM the exact apiVersion
against `kubectl get crd kubearmorpolicies.security.kubearmor.com -o yaml` at build, since
Sandbox-project API groups can shift between releases.

An optional audit companion (detection only, like Falco) for the fork storm:

```yaml
apiVersion: security.kubearmor.com/v1
kind: KubeArmorPolicy
metadata:
  name: audit-fork-syscalls
  namespace: burn-demo
spec:
  selector:
    matchLabels:
      app: target-workload
  syscalls:
    matchSyscalls:
    - syscall:
      - clone
      - fork
      - vfork
  action: Block      # NOTE: syscalls are audit-only; this will be downgraded to Audit
  severity: 5
```

CONFIRMED: the `syscalls:` block is audit-only regardless of `action`, so this alerts but never
prevents. It overlaps Falco's job, not the PID cap's job.

**Falco coexistence. CONFIRMED safe in principle, VERIFY at build.** KubeArmor (LSM/BPF-LSM
enforcement) and Falco (eBPF syscall instrumentation for detection) are widely described as
complementary and commonly run together: KubeArmor enforces inline, Falco detects. They attach
at different layers (KubeArmor at LSM hooks, Falco via its eBPF probe / modern_ebpf driver on
tracepoints), so there is no inherent mutual exclusion the way two AppArmor profile loaders would
conflict. Risks to verify on the workshop nodes:
- Two eBPF-heavy agents increase per-node CPU/memory and BPF map/verifier load. Watch node
  resource headroom on the demo instance type.
- Both want broad host access (privileged DaemonSets, `/sys`, BTF). Confirm both come up healthy
  together (`karmor probe` clean AND Falco driver loaded) on the same node before the demo.
- No documented hard conflict was found; absence of a documented conflict is not proof. Run both
  on one provisioned node and confirm enforcement + detection both fire.

---

## Q5. Different-paths comparison

| Dimension | (a) kubelet `podPidsLimit` (cgroup `pids.max`) | (b) Falco 0.44.1 + Talon | (c) KubeArmor v1.7.3 |
|---|---|---|---|
| Mechanism | Kernel cgroup v2 `pids` controller caps live PID/thread count per pod | eBPF syscall detection rule matches fork-bomb cmdline; Talon kills pod | LSM (BPF-LSM on AL2023) inline allow/deny of exec/file/net/caps; syscalls audit-only |
| Prevent vs detect-respond | PREVENT (hard count ceiling) | DETECT then RESPOND (kill) | PREVENT for named-binary exec/file/net; for fork COUNT/RATE: cannot prevent (no such field), can only audit |
| Inline vs reactive latency | Inline, zero detection latency; kernel refuses `fork` at the cap before it returns | Reactive; detection + kill latency a fast bomb can outrun | Inline for the operations LSM covers (exec deny is pre-`execve`); for forks there is no inline control, only after-the-fact audit |
| EKS AL2023 viability | CONFIRMED working in repo via eksctl `overrideBootstrapCommand` + nodeadm `spec.kubelet.config.podPidsLimit: 1024` | CONFIRMED working in repo (Falco 0.44.1 + Talon) | Enforcement plausible (BPF-LSM default on AL2023) but MUST verify at build (`/sys/kernel/security/lsm` contains `bpf`, `karmor probe`). Risk of audit-only if LSM not enforcing |
| Blast radius | Tight: only the offending pod's cgroup; node and other pods unaffected. The thing that keeps the node alive | Pod-level kill; brief window where bomb runs before kill | Workload-scoped via label selector; blocking a shell breaks legit shell use; no fork ceiling so a bomb still consumes up to cgroup limit |
| Demo value | High but quiet: the bomb fizzles instantly, "nothing happens" (the point is the node survives). Pairs well with showing `pids.max` | High drama: bomb detected, alert fires, pod gets terminated; visible response loop | Medium for fork bomb (honest story is "it does not solve this"); HIGH for other attacks: live inline block of a forbidden binary exec / secret-file read / egress is a clean CNCF-native prevention demo |

**Where KubeArmor genuinely adds something beyond PID cap + Falco:**
- **CNCF-native INLINE prevention for non-fork attacks.** Falco only detects; the PID cap only
  caps PIDs. KubeArmor is the only one of the three that can *inline-block* an arbitrary
  forbidden action: exec of an attacker-dropped binary, reading `/var/run/secrets/...` or
  `/etc/shadow`, writing to a protected path, or opening egress. For an AI-agent workshop where
  the threat is "the agent runs something it should not," KubeArmor's allow-list-of-binaries and
  file/network hardening is a strong, demonstrable inline control that neither podPidsLimit nor
  Falco provides.
- A least-privilege "Allow-list" posture (default-deny exec/file) that turns the agent's
  container into a tightly sandboxed surface, enforced in-kernel.

**Where KubeArmor is redundant or weaker:**
- **Fork bomb specifically: weaker.** It has no count/rate ceiling. Blocking the shell is blunt
  and bypassable (any forking process defeats it). The PID cap already solves this correctly and
  inline. KubeArmor adds nothing to the fork-bomb defense that the PID cap does not already do
  better.
- **Detection overlap with Falco.** KubeArmor's audit alerts overlap Falco's detection role;
  running both purely for fork-detection telemetry is redundant.

---

## Recommendation

**Do NOT introduce KubeArmor as a fork-bomb defense.** For the fork bomb, the kubelet
`podPidsLimit` (cgroup `pids.max`) is and should remain the single true inline block, with Falco
+ Talon as the reactive/detection theater. KubeArmor cannot match the PID cap here because it has
no process-count/fork-rate enforcement primitive (CONFIRMED against the shipped policy spec), and
its only fork-relevant moves are blocking the shell binary (blunt, bypassable) or auditing fork
syscalls (detection, not prevention). Adding it to the fork-bomb story would muddy a clean,
already-verified narrative.

**DO consider KubeArmor as a DIFFERENT-attack option** if the workshop wants a CNCF-native
*inline prevention* demo for the AI-agent threat model: default-deny binary execution, blocking
the agent from reading mounted secrets, or blocking unexpected egress, all enforced in-kernel via
BPF-LSM. That is a capability neither podPidsLimit nor Falco offers, and it is a credible
"prevent, do not just detect" counterpoint to the Falco detect-and-respond station. Position it as
"hardening the agent container," not "stopping the fork bomb."

**If KubeArmor is pursued, verify at build (all on the actual provisioned EKS AL2023 nodes):**
1. `cat /sys/kernel/security/lsm` on a node -> output MUST contain `bpf`. If not, KubeArmor is
   audit-only and the prevention story collapses.
2. `karmor probe` -> confirms active LSM and that enforcement (not just audit) is available per
   node.
3. Apply a trivial `action: Block` KubeArmorPolicy (block exec of a harmless binary like
   `/bin/sleep`) and confirm the exec is actually DENIED at runtime, not merely alerted. This
   distinguishes enforcing mode from audit-only mode end to end.
4. Confirm the exact CRD apiVersion/group: `kubectl get crd kubearmorpolicies.security.kubearmor.com -o yaml`
   (Sandbox-project API surface; do not assume `security.kubearmor.com/v1` without checking).
5. Pin and record versions: KubeArmor v1.7.3 (current as of 2026-05-29) and the operator/Helm
   chart version, into `VERSIONS.lock`.
6. Run KubeArmor and Falco together on one node and confirm BOTH stay healthy (KubeArmor enforcing
   per `karmor probe`, Falco driver loaded and rules firing) and the node has CPU/memory headroom
   for two eBPF agents on the chosen instance type.
7. Confirm the `overrideBootstrapCommand` / nodeadm NodeConfig that delivers `podPidsLimit` does
   not alter the `lsm=` boot parameter in a way that disables BPF-LSM (the two controls must
   coexist on the same node).

CONFIRMED claims: CNCF Sandbox status and acceptance date; v1.7.3 latest; LSM enforcement set
(AppArmor/BPF-LSM/SELinux) with BPF-LSM preferred; inline LSM-hook enforcement for
exec/file/net/caps; syscalls audit-only; no process-count/fork-rate field in the policy spec;
audit-only fallback when no enforcing LSM; AL2023 ships kernel 6.1 with BPF-LSM enabled by default
and SELinux permissive; CRD names KSP/HSP/CSP; DaemonSet + Operator shape.

UNCERTAIN claims (flagged inline): exact AL2023 enforcement on the specific provisioned AMI
(must verify via `/sys/kernel/security/lsm` and `karmor probe`); AppArmor presence on AL2023
(treat as absent); precise current CRD apiVersion/group (verify against the live CRD); Falco +
KubeArmor resource coexistence on the chosen instance type (verify on a real node).
