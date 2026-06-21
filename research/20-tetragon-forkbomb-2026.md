# 20. Tetragon vs the Fork Bomb (Research Spike)

ABOUTME: Research spike on whether CNCF Tetragon (eBPF) can prevent a fork bomb on EKS AL2023,
ABOUTME: how its enforcement model compares to the repo's existing kubelet podPidsLimit (cgroup pids.max).

## Verification Method

Web research conducted 2026-06-21. Every version number, CRD/field/action name, maturity claim,
kernel requirement, and enforcement-timing statement below is taken from the cited primary sources,
not from memory. Where a primary doc page did not state something, that is flagged UNCERTAIN rather
than filled from recall. Primary sources consulted:

- Tetragon homepage and what it is: https://tetragon.io/
- Tetragon overview: https://tetragon.io/docs/overview/
- Tetragon Kubernetes install (helm chart, namespace): https://tetragon.io/docs/installation/kubernetes/
- Tetragon enforcement concepts (Override, Signal, Sigkill): https://tetragon.io/docs/concepts/enforcement/
- Tetragon TracingPolicy selectors (matchActions list, rateLimit, rateLimitScope) raw source:
  https://raw.githubusercontent.com/cilium/tetragon/main/docs/content/en/docs/concepts/tracing-policy/selectors.md
- Tetragon hook points (kprobe/tracepoint/LSM BPF, sched_process_fork): https://tetragon.io/docs/concepts/tracing-policy/hooks/
- Tetragon event throttling / cgroup-rate: https://tetragon.io/docs/concepts/cgroup-rate/
- Tetragon FAQ (kernel version, BTF, CONFIG_BPF_KPROBE_OVERRIDE): https://tetragon.io/docs/installation/faq/
- Tetragon GitHub releases (latest version): https://github.com/cilium/tetragon/releases
- Tetragon GitHub repo: https://github.com/cilium/tetragon
- Isovalent: "Can I Use Tetragon without Cilium? Yes!": https://isovalent.com/blog/post/can-i-use-tetragon-without-cilium-yes/
- CNCF Cilium project page (graduated; Tetragon is a Cilium sub-project): https://www.cncf.io/projects/cilium/
- Kernel: bpf_override_function helper commit (error injection framework): https://github.com/torvalds/linux/commit/9802d86585db91655c7d1929a4f6bbe0952ea88e
- Tetragon issue 1441 (kprobe override of security_ functions): https://github.com/cilium/tetragon/issues/1441
- Falco+Tetragon coexistence overhead figures: https://safeguard.sh/resources/blog/tetragon-vs-falco-runtime-security-2026

Access notes: `github.com/cilium/tetragon/releases` HTML returned 404 to one automated fetch but
resolved on retry; the version below is from that resolved fetch. The `tetragon.io/docs/installation/requirements/`
path 404'd; kernel/BTF requirements were read from the FAQ instead. The Isovalent blog body did not
render fully to the fetcher; the standalone claim is corroborated by the blog title and by the
Tetragon install docs (helm chart deploys a DaemonSet independent of any CNI agent).

---

## Bottom line up front

Tetragon does **not** give you a true inline fork/clone COUNT or RATE ceiling. It cannot replace
the kubelet `podPidsLimit` (cgroup `pids.max`) for fork-bomb prevention. The reasons, all confirmed
against primary docs:

- Tetragon's `Sigkill` action is post-event: it kills the process *after* the matched event is
  observed in the kernel BPF program. A fast self-replicating bomb keeps forking children faster
  than kills land, which is the same race that makes Falco+Talon reactive.
- Tetragon's `Override` action *can* return `-EPERM` from a `sys_clone`/`fork` kprobe before the
  fork completes (pre-syscall), but it is an all-or-nothing per-call deny. It blocks *every* fork
  the selector matches; it does not "allow N forks then deny." There is no inline counter primitive
  in a TracingPolicy that enforces "kill/deny only after the Nth fork."
