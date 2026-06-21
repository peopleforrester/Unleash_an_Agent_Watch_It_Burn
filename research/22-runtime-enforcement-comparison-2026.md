# 22. Runtime Enforcement Comparison: Four Controls, One Fork Bomb (Synthesis)

ABOUTME: Decision-grade comparison of four Kubernetes runtime controls (podPidsLimit, Falco,
ABOUTME: KubeArmor, Tetragon) for the "Watch It Burn" workshop, with the honest fork-bomb verdict.

## Verification Method

Web research conducted 2026-06-21. Every version number, kernel-mechanism statement, CRD/policy
field, CNCF maturity level, and EKS-viability claim below is taken from the cited primary source,
not from memory. This document is a standalone synthesis: it re-verifies the same facts the
companion KubeArmor spike (`research/17-kubearmor-forkbomb-2026.md`) covers, against primary
sources, so the comparison stands on its own. CONFIRMED means a primary source states it directly;
UNCERTAIN means it must be verified on the actual provisioned nodes or could not be pinned to a
primary source.

Primary sources consulted (all read or searched 2026-06-21):

- Linux kernel cgroup v2 docs (PIDs controller): https://docs.kernel.org/admin-guide/cgroup-v2.html
- Kubernetes Pod PID limits doc: https://kubernetes.io/docs/concepts/policy/pid-limiting/
- Kubelet config API (PodPidsLimit field): https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/
- Falco GitHub releases (0.44.1 / 0.44.0): https://github.com/falcosecurity/falco/releases
- Falco changelog: https://falco.org/docs/reference/changelog/
- Falco 0.44.0 release blog: https://falco.org/blog/falco-0-44-0/
- Falco kernel event sources (drivers): https://falco.org/docs/concepts/event-sources/kernel/
- Falco Talon repo (response engine): https://github.com/falcosecurity/falco-talon
- Falco Talon v0.1.0 blog: https://falco.org/blog/falco-talon-v0-1-0/
- Falcosidekick Datadog output doc: https://github.com/falcosecurity/falcosidekick/blob/master/docs/outputs/datadog.md
- Falco CNCF graduation announcement (2024-02-29): https://www.cncf.io/announcements/2024/02/29/cloud-native-computing-foundation-announces-falco-graduation/
- CNCF projects list (Falco/Cilium Graduated): https://www.cncf.io/projects/
- KubeArmor security policy spec (raw): https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/security_policy_specification.md
- KubeArmor FAQ (raw): https://raw.githubusercontent.com/kubearmor/KubeArmor/main/getting-started/FAQ.md
- KubeArmor CNCF project page: https://www.cncf.io/projects/kubearmor/
- Tetragon enforcement concept: https://tetragon.io/docs/concepts/enforcement/
- Tetragon selectors (Override / Signal actions): https://tetragon.io/docs/concepts/tracing-policy/selectors/
- Tetragon TracingPolicy reference: https://tetragon.io/docs/reference/tracing-policy/
- Tetragon Kubernetes install (DaemonSet, standalone): https://tetragon.io/docs/installation/kubernetes/
- Tetragon Prometheus metrics doc: https://tetragon.io/docs/installation/metrics/
- Tetragon issue #419 (syscall blocking = SIGKILL): https://github.com/cilium/tetragon/issues/419
- Linux kernel LSM BPF docs: https://docs.kernel.org/bpf/prog_lsm.html
- AWS AL2023 kernel hardening: https://docs.aws.amazon.com/linux/al2023/ug/kernel-hardening.html

Note on access: `docs.kubearmor.io` and `kubearmor.io/blog` return HTTP 403 to automated fetch;
KubeArmor facts were read from the raw GitHub markdown those pages are generated from and from the
companion spike's verification. The Falco hosted changelog page was stale (showed 0.42.1 as
"latest"); the GitHub Releases page is the source of truth for 0.44.1.

---

## Bottom line up front (read this if you read nothing else)

For the **fork bomb specifically**, the kubelet `podPidsLimit` (cgroup v2 `pids.max`) is the
**only true inline fork-count ceiling** in this stack. The kernel refuses the `fork()`/`clone()`
at the cap and returns `-EAGAIN` before a new task exists. CONFIRMED from the kernel cgroup v2 doc:
"it is not possible to violate a cgroup PID policy through fork() or clone(). These will return
-EAGAIN if the creation of a new process would cause a cgroup policy to be violated."

