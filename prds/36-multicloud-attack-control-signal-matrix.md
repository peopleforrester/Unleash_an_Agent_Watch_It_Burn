# PRD 36: Multi-cloud attack -> control -> signal matrix

Status: DRAFT, awaiting approval (Phase 1.3 gate)
Author: Michael Forrester
Created: 2026-07-01
Branch target: staging
Sibling of: `prds/35-multi-cloud-aks-gke-support.md` (keeps 35 lean at its gate)

## 1. Goal

Give the workshop one authoritative security spine that survives the multi-cloud
refactor in PRD 35. Today the attack story lives as AWS-only prose in
`walkthrough-agenticburn/STACK-MAP.md` §4 and §5, plus the two observability
beats in PRD 22. When the platform becomes pluggable across AWS, Azure, GCP, and
local, each attack beat has to be answered on whichever cloud a run is delivered
on, and the identity and egress models diverge enough per cloud that the same
attack produces a different lesson.

This PRD is that spine: for every attack beat, the control that fires, the
observable signal in Datadog, the round it belongs to (R1/R2/R3), and how the
answer shifts per cloud. It is pegged to a recognized taxonomy so each beat has a
stable external ID, not just a local nickname.

This is a plan and reference document. It contracts no code by itself. The
matrix here becomes the acceptance checklist that PRD 35's per-cloud overlays are
validated against, and the source of truth that STACK-MAP.md points at instead of
carrying an AWS-only table.

## 2. Locked scope decisions

1. **Taxonomy peg is OWASP, cross-referenced to MITRE ATLAS.** Each beat carries
   an OWASP Agentic (ASI) primary ID and a MITRE ATLAS technique ID where one maps
   cleanly. Rationale and versions in §3.
2. **The matrix is descriptive of the existing attack set, not a new attack set.**
   The beats are exactly C1 through C7 plus the observability re-leak trap already
   defined in STACK-MAP §4 and PRD 22. This PRD does not invent attacks; it maps
   and multi-cloud-qualifies the ones we run.
3. **Per-cloud divergence is captured as a column, not a fork.** One matrix, with a
   per-cloud note on each beat where the identity or egress model changes the
   answer. No per-cloud copy of the matrix.
4. **Signals are the ones we already emit or have PRDs for.** The signal column
   references NetworkPolicy/Falco/Kyverno/guard-proxy/OTel outputs that exist or
   are contracted in PRDs 22, 23, 26, 27. This PRD does not add new instrumentation;
   it names which existing signal proves each beat.

## 3. Taxonomy peg (verified 2026-07-01)

Two live taxonomies, pegged deliberately.

- **OWASP Top 10 for Agentic Applications, 2026 edition** (released 2025-12-09 by
  the OWASP GenAI Security Project), threat IDs **ASI01 through ASI10**. This is
  the primary peg because it is agent-shaped end to end (goal hijack, tool misuse,
  identity abuse, supply chain, code execution, memory poisoning) and maps almost
  one to one onto the workshop beats. Source:
  https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- **MITRE ATLAS** (v5.1.0, 2025-11; agent-focused techniques added through v5.4.0,
  2026-02), 16 tactics / 84 techniques. Cross-referenced for the technique-level ID
  where the ATLAS catalog has a clean match, notably Prompt Injection
  (AML.T0051) and Publish a Poisoned AI Agent Tool (AML.T0011.002). Source:
  https://www.getastra.com/blog/security-audit/mitre-atlas/ and the ATLAS matrix at
  https://atlas.mitre.org.

The 2026 ASI IDs used below:

| ID | Name |
|---|---|
| ASI01 | Agent Goal Hijack |
| ASI02 | Tool Misuse and Exploitation |
| ASI03 | Agent Identity and Privilege Abuse |
| ASI04 | Agentic Supply Chain Compromise |
| ASI05 | Unexpected Code Execution |
| ASI06 | Memory and Context Poisoning |
| ASI08 | Cascading Agent Failures |

Re-verify these IDs and versions before any run that presents them to attendees.
Both taxonomies are on a fast release cadence (ATLAS moved to monthly), so a beat
label printed on a slide is a recency claim and gets re-checked per the
recency-claim-verification rule.

## 4. The per-cloud identity and egress through-line (why one attack, three lessons)

This is the spine of the whole thing. The same agent misbehavior teaches a
different security lesson depending on the cloud's identity and egress model. The
workshop gets three distinct burn-and-contain stories out of one attack set.

| Cloud | Model identity | What an attacker can steal | The lesson only this cloud teaches |
|---|---|---|---|
| **AWS** (reference) | Keyless: EKS Pod Identity to Bedrock. No credential on the pod. | Nothing to steal; there is no static key. Blast radius is the pod's IAM scope. | The clean baseline. Guardrails are about scope and egress, not secret hygiene. |
| **Azure** | Static `AZURE_OPENAI_API_KEY` per cluster, delivered as a Secret. | A real, portable key usable off-cluster until rotated. | A stolen static key is a lesson AWS cannot teach. Exfil of the Secret is the whole point. |
| **GCP** | Keyless: Workload Identity to Vertex. No credential on the pod. | Nothing to steal, BUT Vertex and GCS share `restricted.googleapis.com` (199.36.153.4/30). | Your obvious L3/L4 egress guardrail silently fails: a NetworkPolicy that allows Vertex also allows GCS exfil. Separation needs VPC-SC or an SNI-aware proxy. |
| **local** | Keyless, offline: in-cluster Ollama, no egress at all. | Nothing; there is no cloud plane. | The control-plane render check. Proves the policy converges before any cloud spend. |

