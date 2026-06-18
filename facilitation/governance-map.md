*The takeaway artifact: every attack mapped to its governing control, the layer it lives in, and whether existing CNCF tooling covers it or an agent-specific control is required. Attendee-facing.*

# Governance Map

Read this as: for each thing the agent tried, what governs it, where that control lives, and whether your existing platform tooling already covers it or you need a control built specifically for the agent.

Layers used below: **admission** (request-time policy at the API server), **RBAC** (who-can-do-what authorization), **GitOps** (declarative reconciliation / drift control), **input inspection** (what reaches the agent), **output inspection** (what the agent returns), **MCP tool authorization** (which tools the agent is allowed to call), **observability** (the trace/telemetry surface).

| # | Attack / step | Governing control | Layer | Covered by existing CNCF tooling, or agent-specific control required |
|---|---------------|-------------------|-------|----------------------------------------------------------------------|
| **Beat 1, the platform you already have** | | | | |
| 1a | Agent deploys a non-compliant workload | Admission policy (Kyverno), flipped from audit to enforce | Admission | **CNCF tooling covers it.** Admission control already in the platform. |
| 1b | Agent tries to escalate its own privileges (self-granted ClusterRoleBinding) | Scoped RBAC, the agent's ServiceAccount lacks the verbs | RBAC | **CNCF tooling covers it.** Standard Kubernetes authorization. |
| 1c | Agent mutates an ArgoCD-managed resource outside Git | Admission block on non-GitOps principals + GitOps self-heal reverts drift | GitOps (+ admission) | **CNCF tooling covers it.** GitOps reconciliation + admission. |
| **Beat 2, what the control plane can't see (AGENT-SPECIFIC GAP)** | | | | |
| 2a | Prompt injection steers the agent off task | Input inspection at the gateway request phase (hard reject) | Input inspection | **Agent-specific control required.** No admission controller, RBAC rule, or GitOps reconciler inspects natural-language input. |
| 2b | Agent reads a planted secret and returns it (exfil) | Output inspection at the gateway (block/redact the sentinel) | Output inspection | **Agent-specific control required.** The leak rides out in the response body; the control plane never sees it. |
| **Beat 3, when the agent's tools turn on it (AGENT-SPECIFIC GAP)** | | | | |
| 3 | Untrusted MCP server's poisoned tool description induces a rogue tool call that exfiltrates a sentinel | MCP tool authorization at the gateway (allowlist / deny rule over tool name) | MCP tool authorization | **Agent-specific control required.** The over-reach rides in a tool call, not a Kubernetes verb; only a tool-authorization layer can stop it. *(Live if the gateway enforcement was confirmed; otherwise shown recorded, the gap is identical either way.)* |
| **The lens / second sink** | | | | |
| Obs | The sentinel re-appears inside trace spans even after the output guard blocks it | Telemetry content-capture default OFF + collector redaction processor (symmetric with the output guard) | Observability | **Agent-specific control required.** Observability is a control surface, not just a viewer, content capture can become a second exfil sink. *(Covered in the 2-hour slot.)* |

## How to read the split

- **Beat 1 is the big surface, and your existing platform already covers it.** Admission, RBAC, and GitOps are mature, well-understood CNCF controls. If they're on and scoped correctly, a whole class of agent misbehavior against the control plane is already blocked.
- **Beats 2 and 3 are the gaps.** They are smaller in surface area but they are exactly where agents change the threat model: the attack rides in language and in tool calls, which the control plane cannot inspect. These need controls built for the agent path, input inspection, output inspection, and tool authorization.
- **Observability is both the lens and a gap.** The same telemetry you use to watch the agent can re-leak what your output control just blocked, unless you guard it symmetrically.

Pair this with `self-assessment.md` to check your own platform against every row, including the failure modes not demonstrated live.