The three eBPF projects do **not** give you that same guarantee against a self-replicating fork
bomb:

- **Falco + Talon** = DETECT then RESPOND. Falco observes the syscall, emits an alert, Talon kills
  the pod. There is a detection-plus-reaction window a fast bomb runs inside. It is not an inline
  fork ceiling.
- **Tetragon** = inline enforcement exists, but its reliable enforcement action against forking is
  `SIGKILL`, which Tetragon's own docs say "does not always stop the operation," i.e. the syscall
  can still complete. Its truly synchronous action (`Override`) only works on kernel functions
  marked `ALLOW_ERROR_INJECTION()`, which is not a documented fork-bomb control. So Tetragon is a
  post-event kill for this case, not a count ceiling.
- **KubeArmor** = inline LSM deny, but it has **no process-count / fork-rate field at all**. The
  closest it can do is refuse to exec a shell binary (blunt, bypassable) or audit-only alert on
  `clone`/`fork`. It does essentially nothing as a fork-count ceiling.

The eBPF projects earn their place against **other** attacks (an attacker binary exec'ing, reading
mounted secrets, opening egress), where inline LSM/eBPF deny is exactly the right tool and a PID
cap is irrelevant. That is the honest division of labor below.

---

## The four controls, briefly (CONFIRMED versions and mechanisms)