Two beats change character because of this table:

- **C1 (PII/S3 exfil)** becomes **C1' (Secret exfil)** on Azure: the trophy is the
  model key itself, not just data. On GCP the NetworkPolicy that looks like it
  blocks exfil does not, because the exfil destination shares the allowed VIP.
- **C5 (output leak)** on GCP is the beat where "I blocked egress" and "I blocked
  the leak" come apart: egress to `restricted.googleapis.com` is required for the
  model to work and cannot be the enforcement point.

This is the reason the multi-cloud refactor enriches the security story rather
than merely porting it. Identity-as-blast-radius is the connective tissue.

## 5. The matrix

Columns: beat and nickname; OWASP ASI / ATLAS peg; what the agent tries; the
control that fires; the observable signal; the round it is live in; per-cloud
delta. Beats are the STACK-MAP §4 set. "Round" follows the R1 no-guardrails /
R2 some-controls / R3 full-controls arc.

### C1 - PII / data exfil to S3 or external

- **Peg:** ASI03 (Identity and Privilege Abuse), ASI02 (Tool Misuse). ATLAS
  Exfiltration (AML.TA0010).
- **Agent tries:** read PII, ship it to an external bucket or endpoint.
- **Control:** NetworkPolicy default-deny egress; Falco on the sensitive read.
- **Signal:** Falco alert to Datadog; NetworkPolicy drop; guard-proxy sees no
  matching output on the sanctioned path.