- The `rateLimit` / `rateLimitScope` selector arguments throttle how often an **action fires**
  (event reporting), not the underlying syscall. The syscall still runs.
- The `--cgroup-rate` feature is **telemetry throttling** to protect Tetragon from event floods.
  When the threshold is crossed it stops *posting events*; it does not kill or stop the processes.

So a cgroup `pids.max` remains the only hard, inline, count-based ceiling. Tetragon's genuine value
in this workshop is a CNCF-native, eBPF, runtime-enforcement *station* (inline block of forbidden
exec/file/syscall via Override/Sigkill, plus rich process-lineage observability), not as a fork-bomb
replacement for the PID cap.

---

## Q1. What is Tetragon, maturity, version, and standalone (no Cilium CNI)? CONFIRMED

**What it is. CONFIRMED.** Tetragon is "a flexible Kubernetes-aware security observability and
runtime enforcement tool that applies policy and filtering directly with eBPF" (tetragon.io
homepage). It detects and can react to process execution, syscalls, file and network I/O, and
namespace/privilege changes, with Kubernetes pod/namespace identity awareness (homepage, overview).

**CNCF maturity. CONFIRMED with nuance.** Tetragon is a **sub-project of Cilium**, described on its
own site as "a proud CNCF project" and "a sub-project under Cilium" (tetragon.io homepage). Cilium
itself is a CNCF **Graduated** project (accepted to CNCF Incubating 2021-10-13, Graduated
2023-10-11; CNCF Cilium project page). UNCERTAIN: I could not load a CNCF page giving Tetragon a
*separate* maturity level of its own; it appears governed under the Cilium project rather than
holding an independent Sandbox/Incubating/Graduated badge. For the workshop, the honest framing is
"Tetragon is a CNCF project, a sub-project of the graduated Cilium project," not "Tetragon is
independently graduated." Verify the exact current wording at build if the slide needs a precise badge.

**Latest version. CONFIRMED.** Tetragon **v1.7.0**, released **2026-04-29** (GitHub releases). Prior
tags: v1.6.1 (2026-03-31), v1.6.0 (2025-10-23), v1.5.0 (2025-07-29), v1.4.1 (2025-07-15). Pin the
exact chart/app version into `VERSIONS.lock` at build; do not assume v1.7.0 is still current then.

**Standalone, no Cilium CNI, CNI-agnostic. CONFIRMED. This is load-bearing for VPC-CNI and it holds.**
- Tetragon installs via its own Helm chart as a per-node **DaemonSet**:
  `helm repo add cilium https://helm.cilium.io && helm repo update && helm install tetragon cilium/tetragon -n kube-system`
  (Tetragon Kubernetes install docs). The chart is distributed from the Cilium helm repo but installs
  *only* the Tetragon agent DaemonSet (+ operator), not the Cilium CNI agent.
- Isovalent (the Cilium/Tetragon vendor) published "Can I Use Tetragon without Cilium? Yes!"
  (isovalent.com), the title of which is the direct vendor confirmation. Tetragon is an independent
  eBPF agent that works on any Kubernetes cluster regardless of CNI, including AWS VPC-CNI on EKS.
- CONFIRMED net: you keep VPC-CNI for pod networking and run Tetragon purely as a security DaemonSet.
  No CNI change, no CNI chaining required. This matches the repo's deliberate VPC-CNI choice.

---

## Q2. Enforcement model: TracingPolicy CRD and the enforcement actions. CONFIRMED

**Policy object. CONFIRMED.** Enforcement and observability are expressed as a **TracingPolicy** CRD
(also a namespaced `TracingPolicyNamespaced` variant). A TracingPolicy attaches BPF programs at one
or more **hook points** and, per `selectors.matchActions`, runs **actions** when a selector matches
(Tetragon hooks and selectors docs).