1. **kubelet `podPidsLimit` -> cgroup v2 `pids.max`.** A kubelet node-level setting
   (`PodPidsLimit` in the kubelet config, or `--pod-max-pids`) that programs the per-pod cgroup
   `pids` controller. The kernel enforces a hard count ceiling at `fork`/`clone` time. CONFIRMED:
   Kubernetes pid-limiting doc ("You specify this limit at the node level ... Once the limit is
   hit, workload will start experiencing failures when trying to get a new PID") and cgroup v2
   kernel doc (`-EAGAIN` at the cap). Not a project, not a DaemonSet: it is a kernel primitive the
   kubelet configures.

2. **Falco 0.44.1 (+ Falco Talon).** CONFIRMED: Falco 0.44.1 released 2026-06-11, drivers
   `10.2.0+driver` (GitHub Releases). 0.44.0 (2026-05-26) completed removal of the legacy eBPF
   probe, gVisor engine, and gRPC output; the **modern eBPF probe** and **kernel module** are the
   surviving drivers (Falco 0.44.0 blog; kernel event sources doc). Falco is a syscall-level
   **detection** engine: it instruments syscalls via its modern-eBPF driver and matches rules,
   emitting alerts. It does not block. **Falco Talon** is the separate **response engine** that
   consumes Falco events and takes actions (terminate/delete pod, label, apply NetworkPolicy);
   CONFIRMED from the falco-talon repo and v0.1.0 blog ("react to events from Falco in
   milliseconds," actions include terminate pod).

3. **KubeArmor v1.7.3.** CONFIRMED: latest release v1.7.3 (2026-05-29); CNCF **Sandbox** (accepted
   2021-11-16). Inline allow/deny of process exec, file access, network protocol, and Linux
   capabilities via LSM (BPF-LSM preferred, AppArmor/SELinux fallback). CONFIRMED from the raw
   policy spec: its enforcement primitives are `process`/`file`/`network`/`capabilities` with
   `action: Allow|Audit|Block`. **Syscall monitoring is audit-only:** "For System calls
   monitoring, we only support audit mode no matter what the action is set to" (raw policy spec).
   No process-count / thread-count / fork-rate / PID-limit field exists.

4. **Tetragon.** A Cilium **sub-project** (Cilium is CNCF **Graduated**, accepted 2021-10-13;
   Tetragon is not separately listed on the CNCF projects page, so treat its standalone maturity as
   "Graduated-project sub-component," not an independently graduated project; UNCERTAIN as an
   independent maturity badge). CONFIRMED: runs standalone as a DaemonSet without Cilium CNI
   (`helm install tetragon cilium/tetragon -n kube-system`; install doc). Enforcement via
   **TracingPolicy** CRD with two actions (Tetragon enforcement doc):
   - **Override** = return-value override, synchronous/inline: "the function will never be executed
     and, instead, a value (typically an error) will be returned to the caller." Requires kernel
     `CONFIG_BPF_KPROBE_OVERRIDE` and only works on functions annotated `ALLOW_ERROR_INJECTION()`
     (listed in `/sys/kernel/debug/error_injection/list`). CONFIRMED from the selectors doc.
   - **Signal/SIGKILL** = asynchronous post-event kill: "sending a `SIGKILL` signal does not always
     stop the operation being performed by the process that triggered the operation" and "a
     `SIGKILL` sent in a `write()` system call does not guarantee that the data will not be
     written." Tetragon recommends combining Signal with Override. CONFIRMED from enforcement doc.

---

## 1. Comparison matrix

Every cell is CONFIRMED from a primary source unless marked UNCERTAIN.

| Dimension | podPidsLimit (cgroup `pids.max`) | Falco 0.44.1 (+ Talon) | KubeArmor v1.7.3 | Tetragon |
|---|---|---|---|---|
| **Kernel mechanism + attach layer** | cgroup v2 **`pids` controller**; kernel counts tasks in the pod cgroup and refuses `fork`/`clone` at the cap. (cgroup v2 doc) | **eBPF on syscalls** via modern-eBPF driver (or kernel module); observe-only instrumentation. (Falco kernel sources doc) | **LSM hook** (BPF-LSM preferred on AL2023; AppArmor/SELinux fallback); eBPF bytecode at LSM hooks. Syscall monitor is a separate audit-only path. (KubeArmor policy spec; LSM BPF kernel doc) | **eBPF kprobe/tracepoint/LSM/uprobe** via TracingPolicy. (Tetragon TracingPolicy ref) |
| **Prevent vs detect-then-respond** | **PREVENT** (hard count ceiling). | **DETECT** (Falco) then **RESPOND** (Talon kills). | **PREVENT** for exec/file/net/caps (inline LSM deny); **detect-only** for syscalls (audit). No prevent for fork count. | **PREVENT** via Override (limited to error-injection functions) OR **respond** via SIGKILL (post-event). |
| **Inline (pre-syscall deny / hard ceiling) vs reactive (post-event kill); latency for a fast self-replicating fork bomb** | **Inline, zero detection latency.** Kernel returns `-EAGAIN` at the cap before any new task exists. A fork bomb cannot outrun it; there is no race. (cgroup v2 doc) | **Reactive.** Detection + Talon kill have measurable latency; a fast bomb forks heavily inside that window. Not a fork ceiling. | **Inline for exec/file/net/caps** (deny is pre-operation at the LSM hook). **No inline path for fork count**; syscall watch is audit-only and after-the-fact. | **Override is synchronous** but only on error-injection-annotated functions; **SIGKILL is asynchronous** and "does not always stop the operation" (Tetragon docs). For a fork bomb, the realistic action is SIGKILL = post-event, with a race. |
| **Against a classic shell fork bomb `:(){ :\|:& };:` specifically** | **STOPS IT inline.** Caps live PID/thread count; the bomb fizzles at the limit, node survives. The correct control. | **Detects + kills the pod**, but the bomb forks during the detect/kill window. Can be outrun; does not bound the count. | **Cannot cap it.** No count/rate field. Can only (a) block exec of `/bin/bash` etc. (blunt, defeated by any already-running or non-shell forker) or (b) audit-only alert on `clone`/`fork`. No fork ceiling. | **Kills the offending process via SIGKILL after detection.** Same outrun/race problem as Talon; Override on the fork path is not a documented control (see fork-bomb verdict). Not a count ceiling. |
| **Binary exec control** | None (only counts PIDs). | Detect-only (alert on suspicious exec). | **Yes, inline** (`process: matchPaths/matchDirectories`, allow/deny, default-deny posture). | **Yes** (TracingPolicy on `execve`/`sys_execve`; Override to deny or SIGKILL). |
| **File / secret read control** | None. | Detect-only (alert on reads of sensitive paths). | **Yes, inline** (`file:` read/write control, e.g. block `/var/run/secrets/...`, `/etc/shadow`). | **Yes** (TracingPolicy on file open/read kprobes; Override/SIGKILL). |
| **Network egress control** | None. | Detect-only (alert on connections). | **Yes, but coarse** (`network: matchProtocols` TCP/UDP/ICMP; protocol-level, not fine CIDR/L7). | **Yes** (TracingPolicy on `tcp_connect`/socket kprobes; can match dest IP/port and Override/SIGKILL). |
| **EKS AL2023 viability (what must be true on the node)** | **CONFIRMED viable; already in repo.** Set via eksctl `overrideBootstrapCommand` / nodeadm `spec.kubelet.config.podPidsLimit`. cgroup v2 is standard on AL2023. Nothing extra to install. | **CONFIRMED viable.** Needs the modern-eBPF driver to load (kernel BTF; AL2023 6.1+ has BTF). Already running in repo (Falco 0.44.1 + Talon). | **Viable but make-or-break: BPF-LSM must be enforcing.** Requires `bpf` in `/sys/kernel/security/lsm` (AL2023 6.1 reportedly enables BPF-LSM by default; SELinux is permissive). If no enforcing LSM -> degrades to audit-only. **VERIFY with `karmor probe` on the actual node.** (KubeArmor FAQ; AL2023 hardening doc) | **Viable.** Needs kernel BTF (AL2023 6.1+ OK) for observability + SIGKILL. **Override additionally needs `CONFIG_BPF_KPROBE_OVERRIDE`** in the AL2023 kernel - UNCERTAIN, must verify (`/sys/kernel/debug/error_injection/list` present and populated). Without it, only SIGKILL enforcement is available. |
| **Coexistence / overlap if run together** | Orthogonal to all three; it is a kernel cgroup setting, not an agent. No conflict. | Detection layer; complements any enforcer. Talon's "kill pod" overlaps Tetragon SIGKILL and KubeArmor's role conceptually but at a different layer. | LSM-hook enforcer; **distinct layer from Falco's syscall eBPF and from Tetragon's kprobes**, so no inherent mutual exclusion (unlike two AppArmor loaders). Two eBPF agents raise per-node CPU/mem and BPF-map load. VERIFY headroom. | kprobe/LSM eBPF enforcer; coexists with Falco at a different layer. Running **Tetragon + KubeArmor together is redundant** (both are inline eBPF enforcers); pick at most one. |
| **Operational cost** | **Lowest.** One kubelet config field. No DaemonSet, no CRDs, no agent. | Moderate: Falco DaemonSet + Talon deployment + rules + (optional) falcosidekick. One eBPF agent. | Higher: KubeArmor DaemonSet + Operator + KSP/HSP/CSP CRDs. One eBPF/LSM agent. Sandbox-stability of CRD surface. | Higher: Tetragon DaemonSet (+ operator) + TracingPolicy CRDs. One eBPF agent. Override requires a kernel feature check. |
| **CNCF maturity** | n/a (upstream Kubernetes/kernel feature, GA). | **Graduated** (2024-02-29). (CNCF announcement) | **Sandbox** (accepted 2021-11-16). (CNCF project page) | Cilium is **Graduated** (2021-10-13); Tetragon is a Cilium **sub-project**, not separately badged on the CNCF projects list. Treat as backed by a graduated project, but UNCERTAIN as an independent maturity tier. |

---

## 2. Fork bomb verdict: which actually PREVENTS it inline

A classic shell fork bomb `:(){ :|:& };:` is an already-running shell repeatedly calling
`clone()`/`fork()` on itself. No new binary is exec'd after the first shell. The damage is
unbounded **PID/thread COUNT**. The only thing that helps is a **count ceiling enforced before the
new task is created**.

**Only `podPidsLimit` (cgroup `pids.max`) prevents it inline.** CONFIRMED from the kernel cgroup
v2 doc: `fork()`/`clone()` "will return `-EAGAIN` if the creation of a new process would cause a
cgroup policy to be violated." The kernel makes the decision at task-creation time, in the fork
path, with zero detection latency and no race. The bomb hits the wall and the pod's own processes
start failing to fork; the node and other pods are untouched. This is a true ceiling.

**Falco + Talon only detect-and-kill, and can be outrun.** Falco's modern-eBPF driver observes the
syscalls and matches a rule; Talon then terminates the pod "in milliseconds" (Talon blog). But
"detect, emit, decide, kill" is a pipeline with latency, and a fork bomb's whole purpose is to
saturate during exactly that window. There is no upper bound on how many tasks are created before
the kill lands. This is detection theater plus reaction, not a count ceiling. CONFIRMED:
Falco does not block; Talon acts after the event.

**Tetragon kills via SIGKILL, which is post-event and racy - not the same guarantee.** Tetragon's
two actions are Override (synchronous) and SIGKILL (asynchronous). For a fork bomb you would hook
the clone/fork path and act:
- **SIGKILL** is what Tetragon actually uses to "block" execution (issue #419: the block mechanism
  is `__do_action_sigkill()`). But Tetragon's own enforcement doc warns SIGKILL "does not always
  stop the operation being performed by the process that triggered the operation." The kill is
  delivered after the syscall is underway, so tasks can still be created. Same outrun problem as
  Talon, plus you are killing the whole process rather than bounding the count.
- **Override** is the only synchronous Tetragon action, but it is restricted to kernel functions
  annotated `ALLOW_ERROR_INJECTION()` (CONFIRMED, selectors doc). Using Override to fail the fork
  path is not a documented Tetragon fork-bomb control, and whether the relevant function is in the
  AL2023 kernel's `/sys/kernel/debug/error_injection/list` is UNCERTAIN and would have to be
  verified. Even if it were, you would be reimplementing, less robustly, what the cgroup `pids`
  controller already does correctly and unconditionally. Do not claim Tetragon "prevents" the fork
  bomb inline.

**KubeArmor does essentially nothing for the fork bomb.** CONFIRMED (and cross-checked against
companion spike 17 against the raw policy spec): there is **no process-count, thread-count,
fork-rate, PID-limit, ulimit, or rate field** in the KubeArmorPolicy enforcement spec. Its only
fork-relevant moves are (a) inline-block exec of the shell binary - blunt, breaks legit shell use
and exec-into-pod, and trivially bypassed by any already-running shell or any non-shell forker
(Python `os.fork()`, a compiled binary) - or (b) audit-only alert on `clone`/`fork`, which is
detection, not prevention (syscalls are audit-only "no matter what the action is set to"). It is
not a fork-count ceiling.

**Why eBPF kill-on-detect is not the same guarantee as a cgroup count cap.** The cap is a
*precondition check inside the kernel's task-creation path*: the (N+1)th task literally never comes
into existence. Kill-on-detect (Falco/Talon, Tetragon SIGKILL) is a *post-hoc reaction*: the task
already exists, the agent observes it, decides, and sends a kill - and during that window the bomb
keeps multiplying, and (per Tetragon's own docs) the in-flight operation may still complete. One is
arithmetic the kernel enforces for free; the other is a race the attacker is specifically built to
win.

**Verdict table:**

| Control | Fork bomb outcome | Inline count ceiling? |
|---|---|---|
| podPidsLimit (`pids.max`) | **Prevents** - bomb fizzles at the cap, node survives | **Yes** (kernel `-EAGAIN`) |
| Falco + Talon | Detects + kills pod, can be outrun | No (reactive) |
| Tetragon | Kills via SIGKILL (post-event, racy); Override on fork path undocumented/unverified | No (not as a count ceiling) |
| KubeArmor | Does nothing as a count cap; can only block the shell binary (blunt) or audit-alert | No |

---

## 3. Where each tool earns its place

**podPidsLimit = the floor for fork bombs (and the only correct one).** Keep it as the single
inline fork-count control. It costs one kubelet field, has zero runtime agent, and the kernel
guarantees the ceiling with no race. Nothing else here replaces it for this job, and adding an
eBPF project to "also handle" the fork bomb muddies a clean, already-verified story.

**Falco = detection / alerting + the response-engine demo + Datadog.** Falco's job is visibility:
it sees the suspicious syscalls and fires alerts, and Talon turns an alert into a visible pod kill.
That makes a great "detect-and-respond" workshop station (high drama: bomb -> alert -> pod
terminated), as long as it is framed as detection-plus-reaction, not prevention. Telemetry:
CONFIRMED Falco has a **native Datadog output** via falcosidekick
(`falcosidekick/docs/outputs/datadog.md`), plus a Prometheus `/metrics` endpoint. This is the
cleanest path to "show the alert land in Datadog." Falco is **CNCF Graduated**, the most mature of
the three.

**Tetragon vs KubeArmor = the two candidate inline-prevention layers for OTHER attacks - pick at
most one.** For the AI-agent threat model ("the agent runs a binary it should not, reads a mounted
secret, or opens egress"), inline prevention is the right tool, and these two are the candidates.
Running both is redundant. Head to head:

| Aspect | KubeArmor v1.7.3 | Tetragon |
|---|---|---|
| **Enforcement model** | LSM-hook allow/deny (BPF-LSM). Declarative posture: default-deny exec/file allow-lists. Block is a clean inline permission-deny. (policy spec) | TracingPolicy on kprobes/LSM/tracepoints. Enforcement = **Override** (synchronous, but only error-injection functions) or **SIGKILL** (async, racy). More expressive matching; enforcement is finickier. (enforcement/selectors docs) |
| **Exec control** | Inline deny of named binaries/dirs; natural allow-list posture. | Inline via execve hook; deny by SIGKILL or Override. |
| **Secret/file read control** | Inline `file:` read control, easy to express ("block reads of `/var/run/secrets`"). | Inline via file-open kprobe; expressive but you assemble the hook. |
| **Egress control** | Coarse: `matchProtocols` TCP/UDP/ICMP (protocol-level, not CIDR/L7). | Finer: match destination IP/port on connect kprobes. Better for "block egress to anything but X." |
| **CNI dependency** | None. | **None - runs standalone without Cilium CNI** (CONFIRMED, install doc). Do not assume it needs Cilium. |
| **EKS AL2023 fit** | Make-or-break on **BPF-LSM enforcing** (`bpf` in `/sys/kernel/security/lsm`; `karmor probe`). If absent -> audit-only, prevention story collapses. VERIFY on node. | Observability + SIGKILL work with BTF (AL2023 OK). **Override needs `CONFIG_BPF_KPROBE_OVERRIDE`** - UNCERTAIN on the AL2023 AMI; if absent, you only get the racy SIGKILL enforcement. VERIFY. |
| **Telemetry (Datadog/Prometheus)** | Prometheus metrics; Datadog via standard Prometheus scrape (no first-party Datadog output documented - UNCERTAIN). | **Prometheus metrics on port 2112** (CONFIRMED, metrics doc), scrapeable into Datadog; JSON event export for log pipelines. |
| **CNCF maturity** | **Sandbox** (least mature). | Backed by **Graduated** Cilium (more mature lineage). |

**Pick guidance:**
- If the workshop wants a **declarative default-deny "harden the agent container" posture** and
  enforcement that is a clean inline LSM permission-deny (and you are willing to verify BPF-LSM is
  enforcing on the node), **KubeArmor** is the more legible story for "the agent may only run these
  binaries / may not read these files."
- If the workshop wants **finer egress matching** (block connect to specific IPs/ports), is
  comfortable that enforcement leans on SIGKILL (post-event) unless Override is available, and
  wants the more mature (Cilium-backed) lineage and Prometheus-native telemetry, **Tetragon** is
  the pick.
- For **inline prevention robustness**, KubeArmor's LSM deny is architecturally a true pre-operation
  block for exec/file/net (when BPF-LSM enforces), whereas Tetragon's common path is post-event
  SIGKILL unless you can use Override. That argues for KubeArmor *if and only if* BPF-LSM is
  confirmed enforcing on the AL2023 nodes. If BPF-LSM is not enforcing, KubeArmor is audit-only and
  Tetragon (SIGKILL) becomes the only working enforcer of the two.

Whichever you choose, you still run **podPidsLimit** (fork bomb) and **Falco** (detection/Datadog)
alongside it. The choice is only "KubeArmor OR Tetragon" for the inline-prevention-of-other-attacks
slot.

---

## 4. Two-minute plain-language summary for Whitney

**For the fork bomb, we use the PID cap (`podPidsLimit`).** It is a kernel setting, not a tool we
install. It tells Linux "this pod may have at most N processes." When the fork bomb tries to make
process N+1, the kernel just says no - instantly, every time, with no race. The bomb hits a wall
and the node keeps running. This is the only one of the four that actually *stops* a fork bomb,
because it is the only one that caps the *number* of processes before they are created.

**The three eBPF projects (Falco, Tetragon, KubeArmor) are not for the fork bomb.** They are for a
different problem: "the AI agent did something it should not have" - ran a strange program, read a
secret file, or phoned home to the internet.

- **Falco** is the security camera. It *watches* everything the agent does and *raises an alarm*
  when something looks bad. Paired with its sidekick "Talon," it can then *kill the pod* in
  response. Great for showing an attack getting caught and reported (and the alert showing up in
  Datadog). But a camera plus a guard who runs over to react is slower than a locked door - a fast
  fork bomb floods the room before the guard arrives. So Falco is *detect-and-respond*, not
  *prevent*.
- **Tetragon and KubeArmor** are the *locked doors*. They can block the agent inline: refuse to run
  a forbidden program, refuse to read a secret, refuse to connect out. They are two ways to do the
  same job, so we pick **one**, not both. KubeArmor is the cleaner "allow-list / default-deny"
  story but needs a kernel feature (BPF-LSM) turned on, which we must check on our nodes. Tetragon
  is more flexible for blocking specific network destinations and rides on the very mature Cilium
  project, but its usual way of stopping something is to *kill the process after the fact*, which is
  less of a hard guarantee than KubeArmor's inline deny.

**So:** PID cap = the fork-bomb wall (keep it, it is the only real one). Falco = the alarm system
and the response demo. Tetragon-or-KubeArmor (pick one) = the locked door for the agent's *other*
bad behavior. Nobody is redundant except Tetragon-vs-KubeArmor, which overlap - that is the one
choice to make.

---

## CONFIRMED vs UNCERTAIN summary

**CONFIRMED:**
- cgroup v2 `pids.max` returns `-EAGAIN` on fork/clone at the cap (inline kernel ceiling).
- Kubelet `PodPidsLimit` / `--pod-max-pids` sets the per-pod hard limit at the node level.
- Falco 0.44.1 (2026-06-11, drivers 10.2.0+driver); 0.44.0 removed legacy eBPF probe/gVisor/gRPC;
  modern eBPF + kernel module remain. Falco detects only; Talon responds (kill pod). Falco is CNCF
  Graduated (2024-02-29). Falco has a native Datadog output via falcosidekick + Prometheus metrics.
- KubeArmor v1.7.3 (2026-05-29), CNCF Sandbox; LSM (BPF-LSM preferred) inline deny for
  exec/file/net/caps; syscalls audit-only; no process-count/fork-rate field; degrades to audit-only
  with no enforcing LSM.
- Tetragon runs standalone without Cilium CNI (DaemonSet, Cilium Helm chart). Override = synchronous
  but only on `ALLOW_ERROR_INJECTION()` functions and needs `CONFIG_BPF_KPROBE_OVERRIDE`. SIGKILL =
  asynchronous and "does not always stop the operation." Tetragon's block mechanism is SIGKILL.
  Prometheus metrics on port 2112. Cilium is CNCF Graduated; Tetragon is a Cilium sub-project.

**UNCERTAIN (verify on the provisioned EKS AL2023 nodes):**
- BPF-LSM actually enforcing on the AL2023 AMI (`bpf` in `/sys/kernel/security/lsm`; `karmor probe`)
  - make-or-break for KubeArmor prevention; reported on by third parties, not in the AWS KubeArmor
  blogs in those exact words.
- `CONFIG_BPF_KPROBE_OVERRIDE` present and the relevant fork-path function in
  `/sys/kernel/debug/error_injection/list` on AL2023 - gates whether Tetragon Override is even an
  option; otherwise Tetragon enforcement is SIGKILL-only.
- Tetragon's independent CNCF maturity badge (it is a sub-project of graduated Cilium, not separately
  listed).
- KubeArmor first-party Datadog output (only Prometheus-scrape path confirmed).
- Two-eBPF-agent resource coexistence (Falco + KubeArmor/Tetragon) on the chosen instance type.