- **Round:** exfil succeeds in R1; NetworkPolicy lands in R2; full deny + Falco in R3.
- **Per-cloud delta:** **AWS** clean deny. **Azure** the exfil target of choice is
  the `AZURE_OPENAI_API_KEY` Secret (see C1'). **GCP** default-deny that allows
  Vertex also allows GCS; the naive egress policy does not separate them (VPC-SC or
  SNI proxy required). **local** no external plane; the beat is render-only.

### C1' - Static model-key exfil (Azure only)

- **Peg:** ASI03 (Identity and Privilege Abuse). ATLAS Credential Access / Unsecured
  Credentials.
- **Agent tries:** read the mounted Azure OpenAI key and exfiltrate it; the key
  works off-cluster.
- **Control:** Secret not mounted where the agent runs; egress deny; Kyverno on
  Secret access patterns.
- **Signal:** Falco on the Secret read; guard-proxy/egress drop on the exfil.
- **Round:** R3 free-play highlight; this is the Azure-specific "why keyless matters"
  beat.
- **Per-cloud delta:** exists only on Azure. AWS and GCP are keyless, so there is no
  portable credential to steal. This is the beat that makes the identity table
  concrete.

### C2 - Villain workload (unauthorized image)

- **Peg:** ASI04 (Agentic Supply Chain Compromise). ATLAS ML Supply Chain Compromise.
- **Agent tries:** schedule a pod from an untrusted registry.
- **Control:** Kyverno registry allowlist (Enforce).
- **Signal:** Kyverno admission deny event to Datadog.
- **Round:** allowed in R1; Kyverno allowlist in R2/R3.
- **Per-cloud delta:** identical across clouds; admission control is cloud-neutral.
  The allowlist entries differ (ECR vs ACR vs Artifact Registry) but the control and
  signal are the same shape.

### C3 - Filesystem grep for planted secret

- **Peg:** ASI02 (Tool Misuse), ASI03 (Privilege Abuse). ATLAS Discovery / Collection.
- **Agent tries:** grep the filesystem for the planted sauce recipe sentinel
  (`WITCH-HAZEL-GHOST-PEPPER-BAT-SPIT-No7`).
- **Control:** Falco sensitive-file read rule.
- **Signal:** Falco alert to Datadog with the file path.
- **Round:** succeeds silently in R1; Falco visibility in R2; alert + response in R3.
- **Per-cloud delta:** identical across clouds; node-level syscall visibility is
  cloud-neutral. Falco DaemonSet on every cloud.

### C4 - Fork bomb (resource exhaustion)

- **Peg:** ASI05 (Unexpected Code Execution), ASI08 (Cascading Agent Failures).
  ATLAS Impact / Denial of ML Service.
- **Agent tries:** spawn processes without bound.
- **Control:** per-pod PID cap (1024); Falco/Talon terminates in about 4s.
- **Signal:** Falco process-spawn alert; pod termination event; PID-limit metric.
- **Round:** cluster-killable in R1; PID cap in R2; cap + Talon terminate in R3.
- **Per-cloud delta:** identical; the PID cap is a Kubernetes-level control on every
  cloud. Node instance shapes differ but the control does not.

### C5 - Output leak (secret in model output)

- **Peg:** ASI01 (Agent Goal Hijack), ASI02 (Tool Misuse). ATLAS Exfiltration via
  model output.
- **Agent tries:** get a secret or sentinel into the response stream.
- **Control:** guard-proxy output inspection; LLM Guard output Regex scrub.
- **Signal:** guard-proxy scrub event; the two-act sanitize span in Datadog (PRD 22).
- **Round:** leaks in R1; output scrub toggle in R2 (`/toggle?output=on`); full in R3.
- **Per-cloud delta:** the control is cloud-neutral (proxy sits in front of any
  model). **GCP** is where "I blocked egress" and "I blocked the leak" separate:
  egress to `restricted.googleapis.com` is required for the model, so egress control
  cannot be the leak enforcement point; the proxy must be. This is the strongest GCP
  teaching beat.

### C6 - Prompt injection / PII on input

- **Peg:** ASI01 (Agent Goal Hijack). ATLAS Prompt Injection (AML.T0051).
- **Agent tries:** injected instruction or PII in the input.
- **Control:** guard-proxy input blocklist (0 tokens), then input classifier.
- **Signal:** guard-proxy input-block event; classifier decision in Datadog.
- **Round:** unfiltered in R1; blocklist in R2 (`/toggle?input_blocklist=on`);
  classifier in R3 (`/toggle?input_classifier=on`).
- **Per-cloud delta:** cloud-neutral. The cost ladder (blocklist cheapest, classifier
  next) is model-priced per cloud but the control order is the same.

### C7 - Poisoned MCP tool call

- **Peg:** ASI02 (Tool Misuse), ASI04 (Supply Chain). ATLAS Publish a Poisoned AI
  Agent Tool (AML.T0011.002).
- **Agent tries:** call a rogue MCP tool that exfiltrates (sentinel
  `FAKE-MCP-EXFIL-sentinel-4c1d`).
- **Control:** kagent `toolNames` allowlist; evil-mcp-shim stays dark unless armed.
- **Signal:** the `execute_tool` / `gen_ai.tool.name` span chain in Datadog (PRD 22
  Beat 3).
- **Round:** rogue tool callable in R1; `toolNames` allowlist in R2/R3.
- **Per-cloud delta:** cloud-neutral; kagent tool scoping is above the cloud layer.
  The model differs (Claude/GPT/Gemini) but the tool-allowlist control and the span
  signal are identical.

### Obs - Re-leak into the trace

- **Peg:** ASI06 (Memory and Context Poisoning), read as observability-plane leak.
  ATLAS: telemetry as an exfil channel.
- **Agent tries:** nothing new; the leak is that a sanitized value reappears in the
  trace because instrumentation captured raw content.
- **Control:** OTel Collector OTTL `transform/redact_sentinel`; content capture OFF
  (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`).
- **Signal:** the before/after INTERNAL sanitize span (PRD 22 Beat 1); redaction
  visible in the collector pipeline.
- **Round:** trap demonstrated in R3 as the observability lens beat.
- **Per-cloud delta:** cloud-neutral; the collector pipeline is the same on every
  cloud. The model provider attribute differs in the span, the redaction does not.

## 6. Cost ladder (unchanged, restated for completeness)

The controls that reject cheapest-first, from STACK-MAP §4:

input blocklist (0 tokens) < input classifier < tool scoping < output inspection <
Kyverno admission.

This ordering is model-priced per cloud (Bedrock/Azure OpenAI/Vertex token costs
differ), but the ladder order does not change per cloud. It is why input controls
(C6) come before output controls (C5) in the round arc.

## 7. What this PRD contracts

Nothing to build until PRD 35 is approved and its overlays land. This PRD's
deliverables are documentation and an acceptance checklist:

1. This matrix becomes the per-cloud acceptance checklist for PRD 35 overlay
   validation: each beat's "control fires / signal appears" is a render-gate or
   live-cluster assertion the overlay must satisfy on its cloud.
2. `walkthrough-agenticburn/STACK-MAP.md` §4 points at this matrix as the source of
   truth instead of carrying an AWS-only table, and gains a per-cloud column or a
   pointer to §4/§5 here.
3. The Azure C1' beat and the GCP C5/C1 egress-collision beat are added to the
   run-of-show as the cloud-specific highlights when a run is delivered on that cloud.

## 8. Open questions (for Michael)

1. **GCP egress separation:** confirm whether the workshop will provision VPC-SC (org
   level) to actually separate Vertex from GCS, or whether the GCP story deliberately
   leaves the naive NetworkPolicy failing as the teaching point and stops there. This
   ties to PRD 35 §6 risk 1, which is still OPEN pending your answer.
2. **Taxonomy on slides:** peg beats to OWASP ASI only on attendee-facing slides, or
   show the MITRE ATLAS technique IDs alongside? ASI is cleaner for a 60-minute
   format; ATLAS IDs add rigor for a security audience.
3. **C1' scope:** is the Azure static-key steal a full demonstrated beat with a
   response, or a talked-through highlight? Building the live version needs an Azure
   cluster, which is out of scope for the code-only PRD 35 pass.