**Hook points. CONFIRMED.** TracingPolicy supports: **kprobes** (hook any kernel function),
**tracepoints** and **raw tracepoints** (stable kernel-defined hooks, e.g. `sched_process_fork`),
**uprobes** and **USDTs** (user space), and **LSM BPF** hooks (Tetragon hooks doc). So
clone/fork-related points ARE reachable: a `sys_clone` kprobe and the `sched_process_fork`
tracepoint are both hookable (hooks doc).

**Actions in `matchActions`. CONFIRMED list** (from the selectors raw source):
`Post`, `NoPost`, `Sigkill`, `Signal`, `Override`, `FollowFD`, `UnfollowFD`, `CopyFD` (the three FD
actions deprecated/unsafe), `GetUrl`, `DnsLookup`, `TrackSock`, `UntrackSock`, `NotifyEnforcer`,
`Set`. The enforcement-relevant ones:

- **`Override` (pre-syscall deny). CONFIRMED.** "Override the return value of a call means that the
  function will never be executed and, instead, a value (typically an error) will be returned to the
  caller" (enforcement doc). This is genuine *pre-completion* enforcement: the overridden function
  does not run; the caller gets the error (e.g. `-EPERM`). CONFIRMED constraint: Override uses the
  kernel error-injection framework and is only available with `CONFIG_BPF_KPROBE_OVERRIDE`, and the
  overridden function must be tagged `ALLOW_ERROR_INJECTION` in the kernel (FAQ; bpf_override_function
  commit). All syscalls qualify; `security_` LSM hooks became overridable from kernel 5.7 (FAQ; issue 1441).

- **`Sigkill` (post-event kill). CONFIRMED.** "Terminates synchronously the process that made the
  call" (selectors). The enforcement doc is explicit that a kill is not guaranteed to prevent the
  triggering operation: "sending a `SIGKILL` signal does not always stop the operation being performed
  by the process that triggered the operation ... a `SIGKILL` sent in a `write()` system call does not
  guarantee that the data will not be written." It recommends: "To ensure the operation is not
  completed ... the `Signal` action should be combined with the `Override` action" (enforcement doc).
  "Synchronously" here means the kill is delivered as the event is handled, NOT that it pre-empts the
  syscall the way Override does. It is a kill *in response to* an observed event.

- **`Signal`. CONFIRMED.** Sends an arbitrary signal number to the current process (selectors). Same
  post-event timing caveat as Sigkill.

- **`NotifyEnforcer`. CONFIRMED (by name and purpose).** Notifies the enforcer BPF program to
  kill/override syscalls (selectors). It is the multi-stage plumbing that lets one hook signal the
  enforcer to apply Sigkill/Override; it is not a separate "count limit" primitive.

**So what can Tetragon DO when a policy matches? CONFIRMED.** It can (a) **kill** the process
(`Sigkill`/`Signal`, post-event), (b) **deny the call inline** by overriding the return value
(`Override`, pre-completion, for override-eligible functions/syscalls), or (c) just **alert/observe**
(`Post`). The strongest guarantee, per the docs, is `Override` (+`Signal` if you also want the process
gone). This is more than "alert only": Tetragon genuinely enforces in-kernel.

---

## Q3. THE CORE QUESTION: can Tetragon impose a true count/rate ceiling on fork/clone? CONFIRMED: NO

A classic fork bomb is an already-running process repeatedly calling `clone()`/`fork()` on itself.
The harm is unbounded PID/thread COUNT, which `pids.max` caps directly and inline. The question is
whether Tetragon can match that: a hard ceiling of N processes, enforced before the (N+1)th fork
returns. Answer, rigorously: **No. Tetragon cannot impose an inline COUNT or RATE ceiling on fork.**
It can only either deny ALL matching forks inline, or kill-on-detect after the fact. Evidence:

