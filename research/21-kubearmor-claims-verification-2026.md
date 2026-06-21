# 21. KubeArmor Fork-Bomb Claims: Citation-Hardened Verification

ABOUTME: Adversarial, citation-hardened verification of whether CNCF KubeArmor can stop a fork
ABOUTME: bomb, resolving the disagreement between research/17 (it cannot) and a co-presenter doc.

## Verification Method

Web research conducted 2026-06-21. Every claim below carries a direct quote and a primary-source
URL. Where a docs page (docs.kubearmor.io, kubearmor.io/blog) returns HTTP 403 to automated fetch,
the same authoritative content was read from the raw GitHub markdown those pages are generated
from, or from the GitHub API, and the URL is noted as such. Version, maturity, kernel-config, and
runtime-LSM facts were pulled from source-of-truth artifacts (the KubeArmor GitHub repo, the CNCF
project page, the GitHub releases API, AWS AL2023 docs, and a captured AL2023 kernel config and
runtime `/sys/kernel/security/lsm` dump), not from memory.

This document was written to be adversarial. The explicit goal was to find ANY way KubeArmor could
impose a process-count, thread-count, fork-rate, or PID ceiling. No such mechanism exists in the
shipped product. The negative is proven below with the policy spec itself.

Primary sources (source-of-truth markdown and APIs):

- KubeArmor container policy spec (raw): https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md
- KubeArmor FAQ (raw): https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/FAQ.md
- KubeArmor container policy spec (rendered): https://docs.kubearmor.io/kubearmor/documentation/security_policy_specification
- KubeArmor Runtime Enforcer doc: https://docs.kubearmor.io/kubearmor/quick-links/kubearmor_overview/runtime_enforcer
- KubeArmor Event Auditor design blog (the `rate:` syntax source): https://kubearmor.io/blog/kubearmor-event-auditor-design
- KubeArmor releases (GitHub API): https://github.com/kubearmor/KubeArmor/releases
- CNCF project page: https://www.cncf.io/projects/kubearmor/
- AWS AL2023 kernel hardening: https://docs.aws.amazon.com/linux/al2023/ug/kernel-hardening.html
- Captured AL2023 kernel config + runtime LSM dump (nyrahul/linux-kernel-configs): https://github.com/nyrahul/linux-kernel-configs/tree/main/Amazon%20Linux%202023/6.1.19-30.43.amzn2023.x86_64
- Linux kernel LSM-BPF docs: https://docs.kernel.org/bpf/prog_lsm.html
- AccuKnox eBPF/BPF-LSM blog (distro BPF-LSM defaults): https://accuknox.com/blog/runtime-security-ebpf-bpf-lsm

---

## Resolution of the disagreement

research/17 concluded KubeArmor CANNOT stop a fork bomb. The co-presenter (Whitney) doc stated
KubeArmor "actually stops the fork bomb." research/17 is correct, with one charitable
reading of the co-presenter claim that must be stated precisely so it is not overstated:

- KubeArmor has NO process-count / thread-count / fork-rate / PID-limit / ulimit / rate-limit
  enforcement field. It cannot impose a count or rate ceiling on `fork()`/`clone()`. CONFIRMED
  against the shipped policy spec (Claim 1).
- The ONLY fork-relevant things KubeArmor can do are (a) inline-block the `execve` of a named
  binary, e.g. the shell itself, which prevents a shell fork bomb from ever STARTING but is blunt
  and trivially bypassed by any already-running shell or any non-shell forker (a Python
  `os.fork()` loop, a compiled binary), and (b) audit (alert on) `clone`/`fork` syscalls, which is
  detection only. CONFIRMED (Claims 2 and 5).

So the honest statement is: KubeArmor can refuse to start the shell binary that a textbook shell
fork bomb relies on; it cannot cap the act of forking. That is a "block the launcher" control, not
a "cap the resource" control, and it collapses the moment the forker is not a freshly-exec'd shell.
A cgroup `pids.max` (kubelet `podPidsLimit`) is the only true inline fork-bomb ceiling in the
stack. The co-presenter phrasing "actually stops the fork bomb" is therefore misleading and should
not be used unqualified.

---

## Claim-by-claim verification table

