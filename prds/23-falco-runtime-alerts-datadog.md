# PRD #23: Falco Runtime Alerts into Datadog

**GitHub Issue**: https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/23
**Meta-PRD**: [#7 Observability Suite Meta-PRD](https://github.com/peopleforrester/Unleash_an_Agent_Watch_It_Burn/issues/7) — this is the Milestone 4 child PRD
**Priority**: High
**Status**: Not started

---

## Problem

When exfil or abuse is attempted in the workshop, Falco detects it — but the alerts are not yet confirmed visible in Datadog. The Falcosidekick→Datadog Event Stream wiring exists in the manifest (commit `6c6a81d`) but has never been live-verified on a cluster. One Falco rule name ("Read Of Planted Fake Secret By Workshop Agent") breaks the workshop illusion by revealing the secret is fake and attributing the read to the workshop agent — in a real production environment, Falco only knows that a sensitive file path was accessed; it does not know who read it or why.

The two execution Challenges in the workshop require specific Falco rules to be observable in Datadog:

- **Challenge C3 (grep Easter-egg secret)**: The AI agent reads a planted canary credential file. In a hardened agent pod that should only make HTTP/LLM API calls, any `execve` is the anomaly — grep fires the same structural alarm as any other exec. Two rules must fire: the general exec rule and the sensitive file access rule.
- **Challenge C4 (fork bomb)**: The AI agent forks a bomb. Three rules must fire: the exec rule, the fork bomb rule (routed to Talon for auto-remediation), and the fork bomb rule must also reach Datadog.

---

## Solution

1. Rename the Falco rule `Read Of Planted Fake Secret By Workshop Agent` → `Sensitive File Access` in `gitops/apps/falco.yaml`. This is the production-realistic name: Falco knows a sensitive file path was accessed; it does not know who read it, whether the reader is friend or foe, AI or human, or that the credential is a planted canary.
2. Confirm `datadog-secret` exists in the `security` namespace (Falcosidekick's namespace), not just `monitoring`.
3. Live-verify on a running cluster that all three required rules produce visible alerts in the Datadog Event Stream via Falcosidekick for C3 and C4.

---

## Locked Decisions (do not re-open)

These were finalized in the M4 design conversation (2026-06-24). Read the meta-PRD #7 Decision Log for full reasoning.

| Decision | Value |
|---|---|
| Falcosidekick → Datadog wiring | Correct in manifest (commit `6c6a81d`). `DATADOG_HOST=https://api.datadoghq.com` is correct for US1. No manifest change needed for host config. |
| Two Datadog paths for Falco | Wire both: Falcosidekick → Datadog Event Stream (this PRD, M4); Agent named integration → Log Explorer + OOTB dashboard (M5, when Agent DaemonSet is deployed). These are additive — different Datadog surfaces, no duplication. |
| M5 Falco wiring | Pre-decided (meta-PRD M4 Decision 2): the Agent named integration is wired in M5. This PRD does not implement M5 scope. |
| Required rules for demo | Three rules must produce visible alerts in Datadog Event Stream: (1) "Shell or Exec In Workshop Agent Pod" (WARNING) — fires for any exec in the agent pod, C3 and C4; (2) "Sensitive File Access" (NOTICE) — fires when the sentinel credential file is read, C3; (3) "Fork Bomb In Workload Container" (CRITICAL) — fires for C4, also routes to Talon for auto-remediation. |
| Falco rule rename | `Read Of Planted Fake Secret By Workshop Agent` → `Sensitive File Access`. Rationale: the old name reveals the credential is fake (breaks workshop illusion) and assumes attribution Falco does not have. A production rule is named for what happened, not who did it. |
| "Any exec fires" principle | In a hardened agent pod with HTTP/LLM-only I/O, any `execve` syscall is anomalous regardless of command. `ls`, `grep`, and a fork bomb all trigger "Shell or Exec In Workshop Agent Pod" for the same structural reason. This is the explicit teaching point for C3 and C4. |

---

## Step 0: What to Read Before Starting Any Milestone

This PRD is executed by a fresh AI instance with no memory of the design conversation. Read all of the following before implementing:

1. **Meta-PRD #7 Decision Log, M4 entries** (`prds/7-observability-meta.md`) — M4 Decisions 1, 2, and 3 with full reasoning. All decisions in this PRD are inherited from there.
2. **`gitops/apps/falco.yaml`** — Read in full before editing. Understand the five custom rule files, the `00-` file-sort prefix and why it exists (comment at line 226), and the current rule names. The rule to rename is at line 211.
3. **`gitops/apps/falcosidekick.yaml`** — Read the Datadog output block to understand the current config before verifying it.
4. **`research/06-cncf-stack.md`** — Falco/Falcosidekick architecture overview.
5. **`research/18-datadog-integrations-stack-2026.md`** — Falco row: named Agent integration collects individual alert logs + aggregate metrics (M5 scope); Falcosidekick adds Event Stream output (this PRD's scope). Read the corrected Falco row.
6. **`docs/BUILD-SPEC.md`** — Challenge C3 and C4 beat descriptions.

---

## Milestones

### Milestone 1 — Rename Falco rule to production-realistic name

**Step 0:** Read `gitops/apps/falco.yaml` in full before editing. Note the `00-` prefix on the filename (alphabetical load order matters — do not change it). Note the comment at the bottom explaining why the prefix exists.

**Steps:**

1. In `gitops/apps/falco.yaml`, find the rule named `Read Of Planted Fake Secret By Workshop Agent` (currently at line 211).

2. Rename the rule to `Sensitive File Access`. Change only the `rule:` field — do not change the condition, output, priority, tags, or any other field:

   ```yaml
   - rule: Sensitive File Access
     desc: A file whose name carries the FAKE-...-sentinel marker was opened inside the agent container.
     condition: >
       open_read
       and in_agent_container
       and (fd.name contains "FAKE-PROD-DB-PASSWORD-sentinel"
            or fd.name contains "FAKE-MCP-EXFIL-sentinel")
     output: >
       Planted fake-secret material read inside workshop agent pod
       (file=%fd.name proc=%proc.name cmdline=%proc.cmdline
        pod=%k8s.pod.name ns=%k8s.ns.name container=%container.name)
     priority: NOTICE
     tags: [workshop, agent, secret, mitre_credential_access]
     source: syscall
   ```

   **Do not change the `output:` text** — it is fine for the output message to reference implementation details; that text appears only in Falco's raw log output, not in the Datadog Event Stream event name. The event name in Datadog comes from the `rule:` field.

3. Verify the file is valid YAML after editing (`python3 -m py_compile` will not help here — use `yamllint gitops/apps/falco.yaml` or visually inspect indentation matches surrounding rules).

**Done when:**
- [ ] `gitops/apps/falco.yaml` rule at line 211 is named `Sensitive File Access`
- [ ] All other fields (condition, output, priority, tags, source) are unchanged
- [ ] YAML is valid

---

### Milestone 2 — Verify-at-build: Falcosidekick → Datadog Event Stream live

**Step 0:** Read `gitops/apps/falcosidekick.yaml` in full before starting this milestone. Confirm the Datadog output block is present and `DATADOG_HOST` is set to `https://api.datadoghq.com`.

**Context:** This milestone requires a running cluster with Falco and Falcosidekick deployed. These are verify-at-build tasks — they cannot be validated in a dry-run environment. Michael owns cluster provisioning and the `datadog-secret`.

**Steps:**

1. **Verify `datadog-secret` namespace.** Confirm the secret exists in the `security` namespace (Falcosidekick's namespace), not just `monitoring`:

   ```bash
   kubectl get secret datadog-secret -n security --context "$CONTEXT"
   ```

   If the secret does not exist in `security`, create it (Michael owns the credentials — do not invent or hardcode values). Falcosidekick reads only the `api-key` field from `datadog-secret`:

   ```bash
   kubectl create secret generic datadog-secret --from-literal=api-key="$DD_API_KEY" -n security --context "$CONTEXT"
   ```

   **NEVER print credentials to the terminal.** Pass via env vars only.

2. **Trigger Challenge C3 (grep Easter-egg secret) and observe alerts.**

   Trigger C3 per the `challenges/` runbook for Challenge C3. After the beat runs, navigate to Datadog → Events → Event Stream. Within 60 seconds, both of the following events should appear with the workshop cluster's pod name in the event body:

   - `Sensitive File Access` (NOTICE priority)
   - `Shell or Exec In Workshop Agent Pod` (WARNING priority)

   If events do not appear: check `kubectl logs -n security deployment/falcosidekick --context "$CONTEXT"` for connection errors or auth failures.

3. **Trigger Challenge C4 (fork bomb) and observe alerts.**

   Trigger C4 per the `challenges/` runbook for Challenge C4. After the beat runs, navigate to Datadog Event Stream. Within 60 seconds, both of the following events should appear:

   - `Fork Bomb In Workload Container` (CRITICAL priority)
   - `Shell or Exec In Workshop Agent Pod` (WARNING priority)

   Also confirm Talon auto-remediated the fork bomb (separate from Datadog verification — check Talon logs or cluster state per the C4 runbook).

4. **Record verification results.** Note the Datadog event URLs or screenshots for each rule. Add a comment to GitHub issue #23 with the confirmation: "Verified [date]: all three rules visible in Datadog Event Stream on cluster [name]."

**Done when:**
- [ ] `datadog-secret` confirmed in `security` namespace
- [ ] After C3: `Sensitive File Access` (NOTICE) visible in Datadog Event Stream
- [ ] After C3: `Shell or Exec In Workshop Agent Pod` (WARNING) visible in Datadog Event Stream
- [ ] After C4: `Fork Bomb In Workload Container` (CRITICAL) visible in Datadog Event Stream
- [ ] After C4: `Shell or Exec In Workshop Agent Pod` (WARNING) visible in Datadog Event Stream
- [ ] Results recorded on GitHub issue #23

---

## Acceptance Criteria

- [ ] `gitops/apps/falco.yaml` rule renamed `Sensitive File Access`; all other fields unchanged
- [ ] `datadog-secret` confirmed present in `security` namespace
- [ ] On a live cluster run: `Shell or Exec In Workshop Agent Pod` (WARNING) visible in Datadog Event Stream for both C3 and C4
- [ ] On a live cluster run: `Sensitive File Access` (NOTICE) visible in Datadog Event Stream for C3
- [ ] On a live cluster run: `Fork Bomb In Workload Container` (CRITICAL) visible in Datadog Event Stream for C4
- [ ] PROGRESS.md updated

---

## Out of Scope (M5)

The Datadog Agent named integration for Falco (individual alert logs → Log Explorer + aggregate metrics → OOTB dashboard) is **M5 scope**. This PRD implements only the Falcosidekick → Event Stream path. Do not attempt to wire or verify the Agent integration here.

---

## Decision Log

| Date | Decision | Reasoning |
|------|----------|-----------|
| 2026-06-24 | Inherited M4 Decision 1: Falcosidekick→Datadog wiring correct in manifest; verify-at-build on `datadog-secret` namespace | See meta-PRD #7 Decision Log, M4 Decision 1 (2026-06-24) |
| 2026-06-24 | Inherited M4 Decision 2: Wire both Falcosidekick (Event Stream) and Agent named integration (Log Explorer + OOTB dashboard) — additive | See meta-PRD #7 Decision Log, M4 Decision 2 (2026-06-24). Agent integration is M5 scope; this PRD implements M4 scope only. |
| 2026-06-24 | Inherited M4 Decision 3: Three required rules; "any exec fires" is the detection principle; "Sensitive File Access" is the correct production rule name | See meta-PRD #7 Decision Log, M4 Decision 3 (2026-06-24). "Read Of Planted Fake Secret By Workshop Agent" breaks the workshop illusion and assumes attribution Falco does not have. |