**1. `rateLimit` / `rateLimitScope` throttle the ACTION, not the syscall. CONFIRMED.** From the
selectors source: when `rateLimit` is set "for an action, that action will check if the same action
has fired, for the same thread, within the time window, with the same inspected arguments." This
governs how often the **action** (e.g. `Post`, the event report) fires; it deduplicates/limits event
emission. `rateLimitScope` widens that dedup to `process` or `global`. It is supported on kernels
v5.3+ and matches on the first 40 bytes of inspected args. CONFIRMED: it does NOT throttle the
underlying `clone`/`fork`; the syscall still executes normally. It is a telemetry/noise control, not
a fork governor. (This is the Tetragon analogue of KubeArmor's `rate:` audit-throttle from spike 17:
detection-side, not enforcement.)

**2. `--cgroup-rate` is telemetry throttling, NOT enforcement. CONFIRMED.** This is the feature that
looks closest to a fork-rate limiter and is NOT one. Configured cluster/agent-wide as
`--cgroup-rate=<events,interval>` (e.g. `10,1s`), disabled by default. It "monitors and limits base
sensor events: PROCESS_EXEC and PROCESS_EXIT." When a cgroup crosses the rate, Tetragon emits a
`process_throttle` event of type `THROTTLE_START` and **stops posting that cgroup's events**; it
emits `THROTTLE_STOP` once the rate stays below the limit for 5 seconds (cgroup-rate doc). CONFIRMED
critical point: it stops *reporting* events to protect Tetragon from flooding; it does NOT kill,
deny, or slow the offending processes. A fork bomb keeps running; you just stop seeing its events.
It is the opposite of enforcement.

**3. No counter/aggregation primitive in TracingPolicy. CONFIRMED.** The hooks and selectors docs
describe matching on arguments, namespaces, capabilities, binary paths, etc., and then firing an
action. They do **not** document any per-cgroup or per-process COUNTER that you can compare against a
threshold to enforce "deny/kill only after the Nth fork." There is no `maxProcesses`, `pidsLimit`,
`forkRate`, or equivalent field in the TracingPolicy enforcement surface. (CONFIRMED absent from the
documented selector/action set; UNCERTAIN only in the sense that a future release could add one,
which must be re-checked at build.)

**4. What Tetragon CAN do on clone/fork, and why it still is not a PID cap. CONFIRMED.**
- Hook `sys_clone` (kprobe) or `sched_process_fork` (tracepoint) and `Sigkill` on match: this is
  **kill-on-detect**, post-event. Exactly the Falco+Talon failure mode against a fast bomb: kills
  trail the fork rate; the bomb can outrun them.
- Hook the `clone`/`fork` syscall (kprobe) and `Override` to return `-EPERM`: this IS pre-completion
  and inline, BUT it denies **every** matching fork. You can scope it by selector (binary, cgroup,
  arg), yet within that scope it is all-or-nothing. Denying all forks for a workload breaks the
  workload (it cannot start child processes at all); it is not a *ceiling* of N, it is zero. There is
  no documented way to let the first N forks through and override only the (N+1)th, because there is
  no inline counter (point 3).

**Verdict. CONFIRMED.** Tetragon cannot replace the PID cap for fork bombs. It offers kill-on-detect
(post-event, outrunnable) or total fork denial (inline but workload-breaking), neither of which is a
hard inline COUNT ceiling. `pids.max` (podPidsLimit) is the kernel cgroup PIDs controller: it caps
live PID/thread count and the kernel refuses `fork`/`clone` with `EAGAIN` at the cap, inline, with no
detection step and no per-call policy to outrun. That is a fundamentally different and stronger
primitive than anything in Tetragon's TracingPolicy. Stated plainly: **Tetragon does NOT replace the
PID cap for fork-bomb prevention.**

---

## Q4. EKS AL2023 viability and Falco coexistence. CONFIRMED (verify enforcement bits at build)