| # | Claim | Verdict | Quote | Source URL |
|---|---|---|---|---|
| 1 | The shipped KubeArmorPolicy has NO field for process count, thread count, fork rate, PID limit, ulimit, or rate limiting. | CONFIRMED | Process targets are "matchPaths, matchDirectories, matchPatterns"; File targets "matchPaths, matchDirectories, matchPatterns"; Network "matchProtocols"; Capabilities "matchCapabilities"; Syscalls "matchSyscalls and matchPaths". No count/rate/PID/ulimit field appears anywhere in the spec. | https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md |
| 2 | The `syscalls:` section is AUDIT-ONLY regardless of `action:`. | CONFIRMED | "For System calls monitoring, we only support audit mode no matter what the action is set to." | https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md |
| 3 | Enforcement is via LSMs, inline at LSM hooks (pre-operation deny), not post-hoc kill. | CONFIRMED | FAQ: "It maps YAML rules to LSMs (apparmor, bpf-lsm) rules..." Runtime Enforcer doc: "LSM hooks are applied inline to the kernel code processing... the enforcement is inline to the access attempt, and any blocking/denial action can be performed without TOCTOU problems," at hooks "before a file is opened, before a program is executed, before a capability is used." | https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/FAQ.md ; https://docs.kubearmor.io/kubearmor/quick-links/kubearmor_overview/runtime_enforcer |
| 4 | `rate: 10p1s` is an Event-Auditor telemetry throttle, NOT a KubeArmorPolicy enforcement field. | CONFIRMED | Event Auditor design blog: "The rate-limit of 10p1s is depicted in an active-scanning policy scenario, but in reality the scanning speed will be much faster." It is a kprobe telemetry-emission throttle in a design doc. The string `rate` does NOT appear anywhere in the production KubeArmorPolicy spec. | https://kubearmor.io/blog/kubearmor-event-auditor-design ; (absence) https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md |
| 5a | KubeArmor can inline-block exec of the shell binary itself (blunt; bypassed by an already-running shell or a non-shell forker). | CONFIRMED | Process enforcement is by named binary: "matchPaths, matchDirectories, matchPatterns" with `action: Block`, enforced inline "before a program is executed." It blocks a NAMED BINARY, not the act of forking. | https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md ; https://docs.kubearmor.io/kubearmor/quick-links/kubearmor_overview/runtime_enforcer |
| 5b | KubeArmor can audit `clone`/`fork` (detection only, no ceiling). | CONFIRMED | "For System calls monitoring, we only support audit mode no matter what the action is set to." Watching `clone`/`fork` alerts but never blocks and never caps. | https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md |
| 6a | AL2023 kernel 6.1 ships BPF-LSM compiled in. | CONFIRMED | Captured AL2023 6.1.19 config: `CONFIG_BPF_LSM=y`, `CONFIG_BPF=y`, `CONFIG_BPF_SYSCALL=y`, `CONFIG_DEBUG_INFO_BTF=y`. | https://github.com/nyrahul/linux-kernel-configs/tree/main/Amazon%20Linux%202023/6.1.19-30.43.amzn2023.x86_64 |
| 6b | BPF-LSM is enabled in the LSM list by default on AL2023. | CONFIRMED | Captured AL2023 6.1.19 config: `CONFIG_LSM="lockdown,yama,loadpin,safesetid,integrity,selinux,smack,tomoyo,apparmor,bpf"` (bpf present in the ordered list). Runtime confirmation: `cat /sys/kernel/security/lsm` -> `lockdown,capability,yama,safesetid,selinux,bpf` (bpf active). | https://github.com/nyrahul/linux-kernel-configs/tree/main/Amazon%20Linux%202023/6.1.19-30.43.amzn2023.x86_64 |
| 6c | Corroboration that AL2023 has BPF-LSM enabled by default. | CONFIRMED | AccuKnox: Amazon Linux 2022 "had BPF-LSM enabled by default... later renamed Amazon Linux 2023 (AL2023) and became the default production distribution on EKS." | https://accuknox.com/blog/runtime-security-ebpf-bpf-lsm |
| 6d | Verify-at-build method. | CONFIRMED (method) | KubeArmor verification: `cat /sys/kernel/security/lsm` (output must contain `bpf`) and `karmor probe`. | https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/FAQ.md |
| 7a | CNCF maturity is Sandbox with a fixed acceptance date. | CONFIRMED | "KubeArmor was accepted to CNCF on November 16, 2021 at the Sandbox maturity level." | https://www.cncf.io/projects/kubearmor/ |
| 7b | Latest stable version is v1.7.3 (2026-05-29). | CONFIRMED | GitHub releases API: `v1.7.3 | published 2026-05-29T10:40:58Z`. Newer tag `v1.7.4-rc1` (2026-06-08) exists but is a release candidate, not a stable release. | https://github.com/kubearmor/KubeArmor/releases |
| -- | No-LSM fallback degrades enforcement to audit-only. | CONFIRMED | FAQ: "If Block policy is used and there are no supported enforcement mechanism on the platform then the policy enforcement wouldn't be observed. But we will still be able to see the observability data for the applied Block policy." | https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/FAQ.md |