**Kernel / BTF requirements. CONFIRMED.** From the Tetragon FAQ:
- Minimum kernel **4.19+** for Tetragon; tested on LTS 4.19, 5.4, 5.10, 5.15, and bpf-next.
- **BTF is mandatory** (CO-RE): `CONFIG_DEBUG_INFO_BTF=y` (and `CONFIG_DEBUG_INFO_BTF_MODULES=y`),
  i.e. `/sys/kernel/btf/vmlinux` present. Tetragon uses CO-RE so it does not need kernel headers,
  but it does need vmlinux BTF.
- **Enforcement (`Override`) additionally needs `CONFIG_BPF_KPROBE_OVERRIDE=y`**, and the overridden
  function must be `ALLOW_ERROR_INJECTION`-tagged (all syscalls qualify; `security_` hooks from 5.7+).
- Kernel **Lockdown in confidentiality mode** makes Tetragon fail with EPERM; integrity mode is fine.
  This matters on AL2023, which enables lockdown by default per AWS hardening docs (cross-ref spike 17).

**AL2023 (kernel 6.1) satisfies the version + BTF + override requirements. CONFIRMED for version,
VERIFY for the exact AMI.** AL2023 ships kernel 6.1, far above the 4.19 floor, and 6.1 supports BTF,
kprobe override, and `security_` hook override. AL2023 kernels are widely reported BTF-enabled
(`/sys/kernel/btf/vmlinux` present). UNCERTAIN per-AMI: confirm on the actual provisioned node that
`/sys/kernel/btf/vmlinux` exists, `CONFIG_BPF_KPROBE_OVERRIDE=y`, and lockdown is not in
confidentiality mode, because an AMI build or `overrideBootstrapCommand` could alter these.

**Verify-at-build commands (run on a provisioned AL2023 node / Tetragon DaemonSet pod):**
- `ls -la /sys/kernel/btf/vmlinux` -> must exist (BTF present for CO-RE).
- `bpftool btf list 2>/dev/null | head` or `zcat /proc/config.gz 2>/dev/null | grep -E 'CONFIG_DEBUG_INFO_BTF|CONFIG_BPF_KPROBE_OVERRIDE'`
  -> expect `CONFIG_DEBUG_INFO_BTF=y` and `CONFIG_BPF_KPROBE_OVERRIDE=y`. (If `/proc/config.gz` is
  absent on AL2023, rely on the `/sys/kernel/btf/vmlinux` check plus a live Override test below.)
- `cat /sys/kernel/security/lockdown` -> must NOT be in `[confidentiality]`; `[none]` or `[integrity]`
  is required for Override to work.
- `grep -E 'sys_clone|__x64_sys_clone' /sys/kernel/debug/error_injection/list` (mount debugfs first)
  -> confirms the clone syscall is override-eligible if you intend an Override-based demo.
- Apply a trivial enforcing TracingPolicy (e.g. `Sigkill` on `sys_clone` for a throwaway pod, or
  `Override` -EPERM on a harmless syscall) and confirm it actually kills/denies, proving enforcement
  (not just observability) works on the node.

**Falco coexistence (two eBPF agents on one node). CONFIRMED viable, VERIFY on the instance type.**
- No documented hard mutual-exclusion: Falco (its modern_ebpf/CO-RE probe instrumenting syscall
  tracepoints) and Tetragon (its own kprobe/tracepoint/LSM-BPF programs) attach their own BPF
  programs; multiple BPF programs can attach to the same tracepoint, so there is no single-owner
  conflict the way two AppArmor profile loaders would conflict.
- Resource overhead figures (2026 comparison, safeguard.sh): together **0.28 cores and 410 MiB RSS**
  per node; individually Falco 0.40.1 at 0.21 cores / 287 MiB and Tetragon 1.4 at 0.09 cores /
  142 MiB. CONFIRMED these are modest and within headroom for a normal demo instance type, but they
  are third-party benchmark numbers; verify actual usage on the workshop instance type with both
  agents plus the existing stack running.
- Caveats to verify at build: multiple eBPF agents compete for CPU and BPF map/verifier resources
  under load; confirm both come up healthy on the SAME node (Tetragon DaemonSet Ready and emitting
  events, Falco driver loaded and rules firing) before relying on the demo. Note the repo already
  runs Falco 0.44.1 (newer than the benchmarked 0.40.1) and would add Tetragon 1.7.0 (newer than the
  benchmarked 1.4), so treat the numbers as directional, not exact.

---

## Q5. Cleanest demo and honest narration

**Recommended demo (honest, plays to Tetragon's real strength): inline Override block + process
lineage, NOT a fork-bomb "win."**

1. **Observability lead-in (always true, zero risk):** show Tetragon streaming the full process
   lineage of the agent container (exec events with parent/child, args, cwd, container/pod identity)
   via `tetra getevents`. This is Tetragon's standout: rich, Kubernetes-aware, in-kernel process
   tree. Narrate: "Tetragon sees every exec and fork in-kernel, with pod identity, in real time."

2. **Inline enforcement that Tetragon genuinely does well:** a TracingPolicy that `Override`s
   (returns -EPERM) on a forbidden action by the agent, e.g. exec of an unexpected binary, or a
   `security_` file-open hook on a mounted secret path, or an egress connect. Show the agent's call
   fail *before it completes*. Narrate: "This is true inline prevention in eBPF: the call never
   happens, no kill race." This is the clean CNCF-native "prevent, do not just detect" counterpoint
   to the Falco detect-and-respond station, and it is honest because Override IS pre-completion.

3. **The fork bomb, narrated against the PID cap (do NOT claim Tetragon prevents it):** run the fork
   bomb in a pod and show two things side by side: (a) the cgroup `pids.max` (podPidsLimit) refuses
   forks inline and the node survives, the PID cap doing the real work; (b) Tetragon's view of the
   storm, and optionally a `Sigkill`-on-`sys_clone` TracingPolicy to show kill-on-detect. Narrate
   honestly: "Tetragon can kill on detecting forks, but that is reactive, like Falco+Talon, and a
   fast bomb outruns it. The hard inline ceiling that actually saves the node is the cgroup PID cap.
   Tetragon could also `Override` to deny every fork, but that just breaks the workload, it is not a
   count ceiling. There is no fork-COUNT limit in Tetragon; `pids.max` is the right tool here."

This keeps the workshop's clean, already-verified fork-bomb story intact (PID cap = inline block;
Falco+Talon = reactive theater) and adds Tetragon where it is genuinely strong (eBPF process
observability + inline Override prevention of other agent misbehavior), without overclaiming.

---

## Recommendation

**Do NOT position Tetragon as a fork-bomb defense or as a replacement for the PID cap.** CONFIRMED
against primary docs: Tetragon has no inline process/thread COUNT or fork-RATE ceiling. Its
`rateLimit` throttles action/event firing, its `--cgroup-rate` throttles telemetry (and explicitly
does not kill processes), its `Sigkill` is post-event kill-on-detect (outrunnable, same class as
Falco+Talon), and its `Override` is an all-or-nothing pre-completion deny (blocks every matching
fork, breaking the workload) with no counter to enforce "allow N then deny." The kubelet
`podPidsLimit` (cgroup `pids.max`) remains the one true inline fork-bomb block and should stay the
primary control. Adding Tetragon to the fork-bomb narrative would muddy a clean, verified story.