---

## Claim 1 detail: enumerate the ACTUAL enforcement primitives, prove the negative

The shipped KubeArmorPolicy spec exposes exactly these enforcement targets, and nothing else
resembling a resource ceiling:

- `process:` -> `matchPaths`, `matchDirectories`, `matchPatterns` (options: `ownerOnly`,
  `recursive`, `fromSource`). Allow/deny exec of NAMED binaries or directories of binaries.
- `file:` -> `matchPaths`, `matchDirectories`, `matchPatterns` (options: `readOnly`, `ownerOnly`,
  `fromSource`). File read/write access control.
- `network:` -> `matchProtocols`. Values: "TCP, UDP, and ICMP" (case-insensitive `tcp, udp, icmp`).
- `capabilities:` -> `matchCapabilities`. Linux capability allow/deny.
- `syscalls:` -> `matchSyscalls`, `matchPaths` (options: `fromSource`, `recursive`). AUDIT-ONLY.
- `action:` -> "Allow, Audit, or Block" (the only three values).

Quote (spec): process/file/network/capabilities/syscalls match types as listed above; action
values "Allow, Audit, or Block."
Source: https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md

Proof of the negative: there is NO `pids`, `count`, `max`, `limit`, `rate`, `fork`, `thread`, or
`ulimit` enforcement field anywhere in the policy spec. The enforcement model answers "WHICH
binaries / files / protocols / capabilities may be used," never "HOW MANY processes may exist or
how fast they may spawn." KubeArmor has no equivalent of cgroup `pids.max`. This is the structural
reason it cannot be a fork-bomb COUNT/RATE ceiling, and it is verifiable directly from the spec
markdown, not inferred. CONFIRMED.

## Claim 2 detail: syscalls are audit-only regardless of action

A `syscalls:` block that lists `clone`, `fork`, `vfork` with `action: Block` is silently treated as
Audit. The spec is explicit: "For System calls monitoring, we only support audit mode no matter
what the action is set to." So the syscall path can ALERT on a fork storm but can never PREVENT or
THROTTLE it. This is functionally Falco's detection role, not the PID cap's prevention role.
CONFIRMED.
Source: https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md

## Claim 3 detail: inline LSM-hook enforcement, not post-hoc kill

KubeArmor compiles policy down to LSM rules (AppArmor or BPF-LSM) and the kernel evaluates them at
LSM hooks before the guarded operation completes. The Runtime Enforcer doc states LSM hooks fire
"before a file is opened, before a program is executed, before a capability is used," that "LSM
hooks are applied inline to the kernel code processing," and that "the enforcement is inline to the
access attempt, and any blocking/denial action can be performed without TOCTOU problems." With
BPF-LSM, eBPF bytecode attached at those hooks reads rule data from eBPF maps and returns a denial
inline (kernel LSM-BPF docs). This is pre-operation deny at the same hook layer SELinux/AppArmor
use, NOT a watcher that kills a process after the fact. CONFIRMED for the operations LSM hooks
cover (exec, file open, capability, network). It does NOT cover counting forks, because no LSM hook
in KubeArmor's policy model imposes a count.
Sources: https://docs.kubearmor.io/kubearmor/quick-links/kubearmor_overview/runtime_enforcer ;
https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/FAQ.md ;
https://docs.kernel.org/bpf/prog_lsm.html

## Claim 4 detail: the `rate: 10p1s` red herring, traced to source

The `rate: 10p1s` / `rate: 20p1s` syntax that appears in some KubeArmor material comes from the
KubeArmor **Event Auditor design blog**, where it is a kprobe-based TELEMETRY throttle controlling
how often audit events are EMITTED, to keep observability overhead low. The blog itself frames it
as a scanning/telemetry rate: "The rate-limit of 10p1s is depicted in an active-scanning policy
scenario, but in reality the scanning speed will be much faster." It is a detection-side emission
limit in a design document. It is NOT a KubeArmorPolicy field, and the token `rate` does not exist
in the production policy spec. It does not throttle `fork()`. Anyone citing `rate: 10p1s` as
fork-bomb prevention is conflating an Event-Auditor telemetry knob with policy enforcement.
CONFIRMED that it is absent from the production policy spec.
Sources: https://kubearmor.io/blog/kubearmor-event-auditor-design (origin) ;
https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md (absence)

## Claim 5 detail: the only two fork-relevant moves, neither is a ceiling

1. Inline-block exec of the shell binary. A textbook shell fork bomb `:(){ :|:& };:` needs a shell
   process. A policy `process: matchPaths: [/bin/bash, /bin/sh, ...]` with `action: Block` denies
   the initial `execve` of the shell inline via LSM, so the bomb never starts. CONFIRMED
   enforceable. But it blocks a NAMED BINARY, not forking: it breaks all legitimate shell use and
   exec-into-pod debugging, and it does nothing against a bomb launched from an already-running
   shell or from a non-shell forker (a Python `os.fork()` loop, Node, a compiled binary). It is a
   "block the launcher" control, not a "cap the resource" control.
2. Audit `clone`/`fork`. CONFIRMED audit-only (Claim 2): generates alerts, blocks nothing, caps
   nothing.

Neither imposes a count or rate ceiling on forking. CONFIRMED.
Sources: https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md ;
https://docs.kubearmor.io/kubearmor/quick-links/kubearmor_overview/runtime_enforcer

## Claim 6 detail: EKS AL2023 enforcement is viable, and this is now PROVEN from a captured node

This was the make-or-break item in research/17, previously CONFIRMED from third-party report plus
kernel-version reasoning. It is now CONFIRMED from a captured AL2023 6.1.19 node artifact set:

- Compile-time: `CONFIG_BPF_LSM=y`, `CONFIG_BPF=y`, `CONFIG_BPF_SYSCALL=y`,
  `CONFIG_DEBUG_INFO_BTF=y` (all BPF-LSM kernel prerequisites satisfied).
- LSM enabled by default: `CONFIG_LSM="lockdown,yama,loadpin,safesetid,integrity,selinux,smack,tomoyo,apparmor,bpf"`
  (bpf present in the ordered LSM list, so it is active without a boot-param override).
- Runtime confirmation on the node: `cat /sys/kernel/security/lsm` ->
  `lockdown,capability,yama,safesetid,selinux,bpf` (bpf is live at runtime).

So on AL2023, KubeArmor can run in ENFORCING mode via BPF-LSM rather than degrading to audit-only.
Note the AWS kernel-hardening doc itself lists only SELinux (Permissive), lockdown, and yama as the
"Security Models" it calls out, and does NOT mention BPF-LSM in that section; the BPF-LSM evidence
comes from the kernel config and the runtime LSM dump above plus AccuKnox corroboration, which is
why verify-at-build still matters on the SPECIFIC provisioned AMI.

Verify-at-build (run on the actual provisioned EKS AL2023 node / DaemonSet pod):
- `cat /sys/kernel/security/lsm` -> output MUST contain `bpf`.
- `karmor probe` -> reports active LSM and whether enforcement (not just audit) is available.
- Apply a trivial `action: Block` policy (e.g. block exec of `/bin/sleep`) and confirm the exec is
  DENIED at runtime, not merely alerted. If it only audits, the node is in audit-only mode and the
  prevention story collapses.

SELinux on AL2023 is Permissive by default ("AL2023 enables SELinux in Permissive mode by
default... The Lockdown Linux Security Module (LSM) and yama modules are also enabled," AWS kernel
hardening doc), so SELinux does NOT enforce; the enforcing path relied upon is BPF-LSM. AppArmor:
the AL2023 LSM list includes `apparmor` as a compiled-in module, but AL2023 is SELinux-family and
does not ship loaded AppArmor profiles; do not rely on AppArmor on AL2023, rely on BPF-LSM.
CONFIRMED (with the verify-at-build caveat scoped to the specific AMI).
Sources: https://github.com/nyrahul/linux-kernel-configs/tree/main/Amazon%20Linux%202023/6.1.19-30.43.amzn2023.x86_64 ;
https://docs.aws.amazon.com/linux/al2023/ug/kernel-hardening.html ;
https://accuknox.com/blog/runtime-security-ebpf-bpf-lsm ;
https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/FAQ.md

## Claim 7 detail: maturity and version