**DO consider Tetragon for a DIFFERENT role** if the workshop wants a CNCF-native, eBPF
runtime-enforcement station: (1) best-in-class Kubernetes-aware process/exec/fork **observability**
of the agent, and (2) **inline `Override` prevention** of other agent misbehavior (forbidden binary
exec, secret-file reads via `security_` LSM-BPF hooks, unexpected egress). That is "prevent, do not
just detect" enforcement that neither podPidsLimit nor Falco provides, and it runs **standalone on
VPC-CNI as a DaemonSet** with no Cilium CNI change, which fits the repo's stack. This is the same
"different-attack option" conclusion reached for KubeArmor in spike 17, with one Tetragon advantage:
Tetragon's process-lineage observability is richer and its enforcement is via kprobe/tracepoint
override and LSM-BPF rather than KubeArmor's LSM-only allow/deny, so it pairs better with the
AI-agent "watch what the agent does, then block the bad call inline" narrative.

**If Tetragon is pursued, verify at build (all on the actual provisioned EKS AL2023 nodes):**
1. `ls -la /sys/kernel/btf/vmlinux` exists (BTF / CO-RE).
2. `CONFIG_BPF_KPROBE_OVERRIDE=y` and `CONFIG_DEBUG_INFO_BTF=y` present (Override + CO-RE).
3. `cat /sys/kernel/security/lockdown` not in `[confidentiality]` mode (else Override fails with EPERM).
4. Apply a throwaway enforcing TracingPolicy (`Override` -EPERM on a harmless syscall, or `Sigkill`
   on a test binary) and confirm it actually denies/kills, proving enforcement not just observability.
5. Confirm the live CRD names and group: `kubectl get crd | grep tetragon`
   (`tracingpolicies.cilium.io`, `tracingpoliciesnamespaced.cilium.io`) and inspect with
   `kubectl get crd tracingpolicies.cilium.io -o yaml`; do not assume the API group without checking.
6. Pin versions into `VERSIONS.lock`: Tetragon app/chart (v1.7.0 current as of 2026-04-29) once
   confirmed current at build.
7. Run Tetragon and Falco together on one node and confirm BOTH stay healthy (Tetragon DaemonSet
   Ready and emitting events via `tetra getevents`; Falco driver loaded and rules firing) with CPU/
   memory headroom for two eBPF agents on the chosen instance type.
8. Confirm Tetragon installs as a standalone DaemonSet (`helm install tetragon cilium/tetragon -n
   kube-system`) without disturbing VPC-CNI, and that the Cilium CNI agent is NOT installed.

CONFIRMED claims: standalone/CNI-agnostic DaemonSet install on any CNI incl. VPC-CNI; Tetragon a
CNCF project and Cilium sub-project (Cilium graduated 2023-10-11); latest v1.7.0 (2026-04-29);
TracingPolicy CRD with kprobe/tracepoint/raw-tracepoint/uprobe/USDT/LSM-BPF hooks; matchActions set
incl. Override (pre-completion deny), Sigkill/Signal (post-event kill), NotifyEnforcer; Override
needs CONFIG_BPF_KPROBE_OVERRIDE + ALLOW_ERROR_INJECTION (security_ hooks from 5.7); Sigkill not
guaranteed to stop the triggering op, combine with Override; rateLimit throttles action firing not
the syscall; --cgroup-rate is telemetry throttle on PROCESS_EXEC/PROCESS_EXIT that stops posting
events and does NOT kill; no fork-COUNT/RATE ceiling primitive in TracingPolicy; kernel 4.19+ and
BTF mandatory; lockdown confidentiality mode breaks Override; Falco+Tetragon coexistence viable with
modest combined overhead (benchmark 0.28 cores / 410 MiB).

UNCERTAIN claims (flagged inline): Tetragon's exact independent CNCF maturity badge (governed under
graduated Cilium; could not confirm a separate Tetragon level); per-AMI AL2023 satisfaction of
CONFIG_BPF_KPROBE_OVERRIDE / lockdown mode / BTF presence (must verify on the provisioned node);
exact current chart version at build time; precise CRD API group/version on the live cluster;
Falco+Tetragon resource coexistence on the specific workshop instance type with the newer agent
versions actually in use (Falco 0.44.1, Tetragon 1.7.0 vs the 0.40.1/1.4 benchmark).