- CNCF Sandbox, accepted November 16, 2021. Quote: "KubeArmor was accepted to CNCF on November 16,
  2021 at the Sandbox maturity level." Treat the API surface as Sandbox-stable, not LTS-guaranteed;
  re-check the CRD apiVersion/group at build (`kubectl get crd kubearmorpolicies.security.kubearmor.com -o yaml`).
  Source: https://www.cncf.io/projects/kubearmor/
- Latest stable release: v1.7.3, published 2026-05-29 (GitHub releases API). A `v1.7.4-rc1` tag
  exists (2026-06-08) but is a release candidate, not a GA release; pin v1.7.3 for the workshop.
  Source: https://github.com/kubearmor/KubeArmor/releases

---

## Where KubeArmor genuinely adds value (DIFFERENT attack, NOT fork-bomb defense)

KubeArmor is the only control in this stack that can INLINE-BLOCK an arbitrary forbidden action in
kernel before it happens, via BPF-LSM on AL2023. In an AI-agent threat model ("the agent runs or
reads or sends something it should not"), the demonstrable, citable capabilities are:

- Inline prevention of attacker-binary execution. A default-deny / allow-list `process:` policy
  (`matchPaths` / `matchDirectories` / `matchPatterns`, `action: Block`) refuses `execve` of any
  binary the agent was not whitelisted to run, enforced pre-exec at the LSM hook. This stops an
  agent from running a dropped or unexpected binary. (process enforcement + inline LSM hook:
  https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md ;
  https://docs.kubearmor.io/kubearmor/quick-links/kubearmor_overview/runtime_enforcer)
- Inline prevention of secret/credential file reads. A `file:` policy can deny reads of
  `/var/run/secrets/...`, `/etc/shadow`, mounted token paths, etc. (with `readOnly` / `ownerOnly` /
  `fromSource` scoping), blocked at the file-open LSM hook before the read returns. (file
  enforcement:
  https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md)
- Network egress restriction. A `network: matchProtocols` policy constrains the agent to permitted
  protocols (TCP/UDP/ICMP), reducing exfiltration/egress surface. (network enforcement:
  https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md)
- Capability tightening. `capabilities: matchCapabilities` denies dangerous Linux capabilities the
  agent container should never use. (capabilities enforcement:
  https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md)

Position KubeArmor as "harden the agent container with in-kernel least-privilege" (a PREVENT
control that Falco's detect-only model and the PID cap do not provide), NOT as "stop the fork
bomb." For the fork bomb specifically, the kubelet `podPidsLimit` (cgroup `pids.max`) remains the
single correct inline ceiling.

---

## Confidence summary

CONFIRMED (hard primary-source quote each): no count/rate/PID/ulimit enforcement field in the
shipped policy spec; the enumerated enforcement primitives; syscalls are audit-only regardless of
action; inline LSM-hook pre-operation enforcement; `rate: 10p1s` is an Event-Auditor telemetry
throttle and is absent from the policy spec; the two fork-relevant moves (block named shell exec;
audit clone/fork) and that neither is a ceiling; AL2023 6.1 ships BPF-LSM compiled in, enabled in
the LSM list, and active at runtime (`/sys/kernel/security/lsm` contains `bpf`); SELinux permissive
on AL2023; no-LSM fallback degrades to audit-only; CNCF Sandbox accepted 2021-11-16; v1.7.3 latest
stable (2026-05-29); KubeArmor's genuine value as an inline prevention control for non-fork
attacks.

UNCERTAIN (scoped, verify at build): enforcement on the SPECIFIC provisioned EKS AL2023 AMI (the
AWS hardening doc does not itself name BPF-LSM; confirm via `cat /sys/kernel/security/lsm` and a
live `action: Block` test on the actual node); the exact current CRD apiVersion/group (Sandbox API
surface can shift; check against the live CRD); whether a custom `overrideBootstrapCommand` /
nodeadm config alters the `lsm=` boot parameter in a way that disables BPF-LSM.

Bottom line for Whitney: KubeArmor does not "stop the fork bomb" in the sense of capping
fork/process count; it has no such field (proven from the spec). It can only refuse to launch the
shell binary (blunt, bypassable) or alert on fork syscalls (detection only). research/17 stands.
The cgroup `pids.max` (podPidsLimit) is the fork-bomb control; KubeArmor's place in the workshop is
inline prevention of a DIFFERENT attack (binary exec, secret reads, egress).
